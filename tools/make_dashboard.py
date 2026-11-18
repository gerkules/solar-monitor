#!/usr/bin/env python3
"""Generate grafana/dashboards/solar.json.

    INFLUX_MODE=1.8 python3 tools/make_dashboard.py   # InfluxQL (default here)
    INFLUX_MODE=2   python3 tools/make_dashboard.py   # Flux (InfluxDB 2.x)

Add a metric by appending to the panel lists below and re-running.
"""
import json
import os

OUT = os.path.join(os.path.dirname(__file__), "..", "grafana", "dashboards", "solar.json")
MODE = os.getenv("INFLUX_MODE", "1.8")
DEFAULT_SITES = os.getenv("SITES", os.getenv("SITE", "office"))
DEFAULT_BUCKET = os.getenv("INFLUX_DB", os.getenv("INFLUX_BUCKET", "solar"))

UNITS = {"W": "watt", "kWh": "kwatth", "V": "volt", "A": "amp", "%": "percent",
         "C": "celsius", "Hz": "hertz", "VA": "voltamp"}
DS = {"type": "influxdb", "uid": "influxdb"}


# ---------------------------------------------------------------- queries
def q_series(measurement: str, agg: str = "mean") -> str:
    """Query for a timeseries panel."""
    if MODE.startswith("1"):
        return (f'SELECT {agg}("value") FROM "{measurement}" '
                f'WHERE ("site" = \'$site\') AND $timeFilter '
                f'GROUP BY time($__interval) fill(previous)')
    return (
        f'from(bucket: "{DEFAULT_BUCKET}")\n'
        f'  |> range(start: v.timeRangeStart, stop: v.timeRangeStop)\n'
        f'  |> filter(fn: (r) => r["_measurement"] == "{measurement}")\n'
        f'  |> filter(fn: (r) => r["site"] == "$site")\n'
        f'  |> filter(fn: (r) => r["_field"] == "value")\n'
        f'  |> aggregateWindow(every: v.windowPeriod, fn: {agg}, createEmpty: false)\n'
        f'  |> keep(columns: ["_time", "_value"])'
    )


def q_last(measurement: str) -> str:
    if MODE.startswith("1"):
        return (f'SELECT last("value") FROM "{measurement}" '
                f'WHERE ("site" = \'$site\') AND time > now() - 24h')
    return (
        f'from(bucket: "{DEFAULT_BUCKET}")\n'
        f'  |> range(start: today())\n'
        f'  |> filter(fn: (r) => r["_measurement"] == "{measurement}")\n'
        f'  |> filter(fn: (r) => r["site"] == "$site")\n'
        f'  |> filter(fn: (r) => r["_field"] == "value")\n'
        f'  |> last()\n'
        f'  |> keep(columns: ["_time", "_value"])'
    )


def target(measurement: str, legend: str, ref_id: str, agg: str = "mean") -> dict:
    t = {"datasource": DS, "query": q_series(measurement, agg), "refId": ref_id,
         "legendFormat": legend}
    if MODE.startswith("1"):
        t["rawQuery"] = True
        t["resultFormat"] = "time_series"
        t["alias"] = legend
    return t


def last_target(measurement: str, legend: str, ref_id: str) -> dict:
    t = {"datasource": DS, "query": q_last(measurement), "refId": ref_id,
         "legendFormat": legend}
    if MODE.startswith("1"):
        t["rawQuery"] = True
        t["resultFormat"] = "time_series"
        t["alias"] = legend
    return t


# ---------------------------------------------------------------- panels
def gp(y, h, w=8, x=0):
    return {"h": h, "w": w, "x": x, "y": y}


def timeseries(title, targets, unit, pos, fill=10, stack=False):
    return {
        "type": "timeseries",
        "title": title,
        "datasource": DS,
        "gridPos": pos,
        "targets": targets,
        "fieldConfig": {
            "defaults": {
                "unit": UNITS.get(unit, unit),
                "custom": {
                    "drawStyle": "line", "lineWidth": 1, "fillOpacity": fill,
                    "showPoints": "never", "spanNulls": True,
                    "stacking": {"mode": "normal" if stack else "none", "group": "A"},
                },
            },
            "overrides": [],
        },
        "options": {
            "legend": {"displayMode": "table", "placement": "bottom",
                       "calcs": ["lastNotNull", "max", "mean"]},
            "tooltip": {"mode": "multi", "sort": "desc"},
        },
    }


def stat(title, target_, unit, pos, decimals=1):
    return {
        "type": "stat",
        "title": title,
        "datasource": DS,
        "gridPos": pos,
        "targets": [target_],
        "fieldConfig": {
            "defaults": {
                "unit": UNITS.get(unit, unit),
                "decimals": decimals,
                "color": {"mode": "thresholds"},
                "thresholds": {"mode": "absolute", "steps": [{"color": "text", "value": None}]},
            },
            "overrides": [],
        },
        "options": {
            "reduceOptions": {"calcs": ["lastNotNull"], "fields": "", "values": False},
            "colorMode": "value", "graphMode": "area", "justifyMode": "auto",
            "textMode": "auto",
        },
    }


def row(title, y):
    return {"type": "row", "title": title, "collapsed": False,
            "gridPos": {"h": 1, "w": 24, "x": 0, "y": y}, "panels": []}


panels = []
panels.append(row("Energy today", 0))
for i, (meas, title) in enumerate([
    ("pv_energy_today", "PV produced"),
    ("load_energy_today", "Load consumed"),
    ("grid_energy_today", "Grid imported"),
    ("battery_charge_today", "Battery charged"),
    ("battery_discharge_today", "Battery discharged"),
]):
    panels.append(stat(title, last_target(meas, title, "A"), "kWh", gp(1, 4, 4, i * 4), 2))

panels.append(row("Power", 5))
panels.append(timeseries("PV power", [
    target("pv_power", "total", "A"),
    target("pv_power_1", "MPPT 1", "B"),
    target("pv_power_2", "MPPT 2", "C")], "W", gp(6, 9, 12, 0), fill=20, stack=True))
panels.append(timeseries("Load power", [target("load_power", "load", "A")],
                         "W", gp(6, 9, 12, 12)))
panels.append(timeseries("Battery power", [target("battery_power", "battery (+charge / -discharge)", "A")],
                         "W", gp(15, 8, 12, 0)))
panels.append(timeseries("Grid power", [target("grid_power", "grid", "A")],
                         "W", gp(15, 8, 12, 12)))

panels.append(row("Battery", 23))
panels.append(timeseries("State of charge", [target("battery_state_of_charge", "SOC", "A")],
                         "%", gp(24, 7, 8, 0), fill=20))
panels.append(timeseries("Battery voltage", [target("battery_voltage", "voltage", "A")],
                         "V", gp(24, 7, 8, 8)))
panels.append(timeseries("Battery current", [target("battery_current", "current", "A")],
                         "A", gp(24, 7, 8, 16)))

panels.append(row("PV arrays", 31))
panels.append(timeseries("MPPT voltage", [target("pv_voltage_1", "MPPT 1", "A"),
                                          target("pv_voltage_2", "MPPT 2", "B")],
                         "V", gp(32, 7, 12, 0)))
panels.append(timeseries("MPPT current", [target("pv_current_1", "MPPT 1", "A"),
                                          target("pv_current_2", "MPPT 2", "B")],
                         "A", gp(32, 7, 12, 12)))

panels.append(row("System", 39))
panels.append(timeseries("Inverter temperature", [target("temperature", "temperature", "A")],
                         "C", gp(40, 7, 8, 0)))
panels.append(timeseries("Bus voltage", [target("bus_voltage", "bus", "A")],
                         "V", gp(40, 7, 8, 8)))
panels.append(timeseries("AC output / grid voltage",
                         [target("ac_output_voltage", "output", "A"),
                          target("grid_voltage", "grid", "B")],
                         "V", gp(40, 7, 8, 16)))

dashboard = {
    "uid": "solar-overview",
    "title": "Solar overview",
    "tags": ["solar", "inverter"],
    "timezone": "browser",
    "editable": True,
    "refresh": "30s",
    "schemaVersion": 39,
    "version": 1,
    "time": {"from": "now-12h", "to": "now"},
    "templating": {"list": [{
        "name": "site", "label": "Site", "type": "custom",
        "query": DEFAULT_SITES, "multi": True, "includeAll": False,
        "current": {"text": DEFAULT_SITES.split(",")[0], "value": DEFAULT_SITES.split(",")[0]},
        "options": [{"text": s.strip(), "value": s.strip(), "selected": i == 0}
                    for i, s in enumerate(DEFAULT_SITES.split(","))],
        "hide": 0,
    }]},
    "annotations": {"list": []},
    "panels": panels,
}

os.makedirs(os.path.dirname(OUT), exist_ok=True)
with open(OUT, "w") as f:
    json.dump(dashboard, f, indent=2)
print(f"wrote {os.path.abspath(OUT)} (mode={MODE}, panels={len(panels)})")
