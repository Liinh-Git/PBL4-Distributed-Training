"""OS-level directory lock for Node Agent var-dir protection and auto-allocation.

Guarantees:
- Strictly ONE running Node Agent per var-dir.
- OS-level non-blocking exclusive lock (msvcrt on Windows, fcntl on POSIX).
- Kernel automatically releases lock on process exit, termination, or crash.
- Auto-allocates next available demo-node slot without race conditions.
"""

from __future__ import annotations

import contextlib
import logging
import os
from pathlib import Path
from typing import Any

logger = logging.getLogger("pbl4.node_agent")

if os.name == "nt":
    import msvcrt
else:
    import fcntl


class DirectoryAlreadyLockedError(Exception):
    """Raised when a directory cannot be locked because another agent process is running."""

    pass


class NodeAgentDirectoryLock:
    """Exclusive directory lock ensuring only one Node Agent process runs in a var-dir."""

    def __init__(self, var_dir: str | Path) -> None:
        self.var_dir = Path(var_dir)
        self.lock_file_path = self.var_dir / ".agent.lock"
        self.pid_file_path = self.var_dir / "agent.pid"
        self._file: Any = None
        self._locked = False

    @property
    def is_locked(self) -> bool:
        """True if lock is currently held by this instance."""
        return self._locked

    def acquire(self) -> bool:
        """Attempt to acquire non-blocking exclusive lock.

        Returns True if acquired successfully, False if already locked.
        """
        if self._locked:
            return True

        try:
            self.var_dir.mkdir(parents=True, exist_ok=True)
            self._file = open(self.lock_file_path, "a+b")  # noqa: SIM115

            if os.name == "nt":
                self._file.seek(0)
                msvcrt.locking(self._file.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                fcntl.flock(self._file.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)

            self._locked = True
            with contextlib.suppress(Exception):
                self.pid_file_path.write_text(f"{os.getpid()}\n", encoding="utf-8")
            return True

        except (OSError, PermissionError):
            if self._file is not None:
                with contextlib.suppress(Exception):
                    self._file.close()
                self._file = None
            self._locked = False
            return False

    def get_occupant_pid(self) -> int | None:
        """Read the PID of the occupant process from agent.pid if available."""
        if self.pid_file_path.is_file():
            try:
                content = self.pid_file_path.read_text(encoding="utf-8").strip()
                return int(content)
            except Exception:
                return None
        return None

    def release(self) -> None:
        """Release the directory lock and clean up lock handle."""
        if self._locked and self._file is not None:
            try:
                if os.name == "nt":
                    self._file.seek(0)
                    msvcrt.locking(self._file.fileno(), msvcrt.LK_UNLCK, 1)
                else:
                    fcntl.flock(self._file.fileno(), fcntl.LOCK_UN)
            except Exception:
                pass

            with contextlib.suppress(Exception):
                self._file.close()
            self._file = None
            self._locked = False

            with contextlib.suppress(Exception):
                if self.pid_file_path.is_file():
                    self.pid_file_path.unlink()

    def __enter__(self) -> NodeAgentDirectoryLock:
        if not self.acquire():
            occupant = self.get_occupant_pid()
            occupant_str = f" (PID {occupant})" if occupant else ""
            raise DirectoryAlreadyLockedError(
                f"Directory '{self.var_dir}' is already locked by another Node Agent process"
                f"{occupant_str}."
            )
        return self

    def __exit__(self, exc_type: Any, exc_val: Any, exc_tb: Any) -> None:
        self.release()


def find_available_var_dir(
    base_dir: str | Path = "var",
    prefix: str = "demo-node-",
    max_slots: int = 20,
) -> tuple[Path, NodeAgentDirectoryLock]:
    """Find the first available var-dir slot and acquire its lock atomically.

    Returns:
        (var_dir_path, acquired_lock)
    Raises:
        RuntimeError if no available slot is found within max_slots.
    """
    base = Path(base_dir)
    for i in range(max_slots):
        candidate = base / f"{prefix}{i}"
        lock = NodeAgentDirectoryLock(candidate)
        if lock.acquire():
            return candidate, lock

    raise RuntimeError(
        f"No available var-dir slot found under '{base}' with prefix '{prefix}' "
        f"(checked 0 to {max_slots - 1})."
    )
