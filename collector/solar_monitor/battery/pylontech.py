"""Pylontech / Pytes RS232 console (ASCII commands, tolerant parsing).

The console answers text commands (`pwr`, `stat`, `info`) with plain lines; we
parse the key/value pairs instead of fixed offsets, so small firmware differences
do not break the reading.
"""
from __future__ import annotations

import re

from .base import BmsDriver
from .serial_util import SerialPort

FIELDS = {
    "voltage": ("bms_voltage", 1.0),
    "volt": ("bms_voltage", 1.0),
    "curr": ("bms_current", 1.0),
    "current": ("bms_current", 1.0),
    "soc": ("bms_soc", 1.0),
    "soh": ("bms_soh", 1.0),
    "temperature": ("bms_temperature", 1.0),
    "temp": ("bms_temperature", 1.0),
    "total capacity": ("bms_capacity_ah", 1.0),
}


def parse_console(text: str) -> dict | None:
    """Parse 'Power Volt Current SOC ...' style output (labels may be Russian-free)."""
    nums = re.findall(r"-?\d+(?:\.\d+)?", text)
    reading: dict = {}
    lowered = text.lower()
    for label, (key, scale) in FIELDS.items():
        match = re.search(rf"{label}[^\d-]*(-?\d+(?:\.\d+)?)", lowered)
        if match:
            reading[key] = round(float(match.group(1)) * scale, 2)
    if not reading and "power" in lowered and len(nums) >= 3:
        # "Power 01 : Volt 52.13 Curr 12.3 SOC 87 SOH 100" fallback
        reading["bms_voltage"] = float(nums[1])
        reading["bms_current"] = float(nums[2])
        reading["bms_soc"] = float(nums[3]) if len(nums) > 3 else None
    return BmsDriver.post(reading) if reading else None


class PylontechDriver(BmsDriver):
    name = "pylontech"

    def __init__(self, command="pwr", **cfg):
        super().__init__(**cfg)
        self.command = command or "pwr"
        self.port_io = SerialPort(self.port, self.baud or 115200)

    def describe(self) -> str:
        return f"Pylontech console {self.port}@{self.baud}"

    def read(self) -> dict | None:
        try:
            raw = self.port_io.exchange((self.command + "\r\n").encode(), settle=0.3)
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not raw:
            return None
        return parse_console(raw.decode(errors="replace"))

    def close(self):
        self.port_io.close()
