#!/usr/bin/env bash
# Установка ПОЛНОГО стека solar-monitor (collector + InfluxDB 2.x + Grafana) на
# Orange Pi 3 LTS (Allwinner H6, aarch64, 2 ГБ). Проверено на Armbian bookworm.
#
#   sudo bash bootstrap.sh                                  # транспорт из .env (tcp)
#   sudo bash bootstrap.sh --transport serial               # USB-RS232 к инвертору
#   sudo bash bootstrap.sh --transport tcp --tcp-host 10.0.0.5
#   sudo bash bootstrap.sh --site office --transport serial --auth --random-password
#
# Всё, что делает скрипт: ставит Docker + compose v2, zram (если swap нет),
# клонирует репозиторий в /opt/solar-monitor и запускает tools/deploy.sh,
# который сам генерирует секреты в .env и поднимает три контейнера.
# Повторный запуск безопасен: .env и data/ не перезаписываются, код обновляется.
set -euo pipefail

REPO_URL="${REPO_URL:-https://github.com/gerkules/solar-monitor}"
DIR="${DIR:-/opt/solar-monitor}"
WEB_PORT="${WEB_PORT:-8080}"
GRAFANA_LAN_PORT="${GRAFANA_LAN_PORT:-3001}"

ok()   { printf '\033[32m✓ %s\033[0m\n' "$*"; }
info() { printf '\033[36m· %s\033[0m\n' "$*"; }
die()  { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }

[ "$(id -u)" -eq 0 ] || die "запусти через sudo: sudo bash $0 $*"

# ---------------------------------------------------------------- проверки платы
ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ok "архитектура $ARCH — образы стека есть в arm64" ;;
  *) info "архитектура $ARCH: продолжаю, но полный стек собирался под aarch64/x86_64" ;;
esac
[ -f /etc/debian_version ] || info "не Debian/Ubuntu — apt-шаги могут не сработать"

FREE_GB="$(df -BG --output=avail / | tail -1 | tr -dc '0-9')"
info "свободно на /: ${FREE_GB} ГБ"
[ "${FREE_GB:-0}" -lt 8 ] && info "мало места: InfluxDB+Grafana+история просят 8 ГБ+ (карта 16–32 ГБ A1)"

# ---------------------------------------------------------------- пакеты
info "ставлю базовые пакеты"
apt-get update -qq
DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
  git curl ca-certificates jq openssl >/dev/null
ok "git/curl/jq/openssl есть"

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
    info "zram-tools недоступен — пропускаю (можно добавить swap-файл 1 ГБ вручную)"
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

# ---------------------------------------------------------------- запуск стека
info "запускаю tools/deploy.sh $*"
cd "$DIR"
./tools/deploy.sh "$@"

# ---------------------------------------------------------------- итоги
IP="$(hostname -I 2>/dev/null | awk '{print $1}')"
echo
ok "готово. Открывать:"
printf '  панель   : http://%s:%s/          (admin/admin — смени в Настройки → Доступ)\n' "$IP" "$WEB_PORT"
printf '  grafana  : http://%s:%s/          (только если поднимал с -f deploy/orangepi/docker-compose.orangepi.yml)\n' "$IP" "$GRAFANA_LAN_PORT"
printf '  health   : http://%s:%s/healthz\n' "$IP" "$WEB_PORT"
printf '  состояние: curl -s localhost:%s/api/v1/state | jq .device_mode\n' "$WEB_PORT"
echo
info "дальше — в UI: Настройки → Подключение (кабель/донгл) и кнопка «Проверить связь»"
info "логи: cd $DIR && docker compose logs -f collector"
info "Grafana-пароль и токен Influx: grep -E 'GRAFANA_PASSWORD|INFLUX_TOKEN' $DIR/.env"
