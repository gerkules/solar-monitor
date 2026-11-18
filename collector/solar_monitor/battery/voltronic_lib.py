"""Voltronic LIB / Felicity / BlueNova style batteries that answer PI30 frames.

These packs speak the same ASCII protocol as the inverter, so we reuse the PI30
parser: QPIGS gives us battery voltage/current/SOC directly.
"""
from __future__ import annotations

try:
    from .. import pi30          # solar_monitor.battery
except ImportError:  # pragma: no cover - imported as top-level package in tests
    from solar_monitor import pi30
from .base import BmsDriver
from .serial_util import SerialPort


class VoltronicLibDriver(BmsDriver):
    name = "voltronic"

    def __init__(self, **cfg):
        super().__init__(**cfg)
        self.port_io = SerialPort(self.port, self.baud or 2400, timeout=2.0)

    def describe(self) -> str:
        return f"Voltronic LIB {self.port}@{self.baud}"

    def read(self) -> dict | None:
        try:
            raw = self.port_io.exchange(pi30.frame("QPIGS"), expect=110, settle=0.2)
        except Exception:  # noqa: BLE001
            self.port_io.close()
            return None
        if not raw or b"(" not in raw:
            return None
        frame = raw[raw.index(b"("):]
        if not pi30.check_frame(frame):
            return None
        d = pi30.parse_qpigs(frame)
        if not d:
            return None
        reading = {
            "bms_voltage": d.get("battery_voltage"),
            "bms_current": round((d.get("battery_charge_current") or 0)
                                 - (d.get("battery_discharge_current") or 0), 1),
            "bms_soc": d.get("battery_state_of_charge"),
            "bms_temperature": d.get("temperature"),
        }
        return BmsDriver.post({k: v for k, v in reading.items() if v is not None})

    def close(self):
        self.port_io.close()
