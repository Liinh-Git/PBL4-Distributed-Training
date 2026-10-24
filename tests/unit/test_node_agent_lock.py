"""Unit tests for Node Agent directory lock and auto-slot allocation."""

from __future__ import annotations

import os
from pathlib import Path

import pytest

from pbl4.node_agent.dir_lock import (
    DirectoryAlreadyLockedError,
    NodeAgentDirectoryLock,
    find_available_var_dir,
)


def test_directory_lock_acquire_and_release(tmp_path: Path) -> None:
    """Test basic lock acquisition and release lifecycle."""
    lock = NodeAgentDirectoryLock(tmp_path)
    assert not lock.is_locked

    assert lock.acquire() is True
    assert lock.is_locked is True
    assert (tmp_path / ".agent.lock").is_file()
    assert (tmp_path / "agent.pid").is_file()
    assert lock.get_occupant_pid() == os.getpid()

    # Re-entrant check on same instance returns True
    assert lock.acquire() is True

    lock.release()
    assert not lock.is_locked
    assert not (tmp_path / "agent.pid").is_file()


def test_directory_lock_exclusive_prevents_duplicate(tmp_path: Path) -> None:
    """Test that a second lock instance on the same directory is rejected."""
    lock1 = NodeAgentDirectoryLock(tmp_path)
    assert lock1.acquire() is True

    lock2 = NodeAgentDirectoryLock(tmp_path)
    assert lock2.acquire() is False
    assert not lock2.is_locked
    assert lock2.get_occupant_pid() == os.getpid()

    # Once lock1 releases, lock2 can acquire
    lock1.release()
    assert lock2.acquire() is True
    assert lock2.is_locked is True
    lock2.release()


def test_directory_lock_context_manager(tmp_path: Path) -> None:
    """Test context manager usage and DirectoryAlreadyLockedError."""
    with NodeAgentDirectoryLock(tmp_path) as lock1:
        assert lock1.is_locked is True

        with (
            pytest.raises(DirectoryAlreadyLockedError) as exc_info,
            NodeAgentDirectoryLock(tmp_path),
        ):
            pass
        assert "already locked by another Node Agent" in str(exc_info.value)
        assert str(os.getpid()) in str(exc_info.value)

    # After exit, directory can be locked again
    with NodeAgentDirectoryLock(tmp_path) as lock2:
        assert lock2.is_locked is True


def test_find_available_var_dir(tmp_path: Path) -> None:
    """Test auto-discovery skips already locked slots and assigns the next free one."""
    path0, lock0 = find_available_var_dir(base_dir=tmp_path, prefix="demo-node-")
    assert path0 == tmp_path / "demo-node-0"
    assert lock0.is_locked is True

    path1, lock1 = find_available_var_dir(base_dir=tmp_path, prefix="demo-node-")
    assert path1 == tmp_path / "demo-node-1"
    assert lock1.is_locked is True

    path2, lock2 = find_available_var_dir(base_dir=tmp_path, prefix="demo-node-")
    assert path2 == tmp_path / "demo-node-2"
    assert lock2.is_locked is True

    # If slot 1 is released, it becomes available again for new callers
    lock1.release()
    path_reused, lock_reused = find_available_var_dir(base_dir=tmp_path, prefix="demo-node-")
    assert path_reused == tmp_path / "demo-node-1"
    assert lock_reused.is_locked is True

    lock0.release()
    lock_reused.release()
    lock2.release()


def test_find_available_var_dir_exhausted(tmp_path: Path) -> None:
    """Test error when all slots up to max_slots are occupied."""
    with pytest.raises(RuntimeError) as exc_info:
        find_available_var_dir(base_dir=tmp_path, prefix="demo-node-", max_slots=0)
    assert "No available var-dir slot found" in str(exc_info.value)
