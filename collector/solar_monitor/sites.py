"""Multi-site registry: every collector retains `<root>/<site>/state` on the broker,
so any UI container can list and show all sites without extra configuration."""
from __future__ import annotations

import json
import logging
import time

from . import config

log = logging.getLogger("sites")

SUMMARY_KEYS = ("device_mode", "pv_power", "load_power", "grid_power", "battery_power",
                "battery_voltage", "battery_state_of_charge", "temperature",
                "pv_energy_today", "load_energy_today", "pv_power_2", "has_mppt2")


class SiteRegistry:
    def __init__(self, mqtt, local_poller=None):
        self.mqtt = mqtt
        self.local = local_poller
        self.states: dict[str, dict] = {}
        self.updated: dict[str, float] = {}
        self.online: dict[str, bool] = {}
        self._extra_cache: tuple[float, set[str]] = (0.0, set())
        if mqtt is not None:
            mqtt.subscribe(f"{config.SITE_ROOT}/+/state", self._on_state)
            mqtt.subscribe(f"{config.SITE_ROOT}/+/status", self._on_status)

    # -- mqtt ---------------------------------------------------------------
    def _site_of(self, topic: str) -> str | None:
        parts = topic.split("/")
        return parts[-2] if len(parts) >= 3 else None

    def _on_state(self, topic: str, payload: bytes):
        site = self._site_of(topic)
        try:
            state = json.loads(payload)
        except (json.JSONDecodeError, TypeError):
            return
        site = state.get("site") or site
        if not site:
            return
        self.states[site] = state
        self.updated[site] = time.time()
        if state.get("last_update"):
            self.online[site] = True

    def _on_status(self, topic: str, payload: bytes):
        site = self._site_of(topic)
        if not site:
            return
        try:
            value = payload.decode() if isinstance(payload, bytes) else str(payload)
        except Exception:  # noqa: BLE001
            return
        self.online[site] = value.strip() == "online"

    # -- api ----------------------------------------------------------------
    def get(self, site: str | None = None) -> dict | None:
        site = site or config.SITE
        if self.local is not None and site == config.SITE:
            snap = self.local.snapshot()
            if snap:
                return snap
        return self.states.get(site)

    def _prune(self):
        """Forget sites that stopped publishing (a deleted retained state must not linger)."""
        cutoff = time.time() - config.SITE_TTL
        for site in [s for s, ts in self.updated.items() if ts < cutoff]:
            self.states.pop(site, None)
            self.updated.pop(site, None)
            self.online.pop(site, None)

    def _extra_sites(self) -> set[str]:
        """Доп. инверторы, настроенные на этом хосте (даже если они ещё ни разу
        не публиковали состояние): их нужно показывать в списке сайтов, иначе
        добавленный, но неотвечающий инвертор «пропадёт» из интерфейса.

        Результат кешируется: `listing()` дёргает systemctl, а meta/sites
        запрашиваются часто.
        """
        now = time.time()
        cached_at, cached = self._extra_cache
        if now - cached_at < 30.0:
            return cached
        names: set[str] = set()
        try:
            from . import inverters
            if inverters.supported():
                names = {i["site"] for i in inverters.listing()}
        except Exception:  # noqa: BLE001 - без доп. инверторов живём спокойно
            names = set()
        self._extra_cache = (now, names)
        return names

    def sites(self) -> list[dict]:
        self._prune()
        names = set(self.states) | {config.SITE} | self._extra_sites()
        out = []
        for name in sorted(names):
            state = self.get(name) or {}
            age = None
            ts = state.get("last_update")
            if ts:
                age = round(time.time() - ts, 1)
            item = {"site": name, "online": bool(state) and (age is not None and age < 300),
                    "last_update": ts, "age_s": age}
            for key in SUMMARY_KEYS:
                if key in state:
                    item[key] = state[key]
            out.append(item)
        return out

    def sites_for_select(self) -> list[str]:
        return [s["site"] for s in self.sites()]
