"""Persisted battery selection (so the UI can switch sources at runtime)."""
from __future__ import annotations

import json
import logging
import os

log = logging.getLogger("battery")

DEFAULTS = {
    "source": "inverter",       # driver name: inverter|emulated|jbd|daly|pylontech|modbus|vedirect|voltronic|can
    "brand": "",                 # catalogue id, purely informational
    "port": "/dev/ttyUSB0",
    "baud": 9600,
    "unit_id": 1,
    "capacity_ah": None,
    "nominal_voltage": 48.0,
    "interface": "can0",
    "ntc_count": 2,
    "temp_mode": "offset40",
    "interval": 10,
}


class BatteryStore:
    def __init__(self, path: str):
        self.path = path
        self._load()

    def _load(self):
        self.data = dict(DEFAULTS)
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data.update(json.load(f))
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError) as ex:
            log.warning("cannot read battery config %s: %r", self.path, ex)

    def save(self, cfg: dict):
        self.data = {**DEFAULTS, **cfg}
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f, indent=2)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save battery config: %r", ex)

    def update(self, patch: dict):
        self.save({**self.data, **patch})
        return self.data
