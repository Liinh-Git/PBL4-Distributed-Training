# Management Backend Package — AGENTS.md

> Rules specific to `src/pbl4/management_backend/`.

## Role

The Management Backend is the **management/application layer**. It provides REST API, WebSocket, database persistence, and MCP/1 gateway functionality.

## Invariants

1. **No runtime implementation imports** — Management Backend must not import `ParameterServer`, `CanonicalModel`, `UpdateEngine`, `GradientStore`, `Aggregator`, or any runtime training implementation. It communicates with Runtime only through `RuntimeGateway` (MCP/1).

2. **No gradient/tensor path** — Management Backend must never handle raw gradient or parameter tensors. That traffic flows exclusively through DTP/1.

3. **PostgreSQL access through psycopg / explicit repository SQL** — The persistence architecture uses `psycopg` with explicit SQL queries. Introducing SQLAlchemy ORM, asyncpg, or ORM models is strictly prohibited without an approved architecture change.

4. **Dataset Build registration gate** — Management Backend verifies and persists dataset catalog records during registration and issues registration acknowledgement. A Dataset Build requires this acknowledgement for READY; Management Backend does not independently infer READY.

5. **DB is not a synchronization primitive** — PostgreSQL stores application state. It is not used for worker synchronization, barrier coordination, or training step tracking.

6. **Management Backend down ≠ training down** — The Management Backend can crash or restart without affecting an active training session. Training runs independently once started.

## Structure

```
api/          — FastAPI route handlers
schemas/      — Pydantic request/response models
services/     — Business logic (JobService, AttemptService, etc.)
repositories/ — PostgreSQL access through psycopg / explicit repository SQL
gateways/     — Outbound protocol adapters (RuntimeGateway / MCP/1)
clients/      — HTTP clients (DatasetManagerClient)
```
