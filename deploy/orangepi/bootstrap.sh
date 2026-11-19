#!/usr/bin/env bash
# Установка ПОЛНОГО стека solar-monitor (collector + InfluxDB 2.x + Grafana) на
# Orange Pi 3 LTS (Allwinner H6, aarch64, 2 ГБ). Рассчитано на Armbian bookworm.
#
#   sudo bash bootstrap.sh                                  # транспорт из .env (tcp)
#   sudo bash bootstrap.sh --transport hid                  # нативный USB инвертора (SolarAssistant-style)
#   sudo bash bootstrap.sh --transport serial               # USB-RS232 / RS485 к инвертору
#   sudo bash bootstrap.sh --transport tcp --tcp-host 10.0.0.5
#   sudo bash bootstrap.sh --site office --transport hid --auth --random-password
#
# Что делает: ставит Docker + compose v2, zram (если swap нет), для hid — udev-правило
# со стабильным /dev/solar-inverter, клонирует репозиторий в /opt/solar-monitor,
# генерирует .env через tools/deploy.sh и поднимает контейнеры с нужным оверрайдом.
# Повторный запуск безопасен: .env и data/ не перезаписываются, код обновляется.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/gerkules/solar-monitor}"
DIR="${DIR:-/opt/solar-monitor}"
WEB_PORT="${WEB_PORT:-8080}"
GRAFANA_LAN_PORT="${GRAFANA_LAN_PORT:-3001}"
WITH_GRAFANA_LAN="${WITH_GRAFANA_LAN:-1}"

ARGS=("$@")
TRANSPORT=""
prev=""
for a in "$@"; do
  [ "$prev" = "--transport" ] && TRANSPORT="$a"
  prev="$a"
done

ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
info() { printf '\033[36m· %s\033[0m\n' "$*"; }
warn() { printf '\033[33m! %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запусти через sudo: sudo bash $0 $*"

# ---------------------------------------------------------------- проверки платы
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ok "архитектура $ARCH — образы стека есть в arm64" ;;
  *) warn "архитектура $ARCH: полный стек собирался под aarch64/x86_64" ;;
esac
[ -f /etc/debian_version ] || warn "не Debian/Ubuntu — apt-шаги могут не сработать"

FREE_GB="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
info "свободно на /: ${FREE_GB} ГБ"
[ "${FREE_GB:-0}" -lt 8 ] && warn "мало места: InfluxDB+Grafana+история просят 8 ГБ+ (карта 16–32 ГБ A1)"

# ---------------------------------------------------------------- пакеты
info "ставлю базовые пакеты"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git curl ca-certificates jq openssl usbutils >/dev/null
ok "git/curl/jq/openssl/usbutils есть"

# ---------------------------------------------------------------- swap / zram
if swapon --show | grep -q .; then
  ok "swap уже есть: $(swapon --show --noheadings | awk '{print $1,$3}' | head -1)"
else
  info "swap нет — ставлю zram (важно для 2 ГБ RAM: Grafana+Influx любят память)"
  DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends zram-tools >/dev/null || true
  if [ -f /etc/default/zramswap ]; then
    sed -i 's/^#\?PERCENT=.*/PERCENT=100/' /etc/default/zramswap
    systemctl restart zramswap 2>/dev/null || true
    ok "zram включён ($(swapon --show --noheadings | awk '{print $1,$3}' | head -1 || echo 'после ребута'))"
  else
    warn "zram-tools недоступен — добавь swap-файл 1 ГБ вручную"
  fi
fi

# ---------------------------------------------------------------- docker
if command -v docker >/dev/null && docker compose version >/dev/null 2>&1; then
  ok "docker $(docker version --format '{{.Server.Version}}' 2>/dev/null || echo '—') уже установлен"
else
  info "ставлю Docker Engine + compose v2 (официальный скрипт, arm64 поддерживается)"
  curl -fsSL https://get.docker.com | sh
  ok "docker поставлен"
fi
systemctl enable --now docker >/dev/null 2>&1 || true
docker info >/dev/null 2>&1 || die "docker daemon не отвечает: systemctl status docker"

# ---------------------------------------------------------------- код
if [ -d "$DIR/.git" ]; then
  info "обновляю код в $DIR"
  git -C "$DIR" fetch --quiet origin && git -C "$DIR" reset --hard --quiet origin/main
else
  info "клонирую $REPO_URL → $DIR"
  mkdir -p "$(dirname "$DIR")"
  git clone --quiet --depth 1 "$REPO_URL" "$DIR"
fi
ok "код: $(git -C "$DIR" log --oneline -1)"

# ---------------------------------------------------------------- hidraw (нативный USB инвертора)
HID_PATH=""
if [ "$TRANSPORT" = "hid" ]; then
  info "нативный USB: ставлю udev-правило → /dev/solar-inverter"
  install -m 644 "$DIR/deploy/orangepi/99-solar-inverter-hid.rules" /etc/udev/rules.d/99-solar-inverter-hid.rules
  udevadm control --reload-rules
  udevadm trigger --subsystem-match=hidraw || true
  for _ in $(seq 1 15); do
    [ -e /dev/solar-inverter ] && break
    sleep 1
  done
  if [ -e /dev/solar-inverter ]; then
    HID_PATH=/dev/solar-inverter
    ok "инвертор найден: /dev/solar-inverter → $(readlink -f /dev/solar-inverter)"
  else
    warn "VID:PID 0665:5161 не найден. Что есть в системе:"
    lsusb | grep -iE "0665|voltr|axpert|must|inverter" || lsusb | tail -5 || true
    shopt -s nullglob
    NODES=(/dev/hidraw*)
    if [ "${#NODES[@]}" -eq 1 ]; then
      HID_PATH="${NODES[0]}"
      warn "беру единственный hidraw: $HID_PATH — поправь VID:PID в 99-solar-inverter-hid.rules"
    elif [ "${#NODES[@]}" -eq 0 ]; then
      warn "hidraw-узлов нет: кабель не воткнут/выключен инвертор. HID_DEVICE оставлю /dev/solar-inverter —"
      warn "после подключения: sudo udevadm trigger --subsystem-match=hidraw && docker compose restart collector"
      HID_PATH=/dev/solar-inverter
    else
      HID_PATH=/dev/solar-inverter
      warn "hidraw-узлов ${#NODES[@]} — не угадываю. Проверь lsusb и поправь udev-правило"
    fi
  fi
fi

# ---------------------------------------------------------------- .env + данные
cd "$DIR"
DEPLOY_ARGS=(--no-start "${ARGS[@]}")
[ -n "$HID_PATH" ] && DEPLOY_ARGS+=(--hid-device "$HID_PATH")

info "готовлю .env и каталоги: tools/deploy.sh ${DEPLOY_ARGS[*]}"
./tools/deploy.sh "${DEPLOY_ARGS[@]}"

# ---------------------------------------------------------------- compose-файлы
COMPOSE=(-f docker-compose.yml)
[ "$WITH_GRAFANA_LAN" = "1" ] && COMPOSE+=(-f deploy/orangepi/docker-compose.orangepi.yml)
case "$TRANSPORT" in
  hid)    [ -e "$HID_PATH" ] && COMPOSE+=(-f deploy/orangepi/docker-compose.hid.yml) ;;
  serial) COMPOSE+=(-f deploy/orangepi/docker-compose.serial.yml) ;;
esac

info "docker compose ${COMPOSE[*]} up -d --build"
docker compose "${COMPOSE[@]}" up -d --build
ok "контейнеры запущены"

# ---------------------------------------------------------------- health
info "жду /healthz (до 90 с)"
HEALTHY=0
for i in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${WEB_PORT}/healthz" >/dev/null 2>&1; then
    ok "коллектор отвечает"; HEALTHY=1; break
  fi
  sleep 2
done
[ "$HEALTHY" = "0" ] && warn "коллектор не ответил за 90 с: docker compose logs collector"

# ---------------------------------------------------------------- итоги
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "готово. Открывать:"
printf '  панель   : http://%s:%s/          (admin/admin — смени в Настройки → Доступ)\n' "$IP" "$WEB_PORT"
[ "$WITH_GRAFANA_LAN" = "1" ] && \
printf '  grafana  : http://%s:%s/          (пароль GRAFANA_PASSWORD в .env)\n' "$IP" "$GRAFANA_LAN_PORT"
printf '  health   : http://%s:%s/healthz\n' "$IP" "$WEB_PORT"
echo
case "$TRANSPORT" in
  hid)    info "транспорт hid, устройство: $HID_PATH (TRANSPORT/HID_DEVICE уже в .env)" ;;
  serial) info "транспорт serial — проверь SERIAL_PORT в .env (ls /dev/serial/by-id/)" ;;
  "")     info "транспорт не задан — возьмётся из .env (по умолчанию tcp)" ;;
esac
info "дальше — в UI: Настройки → Подключение → «Проверить связь» (АКБ/сеть/нагрузка/S-N)"
info "логи: cd $DIR && docker compose ${COMPOSE[*]} logs -f collector"
info "секреты: grep -E 'GRAFANA_PASSWORD|INFLUX_TOKEN' $DIR/.env"
