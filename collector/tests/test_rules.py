"""Automation rules: validation, persistence, debounce, cooldown, templating."""
import json
import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, rules  # noqa: E402

STATE = {
    "battery_state_of_charge": 21, "battery_voltage": 48.6,
    "pv_power": 1500, "load_percentage": 95, "device_mode": "Battery",
}


class RuleTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "rules.json")
        self.engine = rules.RuleEngine(self.path)
        config.AUTOMATION = True

    def tearDown(self):
        self.tmp.cleanup()
        config.AUTOMATION = True

    def make(self, **over):
        rule = {
            "name": "low soc",
            "when": {"metric": "battery_state_of_charge", "op": "<", "value": 25, "for_s": 0},
            "then": [{"type": "notify", "text": "soc {battery_state_of_charge}%"}],
            "cooldown_s": 0,
        }
        rule.update(over)
        return self.engine.add(rule)


class TestValidation(RuleTestCase):
    def test_rejects_bad_operator(self):
        with self.assertRaises(ValueError):
            self.engine.add({"when": {"metric": "x", "op": "~", "value": 1},
                             "then": [{"type": "notify"}]})

    def test_rejects_bad_action(self):
        with self.assertRaises(ValueError):
            self.engine.add({"when": {"metric": "x", "op": ">", "value": 1},
                             "then": [{"type": "explode"}]})
        with self.assertRaises(ValueError):
            self.engine.add({"when": {"metric": "x", "op": ">", "value": 1},
                             "then": [{"type": "set"}]})       # no key

    def test_defaults_are_filled(self):
        r = self.engine.add({"when": {"metric": "pv_power", "op": ">", "value": 100},
                             "then": [{"type": "notify"}]})
        self.assertTrue(r["enabled"])
        self.assertEqual(r["cooldown_s"], 300)
        self.assertEqual(r["when"]["for_s"], 0)
        self.assertTrue(r["then"][0]["text"])
        self.assertEqual(len(r["id"]), 8)

    def test_persists_and_reloads(self):
        r = self.make()
        again = rules.RuleEngine(self.path)
        self.assertEqual(len(again.list()), 1)
        self.assertEqual(again.list()[0]["id"], r["id"])
        with open(self.path) as f:
            self.assertEqual(json.load(f)["version"], 1)


class TestEvaluation(RuleTestCase):
    def test_fires_when_condition_true(self):
        self.make()
        fired = self.engine.evaluate(STATE, now=1000)
        self.assertEqual(len(fired), 1)
        self.engine.mark_fired(fired[0], now=1000)
        self.assertEqual(fired[0]["fired_count"], 1)
        self.assertEqual(self.engine.fired, 1)

    def test_does_not_fire_when_false(self):
        self.make()
        self.assertEqual(self.engine.evaluate({**STATE, "battery_state_of_charge": 80}, now=1000), [])

    def test_debounce_for_s(self):
        self.make(when={"metric": "battery_state_of_charge", "op": "<", "value": 25, "for_s": 60})
        self.assertEqual(self.engine.evaluate(STATE, now=1000), [])
        self.assertEqual(self.engine.evaluate(STATE, now=1030), [])
        fired = self.engine.evaluate(STATE, now=1061)
        self.assertEqual(len(fired), 1)

    def test_condition_reset_restarts_timer(self):
        self.make(when={"metric": "battery_state_of_charge", "op": "<", "value": 25, "for_s": 60})
        self.engine.evaluate(STATE, now=1000)
        self.engine.evaluate({**STATE, "battery_state_of_charge": 90}, now=1030)
        self.assertEqual(self.engine.evaluate(STATE, now=1040), [])   # timer restarted
        self.assertEqual(len(self.engine.evaluate(STATE, now=1101)), 1)

    def test_cooldown(self):
        r = self.make(cooldown_s=600)
        fired = self.engine.evaluate(STATE, now=1000)
        self.engine.mark_fired(fired[0], now=1000)
        self.assertEqual(self.engine.evaluate(STATE, now=1200), [])   # inside cooldown
        self.assertEqual(len(self.engine.evaluate(STATE, now=1700)), 1)

    def test_string_equality(self):
        self.engine.add({"name": "mode", "when": {"metric": "device_mode", "op": "==", "value": "Fault"},
                         "then": [{"type": "notify", "text": "fault!"}], "cooldown_s": 0})
        self.assertEqual(self.engine.evaluate(STATE, now=1), [])
        fired = self.engine.evaluate({**STATE, "device_mode": "Fault"}, now=2)
        self.assertEqual(len(fired), 1)

    def test_disabled_rule_is_skipped(self):
        r = self.make()
        self.engine.set_enabled(r["id"], False)
        self.assertEqual(self.engine.evaluate(STATE, now=1000), [])

    def test_missing_metric_is_skipped(self):
        self.make(when={"metric": "nope", "op": ">", "value": 0, "for_s": 0})
        self.assertEqual(self.engine.evaluate(STATE, now=1000), [])

    def test_automation_switch_off(self):
        self.make()
        config.AUTOMATION = False
        self.assertEqual(self.engine.evaluate(STATE, now=1000), [])

    def test_delete(self):
        r = self.make()
        self.assertTrue(self.engine.delete(r["id"]))
        self.assertFalse(self.engine.delete(r["id"]))
        self.assertEqual(self.engine.list(), [])


class TestTemplating(unittest.TestCase):
    def test_render(self):
        text = rules.RuleEngine.render("soc {battery_state_of_charge}% / {battery_voltage} В / {nope}",
                                       STATE)
        self.assertIn("21%", text)
        self.assertIn("48.6", text)
        self.assertIn("{nope}", text)

    def test_examples_are_valid(self):
        engine_path = os.path.join(tempfile.mkdtemp(), "r.json")
        engine = rules.RuleEngine(engine_path)
        for ex in rules.EXAMPLES:
            engine.add(ex)
        self.assertEqual(len(engine.list()), len(rules.EXAMPLES))


if __name__ == "__main__":
    unittest.main(verbosity=2)
