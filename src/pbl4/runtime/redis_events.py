"""Background-only Redis transport for the existing Runtime event payload."""

import json

from redis import Redis
from redis.backoff import NoBackoff
from redis.retry import Retry


class RedisEventPublisher:
    def __init__(self, url: str, stream: str) -> None:
        self._client = Redis.from_url(
            url,
            socket_connect_timeout=2,
            socket_timeout=2,
            decode_responses=True,
            retry=Retry(NoBackoff(), 0),
        )
        self._stream = stream

    def publish(self, payloads: list[dict[str, object]]) -> None:
        # Only ACK the outbox after every reply. Ambiguous/partial writes replay
        # the batch; Backend deduplication preserves each event's identity.
        with self._client.pipeline(transaction=False) as pipe:
            for payload in payloads:
                pipe.xadd(
                    self._stream,
                    {"event": json.dumps(payload, ensure_ascii=False, separators=(",", ":"))},
                )
            pipe.execute()

    def close(self) -> None:
        self._client.close()
