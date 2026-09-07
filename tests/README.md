# PBL4 Test Suite

> **Note on Test Strategy:** Tests in this repository are created together with or after their corresponding implementation, not ahead of time.

## Policy

1. **No Pre-Created Empty Taxonomies:** Do not create empty test directories or placeholder tests before the underlying modules exist.
2. **Timing:** Feature tests accompany implemented features before merge.
3. **Protocol Exact-Byte / Golden Tests:** Wire-level contract tests are created *after* the protocol codec implementation, deriving strictly from canonical DTP/1 and MCP/1 specifications.
4. **Regression Tests:** When debugging or fixing an issue, add a regression test after reproducing and fixing the root cause, before merging.
5. **Future Categories:** When implementation begins, test directories may be created as needed:
   - `unit/` — pure logic, fast execution, no network/database I/O.
   - `integration/` — multi-component integration within a single process or with real database/filesystem.
   - `distributed/` — multi-process coordination between Runtime, Workers, and Dataset Manager.
   - `failure/` — fault injection and network partition/timeout scenarios.
   - `benchmark/` — performance and throughput measurements.

Architecture constraints are statically enforced via `python scripts/check_architecture.py`.
