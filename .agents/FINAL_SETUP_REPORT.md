# Final PBL4 agent-skills setup report

Date: 2026-09-08. Scope: .agents only. Seven existing internal skills retained; one local UI direction and six pinned third-party wrappers added. No canonical Drive write, installer execution, production edit or package installation.

## A. Internal corrections

DATA_MODEL now owns persisted table/field shape, identity relationships, nullability, FK/unique/data-shape constraints and artifact/manifest schemas. POSTGRESQL owns repositories, Unit of Work, transactions, locking/concurrency, numbered migration mechanics, connections, outage/reconciliation and operational durability. Canonical source URLs and exact locator names are preserved.

Removed mandatory migration-framework and universal downgrade assumptions. Migration gates cover previous supported schema, history/compatibility, additive/backfill/constraint/destructive behavior, backup testing and unsupported-version rejection. operation_id has strategy-specific 1:1 mapping in StrictBSP V1, without a generic equality assumption. Checkpoint optimizer dynamic state is conditional; stateless SGD has none. Approved model restore remains a controlled writer. Added distributed-debug Route C, exact-locator routing and contract-appropriate deterministic output wording. Manifest schema routing now consistently resolves to DATA_MODEL.

## B. Final tree

```text
.agents/
  SOURCE_REGISTRY.md
  SKILL_ROUTING.md
  SKILL_SCENARIOS.md
  THIRD_PARTY_SKILLS.md
  THIRD_PARTY_AUDIT.md
  VENDOR_MANIFEST.json
  MIT_TERMS.md
  SUPPLY_CHAIN_SCAN.md
  RAW_REFERENCE_EXCLUSIONS.md
  VERIFICATION_COMMANDS.json
  FINAL_SETUP_REPORT.md
  scripts/verify_skills.py
  skills/
    architecture-guard/SKILL.md
    contract-change/SKILL.md
    protocol-change/SKILL.md
    distributed-debug/SKILL.md
    distributed-verification/SKILL.md
    doc-sync/SKILL.md
    release-gate/SKILL.md
    pbl4-ui-direction/SKILL.md
    vendor-impeccable/SKILL.md
    vendor-web-design-guidelines/SKILL.md
    vendor-react-best-practices/SKILL.md
    vendor-webapp-testing/SKILL.md
    vendor-fastapi/SKILL.md
    vendor-verification-before-completion/SKILL.md
  vendor/
    pbakaus/impeccable/<reviewed SHA>/
    vercel-labs/web-design-guidelines/<reviewed SHA>/
    vercel-labs/web-interface-guidelines/<reviewed SHA>/
    vercel-labs/react-best-practices/<reviewed SHA>/
    anthropics/webapp-testing/<reviewed SHA>/
    fastapi/fastapi/<reviewed SHA>/
    obra/verification-before-completion/<reviewed SHA>/
```

The full SHA/path/file inventory is below and in [VENDOR_MANIFEST.json](VENDOR_MANIFEST.json). Snapshots contain 37 original-byte text files, including original licenses/notices and selected references; no executable helper is imported.

## C–D. Active internal and local skills

Internal: architecture-guard, contract-change, protocol-change, distributed-debug, distributed-verification, doc-sync, release-gate.

Local project: pbl4-ui-direction, owning visual implementation direction only. Total intended active discovery entrypoints: 14.

## E. Installed external skills

All six have verdict ACCEPT_WITH_MODIFICATION and import mode VENDORED_PINNED_WRAPPED. Per-file hashes, upstream paths, immutable download URLs and modes are in the manifest; full activation/disabled behavior/license obligations are in [the registry](THIRD_PARTY_SKILLS.md) and [fresh audit](THIRD_PARTY_AUDIT.md).

### impeccable

- Upstream: https://github.com/pbakaus/impeccable/blob/4db7f6ba4b6ef661bc8a721261b691b40648c08a/.agents/skills/impeccable/SKILL.md
- Exact skill path: `.agents/skills/impeccable/SKILL.md`
- Full SHA: `4db7f6ba4b6ef661bc8a721261b691b40648c08a`
- License: Apache-2.0
- Wrapper: [vendor-impeccable](skills/vendor-impeccable/SKILL.md)
- Vendor snapshot: `vendor/pbakaus/impeccable/4db7f6ba4b6ef661bc8a721261b691b40648c08a/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

### web-design-guidelines

- Upstream: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/web-design-guidelines/SKILL.md
- Exact skill path: `skills/web-design-guidelines/SKILL.md`
- Full SHA: `063bee94c3f4df8453406c830b0a7df0f2860278`
- License: MIT (upstream README declaration; local standard terms); guideline dependency MIT LICENSE
- Wrapper: [vendor-web-design-guidelines](skills/vendor-web-design-guidelines/SKILL.md)
- Vendor snapshot: `vendor/vercel-labs/web-design-guidelines/063bee94c3f4df8453406c830b0a7df0f2860278/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

### react-best-practices

- Upstream: https://github.com/vercel-labs/agent-skills/blob/063bee94c3f4df8453406c830b0a7df0f2860278/skills/react-best-practices/SKILL.md
- Exact skill path: `skills/react-best-practices/SKILL.md`
- Full SHA: `063bee94c3f4df8453406c830b0a7df0f2860278`
- License: MIT (README/frontmatter declaration; local standard terms)
- Wrapper: [vendor-react-best-practices](skills/vendor-react-best-practices/SKILL.md)
- Vendor snapshot: `vendor/vercel-labs/react-best-practices/063bee94c3f4df8453406c830b0a7df0f2860278/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

### webapp-testing

- Upstream: https://github.com/anthropics/skills/blob/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/skills/webapp-testing/SKILL.md
- Exact skill path: `skills/webapp-testing/SKILL.md`
- Full SHA: `41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f`
- License: Apache-2.0
- Wrapper: [vendor-webapp-testing](skills/vendor-webapp-testing/SKILL.md)
- Vendor snapshot: `vendor/anthropics/webapp-testing/41bbe19d1a1a7eaab5e7bb9050a417e5c6cffc8f/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

### fastapi

- Upstream: https://github.com/fastapi/fastapi/blob/50113da16fec53b66b80d75e80a89296de4fa5a5/fastapi/.agents/skills/fastapi/SKILL.md
- Exact skill path: `fastapi/.agents/skills/fastapi/SKILL.md`
- Full SHA: `50113da16fec53b66b80d75e80a89296de4fa5a5`
- License: MIT
- Wrapper: [vendor-fastapi](skills/vendor-fastapi/SKILL.md)
- Vendor snapshot: `vendor/fastapi/fastapi/50113da16fec53b66b80d75e80a89296de4fa5a5/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

### verification-before-completion

- Upstream: https://github.com/obra/superpowers/blob/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/skills/verification-before-completion/SKILL.md
- Exact skill path: `skills/verification-before-completion/SKILL.md`
- Full SHA: `b36e0829c6d0140e93cfef2ca599b1b07d4a7797`
- License: MIT
- Wrapper: [vendor-verification-before-completion](skills/vendor-verification-before-completion/SKILL.md)
- Vendor snapshot: `vendor/obra/verification-before-completion/b36e0829c6d0140e93cfef2ca599b1b07d4a7797/`
- Network/install behavior: no upstream runtime fetch, binary download or package installation. Browser testing alone may contact the authorized local app/Backend. Snapshot setup/meta-routing/omitted references are disabled by the wrapper.

Guideline dependency: `vercel-labs/web-interface-guidelines`, `command.md`, SHA `e3d624baaf29dc1fc645aff3e38f03e564d2d6b1`, MIT; local snapshot `vendor/vercel-labs/web-interface-guidelines/e3d624baaf29dc1fc645aff3e38f03e564d2d6b1/`. No runtime guideline fetch.

## F. Rejected candidates

- using-superpowers: rejected global before-any-action/response routing; not vendored.
- requesting-code-review: not selected because mandatory subagent/after-every-task review duplicates the internal gates; MIT itself permits reuse.
- differential-review: not selected because baseline checkout, extra report/history workflow and uninstalled skill/agent integrations outweigh current value. License is CC-BY-SA-4.0, not MIT; attribution/share-alike would apply if reused. No license-incompatibility claim.

No whole pack, generic frontend-design or ui-ux-pro-max installed.

## G. Final routing graph

```text
Semantic delta
  → SOURCE_REGISTRY → exact normative locator
  → protocol-change (DTP/MCP wire) OR contract-change (other semantics)
  → relevant architecture-guard → scoped implementation helper
  → relevant tests/distributed-verification → doc-sync as needed
  → release-gate → vendor-verification-before-completion

Unchanged Backend semantics
  → architecture context → vendor-fastapi → tests → release gate → evidence

Visual-only UI
  → pbl4-ui-direction → vendor-impeccable
  → React implementation + vendor-react-best-practices
  → vendor-web-design-guidelines → vendor-webapp-testing
  → release-gate → evidence

Distributed bug
  → distributed-debug → A protocol / B contract / C direct implementation fix
  → regression + relevant architecture/correctness checks → release → evidence
```

Optional differential review is not an installed dependency. No helper restarts source resolution or becomes a second primary.

## H. Architecture and routing safety audit

Manual instruction-level evaluation, not a claim that a language model was behaviorally sandboxed:

| Scenarios | Outcome | Evidence / decision |
|---|---|---|
| A | PASS | DTP field change selects protocol-change; no second primary. |
| B | PASS | New persisted column selects DATA_MODEL; transaction/migration operations use POSTGRESQL. |
| C, H | PASS | Visual-only work follows local/UI helper chain without contract-change or Drive resolution. |
| D | PASS | Already-resolved semantics proceed during Drive outage. |
| E | PASS | Unresolved checkpoint field blocks on canonical-source unavailability. |
| F | PASS | Pure deadlock/locking defect takes direct implementation Route C with regression/verification. |
| G | PASS | Draft Nháp content cannot become production semantics. |
| I | PASS | UI cannot invent Worker state; domain/API source resolution required. |
| J | PASS | FastAPI preference cannot change response schema. |
| K | PASS | Direct browser-to-Runtime recommendation rejected. |
| L | PASS | Mutable guideline fetch rejected; local pinned command.md used. |
| M | PASS | using-superpowers absent from discovery and vendor. |
| N | PASS | Next/RSC guidance ignored for React+TS+Vite. |
| O | PASS | Browser mismatch investigated against contract; no fake state patched in. |

All requested textual invariants retained: worker count comes from resolved context (no blanket literal-3 ban); BarrierManager stays strategy-internal; operation/step/model-version concepts remain distinct; PostgreSQL is not a training coordinator; Backend is outside gradient causality; Workers do not use DB; WebUI has no direct Runtime/DM/DB route; synchronization does not own checkpoint cadence; Worker-0 uses normal DTP; common is not a domain dumping ground; Nháp and Coordination Matrix cannot override owners; DATA_MODEL/schema, migration, optimizer and deterministic-output corrections hold.

The checkout still contains historical management_backend naming and scaffold/migration dependency declarations outside .agents. Those pre-existing projections were not migrated, reclassified as canonical, or edited. Helpers preflight actual paths and cannot create a duplicate backend. Existing architecture/scaffold check success is limited to the rules those scripts implement; it does not certify full current canonical conformance of production code.

## I. Supply-chain audit

Fresh exact upstream commits, commit dates and license evidence recorded separately for nine candidates. The accepted guideline dependency has its own pin and license. All 37 copied byte sequences match upstream Git blob IDs and local SHA-256. Raw SKILL/AGENTS discovery and executable scripts are absent. Six active wrappers forbid installer/binary/upstream-fetch and autonomous routing behavior.

[SUPPLY_CHAIN_SCAN.md](SUPPLY_CHAIN_SCAN.md) classifies every matching line (79 at final scan); original historical commands/URLs remain visible. [RAW_REFERENCE_EXCLUSIONS.md](RAW_REFERENCE_EXCLUSIONS.md) records 40 deliberately disabled raw relative links. Every enabled local Markdown link resolves. No hidden runtime download is needed to use a wrapper.

## J. Verification results and limits

Exact commands, output and exit codes are in [VERIFICATION_COMMANDS.json](VERIFICATION_COMMANDS.json). Initial verifier findings are retained as history; the final rerun records the corrected state.

- PASS: architecture checker and scaffold checker (including source compilation, bytecode redirected outside production).
- PASS: 14 skill-creator frontmatter validations; offline skill integrity/discovery/link checks; new .agents verifier lint and formatting; git diff whitespace check.
- PASS: four negative verifier cases in disposable copies reject snapshot tampering, raw skill discovery, broken enabled link and missing wrapper. These validate the checker, not LLM behavior.
- Baseline FAIL, unchanged: production Ruff lint E501 at scripts/verify_scaffold.py:218 and formatting at line 224. Both predate this task, proven by the unchanged outside-.agents SHA-256 baseline. They are not fixed because the authorized scope forbids editing that file. This report does not claim the whole repository lint is clean.
- Unit, integration, distributed, failure and benchmark suites: SKIPPED, governance-only scope; tests directory currently contains only README, so executable production test harnesses are NOT_AVAILABLE. Architecture suite: EXECUTED via existing checker.
- Browser app acceptance / frontend build / database migration execution: SKIPPED, no app/DB implementation changed. Wrappers require preflight at use time; availability of those runtime tools is not asserted by this setup.
- Separate Markdown linter: NOT_AVAILABLE as a configured repository command; offline local link/fence/frontmatter validation used.

## K. Production immutability

158 tracked paths outside .agents match the initial content/missing-file baseline. The already-dirty review.zip changed content during the task; no command from this task wrote to that file, and its current content is left untouched. src/pbl4, web, root governance, canonical projections and scripts were not edited. No Google Drive write tool was invoked. Pre-existing unrelated ZIP changes/deletions (PBL4.zip, preview.zip, review.zip) are outside scope; no restore, delete, staging or commit command was performed by this task. Git index presentation may change independently in the desktop app; content comparison is the immutability evidence.

## L. Acceptance criteria 1–32

The PASS statuses below apply to the requested skill setup. They do not override the explicitly reported pre-existing production lint failures or claim completed production implementation.

| # | Criterion | Result | Evidence |
|---:|---|---|---|
| 1 | Internal skills architecture-safe | PASS | Manual invariant/scenario audit and retained core |
| 2 | DATA_MODEL/PostgreSQL ownership | PASS | SOURCE_REGISTRY and contract-change table |
| 3 | No mandatory Alembic | PASS | Internal governance search and migration wording |
| 4 | No universal downgrade | PASS | Conditional policy gate |
| 5 | operation_id semantics correct | PASS | Architecture/protocol/source wording |
| 6 | No optimizer state invented for stateless SGD | PASS | Release checkpoint gate |
| 7 | Debug Route C | PASS | distributed-debug and routing |
| 8 | Exact normative locator respected | PASS | Registry/routing/doc-sync |
| 9 | Local UI direction exists | PASS | pbl4-ui-direction/SKILL.md |
| 10 | Full SHA for each installed skill | PASS | VENDOR_MANIFEST integrity check |
| 11 | Verified license data | PASS | Original licenses/declarations and local MIT terms |
| 12 | Installed skills vendored | PASS | 37 pinned text files |
| 13 | Snapshots outside active discovery | PASS | vendor subtree scan |
| 14 | Active behavior through wrappers | PASS | Six scoped wrappers |
| 15 | No installer executed | PASS | Read-only upstream retrieval and vendoring only |
| 16 | No active floating fetch | PASS | Wrappers and occurrence review |
| 17 | Local pinned guideline | PASS | Separate guideline SHA/license |
| 18 | React+TS+Vite scope | PASS | React wrapper applicability filter |
| 19 | FastAPI not API owner | PASS | BACKEND_API/Contracts precedence |
| 20 | Impeccable not state/architecture owner | PASS | UI and canonical precedence |
| 21 | Completion helper supplements release | PASS | Wrapper scope and routing |
| 22 | using-superpowers absent | PASS | Exact discovery/vendor inventory |
| 23 | Registry complete and reproducible | PASS | Registry plus per-file immutable URLs/hashes |
| 24 | Separate fresh candidate audits | PASS | Nine candidate sections |
| 25 | Correct external routing precedence | PASS | SKILL_ROUTING |
| 26 | External conflict scenarios | PASS | H–O instruction-level evaluation |
| 27 | No raw external SKILL.md | PASS | Recursive discovery assertion |
| 28 | Canonical ownership preserved | PASS | Wrapper boundaries and source corrections |
| 29 | Production unchanged | PASS | Production paths unchanged; 158 other baseline paths match; review.zip change disclosed |
| 30 | Drive unchanged | PASS | No write calls |
| 31 | No silent upstream downloads needed | PASS | All enabled local references present |
| 32 | No unresolved setup architecture blocker | PASS | Scoped audit complete; historical production limits disclosed |
