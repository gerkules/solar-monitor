"""FastAPI web app: SolarAssistant-style UI + JSON API + SSE live stream.

Serves the SPA from web/static and keeps the JSON API that api.py exposed
(/api/v1/state, /metrics, /settings, /history) plus /api/v1/energy and
/api/v1/stream for the frontend.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
from typing import Optional

from fastapi import FastAPI, Query, Request
from fastapi.responses import HTMLResponse, JSONResponse, Response, StreamingResponse
from fastapi.staticfiles import StaticFiles

from . import api, config, publishers
from .pi30 import INFO_METRICS, METRICS, SETTINGS

STATIC_DIR = os.path.join(os.path.dirname(__file__), "web", "static")
# Версия статики: меняется при каждом старте контейнера, чтобы браузер не держал
# старый app.js/styles.css после обновления.
ASSET_V = str(int(time.time()))
INDEX = os.path.join(STATIC_DIR, "index.html")

ENERGY_SOURCES = {
    "pv": "pv_power",
    "load": "load_power",
    "grid": "grid_power",
    "battery_charge": "battery_power",
    "battery_discharge": "battery_power",
}


def _authorized(request: Request) -> bool:
    if not config.API_TOKEN:
        return True
    header = request.headers.get("Authorization", "")
    if header == f"Bearer {config.API_TOKEN}":
        return True
    return request.query_params.get("token") == config.API_TOKEN


def _flux_energy(start: str, stop: str, site: Optional[str] = None) -> dict:
    """kWh per source between two Flux times (mean(W) per 1h bucket -> kWh)."""
    meas = " or ".join(f'r._measurement == "{m}"' for m in
                       ("pv_power", "load_power", "grid_power", "battery_power"))
    flux = (
        f'from(bucket: "{config.INFLUX_BUCKET}")\n'
        f'  |> range(start: {start}, stop: {stop})\n'
        f'  |> filter(fn: (r) => r["site"] == "{site or config.SITE}" and ({meas}))\n'
        f'  |> filter(fn: (r) => r["_field"] == "value")\n'
        f'  |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)\n'
        f'  |> sum()\n'
        f'  |> keep(columns: ["_measurement", "_value"])\n'
    )
    import urllib.parse
    import urllib.request
    url = (config.INFLUX_URL.rstrip("/") + "/api/v2/query?org="
           + urllib.parse.quote(config.INFLUX_ORG))
    req = urllib.request.Request(url, data=json.dumps({"query": flux, "type": "flux"}).encode(),
                                 method="POST")
    req.add_header("Authorization", f"Token {config.INFLUX_TOKEN}")
    req.add_header("Content-Type", "application/json")
    req.add_header("Accept", "application/csv")
    rows = {}
    with urllib.request.urlopen(req, timeout=15) as resp:
        text = resp.read().decode()
    header = None
    for line in text.splitlines():
        if line.startswith("#") or not line.strip():
            continue
        cells = line.split(",")
        if header is None:
            header = cells
            continue
        row = dict(zip(header, cells))
        m, v = row.get("_measurement"), row.get("_value")
        if not m or v in (None, ""):
            continue
        try:
            rows[m] = float(v) * 0.001      # mean W over 1 h -> kWh
        except ValueError:
            pass
    out = {
        "pv": rows.get("pv_power", 0.0),
        "load": rows.get("load_power", 0.0),
        "grid": rows.get("grid_power", 0.0),
    }
    # battery_power is signed (+charge / -discharge): split it by sign
    out["battery_charge"] = 0.0
    out["battery_discharge"] = 0.0
    return {k: round(v, 3) for k, v in out.items()}


class _SiteSource:
    """Minimal poller-like wrapper so SSE can stream any site from the registry."""

    def __init__(self, registry, local_poller, site: str | None):
        self.registry = registry
        self.local = local_poller
        self.site = site

    def snapshot(self):
        return self.registry.get(self.site) or self.local.snapshot()


def sse_stream(poller, interval: float = 1.5, max_events: int | None = None):
    """Server-sent events: one frame per state change (or a keepalive comment)."""
    last = None
    sent = 0
    while True:
        snap = poller.snapshot()
        payload = json.dumps(snap, default=str)
        if payload != last:
            last = payload
            sent += 1
            yield f"event: state\ndata: {payload}\n\n"
            if max_events and sent >= max_events:
                return
        else:
            yield ": keepalive\n\n"
        time.sleep(interval)


class _Described:
    """Транспорт-заглушка: у источника-импорта нет своего транспорта, но описание нужно."""

    def __init__(self, text: str):
        self.text = text

    def describe(self) -> str:
        return self.text


def create_app(poller, notifier=None, rules=None, forecast_svc=None, sites=None,
               battery=None, connection_store=None, auth_store=None) -> FastAPI:
    app = FastAPI(title="solar-monitor", docs_url="/api/docs", redoc_url=None,
                  openapi_url="/api/openapi.json")
    auth_on = bool((config.AUTH_USER and config.AUTH_PASSWORD)
                   or (auth_store is not None and auth_store.info()["source"] == "file"))

    @app.middleware("http")
    async def peer_proxy(request: Request, call_next):
        """`?site=<peer>` — запрос уходит на API другого сайта (у него свой транспорт
        и свои уставки). Так один UI управляет несколькими инверторами."""
        site = request.query_params.get("site")
        peer = config.PEER_SITES.get(site) if site and site != config.SITE else None
        base = peer.get("url") if isinstance(peer, dict) else peer
        if base and request.url.path.startswith("/api/v1/"):
            import urllib.error
            import urllib.parse
            import urllib.request
            from starlette.concurrency import run_in_threadpool

            url = base.rstrip("/") + request.url.path
            pairs = [(k, v) for k, v in request.query_params.multi_items() if k != "site"]
            if pairs:
                url += "?" + urllib.parse.urlencode(pairs)
            body = await request.body()
            headers = {k: v for k, v in request.headers.items()
                       if k.lower() in ("content-type", "authorization")}

            def _do():
                req = urllib.request.Request(url, data=body or None,
                                             method=request.method, headers=headers)
                # у соседа могут быть свои Basic-креды (или self-signed сертификат)
                if isinstance(peer, dict) and peer.get("user"):
                    import base64
                    cred = base64.b64encode(
                        f"{peer['user']}:{peer.get('pass', '')}".encode()).decode()
                    req.add_header("Authorization", f"Basic {cred}")
                ctx = None
                if url.startswith("https") and not config.PEER_TLS_VERIFY:
                    import ssl
                    ctx = ssl._create_unverified_context()
                try:
                    kwargs = {"timeout": 20}
                    if ctx is not None:
                        kwargs["context"] = ctx
                    with urllib.request.urlopen(req, **kwargs) as resp:
                        return resp.status, resp.read(), resp.headers.get("Content-Type")
                except urllib.error.HTTPError as err:
                    return err.code, err.read(), None
                except Exception as err:  # noqa: BLE001
                    return 502, json.dumps({"error": f"{site}: {err!r}"}).encode(), "application/json"

            status, payload, ctype = await run_in_threadpool(_do)
            return Response(payload, status_code=status,
                            media_type=(ctype or "application/json").split(";")[0])
        return await call_next(request)

    @app.middleware("http")
    async def basic_auth(request: Request, call_next):
        """Optional HTTP Basic auth for UI + API (except /healthz for docker)."""
        if not auth_on or request.url.path == "/healthz":
            return await call_next(request)
        header = request.headers.get("Authorization", "")
        if header.startswith("Bearer "):
            if config.API_TOKEN and header[7:] == config.API_TOKEN:
                return await call_next(request)
        if header.startswith("Basic "):
            import base64
            try:
                user, _, pwd = base64.b64decode(header[6:]).decode().partition(":")
            except Exception:  # noqa: BLE001
                user = pwd = ""
            # если пароль меняли в UI — .env больше не действует (иначе старый пароль жив)
            override = auth_store is not None and auth_store.info()["source"] == "file"
            if override:
                if auth_store.check(user, pwd):
                    return await call_next(request)
            elif user == config.AUTH_USER and pwd == config.AUTH_PASSWORD:
                return await call_next(request)
        return JSONResponse({"error": "unauthorized"}, status_code=401,
                            headers={"WWW-Authenticate": 'Basic realm="solar-monitor"'})
    app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

    @app.get("/healthz")
    def healthz():
        h = poller.health()
        return JSONResponse(h, status_code=200 if h["ok"] else 503)

    @app.get("/api/v1/sites")
    def sites_api():
        if sites is None:
            return [{"site": config.SITE, "online": True}]
        return sites.sites()

    @app.get("/api/v1/state")
    def state(request: Request, site: Optional[str] = None):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if sites is None or (site in (None, "", config.SITE)):
            return poller.snapshot()
        snap = sites.get(site)
        if snap is None:
            return JSONResponse({"error": f"unknown site {site}"}, status_code=404)
        return snap

    @app.get("/api/v1/info")
    def info():
        return poller.health()

    @app.get("/api/v1/metrics")
    def metrics(request: Request, topic: Optional[str] = None, value: int = 0):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        items = api.metrics_list(poller.snapshot(), topic)
        if value and len(items) == 1:
            from fastapi.responses import PlainTextResponse
            return PlainTextResponse(str(items[0]["value"]))
        return items

    @app.get("/api/v1/settings")
    def get_settings():
        return api.settings_schema(poller.snapshot())

    @app.post("/api/v1/settings")
    async def set_setting(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        key = body.get("key")
        if not key:
            return JSONResponse({"error": "key is required"}, status_code=400)
        result = poller.submit_set(key, body.get("value"), bool(body.get("verified", True)))
        return JSONResponse(result, status_code=200 if result.get("ok") else 422)

    @app.post("/api/v1/reload_settings")
    def reload_settings():
        result = poller.submit_set("reload_settings", None, False)
        return JSONResponse(result, status_code=200 if result.get("ok") else 422)

    @app.get("/api/v1/history")
    def history(request: Request, topic: str = Query(...),
                frm: str = Query("-1d", alias="from"), to: str = Query("now()"),
                group_by: str = Query("1m"), agg: str = Query("mean"),
                site: Optional[str] = None):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not api._history_enabled():
            return JSONResponse({"error": "history needs InfluxDB configured"}, status_code=501)
        try:
            if config.INFLUX_MODE.startswith("1"):
                now = time.time()
                start = frm if frm.startswith("20") else time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.gmtime(now - _rel_seconds(frm)))
                stop = to if to.startswith("20") else time.strftime(
                    "%Y-%m-%d %H:%M:%S", time.gmtime(now))
                start = start.replace("T", " ").replace("Z", "")
                stop = stop.replace("T", " ").replace("Z", "")
                return api.influxql_history(topic, start, stop, group_by, agg, site)
            return api.flux_history(topic, frm, to, group_by, agg, site)
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"error": str(ex)}, status_code=502)

    @app.get("/api/v1/energy")
    def energy(request: Request, frm: str = Query("-1d", alias="from"),
               to: str = Query("now()"), site: Optional[str] = None):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if config.INFLUX_MODE.startswith("1"):
            return JSONResponse({"error": "energy totals need InfluxDB 2.x"}, status_code=501)
        try:
            return _flux_energy(frm, to, site)
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"error": str(ex)}, status_code=502)

    @app.get("/api/v1/stream")
    def stream(request: Request, events: int = 0, site: Optional[str] = None):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        source = poller if sites is None else _SiteSource(sites, poller, site)
        return StreamingResponse(sse_stream(source, max_events=events or None),
                                 media_type="text/event-stream",
                                 headers={"Cache-Control": "no-cache",
                                          "X-Accel-Buffering": "no"})

    @app.get("/api/v1/export")
    def export(request: Request, metric: str = Query(...), frm: str = Query("-24h", alias="from"),
               to: str = Query("now()"), group_by: str = Query("1m"), agg: str = Query("mean"),
               site: Optional[str] = None):
        """CSV of one metric: time,metric,value (SolarAssistant has an Export page too)."""
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if not api._history_enabled():
            return JSONResponse({"error": "export needs InfluxDB configured"}, status_code=501)
        try:
            if config.INFLUX_MODE.startswith("1"):
                now = time.time()
                start = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now - _rel_seconds(frm)))
                stop = time.strftime("%Y-%m-%d %H:%M:%S", time.gmtime(now))
                data = api.influxql_history(f"inverter_1/{metric}", start, stop, group_by, agg, site)
            else:
                data = api.flux_history(f"inverter_1/{metric}", frm, to, group_by, agg, site)
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"error": str(ex)}, status_code=502)

        def rows():
            yield "time,metric,value\n"
            for ts, val in data["points"]:
                yield f"{ts},{metric},{val}\n"

        return StreamingResponse(rows(), media_type="text/csv", headers={
            "Content-Disposition": f'attachment; filename="{config.SITE}-{metric}.csv"'})

    @app.get("/api/v1/backup")
    def backup(request: Request):
        """Settings + daily energy counters as JSON (no secrets)."""
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        snap = poller.snapshot()
        settings = {k: snap.get(k) for k in SETTINGS if snap.get(k) is not None}
        energy = {k: snap.get(k) for k in ("pv_energy_today", "load_energy_today",
                                           "grid_energy_today", "battery_charge_today",
                                           "battery_discharge_today")
                  if snap.get(k) is not None}
        return JSONResponse({
            "version": 1,
            "site": config.SITE,
            "device": config.DEVICE_NAME,
            "exported": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "settings": settings,
            "info": {k: snap.get(k) for k in INFO_METRICS if snap.get(k) is not None},
            "energy_today": energy,
        }, headers={"Content-Disposition":
                    f'attachment; filename="{config.SITE}-backup.json"'})

    @app.post("/api/v1/restore")
    async def restore(request: Request):
        """Apply settings from a backup file, each one verified by a QPIRI read-back."""
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        wanted = body.get("settings") or {}
        if not isinstance(wanted, dict) or not wanted:
            return JSONResponse({"error": "settings object is required"}, status_code=400)
        results = []
        for key, value in wanted.items():
            if key not in SETTINGS:
                results.append({"key": key, "ok": False,
                                "message": "Error: unknown setting"})
                continue
            results.append(poller.submit_set(key, value, verified=True))
        return {"results": results,
                "ok": all(r.get("ok") for r in results)}

    # ---- automation rules ---------------------------------------------------
    @app.get("/api/v1/rules")
    def list_rules():
        return {
            "rules": rules.list() if rules else [],
            "automation": config.AUTOMATION,
            "channels": notifier.channels() if notifier else [],
            "notify_interval_s": config.NOTIFY_MIN_INTERVAL,
            "fired": rules.fired if rules else 0,
        }

    @app.post("/api/v1/rules")
    async def add_rule(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if rules is None:
            return JSONResponse({"error": "automation disabled"}, status_code=501)
        body = await request.json()
        try:
            return rules.add(body)
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.put("/api/v1/rules/{rule_id}")
    async def update_rule(rule_id: str, request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        try:
            return rules.update(rule_id, body)
        except KeyError:
            return JSONResponse({"error": "not found"}, status_code=404)
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)

    @app.delete("/api/v1/rules/{rule_id}")
    def delete_rule(rule_id: str):
        ok = rules.delete(rule_id) if rules else False
        return {"deleted": ok}

    @app.post("/api/v1/rules/{rule_id}/toggle")
    async def toggle_rule(rule_id: str, request: Request):
        body = await request.json()
        try:
            return rules.set_enabled(rule_id, bool(body.get("enabled", True)))
        except KeyError:
            return JSONResponse({"error": "not found"}, status_code=404)

    @app.get("/api/v1/rules/examples")
    def rule_examples():
        from .rules import EXAMPLES
        return EXAMPLES

    @app.post("/api/v1/notify/test")
    async def notify_test(request: Request):
        if notifier is None:
            return JSONResponse({"error": "notifier disabled"}, status_code=501)
        body = {}
        try:
            body = await request.json()
        except Exception:  # noqa: BLE001
            pass
        text = body.get("text") or f"🔔 Тест уведомлений от {config.DEVICE_NAME} ({config.SITE})"
        return notifier.send(text, force=True)

    @app.get("/api/v1/battery")
    def battery_api():
        if battery is None:
            return {"source": "inverter", "enabled": False, "reading": {}}
        snap = battery.snapshot()
        snap["config"] = battery.config()
        return snap

    @app.get("/api/v1/codes")
    def codes_api():
        from . import codes
        return codes.all_codes()

    @app.get("/api/v1/battery/events")
    def battery_events(limit: int = 50, hours: float = 24):
        log = getattr(poller, "bms_events", None)
        if log is None:
            return {"events": [], "summary": {"codes": []}}
        from . import codes
        events = log.list(limit)
        for event in events:
            code = event.get("code", 0)
            event["title"] = "норма" if code == 0 else codes.title(code, "bms")
            event["effect"] = "" if code == 0 else codes.describe(code, "bms")["action"]
        return {"events": events, "summary": log.summary(hours=hours)}

    @app.get("/api/v1/battery/config")
    def battery_config():
        if battery is None:
            return {"config": {}, "catalog": [], "ports": []}
        return {"config": battery.config(), **battery.available()}

    @app.put("/api/v1/battery/config")
    async def battery_config_set(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if battery is None:
            return JSONResponse({"error": "battery monitor disabled"}, status_code=501)
        body = await request.json()
        try:
            return battery.apply_config(body)
        except ValueError as ex:
            return JSONResponse({"error": str(ex)}, status_code=400)
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"error": repr(ex)}, status_code=500)

    # ---- auth ---------------------------------------------------------------
    from . import auth as auth_mod
    @app.get("/api/v1/auth")
    def auth_info(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if auth_store is None:
            return {"enabled": False, "source": "off", "user": None, "min_length": 6}
        info = auth_store.info()
        info["min_length"] = auth_mod.MIN_LENGTH
        info["default_credentials"] = {"user": auth_mod.DEFAULT_USER,
                                       "password": auth_mod.DEFAULT_PASSWORD}
        return info

    @app.post("/api/v1/auth/password")
    async def auth_change(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if auth_store is None:
            return JSONResponse({"error": "auth store недоступен"}, status_code=501)
        body = await request.json()
        try:
            auth_store.set_password(body.get("current_password", ""),
                                    body.get("new_password", ""),
                                    body.get("user"))
        except ValueError as ex:
            return JSONResponse({"ok": False, "error": str(ex)}, status_code=400)
        info = auth_store.info()
        return {"ok": True, "message": "Пароль изменён",
                "user": info["user"], "source": info["source"],
                "note": "Grafana (порт 3443) имеет свой пароль — он не меняется"}

    # ---- inverter connection ------------------------------------------------
    @app.get("/api/v1/connection")
    def connection_get():
        from . import connection as conn_mod
        if connection_store is None:
            return {"config": {}, "modes": conn_mod.MODES, "ports": {},
                    "transport": getattr(poller, "transport", None).describe()
                    if getattr(poller, "transport", None) else None,
                    "stats": {}, "switchable": False}
        h = poller.health()
        transport = getattr(poller, "transport", None)
        if transport is None:                       # источник — импорт из SolarAssistant
            transport = _Described(poller.describe())
        return {**conn_mod.snapshot(connection_store, transport,
                                    {"rx": h.get("rx"), "tx": h.get("tx"),
                                     "failures": h.get("consecutive_failures"),
                                     "online": h.get("online")}),
                "switchable": hasattr(poller, "apply_connection"),
                "source": config.TRANSPORT}

    @app.put("/api/v1/connection")
    async def connection_put(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        if connection_store is None:
            return JSONResponse({"error": "connection store отсутствует"}, status_code=409)
        body = await request.json()
        mode = body.get("mode")
        from . import connection as conn_mod
        if mode not in conn_mod.MODES:
            return JSONResponse({"error": f"неизвестный режим {mode!r}"}, status_code=400)

        # Сейчас данные идут из SolarAssistant (его USB занят) -> включаем прямое чтение
        # и мягко перезапускаем процесс: Docker поднимет контейнер с новым источником.
        if not hasattr(poller, "apply_connection"):
            connection_store.save({**body, "source": "direct"})
            import os as _os
            import threading as _th
            import time as _t
            def _restart():
                _t.sleep(1.2)
                log.warning("connection: switching source sa-mqtt -> direct, restarting")
                _os._exit(0)          # docker restart: unless-stopped
            _th.Thread(target=_restart, daemon=True).start()
            return {"ok": True, "restarting": True,
                    "transport": conn_mod.describe(connection_store.data)}
        try:
            result = poller.apply_connection(body)
        except Exception as ex:  # noqa: BLE001
            return JSONResponse({"error": repr(ex)}, status_code=500)
        connection_store.save({**body, "source": "direct"})
        return {**result, "saved": dict(connection_store.data)}

    @app.post("/api/v1/connection/probe")
    async def connection_probe(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        from . import connection as conn_mod
        if body.get("mode") not in conn_mod.MODES:
            return JSONResponse({"error": "неизвестный режим"}, status_code=400)
        broker = getattr(poller, "mq", None)
        return conn_mod.probe(body, broker=broker)

    # ---- Wi-Fi (хост-сеть, не инвертор) ------------------------------------
    # Настоящая настройка требует root (polkit: wifi.scan и settings.modify —
    # auth_admin). Поэтому ходим в узкий helper через sudo NOPASSWD,
    # см. deploy/pi/wifi-helper и /etc/sudoers.d/solar-wifi.
    def _wifi_helper(*args: str, timeout: int = 30) -> dict:
        path = os.getenv("WIFI_HELPER", "/usr/local/lib/solar-monitor/wifi-helper")
        if not os.path.exists(path):
            return {"ok": False, "unavailable": True,
                    "error": "wifi helper не установлен (см. deploy/pi/install-pi.sh)"}
        try:
            proc = subprocess.run(["sudo", "-n", path, *args],
                                  capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return {"ok": False, "error": f"helper не ответил за {timeout} с"}
        raw = (proc.stdout or "").strip()
        try:
            return json.loads(raw) if raw else {
                "ok": False, "error": (proc.stderr or "пустой ответ").strip()}
        except json.JSONDecodeError:
            return {"ok": False, "error": (proc.stderr or raw or "не JSON").strip()}

    @app.get("/api/v1/wifi")
    def wifi_status(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return _wifi_helper("status")

    @app.get("/api/v1/wifi/scan")
    def wifi_scan(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        return _wifi_helper("scan", timeout=45)

    @app.post("/api/v1/wifi/connect")
    async def wifi_connect(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        ssid = str(body.get("ssid") or "")
        psk = str(body.get("psk") or "")
        if not ssid:
            return JSONResponse({"ok": False, "error": "не указан SSID"}, status_code=400)
        # helper сам откатывается на прежнюю сеть, если IPv4 не появился
        return _wifi_helper("connect", ssid, psk, timeout=120)

    @app.post("/api/v1/wifi/forget")
    async def wifi_forget(request: Request):
        if not _authorized(request):
            return JSONResponse({"error": "unauthorized"}, status_code=401)
        body = await request.json()
        target = str(body.get("ssid") or "")
        if not target:
            return JSONResponse({"ok": False, "error": "не указан SSID"}, status_code=400)
        return _wifi_helper("forget", target)

    @app.get("/api/v1/battery/protocol")
    def protocol_status():
        status = poller.protocol_status() if hasattr(poller, "protocol_status") else {}
        return {"rollback_enabled": config.BATTERY_TYPE_ROLLBACK,
                "rollback_after_s": config.BATTERY_TYPE_ROLLBACK_AFTER,
                **status}

    @app.post("/api/v1/battery/protocol/confirm")
    def protocol_confirm():
        if not hasattr(poller, "confirm_protocol"):
            return JSONResponse({"error": "not supported by this source"}, status_code=501)
        return poller.confirm_protocol()

    @app.post("/api/v1/battery/protocol/cancel")
    def protocol_cancel():
        if not hasattr(poller, "cancel_protocol"):
            return JSONResponse({"error": "not supported by this source"}, status_code=501)
        return poller.cancel_protocol()

    @app.get("/api/v1/battery/sources")
    def battery_sources():
        from .battery import SOURCES
        return SOURCES

    @app.get("/api/v1/forecast")
    def forecast_api():
        if forecast_svc is None:
            return {"enabled": False, "points": [], "today_kwh": None}
        return forecast_svc.snapshot()

    @app.post("/api/v1/forecast/refresh")
    def forecast_refresh():
        if forecast_svc is None:
            return JSONResponse({"error": "forecast disabled"}, status_code=501)
        return {"ok": forecast_svc.fetch()}

    @app.get("/api/v1/meta")
    def meta():
        """Static UI metadata: metrics/units/settings schema/ranges."""
        return {
            "site": config.SITE,
            "sites": [s["site"] for s in (sites.sites() if sites else [])],
            "device": config.DEVICE_NAME,
            "transport": (poller.transport.describe() if hasattr(poller, "transport")
                          else poller.describe()),
            "metrics": {k: {"name": v[0], "unit": v[1], "icon": v[4]}
                        for k, v in METRICS.items()},
            "info": {k: {"name": v[0], "unit": v[1]} for k, v in INFO_METRICS.items()},
            "battery_source": config.BATTERY_SOURCE,
            "settings": {k: {"name": s["name"], "kind": s["kind"],
                             "icon": s.get("icon"),
                             "unit": s.get("unit")} for k, s in SETTINGS.items()},
            "chart_ranges": ["1h", "6h", "24h", "7d", "30d"],
        }

    def _index_html() -> str:
        with open(INDEX, encoding="utf-8") as f:
            return f.read().replace("{{v}}", ASSET_V)

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_index_html())

    @app.get("/{path:path}", response_class=HTMLResponse)
    def spa(path: str):
        if path.startswith("api/"):
            return JSONResponse({"error": "not found"}, status_code=404)
        return HTMLResponse(_index_html())

    return app


def _rel_seconds(spec: str) -> float:
    """'-7d' -> seconds (used for InfluxDB 1.x absolute times)."""
    units = {"s": 1, "m": 60, "h": 3600, "d": 86400, "w": 604800}
    try:
        return float(spec.lstrip("-")[:-1]) * units.get(spec[-1:], 1)
    except (ValueError, IndexError):
        return 86400.0
