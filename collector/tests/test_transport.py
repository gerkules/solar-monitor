"""Transport tests: framing over TCP against a fake inverter, plus HID report logic."""
import os
import socket
import sys
import threading
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import pi30, transports  # noqa: E402

QPIGS = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
         b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')


class FakeInverter(threading.Thread):
    """Minimal PI30 device: answers QPIGS with a real frame, ACK to POPxx, NAK to rest."""

    def __init__(self):
        super().__init__(daemon=True)
        self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        self.sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        self.sock.bind(("127.0.0.1", 0))
        self.sock.listen(1)
        self.port = self.sock.getsockname()[1]
        self.commands = []
        self.running = True

    def run(self):
        while self.running:
            try:
                conn, _ = self.sock.accept()
            except OSError:
                return
            with conn:
                buf = b""
                while self.running:
                    try:
                        chunk = conn.recv(256)
                    except OSError:
                        break
                    if not chunk:
                        break
                    buf += chunk
                    while b"\r" in buf:
                        raw, buf = buf.split(b"\r", 1)
                        cmd = raw[:-2].decode(errors="replace")
                        self.commands.append(cmd)
                        if cmd == "QPIGS":
                            conn.sendall(QPIGS)
                        elif cmd.startswith("POP"):
                            conn.sendall(b"(ACK\r")
                        elif cmd == "QPIRI":
                            conn.sendall(b"(NAK\r")     # bad read-back on purpose
                        else:
                            conn.sendall(b"(NAK\r")

    def stop(self):
        self.running = False
        try:
            self.sock.close()
        except OSError:
            pass


class TestTcpTransport(unittest.TestCase):
    def setUp(self):
        self.dev = FakeInverter()
        self.dev.start()
        from solar_monitor import config
        self._orig = (config.TCP_HOST, config.TCP_PORT)
        config.TCP_HOST, config.TCP_PORT = "127.0.0.1", self.dev.port

    def tearDown(self):
        from solar_monitor import config
        config.TCP_HOST, config.TCP_PORT = self._orig
        self.dev.stop()

    def test_request_validates_crc(self):
        t = transports.TcpTransport()
        try:
            r = t.request("QPIGS")
            self.assertEqual(r, QPIGS)
            self.assertEqual(self.dev.commands[0], "QPIGS")
        finally:
            t.close()

    def test_request_raw_gets_ack(self):
        t = transports.TcpTransport()
        try:
            self.assertTrue(t.request_raw("POP02").startswith(b"(ACK"))
            self.assertTrue(t.request_raw("PBFT99.9").startswith(b"(NAK"))
        finally:
            t.close()

    def test_reconnect_after_peer_close(self):
        t = transports.TcpTransport()
        try:
            self.assertIsNotNone(t.request("QPIGS"))
            t._close()                       # simulate a dead socket
            self.assertIsNotNone(t.request("QPIGS"))
        finally:
            t.close()

    def test_apply_setting_reports_not_applied(self):
        """ACK but QPIRI read-back does not confirm -> must NOT claim success."""
        from solar_monitor import settings
        t = transports.TcpTransport()
        try:
            result = settings.apply_setting(t, "output_source_priority", "Solar first",
                                            verified=True)
            self.assertFalse(result["ok"])
            self.assertIn("did not apply", result["message"])
        finally:
            t.close()

    def test_apply_setting_unverified(self):
        from solar_monitor import settings
        t = transports.TcpTransport()
        try:
            result = settings.apply_setting(t, "output_source_priority", "SBU",
                                            verified=False)
            self.assertTrue(result["ok"])
            self.assertEqual(result["message"], "Saved")
        finally:
            t.close()


class ForeignFrameTransport:
    """First reply is a frame from another poller on the shared UART, then ACK."""

    def __init__(self):
        self.calls = 0

    def request_raw(self, cmd, timeout=4.0, attempts=2):
        self.calls += 1
        if self.calls == 1:
            return b"(01.2 091.2 00114 \x0c\x11\r"      # QPIGS2 from another device
        return b"(ACK\r"

    def request(self, cmd, timeout=3.0, attempts=2):
        return None


class TestSetterOnSharedUart(unittest.TestCase):
    def test_foreign_frame_is_retried_not_treated_as_nak(self):
        from solar_monitor import settings
        with mock.patch.object(settings, "read_settings", lambda *a, **kw: None):
            result = settings.apply_setting(ForeignFrameTransport(),
                                            "battery_type", "LIb-protocol compatible",
                                            verified=True)
        # the write eventually got an ACK; verification is mocked away -> not a NAK error
        self.assertNotIn("rejected", result["message"])


class TestHidReportPacking(unittest.TestCase):
    def test_write_pads_to_8_bytes_with_report_id(self):
        from solar_monitor import config
        t = transports.HidTransport()
        sent = []
        with mock.patch.object(transports.HidTransport, "_open", lambda self: None), \
             mock.patch.object(transports.os, "write", lambda fd, data: sent.append(data)):
            t.fd = 3
            t._write(pi30.frame("QPIGS"))        # 8 bytes -> +1 report id = 9
            t._write(pi30.frame("QMOD"))         # 7 bytes -> 1+7 = 8
        self.assertEqual(len(sent[0]), 16)       # padded to whole reports
        self.assertEqual(sent[0][:6], b"\x00QPIGS")
        self.assertEqual(sent[1][0], config.HID_REPORT_ID)
        self.assertEqual(len(sent[1]), 8)


class TestTransportFactory(unittest.TestCase):
    def test_unknown_transport_raises(self):
        from solar_monitor import config
        orig, config.TRANSPORT = config.TRANSPORT, "carrier-pigeon"
        try:
            with self.assertRaises(transports.TransportError):
                transports.make_transport()
        finally:
            config.TRANSPORT = orig

    def test_factory_selects_classes(self):
        from solar_monitor import config
        orig = config.TRANSPORT
        try:
            for name, cls in (("hid", transports.HidTransport),
                              ("serial", transports.SerialTransport),
                              ("tcp", transports.TcpTransport)):
                config.TRANSPORT = name
                self.assertIsInstance(transports.make_transport(), cls)
        finally:
            config.TRANSPORT = orig


if __name__ == "__main__":
    unittest.main(verbosity=2)
