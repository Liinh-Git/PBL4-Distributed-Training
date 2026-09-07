"""Dataset Manager — dataset ingestion, partitioning, and serving.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

This process handles:
- Dataset import and preprocessing
- Partitioning into worker shards
- Serving shards to workers via HTTP
- Manifest management

The Dataset Manager does NOT know about:
- Barriers or synchronization
- Gradients or canonical model
- Training step semantics

Build artifacts before training. A Dataset Build may become READY only after artifact
materialization and integrity verification are complete AND management registration
has been successfully acknowledged by Management Backend.
Console entrypoint: pbl4.dataset_manager.entrypoint:main
"""

from __future__ import annotations
