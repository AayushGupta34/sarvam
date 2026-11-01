"""PLC triggers: Modbus TCP coil polling, OPC-UA node polling, and a timed simulator."""
from __future__ import annotations

import socket
import struct
import time
from typing import Protocol


class Trigger(Protocol):
    def fired(self) -> bool: ...


class SimulatedTrigger:
    def __init__(self, period_s: float = 5.0) -> None:
        self.period_s, self.last = period_s, time.monotonic()

    def fired(self) -> bool:
        if time.monotonic() - self.last < self.period_s:
            return False
        self.last = time.monotonic()
        return True


class ModbusTcpTrigger:
    """Fires on the rising edge of one coil, read with function code 1."""

    def __init__(self, host: str, port: int = 502, coil: int = 0, unit: int = 1, timeout: float = 2.0) -> None:
        self.address, self.coil, self.unit, self.timeout = (host, port), coil, unit, timeout
        self.transaction = 0
        self.previous = False

    def read_coil(self) -> bool:
        self.transaction = (self.transaction + 1) & 0xFFFF
        request = struct.pack(">HHHBBHH", self.transaction, 0, 6, self.unit, 1, self.coil, 1)
        with socket.create_connection(self.address, timeout=self.timeout) as sock:
            sock.sendall(request)
            reply = sock.recv(32)
        if len(reply) < 10 or reply[7] != 1:
            raise ConnectionError(f"Modbus exception reply: {reply.hex()}")
        return bool(reply[9] & 1)

    def fired(self) -> bool:
        value = self.read_coil()
        rising = value and not self.previous
        self.previous = value
        return rising


class OpcUaTrigger:
    """Fires on the rising edge of a boolean node. Needs `pip install asyncua`."""

    def __init__(self, url: str, node_id: str) -> None:
        from asyncua.sync import Client

        self.client = Client(url)
        self.client.connect()
        self.node = self.client.get_node(node_id)
        self.previous = False

    def fired(self) -> bool:
        value = bool(self.node.read_value())
        rising = value and not self.previous
        self.previous = value
        return rising
