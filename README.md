# PBL4 — Distributed Deep Learning Training Infrastructure

> **STATUS:** Architecture scaffold / bootstrap.  
> **Core distributed training behavior is NOT implemented yet.**  
> This repository provides an architecture-aligned structural skeleton, interfaces, and boundary checks to guide future implementation.

“Xây dựng hạ tầng huấn luyện mô hình học sâu phân tán với cơ chế đồng bộ tham số giữa các thiết bị.”

---

## Architecture

The system uses a Parameter Server architecture organized around three distinct communication paths:

```
                          ┌───────────────────────────┐
                          │   pbl4-dataset-manager    │
                          │   (Partitioning & Serving)│
                          └─────────────┬─────────────┘
                               ▲        │
            Verify Root Manifest        │ HTTP Shards
                   (read-only) │        │ (before RUNNING)
                               │        ▼
 ┌──────────────┐         ┌────┴─────────┐         ┌──────────────┐
 │ pbl4-worker  │◄───────►│ pbl4-runtime │◄───────►│ pbl4-worker  │
 │   (node-a)   │  DTP/1  │  (Parameter  │  DTP/1  │   (node-b)   │
 └──────────────┘   TCP   │    Server)   │   TCP   └──────────────┘
                          └──────┬───┬───┘
                                 │   │ DTP/1 TCP
                                 │   ▼
                                 │ ┌──────────────┐
                                 │ │ pbl4-worker  │
                                 │ │   (node-c)   │
                                 │ └──────────────┘
                                 │ MCP/1 (TCP)
                                 ▼
                          ┌──────────────┐
                          │ pbl4-backend │◄──── REST / WS ──── WebUI / CLI
                          │ (FastAPI/DB) │
                          └──────┬───────┘
                                 │ psycopg
                                 ▼
                          ┌──────────────┐
                          │  PostgreSQL  │
                          └──────────────┘
```

### The Three Paths

1. **Training Correctness Path (Critical Path):**
   - Direct persistent TCP connections between `pbl4-worker` (node-a, node-b, node-c) ↔ `pbl4-runtime` over **DTP/1**.
   - Raw gradient and parameter tensors flow exclusively through DTP/1.
   - Management Backend, Database, and Dataset Manager are **NOT** in the training step critical path.
   - Invariants: Management Backend down ≠ training down; Database down ≠ training down.

2. **Dataset Provisioning Path:**
   - Before an attempt enters `RUNNING`, Management Backend initiates partitioning on `pbl4-dataset-manager`.
   - `pbl4-runtime` directly reads and verifies the root dataset manifest and content hash from `pbl4-dataset-manager`.
   - Workers download their assigned shards via HTTP before training begins.
   - Once all workers confirm `SHARD_READY`, training commences and Dataset Manager is not contacted during training steps.

3. **Management & Control Path:**
   - `pbl4-runtime` reports semantic events and receives asynchronous commands via **MCP/1** to `pbl4-backend`.
   - `pbl4-backend` (Management Backend) persists state into PostgreSQL via `psycopg` and exposes REST and WebSocket APIs to WebUI and `pblctl`.

---

## Processes & Console Entrypoints

| Process | Console Command | Role |
|---|---|---|
| Runtime | `pbl4-runtime` | Parameter Server, coordinator, DTP/1 server, update engine |
| Worker | `pbl4-worker` | Forward/backward pass, gradient export, parameter application |
| Dataset Manager | `pbl4-dataset-manager` | Dataset ingestion, sharding, and artifact HTTP serving |
| Management Backend | `pbl4-backend` | REST API, WebSocket gateway, PostgreSQL persistence |
| CLI | `pblctl` | Command-line management tool (talks to Management Backend) |
| WebUI | (in `web/`) | React monitoring dashboard (talks to Management Backend only) |

*(Note: Attempting to start unimplemented services will display pending status and exit non-zero. Use `--help` for available options).*

---

## Development Setup

### Prerequisites

- Python 3.12
- Node.js 24
- PostgreSQL (for Management Backend persistence)
- [uv](https://docs.astral.sh/uv/) (fast Python package manager)

### Quick Start

```bash
# 1. Install development dependencies
uv sync

# 2. Verify repository scaffold and architectural constraints
uv run python scripts/verify_scaffold.py

# 3. Local cluster topology planner
uv run python scripts/run_local_cluster.py

# 4. Install and build WebUI
cd web
npm ci
npm run typecheck
npm run build
cd ..
```

---

## Canonical Documentation Reference

The canonical architecture and protocol specifications are maintained in the team's shared Google Drive.
This repository's `docs/IMPLEMENTATION_CONTRACT.md` is an implementation projection.

- [`AGENTS.md`](AGENTS.md) — Normative rules and boundaries for developers and AI agents.
- [`docs/IMPLEMENTATION_CONTRACT.md`](docs/IMPLEMENTATION_CONTRACT.md) — Module-to-document mapping and constraints.
- [`docs/OPEN_ISSUES.md`](docs/OPEN_ISSUES.md) — Unresolved design questions.
- [`CONTRIBUTING.md`](CONTRIBUTING.md) — Development workflow and review rules.
