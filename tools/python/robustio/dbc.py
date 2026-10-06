"""Generate a DBC file for one Robust IO node from protocol.py."""
from __future__ import annotations

from typing import List, Tuple

from . import protocol as p

# (name, start bit, length, signed, scale, unit, min, max)
Sig = Tuple[str, int, int, bool, float, str, float, float]


def _messages(node: int):
    msgs = []

    inp: List[Sig] = [(n, i, 1, False, 1, "", 0, 1) for i, n in enumerate(p.INPUT_NAMES)]
    inp += [("InputsValid", 24, 1, False, 1, "", 0, 1), ("InputDeviceFault", 25, 1, False, 1, "", 0, 1)]
    msgs.append((p.ID_INPUTS, "Inputs", 4, inp, "Switch inputs, 1 = closed. On change and every 100 ms."))

    out: List[Sig] = []
    for g, (label, start) in enumerate((("Commanded", 0), ("On", 8), ("Tripped", 16), ("DeviceFault", 24), ("OffHigh", 32))):
        out += [(f"Out{i}_{label}", start + i, 1, False, 1, "", 0, 1) for i in range(p.NUM_OUTPUTS)]
    msgs.append((p.ID_OUTPUTS, "Outputs", 5, out, "High-side output state, every 100 ms."))

    cur: List[Sig] = [(f"Out{i}_Current", 8 * i, 8, False, 0.1, "A", 0, 25.5) for i in range(p.NUM_OUTPUTS)]
    msgs.append((p.ID_CURRENTS, "Currents", 8, cur, "High-side output currents, every 100 ms."))

    mot: List[Sig] = [
        ("Motor0_Duty", 0, 8, True, 1, "%", -100, 100),
        ("Motor1_Duty", 8, 8, True, 1, "%", -100, 100),
        ("Motor0_Current", 16, 8, False, 0.01, "A", 0, 2.55),
        ("Motor1_Current", 24, 8, False, 0.01, "A", 0, 2.55),
        ("MotorsAsleep", 32, 1, False, 1, "", 0, 1),
        ("MotorFaultLatched", 33, 1, False, 1, "", 0, 1),
        ("MotorFaultPin", 34, 1, False, 1, "", 0, 1),
        ("MotorFaultCount", 40, 8, False, 1, "", 0, 255),
    ]
    msgs.append((p.ID_MOTORS, "Motors", 6, mot, "Motor drivers, every 100 ms."))

    hb: List[Sig] = [
        ("HostActive", 0, 1, False, 1, "", 0, 1),
        ("HostTimedOut", 1, 1, False, 1, "", 0, 1),
        ("InputsValid", 2, 1, False, 1, "", 0, 1),
        ("ConfigDefaults", 3, 1, False, 1, "", 0, 1),
        ("MotorFaultLatched", 4, 1, False, 1, "", 0, 1),
        ("OutputLatched", 5, 1, False, 1, "", 0, 1),
        ("ResetCause", 8, 8, False, 1, "", 0, 255),
        ("VersionMajor", 16, 8, False, 1, "", 0, 255),
        ("VersionMinor", 24, 8, False, 1, "", 0, 255),
        ("TEC", 32, 8, False, 1, "", 0, 255),
        ("REC", 40, 8, False, 1, "", 0, 255),
        ("EFLG", 48, 8, False, 1, "", 0, 255),
        ("TxDropped", 56, 8, False, 1, "", 0, 255),
    ]
    msgs.append((p.ID_HEARTBEAT, "Heartbeat", 8, hb, "Node state, every 1 s."))

    msgs.append((p.ID_SET_OUTPUTS, "SetOutputs", 2,
                 [("Mask", 0, 8, False, 1, "", 0, 255), ("Values", 8, 8, False, 1, "", 0, 255)],
                 "Host command: outputs selected by Mask are set to the matching bit of Values. Restarts the host timeout."))
    msgs.append((p.ID_SET_MOTORS, "SetMotors", 2,
                 [("Motor0_Cmd", 0, 8, True, 1, "%", -100, 100), ("Motor1_Cmd", 8, 8, True, 1, "%", -100, 100)],
                 "Host command: motor duty, ramped. Restarts the host timeout."))
    msgs.append((p.ID_CLEAR, "ClearFaults", 2,
                 [("OutputMask", 0, 8, False, 1, "", 0, 255), ("ClearMotor", 8, 1, False, 1, "", 0, 1)],
                 "Clear latched output trips and the motor fault."))
    cfg = [("Op", 0, 8, False, 1, "", 0, 3), ("Key", 8, 8, False, 1, "", 0, 255), ("Value", 16, 16, False, 1, "", 0, 65535)]
    msgs.append((p.ID_CONFIG, "Config", 4, cfg, "Configuration request."))
    msgs.append((p.ID_CONFIG_REPLY, "ConfigReply", 5, cfg + [("Result", 32, 8, False, 1, "", 0, 3)],
                 "Configuration reply."))
    return msgs


def generate(node: int = 0) -> str:
    p._check_node(node)
    node_name = f"RobustIO_{node}"
    lines = ['VERSION ""', "", "NS_ :", "", "BS_:", "", f"BU_: {node_name} Host", ""]
    comments = []
    for base, name, dlc, sigs, desc in _messages(node):
        cid = base + node
        sender = "Host" if base in p.COMMAND_IDS else node_name
        receiver = node_name if sender == "Host" else "Host"
        lines.append(f"BO_ {cid} {name}: {dlc} {sender}")
        for (sn, start, length, signed, scale, unit, mn, mx) in sigs:
            sign = "-" if signed else "+"
            lines.append(f' SG_ {sn} : {start}|{length}@1{sign} ({scale:g},0) [{mn:g}|{mx:g}] "{unit}" {receiver}')
        lines.append("")
        comments.append(f'CM_ BO_ {cid} "{desc}";')
    lines += comments
    lines.append("")
    for base, name in ((p.ID_CONFIG, "Config"), (p.ID_CONFIG_REPLY, "ConfigReply")):
        lines.append(f'VAL_ {base + node} Op 0 "read" 1 "write" 2 "save" 3 "defaults" ;')
        keys = " ".join(f'{k} "{n}"' for k, n in sorted(p.CONFIG_NAMES.items()))
        lines.append(f"VAL_ {base + node} Key {keys} ;")
    lines.append(f'VAL_ {p.ID_CONFIG_REPLY + node} Result 0 "ok" 1 "bad key" 2 "bad value" 3 "EEPROM failed" ;')
    lines.append("")
    return "\n".join(lines)
