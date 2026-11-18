"""Battery monitoring drivers.

One interface for every source, so the rest of the stack only sees `bms_*` keys:

    driver = make_driver(config)          # or None for "inverter"
    reading = driver.read()               # dict with normalized keys, or None

Normalized keys (only what the BMS actually reports is filled in):
    bms_soc, bms_soh, bms_voltage, bms_current, bms_power, bms_temperature,
    bms_cells, bms_cell_min, bms_cell_max, bms_cycles, bms_capacity_ah,
    bms_remaining_ah, bms_protections, bms_packs
"""
from __future__ import annotations

import logging

log = logging.getLogger("battery")

# state keys written by the monitor
BMS_KEYS = ("bms_soc", "bms_soh", "bms_voltage", "bms_current", "bms_power",
            "bms_temperature", "bms_cells", "bms_cell_min", "bms_cell_max",
            "bms_cycles", "bms_capacity_ah", "bms_remaining_ah",
            "bms_protections", "bms_packs")


class BmsDriver:
    name = "base"
    #: battery metrics that should replace inverter-derived values when this
    #: source is selected (SolarAssistant does the same: the BMS wins)
    overrides = ("battery_voltage", "battery_current", "battery_power",
                 "battery_state_of_charge")

    def __init__(self, **cfg):
        self.cfg = cfg
        self.port = cfg.get("port")
        self.baud = int(cfg.get("baud") or 9600)
        self.unit_id = int(cfg.get("unit_id") or 1)
        self.capacity_ah = float(cfg.get("capacity_ah") or 0) or None
        self._io = None

    # -- io -----------------------------------------------------------------
    def open(self):
        raise NotImplementedError

    def close(self):
        if self._io is not None:
            try:
                self._io.close()
            except Exception:  # noqa: BLE001
                pass
            self._io = None

    def read(self) -> dict | None:
        raise NotImplementedError

    def describe(self) -> str:
        return self.name

    # -- helpers ------------------------------------------------------------
    @staticmethod
    def post(reading: dict) -> dict:
        """Fill derived values that every driver can compute."""
        v, i = reading.get("bms_voltage"), reading.get("bms_current")
        if v is not None and i is not None:
            reading.setdefault("bms_power", round(v * i, 1))
        cells = reading.get("bms_cells")
        if cells:
            valid = [c for c in cells if c]
            if valid:
                reading.setdefault("bms_cell_min", round(min(valid) / 1000.0, 3))
                reading.setdefault("bms_cell_max", round(max(valid) / 1000.0, 3))
        return {k: v for k, v in reading.items() if v is not None}


def to_state(reading: dict) -> dict:
    """Normalized reading -> flat state keys (bms_* only)."""
    out = {}
    for key in BMS_KEYS:
        if key in reading:
            value = reading[key]
            out[key] = value if not isinstance(value, list) else len(value)
    if "bms_cells" in reading:
        out["bms_cell_count"] = len(reading["bms_cells"] or [])
    return out
