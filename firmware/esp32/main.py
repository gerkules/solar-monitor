"""solar-monitor firmware: самостоятельный узел на ESP32/ESP32-C3.

Опрашивает инвертор по UART (PI30), держит состояние, отдаёт веб-интерфейс и
публикует MQTT. Сервер (VDS/InfluxDB/Grafana) не нужен — но если он есть, топики
совпадают и Home Assistant видит устройство как обычно.

Файлы на устройстве: main.py, boot.py(нет), pi30.py, bus.py, poller.py,
sethandler.py, history.py, mqttpub.py, web.py, config.json, vendor/umqtt/simple.py,
www/index.html.
"""
import gc
import time

import machine
import network

try:
    import uasyncio as asyncio
except ImportError:
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

import bus as bus_mod
import history as history_mod
import mqttpub
import poller as poller_mod
import web

DEFAULTS = {
    "wifi": {"ssid": "", "password": ""},
    "uart": {"id": 1, "tx": 4, "rx": 5, "baud": 2400},
    "poll_fast_s": 2,
    "poll_slow_s": 60,
    "history_interval_s": 60,
    "history_points": 1440,
    "http": {"port": 80},
    "auth": {"user": "admin", "password": "admin"},
    "mqtt": {"host": "", "port": 1883, "user": "", "password": "",
             "prefix": "solar/pico", "node_id": "pico", "discovery": True},
    "ntp": {"host": "pool.ntp.org", "tz_offset_h": 0},
    "led_pin": None,
}


def load_config(path="config.json"):
    cfg = {}
    for key, val in DEFAULTS.items():
        cfg[key] = dict(val) if isinstance(val, dict) else val
    try:
        with open(path) as fh:
            user = json.loads(fh.read())
    except (OSError, ValueError) as ex:
        print("config.json:", ex)
        return cfg
    for key, val in user.items():
        if isinstance(val, dict) and isinstance(cfg.get(key), dict):
            cfg[key].update(val)
        else:
            cfg[key] = val
    return cfg


def wifi_connect(cfg):
    w = cfg["wifi"]
    sta = network.WLAN(network.STA_IF)
    sta.active(True)
    if not w.get("ssid"):
        print("wifi: ssid не задан в config.json")
        return False
    if not sta.isconnected():
        sta.connect(w["ssid"], w.get("password", ""))
        for _ in range(60):
            if sta.isconnected():
                break
            time.sleep(0.5)
    if sta.isconnected():
        print("wifi ok:", sta.ifconfig()[0])
        return True
    # Стек Wi-Fi на ESP32 иногда «зависает»: scan пустой, connect возвращает
    # Wifi Internal Error. Полная переинициализация интерфейса это лечит.
    print("wifi: не удалось подключиться — переинициализирую интерфейс")
    try:
        sta.active(False)
        time.sleep(1.5)
        sta.active(True)
        time.sleep(1.5)
        sta.connect(w["ssid"], w.get("password", ""))
        for _ in range(30):
            if sta.isconnected():
                break
            time.sleep(0.5)
    except Exception as ex:                       # noqa: BLE001
        print("wifi: переинициализация не помогла:", ex)
    if sta.isconnected():
        print("wifi ok после переинициализации:", sta.ifconfig()[0])
        return True
    print("wifi: не удалось подключиться")
    return False


def ntp_sync(cfg):
    try:
        import ntptime
        ntptime.host = (cfg.get("ntp") or {}).get("host", "pool.ntp.org")
        ntptime.settime()
        print("ntp ok:", time.time())
        return True
    except Exception as ex:                       # noqa: BLE001
        print("ntp:", ex)
        return False


def make_uart(cfg):
    u = cfg["uart"]
    return machine.UART(int(u.get("id", 1)), baudrate=int(u.get("baud", 2400)),
                        bits=8, parity=None, stop=1,
                        tx=int(u["tx"]), rx=int(u["rx"]), timeout=0)


async def poll_task(poller, wdt, period_s):
    """Опрос инвертора с паузой-передышкой для остальных задач.

    Шина UART опрашивается блокирующе, поэтому молчащий инвертор (нет кабеля,
    не тот порт) отнимает у веб-интерфейса по несколько секунд на каждый QPIGS.
    Пока ответа нет — растягиваем период до 30 с (веб и MQTT остаются живыми),
    как только данные пошли — возвращаемся к обычному периоду.
    """
    quiet = 0
    while True:
        ok = False
        try:
            ok = poller.poll_once()
        except Exception as ex:                   # noqa: BLE001
            print("poll:", ex)
        try:
            if wdt is not None:
                wdt.feed()
        except Exception:
            pass
        if ok:
            quiet = 0
            wait = period_s
        else:
            quiet = min(quiet + 1, 4)
            wait = min(period_s * (2 ** quiet), 30)
        await asyncio.sleep(wait)


async def mqtt_task(publisher):
    while True:
        try:
            publisher.loop_once()
            publisher.publish_health()
        except Exception as ex:                   # noqa: BLE001
            print("mqtt task:", ex)
        await asyncio.sleep(10)


async def history_task(poller, history):
    while True:
        history.maybe_add(poller.state)
        await asyncio.sleep(5)


async def wifi_task(cfg):
    while True:
        try:
            sta = network.WLAN(network.STA_IF)
            if not sta.isconnected():
                print("wifi: переподключение")
                wifi_connect(cfg)
        except Exception as ex:                   # noqa: BLE001
            print("wifi task:", ex)
        await asyncio.sleep(20)


async def main():
    cfg = load_config()
    wifi_connect(cfg)
    ntp_sync(cfg)

    uart = make_uart(cfg)
    bus = bus_mod.Bus(uart, timeout_ms=1500, attempts=2)
    poller = poller_mod.Poller(bus, cfg)
    history = history_mod.History(keep=int(cfg.get("history_points", 1440)),
                                  interval_s=int(cfg.get("history_interval_s", 60)))
    publisher = mqttpub.Publisher(cfg, poller, history, bus)
    publisher.publish_health()
    app = web.App(cfg, poller, history, publisher)

    wdt = None
    wdt_s = int(cfg.get("wdt_s", 0) or 0)
    if wdt_s > 0:
        try:
            wdt = machine.WDT(timeout=wdt_s * 1000)
        except Exception:
            pass

    print("solar-monitor firmware: старт, свободно %d байт" % gc.mem_free())
    # Каждая задача обёрнута: падение одной (Wi-Fi, MQTT, HTTP) не останавливает
    # остальные — иначе устройство замолкает целиком до перезагрузки.
    async def guarded(name, coro, pause_s=5):
        while True:
            try:
                await coro
                print("%s: завершилась, перезапуск" % name)
            except Exception as ex:               # noqa: BLE001
                print("%s: ошибка %r" % (name, ex))
            await asyncio.sleep(pause_s)

    await asyncio.gather(
        guarded("poll", poll_task(poller, wdt, int(cfg.get("poll_fast_s", 2)))),
        guarded("mqtt", mqtt_task(publisher)),
        guarded("history", history_task(poller, history)),
        guarded("wifi", wifi_task(cfg)),
        guarded("http", app.run()),
    )


def run():
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        pass


run()
