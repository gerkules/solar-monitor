"""Страница «MQTT»: параметры публикации, брокер и мосты (без реального mosquitto)."""
import importlib
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, mqttadmin  # noqa: E402


class OwnSettingsTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = os.path.join(self.tmp.name, "mqtt.json")
        self.patch = mock.patch.object(config, "MQTT_OVERRIDE_FILE", self.path)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_save_writes_override_without_restart(self):
        res = mqttadmin.save_own({"host": "192.168.1.220", "port": 1883,
                                  "user": "gerkules", "password": "secret",
                                  "prefix": "solar/pi", "tls": False,
                                  "discovery": True}, restart=False)
        self.assertFalse(res["restarting"])
        with open(self.path, encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["host"], "192.168.1.220")
        self.assertEqual(data["password"], "secret")
        self.assertEqual(oct(os.stat(self.path).st_mode & 0o777), "0o600")

    def test_empty_password_keeps_previous(self):
        mqttadmin.save_own({"host": "a", "port": 1883, "password": "keepme"}, restart=False)
        mqttadmin.save_own({"host": "a", "port": 1883}, restart=False)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["password"], "keepme")

    def test_dash_clears_password(self):
        mqttadmin.save_own({"host": "a", "port": 1883, "password": "keepme"}, restart=False)
        mqttadmin.save_own({"host": "a", "port": 1883, "password": "-"}, restart=False)
        with open(self.path, encoding="utf-8") as f:
            self.assertEqual(json.load(f)["password"], "")

    def test_validation(self):
        for bad in ({"host": "mqtt://a"}, {"host": "a b"}, {"host": "a", "port": 70000},
                    {"host": "a", "port": "x"}, {"host": "a", "prefix": "solar/#"}):
            with self.assertRaises(mqttadmin.MqttError, msg=str(bad)):
                mqttadmin.save_own(bad, restart=False)

    def test_own_reports_current_values(self):
        data = mqttadmin.own()
        self.assertIn("host", data)
        self.assertIn("has_password", data)


class BridgeConfTests(unittest.TestCase):
    def test_conf_contains_direction_and_credentials(self):
        conf = mqttadmin.bridge_conf({"name": "home", "address": "192.168.1.224",
                                      "username": "gerkules", "password": "pw",
                                      "pattern": "solar/#", "direction": "out"})
        self.assertIn("connection home", conf)
        self.assertIn("address 192.168.1.224:1883", conf)
        self.assertIn("remote_username gerkules", conf)
        self.assertIn("remote_password pw", conf)
        self.assertIn("topic solar/# out 0", conf)
        self.assertIn("try_private false", conf)

    def test_conf_without_credentials(self):
        conf = mqttadmin.bridge_conf({"name": "pi", "address": "192.168.1.220:1883",
                                      "pattern": "solar/home/#", "direction": "in"})
        self.assertNotIn("remote_username", conf)
        self.assertIn("topic solar/home/# in 0", conf)

    def test_bad_values(self):
        base = {"name": "x", "address": "1.2.3.4", "pattern": "solar/#", "direction": "out"}
        for bad in ({"address": "mqtt://host"}, {"pattern": "solar/#/bad key"},
                    {"direction": "sideways"}):
            with self.assertRaises(mqttadmin.MqttError, msg=str(bad)):
                mqttadmin.bridge_conf({**base, **bad})


class HelperTests(unittest.TestCase):
    def setUp(self):
        self.patch = mock.patch.object(mqttadmin, "native_available", return_value=True)
        self.patch.start()
        self.addCleanup(self.patch.stop)

    def test_bridge_save_passes_validated_conf(self):
        captured = {}

        def fake_helper(*args, stdin=None, timeout=30.0):
            captured["args"] = args
            captured["stdin"] = stdin
            return {"ok": True, "name": args[1]}

        with mock.patch.object(mqttadmin, "_helper", fake_helper):
            res = mqttadmin.bridge_save({"name": "Home_1".lower(), "address": "192.168.1.224",
                                         "pattern": "solar/#", "direction": "out"})
        self.assertEqual(res["name"], "home_1")
        self.assertEqual(captured["args"], ("bridge-save", "home_1"))
        self.assertIn("connection home_1", captured["stdin"])

    def test_bridge_name_validation(self):
        for bad in ("1bad", "UPPER", "a", "with space", "x" * 30):
            with self.assertRaises(mqttadmin.MqttError, msg=bad):
                mqttadmin.bridge_save({"name": bad, "address": "1.2.3.4"})
            with self.assertRaises(mqttadmin.MqttError, msg=bad):
                mqttadmin.bridge_delete(bad)

    def test_broker_user_validation(self):
        with mock.patch.object(mqttadmin, "_helper", return_value={"ok": True}):
            with self.assertRaises(mqttadmin.MqttError):
                mqttadmin.broker_action("user-add", {"user": "ok", "password": "123"})
            with self.assertRaises(mqttadmin.MqttError):
                mqttadmin.broker_action("user-add", {"user": "плохой", "password": "123456"})
            self.assertTrue(mqttadmin.broker_action("user-add",
                                                    {"user": "solar", "password": "123456"})["ok"])

    def test_snapshot_shape(self):
        with mock.patch.object(mqttadmin, "broker_status", return_value={"active": True}), \
                mock.patch.object(mqttadmin, "bridges", return_value=[]):
            snap = mqttadmin.snapshot(connected=True)
        for key in ("own", "native", "broker", "bridges", "connected"):
            self.assertIn(key, snap)


class NoNativeTests(unittest.TestCase):
    def test_bridge_ops_fail_in_container(self):
        with mock.patch.object(mqttadmin, "native_available", return_value=False):
            with self.assertRaises(mqttadmin.MqttError):
                mqttadmin.bridge_save({"name": "home", "address": "1.2.3.4"})
            self.assertIsNone(mqttadmin.broker_status())
            snap = mqttadmin.snapshot()
            self.assertFalse(snap["native"])
            self.assertEqual(snap["bridges"], [])


class ConfigOverrideTests(unittest.TestCase):
    """Файл из UI должен перекрывать .env при импорте конфига."""

    def test_override_is_applied(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "mqtt.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"host": "10.0.0.5", "port": 1884, "user": "u",
                           "password": "p", "prefix": "solar/x",
                           "tls": True, "discovery": False}, f)
            try:
                with mock.patch.dict(os.environ, {"MQTT_OVERRIDE_FILE": path}):
                    mod = importlib.reload(config)
                    self.assertEqual(mod.MQTT_HOST, "10.0.0.5")
                    self.assertEqual(mod.MQTT_PORT, 1884)
                    self.assertEqual(mod.MQTT_USER, "u")
                    self.assertTrue(mod.MQTT_TLS)
                    self.assertFalse(mod.HA_DISCOVERY)
                    self.assertEqual(mod.MQTT_PREFIX, "solar/x")
                    self.assertEqual(mod.SITE_ROOT, "solar")
            finally:
                importlib.reload(config)      # вернуть исходные значения


if __name__ == "__main__":
    unittest.main()
