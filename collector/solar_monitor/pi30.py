"""PI30 (Voltronic/Axpert) protocol: framing, parsers, metric table, writable settings.

Frame:  <ascii>: 8N1 2400 baud (serial) / raw TCP / 8-byte reports (USB-HID)
        <body> <crc_hi> <crc_lo> \r      crc = CRC-16/XMODEM
Reply:  ( <ascii body> <crc_hi> <crc_lo> \r    or  (NAK / (ACK / (ERR
"""
from __future__ import annotations

# ---------------------------------------------------------------- framing
def crc_xmodem(data: bytes) -> int:
    crc = 0
    for b in data:
        crc ^= b << 8
        for _ in range(8):
            crc = ((crc << 1) ^ 0x1021) & 0xFFFF if crc & 0x8000 else (crc << 1) & 0xFFFF
    return crc


def frame(cmd: str) -> bytes:
    raw = cmd.encode()
    c = crc_xmodem(raw)
    return raw + bytes([c >> 8, c & 0xFF]) + b"\r"


def check_frame(body: bytes | None) -> bool:
    """True if <body> ends with a valid PI30 crc + CR. (ACK/(NAK replies carry none.)"""
    if not body or len(body) < 4 or not body.endswith(b"\r"):
        return False
    payload, crc = body[:-3], body[-3:-1]
    c = crc_xmodem(payload)
    return bytes([c >> 8, c & 0xFF]) == crc


def is_ack(body: bytes | None) -> bool:
    return bool(body) and body.startswith(b"(ACK")


def is_nak(body: bytes | None) -> bool:
    return bool(body) and body.startswith(b"(NAK")


def strip(body: bytes) -> str:
    """'(' + fields + crc + CR  ->  'fields'"""
    raw = body[:-1] if body.endswith(b"\r") else body
    if len(raw) > 3:
        raw = raw[:-2]          # drop crc
    return raw.decode(errors="replace").strip().lstrip("(")


# ---------------------------------------------------------------- parsers
STATUS_BITS = {
    0: "bus_voltage_steady", 1: "inverter_on", 2: "line_fail", 3: "battery_steady",
    4: "battery_low", 5: "line_steady", 6: "charging", 7: "scc_charging", 8: "ac_charging",
}

# QPIWS warning bits (index -> name). Only the commonly used ones.
WARN_BITS = {
    0: "inverter_fault", 1: "bus_over_voltage", 2: "bus_under_voltage", 3: "bus_soft_start_fail",
    4: "bus_over_current", 5: "bus_short", 6: "inverter_soft_start_fail", 7: "inverter_voltage_too_high",
    8: "inverter_voltage_too_low", 9: "inverter_soft_start_timeout", 10: "inverter_over_current",
    11: "inverter_output_short", 13: "over_temperature", 14: "fan_locked",
    16: "battery_voltage_high", 17: "battery_low_alarm", 18: "battery_under_shutdown",
    19: "battery_derating", 20: "overload", 21: "eeprom_fault", 22: "inverter_over_current2",
    23: "pv_over_voltage", 24: "pv_over_current", 25: "pv_short", 26: "pv_soft_start_fail",
    27: "line_voltage_high", 28: "line_voltage_low", 29: "line_frequency_high",
    30: "line_frequency_low", 31: "line_current_max",
}


def _num(f: list[str], i: int, cast=float):
    try:
        return cast(f[i])
    except (IndexError, ValueError):
        return None


def parse_qpigs(body: bytes) -> dict:
    """General status. 18..21+ fields depending on firmware."""
    f = strip(body).split()
    if len(f) < 17:
        return {}
    d = {
        "grid_voltage": _num(f, 0),
        "grid_frequency": _num(f, 1),
        "ac_output_voltage": _num(f, 2),
        "ac_output_frequency": _num(f, 3),
        "load_apparent_power": _num(f, 4, int),
        "load_power": _num(f, 5, int),
        "load_percentage": _num(f, 6, int),
        "bus_voltage": _num(f, 7),
        "battery_voltage": _num(f, 8),
        "battery_charge_current": _num(f, 9, int),
        "battery_state_of_charge": _num(f, 10, int),
        "temperature": _num(f, 11, int),
        "pv_current_1": _num(f, 12),
        "pv_voltage_1": _num(f, 13),
        "battery_voltage_scc": _num(f, 14),
        "battery_discharge_current": _num(f, 15, int),
        "raw_status": f[16] if len(f) > 16 else "",
    }
    if len(f) > 19:
        d["pv_power_1"] = _num(f, 19, int)
    st = d["raw_status"]
    if st and set(st) <= {"0", "1"}:
        # PI30 prints b7..b0 left to right, so bit 0 is the LAST character.
        # Reading it as a left-to-right binary number (as the old bridge.py did)
        # reports "battery low" on a healthy battery.
        val = int(st[::-1], 2)
        d["status_bits"] = val
        d["status_flags"] = [v for k, v in STATUS_BITS.items() if val & (1 << k)]
    gv = d.get("grid_voltage")
    if gv is not None:
        d["mains_ok"] = 1 if gv > 100 else 0
    return d


def parse_qpigs2(body: bytes) -> dict:
    """Second MPPT: (pv2_current pv2_voltage pv2_power<cr>

    A frame glued together from two replies can pass the crc check, and then
    P = U*I does not hold. Rejecting such frames is what keeps a 11 510 W spike
    out of the history of a 40 W array.
    """
    f = strip(body).split()
    if len(f) < 3:
        return {}
    cur, volt, power = _num(f, 0), _num(f, 1), _num(f, 2, int)
    if None in (cur, volt, power):
        return {}
    expected = cur * volt
    if power > 0 and expected < 1:
        return {}                       # power without voltage or current
    if expected >= 1 and abs(power - expected) > max(expected * 0.25, 60):
        return {}                       # inconsistent frame
    return {"pv_current_2": cur, "pv_voltage_2": volt, "pv_power_2": power}


MODES = {"P": "Power on", "S": "Standby", "L": "Line", "B": "Battery",
         "F": "Fault", "H": "Power saving", "D": "Shutdown"}


def parse_qmod(body: bytes) -> dict:
    """QMOD answers exactly one letter. A foreign frame (e.g. QPIGS from another
    poller on the same UART) also passes the CRC check, so validate the payload —
    otherwise the mode silently becomes "0" or "2"."""
    txt = strip(body).strip()
    if len(txt) != 1 or txt not in MODES:
        return {}
    return {"device_mode": MODES[txt], "mode_code": txt}


_SERIAL_RE = None


def parse_qid(body: bytes) -> dict:
    """Serial numbers are 8-20 alphanumerics; reject anything else (foreign frames)."""
    global _SERIAL_RE
    import re
    if _SERIAL_RE is None:
        _SERIAL_RE = re.compile(r"^[0-9A-Za-z]{8,20}$")
    txt = strip(body).strip()
    return {"serial_number": txt} if _SERIAL_RE.match(txt) else {}


QPIRI_FIELDS = [
    "rated_grid_voltage", "rated_grid_current", "rated_ac_output_voltage",
    "rated_ac_output_frequency", "rated_ac_output_current", "rated_ac_output_apparent_power",
    "rated_power", "rated_battery_voltage", "to_grid_battery_voltage",
    "shutdown_battery_voltage", "battery_absorption_charge_voltage",
    "battery_float_charge_voltage", "battery_type", "max_grid_charge_current",
    "max_charge_current", "input_voltage_range", "_output_source_priority",
    "_charger_source_priority", "parallel_max_num", "machine_type", "topology",
    "output_mode", "back_to_battery_voltage", "pv_ok_condition", "pv_power_balance",
    "max_charging_time", "_operation_logic", "max_discharge_current",
]

OUTPUT_SOURCE_PRIORITY = {0: "Utility first", 1: "Solar first", 2: "SBU",
                          3: "Solar/Utility/Battery"}
# QPIRI "battery type": on firmware with BMS support these are the battery/BMS
# protocols the inverter can speak over its CAN/RS485 port (not just chemistry).
BATTERY_TYPES = {
    0: "AGM", 1: "Flooded", 2: "User", 3: "Pylontech", 4: "Shinheung",
    5: "WECO", 6: "Soltaro", 7: "TBD", 8: "LIb-protocol compatible",
    9: "3rd party Lithium",
}
BATTERY_TYPE_COMMAND = "PBT"

# Axpert MAX manual, "Code Reference" (LCD codes driven by the battery BMS)
BMS_CODES = {
    60: ("BMS не разрешает заряд и разряд", "инвертор останавливает заряд и разряд АКБ"),
    69: ("BMS не разрешает заряд", "инвертор прекращает заряд АКБ"),
    70: ("BMS требует заряжать", "инвертор заряжает АКБ по требованию BMS"),
    71: ("BMS не разрешает разряд", "инвертор прекращает разряд АКБ"),
    62: ("Потеряна связь с BMS / изменилось число батарей",
         "buzzer: через 3 мин; через 10 мин инвертор прекращает заряд и разряд"),
}
CHARGER_SOURCE_PRIORITY = {0: "Utility first", 1: "Solar first",
                           2: "Solar and utility simultaneously", 3: "Solar only"}
OPERATION_LOGIC = {0: "Automatic", 1: "On-line mode", 2: "ECO mode"}


def parse_qpiri(body: bytes) -> dict:
    """Device ratings + current settings (QPIRI is how we verify every write)."""
    f = strip(body).split()
    if len(f) < 20:
        return {}
    out: dict = {}
    for i, name in enumerate(QPIRI_FIELDS):
        if i >= len(f):
            break
        try:
            out[name] = float(f[i])
        except ValueError:
            out[name] = f[i]
    bt = out.get("battery_type")
    if isinstance(bt, float):
        # keep the raw code: some firmwares use their own numbering (seen: 8)
        out["battery_type"] = BATTERY_TYPES.get(int(bt), f"code {int(bt)}")
    for key, table in (("_output_source_priority", OUTPUT_SOURCE_PRIORITY),
                       ("_charger_source_priority", CHARGER_SOURCE_PRIORITY),
                       ("_operation_logic", OPERATION_LOGIC)):
        v = out.pop(key, None)
        if isinstance(v, float):
            out[key.strip("_")] = table.get(int(v), str(int(v)))
    if isinstance(out.get("max_charge_current"), float):
        out["max_charge_current"] = int(out["max_charge_current"])
    if isinstance(out.get("max_grid_charge_current"), float):
        out["max_grid_charge_current"] = int(out["max_grid_charge_current"])
    return out


QBMS_FLAGS = {
    "connected": {0: "Connected", 1: "Disconnected"},
    "force_charge": {0: "No", 1: "Yes"},
    "stop_discharge": {0: "Enable discharge", 1: "Disable discharge"},
    "stop_charge": {0: "Enable charge", 1: "Disable charge"},
}


def parse_qbms(body: bytes) -> dict:
    """QBMS — lithium battery data read by the inverter over CAN/RS485.

    (connect soc force_charge stop_discharge stop_charge bulkV floatV cutoffV maxChgA maxDisA)
    """
    f = strip(body).split()
    if len(f) < 5:
        return {}
    def _i(idx):
        try:
            return int(float(f[idx]))
        except (IndexError, ValueError):
            return None
    connected = _i(0)
    if connected is None:
        return {}
    out = {
        "inverter_bms_connected": 0 if connected else 1,
        "inverter_bms_status": QBMS_FLAGS["connected"].get(connected, str(connected)),
        "inverter_bms_soc": _i(1),
        "inverter_bms_force_charge": _i(2),
        "inverter_bms_stop_discharge": _i(3),
        "inverter_bms_stop_charge": _i(4),
    }
    # Axpert MAX manual, "Code Reference": the BMS flags in QBMS are exactly the
    # codes shown on the LCD.
    #   60 = not allowed to charge AND discharge -> stop both
    #   69 = not allowed to charge                -> stop charging
    #   70 = must be charged                     -> force charge
    #   71 = not allowed to discharge            -> stop discharging
    stop_chg = bool(out.get("inverter_bms_stop_charge"))
    stop_dis = bool(out.get("inverter_bms_stop_discharge"))
    force = bool(out.get("inverter_bms_force_charge"))
    out["bms_charge_blocked"] = 1 if stop_chg else 0
    out["bms_discharge_blocked"] = 1 if stop_dis else 0
    if stop_chg and stop_dis:
        out["bms_code"] = 60
    elif stop_chg:
        out["bms_code"] = 69
    elif force:
        out["bms_code"] = 70
    elif stop_dis:
        out["bms_code"] = 71
    else:
        out["bms_code"] = 0
    if len(f) >= 10:
        def _dec(idx, scale=0.1):
            value = _i(idx)
            return round(value * scale, 2) if value is not None else None
        out.update({
            "inverter_bms_bulk_voltage": _dec(5),
            "inverter_bms_float_voltage": _dec(6),
            "inverter_bms_cutoff_voltage": _dec(7),
            "inverter_bms_max_charge_current": _dec(8, 1.0),
            "inverter_bms_max_discharge_current": _dec(9, 1.0),
        })
    return out


def parse_qpiws(body: bytes) -> dict:
    """Warning bits, 40 chars of 0/1 (b0 leftmost).

    A shared UART (another poller on the same RS232 line) can glue two frames
    together with a valid crc by coincidence, so reject anything that is not
    exactly 40 binary characters instead of reporting a phantom fault.
    """
    txt = strip(body).split("\r")[0].replace(" ", "")
    if len(txt) != 40 or set(txt) - {"0", "1"}:
        return {}
    bits = list(txt)
    active, value = [], 0
    for i, b in enumerate(bits):
        if b == "1":
            value |= 1 << i
            name = WARN_BITS.get(i)
            if name:
                active.append(name)
    return {"warning_flags": active, "warning_bits": value,
            "warnings": ";".join(active) if active else "none"}


# ---------------------------------------------------------------- sanity
# Physically plausible ranges per metric. Values outside are dropped instead of
# being written to the history (a dongle glitch must not become a 11 kW spike).
SANE = {
    "grid_voltage": (0, 400), "grid_frequency": (0, 70), "grid_power": (-30000, 60000),
    "ac_output_voltage": (0, 400), "ac_output_frequency": (0, 70),
    "load_power": (-1, 60000), "load_apparent_power": (-1, 60000),
    "load_percentage": (0, 150), "bus_voltage": (0, 600),
    "battery_voltage": (0, 80), "battery_current": (-500, 500),
    "battery_power": (-60000, 60000), "battery_state_of_charge": (0, 100),
    "temperature": (-40, 120),
    "pv_voltage_1": (0, 600), "pv_current_1": (0, 250), "pv_power_1": (0, 30000),
    "pv_voltage_2": (0, 600), "pv_current_2": (0, 250), "pv_power_2": (0, 30000),
    "pv_power": (0, 60000),
    "inverter_bms_soc": (0, 100),
    "inverter_bms_bulk_voltage": (0, 80),
    "inverter_bms_float_voltage": (0, 80),
    "inverter_bms_cutoff_voltage": (0, 80),
    "inverter_bms_max_charge_current": (0, 500),
    "inverter_bms_max_discharge_current": (0, 500),
}


def sanitize(parsed: dict) -> tuple[dict, list[str]]:
    """Drop implausible values. Returns (clean_dict, dropped_keys)."""
    clean, dropped = {}, []
    for key, value in parsed.items():
        limits = SANE.get(key)
        if limits and isinstance(value, (int, float)):
            lo, hi = limits
            if not (lo <= value <= hi):
                dropped.append(key)
                continue
        clean[key] = value
    return clean, dropped


# ---------------------------------------------------------------- metric table
# key -> (name, unit, device_class, state_class, icon, is_energy)
# Drives MQTT topic names, HA discovery and the Influx measurements.
METRICS: dict[str, tuple] = {
    "grid_voltage": ("Grid voltage", "V", "voltage", "measurement", None, False),
    "grid_frequency": ("Grid frequency", "Hz", "frequency", "measurement", None, False),
    "grid_power": ("Grid power", "W", "power", "measurement", "mdi:transmission-tower", False),
    "ac_output_voltage": ("AC output voltage", "V", "voltage", "measurement", None, False),
    "ac_output_frequency": ("AC output frequency", "Hz", "frequency", "measurement", None, False),
    "load_power": ("Load power", "W", "power", "measurement", "mdi:flash", False),
    "load_apparent_power": ("Load apparent power", "VA", "apparent_power", "measurement", None, False),
    "load_percentage": ("Load percentage", "%", None, "measurement", "mdi:gauge", False),
    "bus_voltage": ("Bus voltage", "V", "voltage", "measurement", None, False),
    "battery_voltage": ("Battery voltage", "V", "voltage", "measurement", None, False),
    "battery_current": ("Battery current", "A", "current", "measurement", "mdi:current-dc", False),
    "battery_power": ("Battery power", "W", "power", "measurement", "mdi:battery-charging", False),
    "battery_state_of_charge": ("Battery state of charge", "%", "battery", "measurement", None, False),
    "temperature": ("Inverter temperature", "°C", "temperature", "measurement", None, False),
    "pv_voltage_1": ("PV voltage 1", "V", "voltage", "measurement", "mdi:solar-panel", False),
    "pv_current_1": ("PV current 1", "A", "current", "measurement", "mdi:solar-panel", False),
    "pv_power_1": ("PV power 1", "W", "power", "measurement", "mdi:solar-power", False),
    "pv_voltage_2": ("PV voltage 2", "V", "voltage", "measurement", "mdi:solar-panel", False),
    "pv_current_2": ("PV current 2", "A", "current", "measurement", "mdi:solar-panel", False),
    "pv_power_2": ("PV power 2", "W", "power", "measurement", "mdi:solar-power", False),
    "pv_power": ("PV power", "W", "power", "measurement", "mdi:solar-power-variant", False),
    "device_mode": ("Device mode", None, None, None, "mdi:state-machine", False),
    "warning_bits": ("Warning bits", None, None, None, "mdi:alert", False),
    # данные BMS, которые инвертор читает по CAN/RS485 (команда QBMS)
    "inverter_bms_soc": ("BMS SOC (inverter)", "%", "battery", "measurement", "mdi:battery-heart", False),
    "inverter_bms_bulk_voltage": ("BMS bulk voltage", "V", "voltage", "measurement", "mdi:battery-arrow-up", False),
    "inverter_bms_float_voltage": ("BMS float voltage", "V", "voltage", "measurement", "mdi:battery-arrow-up-outline", False),
    "inverter_bms_cutoff_voltage": ("BMS cut-off voltage", "V", "voltage", "measurement", "mdi:battery-alert-variant-outline", False),
    "inverter_bms_max_charge_current": ("BMS max charge current", "A", "current", "measurement", "mdi:current-dc", False),
    "inverter_bms_max_discharge_current": ("BMS max discharge current", "A", "current", "measurement", "mdi:current-dc", False),
    "bms_code": ("BMS code (LCD)", None, None, None, "mdi:alert-circle-outline", False),
    # energy counters (kWh, monotonically increasing within a day; reset at midnight)
    "pv_energy_today": ("PV energy today", "kWh", "energy", "total_increasing", "mdi:solar-power", True),
    "load_energy_today": ("Load energy today", "kWh", "energy", "total_increasing", "mdi:home-lightning-bolt", True),
    "grid_energy_today": ("Grid energy today", "kWh", "energy", "total_increasing", "mdi:transmission-tower", True),
    "battery_charge_today": ("Battery charged today", "kWh", "energy", "total_increasing", "mdi:battery-plus", True),
    "battery_discharge_today": ("Battery discharged today", "kWh", "energy", "total_increasing", "mdi:battery-minus", True),
}

# read-only passport data from QPIRI (published, not charted)
INFO_METRICS = {
    "rated_power": ("Rated power", "W"),
    "rated_battery_voltage": ("Battery nominal voltage", "V"),
    "rated_grid_voltage": ("Rated grid voltage", "V"),
    "rated_ac_output_voltage": ("Rated AC output voltage", "V"),
    "rated_ac_output_frequency": ("Rated AC output frequency", "Hz"),
    "rated_ac_output_current": ("Rated AC output current", "A"),
    "battery_type": ("Battery type", None),
    "input_voltage_range": ("Input voltage range", None),
    "machine_type": ("Machine type", None),
    "max_charging_time": ("Max charging time", "min"),
    "max_discharge_current": ("Max discharge current", "A"),
    "serial_number": ("Serial number", None),
}


# ---------------------------------------------------------------- writable settings
# Every entry: MQTT topic under <prefix>/inverter_1/<key>/set(,_verified),
# PI30 set command, and the QPIRI field used to read the value back.
# verify=None -> the firmware cannot report it back (write is fire-and-forget).
SETTINGS: dict[str, dict] = {
    "output_source_priority": {
        "name": "Output source priority", "kind": "select", "field": "output_source_priority",
        "options": OUTPUT_SOURCE_PRIORITY,
        "cmd": lambda v: f"POP{int(v):02d}",
        "icon": "mdi:swap-horizontal",
    },
    "charger_source_priority": {
        "name": "Charger source priority", "kind": "select", "field": "charger_source_priority",
        "options": CHARGER_SOURCE_PRIORITY,
        "cmd": lambda v: f"PCP{int(v):02d}",
        "icon": "mdi:battery-charging-high",
    },
    "max_charge_current": {
        "name": "Max charge current", "kind": "number", "field": "max_charge_current",
        "unit": "A", "min": 10, "max": 200, "step": 1, "dev_class": "current",
        "cmd": lambda v: f"MNCHGC0{int(v):03d}",   # m=parallel machine id, mnnn
        "icon": "mdi:current-dc",
    },
    "max_grid_charge_current": {
        "name": "Max grid charge current", "kind": "number", "field": "max_grid_charge_current",
        "unit": "A", "min": 2, "max": 200, "step": 1, "dev_class": "current",
        "cmd": lambda v: f"MUCHGC{int(v):03d}",
        "icon": "mdi:current-ac",
    },
    "shutdown_battery_voltage": {
        "name": "Shutdown battery voltage", "kind": "number", "field": "shutdown_battery_voltage",
        "unit": "V", "min": 40.0, "max": 60.0, "step": 0.1, "dev_class": "voltage",
        "cmd": lambda v: f"PSDV{float(v):.1f}",
        "icon": "mdi:battery-alert-variant-outline",
    },
    "back_to_battery_voltage": {
        "name": "Back to battery voltage", "kind": "number", "field": "back_to_battery_voltage",
        "unit": "V", "min": 40.0, "max": 60.0, "step": 0.1, "dev_class": "voltage",
        "cmd": lambda v: f"PBDV{float(v):.1f}",
        "icon": "mdi:battery-sync",
    },
    "to_grid_battery_voltage": {
        "name": "To grid battery voltage", "kind": "number", "field": "to_grid_battery_voltage",
        "unit": "V", "min": 40.0, "max": 60.0, "step": 0.1, "dev_class": "voltage",
        "cmd": lambda v: f"PBCV{float(v):.1f}",
        "icon": "mdi:transmission-tower-export",
    },
    "battery_absorption_charge_voltage": {
        "name": "Absorption charge voltage", "kind": "number",
        "field": "battery_absorption_charge_voltage",
        "unit": "V", "min": 40.0, "max": 60.0, "step": 0.1, "dev_class": "voltage",
        "cmd": lambda v: f"PCVV{float(v):.1f}",
        "icon": "mdi:battery-arrow-up",
    },
    "battery_float_charge_voltage": {
        "name": "Float charge voltage", "kind": "number", "field": "battery_float_charge_voltage",
        "unit": "V", "min": 40.0, "max": 60.0, "step": 0.1, "dev_class": "voltage",
        "cmd": lambda v: f"PBFT{float(v):.1f}",
        "icon": "mdi:battery-arrow-up-outline",
    },
}

SETTINGS["battery_type"] = {
    "name": "Battery type / BMS protocol", "kind": "select", "field": "battery_type",
    "options": BATTERY_TYPES,
    "cmd": lambda v: f"{BATTERY_TYPE_COMMAND}{int(v):02d}",
    "icon": "mdi:battery-heart-variant",
}

# Present in QPIRI but with no reliable PI30 write command on all firmwares:
READ_ONLY_SETTINGS = {
    "operation_logic": "Operation logic",
    "power_saving": "Power saving",
}
