"""Опрос инвертора и сборка «состояния» (тот же формат, что у сервера).

Модуль без железа: работает через Bus, поэтому опрос проверяется тестами
на CPython с фейковым UART.
"""
import time

import pi30

MODE_TEXT = {
    "P": "Power on",
    "S": "Standby",
    "L": "Line",
    "B": "Battery",
    "F": "Fault",
    "H": "Power saving",
    "D": "Shutdown",
}


def _f(parsed, key):
    val = parsed.get(key)
    return val if isinstance(val, (int, float)) else None


class Poller:
    """Держит актуальное состояние инвертора и счётчики для диагностики."""

    def __init__(self, bus, cfg=None):
        cfg = cfg or {}
        self.bus = bus
        self.state = {}
        self.started = time.time()
        self.last_update = 0
        self.ok_polls = 0
        self.failed_polls = 0
        self.revision = 0
        self.info = {}                 # QPIRI/QID — меняется редко
        self.slow_every_s = cfg.get("poll_slow_s", 60)
        self._last_qmod = 0
        self._last_qpiws = 0
        self._last_qpiri = 0
        self._last_qpigs2 = 0
        self._qid_read = False

    # -- один цикл -----------------------------------------------------------
    def poll_once(self, now=None):
        """QPIGS (быстро) + QMOD/QPIWS/QPIRI/QID/QPIGS2 по расписанию."""
        now = now if now is not None else time.time()
        reply = self.bus.request("QPIGS")
        if not reply:
            self.failed_polls += 1
            return False
        parsed = pi30.parse_qpigs(reply)
        if not parsed:
            self.failed_polls += 1
            return False

        st = dict(parsed)
        st["last_update"] = int(now or time.time())
        pv1 = _f(parsed, "pv_power_1")
        if pv1 is None:
            v, i = _f(parsed, "pv_voltage_1"), _f(parsed, "pv_current_1")
            pv1 = round(v * i) if (v is not None and i is not None) else None
        pv2 = _f(self.state, "pv_power_2")
        st["pv_power"] = (pv1 or 0) + (pv2 or 0) if (pv1 is not None or pv2 is not None) else None
        chg, dis = _f(parsed, "battery_charge_current"), _f(parsed, "battery_discharge_current")
        bv = _f(parsed, "battery_voltage")
        if chg is not None or dis is not None:
            cur = (chg or 0) - (dis or 0)
            st["battery_current"] = cur
            if bv is not None:
                st["battery_power"] = round(bv * cur)
        if parsed.get("status_flags"):
            st["warnings"] = ", ".join(parsed["status_flags"])
        st["warning_bits"] = parsed.get("status_bits", 0)

        # --- медленные команды ---------------------------------------------
        if now - self._last_qmod >= 5 or not self.state.get("device_mode"):
            self._last_qmod = now
            reply = self.bus.request("QMOD")
            mode = pi30.parse_qmod(reply).get("device_mode") if reply else None
            if mode:
                st["device_mode"] = mode
                st["device_mode_text"] = MODE_TEXT.get(mode, mode)
        else:
            st["device_mode"] = self.state.get("device_mode")
            st["device_mode_text"] = self.state.get("device_mode_text")

        if now - self._last_qpiws >= 10 or "warning_bits" not in self.state:
            self._last_qpiws = now
            reply = self.bus.request("QPIWS")
            ws = pi30.parse_qpiws(reply) if reply else {}
            if ws:
                st["warning_bits"] = ws.get("warning_bits", st.get("warning_bits"))
                if ws.get("warnings"):
                    st["warnings"] = ", ".join(ws["warnings"])
                    st["warnings_list"] = ws["warnings"]

        if now - self._last_qpigs2 >= 30:
            self._last_qpigs2 = now
            reply = self.bus.request("QPIGS2", attempts=1)
            if reply:
                second = pi30.parse_qpigs2(reply)
                for key in ("pv_power_2", "pv_voltage_2", "pv_current_2"):
                    if second.get(key) is not None:
                        st[key] = second[key]

        if now - self._last_qpiri >= self.slow_every_s or not self.info:
            self._last_qpiri = now
            from sethandler import read_status          # локально: без циклов импорта
            full = read_status(self.bus)
            if full:
                self.info = dict(full)
        for key, val in (self.info or {}).items():
            st.setdefault(key, val)

        if not self._qid_read:
            reply = self.bus.request("QID", attempts=1)
            qid = pi30.parse_qid(reply) if reply else {}
            if qid.get("serial_number"):
                self.info["serial_number"] = qid["serial_number"]
                st["serial_number"] = qid["serial_number"]
                self._qid_read = True
        if "serial_number" in (self.info or {}):
            st["serial_number"] = self.info["serial_number"]

        self.state = st
        self.last_update = time.time()
        self.ok_polls += 1
        self.revision += 1
        return True

    # -- диагностика ---------------------------------------------------------
    def health(self):
        age = time.time() - self.last_update if self.last_update else None
        return {
            "ok": self.failed_polls == 0 and bool(self.last_update),
            "online": age is not None and age < 30,
            "age_s": round(age, 1) if age is not None else None,
            "uptime_s": int(time.time() - self.started),
            "ok_polls": self.ok_polls,
            "failed_polls": self.failed_polls,
            "rx": self.bus.rx,
            "tx": self.bus.tx,
            "errors": self.bus.errors,
            "last_error": self.bus.last_error,
        }
