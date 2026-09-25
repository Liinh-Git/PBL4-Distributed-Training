"""Authoritative dataset artifact-origin validation."""

import pytest

from pbl4.common.artifact_origin import derive_root_manifest_path, resolve_artifact_url


def test_local_and_hf_style_root_manifest_paths() -> None:
    local = "http://127.0.0.1:8001/artifacts/v1/dataset-builds/build-1"
    assert derive_root_manifest_path(local, f"{local}/manifest.json") == "manifest.json"

    remote = "https://huggingface.co/datasets/org/repo/resolve/rev/dataset-builds/build-1"
    assert (
        derive_root_manifest_path(remote, f"{remote}/dataset-manifest.json")
        == "dataset-manifest.json"
    )
    assert resolve_artifact_url(remote, "shards/000/shard-manifest.json").startswith(remote)


@pytest.mark.parametrize(
    ("base", "manifest"),
    [
        ("https://good.example/build", "https://evil.example/build/manifest.json"),
        ("https://good.example/build", "https://good.example/manifest.json"),
        ("https://good.example/build", "https://good.example/build/%2e%2e/secret"),
    ],
)
def test_manifest_uri_escape_is_rejected(base: str, manifest: str) -> None:
    with pytest.raises(ValueError):
        derive_root_manifest_path(base, manifest)


@pytest.mark.parametrize("path", ["../secret", "%2e%2e/secret", "/absolute", "a\\..\\secret"])
def test_relative_artifact_escape_is_rejected(path: str) -> None:
    with pytest.raises(ValueError):
        resolve_artifact_url("https://good.example/build", path)
