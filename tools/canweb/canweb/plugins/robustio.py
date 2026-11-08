"""Robust IO page: inputs as lights, outputs as buttons with current graphs,
motors as typed duty fields with current graphs, settings as typed fields.
Uses the robustio package's RobustIO device class on the shared bus."""
from __future__ import annotations

import threading

from . import Plugin

try:
    from robustio import RobustIO, protocol as p
    from robustio.device import ConfigRejected, RobustIOError
except ImportError as e:     # robustio not installed
    raise ImportError("robustio package not installed (pip install -e tools/python)") from e


class RobustIOPlugin(Plugin):
    name = "robustio"
    title = "Robust IO"

    def __init__(self, node: int = 0):
        self.node = node
        self.io = None
        self.alive = False
        self.lock = threading.Lock()
        self._config_cache = {}
        self._config_t = 0.0

    def attach(self, bus) -> None:
        self.bus = bus
        # canweb owns the receive thread; RobustIO gets every frame from it.
        self.io = RobustIO(bus.bus, node=self.node, start_reader=False)
        bus.add_listener(self.io._on_message)
        self.io.keepalive_gate = lambda: self.alive

    def detach(self) -> None:
        try:
            self.io.stop()
        finally:
            self.io.stop_keepalive()

    def client_alive(self, alive: bool) -> None:
        self.alive = alive

    def state(self) -> dict:
        io = self.io
        s = io.snapshot()
        hb = s["heartbeat"]
        lights = [{"name": n, "on": v} for n, v in s["inputs"]["closed"].items()]
        buttons = [{"id": f"out{o['n']}", "label": f"OUT_{o['n']}", "on": o["commanded"],
                    "state": o["state"]} for o in s["outputs"]]
        series = [{"name": f"OUT_{o['n']}", "value": o["amps"], "unit": "A"} for o in s["outputs"]]
        series += [{"name": f"motor{m}", "value": s["motors"]["amps"][m], "unit": "A"} for m in range(2)]
        numbers = [{"id": f"motor{m}", "label": f"motor{m} duty", "value": s["motors"]["command"][m],
                    "min": -100, "max": 100, "unit": "%"} for m in range(2)]
        fields = []
        if hb:
            fields = [{"name": "version", "value": hb["version"]}, {"name": "reset", "value": hb["reset"]},
                      {"name": "host_active", "value": hb["host_active"]},
                      {"name": "inputs_valid", "value": hb["inputs_valid"]},
                      {"name": "motor_fault", "value": hb["motor_fault"]},
                      {"name": "output_latched", "value": f"0x{hb['output_latched']:02X}"},
                      {"name": "tec/rec", "value": f"{hb['tec']}/{hb['rec']}"},
                      {"name": "motors asleep", "value": s["motors"]["asleep"]},
                      {"name": "motor duty", "value": s["motors"]["duty"]}]
        config = [{"name": k, "value": v, "unit": p.CONFIG_KEYS[k][1], "help": p.CONFIG_KEYS[k][2]}
                  for k, v in self._config_cache.items()]
        status = "online" if s["online"] else "no heartbeat from node %d" % self.node
        if s["inputs"]["device_fault"]:
            status += ", MC33978 fault"
        return {"online": s["online"], "status": status, "lights": lights, "buttons": buttons,
                "numbers": numbers, "series": series, "fields": fields, "config": config,
                "actions": [{"id": "all_off", "label": "all outputs off"},
                            {"id": "stop", "label": "stop (outputs off, motors 0)"},
                            {"id": "clear", "label": "clear faults"},
                            {"id": "config_read", "label": "read settings"},
                            {"id": "config_save", "label": "save settings to EEPROM"}]}

    def command(self, cmd: str, args: dict) -> dict:
        io = self.io
        with self.lock:
            try:
                if cmd == "button":
                    n = int(args["id"][3:])
                    io.set_output(n, bool(args["on"]))
                elif cmd == "number":
                    m = int(args["id"][5:])
                    io.set_motor(m, int(args["value"]))
                elif cmd == "config":
                    v = io.config_set(args["name"], int(args["value"]))
                    self._config_cache[args["name"]] = v
                    return {"name": args["name"], "value": v}
                elif cmd == "action":
                    a = args["id"]
                    if a == "all_off":
                        io.all_off()
                    elif a == "stop":
                        io.stop()
                    elif a == "clear":
                        io.clear_faults()
                    elif a == "config_read":
                        self._config_cache = io.config_all()
                    elif a == "config_save":
                        io.config_save()
                    else:
                        raise ValueError(f"unknown action {a}")
                else:
                    raise ValueError(f"unknown command {cmd}")
            except ConfigRejected as e:
                raise ValueError(str(e))
            except RobustIOError as e:
                raise RuntimeError(str(e))
        return {"ok": True}

