#!/usr/bin/env bash
# Create the hourly rollup task in InfluxDB 2.x (idempotent: removes an old one).
set -euo pipefail
cd "$(dirname "$0")/.."
[ -f .env ] && set -a && . ./.env && set +a

INFLUX_URL="${INFLUX_URL:-http://localhost:8086}"
INFRA_URL="${INFLUX_URL/influxdb/localhost}"   # running from the host, not in the stack
FLUX=$(cat influxdb/tasks/downsample_1h.flux)

existing=$(curl -s -H "Authorization: Token ${INFLUX_TOKEN}" "$INFRA_URL/api/v2/tasks?org=${INFLUX_ORG}" \
  | grep -o "\"id\":\"[^\"]*\",\"name\":\"downsample_1h\"" | cut -d'"' -f4 || true)
if [ -n "$existing" ]; then
  curl -s -X DELETE -H "Authorization: Token ${INFLUX_TOKEN}" "$INFRA_URL/api/v2/tasks/$existing"
  echo "removed old task $existing"
fi

python3 - "$FLUX" <<'PY' > /tmp/task.json
import json, sys
print(json.dumps({"query": sys.argv[1], "status": "active",
                  "org": __import__("os").environ.get("INFLUX_ORG", "solar")}))
PY
curl -s -X POST -H "Authorization: Token ${INFLUX_TOKEN}" -H 'Content-Type: application/json' \
  -d @/tmp/task.json "$INFRA_URL/api/v2/tasks" | head -c 400
echo
