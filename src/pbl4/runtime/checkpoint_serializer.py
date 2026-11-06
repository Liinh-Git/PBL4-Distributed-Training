"""Strategy-aware serializer; V1 bytes and validation remain untouched."""

import json
from dataclasses import replace

from pbl4.common.hashing import canonical_json_bytes
from pbl4.runtime.checkpoint import CheckpointSerializer
from pbl4.runtime.checkpoint_v1 import CheckpointV1Serializer


class TrainingCheckpointSerializer(CheckpointSerializer):
    def __init__(self):
        self._v1 = CheckpointV1Serializer()

    def serialize(self, snapshot):
        if snapshot.training_strategy == "strict_bsp":
            if snapshot.async_progress is not None:
                raise ValueError("Sync checkpoint cannot contain async progress")
            return self._v1.serialize(snapshot)
        if snapshot.training_strategy != "async_sgd" or snapshot.checkpoint_schema_version != 2:
            raise ValueError("Unsupported checkpoint strategy/schema")
        if not isinstance(snapshot.async_progress, bytes):
            raise ValueError("Missing async checkpoint progress")
        progress = json.loads(snapshot.async_progress)
        if canonical_json_bytes(progress) != snapshot.async_progress or not isinstance(
            progress, dict
        ):
            raise ValueError("Invalid async checkpoint progress")
        payload, raw = self._v1.serialize(
            replace(
                snapshot,
                training_strategy="strict_bsp",
                checkpoint_schema_version=1,
                async_progress=None,
            )
        )
        metadata = json.loads(raw)
        metadata.update(
            training_strategy="async_sgd", checkpoint_schema_version=2, async_progress=progress
        )
        return payload, canonical_json_bytes(metadata)

    def deserialize(self, payload, metadata):
        value = json.loads(metadata)
        if not isinstance(value, dict) or canonical_json_bytes(value) != metadata:
            raise ValueError("Checkpoint metadata must be canonical JSON")
        if value.get("training_strategy") == "strict_bsp":
            return self._v1.deserialize(payload, metadata)
        if (
            value.get("training_strategy") != "async_sgd"
            or value.get("checkpoint_schema_version") != 2
        ):
            raise ValueError("Unsupported checkpoint strategy/schema")
        progress = value.pop("async_progress", None)
        if not isinstance(progress, dict):
            raise ValueError("Missing async checkpoint progress")
        value.update(training_strategy="strict_bsp", checkpoint_schema_version=1)
        restored = self._v1.deserialize(payload, canonical_json_bytes(value))
        return replace(
            restored,
            training_strategy="async_sgd",
            checkpoint_schema_version=2,
            async_progress=canonical_json_bytes(progress),
        )
