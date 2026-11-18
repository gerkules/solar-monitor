# Интеграции

## Home Assistant

1. Настройте MQTT-интеграцию на свой брокер (тот же, что в `MQTT_HOST`).
2. Коллектор сам опубликует discovery — устройства появятся в разделе MQTT.
3. Сущности: `sensor.<prefix>_<metric>`, `binary_sensor.<prefix>_mains_ok`,
   `select.<prefix>_<setting>`, `number.<prefix>_<setting>`, `button.<prefix>_reload_settings`.

Отключить: `HA_DISCOVERY=false` (полезно для тестовых сайтов, чтобы не плодить сущности).

## Импорт из SolarAssistant (`TRANSPORT=sa-mqtt`)

Позволяет забрать данные из уже работающей SolarAssistant, **не отбирая у неё USB-порт**:

```dotenv
SITE=office
TRANSPORT=sa-mqtt
SA_MQTT_HOST=192.168.1.134
MQTT_PREFIX=solar/office
```

Что импортируется: телеметрия `inverter_1/*`, уставки как read-only, `total/*` как резерв
(SOC, battery_power). Запись уставок проксируется в `.../set_verified` SolarAssistant — работает,
только если на её стороне включено «Allow setting changes». Суточные кВт·ч считает наш коллектор.

Переход на прямое подключение: UI → «Подключение» → выбрать транспорт → «Применить»
(коллектор перезапустится и будет читать инвертор сам).

## Несколько сайтов

Каждый коллектор публикует состояние в `<SITE_ROOT>/<site>/state` (retained). UI подписан на
`<SITE_ROOT>/+/state`, поэтому видит все сайты; переключение — селектор в шапке.

Чтобы из UI одного сайта управлять другим (уставки, подключение), пропишите адреса API:

```dotenv
PEER_SITES={"home":"http://192.168.31.115:8080","office":"http://192.168.31.115:8081"}
```

Запросы `?site=office` проксируются на API соседа. Важно: запись уставок и смена транспорта
выполняются **на стороне того коллектора**, а не локального.

## Автоматизация

Правила хранятся в `/data/rules.json`, проверяются каждый цикл опроса:

```json
{
  "name": "АКБ разряжена",
  "when": {"metric": "battery_state_of_charge", "op": "<", "value": 25, "for_s": 60},
  "then": [{"type": "notify", "text": "⚠️ АКБ {battery_state_of_charge}%"}],
  "cooldown_s": 1800
}
```

* `op`: `<`, `<=`, `>`, `>=`, `==`, `!=` (для строк — `device_mode`, `warnings`);
* `for_s` — условие должно держаться N секунд; `cooldown_s` — не чаще;
* действия: `notify` (шаблон `{metric}`), `set` (`key`, `value`, проверка чтением), `mqtt` (`topic`, `payload`).

Системные оповещения: «нет связи» (после `OFFLINE_AFTER`) и «связь восстановлена» уходят во все каналы.

## Уведомления

| Канал | Переменные |
|---|---|
| Telegram | `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` |
| Webhook | `WEBHOOK_URL` (POST JSON `{text, site, ts, source}`) |
| MQTT | всегда: `<prefix>/notify` |

`NOTIFY_MIN_INTERVAL` (60 с) ограничивает частоту на канал; кнопка «Тест уведомлений» и
`POST /api/v1/notify/test` отправляют принудительно.

## Прогноз PV

`FORECAST_ENABLED=true` + координаты и мощность. Раз в час опрашивается forecast.solar; точки
пишутся в InfluxDB как `pv_power_forecast` (будущие метки), на «Обзоре» рисуется пунктиром.

**Ограничение бесплатного тарифа: ~12 запросов в час на IP.** Поэтому последний удачный прогноз
кэшируется в `/data/forecast.json` (переживает перезапуск), а на ответ `429` сервис делает паузу
30 минут. Симптом «нет линии прогноза» = исчерпан лимит: смотрите `last_error` в `/api/v1/forecast`.
