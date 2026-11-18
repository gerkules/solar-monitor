"""Чтение и запись уставок инвертора (PI30) с проверкой по QPIRI.

Повторяет логику сервера: значение считается сохранённым только если инвертор
ответил ACK *и* QPIRI потом показывает новое значение. Иначе — честная ошибка.
"""
import pi30


def parse_value(spec, payload):
    """'Solar first' | '1' | '52.5' -> число (индекс/вольты)."""
    if isinstance(payload, bytes):
        payload = payload.decode()
    txt = str(payload).strip()
    if not txt:
        raise ValueError("пустое значение")
    if spec.get("kind") == "select":
        opts = spec.get("options") or {}
        for idx, name in opts.items():
            if str(name).lower() == txt.lower():
                return float(idx)
        value = float(txt)
        if int(value) not in list(opts.keys()):
            raise ValueError("вариант %s не поддерживается" % txt)
        return value
    value = float(txt)
    lo, hi = spec.get("min"), spec.get("max")
    if lo is not None and value < lo:
        raise ValueError("минимум %s" % lo)
    if hi is not None and value > hi:
        raise ValueError("максимум %s" % hi)
    return value


def build_command(spec, value):
    cmd = spec["cmd"]
    if spec.get("kind") == "select":
        return cmd(int(value))
    return cmd(value)


def same_value(spec, wanted, got):
    if got is None:
        return False
    try:
        if spec.get("kind") == "select":
            if isinstance(got, (int, float)):
                return int(got) == int(wanted)
            return spec["options"].get(int(wanted)) == got
        return abs(float(got) - float(wanted)) < 0.05
    except (TypeError, ValueError):
        return False


def read_status(bus, attempts=3):
    """QPIRI с отбраковкой нереалистичных кадров (общая линия с донглом)."""
    for _ in range(attempts):
        resp = bus.request("QPIRI")
        if not resp:
            continue
        parsed = pi30.parse_qpiri(resp)
        rated = parsed.get("rated_power") or 0
        try:
            rated = float(rated)
        except (TypeError, ValueError):
            rated = 0
        if 300 <= rated <= 50000 and parsed.get("output_source_priority"):
            return parsed
    return None


def settings_list(bus):
    """Список уставок с текущими значениями (для веб-интерфейса и MQTT)."""
    current = read_status(bus) or {}
    out = []
    for key, spec in pi30.SETTINGS.items():
        item = {
            "key": key,
            "name": spec.get("name", key),
            "kind": spec.get("kind", "number"),
            "unit": spec.get("unit"),
            "min": spec.get("min"),
            "max": spec.get("max"),
            "step": spec.get("step"),
            "value": current.get(spec.get("field", key)),
        }
        if spec.get("kind") == "select":
            item["options"] = [[idx, name] for idx, name in spec["options"].items()]
        out.append(item)
    return out


def apply_setting(bus, key, payload, attempts=3):
    """Записать уставку и проверить результат. Возвращает dict как у сервера."""
    spec = pi30.SETTINGS.get(key)
    if spec is None:
        return {"ok": False, "key": key,
                "message": "Error: уставка %s недоступна" % key}
    try:
        value = parse_value(spec, payload)
    except (ValueError, TypeError) as ex:
        return {"ok": False, "key": key, "message": "Error: %s" % (ex,)}

    cmd = build_command(spec, value)
    last_got = None
    for _ in range(attempts):
        reply = None
        for _ in range(3):
            reply = bus.request_raw(cmd)
            if reply and (pi30.is_ack(reply) or pi30.is_nak(reply)):
                break
        if not reply or not pi30.is_ack(reply):
            return {"ok": False, "key": key, "cmd": cmd,
                    "message": "Error: инвертор отклонил команду (NAK)"}
        fresh = read_status(bus)
        if not fresh:
            continue
        last_got = fresh.get(spec.get("field", key))
        if same_value(spec, value, last_got):
            return {"ok": True, "key": key, "cmd": cmd, "value": last_got,
                    "message": "Saved"}
        if spec.get("lenient"):
            return {"ok": True, "key": key, "cmd": cmd, "value": last_got,
                    "message": "Saved (%s)" % (last_got,)}
    return {"ok": False, "key": key, "cmd": cmd, "readback": last_got,
            "message": "Error: ACK получен, но значение не применилось"}
