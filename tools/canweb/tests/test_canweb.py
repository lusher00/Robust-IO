"""End-to-end check on python-can's virtual bus: server, bus view, plugin
commands and the event stream. Run with pytest from tools/canweb."""
import json
import threading
import time
import urllib.error
import urllib.request

import can
import pytest

from canweb.server import main

PORT = 8097
BASE = f"http://127.0.0.1:{PORT}"


@pytest.fixture(scope="module")
def server():
    th = threading.Thread(target=main, args=(["-i", "virtual", "-c", "canweb-test", "--port", str(PORT)],), daemon=True)
    th.start()
    time.sleep(1.0)
    yield


def get(path):
    return json.load(urllib.request.urlopen(BASE + path))


def post(path, body):
    req = urllib.request.Request(BASE + path, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req) as r:
            return r.status, json.load(r)
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read())


def test_bus_and_plugin(server):
    node = can.Bus(interface="virtual", channel="canweb-test")
    seen = []
    stop = threading.Event()

    def pump():
        while not stop.is_set():
            m = node.recv(0.1)
            if m is not None:
                seen.append(m)

    threading.Thread(target=pump, daemon=True).start()
    for _ in range(3):
        node.send(can.Message(arbitration_id=0x100, data=b"\x55\x0a\x03\x00\x00\x00\x00\x00", is_extended_id=False))
        node.send(can.Message(arbitration_id=0x140, data=b"\x00\x03\x00\x00\x00\x00\x00\x00", is_extended_id=False))
        time.sleep(0.05)
    time.sleep(0.2)
    ids = {d["id"]: d for d in get("/api/bus")["ids"]}
    assert 0x100 in ids and ids[0x100]["count"] == 3
    assert get("/api/plugins") == {"robustio": "Robust IO"}

    assert post("/api/send", {"id": "7FF", "data": "de ad"})[0] == 200
    assert post("/api/plugin/robustio", {"cmd": "button", "args": {"id": "out3", "on": True}})[0] == 200
    assert post("/api/plugin/robustio", {"cmd": "zzz", "args": {}})[0] == 400
    time.sleep(0.3)
    sent = [(m.arbitration_id, bytes(m.data)) for m in seen]
    assert (0x7FF, b"\xde\xad") in sent
    assert any(a == 0x200 and d[:2] == b"\x08\x08" for a, d in sent)      # output 3 on

    with urllib.request.urlopen(BASE + "/events") as es:
        frame = json.loads(es.readline()[6:])
    st = frame["plugins"]["robustio"]
    assert st["online"] and len(st["lights"]) == 22 and len(st["buttons"]) == 8 and len(st["series"]) == 10
    assert st["lights"][0]["on"] is True            # bit 0 of 0x55
    stop.set()
    time.sleep(0.2)
    node.shutdown()
