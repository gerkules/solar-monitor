"""Daly / Deligreen / Heyo BMS over UART or RS485 (0xA5 request, 0xD3 reply)."""
from __future__ import annotations

from .base import BmsDriver
from .serial_util import SerialPort


def checksum(data: bytes) -> int:
    return sum(data) & 0xFF


def build_request(address: int = 1, command: int = 0x90) -> bytes:
    """0xA5 0x40 <addr> 0x90 0x08 + 7 zero bytes + checksum."""
    body = bytes([0xA5, 0x40, address & 0xFF, command, 0x08, 0, 0, 0, 0, 0, 0, 0])
    return body + bytes([checksum(body)])


def parse_response(frame: bytes) -> dict | None:
    """Reply: 0xD3 <addr> <cmd> <len> <data...> <checksum>.

    data[0x90] = pack voltage (0.1 V), current (0.1 A, offset 30000),
    SOC (%), max/min cell voltage, temperatures, cell count, protections.
    """
    if len(frame) < 8 or frame[0] != 0xD3:
        return None
    body = frame[:-1]
    if checksum(body) != frame[-1]:
        return None
    data = frame[4:-1]
    if len(data) < 6:
        return None
    voltage = ((data[0] | (data[1] << 8)) / 10.0) if len(data) >= 2 else None
    current = None
    soc = None
    if len(data) >= 10:
        raw_current = data[4] | (data[5] << 8)
        current = round((raw_current - 30000) / 10.0, 1)
    if len(data) >= 11:
        soc = data[10] if data[10] <= 100 else None
    cells = None
    if len(data) >= 14:
        cells = [data[12] | (data[13] << 8)] if data[13] else None
    reading = {"bms_voltage": round(voltage, 2) if voltage else None,
               "bms_current": current, "bms_soc": soc}
    return BmsDriver.post({k: v for k, v in reading.items() if v is not None}) or None


class DalyDriver(BmsDriver):
    name = "daly"

    def __init__(self, **cfg):
        super().__init__(**cfg)
        self.port_io = SerialPort(self.port, self.baud or 9600)

    def describe(self) -> str:
        return f"Daly UART {self.port}@{self.baud}"

    def read(self) -> dict | None:
        try:
            raw = self.port_io.exchange(build_request(self.unit_id), settle=0.15)
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not raw:
            return None
        start = raw.find(b"\xd3")
        return parse_response(raw[start:]) if start >= 0 else None

    def close(self):
        self.port_io.close()
