# Разработка

## Структура

```
collector/
  solar_monitor/
    pi30.py          кадры/CRC, парсеры (QPIGS/QPIGS2/QPIRI/QMOD/QID/QPIWS/QBMS), метрики, уставки
    transports.py    HidTransport, SerialTransport, TcpTransport, MqttTransport
    connection.py    выбор транспорта (store + probe), список портов
    poller.py        цикл опроса, счётчики энергии, очередь записей, watchdog BMS/протокола
    settings.py      запись уставок + проверка чтением QPIRI
    energy.py        производные мощности, суточные кВт·ч
    publishers.py    MQTT (SA-совместимые топики, HA discovery) + InfluxDB line protocol
    rules.py         правила автоматизации (валидация, evaluate, шаблоны)
    notifier.py      Telegram / webhook / MQTT, rate-limit
    forecast.py      forecast.solar + кэш в /data/forecast.json
    sites.py         реестр сайтов по retained-состояниям
    sa_source.py     импорт из SolarAssistant (TRANSPORT=sa-mqtt)
    codes.py         справочник кодов из мануала Axpert MAX
    battery/         драйверы BMS (jbd, daly, pylontech, modbus, vedirect, can, voltronic),
                     каталог 67 источников, store выбора, журнал кодов, emulated
    webapp.py        FastAPI: API, SSE, прокси ?site=, статика SPA
    web/static/      index.html, app.js, i18n.js, styles.css, vendor (uPlot, Exo)
  tests/             179 тестов (unittest)
tools/
  make_dashboard.py  генератор Grafana-дашборда (Flux или InfluxQL)
  create-influx-tasks.sh  часовые агрегаты
```

## Как добавить метрику

1. `pi30.py`: добавить ключ в `METRICS` (имя, единица, класс, иконка) и, если нужно, в `SANE`
   (диапазон правдоподобности).
2. Если значение приходит новым кадром — добавить парсер и вызов в `poller.cycle()`.
3. MQTT/HA/история подхватятся автоматически (`publishers`/`influx` итерируются по `METRICS`).
4. Для графика — добавить запись в `CHARTS` в `app.js`.

## Как добавить перевод

`web/static/i18n.js`: добавить ключ во все три словаря (`ru`/`en`/`el`). Для статической разметки
достаточно текста на русском — он попадёт в `RU_MAP` автоматически (перевод по текстовым узлам).
Для динамики в `app.js` — использовать `t('key', {подстановки})`.

## Как добавить драйвер BMS

1. `battery/<name>.py`: класс наследник `BmsDriver` с `read()` → словарь `bms_*`
   (используйте `BmsDriver.post()` для производных значений, `SerialPort` для обмена).
2. Зарегистрировать в `battery/__init__.py` (`DRIVERS`, `SOURCES`).
3. Добавить позиции в `battery/catalog.py` (группа, бренды, `driver`).
4. Написать тест на разборе кадра (CRC/смещения) — реального железа может не быть.

## Как добавить транспорт

1. Класс наследник `transports.Transport` с `describe/_open/_write/_read_chunk/_reset`.
2. Ветка в `transports.make_transport()` и режим в `connection.MODES` (поля для UI).
3. Тест с фейковым устройством (см. `tests/test_transport.py`: FakeInverter по TCP).

## Тесты

```bash
cd collector
python3 -m unittest discover -s tests -v          # все
python3 -m unittest tests.test_poller -v          # один модуль
```

Правило: у каждого бага сначала тест, потом фикс (все проблемные случаи в этом проекте так и появились:
склеенные кадры, NAK из чужого кадра, ложный `battery_low`, гонка отрисовки графиков).

## Скриншоты UI (без ручного браузера)

Headless Chrome на macOS не даёт окно уже 500 px, поэтому для мобильных используется Playwright:

```bash
python3 -m pip install --user playwright && python3 -m playwright install chromium
python3 - <<'PY'
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    b = p.chromium.launch()
    pg = b.new_context(**p.devices["iPhone 12"]).new_page()
    pg.goto("http://192.168.1.50:8080/?theme=dark#/charts", wait_until="load")
    pg.wait_for_timeout(5000)
    pg.screenshot(path="/tmp/charts.png", full_page=True)
    b.close()
PY
```

Для десктопа: `b.new_context(viewport={"width": 1500, "height": 1000})`.
Важно: `wait_until="load"`, а не `networkidle` (SSE-поток не даёт странице «успокоиться»).

## Публикация на GitHub

Репозиторий уже подготовлен к публикации: есть `.gitignore` (исключает `.env`, `data/`, `.ref/`,
кэши), `LICENSE` (MIT) и `.env.office.example` как образец второго сайта.

```bash
cd ~/solar-monitor
git init
git add .
git commit -m "solar-monitor: initial public snapshot"
git branch -M main
git remote add origin git@github.com:<user>/solar-monitor.git
git push -u origin main
```

Проверьте перед push: `git status --ignored | head` — в индексе не должно быть `.env`,
`data/` и `.ref/`. Секреты живут только в `.env` и `/data/*.json` на рабочих машинах.

## Проверка перед коммитом

```bash
node --check collector/solar_monitor/web/static/app.js
node --check collector/solar_monitor/web/static/i18n.js
cd collector && python3 -m unittest discover -s tests
```
