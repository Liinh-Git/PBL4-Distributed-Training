---
name: protocol-change
description: >
  Primary workflow for modifying DTP/1, MCP/1, binary wire framing,
  headers, message payloads, and tensor transfer representations.
---

# Protocol Change

## 1. When to Activate

Use this skill as the **PRIMARY WORKFLOW** when modifying:
- DTP/1 wire framing, header formats, flags, or binary message schemas
- MCP/1 command and telemetry message formats
- Tensor wire streaming, chunking, or serialization codecs
- Constants in `src/pbl4/protocol/constants.py` or `src/pbl4/management_protocol/constants.py`
- Wire correlation semantics (`operation_id`, `message_id`, `correlation_id`, `command_id`, `runtime_event_seq`)

---

## 2. Step 1: Classify Protocol Kind & Resolve Canonical Owner

Before writing code or changing constants, determine the protocol kind and resolve its canonical specification from [`.agents/SOURCE_REGISTRY.md`](../../SOURCE_REGISTRY.md):

### A. DTP/1 Changes (Data Transfer Protocol)
- **Primary Canonical Owner**: `[DTP1]` (`01. DTP-1`, tab `Chính`)
- **Supporting Sources**:
  - `[CONTRACTS]` → sheet `Runtime Protocol (DTP-MCP)`
  - `[ARCH_SYSTEM]` → critical path topology
  - `[COMMUNICATION_MAP]` → port and connection topologies
  - `[DATA_MODEL]` → if changing artifact identity, hashes, or tensor representation
  - `[SYNC_STRICT_BSP]` → if modifying Strict BSP-specific payloads
- **Architectural Isolation Rules**:
  - `operation_id` must remain generic and neutral at the protocol/codec level (`operation_id` is not universally semantically equivalent to `step_id`; generic code MUST NOT assume equality; StrictBSP V1 maps them 1:1 at the strategy layer; generic schema/protocol must preserve future strategy freedom).
  - Do not couple generic DTP headers or codecs to Strict BSP Step concepts.
  - **Ownership Separation**: DTP wire format owner (`[DTP1]`) ≠ Synchronization policy owner (`[SYNC_STRICT_BSP]`).

### B. MCP/1 Changes (Management Control Protocol)
- **Primary Canonical Owner**: `[MCP1]` (`02. MCP-1`, tab `Chính`)
- **Supporting Sources**:
  - `[CONTRACTS]` → sheet `Runtime Protocol (DTP-MCP)`
  - `[COMMUNICATION_MAP]` → connection topology
  - `[BACKEND]` / `[TRAINING_RUNTIME]` → if changing command dispatch or event handling responsibilities
- **Architectural Isolation Rules**:
  - **No Raw Tensors**: MCP/1 **NEVER** carries raw gradient or parameter tensors.
  - **Correlation Separation**: Must maintain clear distinctions between:
    - `message_id`: Unique message instance ID
    - `correlation_id`: RPC request/response pairing ID
    - `command_id`: Idempotent management command execution ID
    - `runtime_event_seq`: Monotonic runtime telemetry sequence counter
  - **Ownership Separation**: MCP wire format owner (`[MCP1]`) ≠ Backend business logic owner (`[BACKEND]`).

---

## 3. Drive Unavailable Fail-Safe

> [!WARNING]
> If a protocol or wire change requires resolving wire layout, field types, or error codes, and the primary canonical source (`[DTP1]` or `[MCP1]`) is inaccessible (HTTP 401, network failure, etc.):
> - **HALT** immediately.
> - **DO NOT** guess field layouts or pad byte sizes from local code or tab `Nháp`.
> - **Report**:
>   ```text
>   BLOCKED_CANONICAL_SOURCE_UNAVAILABLE: Cannot access canonical source [<SOURCE_KEY>] (<URL>) to resolve wire specifications. Halting protocol change.
>   ```

---

## 4. Wire Change Engineering Checklist

When modifying wire-level definitions, every PR/change must address:
- [ ] **Exact 48-Byte Header Layout**: DTP/1 fixed header must be exactly 48 bytes with canonical field offsets, big-endian byte order, CRC, and sentinel flags.
- [ ] **No Invented Padding / Alignment**:
  - Codecs and headers MUST NOT introduce invented padding fields, arbitrary alignment bytes (no generic "8-byte alignment" requirement), or implicit version fields unless explicitly specified in `[DTP1]`.
- [ ] **Compatibility Impact**: Is the change backward-compatible? Does it require protocol version bumping? (Protocol bumps require team architectural approval).
- [ ] **Maximum Length Validation**: Enforce explicit maximum size limits on strings, chunk sizes, and payloads to prevent denial-of-service / memory exhaustion.
- [ ] **Malformed Frame Handling**: Tests verify that corrupt magic, invalid message types, and out-of-bounds lengths trigger immediate clean socket closure or error frames.
- [ ] **Truncated Frame Handling**: Tests verify that partial header or payload reads do not hang or desync framing (`recv_exact` contract).
- [ ] **Exact-Byte Golden Vectors**: Encode and decode tests using verified binary golden byte sequences directly from canonical specifications.
- [ ] **Sender & Receiver Impact**: Synchronize both sender and receiver implementations across process boundaries.

---

## 5. Standard Pipeline Integration

Following `.agents/SKILL_ROUTING.md`:
1. `protocol-change` is the **PRIMARY WORKFLOW**.
2. Reuses the `resolved canonical source set` across supporting skills.
3. Passes to `architecture-guard` to verify that `protocol` and `transport` have zero invalid imports.
4. Passes to `distributed-verification` if gradient transfer or parameter synchronization is affected.
5. Passes to `doc-sync` for repository projection synchronization.
6. Passes to `release-gate` for protocol-specific verification.
