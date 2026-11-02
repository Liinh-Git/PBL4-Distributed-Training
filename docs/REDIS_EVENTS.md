# Runtime management events via Redis Streams

Install the process extras (`uv sync --extra runtime --extra management-backend`).
Set `REDIS_URL=redis://127.0.0.1:6379/0` and
`REDIS_EVENT_STREAM=pbl4:runtime-events` identically for Runtime and Backend.
Both entrypoints load the working directory's `.env`; exported environment values
take precedence. Empty `REDIS_URL` keeps the existing MCP event transport.
Enable/disable both processes together while no Attempt is active; older MCP
snapshot metadata did not distinguish the durable projection cursor.

Local Redis deployment (from the repository root). `deploy/redis.conf` uses AOF
only, compact rewrites with an RDB preamble, and retains fsync during rewrite:

```sh
docker run -d --name pbl4-redis -p 127.0.0.1:6379:6379 -v pbl4-redis:/data -v "${PWD}/deploy/redis.conf:/usr/local/etc/redis/redis.conf:ro" redis:7.4 redis-server /usr/local/etc/redis/redis.conf --bind 0.0.0.0
```

Use a private reachable endpoint for multiple machines; protect access with Redis
ACL credentials/TLS as appropriate (`rediss://`). Do not expose Redis publicly.
The bundled command binds only localhost. AOF `everysec` can lose roughly one
second on host failure; use `appendfsync always` when that tradeoff is unacceptable.
An XADD response confirms Redis accepted the event, not that everysec fsync finished.

One process-wide background thread publishes compact event JSON in the `event`
stream field with non-transactional XADD pipelines of up to 64 events. It removes
the batch from its bounded queue only after every XADD reply succeeds.
Partial writes or lost replies retain the batch for deduplicated replay.
Timeout/reconnect can duplicate delivery; PostgreSQL deduplication still uses
`(attempt_id, runtime_event_seq)`. Redis I/O is outside training and state locks.
Redis failures retry at 0.5–30 seconds and log degraded/recovered status. The queue
shares one 8192-entry buffer across Attempts, retaining priority eviction and
per-Attempt sequence/drop counters;
overflow or Runtime process loss can lose events. It is not a durable local outbox.

Run exactly **one Backend process/consumer** for each stream (no multiple Uvicorn
workers). Group `pbl4-backend`, consumer `backend` are stable identities. On startup
or error, read own pending entries with XREADGROUP cursor `0`, then wait for new
entries with `XREADGROUP COUNT 100 BLOCK 1000`. This requires no idle claiming timer. Keep
the same stream/group identity across restarts; do not delete the group or stream.
Partial new reads allow a single 25 ms collection window before a non-blocking
read for the remaining slots. A full backlog or pending replay does not wait.
SQL batches are bounded by 100 events and 256 KiB of source JSON; a single larger
event is processed alone. Limits are ordinary constructor defaults, not extra
environment settings. Redis remains the only Backend event buffer.

The existing ingestion, deduplication, sequence/gap handling, SQL projections and
WebSocket publisher are reused. Ordered history, projection and the existing
metadata cursor commit in one transaction per contiguous batch. Each Attempt's
cursor is written once at the end of that batch. Lifecycle events requiring a
snapshot and sequence gaps split batches; authoritative snapshot I/O stays
outside SQL transactions. INSERT-first dedup avoids a SELECT
for new events; duplicates still undergo semantic conflict checks.
DB/read/projection failures roll back the whole current SQL batch and prevent
its XACK. Earlier committed prefixes can still be acknowledged. On restart,
pending replay resumes from the durable projection
cursor even if a newer MCP snapshot arrived. Existing gap recovery uses a committed
authoritative MCP snapshot, skipping only through the encountered gap event.
A newer snapshot does not skip all later queued projections. Gaps from dropped
events cannot restore full history.
WebSocket is best effort after DB commit; reconnect catches up from PostgreSQL.

`model.updated` retains the V1 envelope and core contribution fields:
`worker_id`, `session_id`, `shard_id`, `batch_id`, `sample_count`, `loss` and
`compute_ms`. New events omit optional diagnostic copies of `tensor_id`,
`parameter_manifest_hash`, `batch_ordinal` and `correct_count`. Readers continue
accepting legacy payloads containing these keys, and persisted history is never
rewritten. Runtime Contribution/DTP data, epoch metrics and DBS inputs retain
all their existing fields. No metrics are averaged or sampled away for batching.

After processing a batch, one Redis transaction XACKs and XDELs only the
committed prefix. A failed item and its successors stay pending. This
stream is dedicated to the sole Backend group; extra consumer groups are unsupported.
No MAXLEN trim may discard unread/pending data. Unprocessed entries accumulate in
Redis during Backend/DB outages; `maxmemory` + `noeviction` rejects writes when full,
so Runtime retries and its bounded queue eviction applies. Monitor memory and
pending length; poison/conflicting events stay pending and stall the consumer until
the cause is repaired. There is no automatic discard or dead-letter queue.

Backend `/api/v1/health` reports `backend=degraded` while consumption is failing.
Commands, Command Results, State Snapshots and catalog lookup remain on MCP/1.
Redis failure never falls back to MCP event publication. DTP, Workers, Node Agent,
Dataset Manager, synchronization and checkpoint gates do not depend on Redis.

Canonical Drive follow-up is listed in `IMPLEMENTATION_CONTRACT.md`; this change
does not edit those remote documents. Redis command behavior follows the
[official Streams documentation](https://redis.io/docs/latest/develop/data-types/streams/).
