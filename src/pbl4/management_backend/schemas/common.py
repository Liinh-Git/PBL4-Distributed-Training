"""Common schema helpers: pagination, request metadata, error responses."""

from __future__ import annotations

import uuid
from typing import Any, Generic, TypeVar

from pydantic import BaseModel, Field

T = TypeVar("T")


class PageInfo(BaseModel):
    next_cursor: str | None = None


class Meta(BaseModel):
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")


class ListResponse(BaseModel, Generic[T]):
    data: list[T]
    page: PageInfo


class ItemResponse(BaseModel, Generic[T]):
    data: T
    meta: Meta = Field(default_factory=Meta)


class ErrorDetail(BaseModel):
    code: str
    message: str
    details: dict[str, Any] | None = None
    request_id: str = Field(default_factory=lambda: f"req_{uuid.uuid4().hex[:8]}")


class ErrorResponse(BaseModel):
    error: ErrorDetail
