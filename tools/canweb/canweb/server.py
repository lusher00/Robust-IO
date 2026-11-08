"""HTTP server: one page, a JSON API and a server-sent-events stream.

GET  /                      the page
GET  /events                SSE: {"bus": ..., "plugins": {name: state}} 5 times a second
GET  /api/bus               bus snapshot (same as the SSE bus part)
POST /api/send              {"id": "123", "data": "01 02", "ext": false}
POST /api/clear             reset per-ID statistics
POST /api/dbc               {"path": "/home/pi/x.dbc"}  load a DBC for decoding
GET  /api/log?limit=500     last frames
POST /api/log/save          {"path": "/home/pi/log.csv"}
GET  /api/plugins           {name: title}
POST /api/plugin/<name>     {"cmd": "button", "args": {...}}  (see plugins/__init__.py)

No authentication. Listens on 127.0.0.1 unless --host says otherwise.
"""
from __future__ import annotations

import argparse
import json
import os
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from .bus import CanBus
from .plugins import load_plugins

STATIC = os.path.join(os.path.dirname(__file__), "static")
EVENT_PERIOD = 0.2
CLIENT_TIMEOUT = 1.5


class App:
    bus: CanBus
    plugins: dict
    last_client = 0.0
    lock = threading.Lock()

    @classmethod
    def touch(cls) -> None:
        cls.last_client = time.monotonic()
        for pl in cls.plugins.values():
            pl.client_alive(True)

    @classmethod
    def watchdog(cls) -> None:
        while True:
            time.sleep(0.5)
            if time.monotonic() - cls.last_client > CLIENT_TIMEOUT:
                for pl in cls.plugins.values():
                    pl.client_alive(False)

    @classmethod
    def frame(cls) -> dict:
        states = {}
        for name, pl in cls.plugins.items():
            try:
                states[name] = pl.state()
            except Exception as e:
                states[name] = {"online": False, "status": f"plugin error: {e}"}
        return {"bus": cls.bus.snapshot(), "plugins": states, "t": time.time()}


class Handler(BaseHTTPRequestHandler):
    server_version = "canweb"

    def log_message(self, fmt, *args):
        pass

    def _send(self, code, body, ctype="application/json"):
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def do_GET(self):
        u = urlparse(self.path)
        if u.path in ("/", "/index.html"):
            with open(os.path.join(STATIC, "index.html"), "rb") as f:
                self._send(200, f.read(), "text/html; charset=utf-8")
        elif u.path == "/events":
            self._events()
        elif u.path == "/api/bus":
            self._send(200, App.bus.snapshot())
        elif u.path == "/api/plugins":
            self._send(200, {n: pl.title for n, pl in App.plugins.items()})
        elif u.path == "/api/log":
            q = parse_qs(u.query)
            self._send(200, App.bus.log_rows(int(q.get("limit", ["500"])[0])))
        else:
            self._send(404, {"error": "not found"})

    def _events(self):
        self.send_response(200)
        self.send_header("Content-Type", "text/event-stream")
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        try:
            while True:
                App.touch()
                payload = json.dumps(App.frame())
                self.wfile.write(f"data: {payload}\n\n".encode())
                self.wfile.flush()
                time.sleep(EVENT_PERIOD)
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass

    def do_POST(self):
        u = urlparse(self.path)
        try:
            b = self._body()
            App.touch()
            if u.path == "/api/send":
                arb = int(str(b["id"]), 16)
                data = bytes.fromhex(str(b.get("data", "")).replace(" ", ""))
                App.bus.send(arb, data, bool(b.get("ext", arb > 0x7FF)))
                return self._send(200, {"ok": True})
            if u.path == "/api/clear":
                App.bus.clear_stats()
                return self._send(200, {"ok": True})
            if u.path == "/api/dbc":
                return self._send(200, {"ok": True, "info": App.bus.load_dbc(b["path"])})
            if u.path == "/api/log/save":
                return self._send(200, {"ok": True, "frames": App.bus.write_log(b["path"])})
            if u.path.startswith("/api/plugin/"):
                name = u.path[len("/api/plugin/"):]
                pl = App.plugins.get(name)
                if pl is None:
                    return self._send(404, {"error": f"no plugin {name}"})
                with App.lock:
                    return self._send(200, pl.command(b.get("cmd", ""), b.get("args", {})))
            self._send(404, {"error": "not found"})
        except (KeyError, ValueError, TypeError) as e:
            self._send(400, {"error": str(e)})
        except Exception as e:
            self._send(502, {"error": str(e)})


def main(argv=None):
    ap = argparse.ArgumentParser(prog="canweb", description="CAN diagnostic web app")
    ap.add_argument("-i", "--interface", default=os.environ.get("CANWEB_INTERFACE", "socketcan"))
    ap.add_argument("-c", "--channel", default=os.environ.get("CANWEB_CHANNEL", "can0"))
    ap.add_argument("-b", "--bitrate", type=int, default=int(os.environ.get("CANWEB_BITRATE", "250000")))
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8090)
    ap.add_argument("--dbc", help="DBC file to load at start")
    ap.add_argument("--plugin", action="append", default=[], help="module:Class, repeatable")
    ap.add_argument("--no-plugins", action="store_true", help="bus view only")
    a = ap.parse_args(argv)

    bus = CanBus(a.interface, a.channel, a.bitrate)
    bus.open()
    if a.dbc:
        print("dbc:", bus.load_dbc(a.dbc))
    App.bus = bus
    App.plugins = {} if a.no_plugins else load_plugins(a.plugin)
    for pl in App.plugins.values():
        pl.attach(bus)
    threading.Thread(target=App.watchdog, daemon=True).start()

    httpd = ThreadingHTTPServer((a.host, a.port), Handler)
    print(f"canweb on http://{a.host}:{a.port}/  bus {a.interface}:{a.channel}  plugins: {', '.join(App.plugins) or 'none'}")
    if a.host not in ("127.0.0.1", "localhost"):
        print("warning: no authentication; anyone who can reach this port can send frames and drive plugins")
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        for pl in App.plugins.values():
            try:
                pl.detach()
            except Exception:
                pass
        bus.close()


if __name__ == "__main__":
    main()
