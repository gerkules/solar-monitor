# Эксплуатация

## Ежедневные команды

```bash
docker compose ps                       # состояние
docker compose logs -f collector        # живой лог: режим, сеть, АКБ, нагрузка, PV, warnings
curl -s localhost:8080/healthz | jq     # health + счётчики
curl -s localhost:8080/api/v1/state | jq '.device_mode, .battery_state_of_charge'
```

Лог опроса выглядит так:

```
poller  Battery | grid 230.9V 0W | batt 52.9V 81% -211W | load 187W | pv 34W |
```

## Health-метрики

`/healthz` отдаёт: `ok`, `online`, `age_s`, `consecutive_failures`, `uptime_s`, `transport`,
`mqtt_connected`, `mqtt_restarts`, `influx_written`, `influx_errors`, `rx`, `tx`.
`ok=false` при отсутствии свежих данных — это и есть docker healthcheck.

## Тесты

```bash
cd collector && python3 -m unittest discover -s tests -v
```

179 тестов: PI30 (кадры, парсеры, уставки), транспорты (включая фейковый TCP-инвертор и HID-упаковку),
BMS-драйверы, правила, уведомления, прогноз, импорт SA, мультисайт, веб/API и прокси.

## Резервное копирование

```bash
tar czf solar-$(date +%F).tgz data/collector .env
docker compose exec influxdb influx backup /tmp/influx-backup && docker compose cp influxdb:/tmp/influx-backup ./influx-backup
```

## Обновление

```bash
git pull
docker compose up -d --build
```

Сохранённые в UI настройки (`/data/*.json`) и история не теряются. После обновления статика
получает новый `?v=` — браузер не держит старые файлы.

## Нагрузка и ресурсы

* Коллектор: ~60–80 МБ RAM, CPU почти idle.
* Полный стек (collector + InfluxDB + Grafana): ~1 ГБ RAM — хватает 2 ГБ VDS.
* Grafana: 22 панели, запросы Flux по 30-дневному retention — секунды.

## Проверка подозрений по данным

```bash
# максимумы метрик за 2 часа (ловим выбросы)
docker compose exec influxdb influx query \
  'from(bucket:"solar") |> range(start:-2h) |> filter(fn:(r)=>r._measurement=="pv_power") |> max()' \
  --org solar --token "$INFLUX_TOKEN"
```

Коллектор сам отбрасывает физически невозможные значения и пишет в лог
`QPIGS: implausible values dropped: …`.

## Диагностика конкретного сайта

```bash
curl -s "localhost:8080/api/v1/state?site=office"     | jq '.device_mode'
curl -s "localhost:8080/api/v1/settings?site=office"  | jq '.[0]'
curl -s "localhost:8080/api/v1/connection?site=office"| jq '.transport, .switchable'
```
