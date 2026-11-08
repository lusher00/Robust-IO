import struct

import pytest

from robustio import protocol as p
from robustio.dbc import generate


def test_split_id():
    assert p.split_id(0x105) == (0x100, 5)
    assert p.split_id(0x14F) == (0x140, 15)
    assert p.split_id(0x300) is None


def test_inputs():
    i = p.decode_inputs(bytes([0x05, 0x00, 0x20, 0x01]))
    assert i.valid and not i.device_fault
    assert i.closed("SG0") and i.closed(2) and not i.closed("SG1")
    assert i.closed("SP7")                       # bit 21
    assert sum(i.as_dict().values()) == 3


def test_outputs_state():
    o = p.decode_outputs(bytes([0x0F, 0x03, 0x04, 0x08, 0x10]))
    assert [o.state(n) for n in range(5)] == ["on", "on", "tripped", "fault", "off-high"]


def test_motors_signed():
    m = p.decode_motors(bytes([0x32, 0xCE, 120, 5, 0x06, 2]))
    assert m.duty == [50, -50]
    assert m.amps == [1.2, 0.05]
    assert not m.asleep and m.fault_latched and m.fault_pin and m.fault_count == 2


def test_heartbeat():
    h = p.decode_heartbeat(bytes([0x0D, 0x01, 0, 3, 0, 0, 0, 7]))
    assert h.host_active and h.inputs_valid and h.config_defaults and not h.host_timed_out
    assert h.version == (0, 3) and h.tx_dropped == 7 and h.reset_text() == "power-on"


def test_commands():
    assert p.encode_set_outputs(2, 0xFF, 0x03) == (0x202, b"\xff\x03")
    assert p.encode_set_motors(0, 50, -50) == (0x210, struct.pack("<bb", 50, -50))
    assert p.encode_config(0, p.OP_WRITE, p.config_key("timeout"), 1000) == (0x230, bytes([1, 2, 0xE8, 0x03]))
    with pytest.raises(ValueError):
        p.encode_set_motors(0, 101, 0)
    with pytest.raises(KeyError):
        p.config_key("nonsense")


def test_short_frame_rejected():
    with pytest.raises(ValueError):
        p.decode_heartbeat(b"\x00\x01")


cantools = pytest.importorskip("cantools")


@pytest.mark.parametrize("node", [0, 7])
def test_dbc_matches_decoders(node):
    db = cantools.database.load_string(generate(node), "dbc")
    assert db.get_message_by_name("Inputs").frame_id == 0x100 + node

    d = db.decode_message(0x100 + node, bytes([0x05, 0x00, 0x20, 0x01]))
    assert d["SG0"] == 1 and d["SG2"] == 1 and d["SP7"] == 1 and d["InputsValid"] == 1

    d = db.decode_message(0x130 + node, bytes([0x32, 0xCE, 120, 5, 0x06, 2]))
    assert d["Motor0_Duty"] == 50 and d["Motor1_Duty"] == -50
    assert d["Motor0_Current"] == pytest.approx(1.2) and d["MotorFaultCount"] == 2

    d = db.decode_message(0x120 + node, bytes([12, 0, 0, 0, 0, 0, 0, 255]))
    assert d["Out0_Current"] == pytest.approx(1.2) and d["Out7_Current"] == pytest.approx(25.5)

    d = db.decode_message(0x140 + node, bytes([0x0D, 0x01, 0, 3, 0, 0, 0, 7]), decode_choices=False)
    assert d["HostActive"] == 1 and d["VersionMinor"] == 3 and d["TxDropped"] == 7

    data = db.encode_message(0x230 + node, {"Op": 1, "Key": 2, "Value": 1000})
    assert data == p.encode_config(node, p.OP_WRITE, 2, 1000)[1]


def test_describe_commands_and_status():
    assert p.describe(0x200, bytes([0x00, 0x00]))[3] == "keepalive"
    assert p.describe(0x203, bytes([0x81, 0x01])) == ("set outputs", 3, True, "OUT0=on OUT7=off")
    assert p.describe(0x210, bytes([40, 0x9C]))[3] == "M0 +40 %  M1 -100 %"
    assert p.describe(0x230, bytes([1, 0x02, 0xE8, 0x03]))[3] == "write timeout = 1000"
    assert p.describe(0x110, bytes([3, 1, 2, 0, 0]))[3] == "cmd 0,1  on 0  tripped 1"
    assert p.describe(0x100, bytes([1, 0, 0x10, 1]))[3] == "closed SG0 SP6"
    assert p.describe(0x110, b"\x01")[3].startswith("frame too short")
    assert p.describe(0x7FF, b"") is None
