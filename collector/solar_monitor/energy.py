"""Derived power values and daily energy counters (persisted to disk)."""
from __future__ import annotations

import json
import logging
import os
import time

from . import config

log = logging.getLogger("energy")

ENERGY_KEYS = ("pv_energy_today", "load_energy_today", "grid_energy_today",
               "battery_charge_today", "battery_discharge_today")


def derive_pv(state: dict):
    p1 = state.get("pv_power_1") or 0
    p2 = state.get("pv_power_2") or 0
    # Fallback: inverters that only report MPPT1 in QPIGS
    if not p1 and state.get("pv_voltage_1") and state.get("pv_current_1"):
        p1 = round(state["pv_voltage_1"] * state["pv_current_1"])
        state["pv_power_1"] = p1
    if not p2 and state.get("pv_voltage_2") and state.get("pv_current_2"):
        p2 = round(state["pv_voltage_2"] * state["pv_current_2"])
        state["pv_power_2"] = p2
    state["pv_power"] = p1 + p2


def derive_power(state: dict, deadband: float | None = None):
    """PI30 exposes no grid CT: grid power is the balance of the other three.

    battery_power: >0 charging, <0 discharging
    grid_power   : >0 import from grid (below `deadband` treated as noise)
    """
    deadband = config.GRID_DEADBAND if deadband is None else deadband
    bv = state.get("battery_voltage")
    bc = state.get("battery_charge_current")
    bd = state.get("battery_discharge_current")
    if bv is None or bc is None or bd is None:
        return
    batt = bv * (bc - bd)
    state["battery_power"] = round(batt)
    state["battery_current"] = round(bc - bd, 1)
    pv = state.get("pv_power")
    load = state.get("load_power")
    if pv is not None and load is not None:
        derived = load - pv + batt
        state["grid_power"] = 0 if derived < deadband else round(derived)


class EnergyCounter:
    """W -> kWh integration with a midnight reset (local time, TZ from env)."""

    def __init__(self, path: str = None):
        self.path = path or config.ENERGY_FILE
        self.data: dict = {}
        self.last_ts: float | None = None
        self._load()

    def _load(self):
        try:
            with open(self.path) as f:
                self.data = json.load(f)
        except (OSError, json.JSONDecodeError):
            self.data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w") as f:
                json.dump(self.data, f)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save energy counters: %r", ex)

    def _reset_if_new_day(self):
        today = time.strftime("%Y-%m-%d")
        if self.data.get("date") != today:
            self.data = {"date": today, **{k: 0.0 for k in ENERGY_KEYS}}

    def accumulate(self, state: dict, now: float | None = None) -> dict:
        now = now or time.time()
        self._reset_if_new_day()
        if self.last_ts is not None:
            dt = min(now - self.last_ts, 120.0)
            powers = {
                "pv_energy_today": state.get("pv_power") or 0,
                "load_energy_today": state.get("load_power") or 0,
                "grid_energy_today": max(state.get("grid_power") or 0, 0),
                "battery_charge_today": max(state.get("battery_power") or 0, 0),
                "battery_discharge_today": max(-(state.get("battery_power") or 0), 0),
            }
            for key, watts in powers.items():
                self.data[key] = round(self.data.get(key, 0.0) + watts * dt / 3_600_000.0, 4)
            self._save()
        self.last_ts = now
        state.update({k: self.data.get(k, 0.0) for k in ENERGY_KEYS})
        return state
