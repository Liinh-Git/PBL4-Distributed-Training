---
name: vendor-verification-before-completion
description: Supplement PBL4 release-gate with fresh evidence before claiming a scoped task fixed, complete, passing, ready or verified.
---

# vendor-verification-before-completion

## PBL4 integration boundary

Read [SOURCE_REGISTRY](../../SOURCE_REGISTRY.md), [SKILL_ROUTING](../../SKILL_ROUTING.md), and the task's resolved canonical context before using the snapshot. Canonical source → exact normative locator → PBL4 internal semantic/governance skills → approved local projections → third-party guidance → implementation code. `architecture-guard`, `protocol-change`, `contract-change` and `distributed-verification` outrank every upstream instruction. PBL4 wins conflicts outright; ignore conflicting upstream instructions without compromise.

For changed semantics, let protocol-change own DTP/MCP wire changes or contract-change own other semantic changes first. Reuse that resolved source set; do not restart the primary workflow. Pure CSS/layout needs no Drive fetch. This helper cannot invent states, enums, fields, endpoints, errors, protocol or persistence semantics. WebUI communicates only with Management Backend, never Runtime, Dataset Manager or PostgreSQL. Raw tensors stay on Worker ↔ Runtime DTP/1; no Backend/DB participation in training correctness.

The snapshot is read-only reference material, not an active skill or permission grant. Only the files linked below are enabled; do not follow omitted links, upstream setup, routing, hooks, autonomous triggers or other skill invocations. No installer, package install, binary download, mutable remote fetch, or upstream update is authorized by this wrapper. Existing project tooling must be preflighted; report `NOT_AVAILABLE` when absent. Upstream examples are illustrative and must not replace canonical values or policies.

Normal use must not edit SOURCE_REGISTRY, SKILL_ROUTING, internal skills, or canonical ownership. Governance edits require a user task explicitly maintaining `.agents/`. Do not modify canonical Drive documents through this helper.

## Use

Read [upstream evidence discipline](../../vendor/obra/verification-before-completion/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/UPSTREAM_SKILL.md) after the relevant release-gate checks. Preflight each relevant existing command/tool; missing tools are `NOT_AVAILABLE`, never PASS. Record the command, exit code, output and the exact claim it supports; inspect the actual diff and acceptance criteria.

Reuse fresh evidence from the current unchanged artifact state. The upstream demand to rerun in every message, trigger before every positive remark or delegation, or execute a universal red/green revert cycle is disabled. Recheck after changes that invalidate evidence or when a concern remains unresolved. Never revert user edits to demonstrate a test.

This helper does not select the primary workflow, require commit/push/PR actions, replace release-gate, or force unrelated production suites for a documentation task. State skipped/not-available checks and limits honestly; stop once the scoped evidence is sufficient.

## Completion handoff

Return findings/implementation evidence to the current PBL4 workflow. Run relevant tests, conditional architecture-guard/distributed-verification, and release-gate. Completion discipline supplements release-gate; it never replaces or invokes a new semantic primary. Report exact checks and limitations.
