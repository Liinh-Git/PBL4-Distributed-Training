# PBL4 WebUI — Distributed Training Operations Console

The WebUI is the single-page React frontend for operator monitoring, training orchestration, Strict BSP synchronization visualization, and dataset management in the PBL4 distributed deep learning training system.

---

## Architecture & Communication Boundary

- **Management Backend only:** The WebUI communicates **exclusively** with the PBL4 Management Backend via HTTP/REST and WebSocket APIs.
- **Critical Path Isolation:** The WebUI does **NOT** sit in the training step critical path. It does **NOT** transmit or receive raw gradient tensors, model parameters, or DTP/1 frames.
- Raw tensor exchanges take place exclusively between Worker nodes and the Runtime/Parameter Server over DTP/1 TCP connections.
- If the WebUI is closed or disconnected, active training continues uninterrupted.

---

## Configuration & Environment Variables

Copy `.env.example` to `.env.local` to configure connection endpoints:

```bash
cp .env.example .env.local
```

Available variables:

| Variable | Description | Default |
|---|---|---|
| `VITE_API_BASE_URL` | Base HTTP URL of the Management Backend REST API | `http://localhost:8000` |
| `VITE_WS_BASE_URL` | Base WebSocket URL of the Management Backend | `ws://localhost:8000` |

---

## Development & Build Commands

### Prerequisites

- Node.js 24+
- npm 10+

### Installation

```bash
npm ci
```

### Type Checking

```bash
npm run typecheck
```

### Running Locally (Dev Server)

```bash
npm run dev
```

The development server starts on `http://localhost:3000`.

### Running Tests

```bash
npm run test
```

### Production Build

```bash
npm run build
```

The build script enforces strict TypeScript type checking (`tsc --noEmit`) before executing Vite packaging (`vite build`). Output assets are generated in `dist/`.
