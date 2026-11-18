"""UART-обмен с инвертором: кадр + CRC + CR, повтор и сборка ответа.

Железо сюда не зашито: Bus принимает любой объект с `write(bytes)`, `read(n)`,
`any()`. Поэтому модуль гоняется обычными тестами на CPython с фейковым UART.
"""
import time

import pi30


def now_ms():
    """Монотонные миллисекунды: ticks_ms в MicroPython, monotonic в CPython."""
    if hasattr(time, "ticks_ms"):
        return time.ticks_ms()
    return int(time.monotonic() * 1000)


def ms_since(start):
    if hasattr(time, "ticks_diff"):
        return time.ticks_diff(now_ms(), start)
    return now_ms() - start


class FrameCollector:
    """Собирает байты в один кадр PI30: <тело> <CRC hi> <CRC lo> \\r.

    CRC стоит ПЕРЕД CR (не после) — кадр заканчивается на переводе строки.
    """

    def __init__(self, max_len=512):
        self.buf = b""
        self.max_len = max_len
        self.overflowed = False

    def reset(self):
        self.buf = b""
        self.overflowed = False

    def feed(self, data):
        if data:
            self.buf += data
        if len(self.buf) > self.max_len:
            self.overflowed = True
            self.reset()
            return None
        i = self.buf.find(b"\r")
        if i < 0:
            return None
        end = i + 1                      # кадр включает CR
        frame = self.buf[:end]
        self.buf = self.buf[end:]
        return frame


class Bus:
    """Один инвертор на линии: запрос -> ответ, с валидацией CRC."""

    def __init__(self, uart, timeout_ms=1500, attempts=2, sleep_ms=None):
        self.uart = uart
        self.timeout_ms = timeout_ms
        self.attempts = attempts
        self._sleep_ms = sleep_ms or (lambda ms: time.sleep(ms / 1000))
        self.tx = 0
        self.rx = 0
        self.errors = 0
        self.last_error = ""

    # -- низкий уровень ------------------------------------------------------
    def drain(self):
        try:
            while self.uart.any():
                self.uart.read(self.uart.any() or 1)
        except Exception:
            pass

    def _write(self, data):
        self.uart.write(data)
        self.tx += 1

    def _read_frame(self, timeout_ms):
        col = FrameCollector()
        start = now_ms()
        while ms_since(start) < timeout_ms:
            chunk = b""
            try:
                if self.uart.any():
                    chunk = self.uart.read(self.uart.any() or 1)
            except Exception as ex:                      # noqa: BLE001
                self.last_error = "uart read: %r" % (ex,)
                return None
            if chunk:
                frame = col.feed(chunk)
                if frame:
                    self.rx += 1
                    return frame
                continue
            self._sleep_ms(2)
        return None

    # -- запросы -------------------------------------------------------------
    def exchange(self, cmd, timeout_ms=None, validate=True):
        """Отправить команду, вернуть кадр ответа (или None)."""
        payload = pi30.frame(cmd) if isinstance(cmd, str) else cmd
        self.drain()
        self._write(payload)
        reply = self._read_frame(timeout_ms or self.timeout_ms)
        if reply is None:
            self.errors += 1
            self.last_error = "timeout on %s" % (cmd,)
            return None
        if validate and not pi30.check_frame(reply):
            self.errors += 1
            self.last_error = "bad crc on %s" % (cmd,)
            return None
        return reply

    def request(self, cmd, timeout_ms=None, attempts=None):
        """Как exchange, но с повторами: на общей линии битые кадры — норма."""
        for _ in range(attempts or self.attempts):
            reply = self.exchange(cmd, timeout_ms)
            if reply is not None:
                return reply
        return None

    def request_raw(self, cmd, timeout_ms=None, attempts=None):
        """Без проверки CRC — для ACK/NAK на команды настройки."""
        for _ in range(attempts or self.attempts):
            reply = self.exchange(cmd, timeout_ms, validate=False)
            if reply is not None:
                return reply
        return None
