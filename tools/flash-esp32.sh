#!/usr/bin/env bash
# Прошивка ESP32 / ESP32-C3 прошивкой solar-monitor.
#
#   ./tools/flash-esp32.sh --port /dev/tty.usbserial-0001 --chip esp32c3
#   ./tools/flash-esp32.sh --port COM5 --chip esp32
#   ./tools/flash-esp32.sh --port /dev/tty.usbserial-0001 --chip esp32c3 --files-only
#
# Что делает: ставит esptool+mpremote в .venv-esp, скачивает MicroPython для чипа,
# стирает flash, заливает MicroPython и файлы прошивки. config.json НЕ перезаписывает,
# если он уже есть на устройстве (чтобы не потерять Wi-Fi/пароли).
set -euo pipefail
cd "$(dirname "$0")/.."

PORT=""
CHIP="esp32c3"
FILES_ONLY=0
MICROPYTHON_VERSION="20240602-v1.23.0"

while [ $# -gt 0 ]; do
  case "$1" in
    --port) PORT="$2"; shift 2 ;;
    --chip) CHIP="$2"; shift 2 ;;
    --files-only) FILES_ONLY=1; shift ;;
    --version) MICROPYTHON_VERSION="$2"; shift 2 ;;
    -h|--help) sed -n '2,12p' "$0"; exit 0 ;;
    *) echo "неизвестный аргумент: $1" >&2; exit 2 ;;
  esac
done

[ -n "$PORT" ] || { echo "нужен --port (см. ls /dev/tty.usbserial-* или ls /dev/ttyUSB*)" >&2; exit 2; }

case "$CHIP" in
  # у классического ESP32 образ MicroPython кладётся на 0x1000,
  # у C3/S3 — на 0x0 (иначе плата уходит в цикл "invalid header")
  esp32)     BIN_NAME="ESP32_GENERIC";    FLASH_ADDR="0x1000" ;;
  esp32c3)   BIN_NAME="ESP32_GENERIC_C3"; FLASH_ADDR="0x0" ;;
  esp32s3)   BIN_NAME="ESP32_GENERIC_S3"; FLASH_ADDR="0x0" ;;
  *) echo "поддерживаются esp32, esp32c3, esp32s3" >&2; exit 2 ;;
esac

FW="firmware/esp32"
VENV=".venv-esp"

echo "==> окружение ($VENV)"
python3 -m venv "$VENV"
. "$VENV/bin/activate"
pip install --quiet --upgrade pip esptool mpremote

if [ "$FILES_ONLY" = "0" ]; then
  BIN="${BIN_NAME}-${MICROPYTHON_VERSION}.bin"
  if [ ! -f "$BIN" ]; then
    echo "==> скачиваю MicroPython $BIN"
    curl -fL -o "$BIN" "https://micropython.org/resources/firmware/$BIN"
  fi
  echo "==> стираю flash и заливаю MicroPython (это ~30 секунд)"
  esptool.py --chip "$CHIP" --port "$PORT" erase_flash
  esptool.py --chip "$CHIP" --port "$PORT" --baud 460800 write_flash -z "$FLASH_ADDR" "$BIN"
  sleep 2
fi

echo "==> файлы прошивки"
pushd "$FW" >/dev/null
mp() { mpremote connect "$PORT" "$@"; }
mp fs mkdir :vendor 2>/dev/null || true
mp fs mkdir :www 2>/dev/null || true
mp fs cp vendor/umqtt/simple.py :vendor/simple.py
mp fs cp main.py bus.py pi30.py poller.py sethandler.py history.py mqttpub.py web.py :/
mp fs cp www/index.html :www/index.html
if mp fs cat :config.json >/dev/null 2>&1; then
  echo "    config.json уже есть на устройстве — не трогаю"
else
  mp fs cp config.example.json :config.json
  echo "    залит config.json из config.example.json — впиши Wi-Fi и MQTT"
fi
popd >/dev/null

echo "==> перезагрузка"
mpremote connect "$PORT" reset || true

cat <<EOF

Готово. Дальше:
  1. посмотреть вывод платы:      cd $FW && mpremote connect $PORT repl
  2. поправить конфиг:            mpremote connect $PORT fs cat :config.json
  3. открыть интерфейс:           http://<ip-esp32>/   (admin/admin)

Если Wi-Fi не подключился — правьте config.json через mpremote (файл на устройстве),
либо перезалейте: mpremote connect $PORT fs cp config.json :config.json
EOF
