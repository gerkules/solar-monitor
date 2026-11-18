"""Import an existing SolarAssistant installation as a data source ("sa-mqtt").

Why: the office inverter is wired to an Orange Pi running SolarAssistant, and that
device owns the USB port. Instead of fighting for the cable, we subscribe to the
MQTT output SolarAssistant already publishes (`solar_assistant/inverter_1/...`)
and turn it into a regular site: same state model, same history, same rules.

Settings writes are forwarded to SolarAssistant's own /set_verified topics, so the
read-back verification stays with the software that owns the inverter.
"""
from __future__ import annotations

import json
import logging
import threading
import time

import paho.mqtt.client as mqtt

from . import config, energy as energy_mod, publishers

log = logging.getLogger("sa-source")

PREFIX = "solar_assistant"

# Our metric -> SolarAssistant topic suffix. Basically the same names, but the
# mapping is explicit so a rename upstream cannot silently break the importer.
KEY_MAP = {
    "pv_power": "inverter_1/pv_power",
    "pv_power_1": "inverter_1/pv_power_1",
    "pv_power_2": "inverter_1/pv_power_2",
    "pv_voltage_1": "inverter_1/pv_voltage_1",
    "pv_current_1": "inverter_1/pv_current_1",
    "pv_voltage_2": "inverter_1/pv_voltage_2",
    "pv_current_2": "inverter_1/pv_current_2",
    "grid_voltage": "inverter_1/grid_voltage",
    "grid_frequency": "inverter_1/grid_frequency",
    "grid_power": "inverter_1/grid_power",
    "ac_output_voltage": "inverter_1/ac_output_voltage",
    "ac_output_frequency": "inverter_1/ac_output_frequency",
    "load_power": "inverter_1/load_power",
    "load_apparent_power": "inverter_1/load_apparent_power",
    "load_percentage": "inverter_1/load_percentage",
    "bus_voltage": "inverter_1/bus_voltage",
    "battery_voltage": "inverter_1/battery_voltage",
    "battery_current": "inverter_1/battery_current",
    "battery_power": "inverter_1/battery_power",
    "battery_state_of_charge": "inverter_1/battery_state_of_charge",
    "temperature": "inverter_1/temperature",
    "device_mode": "inverter_1/device_mode",
    "serial_number": "inverter_1/serial_number",
    "output_source_priority": "inverter_1/output_source_priority",
    "charger_source_priority": "inverter_1/charger_source_priority",
    "max_charge_current": "inverter_1/max_charge_current",
    "max_grid_charge_current": "inverter_1/max_grid_charge_current",
    "shutdown_battery_voltage": "inverter_1/shutdown_battery_voltage",
    "back_to_battery_voltage": "inverter_1/back_to_battery_voltage",
    "to_grid_battery_voltage": "inverter_1/to_grid_battery_voltage",
    "battery_absorption_charge_voltage": "inverter_1/battery_absorption_charge_voltage",
    "battery_float_charge_voltage": "inverter_1/battery_float_charge_voltage",
}
TOPIC_TO_KEY = {f"{PREFIX}/{topic}/state": key for key, topic in KEY_MAP.items()}

# Some values SolarAssistant only publishes under total/* (aggregated over all
# inverters of the site). Used as a fallback when inverter_1/... never arrives.
FALLBACK_MAP = {
    "battery_power": "total/battery_power",
    "battery_state_of_charge": "total/battery_state_of_charge",
    "bus_voltage": "total/bus_voltage",
}
FALLBACK_TO_KEY = {f"{PREFIX}/{topic}/state": key for key, topic in FALLBACK_MAP.items()}
NUMERIC = {k for k in KEY_MAP if k not in ("device_mode", "serial_number",
                                           "output_source_priority", "charger_source_priority")}


class SaClient:
    """Resilient subscriber for the SolarAssistant broker (input side)."""

    def __init__(self, on_message, host=None, port=None, user=None, password=None):
        self.host = host or config.SA_MQTT_HOST
        self.port = port or config.SA_MQTT_PORT
        self.user = user if user is not None else config.SA_MQTT_USER
        self.password = password if password is not None else config.SA_MQTT_PASS
        self.on_message = on_message
        self.connected = threading.Event()
        self.restarts = 0
        self.client = None
        self.lock = threading.Lock()
        threading.Thread(target=self._run, name="sa-mqtt", daemon=True).start()

    def _run(self):
        while True:
            try:
                c = mqtt.Client(mqtt.CallbackAPIVersion.VERSION1,
                                client_id=f"sa-import-{config.SITE}", clean_session=True)
            except AttributeError:
                c = mqtt.Client(client_id=f"sa-import-{config.SITE}", clean_session=True)
            if self.user:
                c.username_pw_set(self.user, self.password)
            c.reconnect_delay_set(min_delay=1, max_delay=30)

            def on_connect(cl, userdata, flags, rc, *a):
                if rc != 0:
                    log.warning("sa broker refused rc=%s", rc)
                    return
                log.info("connected to SolarAssistant broker %s:%s", self.host, self.port)
                cl.subscribe(f"{PREFIX}/#", qos=1)
                self.connected.set()

            c.on_connect = on_connect
            c.on_message = lambda cl, ud, msg: self.on_message(msg.topic, msg.payload)
            c.on_disconnect = lambda *a: self.connected.clear()
            with self.lock:
                self.client = c
            try:
                c.connect(self.host, self.port, keepalive=60)
                c.loop_forever(retry_first_connection=True)
            except Exception as ex:  # noqa: BLE001
                log.warning("sa broker loop crashed: %r", ex)
            self.connected.clear()
            with self.lock:
                self.client = None
            self.restarts += 1
            time.sleep(5)

    def publish(self, topic, payload, wait=True) -> bool:
        with self.lock:
            c = self.client
        if c is None or not self.connected.is_set():
            return False
        info = c.publish(topic, payload, qos=1, retain=False)
        if wait:
            try:
                info.wait_for_publish(timeout=5)
            except Exception:  # noqa: BLE001
                return False
        return True


class SaSource:
    """Poller-compatible façade over a SolarAssistant MQTT output."""

    name = "sa-mqtt"

    def __init__(self, mq: publishers.MqttPublisher, influx: publishers.InfluxPublisher,
                 notifier=None, rules=None, battery=None):
        self.mq = mq
        self.influx = influx
        self.notifier = notifier
        self.rules = rules
        self.battery = battery
        self.state: dict = {"site": config.SITE}
        self.values: dict = {}
        self.energy = energy_mod.EnergyCounter()
        self.state.update({k: self.energy.data.get(k, 0.0)
                           for k in energy_mod.ENERGY_KEYS if k in self.energy.data})
        self.started = time.time()
        self.last_rx = 0.0
        self.last_ok: float | None = None
        self.online = False
        self.messages = 0
        self.unknown_topics = 0
        self._primary: set[str] = set()
        self._resp = threading.Event()
        self._resp_payload: bytes | None = None
        self._last_energy_ts: float | None = None
        self.client = SaClient(self._on_message)

    # -- input ---------------------------------------------------------------
    def _on_message(self, topic: str, payload: bytes):
        self.last_rx = time.time()
        self.messages += 1
        if topic == f"{PREFIX}/set/response_message/state":
            self._resp_payload = payload
            self._resp.set()
            return
        if topic == f"{PREFIX}/status":
            return
        key = TOPIC_TO_KEY.get(topic)
        primary = key is not None
        if key is None:
            key = FALLBACK_TO_KEY.get(topic)
            if key is None:
                self.unknown_topics += 1
                return
            if key in self._primary:
                return          # inverter_1/... is authoritative
        else:
            self._primary.add(key)
        text = payload.decode(errors="replace").strip()
        if key in NUMERIC:
            try:
                self.values[key] = float(text)
            except ValueError:
                return
        else:
            self.values[key] = text

    # -- state ---------------------------------------------------------------
    def _assemble(self) -> dict:
        state = dict(self.values)
        state["site"] = config.SITE
        # SolarAssistant publishes the PV total itself; only derive when absent.
        if "pv_power" not in state:
            energy_mod.derive_pv(state)
        energy_mod.derive_power(state)
        gv = state.get("grid_voltage")
        if gv is not None:
            state["mains_ok"] = 1 if gv > 100 else 0
        if (state.get("pv_voltage_2") or 0) > 20 or (state.get("pv_power_2") or 0) > 50:
            state["has_mppt2"] = 1
        # SolarAssistant has no "warnings" topic on this build: keep the field away
        # instead of inventing values.
        return state

    def snapshot(self) -> dict:
        return dict(self.state)

    def describe(self) -> str:
        return f"sa-mqtt {config.SA_MQTT_HOST}:{config.SA_MQTT_PORT}"

    def health(self) -> dict:
        last = self.state.get("last_update")
        return {
            "ok": bool(self.online),
            "online": self.online,
            "last_update": last,
            "age_s": round(time.time() - last, 1) if last else None,
            "consecutive_failures": 0 if self.online else 1,
            "uptime_s": round(time.time() - self.started),
            "transport": f"sa-mqtt {config.SA_MQTT_HOST}:{config.SA_MQTT_PORT}",
            "site": config.SITE,
            "mqtt_connected": self.mq.connected.is_set(),
            "mqtt_restarts": self.mq.restarts,
            "sa_connected": self.client.connected.is_set(),
            "sa_messages": self.messages,
            "influx_written": self.influx.written,
            "influx_errors": self.influx.errors,
        }

    # -- settings ------------------------------------------------------------
    def submit_set(self, key: str, payload, verified: bool = True, timeout: float = 25.0) -> dict:
        if key == "reload_settings":
            return {"ok": True, "key": key, "message": "Saved"}
        if key not in KEY_MAP:
            return {"ok": False, "key": key,
                    "message": f"Error: {key} is not writable through SolarAssistant"}
        if not config.ALLOW_SETTINGS:
            return {"ok": False, "key": key, "message": "Error: setting changes are disabled"}
        value = payload.decode(errors="replace") if isinstance(payload, bytes) else str(payload)
        suffix = "set_verified" if verified else "set"
        topic = f"{PREFIX}/{KEY_MAP[key]}/{suffix}"
        self._resp.clear()
        self._resp_payload = None
        if not self.client.publish(topic, value):
            return {"ok": False, "key": key, "message": "Error: SolarAssistant is not reachable"}
        if not self._resp.wait(timeout):
            return {"ok": False, "key": key, "message": "Error: no answer from SolarAssistant"}
        message = (self._resp_payload or b"").decode(errors="replace").strip()
        ok = message.lower().startswith("saved") or message.lower() == "ok"
        return {"ok": ok, "key": key, "value": value, "message": message or "Error: empty answer"}

    # -- rules ---------------------------------------------------------------
    def _run_rules(self, now: float):
        if self.rules is None:
            return
        try:
            fired = self.rules.evaluate(self.state, now)
        except Exception:  # noqa: BLE001
            log.exception("rule evaluation failed")
            return
        for rule in fired:
            log.info("rule fired: %s", rule.get("name"))
            for act in rule["then"]:
                try:
                    if act.get("type") == "notify":
                        text = self.rules.render(act.get("text", ""), self.state)
                        if self.notifier is not None:
                            self.notifier.send(f"{rule.get('name')}: {text}")
                    elif act.get("type") == "set":
                        result = self.submit_set(act["key"], act.get("value"),
                                                bool(act.get("verified", True)))
                        log.info("rule set %s -> %s", act["key"], result.get("message"))
                    elif act.get("type") == "mqtt":
                        self.mq.publish(act["topic"], self.rules.render(act.get("payload", ""), self.state),
                                        retain=bool(act.get("retain", False)))
                except Exception:  # noqa: BLE001
                    log.exception("rule action failed: %r", act)
            self.rules.mark_fired(rule, now)

    # -- loop ----------------------------------------------------------------
    def cycle(self):
        now = time.time()
        if self.last_rx and now - self.last_rx > config.OFFLINE_AFTER:
            if self.online:
                log.warning("SolarAssistant stopped publishing (%.0fs)", now - self.last_rx)
                self.mq.publish(publishers.STATUS_TOPIC, "offline", retain=True)
                self.online = False
                if self.notifier:
                    self.notifier.send(f"⚠️ {config.DEVICE_NAME}: нет данных от SolarAssistant")
            return

        if not self.values:
            return

        self.state.update(self._assemble())
        self.state["last_update"] = int(now)
        self.energy.accumulate(self.state, now)      # seeds ts on the first pass
        self._last_energy_ts = now

        if self.battery is not None:
            self.battery.reapply(self.state)
        publishers.publish_state(self.mq, self.state)
        self.influx.write(self.state, now)
        self._run_rules(now)

        if not self.online:
            log.info("online (sa-mqtt): %s messages", self.messages)
            self.mq.publish(publishers.STATUS_TOPIC, "online", retain=True)
            self.online = True
        self.last_ok = now
        log.info("%s | grid %.1fV | batt %.1fV %s%% | load %.0fW | pv %.0fW",
                 self.state.get("device_mode", "?"), self.state.get("grid_voltage") or 0,
                 self.state.get("battery_voltage") or 0,
                 self.state.get("battery_state_of_charge", "?"),
                 self.state.get("load_power") or 0, self.state.get("pv_power") or 0)

    def run(self):
        publishers.publish_discovery(self.mq, self.state)
        log.info("importing SolarAssistant from %s:%s as site %r",
                 config.SA_MQTT_HOST, config.SA_MQTT_PORT, config.SITE)
        while True:
            try:
                self.cycle()
            except Exception:  # noqa: BLE001
                log.exception("sa-mqtt cycle failed")
            time.sleep(max(0.5, config.POLL_INTERVAL))


def is_sa_source() -> bool:
    return config.TRANSPORT in ("sa-mqtt", "sa", "solarassistant")
