"""python-can bus that talks to the firmware simulator (firmware/test/sim.c --udp PORT).

Lets every tool run against the real firmware, simulated, with no hardware:

    bash firmware/test/run_sim.sh live        # in one terminal
    robustio --interface sim status           # in another
"""
from __future__ import annotations

import select
import socket
import time
from typing import Optional, Tuple

import can


class SimBus(can.BusABC):
    """channel is 'host:port', default 127.0.0.1:29536."""

    def __init__(self, channel: str = "127.0.0.1:29536", **kwargs):
        host, _, port = (channel or "127.0.0.1:29536").partition(":")
        self._addr = (host or "127.0.0.1", int(port or 29536))
        self._sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        self._sock.bind(("127.0.0.1", 0))
        self._sock.setblocking(False)
        self.channel_info = f"simulator at {self._addr[0]}:{self._addr[1]}"
        super().__init__(channel=channel, **kwargs)
        self._sock.sendto(b"\x00\x00\x00", self._addr)        # announce ourselves; ID 0 is ignored by the firmware

    def send(self, msg: can.Message, timeout: Optional[float] = None) -> None:
        if msg.is_extended_id:
            raise can.CanError("the simulator carries standard IDs only")
        data = bytes(msg.data)[:8]
        self._sock.sendto(bytes([msg.arbitration_id >> 8, msg.arbitration_id & 0xFF, len(data)]) + data, self._addr)

    def _recv_internal(self, timeout: Optional[float]) -> Tuple[Optional[can.Message], bool]:
        r, _, _ = select.select([self._sock], [], [], timeout)
        if not r:
            return None, False
        pkt, _ = self._sock.recvfrom(64)
        if len(pkt) < 3 or len(pkt) < 3 + pkt[2]:
            return None, False
        msg = can.Message(arbitration_id=pkt[0] << 8 | pkt[1], data=pkt[3:3 + pkt[2]],
                          is_extended_id=False, timestamp=time.time(), channel=self.channel_info)
        return msg, False

    def shutdown(self) -> None:
        super().shutdown()
        self._sock.close()
