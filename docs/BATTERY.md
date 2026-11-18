# Мониторинг АКБ

Два независимых механизма:

1. **Что говорит инвертор** (`QBMS`) — SOC, bulk/float/cutoff и лимиты, которые инвертор получил
   от батареи по CAN/RS485. Всегда включено, если прошивка поддерживает.
2. **Прямое чтение BMS** (этот документ) — когда к коллектору подключён адаптер к самой батарее
   (RS485/UART/CAN/VE.Direct). Даёт точные SOC/SOH/ток/температуру ячеек.

## Каталог источников (67 позиций, как в SolarAssistant)

**Настройки → АКБ → «Выбрать источник АКБ»**. Список повторяет группировку SolarAssistant:

| Группа | Драйвер | Позиций |
|---|---|---|
| Основное | `inverter`, `emulated` | 2 |
| USB Daly UART/RS485 | `daly` | 3 |
| USB JBD UART/RS485 | `jbd` | 3 |
| USB JK RS485 | — (протокол не реализован) | 1 |
| USB Modbus RS232/RS485 | `modbus` | 13 |
| USB Narada RS485 | `modbus` | 5 |
| USB Pylontech/Pytes console | `pylontech` | 4 |
| USB Serial RS232/RS485 | `modbus` | 24 |
| USB Voltronic LIB RS485 | `voltronic` | 8 |
| USB CAN bus | `can` | 3 |
| USB Victron VE.Direct | `vedirect` | 1 |

Позиция без драйвера (JK RS485) видна в списке, но недоступна — при попытке включить API отвечает
явной ошибкой, а не «тишиной».

## Драйверы

| Драйвер | Протокол | Особенности |
|---|---|---|
| `inverter` | — | значения инвертора (SOC по напряжению — неточно для Li) |
| `emulated` | кулонометрия | стартует от SOC инвертора и интегрирует `battery_power` при заданной ёмкости |
| `jbd` | UART/RS485 0x03 | кадр `DD … 77`, CRC16-XMODEM; температуры в 3 вариантах (`BMS_JBD_TEMP`) |
| `daly` | UART `A5 40 …` | ответ `D3`, проверка контрольной суммы |
| `pylontech` | RS232 console | команда `pwr`, парсинг «Volt/Curr/SOC/SOH» |
| `modbus` | Modbus RTU | карта регистров в `BMS_MODBUS` |
| `vedirect` | VE.Direct 19200 | шунт Victron BMV/SmartShunt |
| `can` | socketcan | Pylontech-класс: 0x355 SOC/SOH, 0x356 U/I/T, 0x359 protections |
| `voltronic` | PI30 по RS485 | батареи BlueNova/Felicity/Giter/Hubble и подобные |

Ключи состояния: `bms_soc`, `bms_soh`, `bms_voltage`, `bms_current`, `bms_power`,
`bms_temperature`, `bms_cells`, `bms_cell_min/max`, `bms_cycles`, `bms_capacity_ah`,
`bms_remaining_ah`, `bms_protections` + `battery_source`.
Если источник не `inverter`, его значения **перекрывают** показания инвертора.

## Карта регистров Modbus

```dotenv
BMS_MODBUS={"voltage":[256,0.01],"current":[258,0.1,"s16"],"soc":[260,1],"soh":[261,1],"temperature":[262,0.1,"s16"]}
```

Формат: `ключ: [адрес, масштаб, "s16"(опционально знаковый)]`. Адреса — те, что отдаёт
документация батареи; читается один непрерывный блок.

## ⚠️ Ограничения (честно)

* Драйверы покрыты юнит-тестами на кадрах по спецификациям (CRC, Modbus `C5 CD`, CAN-фреймы,
  VE.Direct, Pylontech-консоль), но **на реальном железе не проверялись** — адаптера и батареи
  в распоряжении не было.
* Если BMS не читается: сначала `BMS_PORT`/`BMS_BAUD` (Pylontech 115200, остальные обычно 9600),
  затем для JBD — `BMS_NTC_COUNT`/`BMS_JBD_TEMP`, для Modbus — карта регистров.
* `emulated` требует реальную ёмкость (`BATTERY_CAPACITY_AH`), иначе SOC будет уплывать.

## Коды BMS в журнале

Каждое изменение кода (60/62/69/70/71) пишется в `/data/bms_events.json` и в InfluxDB
(измерение `bms_code`). В UI: таблица «Время · Код · Значение · Длительность» + сводка за сутки.
API: `GET /api/v1/battery/events?limit=30&hours=24`.
