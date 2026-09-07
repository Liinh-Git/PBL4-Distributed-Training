"""Base model adapter interface — framework-to-PBL4 abstraction layer.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- Framework interaction: model construction from contract specification,
  local forward/backward computation, and local framework weight loading.
- Parameter manifest generation and validation from framework model structure.
- Exporting framework-neutral parameter and gradient representations to the protocol layer.
- Loading framework-neutral canonical parameter representations into local framework weights.

MUST NOT OWN
------------
- Protocol-level tensor buffer serialization, flattening, or chunking (owned by TensorCodec).
- Raw wire byte serialization or contiguous DTP byte arrays.
- DTP/1 network transport, socket I/O, or message framing.
- Gradient aggregation or synchronization barrier logic.
- Canonical model parameter updating (Runtime owns canonical model and optimizer).
- Database persistence or Management Backend communications.

CRITICAL V1 INVARIANTS
----------------------
- ModelAdapter owns framework interaction; it MUST NOT become a DTP wire serializer.
- Runtime remains strictly framework-neutral; framework dependencies isolate inside adapter.
- Adapter does NOT call optimizer.step() on the canonical distributed model.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from abc import ABC


class ModelAdapter(ABC):  # noqa: B024
    """Abstract model adapter bridging deep learning frameworks to PBL4."""

    # Method signatures will be implemented strictly per canonical model adapter docs.
    pass
