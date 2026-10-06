"""Robust IO CAN protocol: frame IDs, encoding and decoding.

This module is the single source of truth for the protocol on the host side.
The DBC file is generated from it (`robustio dbc`). It must match
firmware/src/app/canproto.c and firmware/DESIGN.md section 9.

All IDs are standard 11-bit, offset by the node number N (0..15).
Multi-byte values are little-endian.
"""
from __future__ import annotations

import struct
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

# Base IDs (add the node number)
ID_INPUTS = 0x100
ID_OUTPUTS = 0x110
ID_CURRENTS = 0x120
ID_MOTORS = 0x130
ID_HEARTBEAT = 0x140
ID_SET_OUTPUTS = 0x200
ID_SET_MOTORS = 0x210
ID_CLEAR = 0x220
ID_CONFIG = 0x230
ID_CONFIG_REPLY = 0x240

STATUS_IDS = (ID_INPUTS, ID_OUTPUTS, ID_CURRENTS, ID_MOTORS, ID_HEARTBEAT, ID_CONFIG_REPLY)
COMMAND_IDS = (ID_SET_OUTPUTS, ID_SET_MOTORS, ID_CLEAR, ID_CONFIG)

NUM_OUTPUTS = 8
NUM_MOTORS = 2
NUM_INPUTS = 22

# Input names in bit order: bit 0..13 = SG0..SG13, bit 14..21 = SP0..SP7
INPUT_NAMES: List[str] = [f"SG{i}" for i in range(14)] + [f"SP{i}" for i in range(8)]

# Connector for each input, from the rev A netlist
INPUT_CONNECTOR: Dict[str, str] = {}
for _conn, _names in (("J16", ["SG0", "SG1", "SG2", "SG3"]),
                      ("J18", ["SG4", "SG5", "SG6", "SG7"]),
                      ("J19", ["SG8", "SG9", "SG10", "SG11"]),
                      ("J14", ["SG12", "SG13"]),
                      ("J9", ["SP0", "SP1", "SP2", "SP3"]),
                      ("J10", ["SP4", "SP5", "SP6", "SP7"])):
    for _pin, _n in enumerate(_names, start=1):
        INPUT_CONNECTOR[_n] = f"{_conn}-{_pin}"

# Configuration keys: name -> (key, unit, description)
CONFIG_KEYS: Dict[str, Tuple[int, str, str]] = {
    "node": (0x00, "", "node number 0..15, applies after save and reset"),
    "rate": (0x01, "kbit/s", "125, 250, 500 or 1000, applies after save and reset"),
    "timeout": (0x02, "ms", "host timeout, 0 = off, up to 60000"),
    "debounce": (0x03, "ms", "input debounce, 0..250"),
    "wet_sp": (0x04, "mA", "SP wetting current: 2 6 8 10 12 14 16 20"),
    "wet_sg": (0x05, "mA", "SG wetting current: 2 6 8 10 12 14 16 20"),
    "slew": (0x06, "%/10ms", "motor duty change per 10 ms, 1..100"),
    "idle": (0x07, "ms", "motor driver sleep delay, 0..60000"),
}
for _i in range(NUM_OUTPUTS):
    CONFIG_KEYS[f"limit{_i}"] = (0x10 + _i, "mA", f"output {_i} trip level, 100..30000")
    CONFIG_KEYS[f"trip{_i}"] = (0x18 + _i, "ms", f"output {_i} trip time, 0..10000")
CONFIG_NAMES: Dict[int, str] = {v[0]: k for k, v in CONFIG_KEYS.items()}

OP_READ, OP_WRITE, OP_SAVE, OP_DEFAULTS = 0, 1, 2, 3
RESULT_TEXT = {0: "ok", 1: "bad key", 2: "bad value", 3: "EEPROM write failed"}

RESET_CAUSES = {0x01: "power-on", 0x02: "external", 0x04: "brown-out", 0x08: "watchdog", 0x10: "jtag"}


# ---------------------------------------------------------------- status frames

@dataclass
class Inputs:
    bits: int = 0
    valid: bool = False
    device_fault: bool = False

    def closed(self, name_or_index) -> bool:
        i = INPUT_NAMES.index(name_or_index) if isinstance(name_or_index, str) else int(name_or_index)
        return bool(self.bits >> i & 1)

    def as_dict(self) -> Dict[str, bool]:
        return {n: bool(self.bits >> i & 1) for i, n in enumerate(INPUT_NAMES)}


@dataclass
class Outputs:
    commanded: int = 0
    on: int = 0
    tripped: int = 0
    device_fault: int = 0
    off_high: int = 0

    def state(self, n: int) -> str:
        b = 1 << n
        if self.tripped & b:
            return "tripped"
        if self.device_fault & b:
            return "fault"
        if self.on & b:
            return "on"
        if self.off_high & b:
            return "off-high"
        return "off"


@dataclass
class Currents:
    amps: List[float] = field(default_factory=lambda: [0.0] * NUM_OUTPUTS)   # 0.1 A resolution


@dataclass
class Motors:
    duty: List[int] = field(default_factory=lambda: [0, 0])      # percent, signed
    amps: List[float] = field(default_factory=lambda: [0.0, 0.0])  # 0.01 A resolution
    asleep: bool = True
    fault_latched: bool = False
    fault_pin: bool = False
    fault_count: int = 0


@dataclass
class Heartbeat:
    host_active: bool = False
    host_timed_out: bool = False
    inputs_valid: bool = False
    config_defaults: bool = False
    motor_fault: bool = False
    output_latched: bool = False
    reset_cause: int = 0
    version: Tuple[int, int] = (0, 0)
    tec: int = 0
    rec: int = 0
    eflg: int = 0
    tx_dropped: int = 0

    def reset_text(self) -> str:
        names = [t for b, t in RESET_CAUSES.items() if self.reset_cause & b]
        return ", ".join(names) or "none"


@dataclass
class ConfigReply:
    op: int
    key: int
    value: int
    result: int

    @property
    def ok(self) -> bool:
        return self.result == 0


def _pad(data: bytes, n: int) -> bytes:
    if len(data) < n:
        raise ValueError(f"frame too short: {len(data)} bytes, need {n}")
    return bytes(data)


def decode_inputs(d: bytes) -> Inputs:
    d = _pad(d, 4)
    return Inputs(bits=d[0] | d[1] << 8 | d[2] << 16, valid=bool(d[3] & 1), device_fault=bool(d[3] & 2))


def decode_outputs(d: bytes) -> Outputs:
    d = _pad(d, 5)
    return Outputs(*d[:5])


def decode_currents(d: bytes) -> Currents:
    d = _pad(d, 8)
    return Currents([b / 10.0 for b in d[:8]])


def decode_motors(d: bytes) -> Motors:
    d = _pad(d, 6)
    duty0, duty1 = struct.unpack_from("<bb", d, 0)
    return Motors(duty=[duty0, duty1], amps=[d[2] / 100.0, d[3] / 100.0],
                  asleep=bool(d[4] & 1), fault_latched=bool(d[4] & 2), fault_pin=bool(d[4] & 4),
                  fault_count=d[5])


def decode_heartbeat(d: bytes) -> Heartbeat:
    d = _pad(d, 8)
    s = d[0]
    return Heartbeat(host_active=bool(s & 1), host_timed_out=bool(s & 2), inputs_valid=bool(s & 4),
                     config_defaults=bool(s & 8), motor_fault=bool(s & 16), output_latched=bool(s & 32),
                     reset_cause=d[1], version=(d[2], d[3]), tec=d[4], rec=d[5], eflg=d[6], tx_dropped=d[7])


def decode_config_reply(d: bytes) -> ConfigReply:
    d = _pad(d, 5)
    return ConfigReply(op=d[0], key=d[1], value=d[2] | d[3] << 8, result=d[4])


DECODERS = {
    ID_INPUTS: decode_inputs,
    ID_OUTPUTS: decode_outputs,
    ID_CURRENTS: decode_currents,
    ID_MOTORS: decode_motors,
    ID_HEARTBEAT: decode_heartbeat,
    ID_CONFIG_REPLY: decode_config_reply,
}


def split_id(arbitration_id: int) -> Optional[Tuple[int, int]]:
    """Return (base_id, node) for a Robust IO frame ID, or None."""
    base = arbitration_id & ~0x0F
    node = arbitration_id & 0x0F
    if base in STATUS_IDS or base in COMMAND_IDS:
        return base, node
    return None


def decode(arbitration_id: int, data: bytes):
    """Decode a status frame from any node. Returns (base_id, node, object) or None."""
    s = split_id(arbitration_id)
    if not s or s[0] not in DECODERS:
        return None
    return s[0], s[1], DECODERS[s[0]](bytes(data))


# ---------------------------------------------------------------- command frames

def _check_node(node: int) -> None:
    if not 0 <= node <= 15:
        raise ValueError("node must be 0..15")


def encode_set_outputs(node: int, mask: int, values: int) -> Tuple[int, bytes]:
    _check_node(node)
    return ID_SET_OUTPUTS + node, bytes([mask & 0xFF, values & 0xFF])


def encode_set_motors(node: int, duty0: int, duty1: int) -> Tuple[int, bytes]:
    _check_node(node)
    for v in (duty0, duty1):
        if not -100 <= v <= 100:
            raise ValueError("motor duty must be -100..100")
    return ID_SET_MOTORS + node, struct.pack("<bb", duty0, duty1)


def encode_clear(node: int, output_mask: int = 0xFF, motor: bool = True) -> Tuple[int, bytes]:
    _check_node(node)
    return ID_CLEAR + node, bytes([output_mask & 0xFF, 1 if motor else 0])


def encode_config(node: int, op: int, key: int = 0, value: int = 0) -> Tuple[int, bytes]:
    _check_node(node)
    if not 0 <= value <= 0xFFFF:
        raise ValueError("config value must be 0..65535")
    return ID_CONFIG + node, bytes([op, key, value & 0xFF, value >> 8])


def config_key(name_or_key) -> int:
    if isinstance(name_or_key, int):
        return name_or_key
    try:
        return CONFIG_KEYS[name_or_key][0]
    except KeyError:
        raise KeyError(f"unknown setting '{name_or_key}', known: {', '.join(CONFIG_KEYS)}") from None
