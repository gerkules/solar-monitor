"""Unit tests for the PI30 layer. Frames below are real captures from an
Axpert 11 kW (S/N 96342404105016) taken over the EW10 TCP socket."""
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import energy, pi30, settings  # noqa: E402

QPIGS = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
         b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')
QPIRI = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
         b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')
QMOD = b'(B\xe7\xc9\r'
QID = b'(96342404105016\xa1*\r'
QPIGS2 = b'(00.0 000.0 00000 E\x93\r'
QPIWS = b'(0000000000000000000000000000000000000000\x00\x00\r'


class TestFraming(unittest.TestCase):
    def test_crc_and_frame(self):
        self.assertEqual(pi30.frame("QPIGS"), b"QPIGS\xb7\xa9\r")
        self.assertTrue(pi30.check_frame(QPIGS))
        self.assertTrue(pi30.check_frame(QPIRI))

    def test_broken_frame_rejected(self):
        broken = QPIGS[:-3] + b"\x00\x00\r"
        self.assertFalse(pi30.check_frame(broken))
        self.assertFalse(pi30.check_frame(b"(NAK\r"))
        self.assertFalse(pi30.check_frame(b""))

    def test_ack_nak(self):
        self.assertTrue(pi30.is_ack(b"(ACK\r"))
        self.assertTrue(pi30.is_nak(b"(NAK\r"))
        self.assertFalse(pi30.is_ack(QPIGS))


class TestParsers(unittest.TestCase):
    def test_qpigs(self):
        d = pi30.parse_qpigs(QPIGS)
        self.assertAlmostEqual(d["grid_voltage"], 231.3)
        self.assertEqual(d["load_power"], 165)
        self.assertAlmostEqual(d["battery_voltage"], 52.9)
        self.assertEqual(d["battery_state_of_charge"], 81)
        self.assertEqual(d["temperature"], 48)
        self.assertEqual(d["pv_power_1"], 0)
        self.assertEqual(d["mains_ok"], 1)

    def test_status_bits_are_lsb_last(self):
        """'00010000' must be bit 3 (battery steady), not bit 4 (battery low)."""
        d = pi30.parse_qpigs(QPIGS)
        self.assertEqual(d["status_bits"], 8)
        self.assertIn("battery_steady", d["status_flags"])
        self.assertNotIn("battery_low", d["status_flags"])

    def test_qpiri(self):
        d = pi30.parse_qpiri(QPIRI)
        self.assertEqual(d["rated_power"], 11000)
        self.assertEqual(d["rated_battery_voltage"], 48.0)
        self.assertEqual(d["battery_absorption_charge_voltage"], 57.6)
        self.assertEqual(d["battery_float_charge_voltage"], 57.6)
        self.assertEqual(d["shutdown_battery_voltage"], 44.8)
        self.assertEqual(d["to_grid_battery_voltage"], 50.0)
        self.assertEqual(d["back_to_battery_voltage"], 52.0)
        self.assertEqual(d["output_source_priority"], "SBU")
        self.assertEqual(d["charger_source_priority"], "Solar only")
        self.assertEqual(d["max_charge_current"], 150)
        self.assertEqual(d["max_grid_charge_current"], 2)

    def test_qmod_qid_qpigs2(self):
        self.assertEqual(pi30.parse_qmod(QMOD)["device_mode"], "Battery")
        self.assertEqual(pi30.parse_qid(QID)["serial_number"], "96342404105016")
        d = pi30.parse_qpigs2(QPIGS2)
        self.assertEqual(d["pv_power_2"], 0)

    def test_qpiws_clean(self):
        d = pi30.parse_qpiws(QPIWS)
        self.assertEqual(d["warning_bits"], 0)
        self.assertEqual(d["warnings"], "none")

    def test_qpiws_fault(self):
        bits = "0" * 40
        bits = "1" + bits[1:]                     # bit0 inverter_fault
        body = ("(" + bits).encode() + b"\x00\x00\r"
        d = pi30.parse_qpiws(body)
        self.assertEqual(d["warning_bits"], 1)
        self.assertIn("inverter_fault", d["warning_flags"])

    def test_qmod_rejects_foreign_frame(self):
        """A QPIGS frame in reply to QMOD must not become device_mode='2'."""
        foreign = (b'(228.3 50.0 230.1 49.9 00207 00164 001 427 54.50 045 098 0052 03.8 282.2'
                   b' 00.00 00000 00010110 00 00 01073 010 0 00 0000)\x80\r')
        self.assertEqual(pi30.parse_qmod(foreign), {})
        self.assertEqual(pi30.parse_qmod(b'(0\x00\x00\r'), {})
        self.assertEqual(pi30.parse_qmod(QMOD)["device_mode"], "Battery")
        self.assertEqual(pi30.parse_qmod(QMOD)["mode_code"], "B")

    def test_qid_rejects_garbage(self):
        self.assertEqual(pi30.parse_qid(QID)["serial_number"], "96342404105016")
        self.assertEqual(pi30.parse_qid(b'(228.3 50.0 230.1 49.9 00207\x00\x00\r'), {})
        self.assertEqual(pi30.parse_qid(b'(abc\x00\x00\r'), {})

    def test_qpiws_rejects_wrong_length(self):
        """A frame glued from two replies must not produce a phantom warning."""
        mixed = b'(00.0 066000000000000(00.0 060.1 00000 \xf3\xb4\r'
        self.assertEqual(pi30.parse_qpiws(mixed), {})

    def test_qpiws_39_bits_rejected(self):
        self.assertEqual(pi30.parse_qpiws(("(" + "0" * 39).encode() + b"\x00\x00\r"), {})

    def test_qpigs2_rejects_inconsistent_frame(self):
        """11 510 W from 0.1 A x 128 V (a glued frame) must be dropped."""
        frame = ("(0.1 128.2 11510").encode() + b"\x00\x00\r"
        self.assertEqual(pi30.parse_qpigs2(frame), {})
        good = ("(5.0 128.0 640").encode() + b"\x00\x00\r"
        self.assertEqual(pi30.parse_qpigs2(good)["pv_power_2"], 640)
        zero = ("(0.0 0.0 0").encode() + b"\x00\x00\r"
        self.assertEqual(pi30.parse_qpigs2(zero)["pv_power_2"], 0)

    def test_sanitize_drops_impossible_values(self):
        clean, dropped = pi30.sanitize({"battery_voltage": 52.8, "pv_power_2": 11510,
                                        "temperature": 999, "device_mode": "Battery"})
        self.assertEqual(clean["battery_voltage"], 52.8)
        self.assertEqual(clean["device_mode"], "Battery")
        self.assertNotIn("temperature", clean)
        self.assertEqual(sorted(dropped), ["temperature"])
        # pv_power_2 up to 30 kW is legitimate, so it stays
        self.assertEqual(clean["pv_power_2"], 11510)

    def test_garbage_does_not_crash(self):
        for bad in (b"", b"(", b"(1 2 3\r", b"(\xff\xfe\r"):
            self.assertEqual(pi30.parse_qpigs(bad), {})
            self.assertEqual(pi30.parse_qpiri(bad), {})


class TestSettings(unittest.TestCase):
    def setUp(self):
        self.specs = settings.effective_settings()

    def test_parse_select_labels_and_indexes(self):
        spec = self.specs["output_source_priority"]
        self.assertEqual(settings.parse_value(spec, "Solar first"), 1.0)
        self.assertEqual(settings.parse_value(spec, "sbu"), 2.0)
        self.assertEqual(settings.parse_value(spec, b"2"), 2.0)
        self.assertEqual(settings.parse_value(spec, "Solar/Utility/Battery"), 3.0)
        with self.assertRaises(ValueError):
            settings.parse_value(spec, "nonsense")

    def test_parse_number_range(self):
        spec = self.specs["shutdown_battery_voltage"]
        self.assertAlmostEqual(settings.parse_value(spec, "46,5"), 46.5)
        with self.assertRaises(ValueError):
            settings.parse_value(spec, "12")      # below minimum
        with self.assertRaises(ValueError):
            settings.parse_value(spec, "99")

    def test_commands(self):
        self.assertEqual(settings.build_command(self.specs["output_source_priority"], 2), "POP02")
        self.assertEqual(settings.build_command(self.specs["charger_source_priority"], 3), "PCP03")
        self.assertEqual(settings.build_command(self.specs["max_charge_current"], 60), "MNCHGC0060")
        self.assertEqual(settings.build_command(self.specs["max_grid_charge_current"], 30), "MUCHGC030")
        self.assertEqual(settings.build_command(self.specs["shutdown_battery_voltage"], 44.8), "PSDV44.8")
        self.assertEqual(settings.build_command(self.specs["back_to_battery_voltage"], 52.0), "PBDV52.0")
        self.assertEqual(settings.build_command(self.specs["to_grid_battery_voltage"], 50.0), "PBCV50.0")
        self.assertEqual(settings.build_command(self.specs["battery_absorption_charge_voltage"], 57.6), "PCVV57.6")
        self.assertEqual(settings.build_command(self.specs["battery_float_charge_voltage"], 57.6), "PBFT57.6")

    def test_readback_match(self):
        spec = self.specs["output_source_priority"]
        self.assertTrue(settings.same_value(spec, 2, "SBU"))
        self.assertFalse(settings.same_value(spec, 1, "SBU"))
        self.assertTrue(settings.same_value(self.specs["shutdown_battery_voltage"], 44.8, 44.8))
        self.assertFalse(settings.same_value(self.specs["shutdown_battery_voltage"], 44.8, None))

    def test_all_11_sa_settings_present(self):
        """The 11 writable SA selects must all exist."""
        expected = {"output_source_priority", "charger_source_priority", "max_charge_current",
                    "max_grid_charge_current", "shutdown_battery_voltage",
                    "back_to_battery_voltage", "to_grid_battery_voltage",
                    "battery_absorption_charge_voltage", "battery_float_charge_voltage"}
        self.assertTrue(expected <= set(self.specs), expected - set(self.specs))


class TestEnergy(unittest.TestCase):
    def test_accumulate_and_reset(self):
        import json
        import tempfile
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "energy.json")
            with open(path, "w") as f:
                json.dump({"date": "2000-01-01", "pv_energy_today": 5.0}, f)
            counter = energy.EnergyCounter(path)
            state = {"pv_power": 3600, "load_power": 1000, "grid_power": 500,
                     "battery_power": -200}
            counter.accumulate(state, now=1000.0)          # first call only seeds ts
            counter.accumulate(state, now=1001.0)          # 1 s at 3600 W = 0.001 kWh
            self.assertAlmostEqual(state["pv_energy_today"], 0.001, places=4)
            self.assertAlmostEqual(state["load_energy_today"], 0.00028, places=4)
            with open(path) as f:
                saved = json.load(f)
            self.assertEqual(saved["date"].count("-"), 2)   # reset to today
            self.assertAlmostEqual(saved["pv_energy_today"], 0.001, places=4)


class TestDerived(unittest.TestCase):
    def test_power_balance(self):
        state = {"battery_voltage": 52.0, "battery_charge_current": 10,
                 "battery_discharge_current": 0, "load_power": 1000,
                 "pv_power_1": 2000}
        energy.derive_pv(state)
        energy.derive_power(state, deadband=50)
        self.assertEqual(state["pv_power"], 2000)
        self.assertEqual(state["battery_power"], 520)
        self.assertEqual(state["grid_power"], 0)          # 1000-2000+520 < 0
        state.update({"pv_power_1": 0, "battery_charge_current": 0,
                      "battery_discharge_current": 10})
        energy.derive_pv(state)
        energy.derive_power(state, deadband=50)
        self.assertEqual(state["battery_power"], -520)
        self.assertEqual(state["grid_power"], 480)        # 1000 W load - 520 W battery

    def test_pv_from_voltage_current(self):
        state = {"pv_voltage_1": 300.0, "pv_current_1": 5.0}
        energy.derive_pv(state)
        self.assertEqual(state["pv_power_1"], 1500)
        self.assertEqual(state["pv_power"], 1500)


if __name__ == "__main__":
    unittest.main(verbosity=2)
