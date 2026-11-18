---
name: Баг-репорт
about: Что-то работает не так (данные, подключение, UI, запись уставок)
title: ""
labels: bug
---

## Что происходит
<!-- коротко: что ожидали и что получили -->

## Инвертор и прошивка
| | |
|---|---|
| Модель / бренд | напр. Axpert VM II 11 кВт |
| Прошивка (`QVFW`) | напр. `VERFW:00078.07` |
| Протокол (`QPI`) | напр. `PI30` |
| Второй MPPT | да / нет |
| Батарея и протокол BMS (поле 13 QPIRI) | напр. LIb-protocol compatible / Pylontech |

## Как подключено
- [ ] USB-HID
- [ ] USB-RS232 / RS485
- [ ] TCP (донгл EW10 / ser2net / ESP32 / usbip)
- [ ] MQTT-сокет EW10
- [ ] импорт из SolarAssistant (`sa-mqtt`)

## Версия
- коммит/тег:
- как запущено (Docker Compose / вручную):
- ОС и версия Docker:

## Логи
```
docker compose logs --tail 100 collector
```

## Диагностика (полезно приложить)
```bash
curl -s localhost:8080/healthz | jq
curl -s localhost:8080/api/v1/state | jq
curl -s localhost:8080/api/v1/connection | jq
curl -s localhost:8080/api/v1/battery | jq
```

## Что уже пробовали
<!-- например: менял BMS_BAUD, проверял «Проверить связь», перезапускал контейнер -->
