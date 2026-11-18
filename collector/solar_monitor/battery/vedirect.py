"""Victron VE.Direct (BMV / SmartShunt) over USB-serial — the "shunt" option.

VE.Direct sends 19200 8N1 text blocks: "Label<TAB>Value\\n" ending with a
checksum line. We only need V/I/P/SOC/consumed Ah.
"""
from __future__ import annotations

from .base import BmsDriver
from .serial_util import SerialPort

NUMERIC = {
    "V": ("bms_voltage", 0.001),
    "I": ("bms_current", 0.001),
    "P": ("bms_power", 1.0),
    "SOC": ("bms_soc", 0.1),          # per mille
    "CE": ("bms_remaining_ah", -0.001),   # consumed Ah, negative = discharged
    "TTG": (None, 1.0),
}


def parse_vedirect(block: str) -> dict | None:
    reading: dict = {}
    for line in block.splitlines():
        if "\t" not in line:
            continue
        label, _, value = line.partition("\t")
        spec = NUMERIC.get(label.strip())
        if not spec or not spec[0]:
            continue
        key, scale = spec
        try:
            reading[key] = round(float(value) * scale, 2)
        except ValueError:
            continue
    if "bms_remaining_ah" in reading:
        reading["bms_remaining_ah"] = abs(reading["bms_remaining_ah"])
    return BmsDriver.post(reading) if reading else None


class VeDirectDriver(BmsDriver):
    name = "vedirect"

    def __init__(self, **cfg):
        super().__init__(**cfg)
        self.port_io = SerialPort(self.port, 19200, timeout=3.0)

    def describe(self) -> str:
        return f"VE.Direct {self.port}"

    def read(self) -> dict | None:
        try:
            raw = self.port_io.exchange(b"", settle=0.25)     # shunt talks by itself
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not raw:
            return None
        self.last_raw = raw[:200].hex()
        return parse_vedirect(raw.decode(errors="replace"))

    def close(self):
        self.port_io.close()
