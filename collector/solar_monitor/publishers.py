"""Publishers: MQTT (SolarAssistant-compatible topics + HA discovery) and InfluxDB 2.x."""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

import paho.mqtt.client as mqtt

from . import config
from .pi30 import INFO_METRICS, METRICS, SETTINGS

log = logging.getLogger("publisher")

STATUS_TOPIC = f"{config.MQTT_PREFIX}/status"
STATE_TOPIC = f"{config.MQTT_PREFIX}/state"
SET_RESPONSE_TOPIC = f"{config.MQTT_PREFIX}/set/response_message/state"


def metric_topic(key: str) -> str:
    return f"{config.MQTT_PREFIX}/inverter_1/{key}/state"


def set_topic(key: str, verified: bool = False) -> str:
    return f"{config.MQTT_PREFIX}/inverter_1/{key}/" + ("set_verified" if verified else "set")


# ---------------------------------------------------------------- MQTT
def new_client() -> "mqtt.Client":
    """paho-mqtt 2.x requires an explicit callback API version; 1.x has none."""
    try:
        return mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                           client_id=config.MQTT_CLIENT_ID, clean_session=True)
    except AttributeError:
        return mqtt.Client(client_id=config.MQTT_CLIENT_ID, clean_session=True)


class MqttPublisher:
    """Self-healing MQTT client: rebuilds itself if paho's loop dies (Wi-Fi blip)."""

    def __init__(self):
        self.client: mqtt.Client | None = None
        self.lock = threading.Lock()
        self.subs: list[tuple[str, callable]] = []
        self.connected = threading.Event()
        self.restarts = 0
        self.on_connect_hooks: list[callable] = []
        threading.Thread(target=self._run, name="mqtt", daemon=True).start()

    # -- public --------------------------------------------------------------
    def subscribe(self, topic: str, cb):
        with self.lock:
            self.subs.append((topic, cb))
            c = self.client
        if c is not None:
            c.subscribe(topic, qos=1)

    def add_connect_hook(self, fn):
        with self.lock:
            self.on_connect_hooks.append(fn)

    def publish(self, topic: str, payload, qos: int = 1, retain: bool = False):
        if isinstance(payload, (dict, list)):
            payload = json.dumps(payload)
        with self.lock:
            c = self.client
        if c is None or not self.connected.is_set():
            return False
        try:
            c.publish(topic, payload, qos=qos, retain=retain)
            return True
        except Exception as ex:  # noqa: BLE001
            log.warning("publish %s failed: %r", topic, ex)
            return False

    def wait_connected(self, timeout: float = 10.0) -> bool:
        return self.connected.wait(timeout)

    # -- internals -----------------------------------------------------------
    def _run(self):
        while True:
            c = new_client()
            if config.MQTT_USER:
                c.username_pw_set(config.MQTT_USER, config.MQTT_PASS)
            if config.MQTT_TLS:
                c.tls_set()
            c.will_set(STATUS_TOPIC, "offline", qos=1, retain=True)
            c.reconnect_delay_set(min_delay=1, max_delay=30)

            def _on_connect(cl, userdata, flags, rc, *a):
                if rc != 0:
                    log.warning("mqtt connect failed rc=%s", rc)
                    return
                log.info("mqtt connected to %s:%s", config.MQTT_HOST, config.MQTT_PORT)
                with self.lock:
                    subs = list(self.subs)
                    hooks = list(self.on_connect_hooks)
                for topic, cb in subs:
                    cl.subscribe(topic, qos=1)
                cl.on_message = self._on_message
                for fn in hooks:
                    try:
                        fn()
                    except Exception as ex:  # noqa: BLE001
                        log.warning("connect hook failed: %r", ex)
                cl.publish(STATUS_TOPIC, "online", qos=1, retain=True)
                self.connected.set()

            c.on_connect = _on_connect
            c.on_disconnect = lambda *a: self.connected.clear()
            with self.lock:
                self.client = c
            try:
                c.connect(config.MQTT_HOST, config.MQTT_PORT, keepalive=60)
                c.loop_forever(retry_first_connection=True)
                log.warning("mqtt loop exited, restarting")
            except Exception as ex:  # noqa: BLE001
                log.warning("mqtt loop crashed: %r", ex)
            self.connected.clear()
            with self.lock:
                self.client = None
            try:
                c.disconnect()
            except Exception:  # noqa: BLE001
                pass
            self.restarts += 1
            time.sleep(5)

    def _on_message(self, client, userdata, msg):
        with self.lock:
            subs = list(self.subs)
        for topic, cb in subs:
            if mqtt.topic_matches_sub(topic, msg.topic):
                try:
                    cb(msg.topic, msg.payload)
                except Exception as ex:  # noqa: BLE001
                    log.warning("subscriber for %s failed: %r", topic, ex)


def device_info() -> dict:
    return {
        "identifiers": [f"{config.ENTITY_PREFIX}_pi30"],
        "name": config.DEVICE_NAME,
        "manufacturer": "Voltronic Power / Axpert",
        "model": config.DEVICE_MODEL,
        "sw_version": "PI30",
    }


def _entity_base(key: str, name: str, icon: str | None = None) -> dict:
    ent = {
        "name": name,
        "unique_id": f"{config.ENTITY_PREFIX}_{key}",
        "object_id": f"{config.ENTITY_PREFIX}_{key}",
        "default_entity_id": f"sensor.{config.ENTITY_PREFIX}_{key}",
        "availability_topic": STATUS_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_info(),
    }
    if icon:
        ent["icon"] = icon
    return ent


def discovery_messages(state: dict) -> list[tuple[str, dict]]:
    """All retained HA discovery configs for this site."""
    out: list[tuple[str, dict]] = []
    ep = config.ENTITY_PREFIX

    for key, (name, unit, dev_class, state_class, icon, _is_energy) in METRICS.items():
        ent = _entity_base(key, name, icon)
        ent["state_topic"] = metric_topic(key)
        ent["default_entity_id"] = f"sensor.{ep}_{key}"
        if unit:
            ent["unit_of_measurement"] = unit
        if dev_class:
            ent["device_class"] = dev_class
        if state_class:
            ent["state_class"] = state_class
        out.append((f"{config.HA_PREFIX}/sensor/{ep}_{key}/config", ent))

    # warnings as a text sensor + numeric bitmask
    ent = _entity_base("warnings", "Warnings", "mdi:alert")
    ent["state_topic"] = metric_topic("warnings")
    ent["default_entity_id"] = f"sensor.{ep}_warnings"
    out.append((f"{config.HA_PREFIX}/sensor/{ep}_warnings/config", ent))

    # mains presence
    ent = _entity_base("mains_ok", "Mains present", "mdi:transmission-tower")
    ent["state_topic"] = metric_topic("mains_ok")
    ent["default_entity_id"] = f"binary_sensor.{ep}_mains_ok"
    ent["device_class"] = "power"
    out.append((f"{config.HA_PREFIX}/binary_sensor/{ep}_mains_ok/config", ent))

    # read-only ratings
    for key, (name, unit) in INFO_METRICS.items():
        ent = _entity_base(key, name, "mdi:information-outline")
        ent["state_topic"] = metric_topic(key)
        ent["entity_category"] = "diagnostic"
        ent["default_entity_id"] = f"sensor.{ep}_{key}"
        if unit:
            ent["unit_of_measurement"] = unit
        out.append((f"{config.HA_PREFIX}/sensor/{ep}_{key}/config", ent))

    # writable settings
    for key, spec in SETTINGS.items():
        ent = _entity_base(key, spec["name"], spec.get("icon"))
        ent["state_topic"] = metric_topic(key)
        ent["command_topic"] = set_topic(key)
        if spec["kind"] == "select":
            ent["options"] = list(spec["options"].values())
            ent["default_entity_id"] = f"select.{ep}_{key}"
            comp = "select"
        else:
            ent.update({
                "min": spec["min"], "max": spec["max"], "step": spec["step"],
                "unit_of_measurement": spec.get("unit", ""), "mode": "box",
                "default_entity_id": f"number.{ep}_{key}",
            })
            if spec.get("dev_class"):
                ent["device_class"] = spec["dev_class"]
            comp = "number"
        out.append((f"{config.HA_PREFIX}/{comp}/{ep}_{key}/config", ent))

    # reload button
    ent = {
        "name": "Re-read settings",
        "unique_id": f"{ep}_reload_settings",
        "object_id": f"{ep}_reload_settings",
        "default_entity_id": f"button.{ep}_reload_settings",
        "command_topic": f"{config.MQTT_PREFIX}/reload_settings",
        "payload_press": "PRESS",
        "availability_topic": STATUS_TOPIC,
        "payload_available": "online",
        "payload_not_available": "offline",
        "device": device_info(),
        "icon": "mdi:refresh",
    }
    out.append((f"{config.HA_PREFIX}/button/{ep}_reload_settings/config", ent))
    return out


def publish_state(mq: MqttPublisher, state: dict):
    """Full JSON blob + one topic per metric (SolarAssistant layout)."""
    mq.publish(STATE_TOPIC, state, retain=config.STATE_RETAIN)
    for key in METRICS:
        if key in state and state[key] is not None:
            mq.publish(metric_topic(key), state[key], retain=False)
    for key in ("mains_ok", "warnings", "warning_bits", "device_mode", "serial_number"):
        if key in state and state[key] is not None:
            mq.publish(metric_topic(key), state[key], retain=False)
    for key in INFO_METRICS:
        if key in state and state[key] is not None:
            mq.publish(metric_topic(key), state[key], retain=True)
    for key in SETTINGS:
        if key in state and state[key] is not None:
            mq.publish(metric_topic(key), state[key], retain=True)


def publish_discovery(mq: MqttPublisher, state: dict):
    if not config.HA_DISCOVERY:
        log.info("HA discovery disabled (HA_DISCOVERY=false)")
        return
    for topic, payload in discovery_messages(state):
        mq.publish(topic, payload, retain=True)


# ---------------------------------------------------------------- InfluxDB 2.x
class InfluxPublisher:
    """Writes one line-protocol batch per poll. Silent if not configured."""

    def __init__(self):
        self.mode = config.INFLUX_MODE
        if self.mode.startswith("1"):
            self.enabled = bool(config.INFLUX_URL)
            self.url = (config.INFLUX_URL.rstrip("/") + "/write"
                        f"?db={urllib.parse.quote(config.INFLUX_DB)}&precision=s")
        else:
            self.enabled = bool(config.INFLUX_TOKEN and config.INFLUX_URL)
            self.url = (config.INFLUX_URL.rstrip("/") + "/api/v2/write"
                        f"?org={urllib.parse.quote(config.INFLUX_ORG)}"
                        f"&bucket={urllib.parse.quote(config.INFLUX_BUCKET)}&precision=s")
        self.errors = 0
        self.written = 0

    def write_series(self, measurement: str, points: list[tuple[int, float]]):
        """Explicit timestamps (used for future PV forecast points)."""
        if not self.enabled or not points:
            return
        lines = [f"{measurement},site={config.SITE} value={val} {int(ts)}" for ts, val in points]
        body = ("\n".join(lines) + "\n").encode()
        req = urllib.request.Request(self.url, data=body, method="POST")
        if self.mode.startswith("1"):
            if config.INFLUX_AUTH:
                import base64
                req.add_header("Authorization",
                               "Basic " + base64.b64encode(config.INFLUX_AUTH.encode()).decode())
        else:
            req.add_header("Authorization", f"Token {config.INFLUX_TOKEN}")
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                resp.read()
            self.written += len(lines)
        except Exception as ex:  # noqa: BLE001
            self.errors += 1
            log.warning("influx forecast write failed: %r", ex)

    def write(self, state: dict, ts: float | None = None):
        if not self.enabled:
            return
        ts = int(ts or time.time())
        lines = []
        for key, (_n, _u, _dc, _sc, _i, is_energy) in METRICS.items():
            val = state.get(key)
            if val is None or isinstance(val, bool):
                continue
            if not isinstance(val, (int, float)):
                continue
            name = config.INFLUX_MEASUREMENT_PREFIX + key
            lines.append(f"{name},site={config.SITE} value={val} {ts}")
        if not lines:
            return
        body = ("\n".join(lines) + "\n").encode()
        req = urllib.request.Request(self.url, data=body, method="POST")
        if self.mode.startswith("1"):
            if config.INFLUX_AUTH:
                import base64
                cred = base64.b64encode(config.INFLUX_AUTH.encode()).decode()
                req.add_header("Authorization", f"Basic {cred}")
        else:
            req.add_header("Authorization", f"Token {config.INFLUX_TOKEN}")
        req.add_header("Content-Type", "text/plain; charset=utf-8")
        try:
            with urllib.request.urlopen(req, timeout=5) as resp:
                if resp.status >= 300:
                    raise urllib.error.HTTPError(self.url, resp.status, "", {}, None)
            self.written += len(lines)
        except Exception as ex:  # noqa: BLE001
            self.errors += 1
            if self.errors in (1, 10) or self.errors % 60 == 0:
                log.warning("influx write failed (%s times): %r", self.errors, ex)
