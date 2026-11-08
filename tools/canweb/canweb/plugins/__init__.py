"""Product plugins.

A plugin turns raw frames from one product into a page the browser can draw
without knowing the product: lights (inputs), buttons (outputs), typed number
fields, series for graphs, text fields, and actions. The page is generic; the
plugin supplies names and values.

    class MyPlugin(Plugin):
        name = "myproduct"            # URL and tab name
        title = "My Product"
        def attach(self, bus): ...    # bus.add_listener(self.on_frame), create device objects
        def state(self) -> dict: ...  # see Plugin.state for the layout
        def command(self, cmd: str, args: dict) -> dict: ...
        def client_alive(self, alive: bool): ...  # a browser page is (not) connected

Register with an entry point in the "canweb.plugins" group, or pass
--plugin module:Class on the command line.
"""
from __future__ import annotations

from typing import Dict, List


class Plugin:
    name = "plugin"
    title = "Plugin"

    def attach(self, bus) -> None:
        self.bus = bus

    def detach(self) -> None:
        pass

    def client_alive(self, alive: bool) -> None:
        pass

    def state(self) -> dict:
        """Layout, every key optional:
        online:  bool
        status:  str                       one line under the title
        lights:  [{name, on, label?}]      indicator per input
        buttons: [{id, label, on}]         toggles; command("button", {id, on})
        numbers: [{id, label, value, min, max, unit?}]   typed; command("number", {id, value})
        series:  [{name, value, unit}]     graphed by the page, 5 Hz, 60 s
        fields:  [{name, value}]           read-only text
        config:  [{name, value, min, max, unit?}]       typed; command("config", {name, value})
        actions: [{id, label}]             command("action", {id})
        """
        return {"online": False}

    def command(self, cmd: str, args: dict) -> dict:
        raise ValueError(f"unknown command {cmd}")


def load_plugins(specs: List[str]) -> Dict[str, Plugin]:
    """Instantiate plugins from entry points plus explicit module:Class specs."""
    found: Dict[str, Plugin] = {}
    try:
        from importlib.metadata import entry_points
        eps = entry_points()
        group = eps.select(group="canweb.plugins") if hasattr(eps, "select") else eps.get("canweb.plugins", [])
        for ep in group:
            try:
                cls = ep.load()
                found[cls.name] = cls()
            except Exception as e:           # missing optional dependency, keep going
                print(f"plugin {ep.name}: {e}")
    except Exception:
        pass
    for spec in specs:
        mod, _, cls_name = spec.partition(":")
        import importlib
        cls = getattr(importlib.import_module(mod), cls_name)
        found[cls.name] = cls()
    return found
