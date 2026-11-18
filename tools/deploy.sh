#!/usr/bin/env bash
# Развёртывание solar-monitor на чистой машине (VDS, mini PC, NAS).
#
#   ./tools/deploy.sh                                  # интерактивно всё по умолчанию
#   ./tools/deploy.sh --site home --transport tcp --tcp-host 192.168.1.60
#   ./tools/deploy.sh --dir /opt/solar-monitor --no-build
#
# Скрипт: проверяет Docker, создаёт .env с сгенерированными секретами (если файла нет),
# готовит каталоги данных, собирает и поднимает стек, ждёт health и печатает адреса.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

SITE=""
TRANSPORT=""
TCP_HOST=""
TCP_PORT=""
MQTT_HOST=""
NO_BUILD=0
NO_START=0
OFFICE=0
WITH_AUTH=0
WITH_TLS=0

die() { printf '\033[31m✗ %s\033[0m\n' "$*" >&2; exit 1; }
ok()  { printf '\033[32m✓ %s\033[0m\n' "$*"; }
info(){ printf '\033[36m· %s\033[0m\n' "$*"; }

while [ $# -gt 0 ]; do
  case "$1" in
    --site) SITE="${2:?}"; shift 2 ;;
    --transport) TRANSPORT="${2:?}"; shift 2 ;;
    --tcp-host) TCP_HOST="${2:?}"; shift 2 ;;
    --tcp-port) TCP_PORT="${2:?}"; shift 2 ;;
    --mqtt-host) MQTT_HOST="${2:?}"; shift 2 ;;
    --office) OFFICE=1; shift ;;
    --auth) WITH_AUTH=1; shift ;;
    --tls) WITH_TLS=1; shift ;;
    --no-build) NO_BUILD=1; shift ;;
    --no-start) NO_START=1; shift ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) die "неизвестный аргумент: $1" ;;
  esac
done

# ---------------------------------------------------------------- проверки
command -v docker >/dev/null || die "docker не установлен (https://docs.docker.com/engine/install/)"
docker compose version >/dev/null 2>&1 || die "нужен Docker Compose v2 (docker compose …)"
docker info >/dev/null 2>&1 || die "нет доступа к docker daemon (запустите от root или добавьте пользователя в группу docker)"
ok "docker $(docker version --format '{{.Server.Version}}'), compose $(docker compose version --short)"

rand() { openssl rand -hex "${1:-16}" 2>/dev/null || head -c "${1:-16}" /dev/urandom | od -An -tx1 | tr -d ' \n'; }

# ---------------------------------------------------------------- .env
ENV_FILE="$ROOT/.env"
if [ ! -f "$ENV_FILE" ]; then
  info "создаю .env из .env.example со случайными секретами"
  cp .env.example .env
  INFLUX_TOKEN="$(rand 24)"
  INFLUX_PASSWORD="$(rand 12)"
  GRAFANA_PASSWORD="$(rand 8)"
  case "$(uname -s)" in
    Darwin) sedi() { sed -i '' "$@"; } ;;
    *)      sedi() { sed -i "$@"; } ;;
  esac
  sedi "s|^INFLUX_TOKEN=.*|INFLUX_TOKEN=$INFLUX_TOKEN|" .env
  sedi "s|^INFLUX_PASSWORD=.*|INFLUX_PASSWORD=$INFLUX_PASSWORD|" .env
  sedi "s|^GRAFANA_PASSWORD=.*|GRAFANA_PASSWORD=$GRAFANA_PASSWORD|" .env
  chmod 600 .env
  ok "секреты сгенерированы и записаны в .env (Grafana: admin / $GRAFANA_PASSWORD)"
else
  info ".env уже существует — использую его"
fi

set_env() {  # set_env KEY VALUE — заменить или добавить строку
  local key="$1" value="$2"
  case "$(uname -s)" in
    Darwin) sed -i '' "/^${key}=/d" .env; printf '%s=%s\n' "$key" "$value" >> .env ;;
    *)      sed -i "/^${key}=/d" .env; printf '%s=%s\n' "$key" "$value" >> .env ;;
  esac
}

[ -n "$SITE" ] && { set_env SITE "$SITE"; ok "SITE=$SITE"; }
[ -n "$TRANSPORT" ] && { set_env TRANSPORT "$TRANSPORT"; ok "TRANSPORT=$TRANSPORT"; }
[ -n "$TCP_HOST" ] && { set_env TCP_HOST "$TCP_HOST"; ok "TCP_HOST=$TCP_HOST"; }
[ -n "$TCP_PORT" ] && { set_env TCP_PORT "$TCP_PORT"; ok "TCP_PORT=$TCP_PORT"; }
[ -n "$MQTT_HOST" ] && { set_env MQTT_HOST "$MQTT_HOST"; ok "MQTT_HOST=$MQTT_HOST"; }

# ---------------------------------------------------------------- авторизация и TLS
if [ "$WITH_AUTH" = "1" ]; then
  AUTH_PASS="$(rand 8)"
  set_env AUTH_USER admin
  set_env AUTH_PASSWORD "$AUTH_PASS"
  ok "включена HTTP Basic авторизация: admin / $AUTH_PASS"
  info "если сайтов несколько — задайте ОДИНАКОВЫЕ AUTH_USER/AUTH_PASSWORD в каждом .env"
  info "либо укажите креды пира: PEER_SITES={\"office\":{\"url\":\"https://…\",\"user\":\"admin\",\"pass\":\"…\"}}"
fi

if [ "$WITH_TLS" = "1" ]; then
  ./tools/gen-cert.sh "$(hostname)" >/dev/null 2>&1 || true
  if [ -f data/certs/server.crt ]; then
    set_env TLS_CERT /certs/server.crt
    set_env TLS_KEY /certs/server.key
    ok "включён HTTPS (data/certs/server.crt, самоподписанный)"
    info "браузер покажет предупреждение о сертификате — это ожидаемо"
    info "healthcheck понимает и http, и https"
  else
    info "openssl недоступен — сертификат не создан, пропускаю TLS"
  fi
fi

# ---------------------------------------------------------------- данные
info "готовлю каталоги данных"
mkdir -p data/influxdb data/influxdb-config data/grafana data/collector
# Grafana в контейнере работает от uid 472 — иначе crash-loop
if [ "$(id -u)" = "0" ]; then
  chown -R 472:472 data/grafana 2>/dev/null || true
else
  info "если Grafana будет в crash-loop: sudo chown -R 472:472 $ROOT/data/grafana"
fi

# ---------------------------------------------------------------- запуск
COMPOSE_FILES=(-f docker-compose.yml)
if [ "$OFFICE" = "1" ]; then
  [ -f .env.office ] || { cp .env.office.example .env.office; ok "создан .env.office (проверьте SITE и транспорт)"; }
  COMPOSE_FILES+=(-f docker-compose.office.yml)
fi

if [ "$NO_START" = "1" ]; then
  ok "подготовка завершена (запуск пропущен: --no-start)"
  exit 0
fi

if [ "$NO_BUILD" = "1" ]; then
  docker compose "${COMPOSE_FILES[@]}" up -d
else
  docker compose "${COMPOSE_FILES[@]}" up -d --build
fi
ok "контейнеры запущены"

# ---------------------------------------------------------------- health
API_PORT="$(grep -E '^API_HOST_PORT=' .env | cut -d= -f2)"
API_PORT="${API_PORT:-8080}"
GRAFANA_PORT="$(grep -E '^GRAFANA_PORT=' .env | cut -d= -f2)"
GRAFANA_PORT="${GRAFANA_PORT:-3000}"

info "жду /healthz (до 90 с)"
for i in $(seq 1 45); do
  if curl -fsS "http://127.0.0.1:${API_PORT}/healthz" >/tmp/health.json 2>/dev/null; then
    ok "коллектор отвечает"; break
  fi
  sleep 2
  [ "$i" = "45" ] && die "коллектор не поднялся: docker compose logs collector"
done

echo
ok "готово"
printf '  UI + API : http://%s:%s/\n' "$(hostname -I 2>/dev/null | awk '{print $1}' || echo localhost)" "$API_PORT"
printf '  health   : http://127.0.0.1:%s/healthz\n' "$API_PORT"
printf '  Grafana  : http://127.0.0.1:%s/ (см. GRAFANA_PASSWORD в .env)\n' "$GRAFANA_PORT"
printf '  состояние: curl -s localhost:%s/api/v1/state | jq .device_mode\n' "$API_PORT"
echo
info "логи: docker compose logs -f collector"
info "подключение и уставки меняются в UI: Настройки → Подключение / Уставки"
