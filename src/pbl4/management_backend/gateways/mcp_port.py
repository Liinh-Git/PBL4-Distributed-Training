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
from typing import Any

logger = logging.getLogger(__name__)


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


class FakeMcpClientPort(McpClientPort):
    """In-memory fake port for standalone verification and unit tests."""

    def __init__(self, initially_connected: bool = False) -> None:
        self._connected = initially_connected
        self.dispatched_commands: list[dict[str, Any]] = []
        self.snapshot_to_return: dict[str, Any] | None = None

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
        return True

    def request_state(self) -> dict[str, Any] | None:
        if not self._connected:
            return None
        return self.snapshot_to_return
