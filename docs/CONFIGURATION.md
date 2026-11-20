# Конфигурация

Все настройки — переменные окружения в `.env` (см. `.env.example`). Правки в UI (подключение,
источник АКБ) сохраняются в `/data/*.json` и перекрывают `.env`.

## Идентичность сайта

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `SITE` | `office` | короткий ID сайта: тег InfluxDB, часть топиков MQTT |
| `DEVICE_NAME` | `Inverter` | имя устройства в UI и Home Assistant |
| `DEVICE_MODEL` | `PI30 inverter` | модель для HA |
| `ENTITY_PREFIX` | `solar_<site>` | префикс сущностей HA (`sensor.solar_home_pv_power`) |
| `TEMP_UNIT` | `C` | единицы температуры в публикациях (`C`/`F`) |

## Подключение к инвертору

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `TRANSPORT` | `tcp` | `hid` / `serial` / `tcp` / `mqtt` / `sa-mqtt` |
| `TCP_HOST`, `TCP_PORT` | `192.168.1.60`, `9999` | донгл/шлюз для `tcp` |
| `SERIAL_PORT`, `SERIAL_BAUD` | `/dev/ttyUSB0`, `2400` | USB-RS232/RS485 |
| `HID_DEVICE` | `/dev/hidraw0` | hidraw-узел (или `HID_VID`/`HID_PID` + hidapi) |
| `HID_VID`, `HID_PID`, `HID_REPORT_ID` | `0x0665`, `0x5161`, `0` | если HID_DEVICE не путь — открытие через hidapi |
| `TRANS_TOPIC` | `inverter/` | топики EW10 в режиме MQTT-сокета |
| `CONNECTION_FILE` | `/data/connection.json` | выбор из UI (перекрывает `.env`) |

Выбор транспорта также доступен в UI: **Настройки → Подключение** (с кнопкой «Проверить связь»).
## Второй и последующие инверторы

Каждый инвертор — отдельный процесс-коллектор со своим `SITE`: он публикует
`solar/<site>/state`, а UI показывает все площадки в селекторе (иконка сайта в шапке).
Добавляется из интерфейса: **Настройки → Инверторы** — id, название, транспорт
(`tcp` / `serial` / `hid` / `mqtt`), «Проверить связь», «Добавить».

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `INVERTERS_ENABLED` | `1` | разрешить управление доп. инверторами из UI |
| `INVERTERS_MODE` | `auto` | `systemd` (нативный хост) / `process` (Docker: дочерние процессы) / `off` |
| `INVERTERS_DIR` | `/data/inverters` | `<site>.json` + `<site>.env` (по одному на инвертор) |
| `SUPERVISOR_CMD` | `sudo -n /usr/local/lib/solar-monitor/inverter-ctl` | как звать systemd |

Что делает «Добавить»: пишет `<site>.env` (общие настройки наследуются из
основного `/opt/solar-monitor/.env`, свои — файлы состояния, чтобы история и
уставки не пересекались), `systemctl enable --now solar-collector@<site>.service`.
Веб-интерфейс у доп. инверторов по умолчанию выключен (`WEBAPP=0`) — экономим RAM;
их данные видно здесь же, выбрав сайт в шапке.

### Два USB-HID инвертора на одной плате

У инверторов Voltronic одинаковые VID:PID (`0665:5161`) и `SerialNumber=0`,
поэтому различает их только физический USB-порт. Правило
`deploy/pi/60-voltronic-hid.rules` даёт стабильные имена:

| Имя | Смысл |
|---|---|
| `/dev/voltronic-inverter` | первый инвертор (его использует основной коллектор) |
| `/dev/inverter-usb1 … /dev/inverter-usb7` | по номеру порта хаба (`1-1.N`) |

Порядок: воткнуть второй инвертор в свободный порт → `inverter-ports` покажет,
какой алиас ему достался и кто уже занят → в UI «Инверторы» выбрать `hid` и этот
алиас. Пустое поле `hid_device` подставит первый **свободный** узел; занять узел
другого инвертора (или его алиас) нельзя — вернётся ошибка.

На нативном хосте нужны шаблонный unit `solar-collector@.service`, helper
`inverter-ctl` и правило sudoers — всё ставит `deploy/pi/install-pi.sh`
(проверить: `curl -u admin …/api/v1/inverters`). В Docker (systemd внутри нет)
включается режим `process`: панель сама поднимает дочерние процессы того же
контейнера и следит, чтобы они не падали; конфиги и файлы состояния живут в томе
`/data`. Отдельные контейнеры на инвертор тоже возможны, но их придётся вести руками.

## Опрос

## Опрос

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `POLL_INTERVAL` | `5` | период `QPIGS`, сек |
| `QMOD_INTERVAL` | `60` | период `QMOD` (режим) |
| `QPIRI_INTERVAL` | `600` | период `QPIRI` (уставки/паспорт) |
| `QPIWS_INTERVAL` | `60` | период `QPIWS` (предупреждения), `0` — выключить |
| `QBMS_INTERVAL` | `60` | период `QBMS` (данные BMS от инвертора), `0` — выключить |
| `HAS_MPPT2` | `true` | опрашивать `QPIGS2` (второй MPPT) |
| `OFFLINE_AFTER` | `120` | через сколько секунд без данных публиковать `offline` |
| `GRID_DEADBAND` | `50` | порог «шума» при расчёте мощности сети, Вт |
| `ALLOW_SETTINGS` | `true` | разрешить запись уставок |
| `SETTINGS_JSON` | — | переопределение команд записи (`{"max_charge_current":{"cmd":"MCHGC{:03d}"}}`) |

## MQTT

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `MQTT_HOST`, `MQTT_PORT` | `127.0.0.1`, `1883` | брокер |
| `MQTT_USER`, `MQTT_PASS` | — | авторизация |
| `MQTT_TLS` | `false` | TLS |
| `MQTT_PREFIX` | `solar/<site>` | префикс топиков сайта |
| `SITE_ROOT` | родитель `MQTT_PREFIX` | корень для мультисайта (`solar/+/state`) |
| `STATE_RETAIN` | `true` | держать последнее состояние сайта на брокере |
| `SITE_TTL` | `900` | через сколько секунд забывать молчащий сайт |
| `HA_DISCOVERY` | `true` | публиковать discovery для Home Assistant |
| `HA_DISCOVERY_PREFIX` | `homeassistant` | префикс discovery |
| `PEER_SITES` | `{}` | `{"office":"http://ip:8081"}` — API соседних сайтов для UI |

## MQTT из интерфейса

Страница **Настройки → MQTT** закрывает три вещи, которые раньше правились только
руками по SSH:

| Блок | Что делает | Где хранится |
|---|---|---|
| «Куда публикует этот коллектор» | хост/порт/логин/пароль/TLS/префикс топиков | `/data/mqtt.json` (перекрывает `.env`), после сохранения коллектор перезапускается |
| «Брокер на этом хосте» | статус, слушающие порты, клиенты, анонимный доступ, пользователи | `/etc/mosquitto/conf.d/broker-ui.conf`, `/etc/mosquitto/passwd` (helper `mqtt-ctl`) |
| «Подключения к другим брокерам» | CRUD мостов: адрес, логин/пароль, фильтр топиков, направление `in`/`out`/`both` | `/etc/mosquitto/conf.d/bridge-<имя>.conf` |

Привилегированные действия идут через узкий helper
`/usr/local/lib/solar-monitor/mqtt-ctl` (правило sudoers `solar-mqtt`, ставится
`deploy/pi/install-pi.sh`). В Docker брокером управляет хост, поэтому блоки
«брокер» и «мосты» там только для чтения — это видно в UI. Параметры
собственной публикации работают в обоих режимах.

Мост в обе стороны на одинаковые топики даёт петлю: для обмена «дом ↔ офис»
держите `out` на одной стороне и `in` на другой.

## InfluxDB

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `INFLUX_MODE` | `2` | `2` (Flux) или `1.8` (InfluxQL) |
| `INFLUX_URL` | `http://influxdb:8086` | адрес |
| `INFLUX_TOKEN` | — | токен (2.x) |
| `INFLUX_ORG`, `INFLUX_BUCKET` | `solar`, `solar` | организация и бакет |
| `INFLUX_DB` | =`INFLUX_BUCKET` | база для 1.8 |
| `INFLUX_AUTH` | — | `user:pass`, если в 1.8 включена авторизация |
| `INFLUX_MEASUREMENT_PREFIX` | — | префикс имён измерений |

## Веб-интерфейс и API

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `API_HOST`, `API_PORT` | `0.0.0.0`, `8080` | адрес UI/API внутри контейнера |
| `API_HOST_PORT` | `8080` | порт на хосте (compose) |
| `API_TOKEN` | — | требовать `Authorization: Bearer` |
| `AUTH_USER`, `AUTH_PASSWORD` | `admin`, `admin` | HTTP Basic для UI и API (кроме `/healthz`); смените пароль после установки |
| `AUTH_FILE` | `/data/auth.json` | пароль, изменённый в UI (PBKDF2-хэш), перекрывает `AUTH_*` |
| `TLS_CERT`, `TLS_KEY` | — | пути к сертификату/ключу в контейнере → HTTPS на `API_PORT` |
| `PEER_TLS_VERIFY` | `false` | проверять сертификат соседнего сайта |
| `LOG_LEVEL` | `INFO` | уровень логов |
| `MQTT_CLIENT_ID` | `solar-monitor-<site>` | client id |
| `STATE_FILE` | `/data/state.json` | резервный файл состояния |
| `SAMPLE_JSON` | `false` | писать в лог каждый опубликованный state |

## Автоматизация, уведомления, прогноз

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `AUTOMATION` | `true` | включить движок правил |
| `RULES_FILE` | `/data/rules.json` | хранение правил |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | — | канал Telegram |
| `WEBHOOK_URL` | — | POST JSON на webhook |
| `NOTIFY_MQTT_TOPIC` | `<prefix>/notify` | MQTT-канал |
| `NOTIFY_MIN_INTERVAL` | `60` | антиспам, сек на канал |
| `FORECAST_ENABLED` | `false` | прогноз PV (forecast.solar) |
| `FORECAST_LAT`, `FORECAST_LON`, `FORECAST_KWP` | — | координаты и мощность массивов |
| `FORECAST_DECLINATION`, `FORECAST_AZIMUTH` | `30`, `0` | наклон и азимут панелей |
| `FORECAST_INTERVAL` | `3600` | период обновления, сек |
| `FORECAST_CACHE_FILE` | `/data/forecast.json` | кэш (лимит API — 12 запросов/час) |

## Батарея

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `BATTERY_SOURCE` | `inverter` | `inverter`/`emulated`/`jbd`/`daly`/`pylontech`/`modbus`/`vedirect`/`can` |
| `BATTERY_CONFIG_FILE` | `/data/battery.json` | выбор из UI (перекрывает `BATTERY_SOURCE`) |
| `BATTERY_CAPACITY_AH`, `BATTERY_NOMINAL_V` | —, `48` | для `emulated` |
| `BMS_PORT`, `BMS_BAUD` | `/dev/ttyUSB1`, `9600` | порт и скорость адаптера BMS |
| `BMS_UNIT_ID` | `1` | Modbus slave id |
| `BMS_INTERVAL` | `10` | период опроса BMS, сек |
| `BMS_CAN_INTERFACE` | `can0` | интерфейс socketcan |
| `BMS_NTC_COUNT`, `BMS_JBD_TEMP` | `2`, `offset40` | разбор температур JBD |
| `BMS_MODBUS` | — | карта регистров JSON |
| `BMS_EVENTS_FILE` | `/data/bms_events.json` | журнал кодов BMS |
| `BMS_LINK_ALERT_AFTER` | `180` | через сколько секунд без BMS слать алерт (мануал: buzzer 3 мин) |
| `BATTERY_TYPE_ROLLBACK`, `BATTERY_TYPE_ROLLBACK_AFTER` | `false`, `45` | авто-откат протокола BMS (opt-in) |

## Импорт из SolarAssistant

| Переменная | По умолчанию | Смысл |
|---|---|---|
| `SA_MQTT_HOST`, `SA_MQTT_PORT` | `127.0.0.1`, `1883` | брокер SolarAssistant |
| `SA_MQTT_USER`, `SA_MQTT_PASS` | — | если у SA включена авторизация MQTT |

## Порты по умолчанию

| Порт | Что |
|---|---|
| 8080 | UI + REST API коллектора |
| 3000 | Grafana |
| 8086 | InfluxDB (только localhost по умолчанию) |
| 1883 | Mosquitto (если поднят профилем `local-broker`) |
