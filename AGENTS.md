# solar-monitor — память проекта

Открытый аналог SolarAssistant (Voltronic/Axpert PI30) в Docker: mini PC / VDS / NAS.
Каталог: `~/solar-monitor`. Аудит эталона: `~/solar-analog/AUDIT.md`.

## Репозиторий

* **GitHub:** https://github.com/gerkules/solar-monitor (публичный, ветка `main`)
* Git identity в репо: `gerkules <gerkules@users.noreply.github.com>`, push по SSH-ключу
  `~/.ssh/id_ed25519` (добавлен в GitHub).
* CI: `.github/workflows/ci.yml` — 179 тестов, `node --check`, сборка образа, проверка compose.
* Копия проекта на NAS (без `data/` и `.ref/`): `/volume1/WD4/AI/solar-monitor`.
* Пуш: `cd ~/solar-monitor && git add -A && git commit -m "…" && git push`.

## Где что запущено

| Хост | Роль | Как заходить |
|---|---|---|
| **VDS для экспериментов** `192.168.31.115` (`iptv`, Ubuntu 20.04, 2 ядра/1.9 ГБ) | прод-демо: весь стек | `ssh root@192.168.31.115` (ключ залит), проект в `/opt/solar-monitor` |
| Мак `192.168.31.85` | исходники, тесты | `~/solar-monitor` |
| Synology NAS | **не использовать** — InfluxDB 2.x висит в D-state (bolt+btrfs+старое ядро). Всё, что там ставилось, удалено | — |

VDS: Grafana `:3000`, API home `:8080`, API office `:8081`, Influx `127.0.0.1:8086`.
На VDS два коллектора: `solar-collector` (home, TCP → EW10) и `solar-collector-office`
(sa-mqtt → брокер SolarAssistant `192.168.1.134:1883`, .env.office).
Файлы: `/opt/solar-monitor`, поднимать `docker compose -f docker-compose.yml -f docker-compose.office.yml up -d`. Пароль Grafana — в `/opt/solar-monitor/.env` на VDS.

## Состояние (2026-11-18)

- **Итерация 1 готова:** collector (4 транспорта), MQTT + HA discovery, InfluxDB 2.x,
  Grafana (22 панели), HTTP API, запись всех 9 настроек с проверкой по QPIRI.
- **Итерация 2 (UI) готова:** FastAPI + SPA без сборки (`collector/solar_monitor/web/`),
  SSE-обновление, power-flow, страницы обзор/инвертор/АКБ/сеть/энергия/графики/настройки (uPlot вендорен).
- **UI перерисован под SolarAssistant** (дизайн-токены вытащены из `priv/static/css/app.css`
  оригинального устройства): светлая тема, Exo, градиентная шапка, gauge-индикаторы, `.status`-блоки.
  Копия эталонного CSS для справки — `~/solar-monitor/.ref/sa_app.css` (в git/контейнер не идёт).
- Два массива PV показываются только если инвертор их отдаёт: признак `state.has_mppt2`
  ставится в poller, когда `QPIGS2` реально сообщает напряжение/мощность (у домашнего 11 кВт
  второй MPPT есть — 23 + 40 Вт).
- Экспорт CSV, backup/restore добавлены (`/api/v1/export`, `/api/v1/backup`, `/api/v1/restore`).
- **Итерация 3 готова:** правила автоматизации (`rules.py`: условие+`for_s`+`cooldown`,
  действия notify/set/mqtt), уведомления Telegram/webhook/MQTT (`notifier.py`),
  PV-прогноз forecast.solar (`forecast.py`) с записью будущих точек в Influx,
  экспорт CSV + backup/restore.
- **Итерация 4 готова:** мультисайт (collector пишет retained `solar/<site>/state`,
  UI подписан на `solar/+/state`, селектор площадки, `/api/v1/sites`, `?site=` во всех
  эндпоинтах, TTL забывания мёртвых сайтов) + HTTP Basic авторизация UI/API.
- **Итерация 5 готова:** транспорт `sa-mqtt` — импорт работающей SolarAssistant как сайта
  (второй сайт `office` на VDS поднят и живой). Плюс фикс: подписки MQTT получают `(topic, payload)`.
- **Итерация 6 готова:** мониторинг АКБ как у SA — источник данных (`BATTERY_SOURCE`):
  inverter / emulated / jbd / pylontech / modbus / vedirect / can; тип АКБ как уставка (`PBT`).
  Страница «АКБ» → блок «Мониторинг АКБ».
- **Итерация 7 готова:** каталог источников АКБ как у SA (67 позиций, 10 групп транспортов,
  ~55 брендов), выбор **в UI** (АКБ → «Выбрать источник АКБ») с сохранением в `/data/battery.json`
  и переключением без рестарта; добавлены драйверы `daly` и `voltronic` (PI30-совместимые АКБ).
- **Итерация 8 готова:** протокол BMS самого инвертора — `QPIRI` поле 13 = 10 протоколов
  (AGM/Flooded/User/Pylontech/Shinheung/WECO/Soltaro/TBD/LIb/3rd-party-Lithium), уставка `PBT00..09`,
  плюс чтение `QBMS` (данные, которые инвертор получает от АКБ по CAN/RS485) → `inverter_bms_*`.
- **Итерация 9 готова:** подтверждение смены протокола BMS в UI + автооткат, если через
  `BATTERY_TYPE_ROLLBACK_AFTER` (90 с) `QBMS` не вернулся в `Connected`; кнопки
  «Подтвердить сейчас»/«Вернуть прежний», статус `GET /api/v1/battery/protocol`.
- Коды пишутся в журнал из одной точки `_set_bms_code()`: иначе потеря связи (62) и «норма» (0)
  пишутся дважды в одном цикле. Пока связь лежит, `_track_bms_flags()` не трогает журнал.
- **Коды BMS (источник: `/Volumes/WD4/Data/manual-voltronic-axpert-max.pdf`, раздел «5. Code Reference»):**
  60 = не заряжать и не разряжать, 69 = не заряжать, 70 = требует заряжать, 71 = не разряжать,
  62 = нет связи с BMS (buzzer 3 мин, стоп через 10 мин). Всё вычисляется из флагов `QBMS` →
  `bms_code`, `bms_charge_blocked`, `bms_discharge_blocked`, `inverter_bms_force_charge`;
  в UI баннер с кодом + кнопки «User (PBT02)»/«AGM (PBT00)»; алерт по потере связи — 180 с
  Автооткат протокола теперь **opt-in** (`BATTERY_TYPE_ROLLBACK=false` по умолчанию) —
  по просьбе владельца: инвертор защищается сам, а авто-возврат может отменить осознанный выбор.
- **Итерация 10 (проверено на живом инверторе):** автооткат протокола BMS с восстановлением связи.
  Факты от владельца + замер: **инвертор переподключает АКБ за 20–30 с** после выбора правильного
  протокола, и **при неверном протоколе блокирует заряд**. Отсюда: окно проверки 45 с,
  шаг перезаписи 35 с (страховка), до 3 попыток.
- Тесты: **156** (`cd collector && python3 -m unittest discover -s tests`), все зелёные.
- Проверено вживую на домашнем инверторе (`TRANSPORT=tcp` → `192.168.31.110:9999`):
  опрос, парсинг, QPIRI, API, отказ при недопустимых значениях.
- **Не сделано:** мультиинвертор/мультисайт, авторизация UI (сейчас опциональный `API_TOKEN`),
  ретенция правил/истории правил, PV-прогноз по нескольким массивам.

## Документация

`README.md` — лендинг; подробности в `docs/`: ARCHITECTURE, INSTALL, CONFIGURATION, INVERTER, BATTERY,
STORAGE, API, MQTT, UI, INTEGRATIONS, OPERATIONS, TROUBLESHOOTING, DEVELOPMENT, CHANGELOG.
При изменении поведения обновлять соответствующий файл, а не только README.

## Быстрые команды

```bash
# на VDS
ssh root@192.168.31.115
cd /opt/solar-monitor && docker compose up -d --build
cd /opt/solar-monitor && docker compose logs -f collector

# локально
cd ~/solar-monitor
cp .env.example .env && $EDITOR .env     # SITE, TRANSPORT, MQTT_*, INFLUX_TOKEN
docker compose up -d --build
docker compose logs -f collector
curl -s localhost:8080/healthz | jq
curl -s localhost:8080/api/v1/state | jq .battery_state_of_charge
cd collector && python3 -m unittest discover -s tests     # тесты
python3 tools/make_dashboard.py                            # перегенерить дашборд
```

Смоук без Docker (проверка на живом инверторе, в HA ничего не публикует):

```bash
cd ~/solar-monitor/collector
env TRANSPORT=tcp TCP_HOST=192.168.31.110 POLL_INTERVAL=3 MQTT_HOST=127.0.0.1 \
    API_PORT=18080 SITE=test ENERGY_FILE=/tmp/sm_energy.json INFLUX_TOKEN= \
    python3 -m solar_monitor.main
```

## Устройство кода

| Файл | Роль |
|---|---|
| `solar_monitor/pi30.py` | кадры/CRC, парсеры QPIGS/QPIGS2/QPIRI/QMOD/QID/QPIWS, таблица метрик и записываемых настроек |
| `solar_monitor/transports.py` | `HidTransport` (hidraw или hidapi), `SerialTransport`, `TcpTransport`, `MqttTransport` |
| `solar_monitor/poller.py` | цикл опроса, суточные счётчики кВт·ч, очередь записей, watchdog |
| `solar_monitor/settings.py` | запись настроек + проверка чтением QPIRI (аналог `set_verified`) |
| `solar_monitor/publishers.py` | MQTT (SA-совместимые топики, HA discovery), InfluxDB line protocol |
| `solar_monitor/api.py` | `/healthz`, `/api/v1/{state,metrics,settings,history,reload_settings}` |
| `tools/make_dashboard.py` | генератор `grafana/dashboards/solar.json` (править дашборд только здесь) |
| `solar_monitor/webapp.py` | FastAPI: UI + JSON API + SSE (`sse_stream`), rules/forecast/backup |
| `solar_monitor/battery/` | драйверы BMS (jbd, daly, pylontech, modbus, vedirect, voltronic, can), emulated, каталог, store |
| `solar_monitor/rules.py` | правила: валидация, JSON-хранение, `evaluate()`, шаблоны `{metric}` |
| `solar_monitor/notifier.py` | Telegram / webhook / MQTT, rate-limit на канал |
| `solar_monitor/forecast.py` | forecast.solar → `pv_power_forecast` в Influx + состояние |
| `solar_monitor/sa_source.py` | импорт SolarAssistant (`TRANSPORT=sa-mqtt`), маппинг топиков, set через SA |
| `solar_monitor/sites.py` | мультисайт: сбор `<root>/+/state|status` с брокера, TTL, сводка |
| `solar_monitor/web/static/` | `index.html` (SPA), `app.js`, `styles.css`, вендоренный `uplot.min.js` |

## Грабли (проверено на железе)

- **Биты статуса QPIGS идут b7→b0 слева направо**, т.е. bit0 — ПОСЛЕДНИЙ символ.
  Старый `~/inverter-mqtt/bridge.py` читал их как обычное число → ложный `battery_low`.
- **QPIWS может склеиться из двух кадров** с валидным CRC (UART делят несколько опросчиков).
  Парсер принимает только ровно 40 символов 0/1, иначе `{}` → значение не обновляется.
- **Кадр `QPIGS2` может склеиться** с другим ответом и пройти CRC (видели «11 510 Вт» на массиве 40 Вт):
  в `parse_qpigs2()` проверяется P ≈ U·I, плюс `pi30.sanitize()` отбрасывает физически невозможные значения.
- Проверка правил: демо-правило `pv_power > 10` через 5 с сработало и отправилось в MQTT
  (`solar/home/notify`) с подстановкой `{pv_power}`/`{battery_state_of_charge}` — пайплайн рабочий.
- Колбэки MQTT-подписок теперь получают `(topic, payload)` — иначе нельзя понять, с какого
  сайта пришло состояние (`transports.MqttTransport`, правила, `sites.SiteRegistry`).
- Удаление retained-сообщения сайта не приходит подписчику как событие: реестр забывает сайт
  по `SITE_TTL` (900 с), а не мгновенно.
- Чужой кадр на общем UART (ESP32/SA) раньше принимался за `(NAK)` → `apply_setting` ретраит,
  пока не получит именно ACK/NAK.
- Смена протокола BMS пишется на живой инвертор (`PBTnn`) — тесты идут на фейковом инверторе,
  который реально меняет код в QPIRI; на железе проверять только с включённым откатом.
- **Battery type у Voltronic — это не химия, а протокол BMS** (поле 13 QPIRI, 10 значений;
  карта взята из pi30 mpp-solar). `QBMS` отдаёт то, что инвертор прочитал от батареи
  (SOC, bulk/float/cutoff, макс. токи, запреты) — у домашнего 11 кВт: «LIb-protocol compatible»,
  BMS Connected, SOC 80 %, 57.6/44.8 В, 150/220 А.
- Каталог АКБ — точная копия групп SolarAssistant из его документации (`battery/catalog.py`);
  JK RS485 намеренно помечен `supported: False` (протокол не реализован) — API отвечает
  `«…»: протокол пока не реализован`, а не молча ничего не читает.
- BMS-значения нужно **переприменять после каждой сборки состояния** (`battery.reapply()`),
  иначе инверторные значения затирают их каждый цикл (баг был поймал на emulated: SoC 87 → 100).
- JBD отдаёт температуру по-разному: 1 байт с offset 40 (по умолчанию), 1 байт 0.1 K или 2 байта
  0.1 K — переключается `BMS_JBD_TEMP`; без реального BMS это главный источник расхождений.
- Регулярка Flux: `range(start: now(), stop: +2d)` не поддерживается — писать `stop: 2d`.
- InfluxDB 2.x `/api/v2/delete` не понимает `>` в предикате — удалять окно по времени через `influx delete`.
- Прошивки расходятся в командах записи (`MNCHGC0nnn` против `MCHGCnnn`) — переопределяется
  через `SETTINGS_JSON`, код править не нужно.
- `paho-mqtt` 2.x требует `CallbackAPIVersion` — в `publishers.new_client()` есть фолбэк на 1.x.
- Домашний инвертор: 11 кВт, 48 В, S/N `96342404105016`, `QPIGS` отдаёт 24 поля,
  второй MPPT пустой (`QPIGS2` = нули). Офисный (SolarAssistant на Orange Pi) — другой,
  там два MPPT и нативный USB-HID.
- **Synology ≠ хост для InfluxDB 2.x**: проверено, висит в D-state (и bind-mount, и named volume).
  Для NAS есть `docker-compose.synology.yml` (InfluxDB 1.8 + InfluxQL) и
  `INFLUX_MODE=1.8 python3 tools/make_dashboard.py`; но лучше БД держать на VDS/mini PC.
- Grafana в контейнере пишет от uid **472** → `chown -R 472:472 data/grafana`, иначе crash-loop.
- `INFLUX_MODE=2` (Flux, по умолчанию) или `1.8` (InfluxQL): переключается в `.env`,
  для 1.8 нужен ещё отдельный datasource (`grafana/provisioning-1x/`).
