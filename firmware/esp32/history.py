"""Кольцевой буфер истории в RAM: последние N точек, без записи во flash.

Пишем не чаще раза в минуту (по умолчанию): за сутки это 1440 точек по 6 чисел —
около 30 КБ, что нормально для ESP32/C3. Данные теряются при перезагрузке, зато
флеш не изнашивается и ничего не corruption-ится при отключении питания.
"""
import time


class History:
    def __init__(self, keep=1440, interval_s=60):
        self.keep = keep
        self.interval_s = interval_s
        self.t = []
        self.pv = []
        self.load = []
        self.grid = []
        self.batt_v = []
        self.soc = []
        self._last = 0

    def maybe_add(self, state, now=None):
        now = now if now is not None else time.time()
        if now - self._last < self.interval_s:
            return False
        self._last = now
        self.t.append(int(now))
        self.pv.append(round(state.get("pv_power") or 0))
        self.load.append(round(state.get("load_power") or 0))
        self.grid.append(round(state.get("grid_power") or 0))
        self.batt_v.append(round(state.get("battery_voltage") or 0, 2))
        self.soc.append(round(state.get("battery_state_of_charge") or 0))
        if len(self.t) > self.keep:
            for arr in (self.t, self.pv, self.load, self.grid, self.batt_v, self.soc):
                del arr[0]
        return True

    def as_dict(self, limit=None):
        n = len(self.t)
        start = 0 if not limit else max(0, n - limit)
        return {
            "interval_s": self.interval_s,
            "columns": ["t", "pv_power", "load_power", "grid_power", "battery_voltage",
                        "battery_soc"],
            "rows": [[self.t[i], self.pv[i], self.load[i], self.grid[i],
                      self.batt_v[i], self.soc[i]] for i in range(start, n)],
        }

    def summary(self):
        if not self.t:
            return {"points": 0}
        return {
            "points": len(self.t),
            "from": self.t[0],
            "to": self.t[-1],
            "pv_max": max(self.pv),
            "load_max": max(self.load),
            "pv_energy_kwh": round(sum(self.pv) * self.interval_s / 3600 / 1000, 2),
            "load_energy_kwh": round(sum(self.load) * self.interval_s / 3600 / 1000, 2),
        }
