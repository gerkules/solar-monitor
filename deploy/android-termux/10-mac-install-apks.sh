#!/bin/bash
# Выполняется НА МАКЕ (не на телефоне). Скачивает и ставит APK на подключённый телефон,
# затем включает нужные настройки Android.
#
# Использование:  ./10-mac-install-apks.sh [arm64-v8a|armeabi-v7a] [firefox|no]
set -euo pipefail

ABI=${1:-armeabi-v7a}
BROWSER=${2:-firefox}
ADB=${ADB:-$HOME/Library/Android/sdk/platform-tools/adb}
TMP=${TMPDIR:-/tmp}/solar-android.apks
mkdir -p "$TMP"

case "$ABI" in
  arm64-v8a)   TERMUX_SUFFIX=arm64-v8a ;;
  armeabi-v7a) TERMUX_SUFFIX=armeabi-v7a ;;
  *) echo "ABI: arm64-v8a | armeabi-v7a"; exit 1 ;;
esac

echo "== 1. Termux 0.118.3 ($TERMUX_SUFFIX)"
curl -fL -o "$TMP/termux.apk" \
  "https://github.com/termux/termux-app/releases/download/v0.118.3/termux-app_v0.118.3%2Bgithub-debug_${TERMUX_SUFFIX}.apk"

echo "== 2. Termux:Boot 0.8.1 (универсальный)"
curl -fL -o "$TMP/termux-boot.apk" \
  "https://github.com/termux/termux-boot/releases/download/v0.8.1/termux-boot-app_v0.8.1%2Bgithub.debug.apk"

echo "== Устройство:"
"$ADB" devices -l
"$ADB" shell getprop ro.product.model ro.build.version.sdk ro.product.cpu.abilist

echo "== Установка (-g = сразу выдать runtime-разрешения)"
"$ADB" install -r -g "$TMP/termux.apk"
"$ADB" install -r -g "$TMP/termux-boot.apk"

# Firefox 119 — последняя ветка, которая ещё ставится на Android 7 и умеет ?. и ...
if [ "$BROWSER" = firefox ]; then
  echo "== 3. Firefox 119 (armeabi-v7a, minSdk 21)"
  curl -fL -o "$TMP/firefox119.apk" \
    "https://archive.mozilla.org/pub/fenix/releases/119.0/android/fenix-119.0-android-armeabi-v7a/fenix-119.0.multi.android-armeabi-v7a.apk"
  "$ADB" install -r "$TMP/firefox119.apk" || echo "!! Firefox не встал — проверь minSdk/ABI"
fi

echo "== 4. Настройки Android под 24/7 работу"
"$ADB" shell dumpsys deviceidle whitelist +com.termux
"$ADB" shell settings put global wifi_sleep_policy 2
"$ADB" shell settings put global stay_on_while_plugged_in 7

echo "== 5. Мусорные приложения (освобождает ~80 МБ на 1.37 ГБ):"
for p in com.microsoft.skydrive de.axelspringer.yana.zeropage \
         com.google.android.youtube com.google.android.apps.maps com.google.android.gm; do
  "$ADB" shell pm disable-user --user 0 "$p" || true
done

cat <<TXT

Готово. Дальше:
  1. На телефоне: Настройки → О телефоне → Сведения о ПО → «Номер сборки» ×7,
     включить «Отладка по USB», «Выбор конфигурации USB» = MTP, подтвердить RSA.
  2. Открыть Termux (скачает bootstrap) и выполнить 20-phone-bootstrap.sh.
TXT
