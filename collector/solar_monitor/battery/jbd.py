"""JBD / Xiaoxiang / Overkill Solar BMS over UART/RS485 (0x03 "basic info")."""
from __future__ import annotations

from .base import BmsDriver
from .serial_util import SerialPort

REQUEST = bytes([0xDD, 0xA5, 0x03, 0x00, 0xFF, 0xFD, 0x77])


def jbd_checksum(frame: bytes) -> int:
    return (0x10000 - sum(frame)) & 0xFFFF


def _decode_temp(raw: bytes, mode: str) -> float | None:
    """JBD firms differ: 1 byte with +40 offset, 1 byte 0.1 K, or 2-byte 0.1 K."""
    if not raw:
        return None
    if mode == "0.1k16" and len(raw) >= 2:
        return round(int.from_bytes(raw[:2], "big") * 0.1 - 273.15, 1)
    if mode == "0.1k":
        return round(raw[0] * 0.1 - 273.15, 1)
    return round(raw[0] - 40.0, 1)


def parse_jbd(frame: bytes, ntc_count: int = 2, temp_mode: str = "offset40") -> dict | None:
    """Parse a JBD reply frame: DD <status> <len> <data...> <crc16> 77.

    0x03 "basic info" data layout: 0x03, cells(n, 2B), n*2B cell mV,
    `ntc_count` temperatures, current(2B, 10 mA, signed), remaining Ah,
    nominal Ah, cycles (2B each, 10 mAh / 1).
    """
    if len(frame) < 8 or frame[0] != 0xDD or frame[-1] != 0x77:
        return None
    length = frame[2]
    if len(frame) < 5 + length:
        return None
    data = frame[3:3 + length]
    if len(data) < 8 or data[0] != 0x03:
        return None
    crc = (frame[3 + length] << 8) | frame[4 + length]
    if crc != jbd_checksum(frame[2:3 + length]):
        return None

    cells_n = (data[1] << 8) | data[2]
    if not 1 <= cells_n <= 40 or len(data) < 3 + cells_n * 2:
        return None
    cells = [(data[3 + i * 2] << 8) | data[4 + i * 2] for i in range(cells_n)]

    off = 3 + cells_n * 2
    width = 2 if temp_mode == "0.1k16" else 1
    temps = []
    for i in range(ntc_count):
        chunk = data[off + i * width: off + (i + 1) * width]
        if len(chunk) < width:
            break
        temp = _decode_temp(chunk, temp_mode)
        if temp is not None and -40 < temp < 120:
            temps.append(temp)
    off += ntc_count * width

    if off + 8 > len(data):
        return BmsDriver.post({"bms_cells": cells,
                               "bms_temperature": temps[0] if temps else None})
    current = int.from_bytes(data[off:off + 2], "big", signed=True) / 100.0
    remaining = int.from_bytes(data[off + 2:off + 4], "big") / 100.0
    capacity = int.from_bytes(data[off + 4:off + 6], "big") / 100.0
    cycles = int.from_bytes(data[off + 6:off + 8], "big")
    voltage = round(sum(cells) / 1000.0, 2) if cells else None
    soc = round(100.0 * remaining / capacity, 1) if capacity else None
    return BmsDriver.post({
        "bms_cells": cells, "bms_voltage": voltage, "bms_current": current,
        "bms_temperature": temps[0] if temps else None,
        "bms_remaining_ah": remaining, "bms_capacity_ah": capacity,
        "bms_cycles": cycles, "bms_soc": soc,
    })


class JbdDriver(BmsDriver):
    name = "jbd"

    def __init__(self, ntc_count=2, temp_mode="offset40", **cfg):
        super().__init__(**cfg)
        self.ntc_count = int(ntc_count or 2)
        self.temp_mode = temp_mode or "offset40"
        self.port_io = SerialPort(self.port, self.baud)

    def describe(self) -> str:
        return f"JBD {self.port}@{self.baud}"

    def read(self) -> dict | None:
        try:
            frame = self.port_io.exchange(REQUEST, settle=0.1)
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not frame:
            return None
        idx = frame.find(b"\xdd")
        if idx > 0:
            frame = frame[idx:]
        return parse_jbd(frame, self.ntc_count, self.temp_mode)

    def close(self):
        self.port_io.close()
