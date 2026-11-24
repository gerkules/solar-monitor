#!/data/data/com.termux/files/usr/bin/sh
# Вариант boot-скрипта для автономного комплекта (без внешнего брокера):
# поднимает локальный mosquitto, затем коллектор в proot-Debian.
#
# Установка:
#   pkg install -y mosquitto          # ВАЖНО: пакета mosquitto-clients в Termux НЕТ
#   adb push 41-termux-boot-with-broker.sh /sdcard/start-collector.sh
#   mkdir -p ~/.termux/boot && cp /sdcard/start-collector.sh ~/.termux/boot/ \
#     && chmod +x ~/.termux/boot/start-collector.sh
#
# mosquitto на телефоне проверен: version 2.1.4, publish/subscribe через 127.0.0.1 работают.

termux-wake-lock
export PROOT_NO_SECCOMP=1
LOG=/sdcard/collector.log
BROKER_CONF=$HOME/mosquitto/mosquitto.conf

# --- локальный брокер -------------------------------------------------------
if ! pgrep -f "mosquitto -c" > /dev/null 2>&1; then
  mkdir -p "$HOME/mosquitto"
  # allow_anonymous true — только если брокер не смотрит в LAN.
  # Для доступа с других устройств: listener 1883 + allow_anonymous false +
  # password_file и пользователь, созданный mosquitto_passwd (в Debian).
  [ -f "$BROKER_CONF" ] || printf 'listener 127.0.0.1\nallow_anonymous true\npersistence false\n' > "$BROKER_CONF"
  nohup mosquitto -c "$BROKER_CONF" >> "$HOME/mosquitto/mosquitto.log" 2>&1 &
  sleep 2
fi

# --- коллектор --------------------------------------------------------------
while true; do
  echo "=== start $(date)" >> "$LOG"
  proot-distro login debian -- bash /root/start-collector.sh >> "$LOG" 2>&1
  echo "=== collector exited rc=$? $(date), restart in 10s" >> "$LOG"
  sleep 10
done
