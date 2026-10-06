"""Web dashboard and bring-up runner against the simulated firmware."""
import json
import socket
import threading
import time
import urllib.error
import urllib.request

import pytest

from robustio import RobustIO
from robustio.bringup import Runner
from robustio.console import SimConsole
from robustio.simbus import SimBus

from test_sim import ELF, SIM, _free_port

pytestmark = pytest.mark.skipif(not (SIM.exists() and ELF.exists()),
                                reason="simulator not built: bash firmware/test/run_sim.sh")


def test_bringup_runner_passes_on_sim():
    port = _free_port()
    console = SimConsole(str(SIM), str(ELF), port)
    time.sleep(0.3)
    bus = SimBus(f"127.0.0.1:{port}")
    try:
        with RobustIO(bus) as io:
            report = Runner(console, io, "TEST-1", log=lambda s: None).run()
    finally:
        bus.shutdown()
        console.close()
    assert report.passed, report.text()
    assert len(report.steps) >= 9


def test_bringup_with_loads_fails_without_current():
    port = _free_port()
    console = SimConsole(str(SIM), str(ELF), port)
    time.sleep(0.3)
    bus = SimBus(f"127.0.0.1:{port}")
    try:
        with RobustIO(bus) as io:
            report = Runner(console, io, "TEST-2", loads=True, log=lambda s: None).run()
    finally:
        bus.shutdown()
        console.close()
    failed = [s.name for s in report.steps if not s.passed]
    assert failed == ["each output switches on by CAN command and draws current"]


def test_web_api_and_client_timeout():
    from robustio import web
    port = _free_port()
    import subprocess
    sim = subprocess.Popen([str(SIM), str(ELF), "--udp", str(port)], stdin=subprocess.PIPE,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    time.sleep(0.3)
    bus = SimBus(f"127.0.0.1:{port}")
    io = RobustIO(bus)
    ready = threading.Event()
    t = threading.Thread(target=web.serve, args=(io, "127.0.0.1", 0, ready), daemon=True)
    t.start()
    assert ready.wait(5)
    base = f"http://127.0.0.1:{ready.port}"

    def get(path):
        return json.load(urllib.request.urlopen(base + path, timeout=3))

    def post(path, body=None):
        req = urllib.request.Request(base + path, json.dumps(body or {}).encode(),
                                     {"Content-Type": "application/json"}, method="POST")
        try:
            return 200, json.load(urllib.request.urlopen(req, timeout=3))
        except urllib.error.HTTPError as e:
            return e.code, json.load(e)

    try:
        io.wait_ready(5)
        assert "<title>Robust IO</title>" in urllib.request.urlopen(base + "/").read().decode()
        assert post("/api/output", {"n": 6, "on": True})[0] == 200
        assert post("/api/motor", {"m": 0, "duty": 150})[0] == 400
        assert post("/api/config", {"name": "wet_sg", "value": 3})[0] == 400
        for _ in range(8):                      # a page polling
            s = get("/api/state")
            time.sleep(0.2)
        assert s["outputs"][6]["state"] == "on"
        time.sleep(2.0)                         # page closed: no polling
        s = get("/api/state")
        assert s["outputs"][6]["state"] == "off" and s["heartbeat"]["host_timed_out"]
    finally:
        io.close()
        bus.shutdown()
        sim.kill()
        sim.wait()
