#!/usr/bin/env bash
# ============================================================
# solar-monitor collector — нативная установка на Raspberry Pi (ARMv6/v7)
# Без Docker: влезает в 512 МБ и работает на Pi 1 / Zero.
#
#   sudo bash deploy/pi/install-pi.sh
#
# После установки: отредактировать /opt/solar-monitor/.env (инвертор, MQTT),
# затем: sudo systemctl restart solar-collector
# ============================================================
set -e

SRC="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
DST=/opt/solar-monitor

export DEBIAN_FRONTEND=noninteractive
apt-get update -qq
apt-get install -y -qq python3-venv python3-pip

# группа dialout — доступ к /dev/ttyUSB* (USB-RS232/RS485) без root
id solar >/dev/null 2>&1 || useradd -r -s /usr/sbin/nologin solar
usermod -aG dialout solar

mkdir -p "$DST" /data
cp -r "$SRC/collector" "$DST/"
[ -f "$DST/.env" ] || cp "$SRC/deploy/pi/env.example" "$DST/.env"

python3 -m venv "$DST/venv"
# pydantic<2 обязателен: pydantic-core требует Rust и не собирается на ARMv6
"$DST/venv/bin/pip" install --no-cache-dir \
    "pydantic<2" "fastapi>=0.100" "uvicorn>=0.27" "paho-mqtt>=2.0,<3" "pyserial>=3.5,<4"

cp "$SRC/deploy/pi/solar-collector.service" /etc/systemd/system/

# Аутентификация UI включена с установки (заводские admin/admin): Pi не должен
# стартовать с открытой панелью. Пароль меняется в UI -> /data/auth.json.
if ! grep -q '^AUTH_USER=' "$DST/.env" 2>/dev/null; then
    printf 'AUTH_USER=admin\nAUTH_PASSWORD=admin\n' >> "$DST/.env"
    echo "      auth: включена, заводские admin/admin (сменить в UI)"
fi

# Wi-Fi helper: единственная привилегированная точка (scan/connect/forget).
# Коллектор работает под solar и не может менять сеть через polkit, поэтому —
# узкий helper + NOPASSWD только на него.
install -d -m 755 /usr/local/lib/solar-monitor
install -m 755 "$SRC/deploy/pi/wifi-helper" /usr/local/lib/solar-monitor/wifi-helper
printf 'solar ALL=(root) NOPASSWD: /usr/local/lib/solar-monitor/wifi-helper\n' \
    > /etc/sudoers.d/solar-wifi
chmod 440 /etc/sudoers.d/solar-wifi
visudo -cf /etc/sudoers.d/solar-wifi >/dev/null || {
    echo "ОШИБКА: /etc/sudoers.d/solar-wifi не прошёл проверку"; rm -f /etc/sudoers.d/solar-wifi; exit 1;
}

chown -R solar:solar "$DST" /data
systemctl daemon-reload
systemctl enable --now solar-collector

sleep 5
systemctl is-active solar-collector \
  && echo "UI: http://$(hostname -I | awk '{print $1}'):8080/"
echo
echo "USB-RS232: адаптер появится как /dev/ttyUSB0 (драйверы ch341/pl2303/ftdi/cp210x уже в ядре)."
echo "Проверка: ls -l /dev/serial/by-id/ ; затем в UI «Подключение» -> «Проверить связь»."
echo "Wi-Fi: страница «Wi-Fi» в UI (helper: /usr/local/lib/solar-monitor/wifi-helper)."
