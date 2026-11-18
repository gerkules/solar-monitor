"""Battery monitoring: drivers, factory and the polling monitor thread."""
from __future__ import annotations

import logging
import threading
import time

from .base import BMS_KEYS, BmsDriver, to_state
from . import catalog as catalog_mod
from .store import BatteryStore
from .events import BmsEventLog
from .canbus import CanDriver
from .daly import DalyDriver
from .emulated import EmulatedDriver
from .jbd import JbdDriver
from .modbus import ModbusDriver
from .pylontech import PylontechDriver
from .vedirect import VeDirectDriver
from .voltronic_lib import VoltronicLibDriver

log = logging.getLogger("battery")

OVERRIDE_MAP = {
    "battery_voltage": "bms_voltage",
    "battery_current": "bms_current",
    "battery_power": "bms_power",
    "battery_state_of_charge": "bms_soc",
}

SOURCES = {
    "inverter": "значения инвертора",
    "daly": "Daly / Deligreen / Heyo (UART/RS485)",
    "voltronic": "Voltronic LIB / Felicity / BlueNova (RS485)",
    "emulated": "эмуляция (кулонометрия)",
    "jbd": "JBD / Overkill / QUCC (USB-UART/RS485)",
    "pylontech": "Pylontech / Pytes / Dyness (RS232 console)",
    "modbus": "Modbus RTU (RS232/RS485, регистры в конфиге)",
    "vedirect": "Victron VE.Direct (шунт BMV/SmartShunt)",
    "can": "CAN bus (Pylontech/Dyness/SolarMD)",
}

DRIVERS = {
    "jbd": JbdDriver,
    "daly": DalyDriver,
    "voltronic": VoltronicLibDriver,
    "pylontech": PylontechDriver,
    "modbus": ModbusDriver,
    "vedirect": VeDirectDriver,
    "can": CanDriver,
}


def make_driver(source: str, cfg: dict) -> BmsDriver | None:
    """`source` is a driver name (inverter|emulated|jbd|daly|...) or a catalogue id."""
    source = (source or "inverter").lower()
    item = catalog_mod.find(source)
    if item is not None:
        if not item["supported"]:
            raise ValueError(f"«{item['brand']}»: протокол пока не реализован")
        source = item["driver"]
        cfg = {**cfg, "baud": cfg.get("baud") or item.get("baud")}
    if source in ("inverter", "", "none"):
        return None
    if source == "emulated":
        return EmulatedDriver(capacity_ah=cfg.get("capacity_ah"),
                              nominal_voltage=cfg.get("nominal_voltage") or 48.0,
                              initial_soc=cfg.get("initial_soc"))
    cls = DRIVERS.get(source)
    if cls is None:
        raise ValueError(f"unknown battery source {source!r}")
    return cls(**cfg)


class BatteryMonitor:
    """Polls the BMS and merges its values into the collector state.

    When the source is not the inverter, the BMS wins over the inverter's own
    (voltage-based) figures — that is what SolarAssistant does as well.
    The selection can be changed at runtime through the API/UI (stored on disk).
    """

    def __init__(self, source, state: dict, cfg: dict | None = None, store: BatteryStore = None):
        self.lock = threading.Lock()
        self.store = store
        self.cfg = dict(cfg or {})
        if store is not None:
            self.cfg = {**self.cfg, **store.data}
            source = store.data.get("source") or source
            self.cfg["brand"] = store.data.get("brand", "")
        self.source = (source or "inverter").lower()
        self.state = state
        self.driver = make_driver(self.source, self.cfg)
        self.last_reading: dict | None = None
        self.last_ts: float | None = None
        self.errors = 0
        self.last_error: str | None = None

    @property
    def enabled(self) -> bool:
        return self.driver is not None

    def describe(self) -> str:
        if self.driver is None:
            return "inverter"
        return self.driver.describe()

    # -- runtime reconfiguration --------------------------------------------
    def available(self) -> dict:
        return {
            "catalog": catalog_mod.catalog(),
            "drivers": sorted(SOURCES),
            "ports": _serial_ports(),
        }

    def apply_config(self, patch: dict) -> dict:
        """Switch source on the fly (used by the UI/API)."""
        cfg = {**self.cfg, **patch}
        item = catalog_mod.find(cfg.get("brand") or "") if cfg.get("brand") else None
        if item is not None:
            cfg.setdefault("baud", item.get("baud") or cfg.get("baud"))
            if not cfg.get("source"):
                cfg["source"] = item["driver"]
        source = (cfg.get("source") or "inverter").lower()
        new_driver = make_driver(source, cfg)     # raises on unknown/unsupported
        with self.lock:
            old, self.driver = self.driver, new_driver
            self.source, self.cfg = source, cfg
            self.last_reading, self.last_ts, self.last_error = None, None, None
            self.errors = 0
            self.state.pop("battery_source", None)
            for key in list(self.state):
                if key.startswith("bms_"):
                    self.state.pop(key, None)
        if old is not None:
            try:
                old.close()
            except Exception:  # noqa: BLE001
                pass
        if self.store is not None:
            self.store.save(cfg)
        return self.snapshot()

    def config(self) -> dict:
        return {**self.cfg, "source": self.source}

    def snapshot(self) -> dict:
        return {
            "source": self.source,
            "enabled": self.enabled,
            "driver": self.describe(),
            "available": {k: v for k, v in SOURCES.items()},
            "last_ts": self.last_ts,
            "age_s": round(time.time() - self.last_ts, 1) if self.last_ts else None,
            "errors": self.errors,
            "last_error": self.last_error,
            "reading": self.last_reading or {},
        }

    def poll_once(self) -> dict | None:
        driver = self.driver
        if driver is None:
            return None
        try:
            if isinstance(driver, EmulatedDriver):
                reading = driver.update(
                    power=self.state.get("battery_power"),
                    voltage=self.state.get("battery_voltage"),
                    soc_hint=self.state.get("battery_state_of_charge"),
                )
            else:
                reading = driver.read()
        except Exception as ex:  # noqa: BLE001
            self.errors += 1
            self.last_error = repr(ex)
            log.warning("battery read failed: %r", ex)
            return None
        if not reading:
            return None
        self.last_reading = reading
        self.last_ts = time.time()
        self.state.update(to_state(reading))
        self.state["battery_source"] = self.source
        for key, src in OVERRIDE_MAP.items():
            value = reading.get(src)
            if value is not None:
                self.state[key] = value
        if "bms_power" in reading:
            self.state["battery_power"] = reading["bms_power"]
        return reading

    def reapply(self, state: dict | None = None):
        """Re-apply the last BMS reading: the collector rebuilds its state every cycle,
        so without this the inverter's voltage-based values would win again."""
        state = state if state is not None else self.state
        reading = self.last_reading
        if self.driver is None or not reading:
            return
        state.update(to_state(reading))
        state["battery_source"] = self.source
        for key, src in OVERRIDE_MAP.items():
            value = reading.get(src)
            if value is not None:
                state[key] = value

    def run(self):
        log.info("battery source: %s", self.describe())
        interval = float(self.cfg.get("interval") or 10)
        while True:
            if self.driver is not None:
                self.poll_once()
            time.sleep(max(1.0, float(self.cfg.get("interval") or interval)))

    def start(self):
        threading.Thread(target=self.run, name="battery", daemon=True).start()

    def close(self):
        if self.driver is not None:
            self.driver.close()


def _serial_ports() -> list[str]:
    import glob
    ports = sorted(glob.glob("/dev/ttyUSB*") + glob.glob("/dev/ttyACM*")
                   + glob.glob("/dev/serial/by-id/*"))
    return ports or []


__all__ = ["BatteryMonitor", "make_driver", "SOURCES", "BMS_KEYS", "to_state",
           "BatteryStore", "catalog_mod", "BmsEventLog"]
