# solar-monitor

[![CI](https://github.com/gerkules/solar-monitor/actions/workflows/ci.yml/badge.svg)](https://github.com/gerkules/solar-monitor/actions/workflows/ci.yml)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
![Python 3.9+](https://img.shields.io/badge/python-3.9%2B-blue)

Открытый аналог **SolarAssistant** для инверторов **Voltronic / Axpert (протокол PI30)** в Docker:
опрос инвертора → MQTT + InfluxDB → веб-интерфейс, графики, уставки, правила, уведомления, прогноз PV.
Ставится на **mini PC, VDS или NAS**; поддерживает несколько сайтов (инверторов) в одном UI.

<p align="center">
  <em>Обзор: схема потоков с иконками, gauge-индикаторы, энергия за сегодня, состояние</em>
</p>

## Возможности

| Блок | Что умеет |
|---|---|
| **Связь с инвертором** | USB-HID (нативный USB), USB-RS232/RS485, TCP (донгл EW10, ser2net, ESP32, usbip), MQTT-сокет EW10, **импорт из SolarAssistant**; переключение в UI без перезапуска, кнопка «Проверить связь» |
| **Данные** | PI30: `QPIGS`/`QPIGS2` (два MPPT), `QPIRI`, `QMOD`, `QPIWS`, `QBMS`; валидация кадров против чужого трафика на общем UART; физически невозможные значения отбрасываются |
| **История** | InfluxDB 2.x (Flux) или 1.8 (InfluxQL), retention, часовые агрегаты; Grafana с 22 панелями |
| **Веб-интерфейс** | «Обзор» (схема + gauge + энергия), «Сеть», «Энергия», «Графики» (обзор + 14 графиков, зум синхронно, экспорт PNG/CSV), «Инвертор», «АКБ», «Подключение», «Автоматизация», «Коды», «Уставки». Светлая/тёмная тема, RU/EN/EL |
| **Уставки** | 10 параметров с записью и **проверкой чтением** QPIRI (приоритеты, токи, напряжения, тип АКБ/BMS-протокол) |
| **АКБ** | 67 источников данных АКБ (как в SolarAssistant) + эмуляция кулонометрией; драйверы JBD, Daly, Pylontech, Modbus, Victron VE.Direct, CAN, Voltronic LIB; журнал кодов BMS |
| **Автоматизация** | правила «условие → действие» с выдержкой и cooldown; действия: уведомить, записать уставку, опубликовать в MQTT |
| **Уведомления** | Telegram, webhook, MQTT; системные алерты «нет связи»/«связь восстановлена» |
| **Прогноз PV** | forecast.solar с кэшем (лимит 12 запросов/час) и линией на графике |
| **HA** | MQTT discovery: sensor/binary_sensor/select/number/button |
| **Мультисайт** | N инверторов = N коллекторов, один UI на все (селектор сайта, прокси API) |

## Быстрый старт

```bash
git clone <repo> ~/solar-monitor && cd ~/solar-monitor
cp .env.example .env          # SITE, TRANSPORT, MQTT_*, INFLUX_TOKEN, пароли
$EDITOR .env
docker compose up -d --build
```

* UI + API — `http://<host>:8080/`
* Grafana — `http://<host>:3000/` (папка **Solar**)
* health — `http://<host>:8080/healthz`

Минимум для старта:

```dotenv
SITE=home
TRANSPORT=tcp                 # hid | serial | tcp | mqtt | sa-mqtt
TCP_HOST=192.168.1.60
TCP_PORT=9999
MQTT_HOST=192.168.1.80
INFLUX_TOKEN=<сгенерируйте: openssl rand -hex 24>
INFLUX_PASSWORD=<пароль>
GRAFANA_PASSWORD=<пароль>
```

Установка на Synology, VDS, mini PC и проброс USB — [docs/INSTALL.md](docs/INSTALL.md).

## Документация

Полный комплект — в [`docs/`](docs/README.md):

| Документ | О чём |
|---|---|
| [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) | компоненты, поток данных, ключевые решения |
| [docs/INSTALL.md](docs/INSTALL.md) | mini PC / VDS / NAS, USB, второй сайт, обновление |
| [docs/CONFIGURATION.md](docs/CONFIGURATION.md) | все переменные `.env` по группам |
| [docs/INVERTER.md](docs/INVERTER.md) | PI30, транспорты, уставки, протоколы BMS, коды 60/62/69/70/71 |
| [docs/BATTERY.md](docs/BATTERY.md) | 67 источников АКБ, драйверы, ограничения |
| [docs/STORAGE.md](docs/STORAGE.md) | InfluxDB, retention, downsampling, Grafana, экспорт |
| [docs/API.md](docs/API.md) | REST API с примерами |
| [docs/MQTT.md](docs/MQTT.md) | топики, HA discovery, запись уставок |
| [docs/UI.md](docs/UI.md) | страницы, темы, языки, графики |
| [docs/INTEGRATIONS.md](docs/INTEGRATIONS.md) | HA, импорт SA, мультисайт, правила, уведомления, прогноз |
| [docs/SECURITY.md](docs/SECURITY.md) | авторизация, HTTPS, доступ по сети |
| [docs/OPERATIONS.md](docs/OPERATIONS.md) | логи, health, тесты, бэкап, обновление |
| [docs/TROUBLESHOOTING.md](docs/TROUBLESHOOTING.md) | известные проблемы с решениями |
| [docs/DEVELOPMENT.md](docs/DEVELOPMENT.md) | структура кода, как добавить метрику/язык/драйвер |
| [docs/CHANGELOG.md](docs/CHANGELOG.md) | история итераций |

## Структура репозитория

```
collector/            коллектор (Python): опрос, MQTT, InfluxDB, API, UI
  solar_monitor/      pi30, transports, poller, settings, battery/*, rules, forecast, webapp
  tests/              179 тестов
grafana/              provisioning + генератор дашборда (tools/make_dashboard.py)
influxdb/tasks/       часовые агрегаты (Flux)
docker-compose.yml    основной стек (collector + InfluxDB 2.x + Grafana)
docker-compose.office.yml        второй сайт
docker-compose.synology.yml      вариант для DSM (InfluxDB 1.8)
tools/                генератор дашборда, создание задач InfluxDB
docs/                 документация
```

## Проверено на реальном оборудовании

* Инвертор **Axpert 11 кВт** (S/N TEST000000000001), два MPPT, АКБ 48 В с BMS-протоколом
  `LIb-protocol compatible`: опрос по TCP через донгл EW10, `QBMS` (SOC 80 %, bulk 57.6 В,
  max charge 150 А), запись уставок с подтверждением.
* **SolarAssistant** (офисный инвертор): импорт через `sa-mqtt`, мультисайт в одном UI.
* Смена BMS-протокола на живом инверторе: провал `PBT03` → авто-откат (opt-in) → связь вернулась
  через 20–30 с.
* VDS 2 ядра / 1.9 ГБ: коллектор + InfluxDB + Grafana работают с запасом.

## Участие

PR и issue приветствуются: см. [CONTRIBUTING.md](CONTRIBUTING.md). Особенно полезны проверки
драйверов BMS на реальных батареях и протоколы уставок для нестандартных прошивок.

## Тесты

```bash
cd collector && python3 -m unittest discover -s tests      # 179 тестов
```

## Лицензия и оговорки

Проект независимый, не связан с SolarAssistant и Voltronic. Драйверы BMS покрыты тестами на
кадрах по спецификациям, но проверялись не на всех моделях батарей — будьте осторожны с записью
уставок на живом оборудовании (все операции чтения безопасны).
