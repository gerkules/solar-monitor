"""Journal of BMS codes (60/69/70/71) and BMS link losses (62).

The inverter shows these codes on its LCD and they come and go on their own, so a
history answers the practical question: "how often does the battery ask me not to
charge, and for how long". Kept in a small JSON ring buffer + written to InfluxDB
as the `bms_code` measurement, so Grafana can show the same stream as a step line.
"""
from __future__ import annotations

import json
import logging
import os
import time

log = logging.getLogger("battery.events")

MAX_EVENTS = 1000


class BmsEventLog:
    def __init__(self, path: str, influx=None, max_events: int = MAX_EVENTS):
        self.path = path
        self.influx = influx
        self.max_events = max_events
        self.events: list[dict] = []
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.events = list(data.get("events", []))[-self.max_events:]
        except FileNotFoundError:
            self.events = []
        except (OSError, json.JSONDecodeError) as ex:
            log.warning("cannot read BMS events %s: %r", self.path, ex)
            self.events = []

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "events": self.events[-self.max_events:]}, f)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save BMS events: %r", ex)

    # -- api ----------------------------------------------------------------
    def record(self, code: int, previous: int | None = None, note: str | None = None,
               ts: float | None = None) -> dict:
        ts = ts or time.time()
        event = {"ts": int(ts),
                 "time": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(ts)),
                 "code": int(code),
                 "previous": previous}
        if previous is not None and self.events:
            event["previous_since"] = self.events[-1]["ts"]
            event["previous_duration_s"] = int(ts) - self.events[-1]["ts"]
        if note:
            event["note"] = note
        self.events.append(event)
        self.events = self.events[-self.max_events:]
        self._save()
        log.info("BMS code %s (was %s)%s", code, previous, f" — {note}" if note else "")
        if self.influx is not None:
            try:
                self.influx.write_series("bms_code", [(int(ts), float(code))])
            except Exception:  # noqa: BLE001
                pass
        return event

    def list(self, limit: int = 50) -> list[dict]:
        return list(reversed(self.events))[:max(1, limit)]

    def summary(self, hours: float = 24, now: float | None = None) -> dict:
        now = now or time.time()
        since = now - hours * 3600
        per_code: dict[int, dict] = {}
        for i, event in enumerate(self.events):
            if event["ts"] < since or event["code"] == 0:
                continue        # code 0 = "no restriction", not interesting here
            code = event["code"]
            entry = per_code.setdefault(code, {"code": code, "count": 0, "seconds": 0})
            entry["count"] += 1
            end = (self.events[i + 1]["ts"] if i + 1 < len(self.events) else now)
            entry["seconds"] += max(0, min(end, now) - event["ts"])
        out = []
        for code, entry in sorted(per_code.items()):
            entry["minutes"] = round(entry["seconds"] / 60.0, 1)
            entry.pop("seconds", None)
            out.append(entry)
        return {"hours": hours, "codes": out, "events": len(self.events)}

    def current(self) -> dict | None:
        return self.events[-1] if self.events else None
