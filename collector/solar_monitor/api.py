"""HTTP API (stdlib only): health, instant state, settings write, history.

Mirrors the SolarAssistant REST API shape (/api/v1/metrics, /api/v1/history) so a
UI or a script written for SA keeps working, and adds /api/v1/settings for the
full settings write path.
"""
from __future__ import annotations

import csv
import io
import json
import time
import logging
import re
import urllib.parse
import urllib.request
from typing import Optional
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

from . import config, publishers
from .pi30 import INFO_METRICS, METRICS, SETTINGS

log = logging.getLogger("api")

HISTORY_MIN_GROUP = 10  # seconds


def _glob_match(topic: str, pattern: str) -> bool:
    regex = "^" + re.escape(pattern).replace(r"\*", ".*").replace(r"\?", ".") + "$"
    return re.match(regex, topic) is not None


def metrics_list(state: dict, pattern: str | None = None) -> list[dict]:
    out = []
    for key, (name, unit, *_rest) in METRICS.items():
        topic = f"inverter_1/{key}"
        if pattern and not _glob_match(topic, pattern):
            continue
        if key not in state:
            continue
        out.append({"topic": topic, "group": "Status", "name": name,
                    "value": state[key], "unit": unit})
    for key, (name, unit) in INFO_METRICS.items():
        topic = f"inverter_1/{key}"
        if pattern and not _glob_match(topic, pattern):
            continue
        if key in state:
            out.append({"topic": topic, "group": "Settings", "name": name,
                        "value": state[key], "unit": unit})
    for key, spec in SETTINGS.items():
        topic = f"inverter_1/{key}"
        if pattern and not _glob_match(topic, pattern):
            continue
        if key in state:
            out.append({"topic": topic, "group": "Settings", "name": spec["name"],
                        "value": state[key], "unit": spec.get("unit")})
    return out


def settings_schema(state: dict) -> list[dict]:
    out = []
    for key, spec in SETTINGS.items():
        ent = {"key": key, "name": spec["name"], "kind": spec["kind"],
               "value": state.get(key), "writable": config.ALLOW_SETTINGS}
        if spec["kind"] == "select":
            ent["options"] = [{"value": v, "label": n} for v, n in spec["options"].items()]
        else:
            ent.update({"min": spec["min"], "max": spec["max"],
                        "step": spec["step"], "unit": spec.get("unit")})
        out.append(ent)
    return out


def _history_enabled() -> bool:
    if config.INFLUX_MODE.startswith("1"):
        return bool(config.INFLUX_URL)
    return bool(config.INFLUX_TOKEN)


def influxql_history(topic: str, start: str, stop: str, group_by: str, agg: str,
                     site: Optional[str] = None) -> dict:
    """InfluxDB 1.x path: SELECT ... GROUP BY time(<bucket>)."""
    measurement = topic.split("/")[-1]
    fn = {"mean": "mean", "max": "max", "min": "min", "sum": "sum", "last": "last"}.get(agg, "mean")
    q = (f'SELECT {fn}("value") AS "value" FROM "{measurement}" '
         f'WHERE "site" = \'{site or config.SITE}\' AND time >= \'{start}\' AND time <= \'{stop}\' '
         f'GROUP BY time({group_by}) fill(none)')
    url = (config.INFLUX_URL.rstrip("/") + "/query?db=" + urllib.parse.quote(config.INFLUX_DB)
           + "&epoch=ms&q=" + urllib.parse.quote(q))
    req = urllib.request.Request(url)
    if config.INFLUX_AUTH:
        import base64
        req.add_header("Authorization",
                       "Basic " + base64.b64encode(config.INFLUX_AUTH.encode()).decode())
    points = []
    with urllib.request.urlopen(req, timeout=10) as resp:
        data = json.loads(resp.read().decode())
    for result in data.get("results", []):
        for series in result.get("series", []) or []:
            for ts, val in series.get("values", []):
                if val is None:
                    continue
                points.append([time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(ts / 1000.0)), val])
    return {"topic": topic, "group_by": group_by, "agg": agg,
            "from": start, "to": stop, "points": points}


def flux_history(topic: str, start: str, stop: str, group_by: str, agg: str,
                 site: Optional[str] = None) -> dict:
    measurement = topic.split("/")[-1]
    fn = {"mean": "mean", "max": "max", "min": "min", "sum": "sum", "last": "last"}.get(agg, "mean")
    flux = (
        f'from(bucket: "{config.INFLUX_BUCKET}")\n'
        f'  |> range(start: {start}, stop: {stop})\n'
        f'  |> filter(fn: (r) => r._measurement == "{measurement}" and r.site == "{site or config.SITE}")\n'
        f'  |> aggregateWindow(every: {group_by}, fn: {fn}, createEmpty: false)\n'
        f'  |> keep(columns: ["_time", "_value"])\n'
    )
    url = (config.INFLUX_URL.rstrip("/") + "/api/v2/query?org="
           + urllib.parse.quote(config.INFLUX_ORG))
    body = json.dumps({"query": flux, "type": "flux"}).encode()
    req = urllib.request.Request(url, data=body, method="POST")
    req.add_header("Authorization", f"Token {config.INFLUX_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/csv")
    points = []
    with urllib.request.urlopen(req, timeout=10) as resp:
        reader = csv.DictReader(io.StringIO(resp.read().decode()))
        for row in reader:
            if not row.get("_value"):
                continue
            try:
                points.append([row["_time"], float(row["_value"])])
            except ValueError:
                continue
    return {"topic": topic, "group_by": group_by, "agg": agg,
            "from": start, "to": stop, "points": points}


class Handler(BaseHTTPRequestHandler):
    poller = None            # injected in make_server()
    server_version = "solar-monitor/1.0"

    # -- helpers -------------------------------------------------------------
    def _json(self, obj, code: int = 200):
        body = json.dumps(obj, default=str).encode()
        self.send_response(code)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()
        self.wfile.write(body)

    def _text(self, txt: str, code: int = 200):
        body = str(txt).encode()
        self.send_response(code)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _authorized(self) -> bool:
        token = getattr(config, "API_TOKEN", None)
        if not token:
            return True
        header = self.headers.get("Authorization", "")
        return header == f"Bearer {token}"

    def log_message(self, fmt, *args):  # quieter access log
        log.debug("%s - %s", self.address_string(), fmt % args)

    # -- routes --------------------------------------------------------------
    def do_GET(self):
        url = urllib.parse.urlparse(self.path)
        q = urllib.parse.parse_qs(url.query)
        path = url.path.rstrip("/") or "/"

        if path == "/healthz":
            h = self.poller.health()
            return self._json(h, 200 if h["ok"] else 503)

        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)

        if path in ("/", "/api", "/api/v1"):
            return self._json({
                "service": "solar-monitor", "site": config.SITE,
                "transport": self.poller.transport.describe(),
                "endpoints": ["/healthz", "/api/v1/state", "/api/v1/metrics",
                              "/api/v1/settings", "/api/v1/history", "/api/v1/info"],
            })

        if path in ("/api/v1/state", "/api/state"):
            return self._json(self.poller.snapshot())

        if path == "/api/v1/info":
            return self._json(self.poller.health())

        if path == "/api/v1/metrics":
            pattern = q.get("topic", [None])[0]
            state = self.poller.snapshot()
            items = metrics_list(state, pattern)
            if q.get("value", ["0"])[0] in ("1", "true", "yes") and len(items) == 1:
                return self._text(items[0]["value"])
            return self._json(items)

        if path == "/api/v1/settings":
            return self._json(settings_schema(self.poller.snapshot()))

        if path == "/api/v1/history":
            topic = q.get("topic", [None])[0]
            if not topic:
                return self._json({"error": "topic is required"}, 400)
            if not _history_enabled():
                return self._json({"error": "history needs InfluxDB configured"}, 501)
            group_by = q.get("group_by", ["1m"])[0]
            agg = q.get("agg", ["mean"])[0]
            start = q.get("from", ["-1d"])[0]
            stop = q.get("to", ["now()"])[0]
            try:
                if config.INFLUX_MODE.startswith("1"):
                    now = time.time()
                    if start.startswith("20"):
                        start = start.replace("T", " ").replace("Z", "")
                    else:
                        start = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - 86400))
                    if stop.startswith("20"):
                        stop = stop.replace("T", " ").replace("Z", "")
                    else:
                        stop = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
                    return self._json(influxql_history(topic, start, stop, group_by, agg))
                # RFC3339 -> Flux time literal
                start = f'"{start}"' if start.startswith("20") else start
                stop = f'"{stop}"' if stop.startswith("20") else stop
                return self._json(flux_history(topic, start, stop, group_by, agg))
            except Exception as ex:  # noqa: BLE001
                return self._json({"error": str(ex)}, 502)

        return self._json({"error": "not found"}, 404)

    def do_POST(self):
        url = urllib.parse.urlparse(self.path)
        path = url.path.rstrip("/")
        if not self._authorized():
            return self._json({"error": "unauthorized"}, 401)
        length = int(self.headers.get("Content-Length") or 0)
        try:
            body = json.loads(self.rfile.read(length) or b"{}")
        except json.JSONDecodeError:
            return self._json({"error": "invalid json"}, 400)

        if path in ("/api/v1/settings", "/api/v1/settings/set"):
            key = body.get("key")
            if not key:
                return self._json({"error": "key is required"}, 400)
            result = self.poller.submit_set(key, body.get("value"),
                                            bool(body.get("verified", True)))
            return self._json(result, 200 if result.get("ok") else 422)

        if path == "/api/v1/reload_settings":
            result = self.poller.submit_set("reload_settings", None, False)
            return self._json(result, 200 if result.get("ok") else 422)

        return self._json({"error": "not found"}, 404)


def make_server(poller, host: str = "0.0.0.0", port: int = 8080) -> ThreadingHTTPServer:
    Handler.poller = poller
    return ThreadingHTTPServer((host, port), Handler)
