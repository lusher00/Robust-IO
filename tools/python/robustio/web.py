"""Browser dashboard: `robustio web`.

Serves one page and a small JSON API from the Python standard library.
The page polls /api/state five times a second. The board's host timeout is
passed through to the browser: the keepalive only runs while a page has
polled within the last second, so closing the tab, losing the network or
stopping the server lets the board switch everything off.

There is no authentication. By default the server listens on 127.0.0.1 only;
--host 0.0.0.0 opens it to the network, which lets anyone who can reach the
port switch outputs and run motors.

API
  GET  /api/state                          snapshot (see RobustIO.snapshot)
  POST /api/output   {"n": 3, "on": true}
  POST /api/all_off
  POST /api/motor    {"m": 0, "duty": 40}
  POST /api/stop                           outputs off, motors 0
  POST /api/clear
  GET  /api/config                         {"name": value, ...}
  POST /api/config   {"name": "timeout", "value": 1000}
  POST /api/config/save
"""
from __future__ import annotations

import json
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Optional

from . import protocol as p
from .device import ConfigRejected, RobustIO, RobustIOError

CLIENT_TIMEOUT = 1.0


class _State:
    io: RobustIO
    last_poll = 0.0
    lock = threading.Lock()


def _client_alive() -> bool:
    return time.monotonic() - _State.last_poll < CLIENT_TIMEOUT


class Handler(BaseHTTPRequestHandler):
    server_version = "robustio-web"

    def log_message(self, fmt, *args):      # quiet
        pass

    def _send(self, code: int, body, ctype="application/json") -> None:
        data = body if isinstance(body, bytes) else json.dumps(body).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _body(self) -> dict:
        n = int(self.headers.get("Content-Length") or 0)
        if not n:
            return {}
        return json.loads(self.rfile.read(n) or b"{}")

    def do_GET(self):
        io = _State.io
        if self.path in ("/", "/index.html"):
            self._send(200, PAGE.encode(), "text/html; charset=utf-8")
        elif self.path == "/api/state":
            _State.last_poll = time.monotonic()
            snap = io.snapshot()
            snap["config_names"] = {k: [v[1], v[2]] for k, v in p.CONFIG_KEYS.items()}
            self._send(200, snap)
        elif self.path == "/api/config":
            try:
                with _State.lock:
                    self._send(200, io.config_all())
            except RobustIOError as e:
                self._send(502, {"error": str(e)})
        else:
            self._send(404, {"error": "not found"})

    def do_POST(self):
        io = _State.io
        try:
            b = self._body()
            _State.last_poll = time.monotonic()
            with _State.lock:
                if self.path == "/api/output":
                    io.set_output(int(b["n"]), bool(b["on"]))
                elif self.path == "/api/all_off":
                    io.all_off()
                elif self.path == "/api/motor":
                    io.set_motor(int(b["m"]), int(b["duty"]))
                elif self.path == "/api/stop":
                    io.stop()
                elif self.path == "/api/clear":
                    io.clear_faults()
                elif self.path == "/api/config":
                    v = io.config_set(b["name"], int(b["value"]))
                    return self._send(200, {"name": b["name"], "value": v})
                elif self.path == "/api/config/save":
                    io.config_save()
                else:
                    return self._send(404, {"error": "not found"})
            self._send(200, {"ok": True})
        except (KeyError, ValueError, TypeError, ConfigRejected) as e:
            self._send(400, {"error": f"bad request: {e}"})
        except RobustIOError as e:
            self._send(502, {"error": str(e)})


def serve(io: RobustIO, host: str = "127.0.0.1", port: int = 8080, ready: Optional[threading.Event] = None) -> None:
    _State.io = io
    io.keepalive_gate = _client_alive
    httpd = ThreadingHTTPServer((host, port), Handler)
    print(f"Robust IO dashboard on http://{host}:{httpd.server_address[1]}/  (Ctrl-C to stop)")
    if host not in ("127.0.0.1", "localhost"):
        print("warning: no authentication; anyone who can reach this port can switch outputs and run motors")
    if ready:
        ready.port = httpd.server_address[1]
        ready.set()
    try:
        httpd.serve_forever(poll_interval=0.2)
    except KeyboardInterrupt:
        pass
    finally:
        httpd.server_close()
        try:
            io.stop()
        finally:
            io.stop_keepalive()


PAGE = r"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Robust IO</title>
<style>
:root { --bg:#f6f7f9; --card:#fff; --text:#1d2329; --muted:#6b7480; --line:#dde1e6;
        --on:#1f9d55; --off:#9aa3ad; --bad:#d93025; --warn:#c77700; --accent:#2563eb; }
@media (prefers-color-scheme: dark) {
  :root { --bg:#14171b; --card:#1d2127; --text:#e6e9ed; --muted:#9099a4; --line:#2e343c;
          --on:#34c374; --off:#5d6670; --bad:#ff6b5e; --warn:#f0a43a; --accent:#6b9cff; } }
* { box-sizing:border-box }
body { margin:0; font:14px/1.4 system-ui, -apple-system, Segoe UI, sans-serif; background:var(--bg); color:var(--text) }
header { display:flex; flex-wrap:wrap; gap:12px; align-items:baseline; padding:14px 16px; border-bottom:1px solid var(--line) }
header h1 { font-size:18px; margin:0 }
.pill { padding:2px 8px; border-radius:10px; font-size:12px; border:1px solid var(--line) }
.pill.ok { color:var(--on); border-color:var(--on) } .pill.bad { color:var(--bad); border-color:var(--bad) }
main { display:grid; gap:12px; padding:12px 16px; grid-template-columns:repeat(auto-fit, minmax(320px, 1fr)) }
section { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:0 0 10px }
.inputs { display:grid; grid-template-columns:repeat(auto-fill, minmax(64px,1fr)); gap:6px }
.in { border:1px solid var(--line); border-radius:6px; padding:4px 6px; font-size:12px }
.in .dot { display:inline-block; width:9px; height:9px; border-radius:50%; background:var(--off); margin-right:5px }
.in.closed .dot { background:var(--on) } .in small { color:var(--muted); display:block }
.outs { display:grid; grid-template-columns:repeat(auto-fill, minmax(130px,1fr)); gap:8px }
button { font:inherit; padding:6px 10px; border-radius:6px; border:1px solid var(--line); background:var(--card); color:var(--text); cursor:pointer }
button:hover { border-color:var(--accent) }
button.primary { background:var(--accent); border-color:var(--accent); color:#fff }
button.danger { color:var(--bad); border-color:var(--bad) }
.out { text-align:left; width:100% }
.out b { font-size:15px } .out .st { float:right; font-size:12px }
.out.on { border-color:var(--on) } .out.on .st { color:var(--on) }
.out.tripped, .out.fault { border-color:var(--bad) } .out.tripped .st, .out.fault .st { color:var(--bad) }
.out.off-high .st { color:var(--warn) }
.row { display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin:6px 0 }
input[type=number] { width:80px; font:inherit; padding:5px 6px; border-radius:6px; border:1px solid var(--line); background:var(--bg); color:var(--text) }
table { border-collapse:collapse; width:100% } td { padding:3px 4px; border-bottom:1px solid var(--line) } td.u { color:var(--muted) }
section.wide { grid-column:1 / -1 }
.cfgs { display:grid; gap:16px; grid-template-columns:repeat(auto-fit, minmax(300px, 1fr)) }
h3 { font-size:13px; margin:0 0 6px } th { text-align:left; font-weight:500; color:var(--muted); padding:3px 4px }
.muted { color:var(--muted) } .bad { color:var(--bad) } #msg { min-height:1.4em }
</style></head><body>
<header><h1>Robust IO</h1><span id="online" class="pill">connecting</span><span id="info" class="muted"></span><span id="flags"></span></header>
<main>
<section><h2>Inputs</h2><div id="inputs" class="inputs"></div><p id="invalid" class="bad"></p></section>
<section><h2>Outputs</h2><div id="outs" class="outs"></div>
  <div class="row"><button class="danger" onclick="post('/api/all_off')">All off</button>
  <button onclick="post('/api/clear')">Clear faults</button></div></section>
<section><h2>Motors</h2><div id="motors"></div>
  <div class="row"><button class="danger" onclick="post('/api/stop')">Stop all</button></div></section>
<section class="wide"><h2>Settings</h2>
  <div class="cfgs"><div><h3>General</h3><table id="cfg"></table></div>
  <div><h3>Output protection</h3><table id="lim"></table></div></div>
  <div class="row"><button onclick="loadCfg()">Reload</button><button class="primary" onclick="saveCfg()">Save to EEPROM</button></div></section>
</main>
<p id="msg" style="padding:0 16px"></p>
<script>
const $ = id => document.getElementById(id);
let names = null, built = false;
function msg(t, bad) { $('msg').textContent = t; $('msg').className = bad ? 'bad' : 'muted'; }
async function post(path, body) {
  const r = await fetch(path, {method:'POST', headers:{'Content-Type':'application/json'}, body:JSON.stringify(body||{})});
  const j = await r.json().catch(() => ({}));
  if (!r.ok) msg(j.error || ('error ' + r.status), true); else msg(path.replace('/api/','') + ' ok');
  return j;
}
const CONN = {SG0:'J16-1',SG1:'J16-2',SG2:'J16-3',SG3:'J16-4',SG4:'J18-1',SG5:'J18-2',SG6:'J18-3',SG7:'J18-4',
  SG8:'J19-1',SG9:'J19-2',SG10:'J19-3',SG11:'J19-4',SG12:'J14-1',SG13:'J14-2',
  SP0:'J9-1',SP1:'J9-2',SP2:'J9-3',SP3:'J9-4',SP4:'J10-1',SP5:'J10-2',SP6:'J10-3',SP7:'J10-4'};
function build(s) {
  $('inputs').innerHTML = Object.keys(s.inputs.closed).map(n =>
    `<div class="in" id="in_${n}"><span class="dot"></span>${n}<small>${CONN[n]||''}</small></div>`).join('');
  $('outs').innerHTML = s.outputs.map(o =>
    `<button class="out" id="out_${o.n}" onclick="toggle(${o.n})"><b>OUT ${o.n}</b><span class="st"></span><br><span class="a muted"></span></button>`).join('');
  $('motors').innerHTML = [0,1].map(m => `<div class="row"><b>Motor ${m}</b>
     <span id="mstat_${m}" class="muted"></span></div>
     <div class="row"><input type="number" id="duty_${m}" min="-100" max="100" step="1" value="0"> %
     <button class="primary" onclick="setMotor(${m})">Set</button><button onclick="zero(${m})">0</button></div>`).join('') +
     '<p id="mflags" class="muted"></p>';
  built = true;
}
function toggle(n) { const b = $('out_'+n); post('/api/output', {n, on: !b.classList.contains('cmd')}); }
function setMotor(m) {
  const v = parseInt($('duty_'+m).value, 10);
  if (isNaN(v) || v < -100 || v > 100) return msg('duty must be -100..100', true);
  post('/api/motor', {m, duty: v});
}
function zero(m) { $('duty_'+m).value = 0; setMotor(m); }
async function poll() {
  try {
    const s = await (await fetch('/api/state')).json();
    if (!built) build(s);
    names = s.config_names;
    const hb = s.heartbeat;
    $('online').textContent = s.online ? 'online' : 'offline';
    $('online').className = 'pill ' + (s.online ? 'ok' : 'bad');
    $('info').textContent = hb ? `node ${s.node} · firmware ${hb.version} · reset ${hb.reset} · TEC ${hb.tec} REC ${hb.rec}` : `node ${s.node}`;
    $('flags').innerHTML = hb ? [['host active',hb.host_active,''],['host timed out',hb.host_timed_out,'bad'],
       ['config from defaults',hb.config_defaults,''],['motor fault',hb.motor_fault,'bad'],['output latched',hb.output_latched,'bad']]
       .filter(f => f[1]).map(f => `<span class="pill ${f[2]}">${f[0]}</span>`).join(' ') : '';
    for (const [n, c] of Object.entries(s.inputs.closed)) $('in_'+n).classList.toggle('closed', c);
    $('invalid').textContent = s.inputs.valid ? '' : 'inputs not valid: MC33978 not answering';
    for (const o of s.outputs) {
      const b = $('out_'+o.n);
      b.className = 'out ' + o.state + (o.commanded ? ' cmd' : '');
      b.querySelector('.st').textContent = o.state;
      b.querySelector('.a').textContent = o.amps.toFixed(1) + ' A';
    }
    const m = s.motors;
    for (const k of [0,1]) $('mstat_'+k).textContent = `command ${m.command[k]} %, actual ${m.duty[k]} %, ${m.amps[k].toFixed(2)} A`;
    $('mflags').innerHTML = (m.asleep ? 'drivers asleep' : 'drivers awake') + (m.fault_count ? ` · faults ${m.fault_count}` : '') +
       (m.fault_latched ? ' · <span class="bad">FAULT LATCHED, clear faults to run</span>' : '');
  } catch (e) { $('online').textContent = 'no server'; $('online').className = 'pill bad'; }
}
async function loadCfg() {
  const r = await fetch('/api/config'); const c = await r.json();
  if (!r.ok) return msg(c.error, true);
  const general = Object.entries(c).filter(([k]) => !/^(limit|trip)\d$/.test(k));
  $('cfg').innerHTML = general.map(([k, v]) =>
    `<tr><td>${k}</td><td><input type="number" id="cfg_${k}" value="${v}"></td><td class="u">${names ? names[k][0] : ''}</td>
     <td><button onclick="setCfg('${k}')">Set</button></td></tr>`).join('');
  $('lim').innerHTML = '<tr><th>Output</th><th>Trip at, mA</th><th>After, ms</th><th></th></tr>' +
    [0,1,2,3,4,5,6,7].map(n => `<tr><td>OUT ${n}</td>
     <td><input type="number" id="cfg_limit${n}" value="${c['limit'+n]}"></td>
     <td><input type="number" id="cfg_trip${n}" value="${c['trip'+n]}"></td>
     <td><button onclick="setCfg('limit${n}');setCfg('trip${n}')">Set</button></td></tr>`).join('');
}
async function setCfg(k) {
  const v = parseInt($('cfg_'+k).value, 10);
  if (isNaN(v)) return msg('not a number', true);
  const j = await post('/api/config', {name:k, value:v});
  if (j.value !== undefined) $('cfg_'+k).value = j.value;
}
async function saveCfg() { await post('/api/config/save'); }
setInterval(poll, 200); poll(); setTimeout(loadCfg, 800);
</script></body></html>
"""
