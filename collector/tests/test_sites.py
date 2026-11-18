"""Multi-site registry: states are collected from the broker per site."""
import json
import os
import sys
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, sites  # noqa: E402


class FakeMqtt:
    def __init__(self):
        self.subs = {}

    def subscribe(self, topic, cb):
        self.subs[topic] = cb

    def publish(self, *a, **kw):
        return True

    def feed(self, topic, payload: dict):
        """Call the handler the way MqttPublisher does (topic, payload)."""
        for pattern, cb in self.subs.items():
            if pattern.endswith("/state") and topic.endswith("/state"):
                cb(topic, json.dumps(payload).encode())
            elif pattern.endswith("/status") and topic.endswith("/status"):
                cb(topic, payload.encode())


class FakePoller:
    def __init__(self, state):
        self._state = state

    def snapshot(self):
        return dict(self._state)


LOCAL = {"site": "home", "pv_power": 1000, "battery_state_of_charge": 80,
         "device_mode": "Battery", "last_update": int(time.time())}
OFFICE = {"site": "office", "pv_power": 2500, "battery_state_of_charge": 55,
          "device_mode": "Solar/Battery", "last_update": int(time.time())}


class TestSiteRegistry(unittest.TestCase):
    def setUp(self):
        self._root = config.SITE_ROOT
        config.SITE_ROOT = "solar"
        config.SITE = "home"
        self.mq = FakeMqtt()
        self.reg = sites.SiteRegistry(self.mq, local_poller=FakePoller(LOCAL))

    def tearDown(self):
        config.SITE_ROOT = self._root
        config.SITE = "office"

    def test_subscribes_to_wildcards(self):
        self.assertIn("solar/+/state", self.mq.subs)
        self.assertIn("solar/+/status", self.mq.subs)

    def test_collects_remote_site(self):
        self.mq.feed("solar/office/state", OFFICE)
        names = [s["site"] for s in self.reg.sites()]
        self.assertEqual(names, ["home", "office"])
        office = next(s for s in self.reg.sites() if s["site"] == "office")
        self.assertEqual(office["pv_power"], 2500)
        self.assertTrue(office["online"])

    def test_local_site_comes_from_poller(self):
        self.assertEqual(self.reg.get("home")["pv_power"], 1000)
        self.assertEqual(self.reg.get(None)["pv_power"], 1000)

    def test_unknown_site(self):
        self.assertIsNone(self.reg.get("nowhere"))

    def test_status_topic_marks_offline(self):
        self.mq.feed("solar/office/state", OFFICE)
        self.mq.feed("solar/office/status", "offline")
        self.assertFalse(self.reg.online["office"])

    def test_stale_state_is_not_online(self):
        old = dict(OFFICE, last_update=int(time.time()) - 3600)
        self.mq.feed("solar/office/state", old)
        office = next(s for s in self.reg.sites() if s["site"] == "office")
        self.assertFalse(office["online"])
        self.assertGreater(office["age_s"], 1000)

    def test_stale_sites_are_forgotten(self):
        self.mq.feed("solar/office/state", OFFICE)
        self.assertIn("office", [s["site"] for s in self.reg.sites()])
        self.reg.updated["office"] -= (config.SITE_TTL + 10)
        self.assertNotIn("office", [s["site"] for s in self.reg.sites()])
        self.assertIsNone(self.reg.get("office"))

    def test_garbage_payload_is_ignored(self):
        self.mq.subs["solar/+/state"]("solar/x/state", b"not json")
        self.assertIsNone(self.reg.get("x"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
