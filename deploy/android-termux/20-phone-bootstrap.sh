#!/data/data/com.termux/files/usr/bin/sh
# Запускать ВНУТРИ Termux на телефоне. Ставит proot-distro + Debian + venv.
# Логи пишет в /sdcard/bootstrap.log (adb shell "tr '\r' '\n' < /sdcard/bootstrap.log").
#
# Перед запуском (Mac): adb push collector /sdcard/collector
# После запуска:        proot-distro login debian -- bash -c 'mkdir -p /root/solar-monitor \
#                         && cp -r /sdcard/collector /root/solar-monitor/collector \
#                         && cd /root/solar-monitor/collector \
#                         && /root/venv/bin/pip install -q -r requirements.txt'
exec > /sdcard/bootstrap.log 2>&1
set -x

export DEBIAN_FRONTEND=noninteractive
termux-wake-lock

yes | pkg update -y
yes | pkg upgrade -y
pkg install -y proot-distro python git openssh nano

proot-distro install debian

# DNS внутри rootfs — до первого apt/pip, иначе "Temporary failure in name resolution"
RF=$PREFIX/var/lib/proot-distro/installed-rootfs/debian
printf 'nameserver 192.168.31.1\nnameserver 1.1.1.1\nnameserver 8.8.8.8\n' > "$RF/etc/resolv.conf"

# PROOT_NO_SECCOMP=1 обязателен на 32-бит ARM (иначе assertion IS_IN_SYSENTER)
export PROOT_NO_SECCOMP=1
proot-distro login debian -- bash -c '
set -x
export DEBIAN_FRONTEND=noninteractive
uname -m; cat /etc/debian_version
apt-get update -qq
apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip ca-certificates
python3 -V
python3 -m venv /root/venv
/root/venv/bin/pip install -q --upgrade pip wheel
mkdir -p /root/solar-monitor
rm -rf /root/solar-monitor/collector
cp -r /sdcard/collector /root/solar-monitor/collector
cd /root/solar-monitor/collector
/root/venv/bin/pip install -q --timeout 120 --retries 8 -r requirements.txt
/root/venv/bin/python -c "import fastapi, uvicorn, paho.mqtt.client, serial; print(\"IMPORTS OK\")"
'
echo "=== DONE"
