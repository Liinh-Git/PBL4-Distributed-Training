"""DTP/1 (Distributed Training Protocol) — wire-level definitions.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

This package owns:
- Wire constants
- Header structure and framing codec
- Message definitions
- Tensor codec
- Parameter manifest schema

Invariants:
- This package MUST NOT import from runtime, management_backend, worker,
  dataset_manager, torch, or any database library.
- Wire compatibility is the primary concern.
- HeaderCodec does not know about Step semantics.
- operation_id remains a generic correlation ID.
"""

from __future__ import annotations
