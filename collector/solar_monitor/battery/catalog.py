"""Battery source catalogue — the same grouping SolarAssistant offers.

Each entry: transport group -> driver + default serial settings + brand list.
`driver=None` means the protocol is listed but not implemented here yet: the UI
shows it (so nothing is silently missing) and refuses to activate it with a clear
message instead of pretending to read a battery.
"""
from __future__ import annotations

GROUPS = [
    {
        "group": "USB Daly UART/RS485", "driver": "daly", "baud": 9600,
        "brands": ["Daly BMS UART/RS485", "Deligreen BMS UART/RS458",
                   "Heyo BMS UART/RS458"],
    },
    {
        "group": "USB JBD UART/RS485", "driver": "jbd", "baud": 9600,
        "brands": ["JBD BMS UART/RS485", "Overkill Solar BMS UART/RS485",
                   "QUCC BMS UART/RS485"],
    },
    {
        "group": "USB JK RS485", "driver": None, "baud": 115200,
        "brands": ["JK BMS RS485"],
    },
    {
        "group": "USB Modbus RS232/RS485", "driver": "modbus", "baud": 9600,
        "brands": ["Averge CH48/LFeLi range RS485 port", "EG4 LIFEPOWER4 (with LCD) RS485 port",
                   "EG4 LL RS485 port", "EcomLight LifePO4 RS485 port", "Enersol RS485 port",
                   "Fox ESS RS485 port", "Iseli Energy RS485 port", "Leoch LFeLi RS485 port",
                   "Polarium SLB RS485 port", "Rentech BTESF RS485 port", "Revov R9 RS485 port",
                   "SunStonePower Lithium RS485 port", "V-TAC AT48 LiFePO4"],
    },
    {
        "group": "USB Narada RS485", "driver": "modbus", "baud": 9600,
        "brands": ["EG4 LIFEPOWER4 (without LCD) RS485 port", "Narada NPFC RS485 port",
                   "Shoto SDA10-48100L5 RS485 port", "SunSynk SSLB RS232 port",
                   "Storz Power RS485 port"],
    },
    {
        "group": "USB Pylontech/Pytes console", "driver": "pylontech", "baud": 115200,
        "brands": ["BlauHoff RS232 console port", "Pylontech RS232 console port",
                   "Pylontech Force L2 RS232 console port", "Pytes RS232 console port"],
    },
    {
        "group": "USB Serial RS232/RS485", "driver": "modbus", "baud": 9600,
        "brands": ["Averge CH48/LFeLi range RS232 port", "Dyness RS485 port",
                   "Greenrich RS232 port", "Enersol RS232 port",
                   "Hubble AM and X-100/X-101 RS232 port", "Iseli Energy RS232 port",
                   "Jakiper RS232/RS485 port", "Leoch LFeLi RS232 port",
                   "Lithium Batteries SA (LBSA) RS485 port", "Mecer RS485 port",
                   "Meritsun ESS Power Wall RS485 port", "Narada NPFC RS232 port",
                   "PowerUp by ESS LiFePO4 RS232 port", "Pylontech RS485 port",
                   "Revov R100/B100/R9 RS232 port", "Seplos V1/V2 RS485 port",
                   "Shoto SDA10 and SDC-Box RS232/RS485 port", "SOK Battery RS232 port",
                   "SolarPower24 LifePO4", "SunSynk SUN-BATT/BYD RS232 port",
                   "The Sun Pays RS232 port", "Trophy battery RS485 port",
                   "Vestwood RS485 port", "VOLTA Stage 1 RS232 port"],
    },
    {
        "group": "USB Voltronic LIB RS485", "driver": "voltronic", "baud": 2400,
        "brands": ["BlueNova RacPower RS485 port", "BlueNova BMAC RS485 port",
                   "Felicity Solar LPBF com port", "Giter battery RS485 port",
                   "Hubble X-100 RS485 port", "Freedom Won E-Tower RS485 port",
                   "Freedom Won CAN Converter RS485 port", "Upower UE Li RS485 port"],
    },
    {
        "group": "USB CAN bus", "driver": "can", "baud": 0,
        "brands": ["Dyness CAN port", "Pylontech CAN port", "SolarMD CAN port"],
    },
    {
        "group": "USB Victron VE.Direct", "driver": "vedirect", "baud": 19200,
        "brands": ["Victron BMV or SmartShunt"],
    },
]

# Special sources that are not a serial protocol
SPECIAL = [
    {"id": "inverter", "group": "Основное", "brand": "Значения инвертора",
     "driver": "inverter", "baud": 0},
    {"id": "emulated", "group": "Основное", "brand": "Эмуляция BMS (кулонометрия)",
     "driver": "emulated", "baud": 0},
]


def slug(text: str) -> str:
    out = []
    for ch in text.lower():
        if ch.isalnum():
            out.append(ch)
        elif out and out[-1] != "-":
            out.append("-")
    return "".join(out).strip("-")


def catalog() -> list[dict]:
    """Flat list: [{id, group, brand, driver, baud, supported}]."""
    items = []
    for special in SPECIAL:
        items.append({**special, "supported": True,
                      "id": special.get("id") or slug(special["brand"])})
    for group in GROUPS:
        for brand in group["brands"]:
            items.append({
                "id": slug(brand),
                "group": group["group"],
                "brand": brand,
                "driver": group["driver"],
                "baud": group["baud"],
                "supported": group["driver"] is not None,
            })
    return items


def find(identifier: str) -> dict | None:
    for item in catalog():
        if item["id"] == identifier:
            return item
    return None
