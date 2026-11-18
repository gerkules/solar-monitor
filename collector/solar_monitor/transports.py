"""Transports: USB-HID (hidraw), USB-RS232 serial, raw TCP, EW10-MQTT socket.

All of them expose the same tiny API:

    request(cmd)      -> bytes  or None   answer whose PI30 crc validated
    request_raw(cmd)  -> bytes  or None   any answer ((ACK/(NAK/(ERR included)

so the poller does not care how the inverter is wired.
"""
from __future__ import annotations

import os
import select
import socket
import threading
import time

from . import config
from .pi30 import check_frame, frame


class TransportError(Exception):
    pass


class Transport:
    name = "base"

    def __init__(self):
        self.lock = threading.Lock()
        self.last_rx = 0.0
        self.rx_count = 0
        self.tx_count = 0

    # -- to override ---------------------------------------------------------
    def _open(self):
        pass

    def _close(self):
        pass

    def _write(self, data: bytes):
        raise NotImplementedError

    def _read_chunk(self, timeout: float) -> bytes:
        raise NotImplementedError

    def _reset(self):
        """Drop whatever half-frame is still in the buffers."""
        pass

    # -- shared --------------------------------------------------------------
    def describe(self) -> str:
        return self.name

    def close(self):
        with self.lock:
            self._close()

    def _recv_frame(self, timeout: float) -> bytes | None:
        buf = b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            chunk = self._read_chunk(max(0.05, deadline - time.time()))
            if chunk:
                buf += chunk
                if b"\r" in buf:
                    idx = buf.index(b"\r")
                    self.last_rx = time.time()
                    self.rx_count += 1
                    return buf[: idx + 1]
                # ACK/NAK have no crc but do end with \r as well
            if buf.startswith(b"(NAK") or buf.startswith(b"(ACK") or buf.startswith(b"(ERR"):
                if b"\r" in buf or len(buf) > 8:
                    self.last_rx = time.time()
                    return buf
        return None

    def _exchange(self, cmd: str, timeout: float) -> bytes | None:
        self._reset()
        self._write(frame(cmd))
        self.tx_count += 1
        return self._recv_frame(timeout)

    def request(self, cmd: str, timeout: float = 3.0, attempts: int = 2) -> bytes | None:
        with self.lock:
            for _ in range(attempts):
                try:
                    r = self._exchange(cmd, timeout)
                except Exception as ex:  # noqa: BLE001 - reconnect on anything
                    r = None
                    self._reset()
                if r is not None and check_frame(r):
                    return r
        return None

    def request_raw(self, cmd: str, timeout: float = 4.0, attempts: int = 2) -> bytes | None:
        with self.lock:
            for _ in range(attempts):
                try:
                    r = self._exchange(cmd, timeout)
                except Exception:
                    r = None
                    self._reset()
                if r:
                    return r
        return None


# ---------------------------------------------------------------- USB HID
class HidTransport(Transport):
    """Native inverter USB port (0665:5161 style HID, 8-byte reports).

    Works either on a hidraw node (`/dev/hidraw0`, no extra libs, recommended in
    Docker: pass the device through) or through hidapi when HID_DEVICE is not a
    path (pip install hidapi).
    """

    name = "usb-hid"

    def __init__(self):
        super().__init__()
        self.fd = None
        self.hid = None
        self.report_size = 8

    def describe(self) -> str:
        return f"usb-hid {config.HID_DEVICE}" if config.HID_DEVICE.startswith("/") else \
            f"usb-hid {config.HID_VID:04x}:{config.HID_PID:04x}"

    # hidraw ---------------------------------------------------------------
    def _open_hidraw(self):
        if self.fd is None:
            self.fd = os.open(config.HID_DEVICE, os.O_RDWR | os.O_NONBLOCK)

    def _open_hidapi(self):
        if self.hid is None:
            import hid  # type: ignore
            self.hid = hid.device()
            self.hid.open(config.HID_VID, config.HID_PID)
            self.hid.set_nonblocking(1)

    def _open(self):
        if config.HID_DEVICE.startswith("/"):
            self._open_hidraw()
        else:
            self._open_hidapi()

    def _close(self):
        if self.fd is not None:
            try:
                os.close(self.fd)
            finally:
                self.fd = None
        if self.hid is not None:
            try:
                self.hid.close()
            finally:
                self.hid = None

    def _write(self, data: bytes):
        self._open()
        rpt = bytes([config.HID_REPORT_ID]) + data
        if len(rpt) % self.report_size:
            rpt += b"\x00" * (self.report_size - len(rpt) % self.report_size)
        if self.fd is not None:
            os.write(self.fd, rpt)
        else:
            self.hid.write(list(rpt))

    def _read_chunk(self, timeout: float) -> bytes:
        self._open()
        if self.fd is not None:
            r, _, _ = select.select([self.fd], [], [], timeout)
            if not r:
                return b""
            try:
                return os.read(self.fd, 64)
            except BlockingIOError:
                return b""
        deadline = time.time() + timeout
        while time.time() < deadline:
            data = self.hid.read(self.report_size, 50)
            if data:
                return bytes(data)
        return b""

    def _reset(self):
        if self.fd is None and self.hid is None:
            return
        deadline = time.time() + 0.05
        while time.time() < deadline:
            if not self._read_chunk(0.02):
                break


# ---------------------------------------------------------------- serial
class SerialTransport(Transport):
    """USB-RS232 / RS485 adapter (2400 8N1 by default)."""

    name = "serial"

    def __init__(self):
        super().__init__()
        self.port = None

    def describe(self) -> str:
        return f"serial {config.SERIAL_PORT}@{config.SERIAL_BAUD}"

    def _open(self):
        if self.port is None:
            import serial  # type: ignore
            self.port = serial.Serial(
                config.SERIAL_PORT, config.SERIAL_BAUD,
                bytesize=8, parity="N", stopbits=1,
                timeout=0.2, write_timeout=2,
            )

    def _close(self):
        if self.port is not None:
            try:
                self.port.close()
            finally:
                self.port = None

    def _write(self, data: bytes):
        self._open()
        self.port.write(data)
        self.port.flush()

    def _read_chunk(self, timeout: float) -> bytes:
        self._open()
        if not self.port.in_waiting:
            time.sleep(min(timeout, 0.05))
            if not self.port.in_waiting:
                return b""
        return self.port.read(self.port.in_waiting or 1)

    def _reset(self):
        if self.port is None:
            return
        try:
            self.port.reset_input_buffer()
        except Exception:
            self._close()


# ---------------------------------------------------------------- tcp
class TcpTransport(Transport):
    """Any net-serial endpoint: EW10 dongle (:9999), ser2net, ESP32 gateway, usbip."""

    name = "tcp"

    def __init__(self):
        super().__init__()
        self.sock = None

    def describe(self) -> str:
        return f"tcp {config.TCP_HOST}:{config.TCP_PORT}"

    def _open(self):
        if self.sock is not None:
            return
        s = socket.create_connection((config.TCP_HOST, config.TCP_PORT), timeout=5)
        s.settimeout(3)
        if config.TCP_KEEPALIVE:
            s.setsockopt(socket.SOL_SOCKET, socket.SO_KEEPALIVE, 1)
            for opt, val in (("TCP_KEEPIDLE", 30), ("TCP_KEEPINTVL", 10), ("TCP_KEEPCNT", 3)):
                if hasattr(socket, opt):
                    s.setsockopt(socket.IPPROTO_TCP, getattr(socket, opt), val)
        self.sock = s

    def _close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            finally:
                self.sock = None

    def _write(self, data: bytes):
        self._open()
        self.sock.sendall(data)

    def _read_chunk(self, timeout: float) -> bytes:
        self._open()
        self.sock.settimeout(max(0.05, timeout))
        try:
            chunk = self.sock.recv(4096)
        except (socket.timeout, TimeoutError):
            return b""
        if not chunk:
            raise TransportError("connection closed by peer")
        return chunk

    def _reset(self):
        if self.sock is None:
            return
        self.sock.settimeout(0.05)
        try:
            while self.sock.recv(4096):
                pass
        except Exception:
            pass
        self.sock.settimeout(3)


# ---------------------------------------------------------------- mqtt socket
class MqttTransport(Transport):
    """EW10 dongle in MQTT mode: publish the frame, read the reply from a topic."""

    name = "mqtt-socket"

    def __init__(self, broker):
        super().__init__()
        self.b = broker
        self.pending = None
        self.ev = threading.Event()
        broker.subscribe(config.TRANS_TOPIC.rstrip("/") + "/data", self._on_data)

    def describe(self) -> str:
        return f"mqtt-socket {config.TRANS_TOPIC}cmd/{config.TRANS_TOPIC}data"

    def _on_data(self, topic: str, payload: bytes):
        self.pending = payload
        self.last_rx = time.time()
        self.rx_count += 1
        self.ev.set()

    def _exchange_mqtt(self, cmd: str, timeout: float) -> bytes | None:
        self.pending = None
        self.ev.clear()
        self.b.publish(config.TRANS_TOPIC.rstrip("/") + "/cmd", frame(cmd), retain=False)
        self.tx_count += 1
        if self.ev.wait(timeout):
            self.ev.clear()
            return self.pending
        return None

    def request(self, cmd: str, timeout: float = 3.0, attempts: int = 2):
        with self.lock:
            for _ in range(attempts):
                r = self._exchange_mqtt(cmd, timeout)
                if r is not None and check_frame(r):
                    return r
        return None

    def request_raw(self, cmd: str, timeout: float = 4.0, attempts: int = 2):
        with self.lock:
            for _ in range(attempts):
                r = self._exchange_mqtt(cmd, timeout)
                if r:
                    return r
        return None


def make_transport(broker=None) -> Transport:
    t = config.TRANSPORT
    if t in ("hid", "usb", "usb-hid"):
        return HidTransport()
    if t in ("serial", "rs232", "uart"):
        return SerialTransport()
    if t in ("tcp", "net", "ew10"):
        return TcpTransport()
    if t in ("mqtt", "mqtt-socket"):
        if broker is None:
            raise TransportError("TRANSPORT=mqtt needs a broker")
        return MqttTransport(broker)
    raise TransportError(f"unknown TRANSPORT={t!r} (hid|serial|tcp|mqtt)")
