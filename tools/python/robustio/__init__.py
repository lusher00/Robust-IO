"""Host-side tools for the Robust IO board: protocol, device access, DBC, simulator bus."""
from .device import RobustIO, RobustIOError
from . import protocol

__version__ = "0.3.0"
__all__ = ["RobustIO", "RobustIOError", "protocol", "open_bus"]


def open_bus(interface: str = "socketcan", channel: str = "can0", bitrate: int = 250000, **kwargs):
    """Open a python-can bus. interface 'sim' connects to the firmware simulator."""
    import can
    if interface == "sim":
        from .simbus import SimBus
        return SimBus(channel if channel and channel != "can0" else "127.0.0.1:29536")
    if interface == "socketcan":
        return can.Bus(interface=interface, channel=channel, **kwargs)   # bitrate is set with 'ip link'
    return can.Bus(interface=interface, channel=channel, bitrate=bitrate, **kwargs)
