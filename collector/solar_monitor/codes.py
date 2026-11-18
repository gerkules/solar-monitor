"""Inverter code reference — extracted from manual-voltronic-axpert-max.pdf.

Sources (page numbers of the PDF):
  * "Faults Reference Code"   (p.40) - solid red LED
  * "Warning Indicator"       (p.41) - flashing
  * "Fault code display"      (p.58) - parallel system faults
  * "5. Code Reference"       (p.67) - codes driven by the battery BMS
  * "8. Trouble shooting"     (p.61) - actions for parallel faults

Kept here so the UI can explain any code without opening the manual.
"""

# code -> (event, what to do / note)
FAULTS = {
    1: ("Fan is locked when inverter is off", "Проверьте вентилятор и его разъём"),
    2: ("Over temperature", "Снизьте нагрузку, проверьте вентиляцию и вентилятор"),
    3: ("Battery voltage is too high", "Проверьте настройки заряда и BMS"),
    4: ("Battery voltage is too low", "Зарядите АКБ, проверьте клеммы и кабель"),
    5: ("Output short circuited", "Устраните КЗ в нагрузке"),
    6: ("Output voltage is too high", "Обратитесь в сервис"),
    7: ("Overload time out", "Уменьшите нагрузку"),
    8: ("Bus voltage is too high", "Обратитесь в сервис"),
    9: ("Bus soft start failed", "Обратитесь в сервис"),
    10: ("PV over current", "Проверьте массив PV и его ток"),
    11: ("PV over voltage", "Проверьте напряжение массива PV (Voc)"),
    12: ("DCDC over current", "Обратитесь в сервис"),
    13: ("Battery discharge over current", "Снизьте нагрузку / проверьте BMS"),
    51: ("Over current", "Снизьте нагрузку, проверьте нагрузку на выходе"),
    52: ("Bus voltage is too low", "Обратитесь в сервис"),
    53: ("Inverter soft start failed", "Обратитесь в сервис"),
    55: ("Over DC voltage in AC output", "Обратитесь в сервис"),
    57: ("Current sensor failed", "Обратитесь в сервис"),
    58: ("Output voltage is too low", "Проверьте нагрузку и выходной кабель"),
}

WARNINGS = {
    1: ("Fan is locked when inverter is on", "Писк 3 раза/сек. Проверьте вентилятор"),
    2: ("Over temperature", "Снизьте нагрузку, проверьте вентиляцию"),
    3: ("Battery is over-charged", "Писк 1 раз/сек. Проверьте напряжения заряда"),
    4: ("Low battery", "Писк 1 раз/сек. Скоро отключение по низкому напряжению"),
    7: ("Overload", "Писк 2 раза/0.5 сек. Уменьшите нагрузку"),
    10: ("Output power derating", "Мощность ограничена (температура/вход)"),
    15: ("PV energy is low", "Мало солнца, генерация снижена"),
    16: ("High AC input (>280 VAC) during BUS soft start", "Проверьте входное напряжение сети"),
    32: ("Communication failure between inverter and remote display panel",
         "Проверьте кабель панели/дисплея"),
}

# Коды BMS (стр. 67 мануала). Появляются только в режимах PYL/WEC/SOL/LIb/3rd party.
BMS = {
    60: ("BMS не разрешает заряд и разряд",
         "Инвертор останавливает и заряд, и разряд АКБ. Проверьте состояние батареи; "
         "принудительно — режим User/AGM"),
    62: ("Потеряна связь с BMS / изменилось число батарей",
         "Buzzer через 3 мин, через 10 мин инвертор прекращает заряд и разряд. "
         "Проверьте кабель и протокол BMS; на дисплее UP/DOWN перепроверяет число батарей"),
    69: ("BMS не разрешает заряд",
         "Инвертор прекращает заряд АКБ (полный пакет, перенапряжение ячейки, температура). "
         "Обычно снимается само; принудительно — режим User/AGM"),
    70: ("BMS требует заряжать",
         "Инвертор заряжает АКБ по требованию BMS"),
    71: ("BMS не разрешает разряд",
         "Инвертор прекращает разряд АКБ. Проверьте SOC/напряжение ячейки"),
}

# Ошибки параллельной системы (стр. 58) — те же номера, другой смысл!
PARALLEL = {
    60: ("Power feedback protection", "Перезапустите инвертор, проверьте L/N и кабели sharing"),
    71: ("Firmware version inconsistent", "Обновите прошивки всех инверторов до одной версии"),
    72: ("Current sharing fault", "Проверьте кабели sharing и перезапустите"),
    80: ("CAN fault / CAN data loss", "Проверьте коммуникационные кабели, перезапустите"),
    81: ("Host loss / Host data loss", "Проверьте кабели связи между инверторами"),
    82: ("Synchronization loss / data loss", "Включайте инверторы одновременно"),
    83: ("Battery voltage detected different", "Все инверторы должны работать от общей батареи"),
    84: ("AC input voltage and frequency detected different", "Проверьте входы сети"),
    85: ("AC output current unbalance", "Проверьте распределение нагрузки"),
    86: ("AC output mode setting is different", "Приведите настройки режима к одинаковым"),
}

# код -> короткая метка для журнала/баннеров
def title(code: int, context: str = "bms") -> str:
    table = {"bms": BMS, "fault": FAULTS, "warning": WARNINGS, "parallel": PARALLEL}[context]
    return table.get(code, ("", ""))[0]


def describe(code: int, context: str = "bms") -> dict:
    table = {"bms": BMS, "fault": FAULTS, "warning": WARNINGS, "parallel": PARALLEL}[context]
    event, action = table.get(code, ("неизвестный код", ""))
    return {"code": code, "context": context, "event": event, "action": action}


def all_codes() -> dict:
    """Everything the UI needs for the reference page."""
    def dump(table):
        return [{"code": c, "event": e, "action": a} for c, (e, a) in sorted(table.items())]
    return {"faults": dump(FAULTS), "warnings": dump(WARNINGS),
            "bms": dump(BMS), "parallel": dump(PARALLEL),
            "note": ("Коды 60 и 71 встречаются дважды: в одиночной системе с BMS — это запрет "
                     "заряда/разряда, в параллельной системе — power feedback protection и "
                     "несовпадение прошивок.")}
