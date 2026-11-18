"""Web UI + JSON API tests (FastAPI TestClient, no network, no broker)."""
import json
import os
import sys
import tempfile
import threading
import time
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from fastapi.testclient import TestClient  # noqa: E402

from solar_monitor import config, pi30, poller as poller_mod, webapp  # noqa: E402
from solar_monitor import forecast, notifier, rules  # noqa: E402

QPIGS = (b'(231.3 49.9 230.2 50.0 00230 00165 002 372 52.90 000 081 0048 00.0 000.0'
         b' 00.00 00004 00010000 00 00 00000 010 0 00 0000?d\r')
QPIRI = (b'(230.0 47.8 230.0 50.0 47.8 11000 11000 48.0 50.0 44.8 57.6 57.6 8 002 150'
         b' 1 2 3 9 01 0 0 52.0 0 1 480 0 150@\xc6\r')
QMOD = b'(B\xe7\xc9\r'
QID = b'(TEST000000000001\x10#\r'
QPIGS2 = b'(00.0 000.0 00000 E\x93\r'
QPIRS = ("(" + "0" * 40).encode() + b"\x00\x00\r"


class FakeTransport:
    def __init__(self):
        self.answers = {"QPIGS": QPIGS, "QPIGS2": QPIGS2, "QPIRI": QPIRI,
                        "QMOD": QMOD, "QID": QID, "QPIWS": QPIRS, "POP02": b"(ACK\r"}
        self.rx_count = self.tx_count = 0

    def describe(self):
        return "fake"

    def request(self, cmd, timeout=3.0, attempts=2):
        self.tx_count += 1
        r = self.answers.get(cmd)
        if r:
            self.rx_count += 1
        return r

    def request_raw(self, cmd, timeout=4.0, attempts=2):
        return self.request(cmd)

    def close(self):
        pass


class FakeMqtt:
    class _Ev:
        @staticmethod
        def is_set():
            return True

    connected = _Ev()
    restarts = 0

    def __init__(self):
        self.sent = []

    def publish(self, *a, **kw):
        self.sent.append(a)
        return True

    def subscribe(self, *a, **kw):
        pass


class FakeInflux:
    written = errors = 0

    def write(self, *a, **kw):
        pass


class TestWebUi(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls._intervals = (config.QMOD_INTERVAL, config.QPIRI_INTERVAL,
                          config.QPIWS_INTERVAL, config.HAS_MPPT2)
        config.QMOD_INTERVAL = config.QPIRI_INTERVAL = 0
        config.QPIWS_INTERVAL = 0.001
        config.HAS_MPPT2 = True
        config.POLL_INTERVAL = 0.05
        cls.poller = poller_mod.Poller(FakeTransport(), FakeMqtt(), FakeInflux())
        tmp = tempfile.NamedTemporaryFile(suffix=".json", delete=False)
        tmp.close()
        cls.poller.energy.path = tmp.name
        cls.rules_tmp = tempfile.TemporaryDirectory()
        cls.rules = rules.RuleEngine(os.path.join(cls.rules_tmp.name, "rules.json"))
        cls.notifier = notifier.Notifier(mqtt=FakeMqtt())
        cls.forecast = forecast.ForecastService()
        cls.poller.cycle()
        cls.client = TestClient(webapp.create_app(
            cls.poller, notifier=cls.notifier, rules=cls.rules, forecast_svc=cls.forecast))

    @classmethod
    def tearDownClass(cls):
        cls.rules_tmp.cleanup()
        (config.QMOD_INTERVAL, config.QPIRI_INTERVAL,
         config.QPIWS_INTERVAL, config.HAS_MPPT2) = cls._intervals

    # -- pages ---------------------------------------------------------------
    def test_index_serves_spa(self):
        r = self.client.get("/")
        self.assertEqual(r.status_code, 200)
        self.assertIn("solar-monitor", r.text)
        self.assertIn("/static/app.js", r.text)

    def test_static_assets(self):
        for path in ("/static/app.js", "/static/styles.css",
                     "/static/vendor/uplot.min.js"):
            self.assertEqual(self.client.get(path).status_code, 200, path)

    def test_deep_links_return_spa(self):
        for path in ("/inverter", "/charts", "/settings"):
            r = self.client.get(path)
            self.assertEqual(r.status_code, 200, path)
            self.assertIn('id="charts-root"', r.text)      # страница графиков строится в JS
        self.assertEqual(self.client.get("/api/v1/nope").status_code, 404)

    # -- api -----------------------------------------------------------------
    def test_state(self):
        d = self.client.get("/api/v1/state").json()
        self.assertEqual(d["battery_state_of_charge"], 81)
        self.assertEqual(d["output_source_priority"], "SBU")

    def test_health(self):
        r = self.client.get("/healthz")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.json()["transport"], "fake")

    def test_metrics_and_single_value(self):
        items = self.client.get("/api/v1/metrics?topic=inverter_1/battery*").json()
        self.assertTrue(items)
        self.assertTrue(all(i["topic"].startswith("inverter_1/battery") for i in items))
        one = self.client.get("/api/v1/metrics?topic=inverter_1/battery_voltage&value=1")
        self.assertEqual(one.text, "52.9")

    def test_meta(self):
        d = self.client.get("/api/v1/meta").json()
        self.assertIn("pv_power", d["metrics"])
        self.assertIn("output_source_priority", d["settings"])
        self.assertEqual(d["transport"], "fake")

    def test_settings_list_and_write(self):
        schema = self.client.get("/api/v1/settings").json()
        self.assertEqual(len(schema), 10)

        # the write is queued for the poller: keep cycling while the request waits
        result = {}

        def do_post():
            result["r"] = self.client.post("/api/v1/settings",
                                           json={"key": "output_source_priority",
                                                 "value": "SBU", "verified": True})

        worker = threading.Thread(target=do_post)
        worker.start()
        for _ in range(40):
            self.poller.cycle()
            if "r" in result:
                break
        worker.join(10)
        self.assertIn("r", result)
        self.assertEqual(result["r"].status_code, 200, result["r"].text)
        self.assertTrue(result["r"].json()["ok"])

        # validation runs before anything reaches the inverter -> no queuing
        bad = self.client.post("/api/v1/settings", json={"key": "output_source_priority",
                                                         "value": "nonsense"})
        self.assertEqual(bad.status_code, 422)
        self.assertFalse(bad.json()["ok"])

    def test_sse_generator(self):
        """The SSE body is a plain generator, so it can be tested synchronously."""
        gen = webapp.sse_stream(self.poller, interval=0.01, max_events=2)
        first = next(gen)
        self.assertIn("event: state", first)
        self.assertIn('"battery_state_of_charge"', first)
        # a changed state produces a second frame, then the generator stops
        self.poller.state["load_power"] = 4242
        second = next(gen)
        self.assertIn("4242", second)
        with self.assertRaises(StopIteration):
            next(gen)

    def test_basic_auth(self):
        config.AUTH_USER, config.AUTH_PASSWORD = "u", "secret"
        try:
            client = TestClient(webapp.create_app(self.poller))
            self.assertEqual(client.get("/").status_code, 401)
            self.assertEqual(client.get("/api/v1/state").status_code, 401)
            self.assertEqual(client.get("/healthz").status_code, 200)      # docker healthcheck
            self.assertEqual(client.get("/", auth=("u", "secret")).status_code, 200)
            self.assertEqual(client.get("/api/v1/state", auth=("u", "wrong")).status_code, 401)
            self.assertEqual(client.get("/", auth=("nobody", "secret")).status_code, 401)
        finally:
            config.AUTH_USER = config.AUTH_PASSWORD = None

    def test_stream_endpoint_headers_are_eventstream(self):
        r = self.client.get("/api/v1/stream?events=1")
        self.assertEqual(r.status_code, 200)
        self.assertIn("text/event-stream", r.headers["content-type"])
        self.assertIn("event: state", r.text)

    def test_backup_and_restore(self):
        b = self.client.get("/api/v1/backup")
        self.assertEqual(b.status_code, 200)
        data = b.json()
        self.assertEqual(data["version"], 1)
        self.assertIn("output_source_priority", data["settings"])
        self.assertEqual(data["settings"]["output_source_priority"], "SBU")
        self.assertIn("energy_today", data)
        self.assertNotIn("password", json.dumps(data).lower())

        result = {}

        def do_restore():
            result["r"] = self.client.post("/api/v1/restore",
                                           json={"settings": {"output_source_priority": "SBU",
                                                              "unknown_key": 1}})

        worker = threading.Thread(target=do_restore)
        worker.start()
        for _ in range(40):
            self.poller.cycle()
            if "r" in result:
                break
        worker.join(10)
        payload = result["r"].json()
        self.assertFalse(payload["ok"])          # unknown key -> overall false
        by_key = {r["key"]: r for r in payload["results"]}
        self.assertTrue(by_key["output_source_priority"]["ok"])
        self.assertFalse(by_key["unknown_key"]["ok"])

    def test_export_csv_without_influx(self):
        r = self.client.get("/api/v1/export?metric=pv_power&from=-1h")
        self.assertIn(r.status_code, (501, 502))

    def test_rules_crud(self):
        d = self.client.get("/api/v1/rules").json()
        self.assertTrue(d["automation"])
        self.assertEqual(d["rules"], [])

        body = {"name": "test rule",
                "when": {"metric": "battery_state_of_charge", "op": "<", "value": 20, "for_s": 30},
                "then": [{"type": "notify", "text": "soc {battery_state_of_charge}"}],
                "cooldown_s": 120}
        r = self.client.post("/api/v1/rules", json=body)
        self.assertEqual(r.status_code, 200, r.text)
        rule = r.json()
        self.assertEqual(len(rule["id"]), 8)
        self.assertEqual(len(self.client.get("/api/v1/rules").json()["rules"]), 1)

        bad = self.client.post("/api/v1/rules", json={"when": {"metric": "x", "op": "?!", "value": 1},
                                                      "then": [{"type": "notify"}]})
        self.assertEqual(bad.status_code, 400)

        off = self.client.post(f"/api/v1/rules/{rule['id']}/toggle", json={"enabled": False}).json()
        self.assertFalse(off["enabled"])
        self.assertTrue(self.client.delete(f"/api/v1/rules/{rule['id']}").json()["deleted"])
        self.assertEqual(self.client.get("/api/v1/rules").json()["rules"], [])

    def test_rule_examples(self):
        ex = self.client.get("/api/v1/rules/examples").json()
        self.assertEqual(len(ex), 3)
        self.assertIn("when", ex[0])

    def test_forecast_endpoint(self):
        d = self.client.get("/api/v1/forecast").json()
        self.assertFalse(d["enabled"])
        self.assertEqual(d["points"], [])

    def test_notify_test_endpoint(self):
        res = self.client.post("/api/v1/notify/test", json={"text": "hi"}).json()
        self.assertIn("mqtt", res)

    def test_peer_proxy_returns_peer_response(self):
        """?site=<peer> уходит на API другого сайта."""
        import io
        import json as _json
        from unittest import mock
        from solar_monitor import config

        class Resp(io.BytesIO):
            status = 200
            headers = {"Content-Type": "application/json"}

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        captured = {}

        def fake(req, timeout=20):
            captured["url"] = req.full_url
            return Resp(_json.dumps({"transport": "peer-transport"}).encode())

        site_before = config.SITE
        config.SITE = "home"
        config.PEER_SITES = {"office": "http://10.0.0.9:8081"}
        try:
            with mock.patch("urllib.request.urlopen", fake):
                r = self.client.get("/api/v1/connection?site=office")
            self.assertEqual(r.status_code, 200)
            self.assertEqual(r.json()["transport"], "peer-transport")
            self.assertEqual(captured["url"], "http://10.0.0.9:8081/api/v1/connection")
        finally:
            config.PEER_SITES = {}
            config.SITE = site_before

    def test_peer_proxy_unreachable_is_502(self):
        from solar_monitor import config
        site_before = config.SITE
        config.SITE = "home"
        config.PEER_SITES = {"office": "http://127.0.0.1:1"}
        try:
            r = self.client.get("/api/v1/connection?site=office")
            self.assertEqual(r.status_code, 502)
            self.assertIn("error", r.json())
        finally:
            config.PEER_SITES = {}
            config.SITE = site_before

    def test_local_site_is_not_proxied(self):
        from solar_monitor import config
        site_before = config.SITE
        config.SITE = "home"
        config.PEER_SITES = {"office": "http://127.0.0.1:1"}
        try:
            r = self.client.get("/api/v1/connection?site=home")   # локальный — без прокси
            self.assertEqual(r.status_code, 200)
            self.assertIn("transport", r.json())
        finally:
            config.PEER_SITES = {}
            config.SITE = site_before

    def test_sites_endpoint_without_registry(self):
        d = self.client.get("/api/v1/sites").json()
        self.assertEqual(d[0]["site"], config.SITE)

    def test_state_unknown_site(self):
        self.assertEqual(self.client.get("/api/v1/state?site=nope").status_code, 200)

    def test_energy_endpoint_without_influx(self):
        r = self.client.get("/api/v1/energy?from=-7d")
        # no InfluxDB in tests -> explicit error, never a 500 traceback
        self.assertIn(r.status_code, (501, 502))


if __name__ == "__main__":
    unittest.main(verbosity=2)
