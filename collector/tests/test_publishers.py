"""Publisher/API tests: no broker and no InfluxDB needed (everything mocked)."""
import io
import json
import os
import sys
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import api, config, publishers  # noqa: E402

STATE = {
    "pv_power": 1234, "pv_power_1": 1000, "pv_power_2": 234,
    "load_power": 900, "grid_power": 0, "battery_power": -200,
    "battery_voltage": 52.6, "battery_state_of_charge": 88,
    "device_mode": "Battery", "warnings": "none", "mains_ok": 1,
    "serial_number": "TEST000000000001", "rated_power": 11000,
    "output_source_priority": "SBU", "charger_source_priority": "Solar only",
    "max_charge_current": 150, "battery_float_charge_voltage": 57.6,
    "pv_energy_today": 3.42, "load_energy_today": 2.10, "grid_energy_today": 0.0,
    "battery_charge_today": 1.1, "battery_discharge_today": 2.2,
    "temperature": 48, "mode": "Battery",
}


class FakeMqtt:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.sent.append((topic, payload, retain))
        return True


class TestDiscovery(unittest.TestCase):
    def setUp(self):
        config.SITE = "office"
        config.ENTITY_PREFIX = "solar_office"
        config.MQTT_PREFIX = "solar/office"

    def test_messages_are_unique_and_valid(self):
        msgs = publishers.discovery_messages(STATE)
        self.assertGreaterEqual(len(msgs), 40)
        topics = [t for t, _ in msgs]
        self.assertEqual(len(topics), len(set(topics)))
        for topic, payload in msgs:
            self.assertTrue(topic.startswith("homeassistant/"))
            self.assertTrue(topic.endswith("/config"))
            json.dumps(payload)
            self.assertIn("unique_id", payload)
            self.assertEqual(payload["availability_topic"], "solar/office/status")
            self.assertEqual(payload["device"]["identifiers"], ["solar_office_pi30"])

    def test_selects_and_numbers_have_command_topics(self):
        msgs = dict(publishers.discovery_messages(STATE))
        sel = msgs["homeassistant/select/solar_office_output_source_priority/config"]
        self.assertEqual(sel["command_topic"],
                         "solar/office/inverter_1/output_source_priority/set")
        self.assertIn("SBU", sel["options"])
        num = msgs["homeassistant/number/solar_office_battery_float_charge_voltage/config"]
        self.assertEqual(num["command_topic"],
                         "solar/office/inverter_1/battery_float_charge_voltage/set")
        self.assertEqual(num["unit_of_measurement"], "V")

    def test_discovery_can_be_disabled(self):
        mq = FakeMqtt()
        with mock.patch.object(config, "HA_DISCOVERY", False):
            publishers.publish_discovery(mq, STATE)
        self.assertEqual(mq.sent, [])

    def test_publish_state_topics(self):
        mq = FakeMqtt()
        publishers.publish_state(mq, STATE)
        topics = {t: (p, r) for t, p, r in mq.sent}
        self.assertEqual(topics["solar/office/state"][0]["pv_power"], 1234)
        self.assertEqual(topics["solar/office/inverter_1/pv_power/state"][0], 1234)
        # settings are retained so a restarting consumer sees them immediately
        self.assertTrue(topics["solar/office/inverter_1/battery_float_charge_voltage/state"][1])
        self.assertFalse(topics["solar/office/inverter_1/pv_power/state"][1])


class TestInflux(unittest.TestCase):
    def test_line_protocol(self):
        pub = publishers.InfluxPublisher()
        pub.enabled = True
        pub.url = "http://influxdb:8086/api/v2/write?org=solar&bucket=solar&precision=s"
        captured = {}

        class Resp(io.BytesIO):
            status = 204

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake_urlopen(req, timeout=5):
            captured["body"] = req.data.decode()
            return Resp()

        with mock.patch.object(config, "SITE", "office"), \
             mock.patch("urllib.request.urlopen", fake_urlopen):
            pub.write(STATE, ts=1700000000)
        body = captured["body"]
        self.assertIn("pv_power,site=office value=1234 1700000000", body)
        self.assertIn("battery_state_of_charge,site=office value=88", body)
        # strings / None must never reach Influx
        self.assertNotIn("device_mode", body)
        self.assertNotIn("None", body)
        self.assertEqual(pub.written, 14)   # every numeric METRIC present in STATE


class TestApiHelpers(unittest.TestCase):
    def setUp(self):
        config.SITE = "office"
        config.ENTITY_PREFIX = "solar_office"
        config.MQTT_PREFIX = "solar/office"

    def test_metrics_list_and_glob(self):
        items = api.metrics_list(STATE)
        self.assertTrue(any(i["topic"] == "inverter_1/pv_power" for i in items))
        batt = api.metrics_list(STATE, "inverter_1/battery*")
        self.assertTrue(batt)
        self.assertTrue(all(i["topic"].startswith("inverter_1/battery") for i in batt))
        total = api.metrics_list(STATE, "inverter_1/*_energy_today")
        self.assertEqual(len(total), 3)      # pv/load/grid (battery_*_today are named differently)

    def test_settings_schema(self):
        schema = api.settings_schema(STATE)
        self.assertEqual(len(schema), 10)   # 9 PI30 settings + battery type
        by_key = {s["key"]: s for s in schema}
        self.assertEqual(by_key["output_source_priority"]["value"], "SBU")
        self.assertEqual(len(by_key["charger_source_priority"]["options"]), 4)
        self.assertEqual(by_key["max_charge_current"]["unit"], "A")


if __name__ == "__main__":
    unittest.main(verbosity=2)
