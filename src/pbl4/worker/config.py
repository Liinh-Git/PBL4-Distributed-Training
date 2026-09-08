"""Worker deployment configuration; logical rank comes from Runtime registration."""

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class WorkerConfig:
    node_label: str = "node-unknown"
    runtime_host: str = "127.0.0.1"
    runtime_port: int = 9000
    cache_dir: str = "var/worker-cache"
    heartbeat_interval_seconds: float = 5.0
    log_level: str = "INFO"

    def __post_init__(self) -> None:
        if (
            not self.node_label
            or not self.runtime_host
            or not 0 < self.runtime_port < 65536
            or not self.cache_dir
            or self.heartbeat_interval_seconds <= 0
        ):
            raise ValueError("Invalid Worker configuration")
