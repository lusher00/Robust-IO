"""robustio command-line tool.

    robustio [-i INTERFACE] [-c CHANNEL] [-b BITRATE] [-n NODE] COMMAND ...

Defaults come from the environment when set: ROBUSTIO_INTERFACE,
ROBUSTIO_CHANNEL, ROBUSTIO_BITRATE, ROBUSTIO_NODE.
"""
from __future__ import annotations

import argparse
import os
import sys
import time

import socket
from pathlib import Path

import can

from . import open_bus, protocol as p
from .device import RobustIO, RobustIOError
from .dbc import generate as generate_dbc


def _bits(v: int, n: int) -> str:
    return "".join("1" if v >> i & 1 else "." for i in range(n))


def format_status(io: RobustIO) -> str:
    hb, i, o, c, m = io.heartbeat, io.inputs, io.outputs, io.currents, io.motors
    lines = []
    if hb:
        flags = [n for n, v in (("host active", hb.host_active), ("host timed out", hb.host_timed_out),
                                ("config defaults", hb.config_defaults), ("motor fault", hb.motor_fault),
                                ("output latched", hb.output_latched)) if v]
        lines.append(f"node {io.node}  firmware {hb.version[0]}.{hb.version[1]}  reset: {hb.reset_text()}  "
                     f"TEC {hb.tec} REC {hb.rec}  dropped {hb.tx_dropped}  {'  '.join(flags)}")
    lines.append(f"inputs  SG0..13 {_bits(i.bits, 14)}  SP0..7 {_bits(i.bits >> 14, 8)}"
                 f"{'' if i.valid else '  (NOT VALID)'}{'  device fault' if i.device_fault else ''}")
    lines.append("outputs " + "  ".join(f"{n}:{o.state(n)} {c.amps[n]:.1f}A" for n in range(p.NUM_OUTPUTS)))
    lines.append(f"motors  0: {m.duty[0]:+4d}% {m.amps[0]:.2f}A   1: {m.duty[1]:+4d}% {m.amps[1]:.2f}A   "
                 f"{'asleep' if m.asleep else 'awake'}"
                 f"{'  FAULT LATCHED' if m.fault_latched else ''}{'  nFAULT low' if m.fault_pin else ''}"
                 f"  faults {m.fault_count}")
    return "\n".join(lines)


def _hold(io: RobustIO, seconds: float) -> None:
    """Keep the command alive and show live status until Ctrl-C or the time runs out.
    When this returns the keepalive stops and the board times out to all-off."""
    end = time.monotonic() + seconds if seconds > 0 else None
    note = "Ctrl-C to stop; the board then times out to all off" if end is None else f"holding for {seconds:g} s"
    try:
        while end is None or time.monotonic() < end:
            sys.stdout.write("\x1b[H\x1b[2J" + format_status(io) + f"\n\n{note}\n")
            sys.stdout.flush()
            time.sleep(0.25)
    except KeyboardInterrupt:
        pass
    print()


def cmd_status(io, a):
    io.wait_ready(a.timeout)
    print(format_status(io))


def cmd_watch(io, a):
    io.wait_ready(a.timeout)
    try:
        while True:
            sys.stdout.write("\x1b[H\x1b[2J" + format_status(io) + "\n\nCtrl-C to quit\n")
            sys.stdout.flush()
            time.sleep(a.interval)
    except KeyboardInterrupt:
        print()


def cmd_dump(io, a):
    def show(base, obj):
        print(f"{time.strftime('%H:%M:%S')} 0x{base + io.node:03X} {obj}")
    io.add_listener(show)
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        print()


def cmd_out(io, a):
    io.wait_ready(a.timeout)
    on = a.state in ("1", "on")
    if a.output == "all":
        if on:
            sys.exit("only 'out all off' is supported")
        io.all_off()
    else:
        io.set_output(int(a.output), on)
    _hold(io, a.hold)


def cmd_motor(io, a):
    io.wait_ready(a.timeout)
    if a.motor == "off":
        io.set_motors(0, 0)
    else:
        io.set_motor(int(a.motor), int(a.duty))
    _hold(io, a.hold)


def cmd_clear(io, a):
    io.clear_faults(int(a.outputs, 0), not a.no_motor)
    print("cleared")


def cmd_cfg(io, a):
    if a.name is None:
        for name, value in io.config_all().items():
            key, unit, desc = p.CONFIG_KEYS[name]
            print(f"{name:9s} {value:6d} {unit:7s} {desc}")
    elif a.name == "save":
        io.config_save()
        print("saved")
    elif a.name == "defaults":
        io.config_defaults()
        print("defaults loaded on the board, not saved")
    elif a.value is None:
        print(io.config_get(a.name))
    else:
        print(f"{a.name} = {io.config_set(a.name, int(a.value, 0))}")
        if a.name in ("node", "rate"):
            print("applies after 'robustio cfg save' and a reset")


def cmd_tui(io, a):
    from .tui import run
    run(io)


def cmd_web(io, a):
    from .web import serve
    serve(io, a.host, a.port)


def _sim_paths(a):
    fw = Path(a.firmware or os.environ.get("ROBUSTIO_FIRMWARE") or Path(__file__).resolve().parents[3] / "firmware")
    sim, elf = fw / "build" / "sim", fw / "build" / "robust-io.elf"
    if not (sim.exists() and elf.exists()):
        sys.exit(f"simulator not built in {fw / 'build'}: run 'bash firmware/test/run_sim.sh' first")
    return str(sim), str(elf)


def cmd_bringup(a) -> int:
    from .bringup import Runner
    from .console import ConsoleError, SimConsole, open_console
    from .simbus import SimBus

    console = None
    if a.sim:
        sim, elf = _sim_paths(a)
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
        s.close()
        console = SimConsole(sim, elf, port)
        time.sleep(0.3)
        bus = SimBus(f"127.0.0.1:{port}")
    else:
        if a.console:
            try:
                console = open_console(a.console)
            except (ConsoleError, OSError) as e:
                sys.exit(f"cannot open console {a.console}: {e}")
        try:
            bus = open_bus(a.interface, a.channel, a.bitrate)
        except (can.CanError, OSError, ValueError) as e:
            sys.exit(f"cannot open {a.interface} {a.channel}: {e}")
    try:
        with RobustIO(bus, a.node) as io:
            report = Runner(console, io, a.serial, loads=a.loads, min_amps=a.min_amps).run()
    finally:
        bus.shutdown()
        if console:
            console.close()
    text = report.text()
    out_dir = Path(a.report)
    out_dir.mkdir(parents=True, exist_ok=True)
    fn = out_dir / f"bringup-{a.serial}-{time.strftime('%Y%m%d-%H%M%S')}.txt"
    fn.write_text(text)
    print()
    print(next((l for l in text.splitlines() if l.startswith("RESULT")), ""))
    print(f"report: {fn}")
    return 0 if report.passed else 1


def cmd_scan(bus, a):
    seen = {}
    end = time.monotonic() + a.seconds
    while time.monotonic() < end:
        msg = bus.recv(0.1)
        if msg is None:
            continue
        r = p.decode(msg.arbitration_id, msg.data)
        if r and r[0] == p.ID_HEARTBEAT:
            seen[r[1]] = r[2]
    if not seen:
        print("no Robust IO nodes heard")
    for node, hb in sorted(seen.items()):
        print(f"node {node}: firmware {hb.version[0]}.{hb.version[1]}, reset {hb.reset_text()}, "
              f"{'host active' if hb.host_active else 'idle'}")


def main(argv=None) -> None:
    env = os.environ.get
    ap = argparse.ArgumentParser(prog="robustio", description="Robust IO CAN tool")
    ap.add_argument("-i", "--interface", default=env("ROBUSTIO_INTERFACE", "socketcan"),
                    help="python-can interface: socketcan, slcan, pcan, gs_usb, ... or 'sim' (default %(default)s)")
    ap.add_argument("-c", "--channel", default=env("ROBUSTIO_CHANNEL", "can0"),
                    help="channel, e.g. can0, /dev/ttyACM0, PCAN_USBBUS1, 127.0.0.1:29536 (default %(default)s)")
    ap.add_argument("-b", "--bitrate", type=int, default=int(env("ROBUSTIO_BITRATE", "250000")))
    ap.add_argument("-n", "--node", type=int, default=int(env("ROBUSTIO_NODE", "0")))
    ap.add_argument("-t", "--timeout", type=float, default=3.0, help="seconds to wait for the board")
    sub = ap.add_subparsers(dest="cmd", required=True)

    sub.add_parser("status", help="print one status snapshot")
    s = sub.add_parser("watch", help="live status screen")
    s.add_argument("--interval", type=float, default=0.25)
    sub.add_parser("dump", help="print every decoded frame from the node")
    s = sub.add_parser("scan", help="list Robust IO nodes on the bus")
    s.add_argument("--seconds", type=float, default=1.5)
    s = sub.add_parser("out", help="switch an output and hold it on")
    s.add_argument("output", help="0..7 or 'all'")
    s.add_argument("state", choices=["0", "1", "on", "off"])
    s.add_argument("--hold", type=float, default=0, help="seconds to hold, 0 = until Ctrl-C")
    s = sub.add_parser("motor", help="run a motor and hold the command")
    s.add_argument("motor", help="0, 1 or 'off'")
    s.add_argument("duty", nargs="?", default="0", help="-100..100 percent")
    s.add_argument("--hold", type=float, default=0, help="seconds to hold, 0 = until Ctrl-C")
    s = sub.add_parser("clear", help="clear latched output trips and the motor fault")
    s.add_argument("--outputs", default="0xFF", help="output mask (default all)")
    s.add_argument("--no-motor", action="store_true")
    s = sub.add_parser("cfg", help="show or change settings: cfg | cfg NAME | cfg NAME VALUE | cfg save | cfg defaults")
    s.add_argument("name", nargs="?")
    s.add_argument("value", nargs="?")
    sub.add_parser("tui", help="terminal dashboard")
    s = sub.add_parser("web", help="browser dashboard")
    s.add_argument("--host", default="127.0.0.1", help="address to listen on (default %(default)s; 0.0.0.0 for the network)")
    s.add_argument("--port", type=int, default=8080)
    s = sub.add_parser("bringup", help="bring-up / end-of-line test with a written report")
    s.add_argument("--console", help="serial port of the J20 console, e.g. /dev/serial0 or /dev/ttyUSB0")
    s.add_argument("--serial", default="unnumbered", help="board serial number for the report")
    s.add_argument("--loads", action="store_true", help="loads are connected: pulse outputs, run motors, check current")
    s.add_argument("--min-amps", type=float, default=0.1, help="minimum output current with --loads")
    s.add_argument("--report", default=".", help="directory for the report file")
    s.add_argument("--sim", action="store_true", help="test the simulated firmware (starts the simulator)")
    s.add_argument("--firmware", help="firmware directory for --sim (default: the one in this repository)")
    s = sub.add_parser("dbc", help="write a DBC file for the node (no bus needed)")
    s.add_argument("-o", "--output", help="file name (default stdout)")
    s.add_argument("-n", "--node", type=int, dest="dbc_node", help="node number (default: the global -n)")
    a = ap.parse_args(argv)

    if a.cmd == "dbc":
        if a.dbc_node is not None:
            a.node = a.dbc_node
        text = generate_dbc(a.node)
        if a.output:
            with open(a.output, "w") as f:
                f.write(text)
            print(f"wrote {a.output} for node {a.node}")
        else:
            sys.stdout.write(text)
        return

    if a.cmd == "bringup":
        sys.exit(cmd_bringup(a))

    try:
        bus = open_bus(a.interface, a.channel, a.bitrate)
    except (can.CanError, OSError, ValueError) as e:
        sys.exit(f"cannot open {a.interface} {a.channel}: {e}")

    try:
        if a.cmd == "scan":
            cmd_scan(bus, a)
            return
        with RobustIO(bus, a.node) as io:
            {"status": cmd_status, "watch": cmd_watch, "dump": cmd_dump, "out": cmd_out,
             "motor": cmd_motor, "clear": cmd_clear, "cfg": cmd_cfg,
             "tui": cmd_tui, "web": cmd_web}[a.cmd](io, a)
    except RobustIOError as e:
        sys.exit(f"error: {e}")
    finally:
        bus.shutdown()


if __name__ == "__main__":
    main()
