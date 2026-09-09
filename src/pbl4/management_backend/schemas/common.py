"""Common schema helpers: pagination, request metadata, error responses."""

from __future__ import annotations

import uuid
from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class StrictWriteModel(BaseModel):
    """Base model for all write/mutation request DTOs; strictly forbids unexpected fields."""

    model_config = ConfigDict(extra="forbid")


class PageInfo(BaseModel):
    next_cursor: str | None = None


class Meta(BaseModel):
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")


class ListResponse[T](BaseModel):
    data: list[T]
    page: PageInfo


class ItemResponse[T](BaseModel):
    data: T
    meta: Meta = Field(default_factory=Meta)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")
    command_id: str | None = None


class ErrorResponse(BaseModel):
    error: ErrorDetail
