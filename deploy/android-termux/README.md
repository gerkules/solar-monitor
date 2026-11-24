# solar-monitor на старом Android-телефоне (Termux + proot Debian)

Полная процедура «из коробки до работающего узла». Проверено на живом железе
2026-11-24, включая перезагрузку телефона.

## 1. Референсная конфигурация (что реально проверено)

| Параметр | Значение |
|---|---|
| Телефон | Samsung Galaxy A3 2016 (**SM-A310F**, codename `a3xelte`) |
| Android | 7.0, SDK 24, сборка `NRD90M.A310FXXS5CTJ2` |
| SoC | Exynos 7580, ядро 3.10.61, ядро `armv8l`, userspace **32-бит** (`armeabi-v7a,armeabi`) |
| RAM | 1.37 ГБ (свободно после чистки 25–30 МБ) |
| Диск | 11 ГБ `/data`, из них 10 ГБ свободно |
| Termux | 0.118.3 `github-debug_armeabi-v7a` (API 24 — минимум для Termux) |
| Дистрибутив | proot-distro `debian` 13.8 **armhf**, Python 3.13.5 |
| Зависимости | fastapi 0.165.0, uvicorn 0.54.0, pydantic 2.14.4, `pydantic_core 2.50.5` (колесо `cp313-manylinux2014_armv7l`) |
| Браузер для UI | **Firefox 119 (armeabi-v7a, minSdk 21)** |

Итог: коллектор + веб-интерфейс живут на телефоне, публикуют в брокер наружу,
автозапускаются после ребута.

## 1.1. Файлы в этом каталоге

| Файл | Где запускать | Что делает |
|---|---|---|
| `10-mac-install-apks.sh` | **мак** | качает и ставит Termux / Termux:Boot / Firefox 119 через adb, включает настройки Android |
| `20-phone-bootstrap.sh` | Termux на телефоне | `pkg upgrade`, proot-distro, Debian, venv, `pip install -r requirements.txt` |
| `30-start-collector.sh` | **внутри Debian** → `/root/start-collector.sh` | все env-переменные коллектора и запуск |
| `40-termux-boot.sh` | Termux → `~/.termux/boot/start-collector.sh` | автозапуск после ребута, while-true рестарт |
| `41-termux-boot-with-broker.sh` | Termux → `~/.termux/boot/start-collector.sh` | то же + поднимает **локальный mosquitto** (автономный комплект) |
| `config.example` | копия → `/root/solar-monitor.env` в Debian | шаблон всех переменных (SITE, брокер, транспорт, auth) |
| `50-health.sh` | Termux на телефоне | разовая проверка: RAM, Wi-Fi, процессы, `/healthz`, сайты, хвост лога |

## 2. Чего на таком телефоне НЕ будет

| Компонент | Почему |
|---|---|
| InfluxDB 2.x | нет сборок под armv7 — вкладка «Графики» будет пустой, история только на NAS/VDS |
| Grafana | ~~armv7 есть~~, но на 1.37 ГБ вместе с коллектором не оставить |
| Docker | без root невозможен |
| USB-HID / USB-RS232 напрямую | нет `/dev/hidraw*`, `/dev/ttyUSB0`; доступ к инвертору только по TCP (донгл/мост) |

## 3. Три грабли, на которые уйдёт вечер, если не знать

1. **`pip install fastapi` в Termux падает.** В Termux Python собран под
   `arm-unknown-linux-androideabi`, `pydantic-core` таких колёс не публикует →
   pip идёт компилировать Rust и умирает на
   `Target triple not supported by rustup`. Термуксовых пакетов
   `python-pydantic` под arm тоже нет. **Решение:** ставить всё внутри
   `proot-distro` Debian (glibc, колёса `manylinux2014_armv7l` есть).
2. **proot падает с `assertion "IS_IN_SYSENTER(tracee)" failed`.** Классический
   баг 32-бит proot. **Решение:** `export PROOT_NO_SECCOMP=1` перед
   `proot-distro login` (иначе `apt-get`/`pip` убивают контейнер).
3. **Внутри proot отваливается DNS** (`Temporary failure in name resolution`).
   **Решение:** прописать `resolv.conf` в rootfs до первого `apt/pip`:
   `echo 'nameserver 192.168.31.1' > $PREFIX/var/lib/proot-distro/installed-rootfs/debian/etc/resolv.conf`

Плюс мелочь, которая ломает установку: файлы, записанные в rootfs **со стороны
Termux**, внутри proot иногда не видны (владелец/маски). Всё, что должно попасть
в `/root/...`, кладите через `/sdcard` и `cp` **изнутри proot**.

## 4. Порядок установки

### 4.1 Mac: скачать APK и поставить через adb

Всё это делает `10-mac-install-apks.sh` (аргументы: ABI и `firefox|no`).
Ниже — то же самое руками, если нужно понять, что происходит:

```bash
# Termux (armeabi-v7a!)
curl -L -o termux-arm.apk \
  "https://github.com/termux/termux-app/releases/download/v0.118.3/termux-app_v0.118.3%2Bgithub-debug_armeabi-v7a.apk"
# Termux:Boot (автозапуск)
curl -L -o termux-boot.apk \
  "https://github.com/termux/termux-boot/releases/download/v0.8.1/termux-boot-app_v0.8.1%2Bgithub.debug.apk"
# Firefox 119 armeabi-v7a (последняя ветка, которая ещё ставится на Android 7)
curl -L -o firefox119.apk \
  "https://archive.mozilla.org/pub/fenix/releases/119.0/android/fenix-119.0-android-armeabi-v7a/fenix-119.0.multi.android-armeabi-v7a.apk"

adb install -r -g termux-arm.apk        # -g = сразу все runtime-разрешения
adb install -r -g termux-boot.apk
adb install -r firefox119.apk
```

На телефоне: `Настройки → О телефоне → Сведения о ПО → Номер сборки` — 7 тапов →
«Параметры разработчика» → включить **«Отладка по USB»** и **«Выбор конфигурации
USB» = MTP**. Подтвердить на телефоне RSA-ключ мака.

Скачать APK для другой модели = взять ABI из
`adb shell getprop ro.product.cpu.abilist` (arm64-v8a → суффикс `arm64-v8a`).

### 4.2 Телефон: Termux и Debian

Запустить Termux (первый старт скачает bootstrap), затем выполнить
`20-phone-bootstrap.sh` (лежит рядом). Он делает:

```sh
yes | pkg update -y && yes | pkg upgrade -y
pkg install -y proot-distro python git openssh
proot-distro install debian
# ВАЖНО: DNS в rootfs до первого apt
printf 'nameserver 192.168.31.1\nnameserver 1.1.1.1\n' \
  > $PREFIX/var/lib/proot-distro/installed-rootfs/debian/etc/resolv.conf
export PROOT_NO_SECCOMP=1
proot-distro login debian -- bash -c '
  apt-get update -qq
  apt-get install -y -qq --no-install-recommends python3 python3-venv python3-pip ca-certificates
  python3 -m venv /root/venv
  /root/venv/bin/pip install -q --upgrade pip wheel
'
```

Код коллектора копируется внутрь через `/sdcard` (изнутри proot):

```sh
adb push ../../collector /sdcard/collector
proot-distro login debian -- bash -c '
  mkdir -p /root/solar-monitor && cp -r /sdcard/collector /root/solar-monitor/collector
  cd /root/solar-monitor/collector && /root/venv/bin/pip install -q -r requirements.txt'
```

### 4.3 Лаунчер внутри Debian

`/root/start-collector.sh` (см. `30-start-collector.sh`) — все переменные окружения
в одном месте. Ключевое для домашнего инвертора:

```sh
export SITE=phone MQTT_PREFIX=solar/phone
export TRANSPORT=tcp TCP_HOST=192.168.1.222 TCP_PORT=9999   # проброс роутера на EW10
export WEBAPP=true API_PORT=8080 POLL_INTERVAL=10
```

Пароли в git не хранить: `MQTT_USER`/`MQTT_PASS` брать из `~/inverter-mqtt/.env`
(в скрипте — заглушки `CHANGE_ME`).

> Почему `192.168.1.222:9999`, а не `192.168.31.110:9999`: донгл EW10 держит
> **одно** TCP-соединение, локальный порт занят другим коллектором и отвечает
> `Connection refused`. Через проброс роутера соединение отдаётся нормально.
> Если порт занят и там — сначала остановить старый коллектор.

### 4.4 Автозапуск (Termux:Boot)

`~/.termux/boot/start-collector.sh` (см. `40-termux-boot.sh`):

```sh
#!/data/data/com.termux/files/usr/bin/sh
termux-wake-lock
export PROOT_NO_SECCOMP=1
LOG=/sdcard/collector.log
while true; do
  echo "=== start $(date)" >> "$LOG"
  proot-distro login debian -- bash /root/start-collector.sh >> "$LOG" 2>&1
  echo "=== collector exited rc=$? $(date), restart in 10s" >> "$LOG"
  sleep 10
done
```

`chmod +x ~/.termux/boot/start-collector.sh`. Проверка: `adb reboot`, подождать
2 минуты, `tail /sdcard/collector.log` — должен быть свежий `=== start`.

### 4.5 Чтобы Android не убил процесс

```sh
adb shell dumpsys deviceidle whitelist +com.termux     # вывести из Doze
adb shell settings put global wifi_sleep_policy 2      # Wi-Fi не спит
adb shell settings put global stay_on_while_plugged_in 7  # экран горит при зарядке (для панели)
# выкинуть мусор (освобождает ~80 МБ)
for p in com.microsoft.skydrive de.axelspringer.yana.zeropage \
         com.google.android.youtube com.google.android.apps.maps com.google.android.gm; do
  adb shell pm disable-user --user 0 $p
done
```

### 4.6 UI на телефоне

**Только Firefox 119+** (или любой Chromium 80+). Chrome 64 / Samsung Internet 5.2
на Android 7 не понимают `?.` и `...` в `app.js` и `uplot.min.js` → страница
рендерится, но все значения — прочерки, в логе браузера `Uncaught SyntaxError`.

Открыть `http://127.0.0.1:8080/?site=phone#/overview`. Выбор площадки
запоминается в `localStorage['solar.site']` — если однажды выбрали чужую,
сброс: `adb shell pm clear org.mozilla.firefox`.

## 5. Проверка и диагностика

```bash
# разовая проверка узла (RAM, Wi-Fi, процессы, /healthz, сайты, лог)
# adb push 50-health.sh /sdcard/health.sh → bash /sdcard/health.sh в Termux
adb shell "tr '\r' '\n' < /sdcard/health.out"
# вывод любого ad-hoc скрипта
adb shell "tr '\r' '\n' < /sdcard/t.out | tail -20"
# напрямую: открыть в браузере телефона
#   /healthz  /api/v1/info  /api/v1/state  /api/v1/sites
# лог коллектора
adb shell "tail -50 /sdcard/collector.log"
# процессы
adb shell "ps | grep -E 'proot|python'"
```

Как гонять команды в Termux по adb **без рук** (полезно для скриптов):

```bash
adb push script.sh /sdcard/script.sh
adb shell am start -n com.termux/.HomeActivity    # вывести Termux на экран
adb shell input tap 360 400                       # фокус в терминал
adb shell input text 'bash%s/sdcard/script.sh'    # %s = пробел
sleep 1; adb shell input keyevent 66              # Enter (иногда нужен второй раз)
```

Грабли этого способа: если в терминале выполняется долгий скрипт, набранный текст
уходит в его stdin, а Enter «съедается» — ждать окончания и слать Enter повторно.

## 6. Бенчмарк (для сравнения с новым телефоном)

| Метрика | A3 2016 |
|---|---|
| Скорость `apt-get install python3`: | ~40 с |
| `pip install -r requirements.txt`: | ~60 с (колёса armv7) |
| RAM коллектора (python + proot): | ~90–120 МБ |
| Свободно RAM при работе: | 25–30 МБ |
| OOM-смерти при пустом кэше: | не было ни разу |
| OOM-смерти сразу после ребута (забитая память): | 1 раз |
| `healthz` uptime без перезапусков: | 6+ минут (проверено), ребут проходит |

## 7. Чек-лист для следующего телефона

1. `adb shell getprop ro.product.cpu.abilist` → выбрать ABI APK (`arm64-v8a` /
   `armeabi-v7a`). На arm64 будет заметно быстрее и есть шанс на Influx.
2. `ro.build.version.sdk` ≥ 24 (иначе Termux только legacy-сборка `apt-android-5`).
3. Свободного места ≥ 3 ГБ (Termux ~300 МБ + Debian ~700 МБ + venv ~200 МБ).
4. Модель/инвертор: какой транспорт доступен — `tcp` (донгл/мост), `hid` (только
   root), `mqtt` (донгл в MQTT-режиме, делим топик с другими поллерами — не
   запускать вторым).
5. Кнопка «Разблокировка OEM» есть? Если да — в перспективе возможен postmarketOS,
   если для коднейма есть порт (проверять `pmaports/device/{community,testing}`).
6. Не забыть: `AUTH_PASSWORD` для UI, иначе любой в сети меняет уставки инвертора.

## 8. Комплект для друга: мост на Wemos вместо донгла

Сценарий: у второго человека такой же инвертор, своего сервера/брокера нет, данные
отдаёт самодельный мост **Wemos D1 (ESP8266) TCP ⇄ RS232** (прошивка в `firmware/esp8266/`).
Телефон = коллектор + UI + брокер, всё локально, интернет не нужен.

### 8.1 Что настроить на Wemos

1. Прошить образ `firmware/esp8266/builds/126_wemos_d1_esp8266_rs232_ui.bin`.
2. **Включить мост** — по умолчанию он выключен: веб-панель → вкладка «Мост» → вкл,
   либо по USB-serial (115200) командой `bridge on`. Порт TCP по умолчанию **9999**.
3. Линия инвертора **2400 8N1**, подключение через MAX3232 (инвертор — настоящий RS232 ±12 В).
4. **Снять донгл EW10** с разъёма: на линии 2400 бод два мастера несовместимы.
   Wemos сам ставит локальный опрос на паузу, пока подключён TCP-клиент.

### 8.2 Что настроить на телефоне

```sh
pkg install -y mosquitto      # пакета mosquitto-clients в Termux НЕТ (проверено)
```

В `/root/solar-monitor.env` (см. `config.example`):

```sh
SITE=friend                       # имя сайта → solar_friend_* в HA
MQTT_HOST=127.0.0.1               # локальный брокер на самом телефоне
TRANSPORT=tcp
TCP_HOST=<ip-wemos>               # обычно 192.168.4.1 в режиме AP
TCP_PORT=9999
AUTH_PASSWORD=<пароль>            # обязательно
```

Автозапуск — `41-termux-boot-with-broker.sh` (поднимает mosquitto, потом коллектор).

Всё то же можно переключить **из веб-интерфейса**: Настройки → Подключение →
«Виртуальный RS232 (TCP)» → host/port. Выбор пишется в `/data/connection.json`
(внутри rootfs каталог `/data` есть и доступен на запись — проверено).

### 8.3 Что получит друг и чего не получит

| Есть | Нет |
|---|---|
| Живой UI на телефоне (`http://127.0.0.1:8080`) и с любого устройства в его сети (`http://<ip-телефона>:8080`) | Истории/графиков — InfluxDB 2.x не собирается под armv7 |
| MQTT внутри телефона — можно потом прицепить его HA | TLS/HTTPS из коробки (внутри LAN не нужен) |
| Автозапуск после ребута, работа без интернета | Резервирования: упал телефон — нет данных |
| Панель самого Wemos (FW124) со схемой потоков и графиком за час — как замена графикам | — |

### 8.4 Три команды для друга, если «не показывает»

```sh
# 1. жив ли мост и отвечает ли инвертор (с телефона по ssh/adb или в Termux)
python -c "import socket;s=socket.create_connection(('<ip-wemos>',9999),5);print('bridge ok');s.close()"
# 2. жив ли коллектор
python -c "import urllib.request as u;print(u.urlopen('http://127.0.0.1:8080/healthz',timeout=5).read())"
# 3. хвост лога
tail -20 /sdcard/collector.log
```
