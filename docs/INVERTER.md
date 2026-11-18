# Инвертор: протокол, подключение, уставки, коды

## Протокол PI30 (Voltronic / Axpert)

Кадр: ASCII, `CRC-16/XMODEM`, завершается `\r`; ответ — `(…<crc>\r` или `(ACK`/`(NAK`.
Используемые команды:

| Команда | Что даёт | Период |
|---|---|---|
| `QPIGS` | сеть, выход, нагрузка, АКБ, PV1, температуры, статус-биты | 5 с |
| `QPIGS2` | второй MPPT (ток/напряжение/мощность) | 5 с |
| `QPIRI` | уставки и паспорт (тип АКБ, токи, напряжения, тип машины, режим выхода) | 600 с |
| `QMOD` | режим (`P/S/L/B/F/H/D`) | 60 с |
| `QPIWS` | предупреждения (40 бит) | 60 с |
| `QBMS` | статус BMS от инвертора: связь, SOC, bulk/float/cutoff, макс. токи, запреты | 60 с |
| `QID` | серийный номер | при старте |
| `PBT`/`POP`/`PCP`/`PSDV`/`PBDV`/`PBCV`/`PCVV`/`PBFT` | запись уставок | по команде |

**Валидация ответов** (важно на общем UART, где параллельно опрашивают ESP32/SolarAssistant):
* CRC проверяется всегда;
* `QMOD` принимается только если ответ — ровно одна буква из известных режимов;
* `QID` — только 8–20 буквенно-цифровых;
* `QPIWS` — ровно 40 символов `0/1`;
* `QPIGS2` — проверяется согласованность `P ≈ U·I`;
* физически невозможные значения отбрасываются (`pi30.sanitize`).

## Транспорты

| `TRANSPORT` | Что нужно | Работает на VDS |
|---|---|---|
| `hid` | нативный USB-порт инвертора (`/dev/hidraw0`) | нет |
| `serial` | USB-RS232/RS485 адаптер (`2400 8N1`) | нет |
| `tcp` | донгл EW10 `:9999`, ser2net, ESP32, usbip | да |
| `mqtt` | EW10 в режиме MQTT-сокета (`<topic>/cmd`, `<topic>/data`) | да |
| `sa-mqtt` | импорт из работающей SolarAssistant | да |

Переключение — в UI (**Настройки → Подключение**) без перезапуска контейнера, с кнопкой
«Проверить связь» (опрос `QPIGS`+`QID`+`QPIRI`, показывается напряжение, нагрузка, S/N, мощность и
задержка). Выбор сохраняется в `/data/connection.json`.

## Уставки (10 параметров)

Каждая запись подтверждается чтением `QPIRI`; «Saved» без подтверждения не выдаётся.

| Параметр | Команда | Проверка |
|---|---|---|
| Output source priority | `POPnn` | output source priority |
| Charger source priority | `PCPnn` | charger source priority |
| Max charge current | `MNCHGC0nnn` | max charging current |
| Max grid charge current | `MUCHGCnnn` | max AC charging current |
| Shutdown battery voltage | `PSDVnn.n` | battery under voltage |
| Back to battery voltage | `PBDVnn.n` | re-discharge voltage |
| To grid battery voltage | `PBCVnn.n` | recharge voltage |
| Absorption charge voltage | `PCVVnn.n` | bulk voltage |
| Float charge voltage | `PBFTnn.n` | float voltage |
| **Battery type / BMS protocol** | `PBTnn` | battery type (поле 13 QPIRI) |

Прошивки расходятся в командах — переопределение без правки кода:
```dotenv
SETTINGS_JSON={"max_charge_current":{"cmd":"MCHGC{:03d}"},"lenient":false}
```

## Тип АКБ = протокол BMS инвертора

Поле 13 `QPIRI` — не химия, а протокол, по которому инвертор говорит с батареей (CAN/RS485):

| Код | Протокол |
|---|---|
| 0 | AGM |
| 1 | Flooded |
| 2 | User |
| 3 | Pylontech |
| 4 | Shinheung |
| 5 | WECO (48 В) |
| 6 | Soltaro (48 В) |
| 7 | TBD |
| 8 | LIb-protocol compatible |
| 9 | 3rd party Lithium |

Выбор — в **Настройках** и на странице **АКБ → «BMS инвертора (CAN / RS485)»**.

## Коды на дисплее (мануал Axpert MAX, «5. Code Reference»)

| Код | Значение | Поведение инвертора |
|---|---|---|
| 60 | BMS не разрешает заряд **и** разряд | останавливает оба |
| 62 | нет связи с BMS / изменилось число батарей (PYL/WEC/SOL) | buzzer через 3 мин, через 10 мин стоп заряда/разряда |
| 69 | BMS не разрешает заряд | прекращает заряд |
| 70 | BMS требует заряжать | заряжает по требованию BMS |
| 71 | BMS не разрешает разряд | прекращает разряд |

Коды вычисляются прямо из флагов `QBMS` (`stop_charge`/`stop_discharge`/`force_charge`) и пишутся
в журнал (`/data/bms_events.json`, измерение `bms_code` в InfluxDB). В UI — красный баннер,
на «АКБ» журнал с длительностями и сводка за сутки.

> Коды 60 и 71 встречаются дважды: в параллельной системе 60 = power feedback protection,
> 71 = несовпадение прошивок. Справочник кодов в приложении это учитывает.

**R61** — на некоторых прошивках так обозначают ошибку связи BMS; снимается выбором правильного
протокола либо режима User/AGM. В самой сборке SA (1.9.15) кода нет, в мануале Axpert MAX он не
описан — в приложении показываются коды из мануала.

## Ошибки и предупреждения

Полный справочник — страница **Коды** в приложении (`GET /api/v1/codes`): 19 ошибок
(01–13, 51–58), 9 предупреждений (01–32), 5 кодов BMS, 10 кодов параллельной системы,
с рекомендациями «что делать» и быстрыми действиями (User/AGM, перечитать настройки).

## Режимы (`QMOD`)

`P` Power on · `S` Standby · `L` Line · `B` Battery · `F` Fault · `H` Power saving · `D` Shutdown.
