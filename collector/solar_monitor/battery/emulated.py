"""Emulated BMS: coulomb counting on top of the inverter's own power reading.

SolarAssistant offers this as a fallback for lithium packs, because a Voltronic
inverter estimates SoC from voltage and that is very inaccurate.
"""
from __future__ import annotations

import time

from .base import BmsDriver


class EmulatedDriver(BmsDriver):
    name = "emulated"

    def __init__(self, capacity_ah=None, nominal_voltage=48.0, initial_soc=None, **cfg):
        super().__init__(capacity_ah=capacity_ah, **cfg)
        self.nominal_voltage = float(nominal_voltage or 48.0)
        self.soc: float | None = float(initial_soc) if initial_soc is not None else None
        self.last_ts: float | None = None
        self.charged_ah = 0.0

    @property
    def total_wh(self) -> float:
        return self.nominal_voltage * (self.capacity_ah or 0)

    def read(self) -> dict | None:
        return None        # filled in by update() from the inverter's own values

    def update(self, power: float | None, voltage: float | None = None,
               soc_hint: float | None = None) -> dict | None:
        """Integrate battery power (W, +charge/-discharge) into a SoC estimate."""
        now = time.time()
        if self.soc is None:
            if soc_hint is None:
                return None      # wait for the inverter's own SoC before integrating
            self.soc = float(soc_hint)
        if power is not None and self.last_ts is not None and self.total_wh > 0:
            dt = min(now - self.last_ts, 120.0)
            energy_wh = power * dt / 3600.0
            self.charged_ah += energy_wh / self.nominal_voltage
            self.soc = max(0.0, min(100.0, self.soc + 100.0 * energy_wh / self.total_wh))
        self.last_ts = now
        reading = {"bms_soc": round(self.soc, 1),
                   "bms_capacity_ah": self.capacity_ah,
                   "bms_remaining_ah": round(self.charge_left_ah(), 1)
                   if self.capacity_ah else None}
        if voltage:
            reading["bms_voltage"] = voltage
        return {k: v for k, v in reading.items() if v is not None}

    def charge_left_ah(self) -> float:
        if not self.capacity_ah or self.soc is None:
            return 0.0
        return self.capacity_ah * self.soc / 100.0

    def describe(self) -> str:
        cap = f"{self.capacity_ah:g} Ah" if self.capacity_ah else "no capacity"
        return f"emulated ({cap}, {self.nominal_voltage:g} В)"
