#!/usr/bin/env python3
"""solar-monitor collector — inverter -> MQTT / InfluxDB / HTTP API.

One process, one inverter: works over USB-HID, USB-RS232 serial, raw TCP
(dongle / ser2net / ESP32 gateway) or the EW10 MQTT socket.
"""
from __future__ import annotations

import faulthandler
import logging
import os
import signal
import sys
import threading
import time

from . import auth as auth_mod, battery, config, connection as conn_mod, forecast, \
    inverters as inverters_mod, notifier as notifier_mod, publishers, \
    rules as rules_mod, sa_source, settings as settings_mod, sites as sites_mod
from .poller import Poller
from .transports import TransportError, make_transport

# Диагностика: `kill -USR1 <pid>` печатает стеки всех потоков в stderr (журнал).
# Нужно, когда один поток «крутится» и непонятно какой (на Pi 1 это заметно).
try:
    faulthandler.register(signal.SIGUSR1, all_threads=True)
except (AttributeError, ValueError):        # платформа без faulthandler
    pass


def setup_logging():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL, logging.INFO),
        format="%(asctime)s %(levelname)-7s %(name)-12s %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        stream=sys.stdout,
    )
    logging.getLogger("paho").setLevel(logging.WARNING)


def _spawn(fn, *a, **kw):
    threading.Thread(target=fn, args=a, kwargs=kw, daemon=True).start()


def main() -> int:
    setup_logging()
    log = logging.getLogger("main")
    log.info("solar-monitor site=%s entity_prefix=%s transport=%s",
             config.SITE, config.ENTITY_PREFIX, config.TRANSPORT)

    mq = publishers.MqttPublisher()
    influx = publishers.InfluxPublisher()

    notifier = notifier_mod.Notifier(mqtt=mq)
    rule_engine = rules_mod.RuleEngine(notifier=notifier)

    # Сохранённый в UI выбор перекрывает .env: и транспорт, и источник данных
    # ("direct" = читаем инвертор сами, "sa-mqtt" = импорт из SolarAssistant).
    conn_store = conn_mod.ConnectionStore(config.CONNECTION_FILE)
    if os.path.exists(config.CONNECTION_FILE):
        conn_store.apply_to_env()
        log.info("connection: saved source=%s mode=%s",
                 conn_store.data.get("source"), conn_store.data["mode"])

    auth_store = auth_mod.AuthStore(config.AUTH_FILE)
    if auth_store.info()["source"] == "file":
        log.info("auth: пароль из %s (перекрывает .env), пользователь %s",
                 config.AUTH_FILE, auth_store.info()["user"])

    batt_cfg = config.bms_config()
    batt_store = battery.BatteryStore(config.BATTERY_CONFIG_FILE)
    transport = None
    use_import = sa_source.is_sa_source() and conn_store.data.get("source") != "direct"
    if use_import:
        # SolarAssistant owns the inverter; we import its MQTT output instead.
        poller = sa_source.SaSource(mq, influx, notifier=notifier, rules=rule_engine)
        batt_monitor = battery.BatteryMonitor(config.BATTERY_SOURCE, poller.state,
                                              batt_cfg, store=batt_store)
        poller.battery = batt_monitor
        log.info("source: sa-mqtt %s:%s (import SolarAssistant)",
                 config.SA_MQTT_HOST, config.SA_MQTT_PORT)
    else:
        try:
            transport = make_transport(broker=mq)
        except TransportError as ex:
            log.error("transport: %s", ex)
            return 2
        poller = Poller(transport, mq, influx, notifier=notifier, rules=rule_engine)
        batt_monitor = battery.BatteryMonitor(config.BATTERY_SOURCE, poller.state,
                                              batt_cfg, store=batt_store)
        poller.battery = batt_monitor
    forecast_svc = forecast.ForecastService(poller=poller, influx=influx, mqtt=mq)
    site_registry = sites_mod.SiteRegistry(mq, local_poller=poller)
    # второй и последующие инверторы на этом хосте (страница «Инверторы»):
    # в Docker — дочерние процессы контейнера, на нативном хосте — systemd-инстансы
    try:
        inverters_mod.supervise()
    except Exception:  # noqa: BLE001 - без доп. инверторов коллектор работает
        log.exception("супервизор доп. инверторов не поднялся")
    log.info("battery source: %s", batt_monitor.describe())
    log.info("automation: %s rules, notify channels: %s",
             len(rule_engine.list()), ", ".join(notifier.channels()) or "none")
    if config.AUTH_USER:
        log.info("ui auth: basic (%s)", config.AUTH_USER)

    # --- settings writes coming from MQTT (SolarAssistant-compatible topics) ---
    def make_set_handler(key: str, verified: bool):
        def handler(topic: str, payload: bytes):
            _spawn(poller.submit_set, key, payload, verified)
        return handler

    for key in settings_mod.effective_settings():
        mq.subscribe(publishers.set_topic(key, verified=False), make_set_handler(key, False))
        mq.subscribe(publishers.set_topic(key, verified=True), make_set_handler(key, True))
    mq.subscribe(f"{config.MQTT_PREFIX}/reload_settings",
                 lambda topic, payload: _spawn(poller.submit_set, "reload_settings", None, False))

    # --- HA discovery on every (re)connect -----------------------------------
    mq.add_connect_hook(lambda: publishers.publish_discovery(mq, poller.snapshot()))

    # --- web UI + HTTP API (FastAPI/uvicorn) ---------------------------------
    _spawn(forecast_svc.run)
    batt_monitor.start()
    if config.WEBAPP_ENABLED:
        import uvicorn

        from . import webapp
        app = webapp.create_app(poller, notifier=notifier, rules=rule_engine,
                                forecast_svc=forecast_svc, sites=site_registry,
                                battery=batt_monitor, connection_store=conn_store,
                                auth_store=auth_store)
        scheme = "https" if (config.TLS_CERT and config.TLS_KEY) else "http"
        server = uvicorn.Server(uvicorn.Config(
            app, host=config.API_HOST, port=config.API_PORT,
            log_level="warning", access_log=False,
            ssl_certfile=config.TLS_CERT or None,
            ssl_keyfile=config.TLS_KEY or None))
        _spawn(server.run)
        log.info("web ui + api on %s://%s:%s/ (docs: /api/docs)", scheme, config.API_HOST, config.API_PORT)
        if config.AUTH_USER:
            log.info("ui auth: HTTP Basic (%s)", config.AUTH_USER)
        else:
            log.warning("ui auth is OFF: anyone on the network can change inverter settings")
        if auth_store.info().get("default_password"):
            log.warning("ПАРОЛЬ ПО УМОЛЧАНИЮ (%s/%s): смените его в Настройки → Уставки → Доступ",
                        auth_mod.DEFAULT_USER, auth_mod.DEFAULT_PASSWORD)
    else:
        log.info("headless: веб-интерфейс выключен (WEBAPP=false) — только MQTT")

    # --- shutdown ------------------------------------------------------------
    stop = threading.Event()
    for sig in (signal.SIGINT, signal.SIGTERM):
        signal.signal(sig, lambda *_: stop.set())

    _spawn(poller.run)
    while not stop.wait(1.0):
        pass
    log.info("shutting down")
    batt_monitor.close()
    if transport is not None:
        transport.close()
    server.shutdown()
    time.sleep(0.2)
    return 0


if __name__ == "__main__":
    sys.exit(main())
