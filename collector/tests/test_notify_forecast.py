"""Notifications and forecast: channels, rate limiting, API parsing (all mocked)."""
import io
import json
import os
import sys
import time
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, forecast, notifier  # noqa: E402


class FakeMqtt:
    def __init__(self):
        self.sent = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.sent.append((topic, payload, retain))
        return True


class TestNotifier(unittest.TestCase):
    def setUp(self):
        self._orig = (config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT, config.WEBHOOK_URL,
                      config.NOTIFY_MIN_INTERVAL)
        config.TELEGRAM_TOKEN = config.TELEGRAM_CHAT = config.WEBHOOK_URL = None
        config.NOTIFY_MIN_INTERVAL = 60

    def tearDown(self):
        (config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT, config.WEBHOOK_URL,
         config.NOTIFY_MIN_INTERVAL) = self._orig

    def test_no_channels(self):
        n = notifier.Notifier()
        self.assertEqual(n.channels(), [])
        self.assertEqual(n.send("hi"), {})

    def test_mqtt_channel(self):
        mq = FakeMqtt()
        n = notifier.Notifier(mqtt=mq)
        self.assertIn("mqtt", n.channels())
        res = n.send("привет")
        self.assertEqual(res["mqtt"], "sent")
        topic, payload, retain = mq.sent[0]
        self.assertEqual(topic, config.NOTIFY_MQTT_TOPIC)
        self.assertEqual(payload["text"], "привет")
        self.assertFalse(retain)

    def test_rate_limit_and_force(self):
        mq = FakeMqtt()
        n = notifier.Notifier(mqtt=mq)
        n.send("one")
        self.assertEqual(n.send("two")["mqtt"], "rate-limited")
        self.assertEqual(n.send("three", force=True)["mqtt"], "sent")
        self.assertEqual(len(mq.sent), 2)
        self.assertEqual(n.sent, 2)

    def test_webhook(self):
        config.WEBHOOK_URL = "http://example.invalid/hook"
        captured = {}

        class Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        def fake(req, timeout=10):
            captured["url"] = req.full_url
            captured["body"] = json.loads(req.data.decode())
            return Resp()

        with mock.patch("urllib.request.urlopen", fake):
            res = notifier.Notifier().send("test", force=True)
        self.assertEqual(res["webhook"], "sent")
        self.assertEqual(captured["body"]["text"], "test")
        self.assertEqual(captured["body"]["site"], config.SITE)

    def test_telegram_url_and_errors_are_counted(self):
        config.TELEGRAM_TOKEN, config.TELEGRAM_CHAT = "TOKEN", "42"
        captured = {}

        def boom(req, timeout=10):
            captured["url"] = req.full_url
            raise OSError("network down")

        n = notifier.Notifier()
        with mock.patch("urllib.request.urlopen", boom):
            res = n.send("x", force=True)
        self.assertIn("error", res["telegram"])
        self.assertEqual(n.errors, 1)
        self.assertIn("TOKEN/sendMessage", captured["url"])


def _forecast_json():
    """Timestamps relative to now, so the test never depends on wall clock time."""
    import time as _t
    base = _t.time()
    def stamp(offset_h):
        return _t.strftime("%Y-%m-%d %H:%M:%S", _t.gmtime(base + offset_h * 3600))
    return {
        "result": {
            "watts": {stamp(-1): 0, stamp(1): 1200.5, stamp(2): 2500.0},
            "watt_hours_day": {_t.strftime("%Y-%m-%d"): 5432},
        },
        "message": {"code": 0, "type": "success"},
    }


FORECAST_JSON = _forecast_json()


class FakeInflux:
    def __init__(self):
        self.series = []

    def write_series(self, measurement, points):
        self.series.append((measurement, points))


class FakePoller:
    def __init__(self):
        self.state = {}


class TestForecast(unittest.TestCase):
    def setUp(self):
        import tempfile
        self._tmp = tempfile.TemporaryDirectory()
        config.FORECAST_CACHE_FILE = os.path.join(self._tmp.name, "forecast.json")
        self._orig = (config.FORECAST_ENABLED, config.FORECAST_LAT, config.FORECAST_LON,
                      config.FORECAST_KWP)
        config.FORECAST_ENABLED = True
        config.FORECAST_LAT, config.FORECAST_LON, config.FORECAST_KWP = "37.98", "23.72", "5.0"

    def tearDown(self):
        (config.FORECAST_ENABLED, config.FORECAST_LAT, config.FORECAST_LON,
         config.FORECAST_KWP) = self._orig
        self._tmp.cleanup()

    def test_disabled_without_config(self):
        config.FORECAST_LAT = ""
        self.assertFalse(forecast.ForecastService().enabled)
        self.assertFalse(forecast.ForecastService().fetch())

    def test_url_shape(self):
        url = forecast.ForecastService().url()
        self.assertIn("37.98/23.72/", url)
        self.assertTrue(url.endswith("/5.0"))

    def test_fetch_parses_and_publishes(self):
        influx, poller, mq = FakeInflux(), FakePoller(), FakeMqtt()
        svc = forecast.ForecastService(poller=poller, influx=influx, mqtt=mq)

        class Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = json.dumps(_forecast_json())     # свежие метки времени
        with mock.patch("urllib.request.urlopen", lambda *a, **kw: Resp(payload.encode())):
            self.assertTrue(svc.fetch())

        self.assertEqual(len(svc.points), 3)
        self.assertEqual(svc.points, sorted(svc.points))          # sorted by time
        self.assertAlmostEqual(svc.today_kwh, 5.43)
        self.assertEqual(influx.series[0][0], "pv_power_forecast")
        self.assertEqual(len(influx.series[0][1]), 3)
        self.assertEqual(poller.state["pv_forecast_today"], 5.43)
        self.assertIn("pv_forecast_now", poller.state)
        self.assertTrue(any("forecast/pv_power_today" in t for t, _, _ in mq.sent))

    def test_cache_survives_restart(self):
        import io
        from unittest import mock
        config.FORECAST_CACHE_FILE = os.path.join(self._tmp.name, "cache.json")

        class Resp(io.BytesIO):
            status = 200

            def __enter__(self):
                return self

            def __exit__(self, *a):
                return False

        payload = json.dumps(_forecast_json()).encode()
        with mock.patch("urllib.request.urlopen", lambda *a, **kw: Resp(payload)):
            self.assertTrue(forecast.ForecastService().fetch())
        again = forecast.ForecastService()          # «новый контейнер»
        self.assertGreater(len(again.points), 0)
        self.assertIsNotNone(again.today_kwh)

    def test_rate_limit_sets_retry(self):
        from unittest import mock
        import urllib.error

        def boom(*a, **kw):
            raise urllib.error.HTTPError("http://x", 429, "Too Many Requests", {}, None)

        svc = forecast.ForecastService()
        with mock.patch("urllib.request.urlopen", boom):
            self.assertFalse(svc.fetch())
        self.assertGreater(svc.retry_after, 0)
        # второй вызов не идёт в сеть, пока окно не истекло
        with mock.patch("urllib.request.urlopen", side_effect=AssertionError("не должно быть запроса")):
            self.assertFalse(svc.fetch())

    def test_fetch_error_is_survivable(self):
        svc = forecast.ForecastService()

        def boom(*a, **kw):
            raise OSError("no internet")

        with mock.patch("urllib.request.urlopen", boom):
            self.assertFalse(svc.fetch())
        self.assertEqual(svc.errors, 1)
        self.assertIsNotNone(svc.last_error)
        self.assertEqual(svc.snapshot()["points"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)
