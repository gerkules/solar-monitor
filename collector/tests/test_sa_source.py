"""SolarAssistant import (sa-mqtt): topic mapping, derivation, settings writes."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, sa_source  # noqa: E402


class FakeMqtt:
    class _Ev:
        @staticmethod
        def is_set():
            return True

    connected = _Ev()
    restarts = 0

    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.sent.append((topic, payload, retain))
        return True

    def subscribe(self, *a, **kw):
        pass


class FakeInflux:
    def __init__(self):
        self.written = self.errors = 0
        self.states = []

    def write(self, state, ts=None):
        self.written += 1
        self.states.append(dict(state))


class FakeClient:
    response = None

    def __init__(self, on_message, *a, **kw):
        self.on_message = on_message
        self.published = []
        FakeClient.instance = self

        class _Ev:
            def is_set(self):
                return True

            def clear(self):
                pass

        self.connected = _Ev()

    def publish(self, topic, payload, wait=True):
        self.published.append((topic, payload))
        if FakeClient.response is not None:
            self.on_message("solar_assistant/set/response_message/state", FakeClient.response)
        return True


def feed(src, suffix, value, prefix="inverter_1"):
    src._on_message(f"solar_assistant/{prefix}/{suffix}/state",
                    str(value).encode())


class SaSourceTest(unittest.TestCase):
    def setUp(self):
        self._orig = (config.SITE, config.OFFLINE_AFTER, config.SITE_TTL)
        config.SITE = "office"
        config.OFFLINE_AFTER = 120
        self.mq, self.influx = FakeMqtt(), FakeInflux()
        with mock.patch.object(sa_source, "SaClient", FakeClient):
            self.src = sa_source.SaSource(self.mq, self.influx)
        self.src.energy.path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name

    def tearDown(self):
        (config.SITE, config.OFFLINE_AFTER, config.SITE_TTL) = self._orig

    def test_topic_mapping(self):
        feed(self.src, "pv_power", 1500)
        feed(self.src, "battery_voltage", "52.6")
        feed(self.src, "battery_charge_current", 0)   # not in map -> ignored
        feed(self.src, "device_mode", "Solar/Battery")
        feed(self.src, "grid_voltage", 231.2)
        self.src.cycle()
        s = self.src.state
        self.assertEqual(s["pv_power"], 1500)
        self.assertEqual(s["battery_voltage"], 52.6)
        self.assertEqual(s["device_mode"], "Solar/Battery")
        self.assertEqual(s["mains_ok"], 1)
        self.assertEqual(s["site"], "office")
        self.assertIn("last_update", s)

    def test_pv_total_from_sa_wins(self):
        feed(self.src, "pv_power", 1227)
        feed(self.src, "pv_power_1", 800)
        feed(self.src, "pv_power_2", 400)
        self.src.cycle()
        self.assertEqual(self.src.state["pv_power"], 1227)    # SA total is authoritative

    def test_pv_total_derived_when_missing(self):
        feed(self.src, "pv_power_1", 400)
        feed(self.src, "pv_power_2", 300)
        self.src.cycle()
        self.assertEqual(self.src.state["pv_power"], 700)

    def test_battery_power_derived(self):
        feed(self.src, "battery_voltage", 52.0)
        feed(self.src, "load_power", 900)
        feed(self.src, "pv_power", 400)
        feed(self.src, "pv_power_2", 300)
        feed(self.src, "pv_voltage_2", 180.0)
        self.src.cycle()
        self.assertEqual(self.src.state["has_mppt2"], 1)

    def test_fallback_to_total_topics(self):
        self.src._on_message("solar_assistant/total/battery_state_of_charge/state", b"88")
        self.src._on_message("solar_assistant/total/battery_power/state", b"-105")
        self.src.cycle()
        self.assertEqual(self.src.state["battery_state_of_charge"], 88)
        self.assertEqual(self.src.state["battery_power"], -105)

    def test_inverter_topic_wins_over_total(self):
        self.src._on_message("solar_assistant/inverter_1/battery_state_of_charge/state", b"81")
        self.src._on_message("solar_assistant/total/battery_state_of_charge/state", b"88")
        self.src.cycle()
        self.assertEqual(self.src.state["battery_state_of_charge"], 81)

    def test_single_mppt_has_no_flag(self):
        feed(self.src, "pv_power_2", 0)
        feed(self.src, "pv_voltage_2", 0)
        self.src.cycle()
        self.assertNotIn("has_mppt2", self.src.state)

    def test_unknown_topic_is_counted_not_stored(self):
        self.src._on_message("solar_assistant/inverter_1/nonsense/state", b"1")
        self.assertEqual(self.src.unknown_topics, 1)
        self.assertEqual(self.src.values, {})

    def test_cycle_publishes_and_writes(self):
        feed(self.src, "pv_power", 800)
        feed(self.src, "battery_state_of_charge", 77)
        self.src.cycle()
        topics = [t for t, _, _ in self.mq.sent]
        self.assertIn("solar/office/state", topics)
        self.assertIn("solar/office/status", topics)
        self.assertEqual(self.influx.written, 1)
        self.assertTrue(self.src.online)
        self.assertTrue(self.src.health()["ok"])

    def test_no_data_means_no_publish(self):
        self.src.cycle()
        self.assertEqual(self.mq.sent, [])
        self.assertFalse(self.src.online)

    def test_goes_offline_when_sa_stops(self):
        feed(self.src, "pv_power", 800)
        self.src.cycle()
        self.src.last_rx -= (config.OFFLINE_AFTER + 10)
        self.src.cycle()
        self.assertFalse(self.src.online)
        self.assertIn(("solar/office/status", "offline", True), self.mq.sent)

    def test_settings_write_forwarded_and_verified(self):
        FakeClient.response = b"Saved"
        res = self.src.submit_set("max_charge_current", "60", verified=True)
        self.assertTrue(res["ok"], res)
        self.assertEqual(FakeClient.instance.published,
                         [("solar_assistant/inverter_1/max_charge_current/set_verified", "60")])

    def test_settings_write_error_reported(self):
        FakeClient.response = b"Error: The inverter acknowledged the value but did not apply it"
        res = self.src.submit_set("max_charge_current", "200", verified=True)
        self.assertFalse(res["ok"])
        self.assertIn("did not apply", res["message"])

    def test_unknown_setting_rejected(self):
        res = self.src.submit_set("nonsense", "1")
        self.assertFalse(res["ok"])
        self.assertIn("not writable", res["message"])

    def test_unverified_write_uses_set_topic(self):
        FakeClient.response = b"Saved"
        self.src.submit_set("output_source_priority", "SBU", verified=False)
        self.assertEqual(FakeClient.instance.published[0][0],
                         "solar_assistant/inverter_1/output_source_priority/set")

    def test_health_reports_source(self):
        h = self.src.health()
        self.assertIn("sa-mqtt", h["transport"])
        self.assertEqual(h["site"], "office")
        self.assertIn("sa_connected", h)


class TestTransportSelection(unittest.TestCase):
    def test_is_sa_source(self):
        orig = config.TRANSPORT
        try:
            for value, expected in (("sa-mqtt", True), ("solarassistant", True),
                                    ("tcp", False), ("hid", False)):
                config.TRANSPORT = value
                self.assertEqual(sa_source.is_sa_source(), expected, value)
        finally:
            config.TRANSPORT = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
