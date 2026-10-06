"""Terminal dashboard: `robustio tui`.

Keys
  0-7   toggle that output          a   all outputs off
  m     set a motor duty (typed)     s   stop: outputs off, motors 0
  c     clear latched faults         q   quit (sends stop first)

While the dashboard runs it keeps the board's host timeout satisfied. When it
quits, it sends stop and the keepalive ends.
"""
from __future__ import annotations

import curses
import time

from . import protocol as p
from .device import RobustIO, RobustIOError

STATE_ATTR = {}


def _init_colors() -> None:
    if not curses.has_colors():
        return
    curses.start_color()
    curses.use_default_colors()
    for i, fg in enumerate((curses.COLOR_GREEN, curses.COLOR_RED, curses.COLOR_YELLOW, curses.COLOR_CYAN), start=1):
        curses.init_pair(i, fg, -1)
    STATE_ATTR.update({
        "on": curses.color_pair(1) | curses.A_BOLD,
        "tripped": curses.color_pair(2) | curses.A_BOLD,
        "fault": curses.color_pair(2) | curses.A_BOLD,
        "off-high": curses.color_pair(3),
        "closed": curses.color_pair(1) | curses.A_BOLD,
        "title": curses.color_pair(4) | curses.A_BOLD,
        "warn": curses.color_pair(2) | curses.A_BOLD,
    })


def _put(win, y, x, text, attr=0):
    h, w = win.getmaxyx()
    if 0 <= y < h and x < w:
        try:
            win.addnstr(y, x, text, max(0, w - x - 1), attr)
        except curses.error:
            pass


def _prompt(win, y, text) -> str:
    curses.echo()
    curses.curs_set(1)
    win.nodelay(False)
    _put(win, y, 0, " " * 78)
    _put(win, y, 0, text)
    win.refresh()
    try:
        s = win.getstr(y, len(text), 10).decode(errors="ignore").strip()
    finally:
        curses.noecho()
        curses.curs_set(0)
        win.nodelay(True)
    return s


def _draw(win, io: RobustIO, msg: str) -> int:
    win.erase()
    hb = io.heartbeat
    online = io.online()
    _put(win, 0, 0, "Robust IO", STATE_ATTR.get("title", curses.A_BOLD))
    head = f"  node {io.node}"
    if hb:
        head += f"  firmware {hb.version[0]}.{hb.version[1]}  reset {hb.reset_text()}"
    _put(win, 0, 9, head)
    _put(win, 0, 70, "ONLINE " if online else "OFFLINE", 0 if online else STATE_ATTR.get("warn", curses.A_BOLD))

    y = 2
    _put(win, y, 0, "Inputs", curses.A_BOLD)
    if not io.inputs.valid:
        _put(win, y, 8, "not valid (MC33978 not answering)", STATE_ATTR.get("warn", 0))
    y += 1
    for row, names in enumerate((p.INPUT_NAMES[0:7], p.INPUT_NAMES[7:14], p.INPUT_NAMES[14:22])):
        for col, name in enumerate(names):
            closed = io.inputs.closed(name)
            _put(win, y + row, col * 11, f"{name:>4} {'#' if closed else '.'}", STATE_ATTR.get("closed", 0) if closed else 0)
    y += 4

    _put(win, y, 0, "Outputs", curses.A_BOLD)
    y += 1
    for n in range(p.NUM_OUTPUTS):
        st = io.outputs.state(n)
        _put(win, y + n % 4, (n // 4) * 38, f"{n}  {st:9s} {io.currents.amps[n]:5.1f} A", STATE_ATTR.get(st, 0))
    y += 5

    m = io.motors
    _put(win, y, 0, "Motors", curses.A_BOLD)
    _put(win, y, 8, ("asleep" if m.asleep else "awake") + (f"   fault count {m.fault_count}" if m.fault_count else ""))
    if m.fault_latched:
        _put(win, y, 40, "FAULT LATCHED (c clears)", STATE_ATTR.get("warn", 0))
    y += 1
    cmd = io.snapshot()["motors"]["command"]
    for k in range(2):
        _put(win, y + k, 0, f"{k}  command {cmd[k]:+4d} %   actual {m.duty[k]:+4d} %   {m.amps[k]:4.2f} A")
    y += 3

    if hb:
        flags = [t for t, v in (("host active", hb.host_active), ("host timed out", hb.host_timed_out),
                                ("config from defaults", hb.config_defaults)) if v]
        _put(win, y, 0, f"CAN  TEC {hb.tec}  REC {hb.rec}  dropped {hb.tx_dropped}   " + "   ".join(flags))
    y += 2
    _put(win, y, 0, "0-7 toggle output   a all off   m motor duty   s stop   c clear faults   q quit", curses.A_DIM)
    _put(win, y + 1, 0, msg)
    win.refresh()
    return y + 3


def _run(win, io: RobustIO) -> None:
    curses.curs_set(0)
    _init_colors()
    win.nodelay(True)
    msg = "waiting for the board..."
    while True:
        prompt_row = _draw(win, io, msg)
        ch = win.getch()
        if ch == -1:
            time.sleep(0.1)
            continue
        key = chr(ch) if 0 <= ch < 256 else ""
        try:
            if key in "01234567" and key:
                n = int(key)
                on = not (io.outputs.commanded >> n & 1)
                io.set_output(n, on)
                msg = f"output {n} {'on' if on else 'off'}"
            elif key == "a":
                io.all_off()
                msg = "all outputs off"
            elif key == "s":
                io.stop()
                msg = "stopped"
            elif key == "c":
                io.clear_faults()
                msg = "faults cleared"
            elif key == "m":
                mm = _prompt(win, prompt_row, "motor (0 or 1): ")
                if mm not in ("0", "1"):
                    msg = "motor must be 0 or 1"
                    continue
                d = _prompt(win, prompt_row, f"motor {mm} duty, -100..100 %: ")
                duty = int(d)
                if not -100 <= duty <= 100:
                    raise ValueError
                io.set_motor(int(mm), duty)
                msg = f"motor {mm} commanded {duty:+d} %"
            elif key in ("q", "Q"):
                return
        except ValueError:
            msg = "not a number in range"
        except RobustIOError as e:
            msg = str(e)


def run(io: RobustIO) -> None:
    try:
        curses.wrapper(_run, io)
    finally:
        io.stop()
        time.sleep(0.05)
        io.stop_keepalive()
