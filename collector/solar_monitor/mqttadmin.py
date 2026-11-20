"""MQTT из интерфейса: свой брокер, подключения к чужим и параметры публикации.

Раньше всё это жило только в `.env` и в конфигах mosquitto — то есть правилось
руками по SSH. Здесь один экран на три вещи:

* **Своё подключение** («куда публикует этот коллектор»): host/port/логин/пароль/
  TLS/префикс. Сохраняется в `MQTT_OVERRIDE_FILE` (по умолчанию `/data/mqtt.json`),
  читается в `config.py` при старте, после сохранения процесс перезапускается.
  Работает и на нативном хосте, и в Docker.

* **Брокер на этом хосте**: состояние (сервис, слушающие порты, число клиентов),
  анонимный доступ и пользователи. Нативно — через узкий helper `mqtt-ctl`
  (root + правило sudoers). В Docker брокером управляет хост, поэтому раздел
  только для чтения — это честно показывается в UI.

* **Мосты (подключения к другим брокерам)**: CRUD, направление `in`/`out`/`both`
  и фильтр топиков. Тоже через helper, только нативно.
"""
from __future__ import annotations

import json
import logging
import os
import re
import subprocess
import threading
import time

from . import config

log = logging.getLogger("mqttadmin")

BRIDGE_NAME_RE = re.compile(r"^[a-z][a-z0-9_-]{1,23}$")
DIRECTIONS = ("in", "out", "both")
TOPIC_RE = re.compile(r"^[A-Za-z0-9_+#/\-\.]{1,120}$")

#: host:port — только буквы/цифры/точки/двоеточия, без пробелов и кавычек
ADDRESS_RE = re.compile(r"^[A-Za-z0-9\.\-]{1,120}(:\d{1,5})?$")


class MqttError(ValueError):
    """Ошибка валидации/выполнения — текст показывается в UI."""


# --------------------------------------------------------------------------- #
# helper и признак «нативный хост»
# --------------------------------------------------------------------------- #
def helper_path() -> str:
    return os.getenv("MQTT_HELPER", "/usr/local/lib/solar-monitor/mqtt-ctl")


def native_available() -> bool:
    """Можно ли управлять брокером отсюда (нативный хост + helper + sudo)."""
    return os.path.isdir("/run/systemd/system") and os.path.exists(helper_path())


def _helper(*args: str, stdin: str | None = None, timeout: float = 30.0) -> dict:
    if not native_available():
        raise MqttError("управление брокером доступно только на нативном хосте "
                        f"(в контейнере брокер живёт снаружи; нужен {helper_path()})")
    cmd = ["sudo", "-n", helper_path(), *args]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              input=stdin, timeout=timeout)
    except (OSError, subprocess.SubprocessError) as ex:
        raise MqttError(f"helper не запустился: {ex!r}") from ex
    out = (proc.stdout or "").strip()
    try:
        data = json.loads(out.splitlines()[-1]) if out else {}
    except (ValueError, IndexError) as ex:
        raise MqttError(f"helper вернул не JSON: {out[:200] or proc.stderr[:200]}") from ex
    if proc.returncode != 0 or data.get("error"):
        raise MqttError(str(data.get("error") or (proc.stderr or "").strip() or
                            f"код {proc.returncode}"))
    return data


# --------------------------------------------------------------------------- #
# своё подключение (файл-оверрайд, применяется при старте процесса)
# --------------------------------------------------------------------------- #
def own() -> dict:
    """Текущие параметры публикации (+ признак, что они из UI)."""
    overridden = False
    try:
        with open(config.MQTT_OVERRIDE_FILE, encoding="utf-8") as f:
            overridden = bool(json.load(f))
    except (OSError, ValueError):
        overridden = False
    return {
        "host": config.MQTT_HOST,
        "port": config.MQTT_PORT,
        "user": config.MQTT_USER or "",
        "has_password": bool(config.MQTT_PASS),
        "prefix": config.MQTT_PREFIX,
        "tls": bool(config.MQTT_TLS),
        "discovery": bool(config.HA_DISCOVERY),
        "override_file": config.MQTT_OVERRIDE_FILE,
        "overridden": overridden,
    }


def save_own(payload: dict, restart: bool = True) -> dict:
    """Сохранить параметры публикации и (опционально) перезапустить процесс."""
    host = str(payload.get("host") or "").strip()
    if not ADDRESS_RE.match(host) or "/" in host:
        raise MqttError("хост: буквы/цифры/точки/дефис, без схемы и слэшей")
    try:
        port = int(payload.get("port") or 1883)
    except (TypeError, ValueError) as ex:
        raise MqttError("порт должен быть числом") from ex
    if not 1 <= port <= 65535:
        raise MqttError("порт вне диапазона 1..65535")

    prefix = str(payload.get("prefix") or config.MQTT_PREFIX).strip().rstrip("/")
    if not TOPIC_RE.match(prefix) or prefix.endswith("#") or prefix.endswith("+"):
        raise MqttError("префикс топиков: только буквы/цифры/`/_-`, без `#` и `+`")

    path = config.MQTT_OVERRIDE_FILE
    # берём текущий файл за основу: пароль из UI не возвращается, поэтому
    # «пустое поле» должно означать «оставить как было», а не «стереть»
    try:
        with open(path, encoding="utf-8") as f:
            data: dict = json.load(f)
    except (OSError, ValueError):
        data = {}
    data.update({"host": host, "port": port, "prefix": prefix,
                 "tls": bool(payload.get("tls")),
                 "discovery": bool(payload.get("discovery", True))})
    data["user"] = str(payload.get("user") or "").strip()
    password = payload.get("password")
    if password == "-":
        data["password"] = ""
    elif password:
        data["password"] = str(password)
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, ensure_ascii=False)
    os.chmod(tmp, 0o600)
    os.replace(tmp, path)
    log.info("mqtt: сохранены параметры публикации %s:%s (restart=%s)", host, port, restart)
    if restart:
        _schedule_restart()
    return {"saved": data | {"password": "***" if data.get("password") else ""},
            "restarting": restart}


def _schedule_restart():
    """Перезапуск процесса: systemd (Restart=always) или docker (unless-stopped)."""

    def _die():
        time.sleep(1.2)
        log.warning("mqtt: перезапуск коллектора с новыми параметрами")
        os._exit(0)

    threading.Thread(target=_die, daemon=True, name="mqtt-restart").start()


# --------------------------------------------------------------------------- #
# брокер на этом хосте
# --------------------------------------------------------------------------- #
def broker_status() -> dict | None:
    if not native_available():
        return None
    try:
        return _helper("status")
    except MqttError as ex:
        return {"error": str(ex)}


def broker_action(op: str, payload: dict | None = None) -> dict:
    payload = payload or {}
    if op == "anonymous":
        return _helper("broker-anonymous", "on" if payload.get("on") else "off")
    if op == "restart":
        return _helper("restart")
    if op == "user-add":
        user = str(payload.get("user") or "").strip()
        password = str(payload.get("password") or "")
        if not re.match(r"^[A-Za-z0-9_\-\.]{1,32}$", user):
            raise MqttError("логин: буквы/цифры/_/-/. до 32 символов")
        if len(password) < 6:
            raise MqttError("пароль короче 6 символов")
        return _helper("broker-user-add", user, password)
    if op == "user-del":
        user = str(payload.get("user") or "").strip()
        if not user:
            raise MqttError("не указан логин")
        return _helper("broker-user-del", user)
    raise MqttError(f"неизвестная операция {op!r}")


# --------------------------------------------------------------------------- #
# мосты (подключения к другим брокерам)
# --------------------------------------------------------------------------- #
def bridge_conf(bridge: dict) -> str:
    """Собрать конфиг моста mosquitto по данным из UI."""
    name = bridge["name"]
    address = bridge["address"]
    if not ADDRESS_RE.match(address):
        raise MqttError("адрес: host или host:port, без схемы и слэшей")
    if ":" not in address:
        address = f"{address}:1883"
    pattern = str(bridge.get("pattern") or "solar/#").strip()
    if not TOPIC_RE.match(pattern):
        raise MqttError("фильтр топиков: только буквы/цифры/`/_-+#.`")
    direction = str(bridge.get("direction") or "out").lower()
    if direction not in DIRECTIONS:
        raise MqttError("направление: in / out / both")
    lines = [
        f"# мост «{name}», создан из UI solar-monitor",
        f"connection {name}",
        f"address {address}",
        f"remote_clientid solar-{config.SITE}-{name}",
        "cleansession true",
        "try_private false",          # без mosquitto-расширений: работает с любым брокером
        "notifications false",
        "restart_timeout 30",
    ]
    user = str(bridge.get("username") or "").strip()
    if user:
        lines.append(f"remote_username {user}")
        password = bridge.get("password")
        if password:
            lines.append(f"remote_password {password}")
    lines.append(f"topic {pattern} {direction} 0")
    return "\n".join(lines) + "\n"


def bridges() -> list[dict]:
    if not native_available():
        return []
    data = _helper("bridge-list")
    return list(data.get("bridges") or [])


def bridge_save(payload: dict) -> dict:
    name = str(payload.get("name") or "").strip().lower()
    if not BRIDGE_NAME_RE.match(name):
        raise MqttError("имя: 2–24 символа, строчная латиница/цифры/_/-, с буквы")
    conf = bridge_conf({**payload, "name": name})
    return _helper("bridge-save", name, stdin=conf)


def bridge_delete(name: str) -> dict:
    if not BRIDGE_NAME_RE.match(name):
        raise MqttError(f"недопустимое имя моста {name!r}")
    return _helper("bridge-delete", name)


# --------------------------------------------------------------------------- #
# сводка для страницы
# --------------------------------------------------------------------------- #
def snapshot(connected: bool | None = None, error: str | None = None) -> dict:
    native = native_available()
    out: dict = {
        "own": own(),
        "native": native,
        "helper": helper_path(),
        "broker": broker_status(),
        "bridges": bridges() if native else [],
        "connected": connected,
        "error": error,
    }
    return out
