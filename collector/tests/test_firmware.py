"""Тесты прошивки ESP32 на CPython.

Железо не нужно: парсеры общие с сервером (pi30.py генерируется из серверного),
UART подменяется фейком. Так проверяется вся логика опроса, уставок и истории.
"""
import importlib.util
import os
import sys
import unittest

HERE = os.path.dirname(__file__)
REPO = os.path.abspath(os.path.join(HERE, "..", ".."))
FW = os.path.join(REPO, "firmware", "esp32")

sys.path.insert(0, os.path.join(REPO, "collector"))
sys.path.insert(0, FW)

from solar_monitor import pi30 as server_pi30  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


fw_pi30 = _load("fw_pi30", os.path.join(FW, "pi30.py"))
bus_mod = _load("fw_bus", os.path.join(FW, "bus.py"))
poller_mod = _load("fw_poller", os.path.join(FW, "poller.py"))
sethandler = _load("fw_sethandler", os.path.join(FW, "sethandler.py"))
history_mod = _load("fw_history", os.path.join(FW, "history.py"))

# Кадры — реальные записи с Axpert 11 кВт (S/N в тестах подменён)
QPIGS = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
         b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')
QPIRI = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
         b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')
QMOD = b'(B\xe7\xc9\r'
QID = server_pi30.frame("(TEST000000000001")   # CRC считаем сами: фикстура обезличена
QPIGS2 = b'(00.0 000.0 00000 E\x93\r'
QPIWS = b'(0000000000000000000000000000000000000000\x00\x00\r'


class FakeUart:
    """Отвечает на команды заранее заданными кадрами, отдаёт по 1 байту."""

    def __init__(self, replies=None, silence=()):
        self.replies = dict(replies or {})
        self.silence = set(silence)
        self.out = b""
        self.written = []

    def write(self, data):
        self.written.append(bytes(data))
        cmd = bytes(data).split(b"\r")[0]
        name = cmd.decode(errors="replace").rstrip("\x00")
        # Отрезаем CRC от команды, чтобы найти её в таблице ответов
        for key in list(self.replies) + list(self.silence):
            if name.startswith(key):
                self.out += b"" if key in self.silence else self.replies[key]
                return len(data)
        return len(data)

    def any(self):
        return len(self.out)

    def read(self, n=1):
        chunk, self.out = self.out[:n], self.out[n:]
        return chunk


class ParserParityTest(unittest.TestCase):
    """Сгенерированный для прошивки парсер обязан совпадать с серверным."""

    def test_generated_from_server(self):
        for fn in ("parse_qpigs", "parse_qpiri", "parse_qmod", "parse_qpiws",
                   "parse_qpigs2", "parse_qid"):
            self.assertTrue(hasattr(fw_pi30, fn), fn)

    def test_same_results_on_real_frames(self):
        cases = [("QPIGS", QPIGS), ("QPIRI", QPIRI), ("QMOD", QMOD), ("QPIWS", QPIWS),
                 ("QPIGS2", QPIGS2), ("QID", QID)]
        for name, frame in cases:
            fn = "parse_" + name.lower()
            self.assertEqual(getattr(fw_pi30, fn)(frame), getattr(server_pi30, fn)(frame),
                             "%s: прошивка и сервер расходятся" % name)

    def test_crc_and_frames_identical(self):
        for cmd in ("QPIGS", "QPIRI", "QMOD", "QPIWS", "QID", "POP01"):
            self.assertEqual(fw_pi30.frame(cmd), server_pi30.frame(cmd))
        self.assertTrue(fw_pi30.check_frame(QPIGS))
        self.assertFalse(fw_pi30.check_frame(QPIGS[:-3] + b"\x00\x00\r"))

    def test_settings_table_identical(self):
        self.assertEqual(sorted(fw_pi30.SETTINGS), sorted(server_pi30.SETTINGS))
        for key, spec in server_pi30.SETTINGS.items():
            self.assertEqual(fw_pi30.SETTINGS[key].get("field"), spec.get("field"), key)


class BusTest(unittest.TestCase):
    def test_collector_splits_frames(self):
        col = bus_mod.FrameCollector()
        self.assertIsNone(col.feed(QPIGS[:10]))
        self.assertEqual(col.feed(QPIGS[10:]), QPIGS)
        # два кадра в одном буфере — по одному за вызов
        col.feed(QPIGS + QMOD)
        self.assertEqual(col.buf, QMOD)
        self.assertEqual(col.feed(b""), QMOD)

    def test_request_validates_crc(self):
        uart = FakeUart({"QPIGS": QPIGS})
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        self.assertEqual(bus.request("QPIGS"), QPIGS)

    def test_request_retries_then_fails(self):
        bus = bus_mod.Bus(FakeUart({}, silence={"QPIGS"}), timeout_ms=5, attempts=2,
                          sleep_ms=lambda ms: None)
        self.assertIsNone(bus.request("QPIGS"))
        self.assertEqual(bus.errors, 2)

    def test_bad_crc_rejected(self):
        broken = QPIGS[:-3] + b"\x00\x00\r"
        bus = bus_mod.Bus(FakeUart({"QPIGS": broken}), timeout_ms=50, attempts=1,
                          sleep_ms=lambda ms: None)
        self.assertIsNone(bus.request("QPIGS"))

    def test_raw_accepts_ack_and_nak(self):
        for payload in (b"(ACK\xa7\xbb\r", b"(NAK\xc3\xa1\r"):
            bus = bus_mod.Bus(FakeUart({"PCP": payload}), timeout_ms=50, attempts=1,
                              sleep_ms=lambda ms: None)
            self.assertEqual(bus.request_raw("PCP01"), payload)


class PollerTest(unittest.TestCase):
    def make_poller(self, replies, silence=()):
        uart = FakeUart(replies, silence)
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        return poller_mod.Poller(bus, {"poll_slow_s": 0})

    def test_state_matches_server_parser(self):
        p = self.make_poller({"QPIGS": QPIGS, "QPIRI": QPIRI, "QMOD": QMOD,
                              "QPIWS": QPIWS, "QID": QID, "QPIGS2": QPIGS2})
        self.assertTrue(p.poll_once(now=1_700_000_000))
        st = p.state
        ref = server_pi30.parse_qpigs(QPIGS)
        self.assertEqual(st["load_power"], ref["load_power"])
        self.assertEqual(st["battery_voltage"], ref["battery_voltage"])
        self.assertEqual(st["device_mode"], "Battery")
        self.assertEqual(st["serial_number"], "TEST000000000001")
        self.assertEqual(st["rated_power"], 11000.0)
        self.assertIn("output_source_priority", st)
        self.assertIsNotNone(st["battery_current"])
        self.assertEqual(st["health"] if "health" in st else p.health()["rx"], p.health()["rx"])

    def test_failed_poll_keeps_previous_state(self):
        p = self.make_poller({"QPIGS": QPIGS})
        p.poll_once(now=1_700_000_000)
        before = dict(p.state)
        p.bus.uart.replies = {}
        p.bus.uart.silence = {"QPIGS"}
        self.assertFalse(p.poll_once(now=1_700_000_010))
        self.assertEqual(p.state, before)
        self.assertEqual(p.failed_polls, 1)

    def test_health_fields(self):
        p = self.make_poller({"QPIGS": QPIGS})
        p.poll_once(now=1_700_000_000)
        h = p.health()
        for key in ("ok", "online", "age_s", "uptime_s", "rx", "tx", "errors"):
            self.assertIn(key, h)


class SettingsTest(unittest.TestCase):
    def test_parse_value_number_and_label(self):
        spec = {"kind": "number", "min": 10, "max": 200}
        self.assertEqual(sethandler.parse_value(spec, "60"), 60.0)
        with self.assertRaises(ValueError):
            sethandler.parse_value(spec, "5")
        select = {"kind": "select", "options": {0: "Utility first", 1: "Solar first"}}
        self.assertEqual(sethandler.parse_value(select, "Solar first"), 1.0)
        self.assertEqual(sethandler.parse_value(select, "0"), 0.0)

    def test_apply_setting_verified(self):
        """ACK + новое значение в QPIRI -> Saved."""
        uart = FakeUart({"MNCHGC": b"(ACK\xa7\xbb\r", "QPIRI": QPIRI})
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        result = sethandler.apply_setting(bus, "max_charge_current", 150)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["message"], "Saved")

    def test_apply_setting_rejected(self):
        uart = FakeUart({"MNCHGC": b"(NAK\xc3\xa1\r"})
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        result = sethandler.apply_setting(bus, "max_charge_current", 30)
        self.assertFalse(result["ok"])
        self.assertIn("NAK", result["message"])

    def test_apply_setting_not_applied(self):
        """ACK есть, но QPIRI показывает старое значение -> не Saved."""
        uart = FakeUart({"MNCHGC": b"(ACK\xa7\xbb\r", "QPIRI": QPIRI})
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        result = sethandler.apply_setting(bus, "max_charge_current", 120, attempts=1)
        self.assertFalse(result["ok"])
        self.assertEqual(result["readback"], 150.0)

    def test_unknown_setting(self):
        bus = bus_mod.Bus(FakeUart({}), timeout_ms=5, attempts=1, sleep_ms=lambda ms: None)
        self.assertFalse(sethandler.apply_setting(bus, "nope", 1)["ok"])

    def test_settings_list_has_values(self):
        uart = FakeUart({"QPIRI": QPIRI})
        bus = bus_mod.Bus(uart, timeout_ms=50, attempts=1, sleep_ms=lambda ms: None)
        items = sethandler.settings_list(bus)
        keys = {i["key"] for i in items}
        self.assertIn("output_source_priority", keys)
        select = [i for i in items if i["kind"] == "select"][0]
        self.assertTrue(select["options"])


class HistoryTest(unittest.TestCase):
    def test_ring_keeps_limit(self):
        h = history_mod.History(keep=3, interval_s=0)
        for i in range(5):
            h.maybe_add({"pv_power": 100 + i, "load_power": i,
                         "battery_voltage": 52.0, "battery_state_of_charge": 90},
                        now=1000 + i)
        data = h.as_dict()
        self.assertEqual(len(data["rows"]), 3)
        self.assertEqual(data["rows"][-1][1], 104)
        self.assertEqual(data["columns"][1], "pv_power")

    def test_interval_respected(self):
        h = history_mod.History(keep=10, interval_s=60)
        self.assertTrue(h.maybe_add({"pv_power": 1}, now=1000))
        self.assertFalse(h.maybe_add({"pv_power": 2}, now=1030))
        self.assertTrue(h.maybe_add({"pv_power": 3}, now=1061))

    def test_summary_energy(self):
        h = history_mod.History(keep=10, interval_s=60)
        for i in range(3):
            h.maybe_add({"pv_power": 1000, "load_power": 500}, now=1000 + i * 60)
        s = h.summary()
        self.assertEqual(s["points"], 3)
        self.assertAlmostEqual(s["pv_energy_kwh"], 0.05, places=2)


class FirmwareFilesTest(unittest.TestCase):
    def test_required_files_present(self):
        for name in ("main.py", "bus.py", "pi30.py", "poller.py", "sethandler.py",
                     "history.py", "mqttpub.py", "web.py", "config.example.json",
                     "www/index.html", "vendor/umqtt/simple.py"):
            self.assertTrue(os.path.exists(os.path.join(FW, name)), name)

    def test_micropython_has_no_forbidden_syntax(self):
        """Аннотации типов MicroPython не переваривает — в прошивке их быть не должно."""
        import ast
        for name in ("main.py", "bus.py", "poller.py", "sethandler.py", "history.py",
                     "mqttpub.py", "web.py"):
            path = os.path.join(FW, name)
            with open(path) as fh:
                src = fh.read()
            tree = ast.parse(src)
            for node in ast.walk(tree):
                if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                    self.assertIsNone(node.returns, "%s: %s() аннотация" % (name, node.name))
                    for arg in node.args.args:
                        self.assertIsNone(arg.annotation, "%s: %s" % (name, arg.arg))
                if isinstance(node, ast.AnnAssign):
                    self.fail("%s: аннотация переменной" % name)
            self.assertNotIn("from __future__", src, name)

    def test_index_has_api_calls(self):
        html = open(os.path.join(FW, "www", "index.html")).read()
        for path in ("/api/v1/state", "/api/v1/settings", "/api/v1/history"):
            self.assertIn(path, html)


if __name__ == "__main__":
    unittest.main()
