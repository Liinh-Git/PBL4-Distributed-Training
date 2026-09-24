"""Derive the authoritative manifest from the real canonical worker model."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from torch.nn import functional

from pbl4.adapter.models.resnet18_gn import build_resnet18_groupnorm
from pbl4.adapter.pytorch_adapter import PyTorchAdapter


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--seed", type=int, default=20260910)
    args = parser.parse_args()

    adapter = PyTorchAdapter(
        build_resnet18_groupnorm(initialization_seed=args.seed, device="cpu"),
        functional.cross_entropy,
        local_gradient_reduction="mean",
    )
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        json.dumps(adapter.manifest.to_dict(), sort_keys=True, separators=(",", ":")),
        encoding="utf-8",
    )
    print(adapter.manifest.parameter_manifest_hash)


if __name__ == "__main__":
    main()
