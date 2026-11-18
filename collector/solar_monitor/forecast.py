"""PV forecast from forecast.solar (free tier): future watts + kWh for today.

Points are written to InfluxDB as the `pv_power_forecast` measurement with their
own (future) timestamps, so Grafana or the UI can overlay prediction vs reality.
"""
from __future__ import annotations

import json
import logging
import os
import time
import urllib.error
import urllib.request

from . import config

log = logging.getLogger("forecast")

API = "https://api.forecast.solar/estimate/{lat}/{lon}/{decl}/{az}/{kwp}"


class ForecastService:
    def __init__(self, poller=None, influx=None, mqtt=None):
        self.poller = poller
        self.influx = influx
        self.mqtt = mqtt
        self.points: list[list] = []
        self.today_kwh: float | None = None
        self.updated: int | None = None
        self.errors = 0
        self.last_error: str | None = None
        self.retry_after = 0.0
        self._load_cache()

    @property
    def enabled(self) -> bool:
        return bool(config.FORECAST_ENABLED and config.FORECAST_LAT
                    and config.FORECAST_LON and config.FORECAST_KWP)

    # -- cache ---------------------------------------------------------------
    def _load_cache(self):
        """Последний удачный прогноз переживает перезапуск контейнера.

        Бесплатный forecast.solar разрешает ~12 запросов в час на IP, поэтому
        рестарт не должен превращаться в новый запрос.
        """
        try:
            with open(config.FORECAST_CACHE_FILE, encoding="utf-8") as f:
                data = json.load(f)
            self.points = [[int(p[0]), float(p[1])] for p in data.get("points", [])]
            self.today_kwh = data.get("today_kwh")
            self.updated = data.get("updated")
            if self.points:
                log.info("forecast: loaded %s cached points (%s)",
                         len(self.points), data.get("updated"))
        except FileNotFoundError:
            pass
        except (OSError, json.JSONDecodeError, TypeError, ValueError) as ex:
            log.warning("forecast: cannot read cache: %r", ex)

    def _save_cache(self):
        try:
            os.makedirs(os.path.dirname(config.FORECAST_CACHE_FILE) or ".", exist_ok=True)
            tmp = config.FORECAST_CACHE_FILE + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump({"points": self.points, "today_kwh": self.today_kwh,
                           "updated": self.updated}, f)
            os.replace(tmp, config.FORECAST_CACHE_FILE)
        except OSError as ex:
            log.warning("forecast: cannot save cache: %r", ex)

    def url(self) -> str:
        return API.format(lat=config.FORECAST_LAT, lon=config.FORECAST_LON,
                          decl=config.FORECAST_DECLINATION, az=config.FORECAST_AZIMUTH,
                          kwp=config.FORECAST_KWP)

    def fetch(self, force: bool = False) -> bool:
        if not self.enabled:
            return False
        now = time.time()
        if not force and self.retry_after and now < self.retry_after:
            log.info("forecast: waiting until %s (rate limit)",
                     time.strftime("%H:%M", time.localtime(self.retry_after)))
            return False
        if not force and self.updated and now - self.updated < min(600, config.FORECAST_INTERVAL):
            return True          # свежий кеш, лишний запрос не нужен
        try:
            req = urllib.request.Request(self.url(), headers={"User-Agent": "solar-monitor/1.0"})
            with urllib.request.urlopen(req, timeout=20) as resp:
                data = json.loads(resp.read().decode())
        except urllib.error.HTTPError as ex:
            self.errors += 1
            self.last_error = repr(ex)
            if ex.code == 429:
                # бесплатный тариф: 12 запросов/час на IP -> ждём и не долбим
                self.retry_after = now + 1800
                log.warning("forecast: rate limited (429), retry in 30 min")
            else:
                self.retry_after = now + 300
                log.warning("forecast fetch failed: %r", ex)
            return False
        except (OSError, json.JSONDecodeError) as ex:   # URLError/TimeoutError are OSErrors
            self.errors += 1
            self.last_error = repr(ex)
            self.retry_after = now + 300
            log.warning("forecast fetch failed: %r", ex)
            return False

        result = data.get("result") or {}
        watts = result.get("watts") or {}
        points = []
        for stamp, value in watts.items():
            try:
                ts = time.mktime(time.strptime(stamp, "%Y-%m-%d %H:%M:%S")) - time.timezone
            except ValueError:
                continue
            points.append([int(ts), round(float(value), 1)])
        points.sort(key=lambda p: p[0])
        self.points = points
        self.updated = int(time.time())

        days = result.get("watt_hours_day") or {}
        today = time.strftime("%Y-%m-%d")
        self.today_kwh = round(float(days.get(today, 0)) / 1000.0, 2) if days else None

        if self.influx is not None and points:
            self.influx.write_series("pv_power_forecast", points)
        if self.mqtt is not None:
            self.mqtt.publish(f"{config.MQTT_PREFIX}/forecast/pv_power_today",
                              self.today_kwh if self.today_kwh is not None else "", retain=True)
        if self.poller is not None:
            if self.today_kwh is not None:
                self.poller.state["pv_forecast_today"] = self.today_kwh
            now = int(time.time())
            upcoming = [p for p in points if p[0] >= now]
            if upcoming:
                self.poller.state["pv_forecast_now"] = upcoming[0][1]
        self._save_cache()
        log.info("forecast: %s points, today %s kWh", len(points), self.today_kwh)
        return True

    def run(self):
        if not self.enabled:
            log.info("forecast disabled (set FORECAST_ENABLED + FORECAST_LAT/LON/KWP)")
            return
        while True:
            self.fetch()
            if self.retry_after:
                # 429: спим до окна повтора, иначе — обычный интервал
                delay = max(60.0, min(self.retry_after - time.time(),
                                      max(300.0, config.FORECAST_INTERVAL)))
            else:
                delay = max(300.0, config.FORECAST_INTERVAL)
            time.sleep(delay)

    def snapshot(self) -> dict:
        return {
            "enabled": self.enabled,
            "updated": self.updated,
            "today_kwh": self.today_kwh,
            "points": self.points,
            "url": self.url() if self.enabled else None,
            "errors": self.errors,
            "last_error": self.last_error,
        }
