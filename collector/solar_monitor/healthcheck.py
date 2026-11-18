"""Docker healthcheck: работает и по HTTP, и по HTTPS с self-signed сертификатом."""
from __future__ import annotations

import ssl
import sys
import urllib.request


def check(port: int = 8080, timeout: float = 4.0) -> bool:
    for scheme in ("http", "https"):
        ctx = ssl._create_unverified_context() if scheme == "https" else None
        try:
            with urllib.request.urlopen(f"{scheme}://127.0.0.1:{port}/healthz",
                                        timeout=timeout, context=ctx) as resp:
                if resp.status == 200:
                    return True
        except Exception:  # noqa: BLE001 - пробуем второй протокол
            continue
    return False


if __name__ == "__main__":
    sys.exit(0 if check() else 1)
