"""Line-based access to the firmware's UART console (J20, 115200 8N1)."""
from __future__ import annotations

import os
import select
import subprocess
import time
from typing import Optional


class ConsoleError(Exception):
    pass


class Console:
    """Base: subclasses provide _write(bytes) and _read(timeout) -> bytes."""

    PROMPT = "\n> "

    def _write(self, data: bytes) -> None:
        raise NotImplementedError

    def _read(self, timeout: float) -> bytes:
        raise NotImplementedError

    def read_until(self, marker: str, timeout: float) -> str:
        buf = ""
        end = time.monotonic() + timeout
        while marker not in buf:
            left = end - time.monotonic()
            if left <= 0:
                raise ConsoleError(f"timed out waiting for {marker!r}; got {buf[-200:]!r}")
            buf += self._read(min(left, 0.1)).decode(errors="replace").replace("\r", "")
        return buf

    def sync(self, timeout: float = 5.0) -> None:
        """Get to a fresh prompt (sends an empty line)."""
        self.drain()
        self._write(b"\r")
        self.read_until("> ", timeout)

    def drain(self) -> str:
        out = b""
        while True:
            chunk = self._read(0.05)
            if not chunk:
                return out.decode(errors="replace")
            out += chunk

    def command(self, line: str, timeout: float = 5.0) -> str:
        """Send one command and return its output, without the echo and the prompt."""
        self.drain()
        self._write(line.encode() + b"\r")
        text = self.read_until(self.PROMPT, timeout)
        body = text.rsplit(self.PROMPT, 1)[0]
        lines = body.split("\n")
        if lines and lines[0].strip().endswith(line.strip()):
            lines = lines[1:]
        return "\n".join(lines).strip("\n")

    def close(self) -> None:
        pass


class SerialConsole(Console):
    def __init__(self, port: str, baud: int = 115200):
        try:
            import serial
        except ImportError:
            raise ConsoleError("pyserial is needed for a serial console: pip install pyserial") from None
        self._s = serial.Serial(port, baud, timeout=0)

    def _write(self, data: bytes) -> None:
        for b in data:                      # the firmware buffers 64 bytes; pace like a person typing fast
            self._s.write(bytes([b]))
            time.sleep(0.001)

    def _read(self, timeout: float) -> bytes:
        end = time.monotonic() + timeout
        while True:
            data = self._s.read(4096)
            if data or time.monotonic() >= end:
                return data
            time.sleep(0.005)

    def close(self) -> None:
        self._s.close()


class SimConsole(Console):
    """Starts the firmware simulator in live mode and talks to its console.
    The CAN side is reachable with SimBus on the same port."""

    def __init__(self, sim: str, elf: str, port: int):
        self.port = port
        self._p = subprocess.Popen([sim, elf, "--udp", str(port)], stdin=subprocess.PIPE,
                                   stdout=subprocess.PIPE, stderr=subprocess.STDOUT, bufsize=0)
        os.set_blocking(self._p.stdout.fileno(), False)

    def _write(self, data: bytes) -> None:
        # The simulator reads whole lines from stdin and types them in.
        self._p.stdin.write(data.replace(b"\r", b"\n"))
        self._p.stdin.flush()

    def _read(self, timeout: float) -> bytes:
        r, _, _ = select.select([self._p.stdout], [], [], timeout)
        if not r:
            return b""
        try:
            return self._p.stdout.read(4096) or b""
        except BlockingIOError:
            return b""

    def close(self) -> None:
        self._p.kill()
        self._p.wait()


def open_console(spec: str, baud: int = 115200) -> Console:
    return SerialConsole(spec, baud)
