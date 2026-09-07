"""MCP/1 (Management Control Protocol) — wire-level definitions.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

This package owns ONLY:
- Wire constants
- Wire message definitions
- Codec

Networking lifecycle lives in:
- runtime/management_endpoint.py (Runtime side)
- management_backend/gateways/runtime_gateway.py (Management Backend side)

This package MUST NOT contain networking, lifecycle, or application logic.
"""

from __future__ import annotations

# MCP/1 protocol version representation is defined in canonical wire specifications
# and must be taken directly from them during implementation.
