#!/bin/bash
# Watchdog узла solar-monitor: перезапуск коллектора, если данные зависли или API не отвечает.
set -u
API="${API:-http://127.0.0.1:8080/healthz}"
MAX_AGE="${MAX_AGE:-180}"      # сек без свежих данных
MAX_FAILS="${MAX_FAILS:-60}"   # подряд неудачных опросов
COOLDOWN="${COOLDOWN:-600}"    # сек между авто-рестартами
WARMUP="${WARMUP:-90}"         # после старта сервиса не трогаем его столько секунд
STAMP=/run/solar-watchdog.last
TAG=solar-watchdog

restart() {
    local why="$1" now last=0
    now=$(date +%s)
    [ -f "$STAMP" ] && last=$(cat "$STAMP" 2>/dev/null || echo 0)
    case "$last" in ""|*[!0-9]*) last=0 ;; esac
    if [ $((now - last)) -lt "$COOLDOWN" ]; then
        logger -t "$TAG" "нужен рестарт ($why), но кулдаун: ещё $((COOLDOWN - now + last)) c"
        return 0
    fi
    logger -t "$TAG" "РЕСТАРТ solar-collector: $why"
    mosquitto_pub -h 127.0.0.1 -t solar/pi/watchdog -m "restart: $why" 2>/dev/null || true
    systemctl restart solar-collector
    echo "$now" > "$STAMP"
}

pid=$(systemctl show -p MainPID --value solar-collector 2>/dev/null)
etimes=$(ps -o etimes= -p "${pid:-0}" 2>/dev/null | tr -d " ")
[ -e /dev/voltronic-inverter ] || logger -t "$TAG" "нет /dev/voltronic-inverter (USB-инвертор отвалился)"

# Важно: /healthz отдаёт 503, когда данные просто «не свежие» (одна помеха на
# USB-шине). Это не повод перезапускать коллектор, поэтому НЕ используем `curl -f`:
# смотрим код ответа — 000 значит «сервер не ответил», любой HTTP-код = жив.
body=""
code="000"
for _ in 1 2 3; do
    code=$(curl -s -m 12 -o /tmp/solar-health.json -w '%{http_code}' "$API" 2>/dev/null || echo 000)
    body=$(cat /tmp/solar-health.json 2>/dev/null)
    [ "$code" != "000" ] && [ -n "${body:-}" ] && break
    body=""
    sleep 5
done

if [ "$code" = "000" ] || [ -z "${body:-}" ]; then
    if [ "${etimes:-0}" -lt "$WARMUP" ]; then
        logger -t "$TAG" "API не отвечает, но сервис стартовал ${etimes}s назад — ждём"
        exit 0
    fi
    restart "API /healthz не отвечает"
    exit 0
fi

vals=$(printf %s "$body" | python3 -c "
import json,sys
d=json.load(sys.stdin)
print(int(bool(d.get(\"online\"))), int(d.get(\"age_s\") or 0), int(d.get(\"consecutive_failures\") or 0), int(bool(d.get(\"mqtt_connected\"))))
" 2>/dev/null)
if [ -z "${vals:-}" ]; then logger -t "$TAG" "не разобрал healthz: $body"; exit 1; fi
set -- $vals; online=$1; age=$2; fails=$3; mqttc=$4

if [ "$age" -gt "$MAX_AGE" ]; then restart "данные устарели: age=${age}s"; exit 0; fi
if [ "$fails" -gt "$MAX_FAILS" ]; then restart "подряд неудач: $fails"; exit 0; fi
logger -t "$TAG" "ok: online=$online age=${age}s fails=$fails mqtt=$mqttc"
