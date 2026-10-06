"""End-to-end tests against the real firmware running in the simulator.

Needs firmware/build/sim and firmware/build/robust-io.elf (bash firmware/test/run_sim.sh
builds both). Skipped when they are missing.
"""
import os
import socket
import subprocess
import time
from pathlib import Path

import pytest

from robustio import RobustIO, RobustIOError, protocol as p
from robustio.simbus import SimBus

FW = Path(os.environ.get("ROBUSTIO_FIRMWARE", Path(__file__).resolve().parents[3] / "firmware"))
SIM = Path(os.environ.get("ROBUSTIO_SIM", FW / "build" / "sim"))
ELF = FW / "build" / "robust-io.elf"

pytestmark = pytest.mark.skipif(not (SIM.exists() and ELF.exists()),
                                reason="simulator not built: bash firmware/test/run_sim.sh")


def _free_port():
    s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


@pytest.fixture
def sim():
    port = _free_port()
    proc = subprocess.Popen([str(SIM), str(ELF), "--udp", str(port)], stdin=subprocess.PIPE,
                            stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
    time.sleep(0.3)
    bus = SimBus(f"127.0.0.1:{port}")
    io = RobustIO(bus, node=0, keepalive=0.2)
    yield io
    io.close()
    bus.shutdown()
    proc.kill()
    proc.wait()


def test_ready(sim):
    hb = sim.wait_ready(5)
    assert hb.version == (0, 3)
    assert hb.inputs_valid and hb.reset_text() == "power-on"
    assert sim.motors.asleep and sim.outputs.commanded == 0


def test_outputs_and_keepalive(sim):
    sim.wait_ready(5)
    sim.set_output(0, True)
    sim.set_output(3, True)
    time.sleep(1.2)                                  # longer than the 500 ms host timeout
    o = sim.wait_for(p.ID_OUTPUTS)
    assert o.commanded == 0x09 and o.on == 0x09
    assert sim.heartbeat.host_active

    sim.stop_keepalive()                             # host goes quiet
    time.sleep(1.0)
    o = sim.wait_for(p.ID_OUTPUTS)
    assert o.commanded == 0
    sim.wait_for(p.ID_HEARTBEAT, 2)
    assert sim.heartbeat.host_timed_out and not sim.heartbeat.host_active


def test_motors(sim):
    sim.wait_ready(5)
    sim.set_motors(40, -25)
    time.sleep(0.5)
    m = sim.wait_for(p.ID_MOTORS)
    assert m.duty == [40, -25] and not m.asleep
    sim.set_motors(0, 0)
    time.sleep(1.5)                                  # ramp down, then 1 s idle sleep
    m = sim.wait_for(p.ID_MOTORS)
    assert m.duty == [0, 0] and m.asleep


def test_config(sim):
    sim.wait_ready(5)
    assert sim.config_get("timeout") == 500
    assert sim.config_set("debounce", 50) == 50
    assert sim.config_get("debounce") == 50
    with pytest.raises(RobustIOError):
        sim.config_set("wet_sg", 3)                  # not a valid wetting current
    sim.config_save()
    all_ = sim.config_all()
    assert all_["rate"] == 250 and all_["limit0"] == 5000
