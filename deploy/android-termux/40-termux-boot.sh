#!/data/data/com.termux/files/usr/bin/sh
# Кладётся в Termux: ~/.termux/boot/start-collector.sh  (chmod +x)
# Требует приложение Termux:Boot (иначе Android не запустит скрипт после ребута).
#
# adb push 40-termux-boot.sh /sdcard/start-collector.sh
# в Termux:  mkdir -p ~/.termux/boot && cp /sdcard/start-collector.sh ~/.termux/boot/ \
#            && chmod +x ~/.termux/boot/start-collector.sh
#
# Проверка: adb reboot; через 2 минуты `tail /sdcard/collector.log` → свежий "=== start".

termux-wake-lock
export PROOT_NO_SECCOMP=1          # иначе proot умирает на 32-бит ARM
LOG=/sdcard/collector.log

while true; do
  echo "=== start $(date)" >> "$LOG"
  proot-distro login debian -- bash /root/start-collector.sh >> "$LOG" 2>&1
  echo "=== collector exited rc=$? $(date), restart in 10s" >> "$LOG"
  sleep 10
done
