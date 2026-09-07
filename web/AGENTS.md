# WebUI — AGENTS.md

> Rules specific to `web/`.

## Role

React + TypeScript + Vite single-page application for monitoring and managing distributed training.

## Invariants

1. **WebUI talks to Management Backend only** — All API calls go through the Management Backend REST API or WebSocket. WebUI must NOT:
   - Call Runtime directly
   - Call Dataset Manager directly
   - Query PostgreSQL directly

2. **No domain state inference** — WebUI displays state received from the Management Backend. It does not independently compute or infer domain state (e.g., training progress, dataset readiness).

3. **Types from Management Backend contract** — Frontend types should align with the Management Backend's OpenAPI schema. Do not invent types that diverge from the API contract.

## Tech Stack

- React 18+
- TypeScript (strict mode)
- Vite (build tool)
