#!/usr/bin/env bash
# Basic-пароль для Grafana за Caddy.
#
#   ./tools/set-grafana-proxy.sh 'мойПароль' [admin]
#
# Пишет ./data/caddy.env. Важно: Compose интерполирует env_file, поэтому каждый `$`
# в bcrypt-хэше экранируется как `$$` — иначе хэш обрезается до "$2a$14".
set -euo pipefail
cd "$(dirname "$0")/.."

PASS="${1:?использование: $0 <пароль> [пользователь]}"
USER="${2:-admin}"

mkdir -p data
HASH="$(docker run --rm caddy:2 caddy hash-password --plaintext "$PASS" 2>/dev/null | tail -1)"
[ -n "$HASH" ] || { echo "не удалось получить bcrypt-хэш (есть ли docker?)" >&2; exit 1; }

ESCAPED="${HASH//\$/\$\$}"
umask 077
printf 'GRAFANA_PROXY_USER=%s\nGRAFANA_PROXY_HASH=%s\n' "$USER" "$ESCAPED" > data/caddy.env
chmod 600 data/caddy.env

echo "готово: data/caddy.env (пользователь $USER, хэш ${#HASH} символов, \$ экранированы)"
echo "перезапустите прокси: docker compose up -d --force-recreate caddy"
