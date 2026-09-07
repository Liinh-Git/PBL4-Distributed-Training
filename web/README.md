# PBL4 WebUI — Management Interface

> Frontend management interface for the PBL4 distributed training infrastructure.
> Connects exclusively to the Management Backend via REST and WebSocket.

## Architecture

- **Role**: Operator dashboard for inspecting cluster topology, training attempts, metrics, and dataset catalog.
- **Backend Boundary**: Communicates strictly with `pbl4-backend` over HTTP/REST and WebSocket. Does NOT communicate directly with Runtime or Workers.
- **Technology**: React SPA built with Vite and TypeScript.

## Development

```bash
# Install dependencies
npm ci

# Typecheck
npm run typecheck

# Production build
npm run build
```

## Structure

```
src/
├── api/          — REST client and API bindings to Management Backend
├── app/          — Application shell, providers, and layout
├── components/   — Shared UI components
├── domain/       — TypeScript domain models and contract types
├── features/     — Feature modules (jobs, attempts, cluster)
├── live/         — WebSocket connection and telemetry state
├── pages/        — Route views
└── strategies/   — Strategy-specific UI projections (e.g. strict_bsp)
```
