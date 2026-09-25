"""Worker deployment configuration; logical rank comes from Runtime registration."""

from dataclasses import dataclass, field


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    node_label: str = "node-unknown"
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 9000
    cache_dir: str = "var/worker-cache"
    heartbeat_interval_seconds: float = 5.0
    log_level: str = "INFO"
    attempt_id: str | None = None
    allocation_id: str | None = None
    node_id: str | None = None
    worker_join_token: str | None = field(default=None, repr=False)

    def __post_init__(self) -> None:
        if (
            not self.node_label
            or not self.runtime_host
            or not 0 < self.runtime_port < 65536
            or not self.cache_dir
            or self.heartbeat_interval_seconds <= 0
        ):
            raise ValueError("Invalid Worker configuration")

        managed_fields = (
            self.attempt_id,
            self.allocation_id,
            self.node_id,
            self.worker_join_token,
        )
        is_any_managed = any(f is not None for f in managed_fields)
        is_all_managed = all(isinstance(f, str) and f for f in managed_fields)
        if is_any_managed and not is_all_managed:
            raise ValueError(
                "Managed worker identity fields (attempt_id, allocation_id, node_id, "
                "worker_join_token) must be all-or-none"
            )

    @property
    def is_managed(self) -> bool:
        return self.attempt_id is not None
