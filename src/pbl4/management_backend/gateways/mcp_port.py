"""MCP Client Port — boundary interface for MCP/1 runtime communication.

CANONICAL REFERENCES:
- 02. MCP-1 (Management Control Protocol)
- 04. Cấu trúc mã nguồn (Dependency directions: management_backend → gateways)
- docs/IMPLEMENTATION_CONTRACT.md

CONCURRENCY RULE:
- This file defines the port boundary and a testing fake for Management Backend.
- Do NOT touch or replicate Lâm's MCP/1 binary wire codec in management_protocol.
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from collections.abc import Callable
from typing import Any

logger = logging.getLogger(__name__)

McpMessageHandler = Callable[[str, dict[str, Any]], None]


class McpClientPort(ABC):
    """Abstract port for MCP/1 transport and command dispatch."""

    @abstractmethod
    def connect(self) -> bool:
        """Attempt connection and handshake with Runtime MCP/1 endpoint."""

    @abstractmethod
    def disconnect(self) -> None:
        """Disconnect and clean up transport resources."""

    @property
    @abstractmethod
    def is_connected(self) -> bool:
        """Return True if connection and handshake are currently active."""

    @abstractmethod
    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        """Send a control command packet to Runtime via MCP/1."""

    @abstractmethod
    def request_state(self) -> dict[str, Any] | None:
        """Request immediate STATE_SNAPSHOT from Runtime."""

    @abstractmethod
    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        """Register handler for inbound semantic messages (HELLO_ACK, SNAPSHOT, RESULT, EVENT)."""


class TruthfulDisconnectedMcpPort(McpClientPort):
    """Truthful production port when Lâm's MCP/1 client is not integrated.

    Never pretends to be connected. Truthfully returns disconnected and drops commands.
    """

    def __init__(self) -> None:
        self._handler: McpMessageHandler | None = None

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def connect(self) -> bool:
        logger.info(
            "TruthfulDisconnectedMcpPort: MCP/1 endpoint not integrated; staying disconnected."
        )
        return False

    def disconnect(self) -> None:
        pass

    @property
    def is_connected(self) -> bool:
        return False

    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        logger.warning(
            "TruthfulDisconnectedMcpPort: MCP/1 not connected. Command %s (%s) dropped.",
            command_id,
            command_type,
        )
        return False

    def request_state(self) -> dict[str, Any] | None:
        return None


class FakeMcpClientPort(McpClientPort):
    """In-memory fake port for standalone verification and unit tests."""

    def __init__(
        self,
        initially_connected: bool = False,
        auto_accept_commands: bool = True,
    ) -> None:
        self._connected = initially_connected
        self._auto_accept_commands = auto_accept_commands
        self.dispatched_commands: list[dict[str, Any]] = []
        self.snapshot_to_return: dict[str, Any] | None = None
        self._handler: McpMessageHandler | None = None

    def set_message_handler(self, handler: McpMessageHandler | None) -> None:
        self._handler = handler

    def simulate_inbound(self, msg_type: str, payload: dict[str, Any]) -> None:
        """Deliver an inbound semantic message to the registered gateway handler."""
        if self._handler:
            self._handler(msg_type, payload)

    def simulate_hello_ack(self, payload: dict[str, Any] | None = None) -> None:
        self.simulate_inbound("MGMT_HELLO_ACK", payload or {})

    def simulate_state_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.simulate_inbound("STATE_SNAPSHOT", snapshot)

    def simulate_command_result(
        self,
        command_id: str,
        state: str = "ACCEPTED",
        result: dict[str, Any] | None = None,
    ) -> None:
        self.simulate_inbound(
            "COMMAND_RESULT",
            {"command_id": command_id, "state": state, "result": result or {}},
        )

    def simulate_runtime_event(self, event: dict[str, Any]) -> None:
        self.simulate_inbound("RUNTIME_EVENT", event)

    def connect(self) -> bool:
        self._connected = True
        logger.info("FakeMcpClientPort connected.")
        return True

    def disconnect(self) -> None:
        self._connected = False
        logger.info("FakeMcpClientPort disconnected.")

    @property
    def is_connected(self) -> bool:
        return self._connected

    def set_connected(self, connected: bool) -> None:
        self._connected = connected

    def send_command(
        self,
        command_type: str,
        command_id: str,
        target_id: str,
        payload: dict[str, Any] | None = None,
    ) -> bool:
        if not self._connected:
            logger.warning(
                "FakeMcpClientPort: Not connected, dropped command %s (%s)",
                command_id,
                command_type,
            )
            return False

        record = {
            "command_type": command_type,
            "command_id": command_id,
            "target_id": target_id,
            "payload": payload or {},
        }
        self.dispatched_commands.append(record)
        logger.info("FakeMcpClientPort dispatched: %s", record)

        if self._auto_accept_commands and self._handler:
            # Auto-respond with ACCEPTED so tests don't time out
            self.simulate_command_result(
                command_id=command_id,
                state="ACCEPTED",
                result={"status": "accepted", "command_id": command_id},
            )
        return True

    def request_state(self) -> dict[str, Any] | None:
        if not self._connected:
            return None
        return self.snapshot_to_return
