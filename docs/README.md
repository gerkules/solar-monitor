# Документация solar-monitor

Навигация по документации. Начинать лучше с [INSTALL.md](INSTALL.md), если нужен работающий экземпляр,
и с [ARCHITECTURE.md](ARCHITECTURE.md), если нужно понять, как это устроено.

| Документ | О чём |
|---|---|
| [ARCHITECTURE.md](ARCHITECTURE.md) | компоненты, поток данных, ключевые решения и почему так |
| [INSTALL.md](INSTALL.md) | установка: mini PC, VDS, NAS, Docker; проброс USB; compose-варианты |
| [CONFIGURATION.md](CONFIGURATION.md) | все переменные `.env` по группам, значения по умолчанию |
| [INVERTER.md](INVERTER.md) | протокол PI30, транспорты, уставки, коды 60/62/69/70/71, R61 |
| [BATTERY.md](BATTERY.md) | источники данных АКБ: каталог 67 позиций, драйверы, ограничения |
| [STORAGE.md](STORAGE.md) | схема InfluxDB, retention, downsampling, Grafana |
| [API.md](API.md) | REST API: эндпоинты, параметры, примеры `curl` |
| [MQTT.md](MQTT.md) | раскладка топиков, Home Assistant discovery, запись уставок |
| [UI.md](UI.md) | страницы, темы, языки, графики, экспорт |
| [INTEGRATIONS.md](INTEGRATIONS.md) | Home Assistant, импорт SolarAssistant, мультисайт, правила, уведомления, прогноз |
| [SECURITY.md](SECURITY.md) | авторизация, HTTPS, мультисайт, инфраструктура |
| [OPERATIONS.md](OPERATIONS.md) | логи, health, тесты, бэкапы, обновление, диагностика |
| [TROUBLESHOOTING.md](TROUBLESHOOTING.md) | известные проблемы и их решения (с фактами из практики) |
| [DEVELOPMENT.md](DEVELOPMENT.md) | структура кода, как добавить метрику/язык/драйвер, тесты, скриншоты |
| [CHANGELOG.md](CHANGELOG.md) | история итераций |
| [EXISTING-ESP32.md](EXISTING-ESP32.md) | что уже сделано на ESP32 (анализ архива `WD4/AI`) и как прошивка FW 119 стыкуется с сервером |

## Что это коротко

`solar-monitor` — открытый аналог SolarAssistant для инверторов **Voltronic / Axpert (PI30)**:
опрос инвертора → MQTT + InfluxDB → веб-интерфейс, графики, уставки, правила, уведомления,
прогноз PV. Один стек в Docker, ставится на mini PC, VDS или NAS; поддерживает несколько
сайтов (инверторов) в одном UI.

Плюс автономная прошивка ESP32 ([`../firmware/esp32/`](../firmware/esp32/README.md)) — узел без сервера:
сам опрашивает инвертор, отдаёт веб-интерфейс и публикует те же MQTT-топики.

## Соглашения

* «Сайт» (site) — один инвертор + его коллектор. ID сайта попадает в топики MQTT, тег InfluxDB,
  префикс сущностей Home Assistant и в выбор сайта в шапке UI.
* «Коллектор» — контейнер `collector`: опрашивает инвертор, публикует данные, отдаёт API и UI.
* Все секреты живут только в `.env` (и в `/data/*.json` для выбранных в UI настроек), в документации
  их нет.
