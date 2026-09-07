"""Update Plan — synchronization decision output for gradient aggregation.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Immutable carrier describing synchronization decision output for an update iteration.
- Identifying admitted worker contributions to aggregate, sample weights, and target ModelVersion.

MUST NOT OWN
------------
- Aggregation execution (owned by Aggregator).
- Update arithmetic (owned by SgdUpdater).
- Admission or barrier evaluation (owned by SynchronizationPolicy).

CRITICAL V1 INVARIANTS
----------------------
- UpdatePlan is immutable once emitted by the synchronization policy.
- Aggregator operates exclusively on the contribution set specified in the UpdatePlan.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations


class UpdatePlan:
    """Describes the decision output of a SynchronizationPolicy.

    Contains which contributions to include in the next update
    and any associated metadata.
    """

    def __init__(self) -> None:
        raise NotImplementedError
