# Прошивка Wemos D1 (ESP8266): панель инвертора + мост TCP ⇄ RS232

Плата у инвертора отдаёт линию PI30 в TCP, чтобы **Orange Pi / сервер `solar-monitor`
опрашивал инвертор по сети** транспортом «Виртуальный RS232 (TCP)», а без сервера
показывал данные сама в браузере.

База — уже проверенный на железе проект владельца:
`/volume1/WD4/AI/esp32invertormonitornovyi/wemos_usb_firmware/wemos8266_lite.cpp`
(FW 118). Добавлено ровно то, чего не хватало для связки с `solar-monitor`:

* TCP-сервер (по умолчанию `9999`), прозрачный мост `TCP ⇄ UART`;
* пауза локального опроса, пока TCP-клиент подключён (на линии 2400 бод два мастера
  несовместимы);
* блок «RS232 bridge» в панели: IP клиента, байты туда/обратно, сессии, «последний байт»;
* CLI по USB-serial для настройки без телефона/AP.

## Железо

| Плата | ESP8266EX, 4 МБ flash (Wemos D1 / D1 mini) |
|---|---|
| UART инвертора | **SoftwareSerial: RX = D5 (GPIO14), TX = D6 (GPIO12)**, 2400 8N1 |
| Уровни | MAX3232 (инвертор — настоящий RS232, ±12 В), питание модуля 3V3 |
| Serial (USB) | 115200, для логов, CLI и прошивки |

```
Wemos D5 (GPIO14) ◄── MAX3232 R1OUT      MAX3232 T1IN  ◄── Wemos D6 (GPIO12)
Wemos GND         ──── MAX3232 GND        MAX3232 R1IN  ──► инвертор RS232 TX
                                           MAX3232 T1OUT ─► инвертор RS232 RX
```

Линия инвертора: **2400 бод, 8N1**, без flow control. Порт у инвертора один — донгл
EW10 и Wemos одновременно на один разъём не вешаются.

## Сборка и заливка

```bash
cd ~/solar-monitor/firmware/esp8266
~/.platformio/penv/bin/pio run                     # сборка
~/.platformio/penv/bin/pio run -t upload --upload-port /dev/cu.usbserial-XXXX
```

Образ: `.pio/build/d1_mini/firmware.bin` (≈350 КБ, 33 % слота). Заливается по адресу `0x0`.

Если плата была в цикле сброса на `rf cal sector: ...` — служебная область flash
побита, помогает `esptool.py erase_flash` перед заливкой (проверено на этой плате).

## Первая настройка

Вариант A — через AP (по умолчанию, пока нет Wi-Fi):

1. подключиться к `InverterMonitor` / `12345678`;
2. открыть `http://192.168.4.1/`, логин `admin` / `admin`;
3. вкладка **Settings**: SSID, пароль Wi-Fi, пароль админа → **Save Wi-Fi**
   (плата перезагрузится), затем блок **RS232 bridge**: TCP-порт и baud → **Save bridge**.

Вариант B — по USB-serial (115200):

```
show
ssid <имя сети>
pass <пароль>
port 9999
baud 2400
reboot
```

## Подключение к Orange Pi (solar-monitor)

В UI `solar-monitor` → **Настройки → Подключение → Виртуальный RS232 (TCP)**:
host = IP Wemos (DHCP-резерв лучше закрепить), port = `9999` → «Проверить связь».
Или в `.env`:

```
TRANSPORT=tcp
TCP_HOST=<ip-wemos>
TCP_PORT=9999
```

Пока сервер опрашивает инвертор, панель Wemos показывает последние полученные данные,
но сама линию не трогает. После отключения клиента локальный опрос возвращается через ~1 с.

## Диагностика

| Симптом | Что смотреть |
|---|---|
| панель «Нет связи», `/data` → `online: Нет` | провода D5/D6, MAX3232, 2400 8N1, занят ли порт донглом |
| TCP-клиент подключается, но ответов нет | `br_tcp2uart` растёт, `br_uart2tcp` = 0 → RX от инвертора не приходит |
| плата в цикле сброса, boot-лог `rf cal sector` | `esptool erase_flash` и залить заново |
| нет AP при первом включении | держать кнопку RESET 3 с; смотреть USB-serial 115200 |

`GET /data` (после Basic-авторизации) отдаёт и мост: `br_active`, `br_client`,
`br_tcp2uart`, `br_uart2tcp`, `br_sessions`, `br_age`, `br_port`, `baud`.
