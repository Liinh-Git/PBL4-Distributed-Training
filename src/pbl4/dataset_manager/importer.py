"""Dataset Importer — ingestion of raw source datasets.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Ingesting raw dataset sources for the supported V1 reference scope (CIFAR-10).
- Initial validation of dataset samples, format integrity, and metadata extraction.

MUST NOT OWN
------------
- Dataset partitioning into worker shards (owned by Partitioner).
- Serving shards to workers (owned by DatasetService / app).
- Training runtime coordination.
- Claiming arbitrary future archive, generic directory, or remote URI source ecosystems.

CRITICAL V1 INVARIANTS
----------------------
- V1 reference scope is focused on CIFAR-10 ingestion.
- Raw dataset ingestion is completed prior to partitioning and training initialization.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class DatasetImporter:
    """Imports raw datasets into the Dataset Manager's storage."""

    def __init__(self) -> None:
        raise NotImplementedError
