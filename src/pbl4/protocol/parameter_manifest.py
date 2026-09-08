"""Framework-neutral canonical Parameter Manifest V1."""

from __future__ import annotations

import json
from dataclasses import dataclass

from pbl4.common.errors import ProtocolError
from pbl4.common.hashing import sha256_bytes
from pbl4.protocol.constants import FLOAT32_BYTES, PARAMETER_MANIFEST_SCHEMA_VERSION


def _integer(value: object, name: str, *, minimum: int = 0) -> int:
    if type(value) is not int or value < minimum:
        raise ProtocolError(f"{name} must be an integer >= {minimum}")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value:
        raise ProtocolError(f"{name} must be a non-empty string")
    return value


@dataclass(frozen=True, slots=True)
class ParameterEntry:
    tensor_id: int
    name: str
    shape: tuple[int, ...]
    dtype: str
    numel: int
    byte_offset: int
    byte_length: int

    def __post_init__(self) -> None:
        _integer(self.tensor_id, "tensor_id")
        _string(self.name, "name")
        object.__setattr__(self, "shape", tuple(self.shape))
        if not self.shape or any(type(dim) is not int or dim <= 0 for dim in self.shape):
            raise ProtocolError("shape must contain positive integer dimensions")
        if self.dtype != "float32":
            raise ProtocolError("DTP/1 V1 Parameter Manifest dtype must be float32")
        expected_numel = 1
        for dim in self.shape:
            expected_numel *= dim
        if _integer(self.numel, "numel", minimum=1) != expected_numel:
            raise ProtocolError("numel does not equal the product of shape")
        _integer(self.byte_offset, "byte_offset")
        if _integer(self.byte_length, "byte_length", minimum=1) != self.numel * FLOAT32_BYTES:
            raise ProtocolError("byte_length must equal numel * 4")

    def to_dict(self) -> dict[str, object]:
        return {
            "tensor_id": self.tensor_id,
            "name": self.name,
            "shape": list(self.shape),
            "dtype": self.dtype,
            "numel": self.numel,
            "byte_offset": self.byte_offset,
            "byte_length": self.byte_length,
        }

    @classmethod
    def from_dict(cls, value: object) -> ParameterEntry:
        if not isinstance(value, dict):
            raise ProtocolError("Parameter entry must be an object")
        expected = {
            "tensor_id",
            "name",
            "shape",
            "dtype",
            "numel",
            "byte_offset",
            "byte_length",
        }
        if set(value) != expected:
            raise ProtocolError("Parameter entry fields do not match the V1 schema")
        shape = value["shape"]
        if not isinstance(shape, list):
            raise ProtocolError("shape must be an array")
        return cls(
            tensor_id=_integer(value["tensor_id"], "tensor_id"),
            name=_string(value["name"], "name"),
            shape=tuple(shape),
            dtype=_string(value["dtype"], "dtype"),
            numel=_integer(value["numel"], "numel", minimum=1),
            byte_offset=_integer(value["byte_offset"], "byte_offset"),
            byte_length=_integer(value["byte_length"], "byte_length", minimum=1),
        )


@dataclass(frozen=True, slots=True)
class ParameterManifest:
    parameter_manifest_hash: str
    schema_version: int
    total_numel: int
    total_bytes: int
    parameters: tuple[ParameterEntry, ...]

    def __post_init__(self) -> None:
        object.__setattr__(self, "parameters", tuple(self.parameters))
        if self.schema_version != PARAMETER_MANIFEST_SCHEMA_VERSION:
            raise ProtocolError("Unsupported Parameter Manifest schema_version")
        if not self.parameters:
            raise ProtocolError("Parameter Manifest must contain parameters")
        if len({item.tensor_id for item in self.parameters}) != len(self.parameters):
            raise ProtocolError("Parameter Manifest tensor_id values must be unique")
        if len({item.name for item in self.parameters}) != len(self.parameters):
            raise ProtocolError("Parameter Manifest parameter names must be unique")
        if tuple(item.tensor_id for item in self.parameters) != tuple(
            sorted(item.tensor_id for item in self.parameters)
        ):
            raise ProtocolError("Parameter Manifest entries must be ordered by tensor_id")
        offset = 0
        for item in self.parameters:
            if item.byte_offset != offset:
                raise ProtocolError(
                    "Parameter Manifest byte layout must be contiguous and gap-free"
                )
            offset += item.byte_length
        if _integer(self.total_numel, "total_numel", minimum=1) != sum(
            item.numel for item in self.parameters
        ):
            raise ProtocolError("Parameter Manifest total_numel mismatch")
        if _integer(self.total_bytes, "total_bytes", minimum=1) != offset:
            raise ProtocolError("Parameter Manifest total_bytes mismatch")
        if self.total_bytes != self.total_numel * FLOAT32_BYTES:
            raise ProtocolError("Parameter Manifest totals violate FP32 size")
        if (
            not isinstance(self.parameter_manifest_hash, str)
            or len(self.parameter_manifest_hash) != 64
        ):
            raise ProtocolError("parameter_manifest_hash must be a SHA-256 hex digest")
        try:
            int(self.parameter_manifest_hash, 16)
        except ValueError as exc:
            raise ProtocolError("parameter_manifest_hash must be hexadecimal") from exc
        if self.parameter_manifest_hash != self.compute_hash():
            raise ProtocolError("parameter_manifest_hash does not match canonical manifest content")

    def content_dict(self) -> dict[str, object]:
        """Return the canonical hash input, excluding the self-hash field."""
        return {
            "schema_version": self.schema_version,
            "total_numel": self.total_numel,
            "total_bytes": self.total_bytes,
            "parameters": [item.to_dict() for item in self.parameters],
        }

    def canonical_bytes(self) -> bytes:
        return json.dumps(
            self.content_dict(),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")

    def compute_hash(self) -> str:
        """Hash the centralized manifest bytes with the repository SHA-256 helper."""
        return sha256_bytes(self.canonical_bytes())

    def to_dict(self) -> dict[str, object]:
        return {"parameter_manifest_hash": self.parameter_manifest_hash, **self.content_dict()}

    @classmethod
    def create(
        cls, parameters: tuple[ParameterEntry, ...] | list[ParameterEntry]
    ) -> ParameterManifest:
        items = tuple(parameters)
        content = {
            "schema_version": PARAMETER_MANIFEST_SCHEMA_VERSION,
            "total_numel": sum(item.numel for item in items),
            "total_bytes": sum(item.byte_length for item in items),
            "parameters": [item.to_dict() for item in items],
        }
        raw = json.dumps(
            content,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        return cls(
            parameter_manifest_hash=sha256_bytes(raw),
            schema_version=PARAMETER_MANIFEST_SCHEMA_VERSION,
            total_numel=content["total_numel"],
            total_bytes=content["total_bytes"],
            parameters=items,
        )

    @classmethod
    def from_dict(cls, value: object) -> ParameterManifest:
        if not isinstance(value, dict):
            raise ProtocolError("Parameter Manifest must be an object")
        expected = {
            "parameter_manifest_hash",
            "schema_version",
            "total_numel",
            "total_bytes",
            "parameters",
        }
        if set(value) != expected or not isinstance(value["parameters"], list):
            raise ProtocolError("Parameter Manifest fields do not match the V1 schema")
        return cls(
            parameter_manifest_hash=_string(
                value["parameter_manifest_hash"], "parameter_manifest_hash"
            ),
            schema_version=_integer(value["schema_version"], "schema_version", minimum=1),
            total_numel=_integer(value["total_numel"], "total_numel", minimum=1),
            total_bytes=_integer(value["total_bytes"], "total_bytes", minimum=1),
            parameters=tuple(ParameterEntry.from_dict(item) for item in value["parameters"]),
        )
