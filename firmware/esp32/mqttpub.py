"""Публикация в MQTT: те же топики, что у сервера + Home Assistant discovery."""
import time

try:
    import ujson as json
except ImportError:
    import json

import pi30
import sethandler

try:
    from umqtt.simple import MQTTClient
except ImportError:                      # на CPython (тесты) клиента нет
    MQTTClient = None

# Что публикуем в HA (остальное остаётся в JSON-состоянии)
HA_KEYS = (
    "pv_power", "load_power", "grid_power", "battery_voltage", "battery_current",
    "battery_power", "battery_state_of_charge", "grid_voltage", "ac_output_voltage",
    "load_percentage", "temperature", "device_mode",
)


class Publisher:
    """Тонкая обёртка над umqtt.simple с автопереподключением."""

    def __init__(self, cfg, poller, history, bus):
        m = cfg.get("mqtt") or {}
        self.enabled = bool(m.get("host"))
        self.host = m.get("host", "")
        self.port = int(m.get("port", 1883))
        self.user = m.get("user") or None
        self.password = m.get("password") or None
        self.prefix = (m.get("prefix") or "solar/pico").rstrip("/")
        self.node = m.get("node_id") or "pico"
        self.discovery = bool(m.get("discovery", True))
        self.poller = poller
        self.history = history
        self.bus = bus
        self.client = None
        self.connected = False
        self.sent = 0
        self.errors = 0
        self._last_connect = 0
        self._discovery_done = False
        self.last_set = {}

    # -- топики --------------------------------------------------------------
    def state_topic(self):
        return "%s/state" % self.prefix

    def status_topic(self):
        return "%s/status" % self.prefix

    def metric_topic(self, key):
        return "%s/inverter_1/%s/state" % (self.prefix, key)

    def set_topic(self):
        return "%s/inverter_1/+/set" % self.prefix

    # -- соединение ----------------------------------------------------------
    def connect(self):
        if not self.enabled or MQTTClient is None:
            return False
        if time.time() - self._last_connect < 5:
            return False
        self._last_connect = time.time()
        try:
            client = MQTTClient(self.node, self.host, self.port,
                                self.user, self.password, keepalive=60)
            client.set_last_will(self.status_topic(), b"offline", retain=True, qos=1)
            client.set_callback(self._on_message)
            client.connect()
            client.subscribe(self.set_topic(), qos=0)
            self.client = client
            self.connected = True
            self._discovery_done = False
            self.publish(self.status_topic(), b"online", retain=True)
            return True
        except Exception as ex:                       # noqa: BLE001
            self.errors += 1
            self.connected = False
            self.client = None
            print("mqtt connect:", ex)
            return False

    def publish(self, topic, payload, retain=False, qos=0):
        if not self.connected or self.client is None:
            return False
        if not isinstance(payload, (bytes, bytearray)):
            payload = str(payload).encode()
        try:
            self.client.publish(topic, payload, retain=retain, qos=qos)
            self.sent += 1
            return True
        except Exception as ex:                       # noqa: BLE001
            self.errors += 1
            self.connected = False
            print("mqtt publish:", ex)
            return False

    # -- состояние -----------------------------------------------------------
    def publish_state(self):
        if not self.connected:
            return
        state = self.poller.state
        if not state:
            return
        self.publish(self.state_topic(), json.dumps(state), retain=True)
        for key in ("pv_power", "load_power", "grid_power", "battery_voltage",
                    "battery_current", "battery_power", "battery_state_of_charge",
                    "grid_voltage", "ac_output_voltage", "load_percentage",
                    "temperature", "device_mode", "warning_bits", "mains_ok", "warnings"):
            if state.get(key) is not None:
                self.publish(self.metric_topic(key), state[key], retain=False)
        for key in pi30.SETTINGS:
            if state.get(key) is not None:
                self.publish(self.metric_topic(key), state[key], retain=True)
        if self.discovery and not self._discovery_done:
            self.publish_discovery()
            self._discovery_done = True

    def publish_discovery(self):
        for key in HA_KEYS:
            meta = pi30.METRICS.get(key) or (key, None)
            name, unit = meta[0], meta[1]
            cfg = {
                "name": name,
                "unique_id": "%s_%s" % (self.node, key),
                "state_topic": self.metric_topic(key),
                "availability_topic": self.status_topic(),
                "device": {
                    "identifiers": [self.node],
                    "name": "Solar Monitor %s" % self.node,
                    "manufacturer": "solar-monitor firmware",
                    "model": "ESP32",
                },
            }
            if unit:
                cfg["unit_of_measurement"] = unit
            if key == "battery_state_of_charge":
                cfg["device_class"] = "battery"
            elif key in ("pv_power", "load_power", "grid_power", "battery_power"):
                cfg["device_class"] = "power"
            elif key == "temperature":
                cfg["device_class"] = "temperature"
            elif key == "battery_voltage":
                cfg["device_class"] = "voltage"
            topic = "homeassistant/sensor/%s_%s/config" % (self.node, key)
            self.publish(topic, json.dumps(cfg), retain=True)

    def publish_health(self):
        if not self.connected:
            return
        self.publish("%s/bridge" % self.prefix, json.dumps({
            "connected": self.connected,
            "sent": self.sent,
            "errors": self.errors,
            "rx": self.bus.rx,
            "tx": self.bus.tx,
            "uart_errors": self.bus.errors,
            "last_error": self.bus.last_error,
            "history_points": len(self.history.t),
        }), retain=True)

    # -- команды из MQTT -----------------------------------------------------
    def _on_message(self, topic, msg):
        topic = topic.decode() if isinstance(topic, (bytes, bytearray)) else topic
        try:
            payload = msg.decode() if isinstance(msg, (bytes, bytearray)) else str(msg)
        except Exception:                              # noqa: BLE001
            return
        key = topic.split("/")[-2]
        result = sethandler.apply_setting(self.bus, key, payload)
        self.last_set = result
        self.publish("%s/inverter_1/%s/set/response_message/state" % (self.prefix, key),
                     result.get("message", ""), retain=False)

    def loop_once(self, poll_now=True):
        if not self.connected and not self.connect():
            return False
        try:
            self.client.check_msg()
        except Exception as ex:                        # noqa: BLE001
            self.errors += 1
            self.connected = False
            self.client = None
            print("mqtt loop:", ex)
            return False
        if poll_now:
            self.publish_state()
        return True
