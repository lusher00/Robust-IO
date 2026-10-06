"""Bring-up and end-of-line test: `robustio bringup`.

Runs the firmware self-test over the UART console, then checks the CAN side
end to end, and writes a plain-text report. Exit status is 0 only if every
step passed.

Without --loads nothing is switched on except briefly in the CAN command
checks, which expect no loads and only check that commands are accepted.
With --loads, the firmware self-test also pulses every output and runs both
motors at 20 %, and each output must draw at least --min-amps.
"""
from __future__ import annotations

import datetime as dt
import re
import time
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from . import protocol as p
from .console import Console, ConsoleError
from .device import RobustIO, RobustIOError


@dataclass
class Step:
    name: str
    passed: bool
    detail: str = ""


@dataclass
class Report:
    serial: str
    started: str
    steps: List[Step] = field(default_factory=list)
    info: List[str] = field(default_factory=list)

    @property
    def passed(self) -> bool:
        return bool(self.steps) and all(s.passed for s in self.steps)

    def text(self) -> str:
        out = [f"Robust IO bring-up report", f"serial: {self.serial}", f"date:   {self.started}", ""]
        out += self.info + [""]
        for s in self.steps:
            out.append(f"{'PASS' if s.passed else 'FAIL'}  {s.name}")
            for line in s.detail.splitlines():
                out.append(f"      {line}")
        n_fail = sum(not s.passed for s in self.steps)
        out += ["", f"RESULT: {'PASS' if self.passed else 'FAIL'} ({len(self.steps) - n_fail} passed, {n_fail} failed)", ""]
        return "\n".join(out)


class Runner:
    def __init__(self, console: Optional[Console], io: RobustIO, serial: str, loads: bool = False,
                 min_amps: float = 0.1, log: Callable[[str], None] = print):
        self.console, self.io, self.loads, self.min_amps, self.log = console, io, loads, min_amps, log
        self.report = Report(serial=serial, started=dt.datetime.now().isoformat(timespec="seconds"))

    def step(self, name: str, passed: bool, detail: str = "") -> bool:
        self.report.steps.append(Step(name, passed, detail))
        self.log(f"{'PASS' if passed else 'FAIL'}  {name}" + (f"\n      {detail.replace(chr(10), chr(10) + '      ')}" if detail and not passed else ""))
        return passed

    # ------------------------------------------------------------ console

    def console_checks(self) -> None:
        c = self.console
        try:
            c.sync(8.0)
        except ConsoleError as e:
            self.step("console responds on J20", False, str(e))
            return
        self.step("console responds on J20", True)

        ver = c.command("ver")
        self.report.info.append("console 'ver':")
        self.report.info += ["  " + l for l in ver.splitlines()]
        m = re.search(r"firmware (\d+)\.(\d+)", ver)
        self.console_version = (int(m.group(1)), int(m.group(2))) if m else None
        self.step("MC33978 and MCP2515 report ok", "MC33978 ok" in ver and "MCP2515 ok" in ver, ver)

        args = " out motor" if self.loads else ""
        out = c.command("selftest" + args, timeout=30.0)
        results = re.findall(r"^(PASS|FAIL)  (.*)$", out, re.M)
        m = re.search(r"selftest: (\d+) passed, (\d+) failed", out)
        ok = bool(m) and int(m.group(2)) == 0
        self.step(f"firmware selftest{args}", ok, out if not ok else f"{m.group(1)} checks passed" if m else out)

        out = c.command("in")
        self.report.info.append("inputs at test time (1 = closed):")
        self.report.info += ["  " + l for l in out.splitlines()[:2]]

    # ------------------------------------------------------------ CAN

    def can_checks(self) -> None:
        io = self.io
        try:
            hb = io.wait_ready(5.0)
        except RobustIOError as e:
            self.step("CAN status frames received", False, str(e))
            return
        self.step("CAN status frames received", True,
                  f"firmware {hb.version[0]}.{hb.version[1]}, reset {hb.reset_text()}")
        self.report.info.append(f"CAN: node {io.node}, firmware {hb.version[0]}.{hb.version[1]}, TEC {hb.tec}, REC {hb.rec}")
        if getattr(self, "console_version", None):
            self.step("CAN and console report the same firmware version", hb.version == self.console_version,
                      f"CAN {hb.version}, console {self.console_version}")
        self.step("CAN error counters zero", hb.tec == 0 and hb.rec == 0, f"TEC {hb.tec} REC {hb.rec}")

        try:
            cfg = io.config_all()
            self.step("settings readable over CAN", True, ", ".join(f"{k}={v}" for k, v in cfg.items() if not k[-1].isdigit()))
        except RobustIOError as e:
            self.step("settings readable over CAN", False, str(e))
            cfg = {}

        # output command round trip
        bad = []
        for n in range(p.NUM_OUTPUTS):
            io.set_output(n, True)
            time.sleep(0.25 if self.loads else 0.15)
            o = io.wait_for(p.ID_OUTPUTS)
            cur = io.wait_for(p.ID_CURRENTS)
            st = o.state(n)
            amps = cur.amps[n]
            io.set_output(n, False)
            time.sleep(0.1)
            if st != "on":
                bad.append(f"out{n}: {st}")
            elif self.loads and amps < self.min_amps:
                bad.append(f"out{n}: {amps:.1f} A, expected at least {self.min_amps} A")
        io.clear_faults()
        self.step("each output switches on by CAN command" + (" and draws current" if self.loads else ""),
                  not bad, "\n".join(bad))

        # motor command round trip
        io.set_motors(20, -20)
        time.sleep(0.4)
        m = io.wait_for(p.ID_MOTORS)
        io.set_motors(0, 0)
        self.step("motors follow CAN command", m.duty == [20, -20] and not m.fault_latched,
                  f"duty {m.duty}, fault latched {m.fault_latched}")

        # host timeout
        timeout_ms = cfg.get("timeout", 500)
        if timeout_ms:
            io.set_output(0, True)
            time.sleep(0.3)
            io.stop_keepalive()
            time.sleep(timeout_ms / 1000 + 0.4)
            o = io.wait_for(p.ID_OUTPUTS)
            hb = io.wait_for(p.ID_HEARTBEAT, 2.0)
            self.step(f"outputs drop when the host goes quiet ({timeout_ms} ms timeout)",
                      o.commanded == 0 and hb.host_timed_out,
                      f"commanded {o.commanded:#04x}, host timed out {hb.host_timed_out}")
        else:
            self.step("host timeout enabled", False, "timeout is 0 (off); set it with 'robustio cfg timeout 500'")

    def run(self) -> Report:
        if self.console is not None:
            self.console_checks()
        self.can_checks()
        try:
            self.io.stop()
            time.sleep(0.05)
        finally:
            self.io.stop_keepalive()
        return self.report
