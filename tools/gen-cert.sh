#!/usr/bin/env bash
# Самоподписанный сертификат для HTTPS в контейнере коллектора.
#
#   ./tools/gen-cert.sh                       # CN и SAN по имени хоста
#   ./tools/gen-cert.sh solar.example 192.168.1.50
#
# Кладёт data/certs/server.crt и server.key (10 лет). Подключение в .env:
#   TLS_CERT=/certs/server.crt
#   TLS_KEY=/certs/server.key
set -euo pipefail
cd "$(dirname "$0")/.."

CN="${1:-$(hostname)}"
IP="${2:-}"
mkdir -p data/certs
OUT_CRT="data/certs/server.crt"
OUT_KEY="data/certs/server.key"

SAN="DNS:${CN}"
[ -n "$IP" ] && SAN="${SAN},IP:${IP}"

if [ -f "$OUT_CRT" ]; then
  echo "сертификат уже есть: $OUT_CRT (удалите, если нужен новый)"
  exit 0
fi

openssl req -x509 -nodes -newkey rsa:2048 -days 3650 \
  -keyout "$OUT_KEY" -out "$OUT_CRT" \
  -subj "/CN=${CN}" -addext "subjectAltName=${SAN}" 2>/dev/null

chmod 600 "$OUT_KEY"
echo "готово:"
echo "  $OUT_CRT"
echo "  $OUT_KEY"
echo
echo "в .env добавьте:"
echo "  TLS_CERT=/certs/server.crt"
echo "  TLS_KEY=/certs/server.key"
openssl x509 -in "$OUT_CRT" -noout -subject -dates -ext subjectAltName 2>/dev/null | sed 's/^/  /'
