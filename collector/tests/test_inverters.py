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
        # по умолчанию проверяем systemd-ветку; ветка «дочерние процессы» — ниже
        self.mode = mock.patch.object(inverters, "resolved_mode", return_value="systemd")
        self.mode.start()
        self.addCleanup(self.mode.stop)

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
        # пустой hid_device => берётся СВОБОДНЫЙ узел, а не узел первого инвертора
        with mock.patch.object(os, "listdir", dev_listdir(["hidraw0", "hidraw1"])):
            picked = inverters.normalize(self.payload(mode="hid", hid_device=""))["hid_device"]
        self.assertEqual(picked, "/dev/hidraw1")
        self.assertNotEqual(picked, config.HID_DEVICE)
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
    def test_missing_dir_but_writable_parent_is_supported(self):
        """Свежий контейнер: /data/inverters ещё нет, но /data писать можно."""
        with tempfile.TemporaryDirectory() as tmp:
            target = os.path.join(tmp, "inverters")
            with mock.patch.object(config, "INVERTERS_DIR", target), \
                    mock.patch.object(config, "INVERTERS_ENABLED", True), \
                    mock.patch.object(inverters, "resolved_mode", return_value="process"):
                self.assertTrue(inverters.supported())
                os.makedirs(target)
                self.assertTrue(inverters.supported())
                with mock.patch.object(os, "access", return_value=False):
                    self.assertFalse(inverters.supported())

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


class FakePopen:
    """Заглушка subprocess.Popen: дочерний коллектор в тестах не запускается."""

    instances = []

    def __init__(self, args, env=None, cwd=None, **kw):
        self.args, self.env = args, env or {}
        self.pid = 4242
        self._alive = True
        FakePopen.instances.append(self)

    def poll(self):
        return None if self._alive else 1

    def terminate(self):
        self._alive = False

    def kill(self):
        self._alive = False

    def wait(self, timeout=None):
        self._alive = False
        return 0


class ProcessModeTests(InverterTestCase):
    """Docker/VDS: доп. инвертор — дочерний процесс контейнера, без root."""

    def setUp(self):
        super().setUp()
        self.mode.stop()                      # отменяем systemd-заглушку
        self.mode = mock.patch.object(inverters, "resolved_mode", return_value="process")
        self.mode.start()
        self.addCleanup(self.mode.stop)       # иначе подмена «протечёт» в другие тесты
        FakePopen.instances = []
        self.popen = mock.patch.object(inverters.subprocess, "Popen", FakePopen)
        self.popen.start()
        self.addCleanup(self.popen.stop)
        self.supervisor = inverters.ProcessSupervisor.instance()
        self.supervisor.procs.clear()
        self.addCleanup(self.supervisor.procs.clear)

    def test_create_starts_child_process(self):
        created = inverters.create(self.payload(site="solar2"))
        self.assertTrue(created["active"])
        self.assertEqual(len(FakePopen.instances), 1)
        env = FakePopen.instances[0].env
        self.assertEqual(env["SITE"], "solar2")
        self.assertEqual(env["TRANSPORT"], "tcp")
        self.assertEqual(env["WEBAPP"], "0")
        self.assertEqual(env["API_PORT"], "0")
        # вложенных супервизоров быть не должно
        self.assertEqual(env["INVERTERS_ENABLED"], "0")
        self.assertNotIn("TLS_CERT", env)
        # свои файлы состояния
        self.assertTrue(env["ENERGY_FILE"].endswith("solar2.energy.json"))

    def test_stop_then_supervisor_keeps_it_down(self):
        inverters.create(self.payload(site="solar2"))
        res = inverters.action("solar2", "stop")
        self.assertFalse(res["active"])
        self.assertFalse(res["enabled"])
        # enabled=false в конфиге => супервизор не поднимает процесс
        stored = inverters._read("solar2")
        self.assertFalse(stored["enabled"])

    def test_start_again_and_restart(self):
        inverters.create(self.payload(site="solar2"))
        inverters.action("solar2", "stop")
        res = inverters.action("solar2", "start")
        self.assertTrue(res["active"])
        res = inverters.action("solar2", "restart")
        self.assertTrue(res["active"])

    def test_dead_child_is_restarted_by_supervisor_loop(self):
        inverters.create(self.payload(site="solar2"))
        FakePopen.instances[0]._alive = False       # процесс упал
        item = inverters.listing()[0]
        self.assertFalse(item["active"])
        self.supervisor.start(item)                 # то же, что делает loop()
        self.assertTrue(self.supervisor.state("solar2", item)["active"])
        self.assertEqual(len(FakePopen.instances), 2)

    def test_remove_kills_process(self):
        inverters.create(self.payload(site="solar2"))
        proc = FakePopen.instances[0]
        inverters.remove("solar2")
        self.assertFalse(proc._alive)
        self.assertEqual(inverters.listing(), [])

    def test_mode_off_disables_feature(self):
        self.mode.stop()                 # снять подмену resolved_mode
        self.sup.stop()                  # и подмену supported
        with mock.patch.dict(os.environ, {"INVERTERS_MODE": "off"}):
            self.assertEqual(inverters.resolved_mode(), "off")
            self.assertFalse(inverters.supported())


REAL_LISTDIR = os.listdir


def dev_listdir(nodes):
    """os.listdir-заглушка только для /dev (каталог конфигов остаётся настоящим)."""
    def fake(path="/"):
        if str(path).rstrip("/") == "/dev":
            return list(nodes)
        return REAL_LISTDIR(path)
    return fake


class HidDeviceTests(InverterTestCase):
    """У двух инверторов Voltronic одинаковый VID:PID — узлы не должны совпадать."""

    def test_free_node_is_picked(self):
        with mock.patch.object(os, "listdir", dev_listdir(["hidraw0", "hidraw1", "null"])):
            # hidraw0 занят первым инвертором (config.HID_DEVICE)
            self.assertEqual(inverters.free_hid_device(), "/dev/hidraw1")

    def test_pick_skips_nodes_of_other_inverters(self):
        inverters.create(self.payload(site="second", mode="hid", hid_device="/dev/hidraw1"))
        with mock.patch.object(os, "listdir", dev_listdir(["hidraw0", "hidraw1", "hidraw2"])):
            self.assertEqual(inverters.free_hid_device(), "/dev/hidraw2")

    def test_no_free_node_raises(self):
        with mock.patch.object(os, "listdir", dev_listdir(["hidraw0"])):
            with self.assertRaises(inverters.InverterError):
                inverters.normalize(self.payload(mode="hid"))

    def test_busy_node_is_rejected(self):
        with mock.patch.object(os, "listdir", dev_listdir(["hidraw0", "hidraw1"])):
            with self.assertRaises(inverters.InverterError):
                inverters.normalize(self.payload(mode="hid", hid_device=config.HID_DEVICE))

    def test_udev_alias_of_busy_node_is_rejected(self):
        alias = os.path.realpath(config.HID_DEVICE)
        with self.assertRaises(inverters.InverterError):
            inverters.normalize(self.payload(mode="hid", hid_device=alias))
