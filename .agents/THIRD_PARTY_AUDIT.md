# Fresh third-party candidate audit

Review date: 2026-09-08 (Asia/Saigon). Fresh GitHub API commit/tree resolution and raw file reads; no old report reused. HEAD was consulted once to discover each revision, never as a runtime dependency. All following reads were pinned to full SHA. No installer, upstream script, browser binary or downloaded executable was run. Downloaded text was first inspected in a temporary audit cache outside the repository; only selected reviewed reference files were copied into .agents/vendor.

Scope is the exact candidate and its reference/activation dependencies, not a security certification of whole repositories or their binaries. Git tree mode and SHA-256 for every imported file are retained in VENDOR_MANIFEST.json; original bytes also match upstream Git blob IDs. References with executable behavior are disabled by wrappers, not rewritten to hide upstream behavior.

## impeccable

- Repository: https://github.com/pbakaus/impeccable
- Exact skill path: `.agents/skills/impeccable/SKILL.md`
- Exact upstream URL: https://github.com/pbakaus/impeccable/blob/4db7f6ba4b6ef661bc8a721261b691b40648c08a/.agents/skills/impeccable/SKILL.md
- FULL reviewed commit SHA: `4db7f6ba4b6ef661bc8a721261b691b40648c08a`
- Commit date: `2026-09-07T17:12:34Z`
- License at commit: Apache-2.0. Evidence: LICENSE; NOTICE.md. Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Inspected .agents/skills/impeccable/scripts/impeccable (shell launcher) and impeccable.cmd (Windows launcher). Tree includes executable shell launcher; uses exec, chmod, curl/wget, environment/PATH/cache probes and release binary/sidecar download. Shell launcher mode 100755. Root package.json/README describe npx install/update, Node shim, optional platform engine packages, bun builds and fetch:engine. None vendored or executed.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Broad design routing, own PRODUCT/DESIGN/context, hooks and absolute style bans may override project design/architecture. Launcher fetch is version-tagged but not an audited immutable binary dependency; even checksum sidecars do not make it part of this review.
- Routing, activation, internal overlap and semantic ownership risk: supporting Design/page/layout/interaction polish after pbl4-ui-direction; never canonical owner. Broad design routing, own PRODUCT/DESIGN/context, hooks and absolute style bans may override project design/architecture. Launcher fetch is version-tagged but not an audited immutable binary dependency; even checksum sidecars do not make it part of this review.
- Necessary local modifications: Launcher/context, binary download, npx installer, hooks, detector, pin/doctor/live/critique storage and automatic PRODUCT/DESIGN writes disabled. Only Operate, craft-floor, layout and polish prose enabled; PBL4 visual direction overrides aesthetic absolutes. No delegated agents authorized by raw text.
- Active external tooling: No external binary; existing frontend/browser tools as needed
- Active runtime network: NO; no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

## web-design-guidelines

- Repository: https://github.com/vercel-labs/agent-skills
- Exact skill path: `skills/web-design-guidelines/SKILL.md`
- Exact upstream URL: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines/SKILL.md
- FULL reviewed commit SHA: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Commit date: `2026-08-28T13:36:07Z`
- License at commit: MIT (agent-skills README declaration); MIT (guideline LICENSE). Evidence: UPSTREAM_README.md; separate guideline LICENSE; MIT_TERMS.md (local terms, relative to .agents). Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Candidate is declarative; no scripts/executable files in skill directory. README advertises npx skills installation and npm ci/discovery build commands; preserved only as license evidence and explicitly disabled.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Explicit runtime WebFetch to raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md; mutable content could change instructions between runs. Audit overlaps local UI craft, but accessibility/interaction checks provide distinct value.
- Routing, activation, internal overlap and semantic ownership risk: supporting Post-implementation UI audit; never canonical owner. Explicit runtime WebFetch to raw.githubusercontent.com/vercel-labs/web-interface-guidelines/main/command.md; mutable content could change instructions between runs. Audit overlaps local UI craft, but accessibility/interaction checks provide distinct value.
- Necessary local modifications: WebFetch/fresh/main guideline fetch disabled. Local separately pinned command.md only. Framework-only advice, new packages, blanket modal/URL-state/Title Case prescriptions cannot override project contracts.
- Active external tooling: Source reader; existing browser tooling if rendered checks needed
- Active runtime network: NO; no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

Required remote guideline was separately resolved and read at `vercel-labs/web-interface-guidelines` SHA `e3d624baaf29dc1fc645aff3e38f03e564d2d6b1` (2026-08-18T00:21:06Z), exact path `command.md`, URL https://github.com/vercel-labs/web-interface-guidelines/blob/e3d624baaf29dc1fc645aff3e38f03e564d2d6b1/command.md . LICENSE at the same SHA is MIT, copyright 2025 Vercel Labs; retain its full notice. This local snapshot replaces all fresh-fetch behavior. command.md is declarative and contains no required installer/binary.

## react-best-practices

- Repository: https://github.com/vercel-labs/agent-skills
- Exact skill path: `skills/react-best-practices/SKILL.md`
- Exact upstream URL: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/react-best-practices/SKILL.md
- FULL reviewed commit SHA: `063bee94c3f4df8453406c830b0a7df0f2860278`
- Commit date: `2026-08-28T13:36:07Z`
- License at commit: MIT (README and SKILL frontmatter declaration). Evidence: UPSTREAM_README.md; MIT_TERMS.md (local terms, relative to .agents). Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Candidate rule directory is declarative; no scripts/executables imported. Separate repository packages/react-best-practices-build contains TypeScript/pnpm build tooling; not needed or imported. Root README installer/build commands disabled.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Mixes Next/RSC/server cache and client examples; SWR and better-all recommendations conflict with a minimal existing stack. Compile-time/browser support must be preflighted. Generic performance guidance cannot alter canonical projections or authorization.
- Routing, activation, internal overlap and semantic ownership risk: supporting React+TypeScript+Vite implementation/refactor/performance; never canonical owner. Mixes Next/RSC/server cache and client examples; SWR and better-all recommendations conflict with a minimal existing stack. Compile-time/browser support must be preflighted. Generic performance guidance cannot alter canonical projections or authorization.
- Necessary local modifications: Only 13 explicitly linked browser/React rules enabled. Next/RSC/SSR/server rules and compiled AGENTS.md excluded. SWR, better-all and new experimental features not adopted; retain TanStack Query. Preserve auth/error behavior, effect correctness and browser compatibility.
- Active external tooling: Existing React/TS/Vite toolchain
- Active runtime network: NO; no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

## webapp-testing

- Repository: https://github.com/anthropics/skills
- Exact skill path: `skills/webapp-testing/SKILL.md`
- Exact upstream URL: https://github.com/anthropics/skills/blob/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/skills/webapp-testing/SKILL.md
- FULL reviewed commit SHA: `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f`
- Commit date: `2026-09-03T16:37:13Z`
- License at commit: Apache-2.0. Evidence: LICENSE.txt. Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Inspected scripts/with_server.py (100755): Python subprocess.Popen(shell=True), arbitrary server command strings, piped stdout/stderr, localhost port polling and terminate/kill cleanup; risk of blocked pipes and incomplete descendant cleanup. Not imported. Console example is 100644 Python source; copied as .py.txt reference only, with no executable use. Other examples excluded.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Black-box-first instruction obstructs inspection; networkidle and fixed delay examples are unsuitable for persistent telemetry. Browser tests must not invent a Backend state to pass. Existing app/browser tooling is the only runtime dependency.
- Routing, activation, internal overlap and semantic ownership risk: supporting Local browser acceptance/regression including reconnect/degraded/error UI; never canonical owner. Black-box-first instruction obstructs inspection; networkidle and fixed delay examples are unsuitable for persistent telemetry. Browser tests must not invent a Backend state to pass. Existing app/browser tooling is the only runtime dependency.
- Necessary local modifications: with_server.py shell=True launcher not vendored; black-box execution instruction disabled. Console example renamed .py.txt, not executable. Replace networkidle/fixed waits with ready-state assertions for telemetry. No package/browser installation or semantic workaround.
- Active external tooling: Existing Playwright or project browser runner AND installed browser
- Active runtime network: YES (authorized local app/Backend only; no upstream network); no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

## fastapi

- Repository: https://github.com/fastapi/fastapi
- Exact skill path: `fastapi/.agents/skills/fastapi/SKILL.md`
- Exact upstream URL: https://github.com/fastapi/fastapi/blob/50113da16fec53b66b80d75e80a89296de4fa5a5/fastapi/.agents/skills/fastapi/SKILL.md
- FULL reviewed commit SHA: `50113da16fec53b66b80d75e80a89296de4fa5a5`
- Commit date: `2026-09-01T20:59:53Z`
- License at commit: MIT. Evidence: LICENSE. Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Candidate is Markdown and reference Markdown only, no executable scripts. SKILL lists fastapi dev/run and pyproject entrypoint changes; other-tools suggests uv/Ruff/ty/Asyncer/SQLModel/HTTPX. No package installs or launcher replacements authorized.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Framework defaults could introduce ORM, new streaming transport, endpoints, response shapes/errors, or transaction lifetime changes. New API features may exceed installed version; generic best practice is not canonical authority.
- Routing, activation, internal overlap and semantic ownership risk: supporting Already-resolved Backend API/schema implementation; never canonical owner. Framework defaults could introduce ORM, new streaming transport, endpoints, response shapes/errors, or transaction lifetime changes. New API features may exceed installed version; generic best practice is not canonical authority.
- Necessary local modifications: SQLModel/ORM, Asyncer/ty adoption, FastAPI CLI replacement, new installs and app.frontend/SSE changes disabled. Check installed version before any feature; preserve psycopg, API schema/error and transaction contracts. other-tools and streaming references omitted/disabled.
- Active external tooling: Existing Python/FastAPI/Pydantic and project tests
- Active runtime network: NO; no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

## verification-before-completion

- Repository: https://github.com/obra/superpowers
- Exact skill path: `skills/verification-before-completion/SKILL.md`
- Exact upstream URL: https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/verification-before-completion/SKILL.md
- FULL reviewed commit SHA: `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- Commit date: `2026-08-12T16:53:21Z`
- License at commit: MIT. Evidence: LICENSE. Obligations: retain original attribution/license; Apache notices and change notices as applicable. See registry license handling for the agent-skills MIT declaration without a standalone LICENSE.
- Required reviewed files: exactly the files recorded for this snapshot in VENDOR_MANIFEST.json; omitted command/native/framework references are disabled, not missing dependencies.
- Scripts / executable files / shell / package-manager / installer inventory: Single Markdown entrypoint, no scripts or executable files. Text calls for verification shell commands and red-green reversion; wrapper scopes commands and disables universal reversion.
- Allowed tools: Not declared in candidate frontmatter (no tool permission granted).
- Upstream runtime network / remote resources / floating refs / external binaries: Global positive-message/delegation triggers and per-message reruns impose redundant workflow; evidence discipline is useful only as release-gate support.
- Routing, activation, internal overlap and semantic ownership risk: supporting Evidence check after release-gate before scoped completion claims; never canonical owner. Global positive-message/delegation triggers and per-message reruns impose redundant workflow; evidence discipline is useful only as release-gate support.
- Necessary local modifications: Global triggers, per-message reruns, unrelated full suites, universal revert/red-green cycle and commit/push requirements disabled. Reuse fresh unchanged-state evidence. Never becomes task router or replaces release-gate.
- Active external tooling: Existing relevant project verification commands and git
- Active runtime network: NO; no upstream resource fetch, binary download or package install.
- Verdict: **ACCEPT_WITH_MODIFICATION** (installed).

## requesting-code-review

- Repository: https://github.com/obra/superpowers
- Exact skill path: `skills/requesting-code-review/SKILL.md`
- Exact upstream URL: https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/requesting-code-review/SKILL.md
- FULL reviewed commit SHA: `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- Commit date: `2026-08-12T16:53:21Z`
- License at commit: MIT; reviewed root LICENSE at https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/LICENSE . MIT requires retaining notice; CC-BY-SA obligations described below.
- Files/tooling/commands/network/activation audit: Required files: SKILL.md and code-reviewer.md. No scripts/executable files in candidate. Shell examples: git rev-parse HEAD~1/HEAD, git log with grep/head/awk, origin/main baseline. No package commands, installs, runtime network or binary requirement in candidate. No allowed-tools declaration. Requires subagent dispatch and mandates review for tiny work; would need scope and baseline selection overrides.
- Overlap, semantic risk and necessary modifications: Not selected: mandatory subagent review after every task, broad before-merge routing and an extra review workflow duplicate the internal gates. Its narrowed remaining value does not justify another active skill for this setup. License itself permits reuse.
- Verdict: **REJECT**; not vendored and no active wrapper.

## using-superpowers

- Repository: https://github.com/obra/superpowers
- Exact skill path: `skills/using-superpowers/SKILL.md`
- Exact upstream URL: https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/using-superpowers/SKILL.md
- FULL reviewed commit SHA: `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- Commit date: `2026-08-12T16:53:21Z`
- License at commit: MIT; reviewed root LICENSE at https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/LICENSE . MIT requires retaining notice; CC-BY-SA obligations described below.
- Files/tooling/commands/network/activation audit: Required upstream entrypoint plus harness-specific references. No executable script in candidate. No package install/binary/network requirement in entrypoint; routing invokes additional skills and platform references. No allowed-tools declaration. Activation before every response/action and 1% relevance trigger are the core conflict; removing them removes the candidate purpose.
- Overlap, semantic risk and necessary modifications: Global before-any-response/action invocation and process-skill routing compete with deterministic PBL4 routing. Explicitly prohibited by user; no snapshot or wrapper installed.
- Verdict: **REJECT**; not vendored and no active wrapper.

## differential-review

- Repository: https://github.com/trailofbits/skills
- Exact skill path: `plugins/differential-review/skills/differential-review/SKILL.md`
- Exact upstream URL: https://github.com/trailofbits/skills/blob/d3323cefbcf645678b8dc481de204b02ad3d02dc/plugins/differential-review/skills/differential-review/SKILL.md
- FULL reviewed commit SHA: `d3323cefbcf645678b8dc481de204b02ad3d02dc`
- Commit date: `2026-09-02T17:44:09Z`
- License at commit: CC-BY-SA-4.0; reviewed root LICENSE at https://github.com/trailofbits/skills/blob/d3323cefbcf645678b8dc481de204b02ad3d02dc/LICENSE . MIT requires retaining notice; CC-BY-SA obligations described below.
- Files/tooling/commands/network/activation audit: Required files: SKILL.md, methodology.md, adversarial.md, patterns.md and reporting.md; optional plugin agents/commands. Candidate files are 100644 text, no executable scripts. allowed-tools: Read Write Grep Glob Bash. Commands include git checkout baseline, diff/log/blame, grep and issue-writer. No package installation, mutable fetch or external binary download required in candidate; git, shell tools, optional issue-writer and agent dependencies would need preflight. Local baseline checkout should be replaced with read-only git show/diff if reconsidered. CC-BY-SA requires attribution, license link, indication of modifications and ShareAlike for adapted material.
- Overlap, semantic risk and necessary modifications: Not selected for this small setup: mandatory report/history/blast-radius workflow, baseline checkout advice, uninstalled audit-context-building/issue-writer and adversarial-agent integration add excessive workflow. CC-BY-SA permits reuse with attribution/share-alike obligations; not rejected as license-incompatible. Reassess only for a concrete milestone/security diff need.
- Verdict: **REJECT**; not vendored and no active wrapper.

## Safety interpretation

The installed snapshots include only text: no executable script, binary, installer, root AGENTS.md or discovery metadata. Filename changes preserve bytes. Impeccable upstream layout may mention subagents; it is inactive reference text and the wrapper explicitly removes that authorization. This setup did not spawn any subagents.

Supply-chain matches are recorded per file/line with classification in SUPPLY_CHAIN_SCAN.md. Historical setup and mutable URLs remain visible for provenance but cannot be followed by wrappers. Missing raw relative links are disabled subsets, listed in RAW_REFERENCE_EXCLUSIONS.md; all enabled wrapper/local links must resolve.
