"""Automation rules: "when <metric> <op> <value> for <n>s → do <actions>".

Stored as JSON (survives restarts), evaluated once per poll cycle. A rule fires
only when its condition has been true for `for_s` seconds and its per-rule
cooldown has expired — the same debounce-and-cooldown behaviour the rule table in
SolarAssistant has.
"""
from __future__ import annotations

import json
import logging
import operator
import os
import time
import uuid

from . import config

log = logging.getLogger("rules")

OPS = {
    "<": operator.lt, "<=": operator.le, ">": operator.gt,
    ">=": operator.ge, "==": operator.eq, "!=": operator.ne,
}

ACTION_TYPES = ("notify", "set", "mqtt")

EXAMPLES = [
    {
        "name": "АКБ разряжена",
        "when": {"metric": "battery_state_of_charge", "op": "<", "value": 25, "for_s": 60},
        "then": [{"type": "notify", "text": "⚠️ АКБ {battery_state_of_charge}% ({battery_voltage} В)"}],
        "cooldown_s": 1800,
    },
    {
        "name": "PV появилось",
        "when": {"metric": "pv_power", "op": ">", "value": 200, "for_s": 120},
        "then": [{"type": "notify", "text": "☀️ PV {pv_power} Вт, АКБ {battery_state_of_charge}%"}],
        "cooldown_s": 3600,
    },
    {
        "name": "Перегрузка",
        "when": {"metric": "load_percentage", "op": ">", "value": 90, "for_s": 30},
        "then": [{"type": "notify", "text": "🔥 Перегрузка: {load_percentage}% ({load_power} Вт)"},
                 {"type": "mqtt", "topic": "home/alerts/overload", "payload": "ALARM"}],
        "cooldown_s": 300,
    },
]


def _num(v, default=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return default


class RuleError(ValueError):
    pass


class RuleEngine:
    def __init__(self, path: str | None = None, notifier=None):
        self.path = path or config.RULES_FILE
        self.notifier = notifier
        self.rules: list[dict] = []
        self.pending: dict[str, float] = {}      # rule id -> since when condition holds
        self.fired = 0
        self.load()

    # -- storage -------------------------------------------------------------
    def load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                data = json.load(f)
            self.rules = [self._validate(r, generated=False) for r in data.get("rules", [])]
        except FileNotFoundError:
            self.rules = []
        except (OSError, json.JSONDecodeError, RuleError) as ex:
            log.warning("cannot load rules from %s: %r", self.path, ex)
            self.rules = []

    def save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"version": 1, "rules": self.rules}, f, indent=2, ensure_ascii=False)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save rules: %r", ex)

    # -- validation ----------------------------------------------------------
    def _validate(self, rule: dict, generated: bool = True) -> dict:
        if not isinstance(rule, dict):
            raise RuleError("rule must be an object")
        when = rule.get("when") or {}
        metric = when.get("metric")
        if not metric:
            raise RuleError("when.metric is required")
        op = when.get("op", ">")
        if op not in OPS:
            raise RuleError(f"unknown operator {op!r}")
        then = rule.get("then") or []
        if not isinstance(then, list) or not then:
            raise RuleError("then must be a non-empty list")
        actions = []
        for act in then:
            a = dict(act)
            atype = a.get("type")
            if atype not in ACTION_TYPES:
                raise RuleError(f"unknown action type {atype!r}")
            if atype == "set" and not a.get("key"):
                raise RuleError("set action needs key")
            if atype == "mqtt" and not a.get("topic"):
                raise RuleError("mqtt action needs topic")
            if atype == "notify" and not a.get("text"):
                a["text"] = rule.get("name", "rule fired")
            actions.append(a)
        out = {
            "id": rule.get("id") or uuid.uuid4().hex[:8],
            "name": rule.get("name") or f"rule {metric} {op} {when.get('value')}",
            "enabled": bool(rule.get("enabled", True)),
            "when": {
                "metric": metric,
                "op": op,
                "value": when.get("value", 0),
                "for_s": max(0.0, _num(when.get("for_s"), 0.0)),
            },
            "then": actions,
            "cooldown_s": max(0.0, _num(rule.get("cooldown_s"), 300)),
        }
        for key in ("last_fired", "fired_count"):
            if key in rule:
                out[key] = rule[key]
        return out

    # -- crud ----------------------------------------------------------------
    def list(self) -> list[dict]:
        return self.rules

    def get(self, rule_id: str) -> dict | None:
        return next((r for r in self.rules if r["id"] == rule_id), None)

    def add(self, rule: dict) -> dict:
        r = self._validate(rule)
        r.pop("id", None)
        r["id"] = uuid.uuid4().hex[:8]
        self.rules.append(r)
        self.save()
        return r

    def update(self, rule_id: str, rule: dict) -> dict:
        cur = self.get(rule_id)
        if cur is None:
            raise KeyError(rule_id)
        merged = {**cur, **rule, "id": rule_id}
        new = self._validate(merged)
        self.rules = [new if r["id"] == rule_id else r for r in self.rules]
        self.pending.pop(rule_id, None)
        self.save()
        return new

    def delete(self, rule_id: str) -> bool:
        before = len(self.rules)
        self.rules = [r for r in self.rules if r["id"] != rule_id]
        self.pending.pop(rule_id, None)
        if len(self.rules) != before:
            self.save()
            return True
        return False

    def set_enabled(self, rule_id: str, enabled: bool) -> dict:
        return self.update(rule_id, {"enabled": bool(enabled)})

    # -- evaluation ----------------------------------------------------------
    def evaluate(self, state: dict, now: float | None = None) -> list[dict]:
        """Return the rules that must fire now (the caller executes the actions)."""
        if not config.AUTOMATION:
            return []
        now = now or time.time()
        to_fire = []
        for rule in self.rules:
            if not rule.get("enabled", True):
                continue
            when = rule["when"]
            if when["metric"] not in state or state[when["metric"]] is None:
                self.pending.pop(rule["id"], None)
                continue
            current = state[when["metric"]]
            target = when["value"]
            if isinstance(current, str) or isinstance(target, str):
                ok = (str(current) == str(target)) if when["op"] == "==" else \
                     (str(current) != str(target)) if when["op"] == "!=" else False
            else:
                try:
                    ok = OPS[when["op"]](float(current), float(target))
                except (TypeError, ValueError):
                    ok = False
            if not ok:
                self.pending.pop(rule["id"], None)
                continue
            since = self.pending.setdefault(rule["id"], now)
            if now - since < when["for_s"]:
                continue
            last = rule.get("last_fired") or 0
            if last and now - last < rule["cooldown_s"]:
                continue
            to_fire.append(rule)
        return to_fire

    def mark_fired(self, rule: dict, now: float | None = None):
        now = now or time.time()
        rule["last_fired"] = int(now)
        rule["fired_count"] = int(rule.get("fired_count", 0)) + 1
        self.fired += 1
        self.pending.pop(rule["id"], None)
        self.save()

    def reset_pending(self):
        self.pending.clear()

    # -- helpers -------------------------------------------------------------
    @staticmethod
    def render(text: str, state: dict) -> str:
        """Substitute {metric} placeholders (unknown ones are left as is)."""
        out = str(text)
        for key, value in state.items():
            if isinstance(value, (str, int, float)) and f"{{{key}}}" in out:
                if isinstance(value, float):
                    value = f"{value:.1f}".rstrip("0").rstrip(".")
                out = out.replace(f"{{{key}}}", str(value))
        return out
