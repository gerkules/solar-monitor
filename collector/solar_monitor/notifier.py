"""Notifications: Telegram, generic webhook, MQTT. Rate-limited per channel."""
from __future__ import annotations

import json
import logging
import threading
import time
import urllib.parse
import urllib.request

from . import config

log = logging.getLogger("notify")


class Notifier:
    def __init__(self, mqtt=None):
        self.mqtt = mqtt
        self.lock = threading.Lock()
        self.last_sent: dict[str, float] = {}
        self.sent = 0
        self.errors = 0
        self.last_error: str | None = None

    # -- channels ------------------------------------------------------------
    def channels(self) -> list[str]:
        out = []
        if config.TELEGRAM_TOKEN and config.TELEGRAM_CHAT:
            out.append("telegram")
        if config.WEBHOOK_URL:
            out.append("webhook")
        if self.mqtt is not None:
            out.append("mqtt")
        return out

    def _telegram(self, text: str) -> None:
        url = f"https://api.telegram.org/bot{config.TELEGRAM_TOKEN}/sendMessage"
        body = urllib.parse.urlencode({
            "chat_id": config.TELEGRAM_CHAT, "text": text,
            "parse_mode": "HTML", "disable_web_page_preview": "true",
        }).encode()
        req = urllib.request.Request(url, data=body, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"telegram http {resp.status}")

    def _webhook(self, text: str, extra: dict | None = None) -> None:
        payload = json.dumps({"text": text, "site": config.SITE,
                              "ts": int(time.time()), "source": "solar-monitor",
                              **(extra or {})}).encode()
        req = urllib.request.Request(config.WEBHOOK_URL, data=payload, method="POST")
        req.add_header("Content-Type", "application/json")
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status >= 300:
                raise RuntimeError(f"webhook http {resp.status}")

    # -- public --------------------------------------------------------------
    def send(self, text: str, channels: list[str] | None = None,
             force: bool = False, extra: dict | None = None) -> dict:
        """Send to every configured channel; rate-limited unless force=True."""
        result = {}
        wanted = channels or self.channels()
        for ch in wanted:
            if ch not in self.channels():
                result[ch] = "not configured"
                continue
            with self.lock:
                now = time.time()
                if not force and now - self.last_sent.get(ch, 0) < config.NOTIFY_MIN_INTERVAL:
                    result[ch] = "rate-limited"
                    continue
                self.last_sent[ch] = now
            try:
                if ch == "telegram":
                    self._telegram(text)
                elif ch == "webhook":
                    self._webhook(text, extra)
                elif ch == "mqtt":
                    self.mqtt.publish(config.NOTIFY_MQTT_TOPIC,
                                      {"text": text, "ts": int(now), **(extra or {})},
                                      retain=False)
                result[ch] = "sent"
                self.sent += 1
                log.info("notify[%s]: %s", ch, text.replace("\n", " ")[:160])
            except Exception as ex:  # noqa: BLE001
                self.errors += 1
                self.last_error = f"{ch}: {ex!r}"
                result[ch] = f"error: {ex!r}"
                log.warning("notify[%s] failed: %r", ch, ex)
        return result
