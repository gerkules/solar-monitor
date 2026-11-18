// Hourly rollup = the SolarAssistant "… hourly" measurements (kWh per hour is
// computed by the consumer: mean(W) * 1h / 1000).
// Create once:  ./tools/create-influx-tasks.sh
option task = {name: "downsample_1h", every: 1h, offset: 5m}

src = (m) =>
    from(bucket: params.bucket)
        |> range(start: -3h)
        |> filter(fn: (r) => r["_measurement"] == m)
        |> filter(fn: (r) => r["_field"] == "value")
        |> aggregateWindow(every: 1h, fn: mean, createEmpty: false)
        |> set(key: "_measurement", value: m + "_hourly")

union(tables: [
    src(m: "pv_power"),
    src(m: "pv_power_1"),
    src(m: "pv_power_2"),
    src(m: "load_power"),
    src(m: "grid_power"),
    src(m: "battery_power"),
    src(m: "battery_voltage"),
    src(m: "battery_state_of_charge"),
])
    |> to(bucket: params.bucket)
