"""Generic Modbus RTU over RS232/RS485 — the "USB Modbus" option in SolarAssistant.

Register map is configurable, because every brand lays its data out differently:

    BMS_MODBUS={"voltage": [0x0100, 0.01], "current": [0x0102, 0.1, "s16"],
                "soc": [0x0104, 1], "soh": [0x0105, 1], "temperature": [0x0106, 0.1, "s16"]}
"""
from __future__ import annotations

from .base import BmsDriver
from .serial_util import SerialPort


def crc16_modbus(data: bytes) -> bytes:
    crc = 0xFFFF
    for byte in data:
        crc ^= byte
        for _ in range(8):
            crc = (crc >> 1) ^ 0xA001 if crc & 1 else crc >> 1
    return bytes([crc & 0xFF, crc >> 8])


def build_request(unit: int, function: int, address: int, count: int) -> bytes:
    body = bytes([unit, function]) + address.to_bytes(2, "big") + count.to_bytes(2, "big")
    return body + crc16_modbus(body)


def parse_response(frame: bytes, unit: int, function: int) -> list[int] | None:
    if len(frame) < 5 or frame[0] != unit:
        return None
    if frame[1] & 0x80:                     # exception response
        return None
    count = frame[2]
    if len(frame) < 3 + count + 2:
        return None
    payload = frame[3:3 + count]
    crc = frame[3 + count:5 + count]
    if crc16_modbus(frame[:3 + count]) != crc:
        return None
    return [(payload[i] << 8) | payload[i + 1] for i in range(0, count - 1, 2)]


def decode(registers: list[int], base: int, scale: float, signed: bool) -> float | None:
    idx = base
    if idx < 0 or idx >= len(registers):
        return None
    raw = registers[idx]
    if signed and raw > 0x7FFF:
        raw -= 0x10000
    return round(raw * scale, 3)


class ModbusDriver(BmsDriver):
    name = "modbus"

    def __init__(self, registers=None, **cfg):
        super().__init__(**cfg)
        self.registers = registers or {}
        self.port_io = SerialPort(self.port, self.baud)

    def describe(self) -> str:
        return f"Modbus RTU {self.port}@{self.baud} unit {self.unit_id}"

    def read(self) -> dict | None:
        if not self.registers:
            return None
        # one contiguous read covering every configured register
        offsets = [int(spec[0]) for spec in self.registers.values() if spec]
        if not offsets:
            return None
        start, count = min(offsets), max(offsets) - min(offsets) + 1
        if count > 100:
            return None
        try:
            raw = self.port_io.exchange(build_request(self.unit_id, 3, start, count))
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not raw or len(raw) > 64:        # an echo of our own request is not a reply
            return None
        regs = parse_response(raw, self.unit_id, 3)
        if not regs:
            return None
        reading: dict = {}
        for key, spec in self.registers.items():
            address = int(spec[0]) - start
            scale = float(spec[1]) if len(spec) > 1 else 1.0
            signed = len(spec) > 2 and spec[2] == "s16"
            value = decode(regs, address, scale, signed)
            if value is not None:
                reading[f"bms_{key}" if not key.startswith("bms_") else key] = value
        return BmsDriver.post(reading) if reading else None

    def close(self):
        self.port_io.close()
