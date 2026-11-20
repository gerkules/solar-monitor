"""Environment configuration (all settings come from env / .env file)."""
from __future__ import annotations

import json
import os


def _bool(name: str, default: bool = False) -> bool:
    return os.getenv(name, str(default)).strip().lower() in ("1", "true", "yes", "on")


def _int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


# ---- identity ---------------------------------------------------------------
SITE = os.getenv("SITE", "office")                 # short site id, e.g. office / home
DEVICE_NAME = os.getenv("DEVICE_NAME", "Inverter")
DEVICE_MODEL = os.getenv("DEVICE_MODEL", "PI30 inverter")
MQTT_PREFIX = os.getenv("MQTT_PREFIX", f"solar/{SITE}").rstrip("/")
# Root under which every site publishes (solar/home/state, solar/office/state):
# the UI watches this wildcard, so one container can show all sites.
SITE_ROOT = os.getenv("SITE_ROOT") or "/".join(MQTT_PREFIX.split("/")[:-1]) or "solar"
STATE_RETAIN = _bool("STATE_RETAIN", True)     # keeps the last state per site on the broker
SITE_TTL = _float("SITE_TTL", 900.0)
# {"office": "http://192.168.1.50:8081"} — чтобы один UI мог открывать настройки/подключение
# другого сайта (у каждого коллектора свой транспорт и свои уставки)
PEER_SITES = json.loads(os.getenv("PEER_SITES") or "{}")          # forget a site that has not published for N s
HA_PREFIX = os.getenv("HA_DISCOVERY_PREFIX", "homeassistant")
HA_DISCOVERY = _bool("HA_DISCOVERY", True)
ENTITY_PREFIX = os.getenv("ENTITY_PREFIX", "solar_" + SITE)   # HA entity id prefix

# ---- transport --------------------------------------------------------------
TRANSPORT = os.getenv("TRANSPORT", "tcp").lower()   # hid | serial | tcp | mqtt

# tcp / mqtt (EW10 dongle, ser2net, ESP32 gateway, usbip...)
TCP_HOST = os.getenv("TCP_HOST", "192.168.1.60")
TCP_PORT = _int("TCP_PORT", 9999)
TCP_KEEPALIVE = _bool("TCP_KEEPALIVE", True)

# serial (USB-RS232 / RS485 adapter)
SERIAL_PORT = os.getenv("SERIAL_PORT", "/dev/ttyUSB0")
SERIAL_BAUD = _int("SERIAL_BAUD", 2400)

# usb-hid (inverter USB port). Either the hidraw node or vendor:product via hidapi.
HID_DEVICE = os.getenv("HID_DEVICE", "/dev/hidraw0")
HID_VID = int(os.getenv("HID_VID", "0x0665"), 0)
HID_PID = int(os.getenv("HID_PID", "0x5161"), 0)
HID_REPORT_ID = _int("HID_REPORT_ID", 0)

# "sa-mqtt" transport: import a running SolarAssistant installation instead of
# talking to the inverter (its USB port belongs to SolarAssistant).
SA_MQTT_HOST = os.getenv("SA_MQTT_HOST", "127.0.0.1")
SA_MQTT_PORT = _int("SA_MQTT_PORT", 1883)
SA_MQTT_USER = os.getenv("SA_MQTT_USER") or None
SA_MQTT_PASS = os.getenv("SA_MQTT_PASS") or None

# mqtt transport: the EW10 dongle publishes replies on <prefix>/data
TRANS_TOPIC = os.getenv("TRANS_TOPIC", "inverter/")

# ---- polling ----------------------------------------------------------------
POLL_INTERVAL = _float("POLL_INTERVAL", 5.0)        # QPIGS
QMOD_INTERVAL = _float("QMOD_INTERVAL", 60.0)
QPIRI_INTERVAL = _float("QPIRI_INTERVAL", 600.0)
QPIWS_INTERVAL = _float("QPIWS_INTERVAL", 60.0)
QBMS_INTERVAL = _float("QBMS_INTERVAL", 60.0)   # lithium BMS data from the inverter
# Safety net: changing the inverter's BMS protocol can cut the battery link. When
# enabled, a new protocol must prove itself (QBMS "Connected") within N seconds,
# otherwise the previous protocol is restored automatically.
# OFF by default: the inverter protects itself (error R61/R69 on its display, no
# charging, may drop the AC output) and the error clears only when a correct
# protocol — or User/AGM — is selected. Reverting automatically can undo a correct
# choice made on purpose, so the default is "show the problem, let the owner pick".
BATTERY_TYPE_ROLLBACK = _bool("BATTERY_TYPE_ROLLBACK", False)
# A correct protocol reconnects the battery in ~20-30 s, so the check window must
# be a bit longer than that. With a wrong protocol the inverter blocks charging,
# so it should not be much longer either.
BATTERY_TYPE_ROLLBACK_AFTER = _float("BATTERY_TYPE_ROLLBACK_AFTER", 45.0)
# How long a lost BMS link may stay down before we raise the R61/R69 alarm.
# Manual (code 62): buzzer after 3 min without BMS data, charging stops after 10 min
BMS_LINK_ALERT_AFTER = _float("BMS_LINK_ALERT_AFTER", 180.0)
BMS_EVENTS_FILE = os.getenv("BMS_EVENTS_FILE", "/data/bms_events.json")
HAS_MPPT2 = _bool("HAS_MPPT2", True)                # poll QPIGS2
OFFLINE_AFTER = _float("OFFLINE_AFTER", 120.0)
GRID_DEADBAND = _float("GRID_DEADBAND", 50.0)
ALLOW_SETTINGS = _bool("ALLOW_SETTINGS", True)

# ---- mqtt broker (publish) --------------------------------------------------
MQTT_HOST = os.getenv("MQTT_HOST", "127.0.0.1")
MQTT_PORT = _int("MQTT_PORT", 1883)
MQTT_USER = os.getenv("MQTT_USER") or None
MQTT_PASS = os.getenv("MQTT_PASS") or None
MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"solar-monitor-{SITE}")
MQTT_TLS = _bool("MQTT_TLS", False)

# Правки из UI (страница «MQTT»): значения перекрывают .env. Файл читается при
# импорте конфига, поэтому после сохранения процесс перезапускается.
MQTT_OVERRIDE_FILE = os.getenv("MQTT_OVERRIDE_FILE", "/data/mqtt.json")


def _apply_mqtt_override() -> None:
    global MQTT_HOST, MQTT_PORT, MQTT_USER, MQTT_PASS, MQTT_TLS, MQTT_PREFIX, \
        MQTT_CLIENT_ID, SITE_ROOT, HA_DISCOVERY
    try:
        with open(MQTT_OVERRIDE_FILE, encoding="utf-8") as f:
            data = json.load(f)
    except (OSError, ValueError):
        return
    if not isinstance(data, dict):
        return
    if data.get("host"):
        MQTT_HOST = str(data["host"])
    if data.get("port"):
        MQTT_PORT = int(data["port"])
    if "user" in data:
        MQTT_USER = data.get("user") or None
    if "password" in data:
        MQTT_PASS = data.get("password") or None
    if "tls" in data:
        MQTT_TLS = bool(data["tls"])
    if data.get("prefix"):
        MQTT_PREFIX = str(data["prefix"]).rstrip("/")
        SITE_ROOT = "/".join(MQTT_PREFIX.split("/")[:-1]) or "solar"
    if "discovery" in data:
        HA_DISCOVERY = bool(data["discovery"])
    MQTT_CLIENT_ID = os.getenv("MQTT_CLIENT_ID", f"solar-monitor-{SITE}")


_apply_mqtt_override()

# ---- influxdb 2.x -----------------------------------------------------------
# "2" = InfluxDB 2.x (token + Flux), "1.8" = InfluxDB 1.x (InfluxQL, no token).
# 1.8 is what SolarAssistant itself ships and it is the only one that runs on
# Synology's old kernel: 2.x hangs in D-state on bolt/btrfs there.
INFLUX_MODE = os.getenv("INFLUX_MODE", "2")
INFLUX_DB = os.getenv("INFLUX_DB", os.getenv("INFLUX_BUCKET", "solar"))
INFLUX_AUTH = os.getenv("INFLUX_AUTH", "")      # "user:pass" if 1.8 auth is on
INFLUX_URL = os.getenv("INFLUX_URL", "http://influxdb:8086")
INFLUX_TOKEN = os.getenv("INFLUX_TOKEN", "")
INFLUX_ORG = os.getenv("INFLUX_ORG", "solar")
INFLUX_BUCKET = os.getenv("INFLUX_BUCKET", "solar")
INFLUX_MEASUREMENT_PREFIX = os.getenv("INFLUX_MEASUREMENT_PREFIX", "")

# ---- http api ---------------------------------------------------------------
API_HOST = os.getenv("API_HOST", "0.0.0.0")
API_PORT = _int("API_PORT", 8080)
# Веб-интерфейс можно выключить: слабое железо (Raspberry Pi 1/Zero, роутер) без
# FastAPI/pydantic, только MQTT-публикация. API_PORT=0 тоже выключает UI.
WEBAPP_ENABLED = _bool("WEBAPP", API_PORT > 0)
API_TOKEN = os.getenv("API_TOKEN") or None
# Optional HTTP Basic auth for the UI and the API (empty = open, LAN-only deployment).
AUTH_USER = os.getenv("AUTH_USER") or None
AUTH_PASSWORD = os.getenv("AUTH_PASSWORD") or None

# Смена пароля из UI: файл перекрывает AUTH_USER/AUTH_PASSWORD из .env
AUTH_FILE = os.getenv("AUTH_FILE", "/data/auth.json")

# ---- HTTPS (опционально) ----------------------------------------------------
# Если заданы оба пути — поднимается дополнительный HTTPS-листенер.
#   TLS_CERT/TLS_KEY + API_HTTPS_PORT -> HTTP на API_PORT и HTTPS на API_HTTPS_PORT
#   FORCE_HTTPS=true                -> только HTTPS (на API_PORT)
TLS_CERT = os.getenv("TLS_CERT") or None
TLS_KEY = os.getenv("TLS_KEY") or None
API_HTTPS_PORT = _int("API_HTTPS_PORT", 0)
FORCE_HTTPS = _bool("FORCE_HTTPS", False)
# Проверять сертификат соседнего сайта (self-signed -> обычно false)
PEER_TLS_VERIFY = _bool("PEER_TLS_VERIFY", False)

# ---- battery monitoring (source selection, like SolarAssistant) -------------
# inverter | emulated | jbd | pylontech | modbus | vedirect | can
# A selection made in the UI is stored in BATTERY_CONFIG_FILE and wins over env.
BATTERY_CONFIG_FILE = os.getenv("BATTERY_CONFIG_FILE", "/data/battery.json")
# Транспорт, выбранный в UI, хранится здесь и перекрывает TRANSPORT из .env
CONNECTION_FILE = os.getenv("CONNECTION_FILE", "/data/connection.json")

# ---- второй и последующие инверторы на одном хосте --------------------------
# Каждый доп. инвертор = отдельный процесс solar-collector@<site>.service,
# его конфиг лежит в INVERTERS_DIR (<site>.json + <site>.env).
INVERTERS_DIR = os.getenv("INVERTERS_DIR", "/data/inverters")
INVERTERS_ENABLED = _bool("INVERTERS_ENABLED", True)
BATTERY_SOURCE = os.getenv("BATTERY_SOURCE", "inverter").lower()
BMS_PORT = os.getenv("BMS_PORT", "/dev/ttyUSB1")
BMS_BAUD = _int("BMS_BAUD", 9600)
BMS_UNIT_ID = _int("BMS_UNIT_ID", 1)
BMS_INTERVAL = _float("BMS_INTERVAL", 10)
BMS_CAN_INTERFACE = os.getenv("BMS_CAN_INTERFACE", "can0")
BMS_NTC_COUNT = _int("BMS_NTC_COUNT", 2)
BMS_JBD_TEMP = os.getenv("BMS_JBD_TEMP", "offset40")   # offset40 | 0.1k | 0.1k16
BATTERY_CAPACITY_AH = _float("BATTERY_CAPACITY_AH", 0) or None
BATTERY_NOMINAL_V = _float("BATTERY_NOMINAL_V", 48.0)

# ---- automation rules -------------------------------------------------------
RULES_FILE = os.getenv("RULES_FILE", "/data/rules.json")
AUTOMATION = _bool("AUTOMATION", True)

# ---- notifications ----------------------------------------------------------
TELEGRAM_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN") or None
TELEGRAM_CHAT = os.getenv("TELEGRAM_CHAT_ID") or None
WEBHOOK_URL = os.getenv("WEBHOOK_URL") or None
NOTIFY_MQTT_TOPIC = os.getenv("NOTIFY_MQTT_TOPIC") or f"{MQTT_PREFIX}/notify"
NOTIFY_MIN_INTERVAL = _float("NOTIFY_MIN_INTERVAL", 60)   # per channel, seconds

# ---- PV forecast (forecast.solar) -------------------------------------------
FORECAST_ENABLED = _bool("FORECAST_ENABLED", False)
FORECAST_LAT = os.getenv("FORECAST_LAT", "")
FORECAST_LON = os.getenv("FORECAST_LON", "")
FORECAST_KWP = os.getenv("FORECAST_KWP", "")
FORECAST_DECLINATION = _int("FORECAST_DECLINATION", 30)
FORECAST_AZIMUTH = _int("FORECAST_AZIMUTH", 0)
FORECAST_INTERVAL = _float("FORECAST_INTERVAL", 3600)
# бесплатный тариф forecast.solar: ~12 запросов в час на IP, поэтому кешируем на диск
FORECAST_CACHE_FILE = os.getenv("FORECAST_CACHE_FILE", "/data/forecast.json")

# ---- misc -------------------------------------------------------------------
ENERGY_FILE = os.getenv("ENERGY_FILE", "/data/energy.json")
STATE_FILE = os.getenv("STATE_FILE", "/data/state.json")
TEMP_UNIT = os.getenv("TEMP_UNIT", "C").upper()      # C | F
LOG_LEVEL = os.getenv("LOG_LEVEL", "INFO").upper()
SAMPLE_JSON = _bool("SAMPLE_JSON", False)            # log every published state


def bms_config() -> dict:
    """Driver configuration assembled from env (+ optional BMS_MODBUS JSON)."""
    cfg = {
        "port": BMS_PORT, "baud": BMS_BAUD, "unit_id": BMS_UNIT_ID,
        "capacity_ah": BATTERY_CAPACITY_AH, "nominal_voltage": BATTERY_NOMINAL_V,
        "interval": BMS_INTERVAL, "interface": BMS_CAN_INTERFACE,
        "ntc_count": BMS_NTC_COUNT, "temp_mode": BMS_JBD_TEMP,
    }
    raw = os.getenv("BMS_MODBUS")
    if raw:
        try:
            cfg["registers"] = json.loads(raw)
        except json.JSONDecodeError:
            pass
    return cfg


def settings_override() -> dict:
    """Per-firmware tweaks, e.g. SETTINGS_JSON='{"max_charge_current": {"cmd": "MCHGC{:03d}"}}'.

    Anything here patches pi30.SETTINGS (cmd template / writeable flag / field).
    """
    raw = os.getenv("SETTINGS_JSON")
    if not raw:
        return {}
    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {}
