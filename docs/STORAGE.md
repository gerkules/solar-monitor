# Хранение данных и графики Grafana

## Схема InfluxDB

* Измерение (measurement) = метрика в snake_case: `pv_power`, `battery_voltage`, `grid_power`,
  `battery_state_of_charge`, `inverter_bms_soc`, `bms_code`, `pv_power_forecast`, …
* Поле — `value` (double).
* Тег — `site` (`home`, `office`, …) — так один бакет хранит несколько сайтов.
* Шаг записи = `POLL_INTERVAL` (5 с), шаг агрегации в графиках выбирается по периоду.

Объём: 30 метрик × 10 с ≈ 250 тыс. точек в сутки ≈ **1–2 МБ/сутки** (проверено: SolarAssistant с
10 с и 30 метриками занял 96 МБ за 9 месяцев).

## Retention и downsampling

* `INFLUX_RETENTION` (2.x) — срок жизни сырых данных (по умолчанию `30d`).
* Часовые агрегаты — задача Flux `influxdb/tasks/downsample_1h.flux`, создаётся один раз:
  ```bash
  ./tools/create-influx-tasks.sh
  ```
  Она складывает средние по часу в `*_hourly` измерения (аналог «hourly» у SolarAssistant).

## InfluxDB 1.8 (Synology)

```dotenv
INFLUX_MODE=1.8
INFLUX_DB=solar
```
Дашборд пересобрать: `INFLUX_MODE=1.8 python3 tools/make_dashboard.py` — панели будут на InfluxQL.

## Grafana

* Provisioning: `grafana/provisioning/` (datasource + провайдер дашбордов), дашборд —
  `grafana/dashboards/solar.json` (**генерируется**, не править руками).
* 22 панели: суточные кВт·ч, PV (сумма и по MPPT), нагрузка, сеть, АКБ (мощность/SOC/напряжение/ток),
  MPPT напряжение/ток, температура, bus/AC.
* Переменные дашборда: `bucket` (бакет) и `site` (список сайтов).
* Пересобрать дашборд: `python3 tools/make_dashboard.py` (или `INFLUX_MODE=1.8 …`).

## Экспорт данных

| Что | Как |
|---|---|
| CSV одной метрики | `/api/v1/export?metric=pv_power&from=-7d` |
| CSV графика из UI | кнопка **CSV** в заголовке графика |
| PNG графика | кнопка **PNG** |
| Полный дамп настроек | `/api/v1/backup` (JSON) |

## Бэкап

Минимальный набор для восстановления:

```bash
# данные коллектора (правила, счётчики, выбор подключения/АКБ, журнал кодов)
tar czf solar-monitor-data.tgz data/collector/
# история (InfluxDB) — штатным backup InfluxDB или снапшотом data/influxdb
```

`.env` в бэкап не входит по соображениям безопасности — храните его отдельно.
