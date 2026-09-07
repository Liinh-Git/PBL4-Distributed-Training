---
name: pbl4-ui-direction
description: Define PBL4 WebUI visual implementation direction for new pages, dashboard redesign, components and interaction polish without owning domain semantics.
---

# PBL4 UI direction

Local PBL4-owned visual direction. Read [routing](../../SKILL_ROUTING.md) and reuse the resolved canonical context. Canonical [WEBUI], [BACKEND_API], [DOMAIN_MODEL] and their exact [source locators](../../SOURCE_REGISTRY.md) outrank this skill. For changed state/API meaning, contract-change runs first; pure CSS/layout needs no Drive resolution.

Build a modern developer-infrastructure / observability console: operational tasks first, high information density, low visual noise. Modal-style technical tooling is inspiration only; do not copy branding, assets or layouts pixel-for-pixel. Preserve the current app's coherent visual system, including dark-first behavior if consistent with it.

Use restrained neutral surfaces, thin borders, clear typography hierarchy, compact purposeful charts and tabular numerals for metrics. Reserve monospace for IDs, hashes, protocol values, logs and technical metadata. Make logs, events and timelines first-class; keep Worker/Attempt/Step state visible using canonical labels and meaning. Distinguish absent/stale data from zero or success. Connection presentation must not invent a domain state or imply training failed merely because management telemetry disconnected.

Support useful loading, empty, error, degraded, disconnected and reconnecting presentation from existing contracts. Maintain visible keyboard focus, navigable tables and useful shortcuts; add a command palette only for a concrete navigation need. Optimize for a desktop console with responsive narrow-screen access, readable long IDs and usable overflow.

Avoid generic SaaS metric-card templates, decorative purple gradients, glass effects, excessive floating/rounded cards, card nesting, arbitrary bento layouts, giant marketing components, decorative charts and gratuitous animation. Motion explains feedback and respects reduced-motion preferences. No fake infrastructure state or invented status.

Keep React + TypeScript + Vite and established frontend structure. WebUI talks exclusively to Management Backend over REST/WebSocket; never directly to Runtime, Dataset Manager or PostgreSQL. Do not introduce an endpoint or rename canonical states for aesthetics. Normal visual work cannot edit governance or canonical ownership.

Preflight target components, tokens, package scripts and browser tools before execution. Continue with [vendor-impeccable](../vendor-impeccable/SKILL.md) for craft → implementation / [React guidance](../vendor-react-best-practices/SKILL.md) → [UI audit](../vendor-web-design-guidelines/SKILL.md) → [browser acceptance](../vendor-webapp-testing/SKILL.md) → release-gate → vendor-verification-before-completion. Missing tooling is NOT_AVAILABLE; do not silently install it.
