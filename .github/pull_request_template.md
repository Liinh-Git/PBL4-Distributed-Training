## Pull Request

### What type of change?

- [ ] Internal (implementation, no API/protocol change)
- [ ] Architecture (new package, moved files, dependency change)
- [ ] Protocol (DTP/MCP wire format change)
- [ ] Contract/Domain (state machine, domain type change)
- [ ] Database (schema change)
- [ ] API (REST/WebSocket endpoint change)
- [ ] Deployment (configuration, infrastructure)
- [ ] Frontend (WebUI change)

### Checklist

- [ ] **Canonical contract changed?** If yes, which document?
- [ ] **Protocol/schema version bumped?** (DTP, MCP, dataset, parameter manifest, checkpoint)
- [ ] **Migration needed?** If DB schema changed, migration script included?
- [ ] **Golden fixture changed?** Updated expected bytes/hashes?
- [ ] **Failure behavior changed?** How does this affect fault tolerance?
- [ ] **Docs updated?** Implementation contract, OPEN_ISSUES, README as needed?
- [ ] **`python scripts/check_architecture.py` passes?** Zero package boundary violations?
- [ ] **Verification performed?** Describe what was tested.

### Description

<!-- Describe what this PR does and why. -->

### Verification

<!-- How was this tested? Include test commands and results. -->
