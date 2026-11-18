"""Battery over CAN bus (socketcan): Pylontech-style identifiers.

Covered frames (the de-facto standard also spoken by Dyness/SolarMD-class packs):
    0x351 charge/discharge voltage+current limits
    0x355 state of charge / state of health
    0x356 pack voltage / current / temperature
    0x359 protections bitmask
No python-can dependency: one raw AF_CAN socket.
"""
from __future__ import annotations

import logging
import socket
import struct

from .base import BmsDriver

log = logging.getLogger("battery.can")


def decode_frame(can_id: int, data: bytes) -> dict:
    """Decode one CAN frame into normalized keys (empty dict if unknown)."""
    if can_id == 0x355 and len(data) >= 4:
        return {"bms_soc": struct.unpack_from("<H", data, 0)[0],
                "bms_soh": struct.unpack_from("<H", data, 2)[0]}
    if can_id == 0x356 and len(data) >= 6:
        voltage = struct.unpack_from("<H", data, 0)[0] / 100.0
        current = struct.unpack_from("<h", data, 2)[0] / 10.0
        temperature = struct.unpack_from("<H", data, 4)[0] / 10.0
        return {"bms_voltage": round(voltage, 2), "bms_current": round(current, 2),
                "bms_temperature": round(temperature, 1)}
    if can_id == 0x359 and len(data) >= 4:
        masks = struct.unpack_from("<I", data, 0)[0]
        return {"bms_protections": masks} if masks else {}
    return {}


class CanDriver(BmsDriver):
    name = "can"
    overrides = ("battery_voltage", "battery_current", "battery_power",
                 "battery_state_of_charge")

    def __init__(self, interface="can0", **cfg):
        super().__init__(**cfg)
        self.interface = interface or "can0"
        self.sock = None
        self.frames = 0

    def describe(self) -> str:
        return f"CAN {self.interface}"

    def _open(self):
        if self.sock is not None:
            return
        sock = socket.socket(socket.AF_CAN, socket.SOCK_RAW, socket.CAN_RAW)
        sock.bind((self.interface,))
        sock.settimeout(2.0)
        self.sock = sock

    def read(self) -> dict | None:
        try:
            self._open()
        except OSError as ex:
            log.warning("cannot open CAN %s: %r", self.interface, ex)
            return None
        reading: dict = {}
        for _ in range(64):                  # drain a bit, keep the newest values
            try:
                frame = self.sock.recv(16)
            except (socket.timeout, TimeoutError):
                break
            except OSError:
                self.close()
                break
            can_id, _length = struct.unpack_from("=IB3x", frame, 0)
            data = frame[8:]
            self.frames += 1
            reading.update(decode_frame(can_id & 0x1FFFFFFF, data))
        return BmsDriver.post(reading) if reading else None

    def close(self):
        if self.sock is not None:
            try:
                self.sock.close()
            except Exception:  # noqa: BLE001
                pass
            self.sock = None
