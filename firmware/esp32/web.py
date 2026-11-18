"""Мини-HTTP-сервер (uasyncio): веб-интерфейс и JSON API на самом ESP32."""
try:
    import uasyncio as asyncio
except ImportError:                     # CPython (тесты/отладка)
    import asyncio

try:
    import ujson as json
except ImportError:
    import json

try:
    import ubinascii as binascii
except ImportError:
    import binascii

import pi30
import sethandler


def _code(status):
    reasons = {200: "OK", 204: "No Content", 400: "Bad Request", 401: "Unauthorized",
               404: "Not Found", 405: "Method Not Allowed", 500: "Internal Server Error"}
    return "%d %s" % (status, reasons.get(status, "Error"))


class App:
    def __init__(self, cfg, poller, history, publisher):
        self.cfg = cfg
        self.poller = poller
        self.history = history
        self.publisher = publisher
        auth = cfg.get("auth") or {}
        self.user = auth.get("user") or ""
        self.password = auth.get("password") or ""
        self.port = int((cfg.get("http") or {}).get("port", 80))
        self._index = None

    # -- helpers -------------------------------------------------------------
    def _static(self):
        if self._index is None:
            try:
                with open("www/index.html", "r") as fh:
                    self._index = fh.read()
            except OSError:
                self._index = "<h1>solar-monitor</h1><p>www/index.html не найден</p>"
        return self._index

    def _authorized(self, headers):
        if not self.user:
            return True
        token = binascii.b2a_base64(
            ("%s:%s" % (self.user, self.password)).encode()).decode().strip()
        return headers.get("authorization", "") == "Basic " + token

    def _state(self):
        st = dict(self.poller.state)
        st["health"] = self.poller.health()
        st["history_summary"] = self.history.summary()
        return st

    def _settings(self):
        return {"settings": sethandler.settings_list(self.poller.bus),
                "read_only": pi30.READ_ONLY_SETTINGS}

    def _sysinfo(self):
        out = {"port": self.port, "mqtt_connected": self.publisher.connected,
               "mqtt_prefix": self.publisher.prefix}
        try:
            import gc
            out["free_mem"] = gc.mem_free()
        except Exception:
            pass
        try:
            import network
            sta = network.WLAN(network.STA_IF)
            if sta.isconnected():
                out["ip"] = sta.ifconfig()[0]
                out["rssi"] = sta.status("rssi")
        except Exception:
            pass
        return out

    # -- маршруты ------------------------------------------------------------
    def route(self, method, path, query, body, headers):
        if not self._authorized(headers):
            return 401, "text/plain", "unauthorized", {"WWW-Authenticate": "Basic realm=sm"}
        if path in ("/", "/index.html"):
            return 200, "text/html; charset=utf-8", self._static(), {}
        if path == "/api/v1/state":
            return 200, "application/json", json.dumps(self._state()), {}
        if path == "/api/v1/health":
            return 200, "application/json", json.dumps(self.poller.health()), {}
        if path == "/api/v1/sysinfo":
            return 200, "application/json", json.dumps(self._sysinfo()), {}
        if path == "/api/v1/history":
            limit = 0
            for part in query.split("&"):
                if part.startswith("limit="):
                    try:
                        limit = int(part[6:])
                    except ValueError:
                        limit = 0
            return 200, "application/json", json.dumps(self.history.as_dict(limit)), {}
        if path == "/api/v1/settings":
            if method == "GET":
                return 200, "application/json", json.dumps(self._settings()), {}
            if method == "POST":
                try:
                    req = json.loads(body or "{}")
                except Exception:                      # noqa: BLE001
                    return 400, "application/json", json.dumps({"error": "bad json"}), {}
                key = req.get("key")
                value = req.get("value")
                if not key:
                    return 400, "application/json", json.dumps({"error": "no key"}), {}
                result = sethandler.apply_setting(self.poller.bus, key, value)
                self.publisher.last_set = result
                code = 200 if result.get("ok") else 400
                return code, "application/json", json.dumps(result), {}
            return 405, "text/plain", "method not allowed", {}
        if path == "/api/v1/poll":
            self.poller.poll_once()
            return 200, "application/json", json.dumps(self._state()), {}
        return 404, "text/plain", "not found", {}

    # -- соединение ----------------------------------------------------------
    async def handle(self, reader, writer):
        try:
            line = await reader.readline()
            if not line:
                return
            parts = line.decode().split()
            if len(parts) < 3:
                return
            method, target, _ = parts[0], parts[1], parts[2]
            path, _, query = target.partition("?")
            headers = {}
            length = 0
            while True:
                hline = await reader.readline()
                if not hline or hline == b"\r\n":
                    break
                name, _, value = hline.decode().partition(":")
                headers[name.strip().lower()] = value.strip()
                if name.strip().lower() == "content-length":
                    try:
                        length = int(value.strip())
                    except ValueError:
                        length = 0
            body = b""
            if length:
                body = await reader.read(min(length, 1024))
            try:
                status, ctype, payload, extra = self.route(
                    method, path, query, body, headers)
            except Exception as ex:                    # noqa: BLE001
                status, ctype, payload, extra = 500, "text/plain", "error: %r" % (ex,), {}
            if not isinstance(payload, str):
                payload = str(payload)
            await self._send(writer, status, ctype, payload, extra)
        except Exception as ex:                        # noqa: BLE001
            print("http:", ex)
        finally:
            try:
                await writer.aclose()
            except Exception:
                pass

    async def _send(self, writer, status, ctype, payload, extra):
        data = payload.encode()
        head = "HTTP/1.1 %s\r\nContent-Type: %s\r\nContent-Length: %d\r\n" \
               "Connection: close\r\nCache-Control: no-store\r\n" % (
                   _code(status), ctype, len(data))
        for name, value in extra.items():
            head += "%s: %s\r\n" % (name, value)
        await writer.awrite((head + "\r\n").encode())
        await writer.awrite(data)

    async def run(self):
        await asyncio.start_server(self.handle, "0.0.0.0", self.port)
        print("http://0.0.0.0:%d/" % self.port)
        while True:
            await asyncio.sleep(3600)
