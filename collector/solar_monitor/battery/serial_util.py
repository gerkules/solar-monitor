"""Small helper shared by the serial BMS drivers."""
from __future__ import annotations

import time


class SerialPort:
    """Thin wrapper over pyserial with a 'write then read until quiet' pattern."""

    def __init__(self, port: str, baud: int = 9600, timeout: float = 2.0):
        self.port = port
        self.baud = baud
        self.timeout = timeout
        self._ser = None

    def open(self):
        if self._ser is None:
            import serial  # type: ignore
            self._ser = serial.Serial(self.port, self.baud, timeout=0.2,
                                      write_timeout=2, bytesize=8, parity="N",
                                      stopbits=1)
        return self._ser

    def close(self):
        if self._ser is not None:
            try:
                self._ser.close()
            except Exception:  # noqa: BLE001
                pass
            self._ser = None

    def exchange(self, payload: bytes, expect: int = 0, settle: float = 0.15) -> bytes:
        """Write a request and read until `expect` bytes (or the line goes quiet)."""
        ser = self.open()
        ser.reset_input_buffer()
        ser.write(payload)
        ser.flush()
        deadline = time.time() + self.timeout
        buf = b""
        while time.time() < deadline:
            chunk = ser.read(256)
            if chunk:
                buf += chunk
                if expect and len(buf) >= expect:
                    break
                time.sleep(settle)
                continue
            if buf:
                break
            time.sleep(0.05)
        return buf
