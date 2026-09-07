# Open Issues — PBL4 Distributed Training

> This file tracks genuine unresolved design questions that require team alignment.
> Do NOT record issues for architecture decisions that are already frozen or resolved.

---

<!-- Template for new issues:

## ISSUE-NNN: [Title]

| Field | Value |
|---|---|
| **ID** | ISSUE-NNN |
| **Status** | Open / Resolved / Deferred |
| **Question** | What needs to be decided? |
| **Affected Contract** | Which canonical document or contract is affected? |
| **Why It Matters** | Impact on implementation |
| **Options** | A) ... B) ... |
| **Recommended Direction** | Which option and why |
| **Blocking?** | Yes / No — what is blocked? |
| **Owner** | Who should decide? |

-->

## ISSUE-001: Heartbeat Timeout and Failure Detection Thresholds

| Field | Value |
|---|---|
| **ID** | ISSUE-001 |
| **Status** | Open |
| **Question** | What are the canonical heartbeat interval and timeout thresholds for detecting worker disconnection? |
| **Affected Contract** | Runtime Heartbeat / Worker Lifecycle Specification |
| **Why It Matters** | Overly aggressive timeouts trigger false positive worker failure declarations during high load; overly lenient thresholds delay failure detection. |
| **Options** | A) Fixed protocol constants B) Runtime-configured per attempt C) Negotiated during registration |
| **Recommended Direction** | TBD / requires canonical design decision |
| **Blocking?** | No — core scaffold can proceed without freezing concrete heartbeat interval and timeout thresholds; exact ownership and values will be finalized before implementing the heartbeat mechanism. |
| **Owner** | Team consensus |
