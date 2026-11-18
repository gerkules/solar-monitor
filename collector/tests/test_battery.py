"""Battery monitoring: driver parsers, factory, monitor merging, battery type."""
import os
import struct
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import battery, pi30, settings  # noqa: E402
from solar_monitor.battery import canbus, emulated, jbd, modbus, pylontech, vedirect  # noqa: E402


class TestJbd(unittest.TestCase):
    @staticmethod
    def make_frame(cells, temps, current_a, remaining, capacity, cycles=12):
        body = bytearray([0x03, 0x00, len(cells)])
        for mv in cells:
            body += struct.pack(">H", mv)
        for t in temps:
            body.append(int(t + 40))          # JBD "offset 40" encoding
        body += struct.pack(">h", int(current_a * 100))
        body += struct.pack(">H", int(remaining * 100))
        body += struct.pack(">H", int(capacity * 100))
        body += struct.pack(">H", cycles)
        payload = bytes([len(body)]) + bytes(body)
        crc = jbd.jbd_checksum(payload)
        return b"\xdd\x00" + payload + bytes([crc >> 8, crc & 0xFF]) + b"\x77"

    def test_parse_basic_info(self):
        frame = self.make_frame([3300, 3301, 3299, 3302], [25.0, 26.0], 32.5, 210.0, 280.0)
        d = jbd.parse_jbd(frame)
        self.assertIsNotNone(d)
        self.assertEqual(d["bms_current"], 32.5)
        self.assertAlmostEqual(d["bms_voltage"], 13.202, places=2)
        self.assertEqual(d["bms_remaining_ah"], 210.0)
        self.assertEqual(d["bms_capacity_ah"], 280.0)
        self.assertEqual(d["bms_cycles"], 12)
        self.assertAlmostEqual(d["bms_soc"], 75.0, places=1)
        self.assertEqual(d["bms_temperature"], 25.0)   # byte 65 -> 25 °C
        self.assertAlmostEqual(d["bms_cell_min"], 3.299, places=3)
        self.assertAlmostEqual(d["bms_cell_max"], 3.302, places=3)

    def test_temperature_encodings(self):
        frame = self.make_frame([3300, 3301], [25.0], 10.0, 100.0, 200.0)
        self.assertEqual(jbd.parse_jbd(frame)["bms_temperature"], 25.0)
        # 0.1 K variant: byte 2981 -> 25.0 °C (2 bytes)
        body = bytearray([0x03, 0x00, 0x01]) + struct.pack(">H", 3300)
        body += struct.pack(">H", 2981)
        body += struct.pack(">h", 1000) + struct.pack(">H", 10000) + struct.pack(">H", 20000) \
            + struct.pack(">H", 5)
        payload = bytes([len(body)]) + bytes(body)
        crc = jbd.jbd_checksum(payload)
        frame2 = b"\xdd\x00" + payload + bytes([crc >> 8, crc & 0xFF]) + b"\x77"
        d = jbd.parse_jbd(frame2, ntc_count=1, temp_mode="0.1k16")
        self.assertAlmostEqual(d["bms_temperature"], 25.0, places=1)

    def test_rejects_garbage(self):
        self.assertIsNone(jbd.parse_jbd(b"\x00\x01\x02"))
        self.assertIsNone(jbd.parse_jbd(b"\xdd\x00\x04\x99\x00\x00\x00\x77"))


class TestModbus(unittest.TestCase):
    def test_crc_known_vector(self):
        # classic reference frame: 01 03 00 00 00 0A -> CRC C5 CD
        self.assertEqual(modbus.crc16_modbus(bytes([0x01, 0x03, 0x00, 0x00, 0x00, 0x0A])),
                         bytes([0xC5, 0xCD]))

    def test_build_and_parse(self):
        req = modbus.build_request(1, 3, 0x0100, 3)
        self.assertEqual(req[:6], bytes([0x01, 0x03, 0x01, 0x00, 0x00, 0x03]))
        payload = struct.pack(">HHH", 5260, 150, 87)     # 52.60 V, 15.0 A, 87 %
        body = bytes([0x01, 0x03, 6]) + payload
        frame = body + modbus.crc16_modbus(body)
        regs = modbus.parse_response(frame, 1, 3)
        self.assertEqual(regs, [5260, 150, 87])

    def test_parse_rejects_bad_crc(self):
        body = bytes([0x01, 0x03, 2]) + struct.pack(">H", 5260)
        self.assertIsNone(modbus.parse_response(body + b"\x00\x00", 1, 3))


class TestPylontech(unittest.TestCase):
    def test_parse_console_text(self):
        text = ("Power 01 : Volt 52.13 Curr 12.3 SOC 87 SOH 100 Temp 27\n"
                "Total Capacity 280 Ah")
        d = pylontech.parse_console(text)
        self.assertEqual(d["bms_voltage"], 52.13)
        self.assertEqual(d["bms_current"], 12.3)
        self.assertEqual(d["bms_soc"], 87.0)
        self.assertEqual(d["bms_soh"], 100.0)
        self.assertEqual(d["bms_temperature"], 27.0)
        self.assertEqual(d["bms_capacity_ah"], 280.0)

    def test_empty(self):
        self.assertIsNone(pylontech.parse_console(""))


class TestVeDirect(unittest.TestCase):
    def test_parse_block(self):
        block = "\r\n".join([
            "V\t52130", "I\t-12300", "P\t-641", "CE\t-15200", "SOC\t870", "TTG\t1234",
            "Checksum\t\u0000",
        ])
        d = vedirect.parse_vedirect(block)
        self.assertEqual(d["bms_voltage"], 52.13)
        self.assertEqual(d["bms_current"], -12.3)
        self.assertEqual(d["bms_power"], -641.0)
        self.assertEqual(d["bms_soc"], 87.0)
        self.assertEqual(d["bms_remaining_ah"], 15.2)


class TestCan(unittest.TestCase):
    def test_soc_soh_frame(self):
        d = canbus.decode_frame(0x355, bytes([87, 0, 100, 0, 0, 0, 0, 0]))
        self.assertEqual(d, {"bms_soc": 87, "bms_soh": 100})

    def test_voltage_current_frame(self):
        data = (5270).to_bytes(2, "little") + (-123).to_bytes(2, "little", signed=True) \
            + (245).to_bytes(2, "little") + b"\x00\x00"
        d = canbus.decode_frame(0x356, data)
        self.assertEqual(d["bms_voltage"], 52.7)
        self.assertEqual(d["bms_current"], -12.3)
        self.assertEqual(d["bms_temperature"], 24.5)

    def test_unknown_frame(self):
        self.assertEqual(canbus.decode_frame(0x123, b"\x00" * 8), {})


class TestEmulated(unittest.TestCase):
    def test_coulomb_counting(self):
        drv = emulated.EmulatedDriver(capacity_ah=100, nominal_voltage=48, initial_soc=50)
        drv.last_ts = 0
        import time
        drv.update(power=4800, soc_hint=50)      # 4.8 kW for (now-0) -> clipped to 120 s
        self.assertLess(drv.soc, 60)
        self.assertGreater(drv.soc, 50)

    def test_zero_capacity_does_not_crash(self):
        drv = emulated.EmulatedDriver(capacity_ah=None, initial_soc=42)
        self.assertEqual(drv.update(power=1000)["bms_soc"], 42.0)


class TestMonitor(unittest.TestCase):
    def test_inverter_source_is_noop(self):
        m = battery.BatteryMonitor("inverter", {})
        self.assertFalse(m.enabled)
        self.assertIsNone(m.poll_once())
        self.assertEqual(m.describe(), "inverter")

    def test_bms_overrides_inverter_values(self):
        state = {"battery_voltage": 52.9, "battery_current": -4,
                 "battery_state_of_charge": 80, "battery_power": -211}
        m = battery.BatteryMonitor("emulated", state,
                                   {"capacity_ah": 280, "nominal_voltage": 48,
                                    "initial_soc": 88})
        m.poll_once()
        self.assertEqual(state["battery_state_of_charge"], 88.0)
        self.assertEqual(state["battery_source"], "emulated")
        self.assertEqual(state["bms_soc"], 88.0)
        self.assertTrue(m.snapshot()["enabled"])

    def test_unknown_source_raises(self):
        with self.assertRaises(ValueError):
            battery.BatteryMonitor("nonsense", {})

    def test_sources_list_matches_solarassistant_options(self):
        for name in ("inverter", "emulated", "jbd", "pylontech", "modbus",
                     "vedirect", "can"):
            self.assertIn(name, battery.SOURCES)


class TestCatalog(unittest.TestCase):
    def test_catalog_mirrors_solarassistant_groups(self):
        items = battery.catalog_mod.catalog()
        self.assertGreaterEqual(len(items), 60)
        groups = {i["group"] for i in items}
        for expected in ("USB Daly UART/RS485", "USB JBD UART/RS485", "USB JK RS485",
                         "USB Modbus RS232/RS485", "USB Narada RS485",
                         "USB Pylontech/Pytes console", "USB Serial RS232/RS485",
                         "USB Voltronic LIB RS485", "USB CAN bus", "USB Victron VE.Direct"):
            self.assertIn(expected, groups)

    def test_every_entry_has_driver_or_is_marked_unsupported(self):
        for item in battery.catalog_mod.catalog():
            if item["supported"]:
                self.assertIn(item["driver"], battery.SOURCES)
            else:
                self.assertIsNone(item["driver"])

    def test_find_by_id(self):
        item = battery.catalog_mod.find("victron-bmv-or-smartshunt")
        self.assertEqual(item["driver"], "vedirect")

    def test_unsupported_protocol_is_refused(self):
        with self.assertRaises(ValueError):
            battery.make_driver("jk-bms-rs485", {"port": "/dev/null"})


class TestRuntimeConfig(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.store = battery.BatteryStore(os.path.join(self.tmp.name, "battery.json"))
        self.state = {"battery_voltage": 52.9, "battery_state_of_charge": 80}
        self.mon = battery.BatteryMonitor("inverter", self.state, {}, store=self.store)

    def tearDown(self):
        self.tmp.cleanup()

    def test_default_is_inverter(self):
        self.assertFalse(self.mon.enabled)
        self.assertEqual(self.mon.config()["source"], "inverter")

    def test_switch_to_emulated_and_persist(self):
        snap = self.mon.apply_config({"source": "emulated", "capacity_ah": 100})
        self.assertTrue(snap["enabled"])
        self.assertEqual(snap["source"], "emulated")
        self.assertTrue(os.path.exists(self.store.path))
        again = battery.BatteryStore(self.store.path)
        self.assertEqual(again.data["source"], "emulated")
        self.assertEqual(again.data["capacity_ah"], 100)

    def test_switching_back_clears_bms_keys(self):
        self.mon.apply_config({"source": "emulated", "capacity_ah": 100})
        self.mon.poll_once()
        self.assertIn("bms_soc", self.state)
        self.mon.apply_config({"source": "inverter"})
        self.assertNotIn("bms_soc", self.state)
        self.assertNotIn("battery_source", self.state)

    def test_unsupported_selection_raises(self):
        with self.assertRaises(ValueError):
            self.mon.apply_config({"source": "jk"})

    def test_catalog_available_for_ui(self):
        info = self.mon.available()
        self.assertGreaterEqual(len(info["catalog"]), 60)
        self.assertIn("ports", info)


class TestDaly(unittest.TestCase):
    def test_request_frame(self):
        req = battery.daly.build_request(1)
        self.assertEqual(req[0], 0xA5)
        self.assertEqual(req[1], 0x40)
        self.assertEqual(req[3], 0x90)
        self.assertEqual(req[-1], sum(req[:-1]) & 0xFF)

    def test_parse_reply(self):
        data = bytes([0x12, 0x02, 0, 0, 0x2C, 0x75, 0, 0, 0, 0, 87]) + b"\x00" * 4
        frame = bytes([0xD3, 0x01, 0x01, len(data)]) + data
        frame += bytes([sum(frame) & 0xFF])
        d = battery.daly.parse_response(frame)
        self.assertAlmostEqual(d["bms_voltage"], 53.0, places=2)   # 530 * 0.1 V
        self.assertEqual(d["bms_soc"], 87)

    def test_rejects_bad_checksum(self):
        self.assertIsNone(battery.daly.parse_response(b"\xd3\x01\x01\x00\x00"))


class TestBmsEventLog(unittest.TestCase):
    def setUp(self):
        import tempfile
        self.tmp = tempfile.TemporaryDirectory()
        self.log = battery.BmsEventLog(os.path.join(self.tmp.name, "events.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def test_records_and_persists(self):
        self.log.record(69, 0, ts=1000)
        self.log.record(0, 69, ts=1240)
        again = battery.BmsEventLog(self.log.path)
        self.assertEqual([e["code"] for e in again.list()], [0, 69])
        self.assertEqual(again.list()[1]["previous"], 0)

    def test_duration_of_previous_state(self):
        self.log.record(69, 0, ts=1000)
        event = self.log.record(0, 69, ts=1180)
        self.assertEqual(event["previous_duration_s"], 180)

    def test_summary_ignores_normal_code(self):
        self.log.record(69, 0, ts=1000)
        self.log.record(0, 69, ts=1600)
        self.log.record(60, 0, ts=1900)
        summary = self.log.summary(hours=2, now=2500)
        codes = {c["code"]: c for c in summary["codes"]}
        self.assertNotIn(0, codes)
        self.assertEqual(codes[69]["count"], 1)
        self.assertEqual(codes[69]["minutes"], 10.0)
        self.assertEqual(codes[60]["minutes"], 10.0)

    def test_ring_buffer_keeps_last(self):
        log = battery.BmsEventLog(self.log.path, max_events=3)
        for i in range(6):
            log.record(69 if i % 2 else 0, ts=1000 + i)
        self.assertEqual(len(log.list()), 3)
        self.assertEqual(log.current()["code"], 69)


class TestBatteryTypeSetting(unittest.TestCase):
    def test_battery_type_lists_all_bms_protocols(self):
        """QPIRI field 13 is the inverter's BMS protocol table, not just chemistry."""
        specs = settings.effective_settings()
        spec = specs["battery_type"]
        self.assertEqual(len(spec["options"]), 10)
        self.assertEqual(spec["options"][0], "AGM")
        self.assertEqual(spec["options"][3], "Pylontech")
        self.assertEqual(spec["options"][8], "LIb-protocol compatible")
        self.assertEqual(spec["options"][9], "3rd party Lithium")

    def test_battery_type_commands_are_two_digits(self):
        spec = settings.effective_settings()["battery_type"]
        self.assertEqual(settings.build_command(spec, 2), "PBT02")
        self.assertEqual(settings.build_command(spec, 3), "PBT03")
        self.assertEqual(settings.build_command(spec, 8), "PBT08")
        self.assertEqual(settings.build_command(spec, 9), "PBT09")

    def test_qpiri_reports_current_protocol(self):
        frame = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
                 b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')
        self.assertEqual(pi30.parse_qpiri(frame)["battery_type"], "LIb-protocol compatible")

    def test_qbms_lithium_battery_data(self):
        """QBMS = what the inverter reads from the battery over CAN/RS485."""
        frame = b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r'
        d = pi30.parse_qbms(frame)
        self.assertEqual(d["inverter_bms_connected"], 1)
        self.assertEqual(d["inverter_bms_status"], "Connected")
        self.assertEqual(d["inverter_bms_soc"], 80)
        self.assertEqual(d["inverter_bms_bulk_voltage"], 57.6)
        self.assertEqual(d["inverter_bms_float_voltage"], 57.6)
        self.assertEqual(d["inverter_bms_cutoff_voltage"], 44.8)
        self.assertEqual(d["inverter_bms_max_charge_current"], 150.0)
        self.assertEqual(d["inverter_bms_max_discharge_current"], 220.0)

    def test_qbms_charge_blocked_is_warning_69_cause(self):
        """stop_charge=1 is exactly what makes the inverter show warning 69/60."""
        frame = b'(0 100 0 0 1 532 532 450 0000 0030\x0e\x5e\r'
        d = pi30.parse_qbms(frame)
        self.assertEqual(d["bms_charge_blocked"], 1)
        self.assertEqual(d["bms_discharge_blocked"], 0)
        self.assertEqual(d["inverter_bms_stop_charge"], 1)
        ok = pi30.parse_qbms(b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r')
        self.assertEqual(ok["bms_charge_blocked"], 0)

    def test_qbms_disconnected_and_garbage(self):
        d = pi30.parse_qbms(b'(1 000 0 0 1 500 500 440 0000 0030\x00\x00\r')
        self.assertEqual(d["inverter_bms_connected"], 0)
        self.assertEqual(d["inverter_bms_status"], "Disconnected")
        self.assertEqual(pi30.parse_qbms(b"(NAKss\r"), {})
        self.assertEqual(pi30.parse_qbms(b"(\x00\x00\r"), {})


if __name__ == "__main__":
    unittest.main(verbosity=2)


class TestConnection(unittest.TestCase):
    """Переключение транспорта: TCP (виртуальный RS232) / USB-RS232 / HID / MQTT."""

    def setUp(self):
        import tempfile
        from solar_monitor import config, connection
        self.connection = connection
        self.tmp = tempfile.TemporaryDirectory()
        self.path = os.path.join(self.tmp.name, "connection.json")
        self.store = connection.ConnectionStore(self.path)
        self._save = (config.TRANSPORT, config.TCP_HOST, config.TCP_PORT,
                      config.SERIAL_PORT, config.SERIAL_BAUD, config.HID_DEVICE)

    def tearDown(self):
        from solar_monitor import config
        (config.TRANSPORT, config.TCP_HOST, config.TCP_PORT,
         config.SERIAL_PORT, config.SERIAL_BAUD, config.HID_DEVICE) = self._save
        self.tmp.cleanup()

    def test_defaults_from_env(self):
        self.assertIn(self.store.data["mode"], self.connection.MODES)
        self.assertIn("tcp_host", self.store.data)

    def test_save_and_reload(self):
        self.store.save({"mode": "serial", "serial_port": "/dev/ttyUSB1",
                         "serial_baud": 9600, "tcp_host": "10.0.0.5"})
        again = self.connection.ConnectionStore(self.path)
        self.assertEqual(again.data["mode"], "serial")
        self.assertEqual(again.data["serial_port"], "/dev/ttyUSB1")
        self.assertEqual(again.data["serial_baud"], 9600)
        self.assertEqual(again.data["tcp_host"], "10.0.0.5")

    def test_apply_to_env_switches_config(self):
        from solar_monitor import config
        self.store.save({"mode": "serial", "serial_port": "/dev/ttyACM0", "serial_baud": 19200})
        self.store.apply_to_env()
        self.assertEqual(config.TRANSPORT, "serial")
        self.assertEqual(config.SERIAL_PORT, "/dev/ttyACM0")
        self.assertEqual(config.SERIAL_BAUD, 19200)

    def test_describe(self):
        self.assertEqual(self.connection.describe({"mode": "tcp", "tcp_host": "1.2.3.4",
                                                   "tcp_port": 9999}), "tcp 1.2.3.4:9999")
        self.assertEqual(self.connection.describe({"mode": "serial", "serial_port": "/dev/ttyUSB0",
                                                   "serial_baud": 2400}), "serial /dev/ttyUSB0@2400")
        self.assertEqual(self.connection.describe({"mode": "hid", "hid_device": "/dev/hidraw0"}),
                         "usb-hid /dev/hidraw0")

    def test_probe_reports_unreachable_target(self):
        res = self.connection.probe({"mode": "tcp", "tcp_host": "127.0.0.1", "tcp_port": 1})
        self.assertFalse(res["ok"])
        self.assertIn("error", res)

    def test_probe_success_with_fake_transport(self):
        from unittest import mock
        from solar_monitor import pi30
        frame = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
                 b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')
        qid = b'(96342404105016\xa1*\r'
        qiri = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
                b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')

        class Fake:
            def describe(self):
                return "fake"

            def request(self, cmd, timeout=3.0, attempts=2):
                return {"QPIGS": frame, "QID": qid, "QPIRI": qiri}.get(cmd)

            def close(self):
                pass

        with mock.patch.object(self.connection, "build", lambda cfg, broker=None: Fake()):
            res = self.connection.probe({"mode": "serial", "serial_port": "/dev/null"})
        self.assertTrue(res["ok"], res)
        self.assertEqual(res["battery_voltage"], 52.9)
        self.assertEqual(res["serial_number"], "96342404105016")
        self.assertEqual(res["rated_power"], 11000)
        self.assertIn("latency_ms", res)


class TestPollerConnectionSwitch(unittest.TestCase):
    def test_apply_connection_swaps_transport(self):
        import tempfile
        from unittest import mock
        from test_poller import FakeTransport, FakeMqtt, FakeInflux, QPIGS
        from solar_monitor import connection, poller as poller_mod

        old = FakeTransport({"QPIGS": QPIGS})

        class New:
            def describe(self):
                return "new-transport"

            def request(self, cmd, timeout=3.0, attempts=2):
                return QPIGS

            def request_raw(self, cmd, timeout=4.0, attempts=2):
                return QPIGS

            def close(self):
                self.closed = True

        new = New()
        p = poller_mod.Poller(old, FakeMqtt(), FakeInflux())
        p.bms_events.path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        p.fails = 5
        with mock.patch.object(connection, "build", lambda cfg, broker=None: new):
            res = p.apply_connection({"mode": "serial", "serial_port": "/dev/ttyUSB0"})
        self.assertTrue(res["ok"])
        self.assertEqual(p.transport.describe(), "new-transport")
        self.assertEqual(p.fails, 0)          # счётчик ошибок сброшен
        self.assertTrue(getattr(new, "closed", False) is False)
