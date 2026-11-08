"""CAN bus side: one receive thread, per-ID statistics, a ring log, optional
DBC decoding (cantools) and frame sending. Plugins subscribe to every frame."""
from __future__ import annotations

import collections
import csv
import threading
import time
from typing import Callable, Deque, Dict, List, Optional

import can

try:
    import cantools
except ImportError:          # DBC decoding is optional
    cantools = None

Listener = Callable[[can.Message], None]


class IdStat:
    __slots__ = ("arb", "ext", "dlc", "data", "count", "first", "last", "prev", "period", "changed")

    def __init__(self, msg: can.Message, now: float):
        self.arb = msg.arbitration_id
        self.ext = msg.is_extended_id
        self.dlc = msg.dlc
        self.data = bytes(msg.data)
        self.count = 0
        self.first = now
        self.last = now
        self.prev = now
        self.period = 0.0            # smoothed seconds between frames
        self.changed = now           # when the data bytes last changed

    def update(self, msg: can.Message, now: float) -> None:
        d = bytes(msg.data)
        if d != self.data:
            self.changed = now
        self.data = d
        self.dlc = msg.dlc
        self.count += 1
        dt = now - self.last
        self.period = dt if self.period == 0 else 0.8 * self.period + 0.2 * dt
        self.prev, self.last = self.last, now

    def as_dict(self, now: float) -> dict:
        return {"id": self.arb, "ext": self.ext, "dlc": self.dlc, "data": self.data.hex(" "),
                "count": self.count, "rate": (1.0 / self.period) if self.period > 0 else 0.0,
                "age": now - self.last, "changed": now - self.changed}


class CanBus:
    def __init__(self, interface: str, channel: str, bitrate: int, log_size: int = 20000):
        self.interface, self.channel, self.bitrate = interface, channel, bitrate
        self.bus: Optional[can.BusABC] = None
        self.stats: Dict[int, IdStat] = {}
        self.log: Deque[tuple] = collections.deque(maxlen=log_size)   # (t, arb, ext, data)
        self.listeners: List[Listener] = []
        self.lock = threading.Lock()
        self.rx_total = 0
        self.tx_total = 0
        self.errors = 0
        self.db = None
        self.db_name = ""
        self.started = time.monotonic()
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None

    # ---------------------------------------------------------------- lifecycle
    def open(self) -> None:
        if self.interface == "sim":                 # Robust IO firmware simulator (robustio package)
            from robustio.simbus import SimBus
            self.bus = SimBus(self.channel if self.channel and self.channel != "can0" else "127.0.0.1:29536")
        elif self.interface == "virtual":           # python-can in-process bus, for trying the page with no hardware
            self.bus = can.Bus(interface="virtual", channel=self.channel)
        elif self.interface == "socketcan":         # bitrate is set with 'ip link'
            self.bus = can.Bus(interface="socketcan", channel=self.channel)
        else:
            self.bus = can.Bus(interface=self.interface, channel=self.channel, bitrate=self.bitrate)
        self._thread = threading.Thread(target=self._rx_loop, name="canweb-rx", daemon=True)
        self._thread.start()

    def close(self) -> None:
        self._stop.set()
        if self._thread:
            self._thread.join(1.0)
        if self.bus:
            self.bus.shutdown()

    def _rx_loop(self) -> None:
        while not self._stop.is_set():
            try:
                msg = self.bus.recv(0.2)
            except can.CanError:
                self.errors += 1
                time.sleep(0.1)
                continue
            if msg is None:
                continue
            if msg.is_error_frame:
                self.errors += 1
                continue
            now = time.monotonic()
            with self.lock:
                self.rx_total += 1
                st = self.stats.get(msg.arbitration_id)
                if st is None:
                    st = self.stats[msg.arbitration_id] = IdStat(msg, now)
                st.update(msg, now)
                self.log.append((time.time(), msg.arbitration_id, msg.is_extended_id, bytes(msg.data)))
            for fn in list(self.listeners):
                try:
                    fn(msg)
                except Exception:          # a plugin bug must not stop the bus
                    pass

    # ---------------------------------------------------------------- api
    def add_listener(self, fn: Listener) -> None:
        self.listeners.append(fn)

    def send(self, arb: int, data: bytes, ext: bool = False) -> None:
        self.bus.send(can.Message(arbitration_id=arb, data=data, is_extended_id=ext))
        with self.lock:
            self.tx_total += 1

    def snapshot(self) -> dict:
        now = time.monotonic()
        with self.lock:
            ids = [s.as_dict(now) for s in self.stats.values()]
        ids.sort(key=lambda d: d["id"])
        for d in ids:
            d["decoded"] = self.decode(d["id"], bytes.fromhex(d["data"].replace(" ", "")))
        return {"interface": self.interface, "channel": self.channel, "bitrate": self.bitrate,
                "rx": self.rx_total, "tx": self.tx_total, "errors": self.errors,
                "uptime": now - self.started, "dbc": self.db_name, "ids": ids}

    def clear_stats(self) -> None:
        with self.lock:
            self.stats.clear()
            self.rx_total = self.tx_total = self.errors = 0
            self.started = time.monotonic()

    # ---------------------------------------------------------------- dbc
    def load_dbc(self, path: str) -> str:
        if cantools is None:
            raise RuntimeError("cantools is not installed (pip install cantools)")
        self.db = cantools.database.load_file(path)
        self.db_name = path
        return f"{len(self.db.messages)} messages"

    def decode(self, arb: int, data: bytes) -> Optional[dict]:
        if self.db is None:
            return None
        try:
            m = self.db.get_message_by_frame_id(arb)
        except KeyError:
            return None
        try:
            vals = m.decode(data, decode_choices=True)
        except Exception:
            return {"name": m.name, "error": "decode failed"}
        out = {}
        for k, v in vals.items():
            out[k] = v if isinstance(v, (int, float, str)) else str(v)
        return {"name": m.name, "signals": out}

    # ---------------------------------------------------------------- log
    def log_rows(self, limit: int = 500) -> list:
        with self.lock:
            rows = list(self.log)[-limit:]
        return [{"t": t, "id": a, "ext": e, "data": d.hex(" ")} for t, a, e, d in rows]

    def write_log(self, path: str) -> int:
        with self.lock:
            rows = list(self.log)
        with open(path, "w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["time", "id_hex", "ext", "dlc", "data_hex"])
            for t, a, e, d in rows:
                w.writerow([f"{t:.6f}", f"{a:X}", int(e), len(d), d.hex()])
        return len(rows)
