#!/bin/bash
# Кладётся в rootfs: /root/start-collector.sh  (ВНУТРИ Debian, не в Termux!)
# ВАЖНО: копировать через /sdcard изнутри proot — файлы, записанные со стороны
# Termux напрямую в rootfs, внутри proot могут быть не видны.
#
# adb push 30-start-collector.sh /sdcard/start-collector.sh
# PROOT_NO_SECCOMP=1 proot-distro login debian -- bash -c '
#   cp /sdcard/start-collector.sh /root/start-collector.sh && chmod +x /root/start-collector.sh'
#
# Пароли НЕ хранить в git: взять из ~/inverter-mqtt/.env и подставить на телефоне.

cd /root/solar-monitor/collector || exit 1

export SITE=phone
export MQTT_PREFIX=solar/phone
export MQTT_HOST=192.168.1.224        # брокер на NAS (второй NIC; .31.224 не отвечает)
export MQTT_PORT=1883
export MQTT_USER=CHANGE_ME            # из ~/inverter-mqtt/.env
export MQTT_PASS=CHANGE_ME

# Транспорт: tcp через проброс роутера к донглу EW10.
# Локальный 192.168.31.110:9999 занят (донгл держит одно соединение) → refused.
export TRANSPORT=tcp
export TCP_HOST=192.168.1.222
export TCP_PORT=9999

export WEBAPP=true
export API_PORT=8080
export POLL_INTERVAL=10
# export AUTH_PASSWORD=...            # обязательно для боевого использования

exec /root/venv/bin/python -m solar_monitor.main
