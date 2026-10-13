"""Construct supported worker models with reproducible initialization."""

import torch


def build_model(model_id: str, *, initialization_seed: int, device: str = "cpu"):
    if model_id == "resnet18_groupnorm":
        from pbl4.adapter.models.resnet18_gn import build_resnet18_groupnorm

        return build_resnet18_groupnorm(initialization_seed=initialization_seed, device=device)
    if model_id == "small_cnn":
        from pbl4.adapter.models.small_cnn import SmallCNN

        with torch.random.fork_rng(devices=[]):
            torch.manual_seed(initialization_seed)
            return SmallCNN().to(device)
    raise ValueError(f"Unsupported model_id: {model_id}")
