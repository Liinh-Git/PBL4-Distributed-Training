"""ResNet-18 model architecture with Group Normalization.

CANONICAL REFERENCES
--------------------
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

Canonical responsibility:
- Constructs a ResNet-18 model substituting BatchNorm with GroupNorm for distributed training.
- Canonical workload defines ResNet-18 with Group Normalization (GroupNorm) for CIFAR-10
  distributed training to avoid cross-worker batch statistics synchronization over the network.

Important boundary:
- Documents WHAT is canonical without freezing HOW the class is constructed internally.
- Framework-specific model implementation; Runtime remains framework-neutral.

The V1 constructor is intentionally centralized here so every worker and the
local bootstrap derive the exact same Parameter Manifest from the real model.
"""

from __future__ import annotations

from collections.abc import Callable

import torch
from torch import nn
from torchvision.models import resnet18

MODEL_ID = "resnet18_groupnorm"
MODEL_PROFILE = "RESNET18_GROUPNORM_V1"


def _group_norm(channels: int) -> nn.GroupNorm:
    """Return the fixed V1 GroupNorm used at every ResNet normalization site."""
    return nn.GroupNorm(num_groups=32, num_channels=channels)


def build_resnet18_groupnorm(
    *, initialization_seed: int, num_classes: int = 10, device: str = "cpu"
) -> nn.Module:
    """Build the canonical CIFAR-10 ResNet-18 GroupNorm worker model.

    The CIFAR stem uses a 3x3 stride-one convolution and no max-pool.  Model
    initialization is performed under an isolated RNG context so constructing
    the model does not perturb caller RNG state.
    """
    if type(initialization_seed) is not int:
        raise ValueError("initialization_seed must be an integer")
    if type(num_classes) is not int or num_classes <= 0:
        raise ValueError("num_classes must be a positive integer")
    norm_layer: Callable[[int], nn.Module] = _group_norm
    with torch.random.fork_rng(devices=[]):
        torch.manual_seed(initialization_seed)
        model = resnet18(weights=None, num_classes=num_classes, norm_layer=norm_layer)
        model.conv1 = nn.Conv2d(3, 64, kernel_size=3, stride=1, padding=1, bias=False)
        model.maxpool = nn.Identity()
        # The replacement stem is initialized after torchvision constructs the
        # base network; explicitly reinitialize it under the same isolated seed.
        nn.init.kaiming_normal_(model.conv1.weight, mode="fan_out", nonlinearity="relu")
    model.to(torch.device(device))
    model.train()
    return model
