# Полный стек на Orange Pi 3 LTS

Цель: тот же комплект, что собран на VDS (`collector` + `InfluxDB 2.x` + `Grafana`), но на своей
плате в офисе — с историей, графиками и настройками, а не только live-панелью как на Pi 1.

Плата подходит: **Allwinner H6, aarch64, 4 ядра A53, 2 ГБ RAM, GbE, Wi-Fi (AP6256), eMMC 8 ГБ**.
Все образы стека имеют arm64-сборки; зависимости коллектора — чистый Python (fastapi/uvicorn/
paho/pyserial), компиляции при сборке нет.

## 1. Образ на карту

Что качать: **Armbian, ветка `bookworm` (Debian 12), minimal, для `orangepi3-lts`** —
<https://www.armbian.com/orange-pi-3-lts/> → `Armbian_*_Orangepi3-lts_bookworm_current_*_minimal.img.xz`.
(Официальный OrangePi Ubuntu тоже заведётся, но у Armbian свежее ядро и нормальный zram из коробки.)

Запись:

```bash
# macOS: узнать диск, потом писать (ОШИБКА В /dev/diskN = стёртый диск, проверь дважды!)
diskutil list                                    # найти внешний диск, напр. /dev/disk4
xz -dc Armbian_*_Orangepi3-lts_bookworm_*.img.xz | sudo dd of=/dev/rdisk4 bs=4m status=progress
```

Или GUI: balenaEtcher / Raspberry Pi Imager → «Use custom image».

Карту бери **16–32 ГБ класса A1/A2**: InfluxDB пишет непрерывно, на no-name 8 ГБ она умрёт
за месяцы. eMMC (8 ГБ) для истории маловата — оставь её системе только если карты нет.

## 2. Первый запуск

1. Карта в плату, питание (нужен БП **5 В / 3 А**, иначе просадки под нагрузкой), кабель в LAN.
2. Найти адрес: на роутере или `ping orangepi3-lts.local`. В Armbian логин по SSH —
   `root` / `1234` (сразу заставит сменить пароль и создать пользователя).
3. Поставить время (на H6 нет батарейки RTC — без NTP графики поедут):
   ```bash
   sudo timedatectl set-timezone Europe/Athens     # свою зону
   sudo timedatectl set-ntp true
   timedatectl | head -3
   ```
4. Закрепить IP на роутере (DHCP-резерв) — чтобы панель не переезжала.

## 3. Установка стека

Скопировать скрипт на плату и запустить (он сам поставит Docker, zram, склонирует репозиторий
в `/opt/solar-monitor` и поднимет контейнеры):

```bash
# с мака, если плата уже в сети
scp ~/solar-monitor/deploy/orangepi/bootstrap.sh root@<ip>:/root/
ssh root@<ip>
bash /root/bootstrap.sh --site office --transport hid --auth --random-password
```

Варианты транспорта:

| Как подключён инвертор | Аргументы |
|---|---|
| Нативный **USB**-порт инвертора (как SolarAssistant) | `--transport hid` |
| USB-RS232 / RS485 кабель | `--transport serial` |
| Донгл EW10 / ESP32-шлюз по сети | `--transport tcp --tcp-host <ip> --tcp-port 9999` |
| Импорт из SolarAssistant | `--transport sa-mqtt --mqtt-host <ip-SA>` |

### Нативный USB (hid) — подробнее

Инвертор с USB-портом (Voltronic/Axpert/Must) отдаёт PI30 через HID без переходника —
именно так его видит SolarAssistant. Коллектор для этого умеет `TRANSPORT=hid`:
пишет 8-байтные репорты в `/dev/hidrawN` и читает ответы оттуда же.

Важно: hidraw-номер (`hidraw0`, `hidraw1`, …) после перезагрузки может измениться, поэтому
`bootstrap.sh --transport hid` ставит udev-правило `99-solar-inverter-hid.rules` со стабильным
**`/dev/solar-inverter`** и прописывает его в `.env` (`HID_DEVICE=/dev/solar-inverter`).
Проверка на хосте:

```bash
lsusb | grep -iE '0665|voltr|axpert|must'      # обычно 0665:5161
ls -l /dev/solar-inverter                      # → ../hidrawN
```

Если VID:PID другой — раскомментируй строку в `/etc/udev/rules.d/99-solar-inverter-hid.rules`
(частые варианты: `0665:5161`, `0001:0000`, `0483:0035`), затем:
`sudo udevadm control --reload-rules && sudo udevadm trigger --subsystem-match=hidraw`.

**Один хозяин порта:** пока инвертор читает SolarAssistant (или mpp-solar), коллектор получит
пустые ответы — отключи старый софт/выключи ту плату, оставь только Orange Pi.

Скрипт печатает адреса и пароль Grafana. Дальше всё то же, что на VDS:
UI `http://<ip>:8080/` (Настройки → Подключение → «Проверить связь»), история — в Influx
(30 дней по умолчанию), дашборд — `Grafana → папка Solar → Solar overview`.

Если нужен Grafana по сети (по умолчанию он слушает только localhost), `bootstrap.sh` добавляет
оверрайд сам; вручную то же самое:

```bash
cd /opt/solar-monitor
# нативный USB (hid):
docker compose -f docker-compose.yml \
  -f deploy/orangepi/docker-compose.orangepi.yml \
  -f deploy/orangepi/docker-compose.hid.yml up -d
# RS232:
docker compose -f docker-compose.yml \
  -f deploy/orangepi/docker-compose.orangepi.yml \
  -f deploy/orangepi/docker-compose.serial.yml up -d
```

Оверрайды прокидывают устройство в контейнер (`/dev/solar-inverter` или `/dev/ttyUSB0`)
без правки основного `docker-compose.yml`. Если адаптер висит на другом порту — поправь
`devices:` в оверрайде (стабильное имя: `ls /dev/serial/by-id/`).

## 4. Что проверить в первый день

```bash
cd /opt/solar-monitor
docker compose ps                       # три контейнера Up, collector — healthy
curl -s localhost:8080/healthz | jq      # {"status":"ok"...}
curl -s localhost:8080/api/v1/state | jq '.device_mode, .battery_state_of_charge, .pv_power'
docker compose logs --tail 30 collector  # "poller online", значения каждые 10 с
docker stats --no-stream                 # RAM: influx ~400 МБ, grafana ~200, collector ~80
df -h /                                  # свободное место не тает
```

Для нативного USB первым делом смотри лог коллектора: `poller online` vs
`no valid answer from usb-hid`. Если нет ответа, а SolarAssistant на этом же кабеле работал —
проверь, что старая плата/софт отключены (порт у инвертора один) и что `lsusb` видит `0665:5161`.
Запасной путь у тебя есть всегда: в инверторе тот же PI30 выходит на **RS232**,
тогда `TRANSPORT=serial` + кабель USB-RS232 (2400 8N1).

Через сутки: появились ли точки в Grafana (`Solar overview`, период 24 ч), не растёт ли RAM
(`docker stats`), нет ли `restart` у контейнеров.

## 5. Грабли (по опыту Pi 1 / VDS)

* **2 ГБ RAM** — впритык, но хватает; zram ставит сам bootstrap. Не добавляй панелей-монстров
  и не включай лишние плагины Grafana.
* **Износ карты** — логи контейнеров уже ограничены (`10m×3`), ретенция Influx 30 дней;
  если карта начнёт сыпать ошибками — переносить данные на USB-SSD.
* **Одна USB-шина** на H6: Wi-Fi-свисток + USB-RS232 + USB-SSD одновременно = просадки.
  Для офиса лучше **кабель в LAN** (GbE есть) + USB-RS232.
* **RAM-диск/swap**: если после суток `docker stats` показывает OOM (контейнер перезапускается) —
  подними `POLL_INTERVAL` до 10–15 с и оставь Influx-ретенцию 14 дней.
* **Пароль UI** `admin/admin` в `.env` — либо `--auth --random-password` при установке,
  либо сменить в Настройки → Уставки → Доступ.
* Токены и пароли (`INFLUX_TOKEN`, `GRAFANA_PASSWORD`, `INFLUX_PASSWORD`) генерируются в
  `/opt/solar-monitor/.env` с правами 600 — этот файл в git не попадает, бэкапь его отдельно
  (`sudo cp .env ~/solar-env.backup`).
