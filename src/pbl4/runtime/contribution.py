"""Contribution — worker gradient contribution value object.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Encapsulation of admitted worker gradient tensors, sample counts, and correlation metadata.
- Immutable representation of a single worker contribution for aggregation.

MUST NOT OWN
------------
- Admission, staleness, or currency decision logic (owned by SynchronizationPolicy).
- Aggregation execution or sample weighting arithmetic (owned by Aggregator).
- Storage or lifecycle retention (owned by GradientStore).

CRITICAL V1 INVARIANTS
----------------------
- Contributions represent validated inputs from registered worker sessions.
- Ingestion and validation are evaluated against active attempt and model version.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class Contribution:
    """A gradient contribution from a worker session."""

    # Implementation pending runtime synchronization phase.
    pass
