# Third-party skills registry

## Part A — Policy

Only exact full 40-character reviewed commit SHAs may be imported; no floating refs or automatic updates. No unreviewed installer, runtime mutable fetch, bootstrapper, package installation or binary download. Installation here means reviewed vendoring plus a controlled wrapper, never upstream setup execution.

Authority: canonical source resolved through SOURCE_REGISTRY → exact normative locator → PBL4 internal semantic/governance skills → approved local projections → third-party helpers → current code. SOURCE_REGISTRY, SKILL_ROUTING, architecture-guard, protocol-change, contract-change and distributed-verification always outrank third-party instructions. Ignore conflicts outright.

Raw snapshots under vendor are reference-only and never active. SKILL.md is renamed UPSTREAM_SKILL.md; no raw AGENTS.md, auto-discovery metadata, hooks or executable scripts are imported. Active wrappers under skills are the integration boundary. Only wrapper-linked reference subsets are enabled; omitted raw links are explicitly disabled, not runtime downloads. Preserve original bytes and notices; adaptations live in wrappers. Normal helper use cannot edit governance or canonical ownership.

For maintenance, obtain each file from its exact immutable URL in [VENDOR_MANIFEST.json](VENDOR_MANIFEST.json), verify Git blob SHA plus SHA-256, retain the upstream mode as provenance (do not activate executable mode), and rerun [verification](scripts/verify_skills.py). A new revision requires a fresh audit. Original instructions may mention mutable URLs or shell commands only as inactive historical text.

License handling: Apache snapshots retain the original license and relevant notices; byte contents are unchanged and filename changes are recorded. MIT snapshots retain attribution and permission notices. agent-skills ships an MIT declaration in README, not a standalone LICENSE at the reviewed SHA: preserve that README and skill author metadata, with [locally supplied standard MIT terms](MIT_TERMS.md), without claiming it is an upstream LICENSE. The separate guideline repository supplies its own MIT LICENSE. No third-party notices for unimported fonts/native assets are needed.

## Part B — Installed / vendored skills

### impeccable

- Upstream repo: https://github.com/pbakaus/impeccable
- Exact skill path: `.agents/skills/impeccable/SKILL.md`
- Exact upstream: https://github.com/pbakaus/impeccable/blob/4db7f6ba4b6ef661bc8a721261b691b40648c08a/.agents/skills/impeccable/SKILL.md
- Reviewed commit: `4db7f6ba4b6ef661bc8a721261b691b40648c08a`
- Commit date: `2026-09-07T17:12:34Z`
- License: Apache-2.0
- License file(s): LICENSE; NOTICE.md, relative to snapshot unless stated otherwise.
- Vendored location: `vendor/pbakaus/impeccable/4db7f6ba4b6ef661bc8a721261b691b40648c08a/`
- Active wrapper: [vendor-impeccable](skills/vendor-impeccable/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `reference/operate.md`, `reference/craft-floor.md`, `reference/layout.md`, `reference/polish.md`, `LICENSE`, `NOTICE.md`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: No external binary; existing frontend/browser tools as needed. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: NO
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: Launcher/context, binary download, npx installer, hooks, detector, pin/doctor/live/critique storage and automatic PRODUCT/DESIGN writes disabled. Only Operate, craft-floor, layout and polish prose enabled; PBL4 visual direction overrides aesthetic absolutes. No delegated agents authorized by raw text. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: Design/page/layout/interaction polish after pbl4-ui-direction
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

### web-design-guidelines

- Upstream repo: https://github.com/vercel-labs/agent-skills
- Exact skill path: `skills/web-design-guidelines/SKILL.md`
- Exact upstream: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines/SKILL.md
- Reviewed commit: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Commit date: `2026-08-28T13:36:07Z`
- License: MIT (agent-skills README declaration); MIT (guideline LICENSE)
- License file(s): UPSTREAM_README.md; separate guideline LICENSE; MIT_TERMS.md (local terms, relative to .agents), relative to snapshot unless stated otherwise.
- Vendored location: `vendor/vercel-labs/web-design-guidelines/063bee94c3f4df8453406c830b0a7df0f2860278/`
- Active wrapper: [vendor-web-design-guidelines](skills/vendor-web-design-guidelines/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `UPSTREAM_README.md`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: Source reader; existing browser tooling if rendered checks needed. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: NO
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: WebFetch/fresh/main guideline fetch disabled. Local separately pinned command.md only. Framework-only advice, new packages, blanket modal/URL-state/Title Case prescriptions cannot override project contracts. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: Post-implementation UI audit
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

Guideline dependency: `vercel-labs/web-interface-guidelines`, exact path `command.md`, reviewed SHA `e3d624baaf29dc1fc645aff3e38f03e564d2d6b1`, commit date `2026-08-18T00:21:06Z`; snapshot `vendor/vercel-labs/web-interface-guidelines/e3d624baaf29dc1fc645aff3e38f03e564d2d6b1/` contains command.md and original MIT LICENSE. It has no separate active wrapper.

### react-best-practices

- Upstream repo: https://github.com/vercel-labs/agent-skills
- Exact skill path: `skills/react-best-practices/SKILL.md`
- Exact upstream: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/react-best-practices/SKILL.md
- Reviewed commit: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Commit date: `2026-08-28T13:36:07Z`
- License: MIT (README and SKILL frontmatter declaration)
- License file(s): UPSTREAM_README.md; MIT_TERMS.md (local terms, relative to .agents), relative to snapshot unless stated otherwise.
- Vendored location: `vendor/vercel-labs/react-best-practices/063bee94c3f4df8453406c830b0a7df0f2860278/`
- Active wrapper: [vendor-react-best-practices](skills/vendor-react-best-practices/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `rules/async-parallel.md`, `rules/async-defer-await.md`, `rules/async-cheap-condition-before-await.md`, `rules/client-event-listeners.md`, `rules/client-passive-event-listeners.md`, `rules/rerender-derived-state-no-effect.md`, `rules/rerender-functional-setstate.md`, `rules/rerender-dependencies.md`, `rules/rerender-lazy-state-init.md`, `rules/rerender-no-inline-components.md`, `rules/rendering-conditional-render.md`, `rules/js-tosorted-immutable.md`, `rules/js-set-map-lookups.md`, `UPSTREAM_README.md`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: Existing React/TS/Vite toolchain. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: NO
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: Only 13 explicitly linked browser/React rules enabled. Next/RSC/SSR/server rules and compiled AGENTS.md excluded. SWR, better-all and new experimental features not adopted; retain TanStack Query. Preserve auth/error behavior, effect correctness and browser compatibility. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: React+TypeScript+Vite implementation/refactor/performance
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

### webapp-testing

- Upstream repo: https://github.com/anthropics/skills
- Exact skill path: `skills/webapp-testing/SKILL.md`
- Exact upstream: https://github.com/anthropics/skills/blob/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/skills/webapp-testing/SKILL.md
- Reviewed commit: `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f`
- Commit date: `2026-09-03T16:37:13Z`
- License: Apache-2.0
- License file(s): LICENSE.txt, relative to snapshot unless stated otherwise.
- Vendored location: `vendor/anthropics/webapp-testing/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/`
- Active wrapper: [vendor-webapp-testing](skills/vendor-webapp-testing/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `examples/console_logging.py.txt`, `LICENSE.txt`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: Existing Playwright or project browser runner AND installed browser. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: YES (authorized local app/Backend only; no upstream network)
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: with_server.py shell=True launcher not vendored; black-box execution instruction disabled. Console example renamed .py.txt, not executable. Replace networkidle/fixed waits with ready-state assertions for telemetry. No package/browser installation or semantic workaround. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: Local browser acceptance/regression including reconnect/degraded/error UI
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

### fastapi

- Upstream repo: https://github.com/fastapi/fastapi
- Exact skill path: `fastapi/.agents/skills/fastapi/SKILL.md`
- Exact upstream: https://github.com/fastapi/fastapi/blob/50113da16fec53b66b80d75e80a89296de4fa5a5/fastapi/.agents/skills/fastapi/SKILL.md
- Reviewed commit: `50113da16fec53b66b80d75e80a89296de4fa5a5`
- Commit date: `2026-09-01T20:59:53Z`
- License: MIT
- License file(s): LICENSE, relative to snapshot unless stated otherwise.
- Vendored location: `vendor/fastapi/fastapi/50113da16fec53b66b80d75e80a89296de4fa5a5/`
- Active wrapper: [vendor-fastapi](skills/vendor-fastapi/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `references/dependencies.md`, `references/responses.md`, `references/pydantic.md`, `references/path-operations.md`, `LICENSE`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: Existing Python/FastAPI/Pydantic and project tests. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: NO
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: SQLModel/ORM, Asyncer/ty adoption, FastAPI CLI replacement, new installs and app.frontend/SSE changes disabled. Check installed version before any feature; preserve psycopg, API schema/error and transaction contracts. other-tools and streaming references omitted/disabled. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: Already-resolved Backend API/schema implementation
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

### verification-before-completion

- Upstream repo: https://github.com/obra/superpowers
- Exact skill path: `skills/verification-before-completion/SKILL.md`
- Exact upstream: https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/verification-before-completion/SKILL.md
- Reviewed commit: `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- Commit date: `2026-08-12T16:53:21Z`
- License: MIT
- License file(s): LICENSE, relative to snapshot unless stated otherwise.
- Vendored location: `vendor/obra/verification-before-completion/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/`
- Active wrapper: [vendor-verification-before-completion](skills/vendor-verification-before-completion/SKILL.md)
- Imported files: `UPSTREAM_SKILL.md`, `LICENSE`. Exact paths, immutable URLs, Git modes/blob IDs and SHA-256 are in VENDOR_MANIFEST.json.
- Required external tooling: Existing relevant project verification commands and git. Preflight; missing means NOT_AVAILABLE, never silent installation.
- Runtime network access: NO
- Mutable upstream fetch disabled: YES
- Local modifications/disabled behavior: Global triggers, per-message reruns, unrelated full suites, universal revert/red-green cycle and commit/push requirements disabled. Reuse fresh unchanged-state evidence. Never becomes task router or replaces release-gate. Snapshot bytes unchanged; upstream SKILL.md renamed UPSTREAM_SKILL.md, README renamed UPSTREAM_README.md where present.
- Activation scope: Evidence check after release-gate before scoped completion claims
- PBL4 owners that outrank this skill: SOURCE_REGISTRY and exact canonical owners/locators; SKILL_ROUTING; internal architecture/protocol/contract/distributed-verification skills; approved local projections. UI helpers also defer to pbl4-ui-direction on aesthetics.
- Import mode: VENDORED_PINNED_WRAPPED
- Review date: 2026-09-08
- Status: ACTIVE

## Rejected / not installed

- **requesting-code-review**: Not selected: mandatory subagent review after every task, broad before-merge routing and an extra review workflow duplicate the internal gates. Its narrowed remaining value does not justify another active skill for this setup. License itself permits reuse.
- **using-superpowers**: Global before-any-response/action invocation and process-skill routing compete with deterministic PBL4 routing. Explicitly prohibited by user; no snapshot or wrapper installed.
- **differential-review**: Not selected for this small setup: mandatory report/history/blast-radius workflow, baseline checkout advice, uninstalled audit-context-building/issue-writer and adversarial-agent integration add excessive workflow. CC-BY-SA permits reuse with attribution/share-alike obligations; not rejected as license-incompatible. Reassess only for a concrete milestone/security diff need.

Generic frontend-design, using-superpowers, whole packs, ui-ux-pro-max and global meta-routers were not installed.
