"""PyTorch model adapter — bridges PyTorch nn.Module to PBL4 contracts.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

OWNS
----
- PyTorch nn.Module instantiation and local forward/loss/backward execution.
- Exporting PyTorch model parameters and gradients to framework-neutral tensor representations.
- Ingesting framework-neutral canonical parameter representations into
  PyTorch parameters/state_dict.

MUST NOT OWN
------------
- Raw wire byte serialization or DTP chunk serialization (owned by TensorCodec in protocol layer).
- DTP/1 wire framing or socket transport.
- Gradient aggregation or synchronization barrier mechanics.
- External distributed training frameworks (forbidden: DDP, FSDP, Horovod, DeepSpeed).
- Database or Management Backend dependencies.

CRITICAL V1 INVARIANTS
----------------------
- ModelAdapter bridges PyTorch to framework-neutral representations;
  TensorCodec handles DTP wire bytes.
- Isolated to worker/adapter boundary; Runtime never imports PyTorch.
- Uses custom DTP/1 and Parameter Server architecture; no PyTorch distributed primitives.

IMPLEMENTATION STATUS
---------------------
Scaffold only. Core behavior is intentionally not implemented.
"""

from __future__ import annotations

from pbl4.adapter.base import ModelAdapter


class PyTorchAdapter(ModelAdapter):
    """ModelAdapter implementation for PyTorch."""

    # Implementation pending worker adapter phase.
    pass
