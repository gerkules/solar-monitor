"""Второй (и далее) инвертор на одном хосте.

Один инвертор = один процесс-коллектор со своим ``SITE`` и своим топиком
``solar/<site>/state``. UI и так умеет показывать несколько площадок
(мультисайт-реестр в `sites.py`), но добавить вторую площадку было негде —
только руками: скопировать unit, править `.env`, запускать сервис.

Здесь это делается из интерфейса:

* конфигурация доп. инвертора — ``<INVERTERS_DIR>/<site>.json``;
* переменные окружения для его процесса — ``<INVERTERS_DIR>/<site>.env``
  (база наследуется из основного `.env` через `EnvironmentFile=-` в шаблонном
  unit, поэтому креды брокера и прочие общие настройки не дублируются);
* процесс — ``solar-collector@<site>.service`` (systemd-шаблон);
* привилегированные действия (start/stop/enable) идут через узкий helper
  ``inverter-ctl`` с правилом sudoers — см. ``deploy/pi/``.

В Docker-режиме (нет systemd) модуль честно отвечает ``supported: false``.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import sys
import time

from . import config

log = logging.getLogger("inverters")

#: допустимый id площадки: с латинской буквы, дальше буквы/цифры/`_`/`-`
SITE_RE = re.compile(r"^[a-z][a-z0-9_-]{1,23}$")

#: операции, которые разрешает helper
OPS = ("start", "stop", "restart", "enable", "disable", "reset-failed",
       "is-active", "is-enabled")

ENV_FIELDS = ("tcp_host", "tcp_port", "serial_port", "serial_baud",
              "hid_device", "trans_topic")

#: файлы состояния, которые у каждого инвертора должны быть свои
STATE_FILES = ("CONNECTION_FILE", "BATTERY_CONFIG_FILE", "RULES_FILE",
               "FORECAST_CACHE_FILE", "ENERGY_FILE", "STATE_FILE",
               "BMS_EVENTS_FILE", "AUTH_FILE")


class InverterError(ValueError):
    """Ошибка валидации или управления — текст показывается в UI."""


# --------------------------------------------------------------------------- #
# пути и утилиты
# --------------------------------------------------------------------------- #
def directory() -> str:
    return config.INVERTERS_DIR


def unit_name(site: str) -> str:
    return f"solar-collector@{site}.service"


def _json_path(site: str) -> str:
    return os.path.join(directory(), f"{site}.json")


def _env_path(site: str) -> str:
    return os.path.join(directory(), f"{site}.env")


def supported() -> bool:
    """Есть ли systemd и права писать в каталог конфигов."""
    if not config.INVERTERS_ENABLED:
        return False
    if not os.path.isdir("/run/systemd/system"):
        return False
    return os.path.isdir(directory()) and os.access(directory(), os.W_OK)


def _supervisor_cmd() -> list[str]:
    raw = os.getenv("SUPERVISOR_CMD", "sudo -n /usr/local/lib/solar-monitor/inverter-ctl")
    return raw.split()


def _systemctl(op: str, site: str, timeout: float = 25.0) -> tuple[int, str]:
    """Выполнить операцию над unit'ом (через helper, если мы не root)."""
    cmd = [*_supervisor_cmd(), op, unit_name(site)]
    if os.geteuid() == 0:
        cmd = ["systemctl", op, unit_name(site)]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as ex:
        return 1, repr(ex)
    return proc.returncode, (proc.stdout or proc.stderr or "").strip()


def _unit_state(site: str) -> dict:
    active_rc, active_out = _systemctl("is-active", site, timeout=10)
    enabled_rc, enabled_out = _systemctl("is-enabled", site, timeout=10)
    return {"active": active_out.startswith("active") if active_out else False,
            "enabled": enabled_out.split()[0] == "enabled" if enabled_out else False,
            "state": active_out or "unknown"}


# --------------------------------------------------------------------------- #
# валидация и генерация конфигурации
# --------------------------------------------------------------------------- #
def _mode_fields(mode: str) -> tuple[str, ...]:
    from . import connection as conn_mod
    if mode not in conn_mod.MODES:
        raise InverterError(f"неизвестный способ подключения {mode!r}")
    return tuple(conn_mod.MODES[mode]["fields"])


def normalize(payload: dict) -> dict:
    """Проверить данные из UI и привести к каноническому виду."""
    from . import connection as conn_mod
    site = str(payload.get("site") or "").strip().lower()
    if not SITE_RE.match(site):
        raise InverterError("id площадки: 2–24 символа, латиница/цифры/_/-, "
                            "начинается с буквы (например garage)")
    if site == config.SITE:
        raise InverterError(f"id {site!r} уже занят этим инвертором")
    if site == "all":
        raise InverterError("id 'all' зарезервирован")

    mode = str(payload.get("mode") or "").strip().lower()
    _mode_fields(mode)                       # валидация режима и его полей
    if mode == "hid" and not str(payload.get("hid_device") or "").strip():
        # удобный дефолт: стабильное имя из udev-правила, если оно есть
        payload = {**payload, "hid_device": config.HID_DEVICE}

    item = {
        "site": site,
        "label": str(payload.get("label") or site).strip()[:60] or site,
        "mode": mode,
        "webapp": bool(payload.get("webapp")),
        "api_port": int(payload.get("api_port") or 0),
        "poll_interval": float(payload.get("poll_interval") or config.POLL_INTERVAL),
    }
    for key in ENV_FIELDS:
        item[key] = payload.get(key, conn_mod.DEFAULTS.get(key))
    if mode == "tcp":
        item["tcp_host"] = str(item.get("tcp_host") or "").strip()
        item["tcp_port"] = int(item.get("tcp_port") or 9999)
        if not item["tcp_host"]:
            raise InverterError("для TCP нужен хост донгла/шлюза")
    if mode == "serial":
        item["serial_port"] = str(item.get("serial_port") or "").strip()
        item["serial_baud"] = int(item.get("serial_baud") or 2400)
        if not item["serial_port"]:
            raise InverterError("для serial нужен порт адаптера (/dev/ttyUSB0)")
    if mode == "hid":
        item["hid_device"] = str(item.get("hid_device") or "").strip()
        if not item["hid_device"]:
            raise InverterError("для USB-HID нужен hidraw-узел")
    if mode == "mqtt":
        item["trans_topic"] = str(item.get("trans_topic") or "").strip() or "inverter/"
    return item


def env_text(item: dict) -> str:
    """Содержимое `<site>.env`: только отличия от основного `.env`."""
    site = item["site"]
    base = directory()
    lines = [
        "# сгенерировано solar-monitor (страница «Инверторы»), правки затрутся",
        f"SITE={site}",
        f"MQTT_PREFIX=solar/{site}",
        f"ENTITY_PREFIX=solar_{site}",
        f"DEVICE_NAME={item['label']}",
        f"TRANSPORT={item['mode']}",
        f"POLL_INTERVAL={item['poll_interval']:g}",
    ]
    for name in STATE_FILES:
        lines.append(f"{name}={os.path.join(base, site + '.' + name.lower().replace('_file', '') + '.json')}")
    if item["mode"] == "tcp":
        lines += [f"TCP_HOST={item['tcp_host']}", f"TCP_PORT={item['tcp_port']}"]
    elif item["mode"] == "serial":
        lines += [f"SERIAL_PORT={item['serial_port']}", f"SERIAL_BAUD={item['serial_baud']}"]
    elif item["mode"] == "hid":
        lines += [f"HID_DEVICE={item['hid_device']}"]
    elif item["mode"] == "mqtt":
        lines += [f"TRANS_TOPIC={item['trans_topic']}"]
    if item.get("webapp") and item.get("api_port"):
        lines += ["WEBAPP=1", f"API_PORT={item['api_port']}"]
    else:
        # лишний веб-сервер на Pi 1 съедает RAM и порт: по умолчанию выключен
        lines += ["WEBAPP=0", "API_PORT=0"]
    return "\n".join(lines) + "\n"


def probe_payload(item: dict, timeout: float = 40.0) -> dict:
    """Проверить связь с инвертором в отдельном процессе.

    Отдельный процесс важен: `connection.probe()` правит глобальный `config`,
    и в основном процессе это сбило бы транспорт работающего коллектора.
    """
    cfg = {"mode": item["mode"], **{k: item[k] for k in ENV_FIELDS}}
    code = ("import json, os, sys;"
            "from solar_monitor import connection;"
            "print(json.dumps(connection.probe(json.loads(os.environ['PROBE_CFG']))))")
    env = dict(os.environ, PROBE_CFG=json.dumps(cfg))
    env.update({k: str(v) for k, v in _env_pairs(item)})
    cwd = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    try:
        proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                              text=True, timeout=timeout, env=env, cwd=cwd)
    except (OSError, subprocess.SubprocessError) as ex:
        return {"ok": False, "error": f"проверка не запустилась: {ex!r}"}
    out = (proc.stdout or "").strip().splitlines()
    if not out:
        return {"ok": False, "error": (proc.stderr or "пустой ответ").strip()[-400:]}
    try:
        return json.loads(out[-1])
    except json.JSONDecodeError:
        return {"ok": False, "error": out[-1][:400]}


def _env_pairs(item: dict) -> list[tuple[str, str]]:
    pairs = [("SITE", item["site"]),
             ("MQTT_PREFIX", f"solar/{item['site']}"),
             ("DEVICE_NAME", item["label"]),
             ("TRANSPORT", item["mode"])]
    if item["mode"] == "tcp":
        pairs += [("TCP_HOST", item["tcp_host"]), ("TCP_PORT", str(item["tcp_port"]))]
    elif item["mode"] == "serial":
        pairs += [("SERIAL_PORT", item["serial_port"]),
                  ("SERIAL_BAUD", str(item["serial_baud"]))]
    elif item["mode"] == "hid":
        pairs += [("HID_DEVICE", item["hid_device"])]
    elif item["mode"] == "mqtt":
        pairs += [("TRANS_TOPIC", item["trans_topic"])]
    return pairs


# --------------------------------------------------------------------------- #
# файлы
# --------------------------------------------------------------------------- #
def _read(site: str) -> dict | None:
    try:
        with open(_json_path(site), encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        return None
    except (OSError, json.JSONDecodeError) as ex:
        log.warning("не читается конфиг инвертора %s: %r", site, ex)
        return None


def _write_files(item: dict):
    """Записать `<site>.json` и `<site>.env` (атомарно, 0640)."""
    os.makedirs(directory(), exist_ok=True)
    data = dict(item, updated=time.time())
    for path, text in ((_json_path(item["site"]), json.dumps(data, indent=2, ensure_ascii=False)),
                       (_env_path(item["site"]), env_text(item))):
        tmp = path + ".tmp"
        with open(tmp, "w", encoding="utf-8") as f:
            f.write(text + ("" if text.endswith("\n") else "\n"))
        os.chmod(tmp, 0o640)
        os.replace(tmp, path)


def _remove_files(site: str):
    for path in (_json_path(site), _env_path(site)):
        try:
            os.remove(path)
        except FileNotFoundError:
            pass
    for name in STATE_FILES:
        try:
            os.remove(os.path.join(directory(), f"{site}.{name.lower().replace('_file', '')}.json"))
        except FileNotFoundError:
            pass


# --------------------------------------------------------------------------- #
# публичное API (используется HTTP-роутами)
# --------------------------------------------------------------------------- #
def listing() -> list[dict]:
    """Все доп. инверторы с их состоянием."""
    out = []
    try:
        names = sorted(os.listdir(directory()))
    except OSError:
        return out
    for name in names:
        if not name.endswith(".json"):
            continue
        site = name[:-5]
        if not SITE_RE.match(site):
            continue
        item = _read(site) or {}
        item.setdefault("site", site)
        item.update(_unit_state(site))
        item["env_file"] = _env_path(site)
        out.append(item)
    return out


def snapshot() -> dict:
    return {
        "supported": supported(),
        "enabled": config.INVERTERS_ENABLED,
        "dir": directory(),
        "unit_template": "solar-collector@.service",
        "current_site": config.SITE,
        "inverters": listing(),
        "modes": _modes_public(),
        "ports": _ports_public(),
    }


def _modes_public() -> dict:
    from . import connection as conn_mod
    return conn_mod.MODES


def _ports_public() -> dict:
    from . import connection as conn_mod
    return conn_mod.list_ports()


def create(payload: dict) -> dict:
    if not supported():
        raise InverterError("хост не умеет запускать доп. инверторы "
                            "(нужен systemd и каталог " + directory() + ")")
    item = normalize(payload)
    if _read(item["site"]) is not None:
        raise InverterError(f"инвертор {item['site']!r} уже добавлен")
    _write_files(item)
    rc, out = _systemctl("enable", item["site"])
    if rc != 0:
        _remove_files(item["site"])
        raise InverterError(f"systemd enable не сработал: {out or rc}")
    _systemctl("restart", item["site"])
    log.info("добавлен инвертор %s (%s)", item["site"], item["mode"])
    return {**item, **_unit_state(item["site"])}


def update(site: str, payload: dict) -> dict:
    current = _read(site)
    if current is None:
        raise InverterError(f"инвертора {site!r} нет")
    item = normalize({**current, **payload, "site": site})
    _write_files(item)
    _systemctl("restart", site)
    return {**item, **_unit_state(site)}


def remove(site: str) -> dict:
    if _read(site) is None:
        raise InverterError(f"инвертора {site!r} нет")
    _systemctl("stop", site)
    _systemctl("disable", site)
    _systemctl("reset-failed", site)      # иначе unit остаётся в state=failed
    _remove_files(site)
    log.info("инвертор %s удалён", site)
    return {"ok": True, "site": site}


def action(site: str, op: str) -> dict:
    if op not in OPS:
        raise InverterError(f"неизвестная операция {op!r}")
    if _read(site) is None:
        raise InverterError(f"инвертора {site!r} нет")
    rc, out = _systemctl(op, site)
    return {"ok": rc == 0 or op.startswith("is-"), "site": site, "op": op,
            "result": out, **_unit_state(site)}
