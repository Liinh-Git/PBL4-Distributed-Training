"""One consumer, with a stable identity so restart replays its pending entries."""

import json
import logging
import threading
from collections.abc import Callable

from redis import Redis
from redis.backoff import NoBackoff
from redis.exceptions import ResponseError
from redis.retry import Retry

logger = logging.getLogger(__name__)


class RedisEventConsumer:
    GROUP = "pbl4-backend"
    CONSUMER = "backend"

    def __init__(
        self,
        url: str,
        stream: str,
        ingest: Callable[[list[dict]], int],
        *,
        batch_size: int = 100,
        max_wait: float = 0.025,
        max_batch_bytes: int = 262144,
    ) -> None:
        if batch_size <= 0 or max_wait < 0 or max_batch_bytes <= 0:
            raise ValueError("Invalid event batch limits")
        self._client = Redis.from_url(
            url,
            socket_connect_timeout=2,
            socket_timeout=3,
            decode_responses=True,
            retry=Retry(NoBackoff(), 0),
        )
        self._stream = stream
        self._ingest = ingest
        self._batch_size = batch_size
        self._max_wait = max_wait
        self._max_batch_bytes = max_batch_bytes
        self._stopping = threading.Event()
        self._thread = threading.Thread(target=self._run, name="redis-events", daemon=True)
        self.degraded = True

    def start(self) -> None:
        self._thread.start()

    def stop(self) -> None:
        self._stopping.set()
        self._thread.join()
        self._client.close()

    def _consume(self, pending: bool) -> bool:
        batches = self._client.xreadgroup(
            self.GROUP,
            self.CONSUMER,
            {self._stream: "0" if pending else ">"},
            count=self._batch_size,
            **({} if pending else {"block": 1000}),
        )
        entries = [entry for _, items in batches for entry in items]
        # A backlog flushes immediately. At low load, allow one short collection
        # window, outside SQL and without another application queue. Pending
        # reads cannot be repeated before ACK or they would return the same IDs.
        if (
            not pending
            and 0 < len(entries) < self._batch_size
            and not self._stopping.wait(self._max_wait)
        ):
            more = self._client.xreadgroup(
                self.GROUP,
                self.CONSUMER,
                {self._stream: ">"},
                count=self._batch_size - len(entries),
            )
            entries.extend(entry for _, items in more for entry in items)

        committed = []
        try:
            offset = 0
            while offset < len(entries) and not self._stopping.is_set():
                payloads = []
                batch_bytes = 0
                for _, fields in entries[offset : offset + self._batch_size]:
                    raw = fields["event"]
                    size = len(raw.encode("utf-8"))
                    if payloads and batch_bytes + size > self._max_batch_bytes:
                        break
                    payloads.append(json.loads(raw))
                    batch_bytes += size
                count = self._ingest(payloads)
                if not 0 < count <= len(payloads):
                    raise ValueError("Event ingestion must commit a nonempty prefix")
                committed.extend(entry_id for entry_id, _ in entries[offset : offset + count])
                offset += count
        finally:
            # Retain the failed item and successors; ACK only the committed prefix.
            if committed:
                with self._client.pipeline(transaction=True) as pipe:
                    pipe.xack(self._stream, self.GROUP, *committed)
                    pipe.xdel(self._stream, *committed)
                    pipe.execute()
        return bool(committed)

    def _run(self) -> None:
        delay = 0.5
        while not self._stopping.is_set():
            try:
                try:
                    self._client.xgroup_create(self._stream, self.GROUP, id="0", mkstream=True)
                except ResponseError as exc:
                    if "BUSYGROUP" not in str(exc):
                        raise
                # Always finish pending work before reading new entries. A failed
                # ingest stays pending, including after process restart.
                while not self._stopping.is_set() and self._consume(pending=True):
                    pass
                while not self._stopping.is_set():
                    self._consume(pending=False)
                    if self.degraded:
                        logger.info("Redis Runtime event consumer recovered")
                    self.degraded = False
                    delay = 0.5
            except Exception as exc:
                self.degraded = True
                logger.warning(
                    "Runtime event ingestion degraded; pending retained: %s", type(exc).__name__
                )
                self._stopping.wait(delay)
                delay = min(delay * 2, 30.0)
