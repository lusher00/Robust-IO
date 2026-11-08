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
  GET  /api/frames?since=N                 CAN frames logged after seq N, sent and received
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
from urllib.parse import parse_qs, urlsplit

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
        url = urlsplit(self.path)
        if url.path == "/api/frames":
            q = parse_qs(url.query)
            try:
                since = int(q.get("since", ["0"])[0])
            except ValueError:
                return self._send(400, {"error": "since must be a number"})
            return self._send(200, io.frames(since))
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
main { display:grid; gap:12px; padding:12px 16px; grid-template-columns:repeat(auto-fit, minmax(min(420px, 100%), 1fr)) }
section { background:var(--card); border:1px solid var(--line); border-radius:8px; padding:12px 14px }
h2 { font-size:13px; text-transform:uppercase; letter-spacing:.05em; color:var(--muted); margin:0 0 10px }
.inputs { display:grid; grid-template-columns:repeat(auto-fill, minmax(64px,1fr)); gap:6px }
.in { border:1px solid var(--line); border-radius:6px; padding:6px; font-size:12px; text-align:center }
.in .dot { display:block; width:16px; height:16px; margin:0 auto 4px; border-radius:50%; background:var(--off); border:1px solid rgba(0,0,0,.25) }
.in.closed .dot { background:var(--on); box-shadow:0 0 8px var(--on) } .in small { color:var(--muted); display:block }
.sw { display:flex; align-items:center; gap:10px; padding:8px 10px; border:1px solid var(--line); border-radius:6px; cursor:pointer; user-select:none }
.sw input { position:absolute; opacity:0; width:0; height:0 }
.sw .track { position:relative; flex:none; width:40px; height:22px; border-radius:11px; background:var(--off); transition:background .15s }
.sw .track::after { content:""; position:absolute; top:3px; left:3px; width:16px; height:16px; border-radius:50%; background:#fff; transition:transform .15s }
.sw input:checked + .track { background:var(--on) } .sw input:checked + .track::after { transform:translateX(18px) }
.sw input:focus-visible + .track { outline:2px solid var(--accent); outline-offset:2px }
.sw .lbl { flex:1 } .sw .st { font-size:12px; color:var(--muted) } .sw .a { font-size:12px; color:var(--muted); min-width:44px; text-align:right; font-variant-numeric:tabular-nums }
.sw.on { border-color:var(--on) } .sw.on .st { color:var(--on) }
.sw.tripped, .sw.fault { border-color:var(--bad) } .sw.tripped .st, .sw.fault .st { color:var(--bad) } .sw.off-high .st { color:var(--warn) }
.motor { border:1px solid var(--line); border-radius:6px; padding:8px 10px; margin-bottom:8px }
.slide { display:flex; align-items:center; gap:8px; margin-top:6px }
.slide input[type=range] { flex:1; min-width:0; accent-color:var(--accent) }
.slide button { width:38px; padding:6px 0; font-size:16px; line-height:1 }
.motor .row output { margin-left:auto; font-size:18px; font-weight:600; font-variant-numeric:tabular-nums }
.slide input[type=range] { height:28px }
.slide output { width:52px; text-align:right; font-weight:600; font-variant-numeric:tabular-nums }
.outs { display:grid; grid-template-columns:repeat(auto-fill, minmax(200px,1fr)); gap:8px }
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
table { border-collapse:collapse; width:100% } .cfgs > div { overflow-x:auto } td { padding:3px 4px; border-bottom:1px solid var(--line) } td.u { color:var(--muted) }
section.wide { grid-column:1 / -1 }
.cfgs { display:grid; gap:16px; grid-template-columns:repeat(auto-fit, minmax(min(300px, 100%), 1fr)) }
h3 { font-size:13px; margin:0 0 6px } th { text-align:left; font-weight:500; color:var(--muted); padding:3px 4px }
.bus { display:grid; gap:12px; grid-template-columns:repeat(auto-fit, minmax(min(420px, 100%), 1fr)) }
.log { height:340px; overflow:auto; border:1px solid var(--line); border-radius:6px; background:var(--bg);
       font:12px/1.45 ui-monospace, SFMono-Regular, Menlo, Consolas, monospace; padding:4px 0 }
.log div { white-space:pre; padding:0 8px } .log div:hover { background:var(--card) }
.log .tx { color:var(--accent) } .log .cmd { font-weight:600 } .log .chg { color:var(--warn) } .log .e { color:var(--bad) }
.log .t { color:var(--muted) }
.ctl label { display:inline-flex; gap:4px; align-items:center; font-size:13px }
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
<section class="wide"><h2>CAN</h2>
  <div class="row ctl"><button id="pause" onclick="togglePause()">Pause</button><button onclick="clearLogs()">Clear</button>
  <label><input type="checkbox" id="f_status" checked onchange="redraw()"> status frames</label>
  <label><input type="checkbox" id="f_ka" onchange="redraw()"> keepalives</label>
  <label><input type="checkbox" id="f_other" checked onchange="redraw()"> other IDs</label>
  <label>ID <input type="text" id="f_id" placeholder="e.g. 200" size="6" oninput="redraw()" style="font:inherit;padding:4px 6px;border-radius:6px;border:1px solid var(--line);background:var(--bg);color:var(--text)"></label>
  <span id="busrate" class="muted"></span></div>
  <div class="bus"><div><h3>Bus traffic</h3><div id="raw" class="log"></div></div>
  <div><h3>Command trace</h3><div id="trace" class="log"></div></div></div></section>
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
    `<label class="sw" id="out_${o.n}"><input type="checkbox" id="chk_${o.n}" onchange="setOut(${o.n}, this.checked)">
     <span class="track"></span><span class="lbl"><b>OUT ${o.n}</b> <span class="st"></span></span><span class="a"></span></label>`).join('');
  $('motors').innerHTML = [0,1].map(m => `<div class="motor"><div class="row" style="margin:0"><b>Motor ${m}</b>
     <span id="mstat_${m}" class="muted"></span><output id="dv_${m}">${s.motors.command[m]} %</output>
     <button onclick="zero(${m})">0</button></div>
     <div class="slide"><button onclick="step(${m},-1)" aria-label="Motor ${m} minus 1">&minus;</button>
     <input type="range" id="duty_${m}" min="-100" max="100" step="1" value="${s.motors.command[m]}"
       oninput="slid(${m})" onchange="sendMotor(${m})" onpointerdown="drag[${m}]=true" onpointerup="drag[${m}]=false">
     <button onclick="step(${m},1)" aria-label="Motor ${m} plus 1">+</button>
</div></div>`).join('') +
     '<p id="mflags" class="muted"></p>';
  built = true;
}
const drag = [false, false], sendT = [0, 0], pending = [null, null];
function setOut(n, on) { post('/api/output', {n, on}); }
function slid(m) { const v = +$('duty_'+m).value; $('dv_'+m).textContent = v + ' %'; throttle(m); }
function throttle(m) {
  const now = Date.now();
  if (now - sendT[m] > 120) { sendT[m] = now; sendMotor(m); }
  else { clearTimeout(pending[m]); pending[m] = setTimeout(() => sendMotor(m), 130); }
}
function sendMotor(m) { sendT[m] = Date.now(); post('/api/motor', {m, duty: +$('duty_'+m).value}); }
function step(m, d) {
  const r = $('duty_'+m); r.value = Math.max(-100, Math.min(100, +r.value + d));
  $('dv_'+m).textContent = r.value + ' %'; sendMotor(m);
}
function zero(m) { $('duty_'+m).value = 0; $('dv_'+m).textContent = '0 %'; sendMotor(m); }
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
      b.className = 'sw ' + o.state;
      $('chk_'+o.n).checked = o.commanded;
      b.querySelector('.st').textContent = o.state;
      b.querySelector('.a').textContent = o.amps.toFixed(1) + ' A';
    }
    const m = s.motors;
    for (const k of [0,1]) {
      $('mstat_'+k).textContent = `actual ${m.duty[k]} %, ${m.amps[k].toFixed(2)} A`;
      if (!drag[k] && Date.now() - sendT[k] > 600) { $('duty_'+k).value = m.command[k]; $('dv_'+k).textContent = m.command[k] + ' %'; }
    }
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
let seq = 0, paused = false, frames = [], last = {}, rateN = 0, rateT = Date.now();
const MAXF = 3000, MAXROWS = 800;
const esc = t => String(t).replace(/[&<>]/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;'}[c]));
const hex3 = n => n.toString(16).toUpperCase().padStart(3, '0');
function ts(t) { const d = new Date(t * 1000);
  return d.toTimeString().slice(0, 8) + '.' + String(d.getMilliseconds()).padStart(3, '0'); }
function ka(f) { return f.name === 'set outputs' && f.text === 'keepalive'; }
function showRaw(f) {
  const want = $('f_id').value.trim().toLowerCase().replace(/^0x/, '');
  if (want && !f.id.toString(16).startsWith(want)) return false;
  if (ka(f)) return $('f_ka').checked;
  if (!f.name) return $('f_other').checked;
  if (!f.cmd) return $('f_status').checked;
  return true;
}
function rawRow(f) {
  const id = f.err ? 'ERR' : f.ext ? f.id.toString(16).toUpperCase().padStart(8, '0') : hex3(f.id);
  const dlc = f.data ? f.data.split(' ').length : 0;
  const cls = (f.dir === 'tx' ? 'tx' : '') + (f.err ? ' e' : '');
  return `<div class="${cls}"><span class="t">${ts(f.t)}</span> ${f.dir.toUpperCase()} ${id.padStart(3)} [${dlc}] ${f.data.padEnd(23)}  ${esc(f.name ? f.name + ': ' + f.text : '')}</div>`;
}
function traceRow(f, change) {
  const who = f.dir === 'tx' ? 'web' : f.cmd ? 'bus' : 'board';
  const cls = f.cmd ? 'cmd' + (f.dir === 'tx' ? ' tx' : '') : change ? 'chg' : '';
  return `<div class="${cls}"><span class="t">${ts(f.t)}</span> ${who.padEnd(5)} ${hex3(f.id)} ${esc(f.name.padEnd(12))} ${esc(f.text)}</div>`;
}
const TRACKED = ['inputs', 'outputs', 'motors'];
function traceOf(f) {
  if (!f.name || ka(f)) return null;
  if (f.cmd || f.name === 'config reply') return traceRow(f, false);
  if (TRACKED.includes(f.name)) {
    const k = f.name + f.node, txt = f.name === 'motors' ? f.text.replace(/ \d+\.\d+ A/g, '') : f.text;
    if (last[k] !== txt) { const first = last[k] === undefined; last[k] = txt; if (!first) return traceRow(f, true); }
  }
  return null;
}
function append(el, html) {
  if (!html) return;
  const stick = el.scrollTop + el.clientHeight >= el.scrollHeight - 30;
  el.insertAdjacentHTML('beforeend', html);
  while (el.childElementCount > MAXROWS) el.firstElementChild.remove();
  if (stick) el.scrollTop = el.scrollHeight;
}
function redraw() {
  $('raw').innerHTML = frames.filter(showRaw).slice(-MAXROWS).map(rawRow).join('');
  $('raw').scrollTop = $('raw').scrollHeight;
}
function clearLogs() { frames = []; $('raw').innerHTML = ''; $('trace').innerHTML = ''; }
function togglePause() { paused = !paused; $('pause').textContent = paused ? 'Resume' : 'Pause'; $('pause').className = paused ? 'primary' : ''; }
async function pollFrames() {
  try {
    const r = await (await fetch('/api/frames?since=' + seq)).json();
    if (r.seq < seq) last = {};
    seq = r.seq; rateN += r.frames.length;
    const now = Date.now();
    if (now - rateT >= 1000) { $('busrate').textContent = Math.round(rateN * 1000 / (now - rateT)) + ' frames/s'; rateN = 0; rateT = now; }
    let raw = '', tr = '';
    for (const f of r.frames) { const t = traceOf(f); if (paused) continue;
      frames.push(f); if (showRaw(f)) raw += rawRow(f); if (t) tr += t; }
    if (frames.length > MAXF) frames.splice(0, frames.length - MAXF);
    append($('raw'), raw); append($('trace'), tr);
  } catch (e) {}
}
setInterval(poll, 200); poll(); setTimeout(loadCfg, 800);
setInterval(pollFrames, 200); pollFrames();
</script></body></html>
"""
