# MQTT

## Раскладка топиков

Префикс сайта — `MQTT_PREFIX` (по умолчанию `solar/<site>`).

| Топик | Retain | Что |
|---|---|---|
| `<prefix>/state` | да (если `STATE_RETAIN=true`) | полное состояние одним JSON |
| `<prefix>/status` | да | `online`/`offline` (LWT, `OFFLINE_AFTER`) |
| `<prefix>/inverter_1/<metric>/state` | нет | отдельное значение (телеметрия) |
| `<prefix>/inverter_1/<setting>/state` | да | текущее значение уставки |
| `<prefix>/inverter_1/<setting>/set` | — | запись уставки (без проверки) |
| `<prefix>/inverter_1/<setting>/set_verified` | — | запись с проверкой чтением QPIRI |
| `<prefix>/set/response_message/state` | да | ответ на запись: `Saved` / `Error: …` |
| `<prefix>/reload_settings` | — | перечитать QPIRI (payload `PRESS`) |
| `<prefix>/notify` | нет | уведомления (`{"text","ts"}`) |
| `<prefix>/forecast/pv_power_today` | да | прогноз на сегодня, кВт·ч |

Метрики (`inverter_1/…`): `grid_voltage`, `grid_frequency`, `grid_power`, `ac_output_voltage`,
`ac_output_frequency`, `load_power`, `load_apparent_power`, `load_percentage`, `bus_voltage`,
`battery_voltage`, `battery_current`, `battery_power`, `battery_state_of_charge`, `temperature`,
`pv_voltage_1/2`, `pv_current_1/2`, `pv_power_1/2`, `pv_power`, `device_mode`, `warnings`,
`pv_energy_today`, `load_energy_today`, `grid_energy_today`, `battery_charge_today`,
`battery_discharge_today`, `bms_code`, `inverter_bms_*`.

## Запись уставок

```bash
mosquitto_pub -h <broker> -t 'solar/home/inverter_1/battery_float_charge_voltage/set_verified' -m '55.2'
mosquitto_sub -h <broker> -t 'solar/home/set/response_message/state' -C 1   # → Saved | Error: …
```

`set_verified` проверяет результат чтением `QPIRI` (до 3 попыток). Если инвертор принял команду, но
значение не изменилось — вернётся `Error: The inverter acknowledged the value but did not apply it`.

## Мост в другой брокер (вариант SolarAssistant)

```conf
connection SolarAssistant
address 192.168.1.70
topic solar_assistant/+/+/state in
topic homeassistant/# in
topic solar_assistant/+/+/set out
```

Для этого проекта аналогично: `topic solar/+/+/state in`, `topic homeassistant/# in`.

## Home Assistant

Discovery публикуется на `<HA_DISCOVERY_PREFIX>/<component>/<ENTITY_PREFIX>_<key>/config`:

| Компонент | Что |
|---|---|
| `sensor` | телеметрия, счётчики энергии, паспортные значения |
| `binary_sensor` | наличие сети (`mains_ok`) |
| `select` | приоритеты, тип АКБ |
| `number` | токи и напряжения уставок |
| `button` | «Re-read settings» |

Доступность привязана к `<prefix>/status`, поэтому в HA сущности корректно становятся
`unavailable`, когда инвертор пропадает.

Отключить публикацию discovery (например для тестового сайта): `HA_DISCOVERY=false`.
