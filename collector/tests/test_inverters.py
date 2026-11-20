"""Доп. инверторы на одном хосте: валидация, генерация env, CRUD через systemd."""
import json
import os
import sys
import tempfile
import unittest
from unittest import mock

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from solar_monitor import config, inverters  # noqa: E402


class InverterTestCase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.patch = mock.patch.object(config, "INVERTERS_DIR", self.tmp.name)
        self.patch.start()
        self.addCleanup(self.patch.stop)
        # systemd в тестах нет — подменяем вызовы helper'а
        self.calls = []
        self.sysctl = mock.patch.object(inverters, "_systemctl",
                                        side_effect=self._fake_systemctl)
        self.sysctl.start()
        self.addCleanup(self.sysctl.stop)
        # на macOS/в CI systemd нет — считаем хост «умеющим» (иначе create откажет)
        self.sup = mock.patch.object(inverters, "supported", return_value=True)
        self.sup.start()
        self.addCleanup(self.sup.stop)

    def _fake_systemctl(self, op, site, timeout=25.0):
        self.calls.append((op, site))
        if op == "is-active":
            return 0, "active"
        if op == "is-enabled":
            return 0, "enabled"
        return 0, ""

    def payload(self, **over):
        base = {"site": "garage", "label": "Гараж", "mode": "tcp",
                "tcp_host": "192.168.1.60", "tcp_port": 9999}
        base.update(over)
        return base


class ValidationTests(InverterTestCase):
    def test_slug_rules(self):
        for bad in ("", "g", "1abc", "привет", "with space", "a" * 25):
            with self.assertRaises(inverters.InverterError, msg=bad):
                inverters.normalize(self.payload(site=bad))
        # регистр не важен: UI вводит как удобно, id хранится нижним регистром
        self.assertEqual(inverters.normalize(self.payload(site="Garage"))["site"], "garage")

    def test_reserved_and_own_site(self):
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(site="all"))
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(site=config.SITE))

    def test_mode_needs_its_field(self):
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(tcp_host=""))
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(mode="serial", serial_port=""))
        # пустой hid_device подставляется из HID_DEVICE (udev-symlink или hidraw0)
        self.assertTrue(inverters.normalize(self.payload(mode="hid", hid_device=""))["hid_device"])
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(mode="telnet"))

    def test_normalized_defaults(self):
        item = inverters.normalize(self.payload(site="garage"))
        self.assertEqual(item["site"], "garage")
        self.assertEqual(item["label"], "Гараж")
        self.assertTrue(item["mode"] == "tcp")
        self.assertFalse(item["webapp"])


class EnvTests(InverterTestCase):
    def test_env_has_site_transport_and_own_state_files(self):
        item = inverters.normalize(self.payload())
        text = inverters.env_text(item)
        self.assertIn("SITE=garage", text)
        self.assertIn("TRANSPORT=tcp", text)
        self.assertIn("TCP_HOST=192.168.1.60", text)
        self.assertIn("TCP_PORT=9999", text)
        # состояние доп. инвертора не должно перетирать основное
        self.assertIn(f"CONNECTION_FILE={self.tmp.name}/garage.connection.json", text)
        self.assertIn(f"ENERGY_FILE={self.tmp.name}/garage.energy.json", text)
        # второй веб-сервер по умолчанию выключен (RAM на Pi)
        self.assertIn("WEBAPP=0", text)
        self.assertIn("API_PORT=0", text)

    def test_env_hid_and_webapp(self):
        item = inverters.normalize(self.payload(mode="hid", hid_device="/dev/voltronic-inverter",
                                                webapp=True, api_port=8081))
        text = inverters.env_text(item)
        self.assertIn("HID_DEVICE=/dev/voltronic-inverter", text)
        self.assertIn("API_PORT=8081", text)
        self.assertIn("WEBAPP=1", text)


class CrudTests(InverterTestCase):
    def test_create_list_remove(self):
        created = inverters.create(self.payload())
        self.assertEqual(created["site"], "garage")
        self.assertIn(("enable", "garage"), self.calls)
        self.assertIn(("restart", "garage"), self.calls)
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "garage.json")))
        self.assertTrue(os.path.exists(os.path.join(self.tmp.name, "garage.env")))

        listing = inverters.listing()
        self.assertEqual([i["site"] for i in listing], ["garage"])
        self.assertTrue(listing[0]["active"])

        inverters.remove("garage")
        self.assertEqual(inverters.listing(), [])
        self.assertIn(("stop", "garage"), self.calls)
        self.assertIn(("disable", "garage"), self.calls)
        self.assertFalse(os.path.exists(os.path.join(self.tmp.name, "garage.env")))

    def test_duplicate_is_rejected(self):
        inverters.create(self.payload())
        with self.assertRaises(inverters.InverterError):
            inverters.create(self.payload())

    def test_update_rewrites_env_and_restarts(self):
        inverters.create(self.payload())
        self.calls.clear()
        updated = inverters.update("garage", {"tcp_host": "10.0.0.5"})
        self.assertEqual(updated["tcp_host"], "10.0.0.5")
        self.assertIn(("restart", "garage"), self.calls)
        with open(os.path.join(self.tmp.name, "garage.env"), encoding="utf-8") as f:
            self.assertIn("TCP_HOST=10.0.0.5", f.read())

    def test_actions_validate(self):
        inverters.create(self.payload())
        with self.assertRaises(inverters.InverterError):
            inverters.action("garage", "format-disk")
        with self.assertRaises(inverters.InverterError):
            inverters.action("missing", "start")
        res = inverters.action("garage", "start")
        self.assertTrue(res["ok"])

    def test_json_is_valid_and_readable(self):
        inverters.create(self.payload())
        with open(os.path.join(self.tmp.name, "garage.json"), encoding="utf-8") as f:
            data = json.load(f)
        self.assertEqual(data["site"], "garage")
        mode = os.stat(os.path.join(self.tmp.name, "garage.json")).st_mode & 0o777
        self.assertEqual(oct(mode), "0o640")


class SupportTests(unittest.TestCase):
    def test_unsupported_when_dir_missing(self):
        with mock.patch.object(config, "INVERTERS_DIR", "/nonexistent/solar-sites"):
            self.assertFalse(inverters.supported())
            with self.assertRaises(inverters.InverterError):
                inverters.create({"site": "garage", "mode": "tcp", "tcp_host": "1.2.3.4"})

    def test_snapshot_shape(self):
        with tempfile.TemporaryDirectory() as tmp, \
                mock.patch.object(config, "INVERTERS_DIR", tmp):
            snap = inverters.snapshot()
            self.assertIn("supported", snap)
            self.assertIn("inverters", snap)
            self.assertEqual(snap["inverters"], [])
            self.assertIn("modes", snap)


if __name__ == "__main__":
    unittest.main()


class SiteRegistryTests(InverterTestCase):
    def test_extra_site_is_listed_before_it_publishes(self):
        """Добавленный инвертор сразу виден в списке сайтов, даже офлайн."""
        from solar_monitor import sites as sites_mod

        class NoMqtt:
            def subscribe(self, *a, **kw):
                pass

        inverters.create(self.payload(site="garage"))
        registry = sites_mod.SiteRegistry(NoMqtt())
        names = [s["site"] for s in registry.sites()]
        self.assertIn("garage", names)
        garage = [s for s in registry.sites() if s["site"] == "garage"][0]
        self.assertFalse(garage["online"])          # ещё не публиковал state

    def test_registry_caches_listing(self):
        from solar_monitor import sites as sites_mod

        class NoMqtt:
            def subscribe(self, *a, **kw):
                pass

        inverters.create(self.payload(site="garage"))
        registry = sites_mod.SiteRegistry(NoMqtt())
        registry.sites()
        with mock.patch.object(inverters, "listing", side_effect=AssertionError("кеш не работает")):
            self.assertIn("garage", [s["site"] for s in registry.sites()])
