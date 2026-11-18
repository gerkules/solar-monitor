# Прошивка solar-monitor для ESP32 / ESP32-C3

Самостоятельный узел: сам опрашивает инвертор по UART, сам показывает цифры в
браузере и сам публикует MQTT. VDS, InfluxDB и Grafana **не нужны** — но если сервер
есть, топики совпадают с серверными и Home Assistant видит устройство как обычно.

## Что умеет

| Возможность | Есть |
|---|---|
| PI30: `QPIGS`, `QPIGS2`, `QPIRI`, `QMOD`, `QPIWS`, `QID` | ✅ |
| Веб-интерфейс на самом ESP32 (`http://<ip>/`) | ✅ |
| Уставки: 10 шт. с записью и проверкой по `QPIRI` | ✅ |
| MQTT: JSON-состояние, по топику на метрику, HA discovery, LWT | ✅ |
| Запись уставок по MQTT (`.../inverter_1/<key>/set`) | ✅ |
| История в RAM (кольцо, по умолчанию сутки) | ✅ |
| BMS, прогноз PV, автоматизации, несколько площадок | ❌ (это на сервере) |

## Что нужно

* ESP32 (WROOM) или ESP32-C3 с 4 МБ flash — прошивка MicroPython.
* **RS232/RS485-модуль** (MAX3232 для RJ45-RS232 инвертора или MAX485 для RS485)
  либо USB-TTL, если цепляемся к USB-порту инвертора.
* Инвертор Voltronic/Axpert с протоколом PI30.

> Одна линия — один поллер. Если в инверторе уже стоит донгл EW10, он занимает порт:
> либо освободите его, либо вешайтесь на отдельный RS232-порт.

## Монтаж

```
ESP32 GPIO4 (TX) ──► MAX3232 R1IN      MAX3232 T1OUT ──► инвертор RS232 (RJ45, pin 3/5)
ESP32 GPIO5 (RX) ◄── MAX3232 R1OUT     MAX3232 R1IN  ◄── инвертор RS232 (RJ45, pin 6)
ESP32 GND        ──── MAX3232 GND      питание модуля — 3V3 ESP32
```

Параметры линии: **2400 бод, 8N1**, без flow control. Пин TX/RX и номер UART
задаются в `config.json` (`uart.tx` / `uart.rx` / `uart.id`). Для ESP32-C3 удобно
`tx=21, rx=20`; для классического ESP32 — `tx=4, rx=5` (значения по умолчанию).

## Прошивка

```bash
# 1) скачать MicroPython и залить (нужны esptool и mpremote, скрипт поставит их сам)
./tools/flash-esp32.sh --port /dev/tty.usbserial-0001 --chip esp32c3

# 2) на устройстве отредактировать config.json (Wi-Fi, MQTT, пины)
mpremote connect /dev/tty.usbserial-0001 fs cat :config.json

# 3) перезагрузить
mpremote connect /dev/tty.usbserial-0001 reset
```

Без скрипта:

```bash
pip install esptool mpremote
esptool.py --chip esp32c3 --port /dev/tty.usbserial-0001 erase_flash
esptool.py --chip esp32c3 --port /dev/tty.usbserial-0001 write_flash -z 0 ESP32_GENERIC_C3-*.bin
mpremote connect /dev/tty.usbserial-0001 fs mkdir :vendor
mpremote connect /dev/tty.usbserial-0001 fs cp main.py bus.py pi30.py poller.py \
        sethandler.py history.py mqttpub.py web.py config.example.json :/
mpremote connect /dev/tty.usbserial-0001 fs cp vendor/umqtt/simple.py :vendor/
mpremote connect /dev/tty.usbserial-0001 fs mkdir :www
mpremote connect /dev/tty.usbserial-0001 fs cp www/index.html :www/
```

## Настройка

`config.json` (см. `config.example.json`):

| Ключ | По умолчанию | Смысл |
|---|---|---|
| `wifi.ssid/password` | — | Wi-Fi 2.4 ГГц (ESP32 не умеет 5 ГГц) |
| `uart.id/tx/rx/baud` | `1/4/5/2400` | линия к инвертору |
| `poll_fast_s` | 2 | период `QPIGS` |
| `poll_slow_s` | 60 | период `QPIRI` (читаем уставки) |
| `history_points` | 1440 | глубина кольца истории (1 точка/мин → сутки) |
| `http.port` | 80 | веб-интерфейс |
| `auth.user/password` | `admin`/`admin` | HTTP Basic (**смените**) |
| `mqtt.host/port/user/password` | — | брокер |
| `mqtt.prefix` | `solar/pico` | префикс топиков |
| `mqtt.node_id` | `pico` | id для HA discovery |

## Топики MQTT

```
solar/pico/state                            ← полный JSON состояния (retain)
solar/pico/status                           ← online/offline (LWT, retain)
solar/pico/bridge                           ← диагностика: rx/tx/ошибки/RSSI
solar/pico/inverter_1/pv_power/state        ← по топику на метрику
solar/pico/inverter_1/<key>/set             ← записать уставку (payload = значение)
solar/pico/inverter_1/<key>/set/response_message/state
homeassistant/sensor/pico_<key>/config      ← discovery
```

Префикс совпадает с серверным форматом, поэтому HA-шаблоны и дашборды работают и с
прошивкой, и с сервером: достаточно поменять `mqtt.prefix` на `solar/home`.

## API

| Метод | Путь | Что |
|---|---|---|
| GET | `/` | веб-интерфейс |
| GET | `/api/v1/state` | состояние + health |
| GET | `/api/v1/health` | только health |
| GET | `/api/v1/sysinfo` | IP, RSSI, свободная память, MQTT |
| GET | `/api/v1/history?limit=720` | кольцо истории |
| GET | `/api/v1/settings` | уставки с текущими значениями |
| POST | `/api/v1/settings` | `{"key":"max_charge_current","value":60}` |
| GET | `/api/v1/poll` | внеочередной опрос |

## Ограничения и честные оговорки

* Прошивка **не проверена на живом инверторе** — логика парсеров общая с сервером
  (тест `collector/tests/test_firmware.py` сверяет результаты), но UART-тайминги на
  железе надо подтвердить.
* История живёт в RAM: после перезагрузки пусто. Для долгой истории — сервер/InfluxDB.
* TLS для MQTT на RP2350/ESP32-C3 в MicroPython есть, но памяти мало — в этой версии
  только plain MQTT (локальная сеть). Не выставляйте порт 80 в интернет.
* `pi30.py` генерируется: `python3 tools/make_firmware_pi30.py` после правок серверного
  парсера.
