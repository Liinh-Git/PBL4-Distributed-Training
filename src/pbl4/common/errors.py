"""PBL4 common error hierarchy.

Defines the root exception and generic protocol/transport error categories.
Subsystem-specific rejection semantics belong to their respective owners.
"""

from __future__ import annotations


class PBL4Error(Exception):
    """Base exception for all PBL4 errors."""


# ─── Generic Protocol Errors ─────────────────────────────


class ProtocolError(PBL4Error):
    """Generic wire protocol violation or malformed frame error."""


# ─── Generic Transport Errors ────────────────────────────


class TransportError(PBL4Error):
    """Generic network transport error."""
