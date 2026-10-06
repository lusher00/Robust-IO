"""High-level access to one Robust IO board over CAN.

    import can
    from robustio import RobustIO

    with RobustIO(can.Bus(interface="socketcan", channel="can0"), node=0) as io:
        io.wait_ready()
        io.set_output(3, True)        # keepalive starts automatically
        print(io.inputs.as_dict(), io.currents.amps)

The board switches everything off if the host goes quiet for the configured
timeout (500 ms by default). While this object has commanded anything, a
background thread repeats a no-change command every `keepalive` seconds so
that does not happen; close() stops it, and the board then times out.

keepalive_gate, when given, is called before each keepalive frame; the frame
is sent only if it returns True. Programs that act for someone else (a web
page, a ROS topic) use it to pass the board's timeout through: when their own
client goes quiet, the keepalive stops and the board switches off.
"""
from __future__ import annotations

import threading
import time
from typing import Callable, Dict, List, Optional

import can

from . import protocol as p


class RobustIOError(Exception):
    pass


class ConfigRejected(RobustIOError):
    """The board answered but refused the key or value."""


class RobustIO:
    def __init__(self, bus: can.BusABC, node: int = 0, keepalive: float = 0.2,
                 keepalive_gate: Optional[Callable[[], bool]] = None):
        p._check_node(node)
        self.bus = bus
        self.node = node
        self.keepalive_period = keepalive
        self.keepalive_gate = keepalive_gate

        self.inputs = p.Inputs()
        self.outputs = p.Outputs()
        self.currents = p.Currents()
        self.motors = p.Motors()
        self.heartbeat: Optional[p.Heartbeat] = None
        self.last_seen: Dict[int, float] = {}

        self._motor_cmd: List[int] = [0, 0]
        self._lock = threading.Lock()
        self._cond = threading.Condition(self._lock)
        self._reply: Optional[p.ConfigReply] = None
        self._listeners: List[Callable[[int, object], None]] = []
        self._ka_stop = threading.Event()
        self._ka_thread: Optional[threading.Thread] = None
        self._notifier = can.Notifier(bus, [self._on_message], timeout=0.05)

    # ------------------------------------------------------------ receive

    def _on_message(self, msg: can.Message) -> None:
        if msg.is_extended_id or msg.is_error_frame:
            return
        r = p.decode(msg.arbitration_id, msg.data)
        if r is None or r[1] != self.node:
            return
        base, _, obj = r
        with self._cond:
            if base == p.ID_INPUTS:
                self.inputs = obj
            elif base == p.ID_OUTPUTS:
                self.outputs = obj
            elif base == p.ID_CURRENTS:
                self.currents = obj
            elif base == p.ID_MOTORS:
                self.motors = obj
            elif base == p.ID_HEARTBEAT:
                self.heartbeat = obj
            elif base == p.ID_CONFIG_REPLY:
                self._reply = obj
            self.last_seen[base] = time.monotonic()
            self._cond.notify_all()
        for fn in list(self._listeners):
            fn(base, obj)

    def add_listener(self, fn: Callable[[int, object], None]) -> None:
        """fn(base_id, decoded_object) is called from the receive thread for every frame from this node."""
        self._listeners.append(fn)

    def wait_for(self, base_id: int, timeout: float = 2.0) -> object:
        """Wait for the next frame of one type and return it decoded."""
        with self._cond:
            t0 = self.last_seen.get(base_id, 0.0)
            if not self._cond.wait_for(lambda: self.last_seen.get(base_id, 0.0) > t0, timeout):
                raise RobustIOError(f"no frame 0x{base_id + self.node:03X} within {timeout} s")
        return {p.ID_INPUTS: self.inputs, p.ID_OUTPUTS: self.outputs, p.ID_CURRENTS: self.currents,
                p.ID_MOTORS: self.motors, p.ID_HEARTBEAT: self.heartbeat}.get(base_id)

    def wait_ready(self, timeout: float = 3.0) -> p.Heartbeat:
        """Wait until a heartbeat and one of each status frame have arrived."""
        deadline = time.monotonic() + timeout
        for base in (p.ID_HEARTBEAT, p.ID_INPUTS, p.ID_OUTPUTS, p.ID_CURRENTS, p.ID_MOTORS):
            if base not in self.last_seen:
                self.wait_for(base, max(0.0, deadline - time.monotonic()))
        return self.heartbeat

    def snapshot(self) -> dict:
        """Current state as plain data (for JSON, logging, ROS)."""
        hb = self.heartbeat
        return {
            "node": self.node,
            "online": self.online(),
            "heartbeat": None if hb is None else {
                "version": f"{hb.version[0]}.{hb.version[1]}", "reset": hb.reset_text(),
                "host_active": hb.host_active, "host_timed_out": hb.host_timed_out,
                "inputs_valid": hb.inputs_valid, "config_defaults": hb.config_defaults,
                "motor_fault": hb.motor_fault, "output_latched": hb.output_latched,
                "tec": hb.tec, "rec": hb.rec, "eflg": hb.eflg, "tx_dropped": hb.tx_dropped},
            "inputs": {"bits": self.inputs.bits, "valid": self.inputs.valid,
                       "device_fault": self.inputs.device_fault, "closed": self.inputs.as_dict()},
            "outputs": [{"n": n, "state": self.outputs.state(n),
                         "commanded": bool(self.outputs.commanded >> n & 1),
                         "amps": self.currents.amps[n]} for n in range(p.NUM_OUTPUTS)],
            "motors": {"duty": list(self.motors.duty), "amps": list(self.motors.amps),
                       "command": list(self._motor_cmd), "asleep": self.motors.asleep,
                       "fault_latched": self.motors.fault_latched, "fault_pin": self.motors.fault_pin,
                       "fault_count": self.motors.fault_count},
        }

    def online(self, within: float = 1.5) -> bool:
        t = self.last_seen.get(p.ID_HEARTBEAT)
        return t is not None and time.monotonic() - t < within

    # ------------------------------------------------------------ commands

    def _send(self, frame) -> None:
        arb, data = frame
        self.bus.send(can.Message(arbitration_id=arb, data=data, is_extended_id=False))

    def set_outputs(self, mask: int, values: int) -> None:
        """Outputs selected by mask are set to the matching bit of values."""
        self._send(p.encode_set_outputs(self.node, mask, values))
        self._start_keepalive()

    def set_output(self, n: int, on: bool) -> None:
        if not 0 <= n < p.NUM_OUTPUTS:
            raise ValueError("output must be 0..7")
        self.set_outputs(1 << n, (1 << n) if on else 0)

    def all_off(self) -> None:
        self.set_outputs(0xFF, 0)

    def set_motors(self, duty0: int, duty1: int) -> None:
        self._motor_cmd = [int(duty0), int(duty1)]
        self._send(p.encode_set_motors(self.node, *self._motor_cmd))
        self._start_keepalive()

    def set_motor(self, m: int, duty: int) -> None:
        cmd = list(self._motor_cmd)
        cmd[m] = int(duty)
        self.set_motors(*cmd)

    def stop(self) -> None:
        """Outputs off, motors to zero."""
        self.all_off()
        self.set_motors(0, 0)

    def clear_faults(self, output_mask: int = 0xFF, motor: bool = True) -> None:
        self._send(p.encode_clear(self.node, output_mask, motor))

    # ------------------------------------------------------------ configuration

    def _config(self, op: int, key: int = 0, value: int = 0, timeout: float = 1.0) -> p.ConfigReply:
        with self._cond:
            self._reply = None
        self._send(p.encode_config(self.node, op, key, value))
        with self._cond:
            if not self._cond.wait_for(lambda: self._reply is not None and self._reply.op == op, timeout):
                raise RobustIOError("no configuration reply")
            r = self._reply
        if not r.ok:
            raise ConfigRejected(f"configuration {p.CONFIG_NAMES.get(r.key, hex(r.key))}: {p.RESULT_TEXT.get(r.result, r.result)}")
        return r

    def config_get(self, name_or_key) -> int:
        return self._config(p.OP_READ, p.config_key(name_or_key)).value

    def config_set(self, name_or_key, value: int) -> int:
        """Returns the value the board accepted."""
        return self._config(p.OP_WRITE, p.config_key(name_or_key), int(value)).value

    def config_all(self) -> Dict[str, int]:
        return {name: self.config_get(key) for name, (key, _, _) in p.CONFIG_KEYS.items()}

    def config_save(self) -> None:
        self._config(p.OP_SAVE, timeout=2.0)

    def config_defaults(self) -> None:
        """Load defaults into RAM on the board; config_save() makes them permanent."""
        self._config(p.OP_DEFAULTS)

    # ------------------------------------------------------------ keepalive and teardown

    def _start_keepalive(self) -> None:
        if self.keepalive_period <= 0 or (self._ka_thread and self._ka_thread.is_alive()):
            return
        self._ka_stop.clear()
        self._ka_thread = threading.Thread(target=self._keepalive, name="robustio-keepalive", daemon=True)
        self._ka_thread.start()

    def _keepalive(self) -> None:
        # A set-outputs frame with an empty mask changes nothing but restarts the host timeout.
        while not self._ka_stop.wait(self.keepalive_period):
            if self.keepalive_gate is not None and not self.keepalive_gate():
                continue
            try:
                self._send(p.encode_set_outputs(self.node, 0, 0))
            except can.CanError:
                pass

    def stop_keepalive(self) -> None:
        self._ka_stop.set()
        if self._ka_thread:
            self._ka_thread.join(timeout=1.0)
            self._ka_thread = None

    def close(self) -> None:
        self.stop_keepalive()
        self._notifier.stop()

    def __enter__(self) -> "RobustIO":
        return self

    def __exit__(self, *exc) -> None:
        self.close()
