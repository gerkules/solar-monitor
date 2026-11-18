# REST API

Базовый адрес: `http://<host>:8080`. Полная интерактивная схема — `/api/docs` (Swagger) и
`/api/openapi.json`.

Авторизация опциональна:
* `API_TOKEN` → заголовок `Authorization: Bearer <token>` (или `?token=`);
* `AUTH_USER`/`AUTH_PASSWORD` → HTTP Basic на всё, кроме `/healthz`.

Мультисайт: любой `/api/v1/...` принимает `?site=<peer>` — запрос уходит на API соседнего
коллектора (см. `PEER_SITES` в [CONFIGURATION.md](CONFIGURATION.md)).

## Состояние и метрики

| Метод | Путь | Описание |
|---|---|---|
| GET | `/healthz` | 200/503 + `online`, `age_s`, `rx/tx`, `influx_written/errors`, `mqtt_restarts`, `transport` |
| GET | `/api/v1/state` | полный снимок состояния (JSON) |
| GET | `/api/v1/stream` | SSE-поток состояния (`event: state`) |
| GET | `/api/v1/metrics?topic=inverter_1/battery*` | список метрик `{topic, group, name, value, unit}` |
| GET | `/api/v1/metrics?topic=inverter_1/battery_voltage&value=1` | одно значение текстом |
| GET | `/api/v1/info` | то же, что `/healthz` |
| GET | `/api/v1/meta` | метаданные UI: метрики, единицы, схема настроек, список сайтов |
| GET | `/api/v1/sites` | все сайты из retained-состояний на брокере |

```bash
curl -s localhost:8080/api/v1/state | jq '.battery_state_of_charge, .pv_power'
curl -s "localhost:8080/api/v1/metrics?topic=inverter_1/pv*" | jq
curl -N localhost:8080/api/v1/stream        # живой поток
```

## История и энергия

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/history?topic=inverter_1/pv_power&from=-24h&group_by=5m&agg=mean` | точки `[[iso, value], …]` |
| GET | `/api/v1/energy?from=-7d` | `{pv, load, grid, battery_charge, battery_discharge}` в кВт·ч |
| GET | `/api/v1/export?metric=pv_power&from=-24h` | CSV `time,metric,value` |
| GET | `/api/v1/forecast` | прогноз PV: `{enabled, points, today_kwh, updated, last_error}` |
| POST | `/api/v1/forecast/refresh` | принудительно обновить прогноз |

`agg`: `mean` (по умолчанию), `max`, `min`, `sum`, `last`. `group_by`: `10s`, `1m`, `15m`, `1h`, `1d`.

## Уставки инвертора

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/settings` | 10 параметров: `key`, `name`, `kind`, `value`, `options`/`min/max/step` |
| POST | `/api/v1/settings` | `{"key","value","verified":true}` → `{ok, message, readback}` |
| POST | `/api/v1/reload_settings` | перечитать `QPIRI` |
| GET | `/api/v1/backup` | JSON: уставки + паспорт + суточные счётчики |
| POST | `/api/v1/restore` | `{"settings":{...}}` → применить всё с проверкой |

```bash
curl -s -X POST localhost:8080/api/v1/settings -H 'Content-Type: application/json' \
  -d '{"key":"output_source_priority","value":"Solar first","verified":true}'
# {"ok":true,"key":"output_source_priority","cmd":"POP01","value":"Solar first","message":"Saved"}
```

## Подключение к инвертору

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/connection` | текущий транспорт, режимы, найденные порты, статистика |
| POST | `/api/v1/connection/probe` | `{"mode":"tcp","tcp_host":"…","tcp_port":9999}` → результат опроса |
| PUT | `/api/v1/connection` | применить (на лету); для источника `sa-mqtt` — переключит на прямое и перезапустит коллектор |

```bash
curl -s localhost:8080/api/v1/connection | jq '.transport, .ports'
curl -s -X POST localhost:8080/api/v1/connection/probe -H 'Content-Type: application/json' \
  -d '{"mode":"tcp","tcp_host":"192.168.1.60","tcp_port":9999}'
```

## Батарея

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/battery` | источник, драйвер, последние значения `bms_*` |
| GET | `/api/v1/battery/sources` | доступные драйверы |
| GET | `/api/v1/battery/config` | текущий выбор + каталог 67 позиций + найденные порты |
| PUT | `/api/v1/battery/config` | `{"brand":"pylontech-rs232-console-port","port":"/dev/ttyUSB1"}` |
| GET | `/api/v1/battery/protocol` | протокол BMS инвертора, флаги, `bms_down_s`, `warning_69` |
| POST | `/api/v1/battery/protocol/confirm` | подтвердить смену протокола |
| POST | `/api/v1/battery/protocol/cancel` | откатить протокол |
| GET | `/api/v1/battery/events?limit=30&hours=24` | журнал кодов + сводка |

## Автоматизация и уведомления

| Метод | Путь | Описание |
|---|---|---|
| GET | `/api/v1/rules` | правила + каналы уведомлений + счётчик срабатываний |
| POST | `/api/v1/rules` | добавить правило |
| PUT | `/api/v1/rules/{id}` | изменить |
| DELETE | `/api/v1/rules/{id}` | удалить |
| POST | `/api/v1/rules/{id}/toggle` | `{"enabled":false}` |
| GET | `/api/v1/rules/examples` | три готовых примера |
| POST | `/api/v1/notify/test` | тестовое уведомление во все каналы |

```bash
curl -s -X POST localhost:8080/api/v1/rules -H 'Content-Type: application/json' -d '{
  "name":"АКБ разряжена",
  "when":{"metric":"battery_state_of_charge","op":"<","value":25,"for_s":60},
  "then":[{"type":"notify","text":"АКБ {battery_state_of_charge}%"}],
  "cooldown_s":1800}'
```

## Справочник кодов

`GET /api/v1/codes` → `{faults:[…], warnings:[…], bms:[…], parallel:[…], note}`.

## Коды ошибок

| Код | Когда |
|---|---|
| 400 | неверные параметры (например неизвестный ключ настройки) |
| 401 | требуется токен/Basic |
| 404 | нет такого endpoint/сайта |
| 409 | операция недоступна для текущего источника (например смена транспорта при `sa-mqtt`) |
| 422 | инвертор отклонил или не применил значение |
| 501 | функция выключена (история без InfluxDB, автоматизация и т.п.) |
| 502 | ошибка внешнего сервиса (InfluxDB, соседний сайт) |
