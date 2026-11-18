# Что уже было сделано на ESP32 (анализ `WD4/AI`, 18.11.2026)

Прежде чем писать `firmware/esp32/` (MicroPython-узел), был разобран архив проектов
на NAS — чтобы не изобретать заново и понимать, что брать готовым.

## Инвентаризация

| Каталог | Что это | Объём | Состояние |
|---|---|---|---|
| `esp32invertormonitornovyi` | **основной прод**: PI30 по RS232 + CAN BMS (JK), веб-UI, OTA, профили прошивок | `.ino` 1485 + `app/*.inc` 2378 + ESP8266-lite 568 ≈ 4.6 k строк | FW 118 → **119 (MQTT)**, 195 каталогов бэкапов, бинарники с sha256, **не в git** |
| `solarassistantesp32` / `…321` | Modbus RTU: Deye/SunSynk/Sol-Ark/EG4/Growatt + Voltronic, BMS по Modbus | 2059 строк, модульный C++ | два почти одинаковых каталога (различия в 8 файлах), не в git |
| `arduino/esp32s3usbklientFinal`, `Solar-S3-Pro` | USB-HID клиент к USB-порту инвертора (обход занятого донглом порта) | — | |
| `OpenMonitoring_V42_MultiProtocol` | 5 `.ino`, отправка в стороннее облако HTTP GET с приватным ключом | — | чужой сервис, наружу не выпускать |
| `a2527_bms` | BMS field guide 19 КБ + `esp32_bms` | — | |
| `EW10.xml` | дамп/описание протокола донгла EW10 | — | |

## Что умеет основной проект (и чего нет у MicroPython-прошивки)

1. **CAN BMS listen-only 500 кбит/с**: разбор `0x351/0x356/0x359/0x35C/0x35E` — SOC, SOH,
   V, A, W, T, лимиты заряда/разряда; выбор источника батареи `CAN_FIRST` / `INVERTER` /
   `CAN_ONLY`. В MicroPython CAN (TWAI) недоступен без native-модуля — поэтому это
   остаётся только в Arduino-версии.
2. **Профили**: `inverterProfile` / `controlProfile` / `commandProfile` / `supportedWrites`,
   блокировки неподтверждённых команд («Blocked: solar only is not confirmed for this
   Axpert profile»).
3. **Проверка записи по QPIRI** (`verify*Expected`): ACK без применения не считается успехом.
4. **OTA из браузера** (`/ota`), скан и настройка Wi-Fi из UI.
5. **Command lab + command log**: ручные команды и журнал результатов/ответов.
6. **Диагностика линии**: tx/rx, CRC-ошибки, таймауты, занятость шины, heap.
7. **История и энергия**: RAM+SPIFFS, сутки/неделя по PV/нагрузке/сети/заряду, CSV.
8. **Три платформы**: `esp32dev`, `esp32-s3` (`RX 4 / TX 5`), **ESP8266 lite** (568 строк).
9. **Reverse-агент**: `GET /api/v2/next?device_id=…` + `POST /api/v1/push` с Bearer-токеном.

## Слабости, которые стоит знать

- До FW 119 **не было MQTT**: данные жили только внутри устройства (+ приватный HTTP-агент).
- Веб-UI — строки C++ в `.ino` (одна строка JS на 3000+ символов): тяжело править и локализовать.
- Нет git: 195 каталогов `backups/` вместо истории; тестов нет.
- Приватный reverse-агент работает по plain HTTP — только в локалке.

## Как FW 119 стыкуется с сервером

Прошивка публикует ровно те топики, что и серверный коллектор:

```
<prefix>/state                          ← JSON состояния (как /api/v1/state)
<prefix>/inverter_1/<key>/state         ← по метрике (как publishers.metric_topic)
<prefix>/inverter_1/<key>/set           ← запись уставки (как publishers.set_topic)
<prefix>/status                         ← online/offline (LWT)
```

Поэтому Home Assistant, MQTT-шаблоны и Grafana-дашборды не различают «сервер» и «ESP32»:
достаточно совпадения `MQTT_PREFIX`. Один инвертор — один поллер: либо сервер читает
донгл, либо ESP32 читает RS232, одновременно нельзя.

Справочник по FW 119: `docs/FW119_MQTT.md` в проекте `esp32invertormonitornovyi`.

## Что осталось на будущее (не сделано)

- [ ] `git init` для `esp32invertormonitornovyi` и `solarassistantesp32`, публикация без секретов
      (Wi-Fi, `remoteAgent.token` → `.gitignore`/`secrets.h`).
- [ ] Приёмник `/api/v1/push` в сервере — если захочется оставить и reverse-агент.
- [ ] Перенести `firmware/esp32` (MicroPython) на общий брокер как «лёгкий узел» для
      второго инвертора без CAN.
