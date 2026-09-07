"""Cryptographic hashing utilities for PBL4.

CANONICAL REFERENCES
--------------------
- 02. Mô hình miền
- 03. Mô hình dữ liệu
- 04. Cấu trúc mã nguồn
- docs/IMPLEMENTATION_CONTRACT.md -> Module-to-Canonical-Document mapping

Used for content-addressable verification of:
- Training contract hash (contract_hash)
- Parameter manifests (parameter_manifest_hash)
- Dataset manifests (dataset_manifest_hash)
- Checkpoint integrity

CANONICAL JSON HASH RESPONSIBILITY
----------------------------------
Canonical hashes (contract_hash, dataset_manifest_hash, parameter_manifest_hash)
require deterministic canonical byte serialization (UTF-8 encoding, deterministic
object-key sorting, deterministic separators/whitespace, formatting-independent digest)
prior to SHA-256 hashing. This module owns the shared responsibility of providing
standardized byte hashing utilities across Management Backend, Dataset Manager, and
Runtime to prevent subsystems from independently inventing incompatible hashing
procedures. Exact canonical JSON serialization rules derive strictly from canonical
data model specifications.
"""

from __future__ import annotations

import hashlib


def sha256_bytes(data: bytes) -> str:
    """Return hex-encoded SHA-256 digest of raw bytes."""
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: str) -> str:
    """Return hex-encoded SHA-256 digest of a file, read in chunks."""
    h = hashlib.sha256()
    with open(path, "rb") as f:
        while chunk := f.read(8192):
            h.update(chunk)
    return h.hexdigest()
