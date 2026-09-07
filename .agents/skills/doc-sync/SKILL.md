---
name: doc-sync
description: >
  Workflow for synchronizing repository documentation and projections with
  canonical technical specifications hosted on Google Drive.
---

# Doc Sync

## 1. Authority & Principles

1. **Specific Canonical Ownership**: Canonical technical specifications live on Google Drive. Each architectural subsystem, protocol, and contract has **one specific canonical owner** registered in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md). Documents do not share equal authority; the primary owner always outranks supporting sources.
2. **Normative Locator**: Resolve and read the exact normative locator declared in SOURCE_REGISTRY: exact named sheets for Sheets, whole document for whole-document sources, and the declared Doc tab. The following convention applies to Docs that declare it:
   - Tab `Chính` = **Canonical / Normative**. All documentation projections must align strictly with `Chính`.
   - Tab `Nháp` = **Non-normative working material**. Tab `Nháp` is **IGNORED** and must never be synced into local projections as established architecture.
3. **Projections Never Override Canonical Architecture**: Repository documents (`docs/IMPLEMENTATION_CONTRACT.md`, `README.md`, `AGENTS.md`, docstrings, and existing code) are projections. If a local projection diverges from the canonical Drive owner, **the canonical document wins** and the projection must be updated.
4. **No Bulk Rewrites**: Make surgical, localized updates to affected projection sections only.

---

## 2. Seven-Step Synchronization Protocol

Execute projection updates following this strict sequence:

```
Step 1: Classify Semantic Contract
         ↓
Step 2: Resolve Stable Source Key from SOURCE_REGISTRY.md
         ↓
Step 3: Open Exact Canonical Drive Document / Sheet
         ↓
Step 4: Read exact normative locator declared in SOURCE_REGISTRY
         ↓
Step 5: Identify Target Repository Projections
         ↓
Step 6: Perform Surgical Synchronization
         ↓
Step 7: Verify Zero Semantic Invention Outside Owner Scope
```

### Step 1: Classify Semantic Contract
Identify what domain is changing (wire protocol, domain lifecycle, DB schema, REST endpoint, checkpoint format).

### Step 2: Resolve Stable Source Key
Look up the primary owner key (e.g., `[DTP1]`, `[BACKEND_API]`, `[POSTGRESQL]`) in [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md).

### Step 3: Access Canonical Document
Consult the exact Drive URL associated with the key.

> [!WARNING]
> **Drive Unavailable Fail-safe**: If canonical source resolution is required to settle an architectural ambiguity and Drive is inaccessible:
> - **HALT** projection sync.
> - **DO NOT** guess or infer new architecture from local source code.
> - **Report**:
>   ```text
>   BLOCKED_CANONICAL_SOURCE_UNAVAILABLE: Cannot access canonical source [<SOURCE_KEY>] (<URL>) to sync projection. Halting doc-sync.
>   ```

### Step 4: Confirm Normative Section
Read the exact normative locator declared in SOURCE_REGISTRY (Doc tab, exact named sheet, or whole document). Ignore tab `Nháp` and archive folders (`99. Cũ`, `FINAL_REPORT`).

### Step 5: Identify Affected Repository Projections
Map the change to repository files:
- `docs/IMPLEMENTATION_CONTRACT.md`: System-wide contracts, module mappings, communication paths.
- `AGENTS.md` / nested `AGENTS.md`: Subsystem boundaries and package rules; edit only in an explicitly authorized governance task, never as a side effect of feature work.
- Code Docstrings: Module and class level contract documentation.
- `docs/OPEN_ISSUES.md`: Update status when tracked architectural questions are resolved.

### Step 6: Surgical Sync
Update only the specific lines or tables representing the changed contract.

### Step 7: Integrity Verification
Verify that the update introduces no secondary architectures or unapproved domain enums.

---

## 3. Conflict Resolution Protocol

If two canonical documents appear to contradict each other:
1. **DO NOT** guess or pick the more "convenient" option.
2. **Report the conflict explicitly**:
   ```text
   CANONICAL_CONFLICT_DETECTED:
   - Source A: [<KEY_A>] <Title> (Section / Sheet: <Loc_A>)
   - Source B: [<KEY_B>] <Title> (Section / Sheet: <Loc_B>)
   - Conflict Description: <Detail of contradiction>
   - Implementation Impact: <How it affects the system>
   - Recommended Authority: <Which owner should logically govern per SOURCE_REGISTRY.md>
   ```
3. Await user / human architect resolution before updating projections.
