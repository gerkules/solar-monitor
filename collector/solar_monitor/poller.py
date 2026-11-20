"""Main polling loop: read the inverter, publish, store history, apply settings."""
from __future__ import annotations

import json
import logging
import queue
import threading
import time

from . import battery as battery_mod, codes as codes_mod, config, connection as conn_mod, \
    energy as energy_mod, pi30, publishers, rules as rules_mod, settings as settings_mod

log = logging.getLogger("poller")


class _Job:
    __slots__ = ("key", "payload", "verified", "event", "result")

    def __init__(self, key, payload, verified):
        self.key = key
        self.payload = payload
        self.verified = verified
        self.event = threading.Event()
        self.result: dict | None = None


class Poller:
    def __init__(self, transport, mq: publishers.MqttPublisher,
                 influx: publishers.InfluxPublisher, notifier=None, rules=None,
                 battery=None):
        self.transport = transport
        self.mq = mq
        self.influx = influx
        self.notifier = notifier
        self.rules = rules if rules is not None else rules_mod.RuleEngine(notifier=notifier)
        self.battery = battery
        self.state: dict = {}
        self.energy = energy_mod.EnergyCounter()
        self.jobs: queue.Queue[_Job] = queue.Queue()
        self.started = time.time()
        self.last_ok: float | None = None
        self.online = False
        self.fails = 0
        self.last_qmod = 0.0
        self.last_qpiri = 0.0
        self.last_qpiws = 0.0
        self.last_qbms = 0.0
        self.qbms_supported: bool | None = None
        self.protocol_change: dict | None = None
        self.bms_down_since: float | None = None
        self.bms_alarm_sent = False
        self.warning69_since: float | None = None
        self.warning69_sent = False
        self.bms_events = battery_mod.BmsEventLog(config.BMS_EVENTS_FILE, influx=influx)
        self.bms_code_current = 0
        self.settings = settings_mod.effective_settings()
        self.state["site"] = config.SITE
        self.state.update({k: self.energy.data.get(k, 0.0)
                           for k in energy_mod.ENERGY_KEYS if k in self.energy.data})

    # -- public API (used by the HTTP API and MQTT) --------------------------
    def submit_set(self, key: str, payload, verified: bool = True,
                   timeout: float = 20.0) -> dict:
        job = _Job(key, payload, verified)
        self.jobs.put(job)
        if not job.event.wait(timeout):
            return {"ok": False, "key": key,
                    "message": "Error: inverter did not answer in time"}
        return job.result or {"ok": False, "key": key, "message": "Error: unknown"}

    def snapshot(self) -> dict:
        return dict(self.state)

    def health(self) -> dict:
        last = self.state.get("last_update")
        # «Здоров» = данные свежие. Один пропущенный опрос (USB-сброс, помеха) —
        # ещё не повод отдавать 503: иначе дёргаются healthcheck и watchdog.
        fresh = bool(last) and (time.time() - last) < config.OFFLINE_AFTER
        return {
            "ok": fresh,
            "online": self.online,
            "last_update": last,
            "age_s": round(time.time() - last, 1) if last else None,
            "consecutive_failures": self.fails,
            "uptime_s": round(time.time() - self.started),
            "transport": self.transport.describe(),
            "site": config.SITE,
            "mqtt_connected": self.mq.connected.is_set(),
            "mqtt_restarts": self.mq.restarts,
            "influx_written": self.influx.written,
            "influx_errors": self.influx.errors,
            "rx": self.transport.rx_count,
            "tx": self.transport.tx_count,
        }

    # -- internals -----------------------------------------------------------
    def _handle_jobs(self):
        while True:
            try:
                job = self.jobs.get_nowait()
            except queue.Empty:
                return
            previous_battery_type = self.state.get("battery_type")
            try:
                if job.key == "reload_settings":
                    fresh = settings_mod.read_settings(self.transport)
                    job.result = ({"ok": True, "key": job.key, "message": "Saved"} if fresh
                                  else {"ok": False, "key": job.key,
                                        "message": "Error: could not read settings"})
                else:
                    job.result = settings_mod.apply_setting(
                        self.transport, job.key, job.payload, job.verified)
                if job.result.get("ok"):
                    fresh = settings_mod.read_settings(self.transport)
                    if fresh:
                        self.state.update(fresh)
                        publishers.publish_state(self.mq, self.state)
                    if job.key == "battery_type" and config.BATTERY_TYPE_ROLLBACK \
                            and previous_battery_type \
                            and job.result.get("value") != previous_battery_type:
                        self._start_protocol_watch(previous_battery_type,
                                                   job.result.get("value"))
            except Exception as ex:  # noqa: BLE001 - one bad write must not stop the loop
                log.exception("setting write failed")
                job.result = {"ok": False, "key": job.key, "message": f"Error: {ex!r}"}
            log.info("set result: %s", job.result)
            self.mq.publish(publishers.SET_RESPONSE_TOPIC, job.result["message"], retain=True)
            job.event.set()

    # -- transport switching (UI: «Подключение») ------------------------------
    def apply_connection(self, cfg: dict) -> dict:
        """Swap the transport at runtime: close the old one, use the new one."""
        new = conn_mod.build(cfg, broker=self.mq)
        old = self.transport
        self.transport = new
        log.warning("transport switched: %s -> %s", old.describe(), new.describe())
        try:
            old.close()
        except Exception:  # noqa: BLE001
            pass
        self.fails = 0
        self.last_ok = None
        self.qbms_supported = None      # re-probe the new link
        self.last_qbms = 0.0
        self.last_qmod = 0.0
        self.last_qpiri = 0.0
        for key in ("device_mode", "bms_link", "inverter_bms_connected"):
            self.state.pop(key, None)
        return {"ok": True, "transport": new.describe()}

    # -- BMS link watchdog (R61/R69 on the inverter display) -------------------
    def _track_bms_link(self, connected, now: float):
        if connected == 1:
            if self.bms_down_since is not None:
                log.info("BMS link restored after %.0fs", now - self.bms_down_since)
                if self.bms_code_current == 62:
                    self._set_bms_code(0, note="связь восстановлена")
            self.bms_down_since = None
            self.bms_alarm_sent = False
            return
        if self.bms_down_since is None:
            self.bms_down_since = now
            log.warning("BMS link lost (protocol %r)", self.state.get("battery_type"))
            self._set_bms_code(62, note="нет связи с BMS")
            return
        down = now - self.bms_down_since
        if down >= config.BMS_LINK_ALERT_AFTER and not self.bms_alarm_sent:
            self.bms_alarm_sent = True
            log.error("BMS link down for %.0fs on protocol %r", down,
                      self.state.get("battery_type"))
            if self.notifier is not None:
                self.notifier.send(
                    f"🛑 {config.DEVICE_NAME}: нет связи с BMS {down:.0f} с "
                    f"(протокол «{self.state.get('battery_type')}»).\n"
                    f"Инвертор в этом режиме не заряжает АКБ. Проверьте протокол батареи "
                    f"или выберите User/AGM. Warning 69 (запрет заряда от BMS) — это другое: "
                    f"он появляется при живой связи, когда сама батарея просит не заряжать.",
                    force=True)

    def _set_bms_code(self, code: int, note: str | None = None):
        """Single place that records code transitions into the journal."""
        if code == self.bms_code_current:
            return
        self.bms_events.record(code, self.bms_code_current, note=note)
        self.bms_code_current = code

    def _track_bms_flags(self, parsed: dict, now: float):
        """Warning 60/69 on the inverter display = the BMS asked to stop charging.

        Manual wording: "If battery status is not allowed to charge after battery is
        successful, it will show code 69 to stop charging battery." It is a warning
        from the battery (full pack, cell over-voltage, temperature), not a link
        failure — and it clears itself when the BMS allows charging again.
        """
        if self.bms_down_since is not None:
            return                      # link is down: code 62 owns the journal
        code = int(parsed.get("bms_code") or 0)
        self.state["bms_code"] = code
        self._set_bms_code(code)
        blocked_charge = parsed.get("bms_charge_blocked")
        blocked_discharge = parsed.get("bms_discharge_blocked")
        if not code:
            if self.warning69_since is not None:
                log.info("BMS allows charge/discharge again (warning 69 cleared)")
                self.state["bms_warning_69"] = 0
            self.warning69_since = None
            self.warning69_sent = False
            return

        self.state["bms_warning_69"] = 1
        self.state["bms_warning_code"] = code
        if self.warning69_since is None:
            self.warning69_since = now
            log.warning("BMS code %s: %s", code, pi30.BMS_CODES.get(code, ("", ""))[0])
        if not self.warning69_sent and now - self.warning69_since >= 30:
            self.warning69_sent = True
            info = codes_mod.describe(code, "bms")
            title, effect = info["event"], info["action"]
            if self.notifier is not None:
                self.notifier.send(
                    f"⚠️ {config.DEVICE_NAME}: код {code} на дисплее — {title}.\n"
                    f"{effect.capitalize()}. Это защита батареи (полный пакет, напряжение "
                    f"ячейки, температура), а не ошибка протокола. Обычно снимается само; "
                    f"принудительно — режим User/AGM.", force=True)

    # -- battery protocol safety net ------------------------------------------
    def _start_protocol_watch(self, previous, current):
        now = time.time()
        self.protocol_change = {
            "previous": previous,
            "current": current,
            "started": int(now),
            "deadline": int(now + config.BATTERY_TYPE_ROLLBACK_AFTER),
            "timeout": config.BATTERY_TYPE_ROLLBACK_AFTER,
            "state": "checking",
        }
        self.last_qbms = 0.0          # fetch BMS status right away
        self.qbms_supported = None     # re-probe: the protocol just changed
        log.warning("battery protocol changed %s -> %s: verifying BMS link for %.0fs",
                    previous, current, config.BATTERY_TYPE_ROLLBACK_AFTER)
        if self.notifier is not None:
            self.notifier.send(
                f"🔋 {config.DEVICE_NAME}: протокол BMS изменён на «{current}». "
                f"Инвертор подключает АКБ 20-30 с; пока связи нет, он НЕ заряжает батарею. "
                f"Проверяю {config.BATTERY_TYPE_ROLLBACK_AFTER:.0f} с, затем верну «{previous}».")

    def protocol_status(self) -> dict:
        info = dict(self.protocol_change or {})
        info["battery_type"] = self.state.get("battery_type")
        info["bms_link"] = self.state.get("bms_link")
        info["bms_connected"] = self.state.get("inverter_bms_connected")
        info["qbms_supported"] = self.qbms_supported
        info["rollback_enabled"] = config.BATTERY_TYPE_ROLLBACK
        info["bms_down_s"] = (round(time.time() - self.bms_down_since)
                              if self.bms_down_since else 0)
        info["warning_69"] = bool(self.warning69_since)
        info["charge_blocked"] = self.state.get("bms_charge_blocked")
        info["discharge_blocked"] = self.state.get("bms_discharge_blocked")
        if info.get("deadline"):
            info["seconds_left"] = max(0, int(info["deadline"] - time.time()))
        return info

    def _check_protocol_watch(self, now: float):
        change = self.protocol_change
        if not change:
            return
        if change.get("state") == "recovering":
            self._check_recovery(now)
            return
        if change.get("state") != "checking":
            return
        connected = self.state.get("inverter_bms_connected")
        if connected == 1:
            change["state"] = "confirmed"
            change["finished"] = int(now)
            log.info("battery protocol %s confirmed: BMS connected", change.get("current"))
            if self.notifier is not None:
                self.notifier.send(f"✅ {config.DEVICE_NAME}: протокол «{change['current']}» "
                                   f"подтверждён, BMS на связи")
            return
        if now >= change.get("deadline", 0):
            self._rollback_protocol("timeout")

    RECOVERY_ATTEMPTS = 3
    # The inverter reconnects the battery ~20-30 s after the correct protocol is
    # selected, so only rewrite it if the link is still down after this delay.
    RECOVERY_STEP = 35.0

    def _write_battery_type(self, value) -> dict:
        try:
            return settings_mod.apply_setting(self.transport, "battery_type", value, True)
        except Exception as ex:  # noqa: BLE001
            return {"ok": False, "message": repr(ex)}

    def _rollback_protocol(self, reason: str) -> dict:
        """Restore the previous protocol and make sure the BMS really comes back.

        Observed on real hardware: the inverter re-establishes the battery link
        20-30 s after a correct protocol is selected. If it is still down after
        RECOVERY_STEP, the protocol is written again (up to RECOVERY_ATTEMPTS).
        """
        change = self.protocol_change or {}
        previous = change.get("previous")
        result = {"ok": False, "reason": reason, "previous": previous}
        if not previous:
            change["state"] = "failed"
            self.protocol_change = change
            return result
        log.warning("battery protocol rollback to %r (%s)", previous, reason)
        applied = self._write_battery_type(previous)
        result.update(applied)
        now = time.time()
        change.update({
            "state": "recovering", "reason": reason, "attempts": 1,
            "next_check": now + self.RECOVERY_STEP, "finished": None,
        })
        self.protocol_change = change
        fresh = settings_mod.read_settings(self.transport)
        if fresh:
            self.state.update(fresh)
        self.last_qbms = 0.0
        self.qbms_supported = None
        if self.notifier is not None:
            self.notifier.send(
                f"↩️ {config.DEVICE_NAME}: протокол BMS возвращён на «{previous}» "
                f"({'нет связи с АКБ' if reason == 'timeout' else reason}). "
                f"Восстанавливаю связь с батареей (заряд заблокирован инвертором).")
        return result

    def _check_recovery(self, now: float):
        change = self.protocol_change or {}
        if self.state.get("inverter_bms_connected") == 1:
            change.update({"state": "rolled_back", "finished": int(now)})
            log.info("battery link restored on protocol %r", change.get("previous"))
            if self.notifier is not None:
                self.notifier.send(f"✅ {config.DEVICE_NAME}: связь с АКБ восстановлена "
                                   f"на протоколе «{change.get('previous')}»")
            return
        if now < change.get("next_check", 0):
            return
        attempts = int(change.get("attempts", 1))
        if attempts >= self.RECOVERY_ATTEMPTS:
            change.update({"state": "failed", "finished": int(now)})
            log.error("BMS link did not come back after %s attempts", attempts)
            if self.notifier is not None:
                self.notifier.send(
                    f"❌ {config.DEVICE_NAME}: связь с АКБ не восстановилась на протоколе "
                    f"«{change.get('previous')}» после {attempts} попыток. "
                    f"Возможно, требуется перезагрузка инвертора.")
            return
        log.warning("battery link still down: rewriting protocol %r (attempt %s)",
                    change.get("previous"), attempts + 1)
        self._write_battery_type(change.get("previous"))
        change.update({"attempts": attempts + 1, "next_check": now + self.RECOVERY_STEP})
        self.last_qbms = 0.0
        self.qbms_supported = None

    def confirm_protocol(self) -> dict:
        if not self.protocol_change:
            return {"ok": False, "message": "нет изменения протокола"}
        self.protocol_change["state"] = "confirmed"
        self.protocol_change["finished"] = int(time.time())
        return {"ok": True, "message": "подтверждено", **self.protocol_status()}

    def cancel_protocol(self) -> dict:
        if not self.protocol_change or \
                self.protocol_change.get("state") not in ("checking", "recovering"):
            return {"ok": False, "message": "нет активной проверки протокола"}
        return self._rollback_protocol("manual")

    def _poll_fast(self) -> bool:
        resp = self.transport.request("QPIGS")
        if not resp:
            return False
        parsed = pi30.parse_qpigs(resp)
        if not parsed:
            return False
        parsed, dropped = pi30.sanitize(parsed)
        if dropped:
            log.warning("QPIGS: implausible values dropped: %s", ", ".join(dropped))
        self.state.update(parsed)
        if config.HAS_MPPT2:
            r2 = self.transport.request("QPIGS2")
            parsed2 = pi30.parse_qpigs2(r2) if r2 else {}
            if parsed2:
                parsed2, dropped = pi30.sanitize(parsed2)
                if dropped:
                    log.warning("QPIGS2: implausible values dropped: %s", ", ".join(dropped))
                self.state.update(parsed2)
                # A dual-MPPT inverter is only recognised once the second array
                # actually reports something: the UI hides PV2 for single-MPPT units.
                if (parsed2.get("pv_voltage_2") or 0) > 20 or \
                        (parsed2.get("pv_power_2") or 0) > 50:
                    self.state["has_mppt2"] = 1
            else:
                # firmware without a second MPPT: do not keep stale values
                for key in ("pv_power_2", "pv_voltage_2", "pv_current_2"):
                    self.state.pop(key, None)
        energy_mod.derive_pv(self.state)
        energy_mod.derive_power(self.state)
        self.energy.accumulate(self.state)
        return True

    def cycle(self):
        """One poll iteration (separated from run() so it can be unit-tested)."""
        t0 = time.time()
        self._handle_jobs()
        ok = self._poll_fast()

        if ok:
            self.fails = 0
            now = time.time()
            self.state["last_update"] = int(now)

            if now - self.last_qmod > config.QMOD_INTERVAL:
                r = self.transport.request("QMOD")
                parsed = pi30.parse_qmod(r) if r else {}
                if parsed:
                    self.state.update(parsed)
                self.last_qmod = now

            if config.QPIWS_INTERVAL > 0 and now - self.last_qpiws > config.QPIWS_INTERVAL:
                r = self.transport.request("QPIWS")
                # a frame glued from two replies yields {} -> keep the previous value
                parsed = pi30.parse_qpiws(r) if r else {}
                if parsed:
                    self.state.update(parsed)
                self.last_qpiws = now

            verifying = bool(self.protocol_change
                             and self.protocol_change.get("state") in ("checking", "recovering"))
            qbms_due = config.QBMS_INTERVAL if not verifying else min(
                config.QBMS_INTERVAL, max(2.0, config.POLL_INTERVAL))
            if config.QBMS_INTERVAL > 0 and self.qbms_supported is not False and \
                    (verifying or now - self.last_qbms > qbms_due):
                r = self.transport.request("QBMS")
                parsed = pi30.parse_qbms(r) if r else {}
                if parsed:
                    self.state.update(parsed)
                    self.state["bms_link"] = parsed.get("inverter_bms_status")
                    self.qbms_supported = True
                    self._track_bms_link(parsed.get("inverter_bms_connected"), now)
                    self._track_bms_flags(parsed, now)
                elif r is not None and not verifying:
                    # (NAK) — firmware without BMS support: stop asking.
                    # While a protocol change is being verified we keep polling,
                    # because the link is expected to appear/disappear.
                    self.qbms_supported = False
                    log.info("QBMS not supported by this firmware, disabling BMS polling")
                self.last_qbms = now

            if now - self.last_qpiri > config.QPIRI_INTERVAL or \
                    "output_source_priority" not in self.state:
                r = self.transport.request("QPIRI")
                parsed = pi30.parse_qpiri(r) if r else {}
                if parsed:
                    self.state.update(parsed)
                self.last_qpiri = now

            if "serial_number" not in self.state:
                r = self.transport.request("QID")
                parsed = pi30.parse_qid(r) if r else {}
                if parsed:
                    self.state.update(parsed)

            self._check_protocol_watch(now)
            if self.battery is not None:
                self.battery.reapply(self.state)
            publishers.publish_state(self.mq, self.state)
            self.influx.write(self.state, now)
            self._run_rules(now)
            if config.SAMPLE_JSON:
                log.debug("state: %s", json.dumps(self.state))

            if not self.online:
                back = now - self.last_ok if self.last_ok else 0
                log.info("online%s", f" (after {back:.0f}s)" if back else "")
                self.mq.publish(publishers.STATUS_TOPIC, "online", retain=True)
                self.online = True
            self.last_ok = now

            log.info("%s | grid %.1fV %.0fW | batt %.1fV %s%% %.0fW | load %.0fW | pv %.0fW | %s",
                     self.state.get("device_mode", "?"),
                     self.state.get("grid_voltage") or 0,
                     self.state.get("grid_power") or 0,
                     self.state.get("battery_voltage") or 0,
                     self.state.get("battery_state_of_charge", "?"),
                     self.state.get("battery_power") or 0,
                     self.state.get("load_power") or 0,
                     self.state.get("pv_power") or 0,
                     self.state.get("warnings", ""))
        else:
            self.fails += 1
            now = time.time()
            if self.fails in (1, 5) or self.fails % 60 == 0:
                log.warning("no valid answer from %s (%s in a row)",
                            self.transport.describe(), self.fails)
            if self.fails % 20 == 0:
                # wedged link: drop it so the next attempt reconnects cleanly
                log.warning("reconnecting transport after %s failures", self.fails)
                self.transport.close()
            if self.online and self.last_ok and now - self.last_ok >= config.OFFLINE_AFTER:
                log.warning("offline: no data for %.0fs", now - self.last_ok)
                self.mq.publish(publishers.STATUS_TOPIC, "offline", retain=True)
                self.online = False
                if self.notifier:
                    self.notifier.send(f"⚠️ {config.DEVICE_NAME}: нет связи "
                                       f"({now - self.last_ok:.0f} с)")

        elapsed = time.time() - t0
        time.sleep(max(0.2, config.POLL_INTERVAL - elapsed))

    def _run_rules(self, now: float):
        try:
            fired = self.rules.evaluate(self.state, now)
        except Exception:  # noqa: BLE001
            log.exception("rule evaluation failed")
            return
        for rule in fired:
            log.info("rule fired: %s", rule.get("name"))
            for act in rule["then"]:
                self._run_action(rule, act)
            self.rules.mark_fired(rule, now)

    def _run_action(self, rule: dict, act: dict):
        kind = act.get("type")
        try:
            if kind == "notify":
                text = rules_mod.RuleEngine.render(act.get("text", ""), self.state)
                if self.notifier is not None:
                    self.notifier.send(f"{rule.get('name')}: {text}" if act.get("prefix", True) else text)
                else:
                    log.info("notify (no channel): %s", text)
            elif kind == "set":
                result = settings_mod.apply_setting(self.transport, act["key"],
                                                    act.get("value"), bool(act.get("verified", True)))
                log.info("rule %s set %s=%s -> %s", rule.get("name"), act["key"],
                         act.get("value"), result.get("message"))
                if result.get("ok"):
                    fresh = settings_mod.read_settings(self.transport)
                    if fresh:
                        self.state.update(fresh)
            elif kind == "mqtt":
                payload = rules_mod.RuleEngine.render(act.get("payload", ""), self.state)
                self.mq.publish(act["topic"], payload, retain=bool(act.get("retain", False)))
        except Exception:  # noqa: BLE001
            log.exception("rule action failed: %r", act)

    def run(self):
        """Supervised loop: one bad frame must never kill the collector."""
        publishers.publish_discovery(self.mq, self.state)
        log.info("polling %s every %ss (settings writes: %s)",
                 self.transport.describe(), config.POLL_INTERVAL, config.ALLOW_SETTINGS)
        while True:
            try:
                self.cycle()
            except Exception:  # noqa: BLE001
                log.exception("poll cycle failed, continuing")
                # Устройство могло переподключиться (USB re-enumeration на одноплатнике):
                # сбрасываем транспорт, чтобы следующий цикл открыл его заново.
                # Для hidraw/serial это критично — иначе остаётся протухший fd
                # и EIO повторяется до ручного рестарта сервиса.
                try:
                    self.transport.close()
                except Exception:  # noqa: BLE001
                    pass
                time.sleep(1.0)
