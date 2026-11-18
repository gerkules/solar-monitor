"""Inverter connection settings: transport selection, device discovery, probe.

The collector normally takes the transport from the environment, but a physical
USB-RS232 adapter and a virtual RS232 (TCP) need to be switchable at runtime —
without editing .env and recreating the container. The choice is stored in
/data/connection.json and applied by the poller.
"""
from __future__ import annotations

import glob
import json
import logging
import os
import time

from . import config, pi30
from .transports import TransportError, make_transport

log = logging.getLogger("connection")

MODES = {
    "tcp": {
        "label": "Виртуальный RS232 (TCP)",
        "hint": "Донгл EW10 :9999, ser2net, ESP32-шлюз, usbip",
        "fields": ["tcp_host", "tcp_port"],
    },
    "serial": {
        "label": "Физический USB-RS232 / RS485",
        "hint": "USB-адаптер в инвертор (обычно 2400 8N1)",
        "fields": ["serial_port", "serial_baud"],
    },
    "hid": {
        "label": "USB-HID (нативный USB инвертора)",
        "hint": "Порт инвертора напрямую, без переходников",
        "fields": ["hid_device"],
    },
    "mqtt": {
        "label": "MQTT-сокет (EW10 в режиме MQTT)",
        "hint": "Кадры уходят в <topic>/cmd, ответы приходят в <topic>/data",
        "fields": ["trans_topic"],
    },
}

DEFAULTS = {
    # "direct" = читаем инвертор сами, "sa-mqtt" = импорт из SolarAssistant
    "source": "sa-mqtt" if config.TRANSPORT == "sa-mqtt" else "direct",
    "mode": "tcp" if config.TRANSPORT == "sa-mqtt" else (
        config.TRANSPORT if config.TRANSPORT in ("tcp", "serial", "hid", "mqtt") else "tcp"),
    "tcp_host": config.TCP_HOST,
    "tcp_port": config.TCP_PORT,
    "serial_port": config.SERIAL_PORT,
    "serial_baud": config.SERIAL_BAUD,
    "hid_device": config.HID_DEVICE,
    "trans_topic": config.TRANS_TOPIC,
}


class ConnectionStore:
    def __init__(self, path: str):
        self.path = path
        self.data = dict(DEFAULTS)
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                saved = json.load(f)
            self.data.update({k: v for k, v in saved.items() if k in DEFAULTS})
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as ex:
            log.warning("cannot read connection config %s: %r", self.path, ex)

    def save(self, patch: dict):
        self.data.update({k: v for k, v in patch.items() if k in DEFAULTS})
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save connection config: %r", ex)
        return self.data

    def apply_to_env(self):
        """Push the stored settings into the config module (transports read it)."""
        config.TRANSPORT = self.data["mode"] if self.data.get("source") != "sa-mqtt" else "sa-mqtt"
        config.TCP_HOST = str(self.data["tcp_host"])
        config.TCP_PORT = int(self.data["tcp_port"])
        config.SERIAL_PORT = str(self.data["serial_port"])
        config.SERIAL_BAUD = int(self.data["serial_baud"])
        config.HID_DEVICE = str(self.data["hid_device"])
        config.TRANS_TOPIC = str(self.data["trans_topic"])


def list_ports() -> dict:
    """Serial ports and hidraw nodes present in the container."""
    serial = sorted(set(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
                        + glob.glob("/dev/serial/by-id/*")))
    hid = sorted(glob.glob("/dev/hidraw*"))
    return {"serial": serial, "hid": hid}


def describe(cfg: dict) -> str:
    mode = cfg.get("mode")
    if mode == "tcp":
        return f"tcp {cfg.get('tcp_host')}:{cfg.get('tcp_port')}"
    if mode == "serial":
        return f"serial {cfg.get('serial_port')}@{cfg.get('serial_baud')}"
    if mode == "hid":
        return f"usb-hid {cfg.get('hid_device')}"
    if mode == "mqtt":
        return f"mqtt-socket {cfg.get('trans_topic')}"
    return str(mode)


def build(cfg: dict, broker=None):
    """Create a transport for these settings (config module is patched first)."""
    store = ConnectionStore("")          # no file access: just to reuse apply logic
    store.data = dict(DEFAULTS, **{k: v for k, v in cfg.items() if k in DEFAULTS})
    store.apply_to_env()
    return make_transport(broker=broker)


def probe(cfg: dict, broker=None) -> dict:
    """Open the connection, ask QPIGS/QID and report what came back."""
    t0 = time.time()
    out = {"ok": False, "mode": cfg.get("mode"), "target": describe(cfg)}
    transport = None
    try:
        transport = build(cfg, broker=broker)
        resp = transport.request("QPIGS")
        if not resp:
            out["error"] = "нет ответа на QPIGS (проверьте порт/скорость/кабель)"
            return out
        parsed = pi30.parse_qpigs(resp)
        out.update({
            "ok": bool(parsed),
            "latency_ms": int((time.time() - t0) * 1000),
            "battery_voltage": parsed.get("battery_voltage"),
            "grid_voltage": parsed.get("grid_voltage"),
            "load_power": parsed.get("load_power"),
            "raw": resp[:80].decode(errors="replace").strip(),
        })
        qid = transport.request("QID")
        serial = pi30.parse_qid(qid).get("serial_number") if qid else None
        if serial:
            out["serial_number"] = serial
        qiri = transport.request("QPIRI")
        rated = pi30.parse_qpiri(qiri).get("rated_power") if qiri else None
        if rated:
            out["rated_power"] = rated
        return out
    except TransportError as ex:
        out["error"] = str(ex)
        return out
    except Exception as ex:  # noqa: BLE001
        out["error"] = repr(ex)
        return out
    finally:
        if transport is not None:
            try:
                transport.close()
            except Exception:  # noqa: BLE001
                pass


def snapshot(store: ConnectionStore, transport=None, stats: dict | None = None) -> dict:
    return {
        "config": dict(store.data),
        "modes": MODES,
        "ports": list_ports(),
        "current": describe(store.data),
        "transport": transport.describe() if transport is not None else None,
        "stats": stats or {},
    }
