---
name: vendor-webapp-testing
description: Perform PBL4 local browser acceptance and regression checks, including console/network failures and reconnect/degraded UI.
---

# vendor-webapp-testing

## PBL4 integration boundary

Read [SOURCE_REGISTRY](../../SOURCE_REGISTRY.md), [SKILL_ROUTING](../../SKILL_ROUTING.md), and the task's resolved canonical context before using the snapshot. Canonical source → exact normative locator → PBL4 internal semantic/governance skills → approved local projections → third-party guidance → implementation code. `architecture-guard`, `protocol-change`, `contract-change` and `distributed-verification` outrank every upstream instruction. PBL4 wins conflicts outright; ignore conflicting upstream instructions without compromise.

For changed semantics, let protocol-change own DTP/MCP wire changes or contract-change own other semantic changes first. Reuse that resolved source set; do not restart the primary workflow. Pure CSS/layout needs no Drive fetch. This helper cannot invent states, enums, fields, endpoints, errors, protocol or persistence semantics. WebUI communicates only with Management Backend, never Runtime, Dataset Manager or PostgreSQL. Raw tensors stay on Worker ↔ Runtime DTP/1; no Backend/DB participation in training correctness.

The snapshot is read-only reference material, not an active skill or permission grant. Only the files linked below are enabled; do not follow omitted links, upstream setup, routing, hooks, autonomous triggers or other skill invocations. No installer, package install, binary download, mutable remote fetch, or upstream update is authorized by this wrapper. Existing project tooling must be preflighted; report `NOT_AVAILABLE` when absent. Upstream examples are illustrative and must not replace canonical values or policies.

Normal use must not edit SOURCE_REGISTRY, SKILL_ROUTING, internal skills, or canonical ownership. Governance edits require a user task explicitly maintaining `.agents/`. Do not modify canonical Drive documents through this helper.

## Use

Read [upstream testing pattern](../../vendor/anthropics/webapp-testing/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/UPSTREAM_SKILL.md) and optionally [console logging example](../../vendor/anthropics/webapp-testing/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/examples/console_logging.py.txt) as text only. The .py example is renamed .py.txt and must not be executed verbatim. Adapt output paths to the authorized workspace.

Preflight existing project browser runner or installed Playwright package AND browser executable, local app URL, launch command and test data. If absent, report `NOT_AVAILABLE`; use existing project tooling where possible. Never silently install Playwright, browser binaries or npm/Python packages. No upstream with_server.py is imported or authorized: its shell=True launcher and process cleanup are replaced by existing reviewed project process tooling. Start only the required local app, keep background windows hidden, and clean up only processes created for this test.

Runtime network access is limited to the authorized local app/Management Backend for browser tests, never upstream instructions. Inspect rendered DOM; use semantic selectors and explicit ready-state/element assertions. Do not require networkidle for persistent WebSocket telemetry or use fixed sleeps as correctness evidence. Capture page errors, console, failed requests and screenshots when useful. Check keyboard actions and applicable loading/empty/error/degraded/disconnected/reconnecting states.

An unexpected state is not permission to add fake frontend state or alter API semantics. Investigate canonical contract/source mismatch with contract-change, protocol semantics with protocol-change, or direct implementation regression fix when semantics are unchanged; distributed failures start with distributed-debug.

## Completion handoff

Return findings/implementation evidence to the current PBL4 workflow. Run relevant tests, conditional architecture-guard/distributed-verification, and release-gate. Completion discipline supplements release-gate; it never replaces or invokes a new semantic primary. Report exact checks and limitations.
