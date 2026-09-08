"""Pydantic schemas for Command endpoints.

Aligned to api_contract_formatted.md — BE Command group.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel


class CommandListItem(BaseModel):
    command_id: str
    command_type: str
    state: str
    target_type: str
    target_id: str | None = None
    requested_at: datetime
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None


class CommandResult(BaseModel):
    code: str
    message: str | None = None


class CommandDetail(BaseModel):
    command_id: str
    command_type: str
    state: str
    target_type: str
    target_id: str | None = None
    request: dict[str, Any] = {}
    result: CommandResult | None = None
    requested_at: datetime
    dispatched_at: datetime | None = None
    completed_at: datetime | None = None
