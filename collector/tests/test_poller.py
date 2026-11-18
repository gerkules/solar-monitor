"""Poller tests: bad frames must degrade gracefully, settings must be queued.

Everything runs against a scripted fake transport — no inverter, no broker.
"""
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, pi30, poller as poller_mod  # noqa: E402

QPIGS = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
         b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')
QPIRI = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
         b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')
QMOD = b'(B\xe7\xc9\r'
QID = b'(TEST000000000001\x10#\r'
QPIGS2 = b'(00.0 000.0 00000 E\x93\r'
QPIRS = ("(" + "0" * 40).encode() + b"\x00\x00\r"
QBMS = b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r'


class FakeTransport:
    """Answers per command; `None` simulates a timeout/mixed frame."""

    def __init__(self, answers=None):
        self.answers = answers or {}
        self.sent = []
        self.rx_count = self.tx_count = 0
        self.closed = 0

    def describe(self):
        return "fake"

    def request(self, cmd, timeout=3.0, attempts=2):
        self.sent.append(cmd)
        self.tx_count += 1
        reply = self.answers.get(cmd)
        if reply:
            self.rx_count += 1
        return reply

    def request_raw(self, cmd, timeout=4.0, attempts=2):
        return self.request(cmd, timeout, attempts)

    def close(self):
        self.closed += 1


class FakeBatteryTypeTransport(FakeTransport):
    """Behaves like the real inverter: PBTxx changes the QPIRI battery-type field."""

    CODES = {0: "AGM", 1: "Flooded", 2: "User", 3: "Pylontech", 4: "Shinheung",
             5: "WECO", 6: "Soltaro", 7: "TBD", 8: "LIb-protocol compatible",
             9: "3rd party Lithium"}

    def __init__(self, code=8, connected=True):
        super().__init__({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QMOD": QMOD,
                          "QID": QID, "QPIWS": QPIRS})
        self.code = code
        self.connected = connected      # QBMS 0 = Connected, 1 = Disconnected
        self.answers["QBMS"] = self._qbms()
        self.answers["QPIRI"] = self._qpiri()

    def _qbms(self):
        flag = 0 if self.connected else 1
        return (f"({flag} 080 0 0 0 576 576 448 0150 0220"
                ).encode() + b"\xea\xe9\r"

    def _qpiri(self):
        fields = ("(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 "
                  f"{self.code} 002 150 1 2 3 9 01 0 0 52.0 0 1 480 0 150").encode()
        from solar_monitor.pi30 import crc_xmodem
        crc = crc_xmodem(fields)
        return fields + bytes([crc >> 8, crc & 0xFF]) + b"\r"

    def request(self, cmd, timeout=3.0, attempts=2):
        if cmd.startswith("PBT") and len(cmd) == 5:
            code = int(cmd[3:])
            prev_code = self.code
            self.code = code
            # "Pylontech" keeps the battery link; anything else loses it
            self.connected = code == 3
            self.answers["QPIRI"] = self._qpiri()
            self.answers["QBMS"] = self._qbms()
            self.sent.append(cmd)
            return b"(ACK\r"
        if cmd == "QPIRI":
            self.answers["QPIRI"] = self._qpiri()
        if cmd == "QBMS":
            if getattr(self, "qbms_override", None) is not None:
                self.answers["QBMS"] = self.qbms_override
            else:
                self.answers["QBMS"] = self._qbms()
        return super().request(cmd, timeout, attempts)


class FakeMqtt:
    connected_restarts = 0

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


class FakeInflux:
    written = errors = 0

    def write(self, state, ts=None):
        FakeInflux.written += 1


def make_poller(answers):
    config.POLL_INTERVAL = 0.2
    p = poller_mod.Poller(FakeTransport(answers), FakeMqtt(), FakeInflux())
    tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
    tmp.close()
    p.energy.path = tmp.name
    return p


class TestPollerCycle(unittest.TestCase):
    def setUp(self):
        self._rollback = config.BATTERY_TYPE_ROLLBACK
        config.BATTERY_TYPE_ROLLBACK = True      # auto-revert is opt-in now
        self._intervals = (config.QMOD_INTERVAL, config.QPIRI_INTERVAL,
                           config.QPIWS_INTERVAL, config.HAS_MPPT2,
                           config.QBMS_INTERVAL)
        config.QMOD_INTERVAL = config.QPIRI_INTERVAL = 0
        config.QPIWS_INTERVAL = 0.001      # 0 would disable QPIWS polling completely
        config.QBMS_INTERVAL = 0.001
        config.HAS_MPPT2 = True

    def tearDown(self):
        config.BATTERY_TYPE_ROLLBACK = self._rollback
        (config.QMOD_INTERVAL, config.QPIRI_INTERVAL,
         config.QPIWS_INTERVAL, config.HAS_MPPT2, config.QBMS_INTERVAL) = self._intervals

    def test_happy_path_sets_state(self):
        p = make_poller({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI,
                         "QMOD": QMOD, "QID": QID, "QPIWS": QPIRS})
        p.cycle()
        self.assertTrue(p.online)
        self.assertEqual(p.state["battery_state_of_charge"], 81)
        self.assertEqual(p.state["pv_power"], 0)
        self.assertEqual(p.state["output_source_priority"], "SBU")
        self.assertEqual(p.state["warnings"], "none")
        self.assertIn("last_update", p.state)
        self.assertEqual(p.health()["consecutive_failures"], 0)

    def test_invalid_qpiws_does_not_crash(self):
        """Regression: a frame glued from two replies killed the poll thread."""
        glued = b'(00.0 066000000000000(00.0 060.1 00000 \xf3\xb4\r'
        p = make_poller({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI,
                         "QMOD": QMOD, "QID": QID, "QPIWS": glued})
        p.cycle()                              # must not raise
        p.cycle()
        self.assertNotIn("warnings", p.state)  # no phantom fault
        self.assertTrue(p.online)

    def test_second_mppt_is_detected_only_when_it_reports(self):
        p = make_poller({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI})
        p.cycle()
        self.assertNotIn("has_mppt2", p.state)      # zeros -> single MPPT

        dual = b'(5.0 300.0 1500 \x00\x00\r'
        p2 = make_poller({"QPIGS": QPIGS, "QPIGS2": dual, "QPIRI": QPIRI})
        p2.cycle()
        self.assertEqual(p2.state["has_mppt2"], 1)
        self.assertEqual(p2.state["pv_power_2"], 1500)

    def test_qbms_bms_link(self):
        p = make_poller({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI,
                         "QMOD": QMOD, "QID": QID, "QPIWS": QPIRS, "QBMS": QBMS})
        p.cycle()
        self.assertEqual(p.state["inverter_bms_connected"], 1)
        self.assertEqual(p.state["inverter_bms_soc"], 80)
        self.assertEqual(p.state["inverter_bms_bulk_voltage"], 57.6)
        self.assertEqual(p.state["inverter_bms_max_charge_current"], 150.0)
        self.assertEqual(p.state["bms_link"], "Connected")
        self.assertTrue(p.qbms_supported)

    def test_protocol_change_confirmed_when_bms_stays_connected(self):
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        config.POLL_INTERVAL = 0.2
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        self.assertEqual(p.state["battery_type"], "LIb-protocol compatible")
        self.assertEqual(p.state["inverter_bms_connected"], 1)

        result = {}

        def do_set():
            result.update(p.submit_set("battery_type", "Pylontech", verified=True))

        worker = threading.Thread(target=do_set)
        worker.start()
        for _ in range(40):
            p.cycle()
            if "ok" in result:
                break
        worker.join(5)

        self.assertTrue(result["ok"], result)
        self.assertEqual(transport.code, 3)                     # PBT03 written
        self.assertEqual(p.protocol_status()["previous"], "LIb-protocol compatible")
        p.cycle()                                               # QBMS -> Connected
        self.assertEqual(p.protocol_status()["state"], "confirmed")

    def test_protocol_change_rolls_back_when_bms_disappears(self):
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        config.POLL_INTERVAL = 0.2
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        p.protocol_change = {
            "previous": "LIb-protocol compatible", "current": "Pylontech",
            "started": int(time.time()) - 200, "deadline": int(time.time()) - 1,
            "timeout": 90, "state": "checking",
        }
        transport.connected = False          # the new protocol lost the battery
        p.cycle()
        # protocol restored right away, but the link is still down -> recovering
        self.assertEqual(p.protocol_status()["state"], "recovering")
        self.assertEqual(transport.code, 8)  # previous protocol written back
        transport.connected = True           # the inverter found the battery again
        p.cycle()
        self.assertEqual(p.protocol_status()["state"], "rolled_back")
        self.assertEqual(p.state["battery_type"], "LIb-protocol compatible")

    def test_protocol_cancel_rolls_back_immediately(self):
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        config.POLL_INTERVAL = 0.2
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        p.protocol_change = {
            "previous": "LIb-protocol compatible", "current": "Pylontech",
            "started": int(time.time()), "deadline": int(time.time()) + 90,
            "timeout": 90, "state": "checking",
        }
        res = p.cancel_protocol()
        self.assertTrue(res.get("ok"), res)
        self.assertEqual(transport.code, 8)

    def test_recovery_rewrites_protocol_and_gives_up(self):
        """A real inverter needed the protocol rewritten before the BMS answered."""
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        config.POLL_INTERVAL = 0.2
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        now = time.time()
        p.protocol_change = {
            "previous": "LIb-protocol compatible", "current": "Pylontech",
            "started": int(now) - 200, "deadline": int(now) - 1,
            "timeout": 90, "state": "checking",
        }
        transport.connected = False
        p.cycle()                                    # -> recovering, attempt 1
        self.assertEqual(p.protocol_status()["state"], "recovering")
        p.protocol_change["next_check"] = time.time() - 1
        transport.sent.clear()
        p.cycle()                                    # attempt 2: rewrites protocol
        self.assertIn("PBT08", transport.sent)
        self.assertEqual(p.protocol_status()["attempts"], 2)
        for _ in range(4):                           # exhaust the attempts
            p.protocol_change["next_check"] = time.time() - 1
            p.cycle()
        self.assertEqual(p.protocol_status()["state"], "failed")

    def test_confirm_without_change(self):
        p = poller_mod.Poller(FakeTransport({"QPIGS": QPIGS}), FakeMqtt(), FakeInflux())
        self.assertFalse(p.confirm_protocol()["ok"])

    def test_warning_69_when_bms_blocks_charge(self):
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        transport.qbms_override = b'(0 100 0 0 1 532 532 450 0000 0030\x0e\x5e\r'
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        self.assertEqual(p.state["bms_warning_69"], 1)
        self.assertEqual(p.state["bms_code"], 69)
        self.assertEqual(p.state["bms_charge_blocked"], 1)
        self.assertTrue(p.protocol_status()["warning_69"])
        # BMS allows charging again -> warning clears
        transport.qbms_override = b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r'
        p.last_qbms = 0
        p.cycle()
        self.assertEqual(p.state["bms_warning_69"], 0)

    def test_bms_codes_from_manual(self):
        """Axpert MAX code reference: 60/69/70/71 come straight from QBMS flags."""
        cases = {
            b'(0 100 0 1 1 532 532 450 0000 0030\x0e\x5e\r': 60,   # stop chg + dis
            b'(0 100 0 0 1 532 532 450 0000 0030\x0e\x5e\r': 69,   # stop charge
            b'(0 100 1 0 0 532 532 450 0000 0030\x0e\x5e\r': 70,   # force charge
            b'(0 100 0 1 0 532 532 450 0000 0030\x0e\x5e\r': 71,   # stop discharge
            b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r': 0,    # all good
        }
        for frame, expected in cases.items():
            from solar_monitor import pi30
            self.assertEqual(pi30.parse_qbms(frame)["bms_code"], expected, frame)

    def test_bms_events_are_logged(self):
        """Code 69 -> 0 and a link loss (62) must land in the journal."""
        import tempfile
        transport = FakeBatteryTypeTransport(code=8, connected=True)
        transport.qbms_override = b'(0 100 0 0 1 532 532 450 0000 0030\x0e\x5e\r'
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.bms_events.path = tempfile.NamedTemporaryFile(suffix=".json", delete=False).name
        p.cycle()
        self.assertEqual(p.bms_events.current()["code"], 69)

        transport.qbms_override = b'(0 080 0 0 0 576 576 448 0150 0220\xea\xe9\r'
        p.last_qbms = 0
        p.cycle()
        self.assertEqual(p.bms_events.current()["code"], 0)
        self.assertEqual(p.bms_events.current()["previous"], 69)

        transport.connected = False            # link lost -> code 62
        transport.qbms_override = None
        p.last_qbms = 0
        p.cycle()
        self.assertEqual(p.bms_events.current()["code"], 62)
        transport.connected = True             # restored -> back to 0
        p.last_qbms = 0
        p.cycle()
        self.assertEqual(p.bms_events.current()["code"], 0)
        self.assertIn("восстановлена", p.bms_events.current().get("note", ""))

    def test_bms_alarm_after_link_lost(self):
        """R61/R69: the inverter needs a correct protocol, so we alarm instead."""
        config.BMS_LINK_ALERT_AFTER = 30
        transport = FakeBatteryTypeTransport(code=8, connected=False)
        p = poller_mod.Poller(transport, FakeMqtt(), FakeInflux())
        p.cycle()
        self.assertGreaterEqual(p.protocol_status()["bms_down_s"], 0)   # just lost
        p.bms_down_since -= 100                                   # pretend it is old
        p.last_qbms = 0
        p.cycle()
        self.assertTrue(p.bms_alarm_sent)
        self.assertGreater(p.protocol_status()["bms_down_s"], 90)

    def test_qbms_nak_disables_polling(self):
        p = make_poller({"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI,
                         "QBMS": b"(NAKss\r"})
        p.cycle()
        self.assertFalse(p.qbms_supported)
        self.assertNotIn("inverter_bms_soc", p.state)

    def test_missing_qpigs_counts_as_failure(self):
        p = make_poller({"QPIGS": None})
        p.cycle()
        self.assertEqual(p.fails, 1)
        self.assertFalse(p.online)
        self.assertFalse(p.health()["ok"])

    def test_garbage_qpigs_is_ignored(self):
        p = make_poller({"QPIGS": b"(\xff\xfe\r"})
        p.cycle()
        self.assertEqual(p.fails, 1)
        self.assertNotIn("battery_voltage", p.state)

    def test_writes_are_queued_and_answered(self):
        p = make_poller({"QPIGS": QPIGS, "QPIRI": QPIRI, "POP02": b"(ACK\r"})
        result = {}
        import threading

        def do_set():
            result.update(p.submit_set("output_source_priority", "SBU", verified=True))

        t = threading.Thread(target=do_set)
        t.start()
        p.cycle()          # executes the queued job
        t.join(5)
        self.assertIn("ok", result)
        self.assertTrue(result["ok"], result)
        self.assertEqual(result["message"], "Saved")
        # the response must be published for MQTT consumers
        topics = [t for t, _, _ in p.mq.sent]
        self.assertIn("solar/office/set/response_message/state", topics)


if __name__ == "__main__":
    unittest.main(verbosity=2)
