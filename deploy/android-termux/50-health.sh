#!/data/data/com.termux/files/usr/bin/sh
# Быстрая проверка узла. Запускать в Termux:
#   adb push 50-health.sh /sdcard/health.sh && adb shell input text 'bash%s/sdcard/health.sh'
# Вывод: /sdcard/health.out  (читать с мака: adb shell "tr '\r' '\n' < /sdcard/health.out")
exec > /sdcard/health.out 2>&1

echo "=== $(date)"
echo "--- android"
getprop ro.product.model; getprop ro.build.version.release
awk '/MemFree|MemAvailable/{print}' /proc/meminfo
awk '/^wlan0|inet /{print}' /proc/net/route >/dev/null 2>&1
ip -f inet addr show wlan0 2>/dev/null | grep 'inet ' || echo "нет ip на wlan0"

echo "--- процессы"
ps | grep -E 'proot|venv/bin/python' | grep -v grep || echo "коллектор НЕ запущен"

echo "--- api"
python - <<'PY'
import json, urllib.request
for path in ("/healthz", "/api/v1/info"):
    try:
        with urllib.request.urlopen("http://127.0.0.1:8080" + path, timeout=8) as r:
            print(path, r.status, r.read(300).decode("utf-8", "replace"))
    except Exception as e:
        print(path, "ERR", e)
PY

echo "--- sites (кто онлайн)"
python - <<'PY'
import json, urllib.request
try:
    with urllib.request.urlopen("http://127.0.0.1:8080/api/v1/sites", timeout=8) as r:
        for s in json.load(r):
            print(f"  {s['site']:8s} online={s['online']} age={s['age_s']/60:.0f}m "
                  f"pv={s.get('pv_power')} load={s.get('load_power')} soc={s.get('battery_state_of_charge')}")
except Exception as e:
    print("ERR", e)
PY

echo "--- лог коллектора (хвост)"
tail -8 /sdcard/collector.log 2>/dev/null
echo "=== DONE"
