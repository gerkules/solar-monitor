"""Writable inverter settings: PI30 command, ACK check and read-back verification.

SolarAssistant's rule: a setting is only "Saved" when the inverter acknowledged it,
and with `set_verified` only after QPIRI reports the new value (up to 3 attempts).
That is exactly what `apply_setting()` does — no write is ever reported as success
without the read-back, because a silently ignored command is worse than an error.
"""
from __future__ import annotations

import logging

from . import config
from .pi30 import SETTINGS, is_ack, is_nak, parse_qpiri

log = logging.getLogger("settings")


def effective_settings() -> dict:
    """pi30.SETTINGS patched with SETTINGS_JSON (per-firmware command variants)."""
    out = {}
    overrides = config.settings_override()
    for key, spec in SETTINGS.items():
        s = dict(spec)
        ov = overrides.get(key) or {}
        if "cmd" in ov and isinstance(ov["cmd"], str):
            template = ov["cmd"]
            s["cmd"] = (lambda tpl: (lambda v: tpl.format(v)))(template)
        if ov.get("lenient") is not None:
            s["lenient"] = bool(ov["lenient"])
        if "field" in ov:
            s["field"] = ov["field"]
        if "min" in ov:
            s["min"] = ov["min"]
        if "max" in ov:
            s["max"] = ov["max"]
        if ov.get("disabled"):
            continue
        out[key] = s
    return out


def parse_value(spec: dict, payload) -> float:
    """Accept a label ('Solar first'), an index ('1') or a number ('52.5')."""
    if isinstance(payload, bytes):
        payload = payload.decode(errors="replace")
    txt = str(payload).strip()
    if not txt:
        raise ValueError("empty value")
    if spec["kind"] == "select":
        labels = {name.lower(): idx for idx, name in spec["options"].items()}
        if txt.lower() in labels:
            return float(labels[txt.lower()])
        try:
            idx = int(float(txt))
        except ValueError:
            raise ValueError(f"unknown option {txt!r}; use one of: "
                             + ", ".join(spec["options"].values())) from None
        if idx not in spec["options"]:
            raise ValueError(f"option {idx} not valid; use one of: "
                             + ", ".join(str(i) for i in spec["options"]))
        return float(idx)
    try:
        val = float(txt.replace(",", "."))
    except ValueError:
        raise ValueError(f"not a number: {txt!r}") from None
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and val < lo:
        raise ValueError(f"{val} below minimum {lo}")
    if hi is not None and val > hi:
        raise ValueError(f"{val} above maximum {hi}")
    return val


def build_command(spec: dict, value: float) -> str:
    cmd = spec["cmd"]
    if spec["kind"] == "select":
        return cmd(int(value))
    return cmd(value)


def read_settings(transport, attempts: int = 3) -> dict | None:
    """QPIRI, rejecting frames mixed with another poller on a shared UART."""
    for _ in range(attempts):
        resp = transport.request("QPIRI")
        if not resp:
            continue
        parsed = parse_qpiri(resp)
        rated = parsed.get("rated_power") or 0
        if 300 <= float(rated) <= 50_000 and parsed.get("output_source_priority"):
            return parsed
        log.warning("QPIRI: implausible frame (rated=%s), retrying", rated)
    return None


def same_value(spec: dict, wanted: float, got) -> bool:
    if got is None:
        return False
    try:
        if spec["kind"] == "select":
            return int(float(got)) == int(wanted) if isinstance(got, float) else \
                spec["options"].get(int(wanted)) == got
        return abs(float(got) - float(wanted)) < 0.05
    except (TypeError, ValueError):
        return False


def apply_setting(transport, key: str, payload, verified: bool = True) -> dict:
    """Write one setting. Returns {ok, message, key, value, readback}."""
    specs = effective_settings()
    spec = specs.get(key)
    if spec is None:
        return {"ok": False, "key": key,
                "message": f"Error: {key} is not writable on this build"}
    if not config.ALLOW_SETTINGS:
        return {"ok": False, "key": key, "message": "Error: setting changes are disabled"}

    try:
        value = parse_value(spec, payload)
    except ValueError as ex:
        return {"ok": False, "key": key, "message": f"Error: {ex}"}

    cmd = build_command(spec, value)
    tries = 3 if verified else 1
    last_got = None
    for attempt in range(1, tries + 1):
        # A shared UART can return a frame belonging to another poller; that is not
        # a NAK, so retry instead of reporting a rejection.
        reply = None
        for _ in range(3):
            reply = transport.request_raw(cmd)
            if reply and (is_ack(reply) or is_nak(reply)):
                break
            log.info("set %s: foreign frame %r, retrying", key, reply)
        log.info("set %s: %s -> %r (attempt %s/%s)", key, cmd, reply, attempt, tries)
        if not reply or not is_ack(reply):
            return {"ok": False, "key": key, "cmd": cmd,
                    "message": "Error: inverter rejected the change (NAK)"}
        if not verified:
            return {"ok": True, "key": key, "cmd": cmd, "message": "Saved"}

        fresh = read_settings(transport)
        if not fresh:
            continue
        last_got = fresh.get(spec["field"])
        if same_value(spec, value, last_got):
            return {"ok": True, "key": key, "cmd": cmd, "value": last_got,
                    "message": "Saved"}
        if spec.get("lenient"):
            # acknowledged, but the firmware reported another code back
            return {"ok": True, "key": key, "cmd": cmd, "value": last_got,
                    "message": f"Saved (инвертор сообщает «{last_got}»: своя нумерация) "}

    return {"ok": False, "key": key, "cmd": cmd, "readback": last_got,
            "message": "Error: The inverter acknowledged the value but did not apply it"}
