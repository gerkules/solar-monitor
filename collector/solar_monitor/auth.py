"""Учётные данные веб-интерфейса: смена пароля из UI.

Пароль из `.env` (AUTH_USER/AUTH_PASSWORD) — «заводской». Если пользователь сменил пароль
в интерфейсе, он сохраняется сюда (PBKDF2-SHA256 + соль) и **перекрывает** .env.
Файл лежит в /data (volume), права 0600.
"""
from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import secrets
import time

from . import config

log = logging.getLogger("auth")

ITERATIONS = 200_000
ALGO = "pbkdf2_sha256"
MIN_LENGTH = 6
# Пароль «из коробки»: его знает любой, кто прочитал README, поэтому UI настойчиво
# предлагает сменить его, а в лог пишется предупреждение.
DEFAULT_USER = "admin"
DEFAULT_PASSWORD = "admin"


def hash_password(password: str, salt: bytes | None = None,
                  iterations: int = ITERATIONS) -> dict:
    salt = salt or secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode(), salt, iterations)
    return {"algo": ALGO, "iterations": iterations,
            "salt": salt.hex(), "hash": digest.hex()}


def verify(password: str, record: dict) -> bool:
    try:
        digest = hashlib.pbkdf2_hmac(
            "sha256", password.encode(), bytes.fromhex(record["salt"]),
            int(record.get("iterations", ITERATIONS)))
    except (KeyError, ValueError, TypeError):
        return False
    return hmac.compare_digest(digest.hex(), str(record.get("hash", "")))


class AuthStore:
    def __init__(self, path: str | None = None):
        self.path = path or config.AUTH_FILE
        self.data: dict = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        except FileNotFoundError:
            self.data = {}
        except (OSError, json.JSONDecodeError) as ex:
            log.warning("cannot read auth file %s: %r", self.path, ex)
            self.data = {}

    def _save(self):
        try:
            os.makedirs(os.path.dirname(self.path) or ".", exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(self.data, f)
            os.chmod(tmp, 0o600)
            os.replace(tmp, self.path)
        except OSError as ex:
            log.warning("cannot save auth file: %r", ex)

    # -- состояние ------------------------------------------------------------
    @property
    def enabled(self) -> bool:
        return bool(self.data.get("user")) or bool(config.AUTH_USER and config.AUTH_PASSWORD)

    def is_default(self) -> bool:
        """Действует ли ещё пароль по умолчанию (только для варианта из .env)."""
        return (not self.data.get("user")
                and (config.AUTH_PASSWORD or "") == DEFAULT_PASSWORD)

    def info(self) -> dict:
        if self.data.get("user"):
            return {"user": self.data["user"], "source": "file",
                    "updated": self.data.get("updated"), "enabled": True,
                    "default_password": False}
        return {"user": config.AUTH_USER, "source": "env" if config.AUTH_USER else "off",
                "updated": None, "enabled": bool(config.AUTH_USER and config.AUTH_PASSWORD),
                "default_password": self.is_default()}

    # -- проверка -------------------------------------------------------------
    def check(self, user: str, password: str) -> bool:
        rec = self.data.get("password")
        if rec and self.data.get("user"):
            return hmac.compare_digest(str(user), str(self.data["user"])) and verify(password, rec)
        if config.AUTH_USER and config.AUTH_PASSWORD:
            return (hmac.compare_digest(user, config.AUTH_USER)
                    and hmac.compare_digest(password, config.AUTH_PASSWORD))
        return False

    # -- изменение ------------------------------------------------------------
    def bootstrap(self, user: str, password: str) -> None:
        """Включить защиту впервые, когда авторизация выключена.

        Заодно закрывает наихудший сценарий «панель открыта всем в сети»:
        после вызова файл auth.json существует, и middleware требует Basic.
        """
        if self.enabled:
            raise ValueError("авторизация уже включена — используйте смену пароля")
        user = (user or "").strip() or DEFAULT_USER
        if len(password or "") < MIN_LENGTH:
            raise ValueError(f"пароль короче {MIN_LENGTH} символов")
        self.data = {"user": user, "password": hash_password(password),
                     "updated": int(time.time())}
        self._save()
        log.warning("ui auth enabled by bootstrap for user %r", user)

    def set_password(self, current_password: str, new_password: str,
                     new_user: str | None = None) -> None:
        user = self.info()["user"]
        if not user:
            raise ValueError("авторизация выключена: задайте AUTH_USER/AUTH_PASSWORD в .env")
        if len(new_password or "") < MIN_LENGTH:
            raise ValueError(f"пароль короче {MIN_LENGTH} символов")
        if not self.check(user, current_password or ""):
            raise ValueError("текущий пароль неверен")
        user = (new_user or user).strip() or user
        self.data = {"user": user, "password": hash_password(new_password),
                     "updated": int(time.time())}
        self._save()
        log.warning("ui password changed for user %r", user)
