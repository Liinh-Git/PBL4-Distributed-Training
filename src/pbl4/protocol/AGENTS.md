# Protocol Package — AGENTS.md

> Rules specific to `src/pbl4/protocol/`.

## Role

Pure wire-format specification and serialization for DTP/1.

## Invariants

1. **Wire compatibility first** — Any change to this package is a potential wire-breaking change. Follow the canonical DTP/1 specification.

2. **Zero runtime/management_backend/worker/dataset_manager imports** — This package must not import from `pbl4.runtime`, `pbl4.worker`, `pbl4.management_backend`, or `pbl4.dataset_manager`.

3. **Zero PyTorch/framework imports** — This package must not import `torch` or any deep learning framework. Tensor representation is raw bytes/buffers.

4. **Zero database imports** — This package must not import `psycopg`, `asyncpg`, `sqlalchemy`, or any database library.

5. **HeaderCodec does not know Step semantics** — The header codec is a pure framing and wire validation concern. Step numbers and synchronization state belong to Runtime policy.

6. **operation_id is a generic correlation field** — `operation_id` is an 8-byte correlation identifier for matching requests and responses. It does not carry training-specific semantics.

7. **Tests accompany implementation** — When protocol codecs are implemented, exact-wire and malformed-input tests must be added after implementation and before merge, deriving strictly from the canonical DTP/1 specification. No invented wire semantics.

## Version Constants

- `DTP_PROTOCOL_VERSION` — in `constants.py`
- `PARAMETER_MANIFEST_SCHEMA_VERSION` — in `constants.py`

*(Checkpoint schema is owned by Runtime durability, NOT protocol).*
