"""System telemetry and hardware capability discovery for Node Agent.

Monitors CPU, RAM, and NVIDIA GPU resources without crashing when GPU / NVML is unavailable.
"""

from __future__ import annotations

import logging
import platform
from typing import Any

import psutil

from pbl4.agent_protocol.messages import GpuSnapshotItem, ResourceSnapshotPayload

logger = logging.getLogger(__name__)

import warnings

# Defensive pynvml import
try:
    with warnings.catch_warnings():
        warnings.simplefilter("ignore", category=FutureWarning)
        import pynvml
    _HAS_PYNVML = True
except ImportError:
    pynvml = None  # type: ignore[assignment]
    _HAS_PYNVML = False


def _get_gpu_snapshots() -> list[GpuSnapshotItem]:
    """Sample real-time GPU utilization and VRAM using pynvml if available."""
    if not _HAS_PYNVML or pynvml is None:
        return []

    snapshots: list[GpuSnapshotItem] = []
    try:
        pynvml.nvmlInit()
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for idx in range(device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                    try:
                        util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                        gpu_util = float(util.gpu)
                    except Exception:
                        gpu_util = None

                    try:
                        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        vram_used = int(mem.used)
                        vram_total = int(mem.total)
                    except Exception:
                        vram_used = None
                        vram_total = None

                    snapshots.append(
                        GpuSnapshotItem(
                            index=idx,
                            gpu_utilization_pct=gpu_util,
                            vram_used_bytes=vram_used,
                            vram_total_bytes=vram_total,
                        )
                    )
                except Exception as exc:
                    logger.debug("Failed querying GPU device index %d: %s", idx, exc)
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("NVML unavailable or failed to initialize: %s", exc)
        return []

    return snapshots


def _get_gpu_static_capabilities() -> list[dict[str, Any]]:
    """Query static GPU capabilities using pynvml if available."""
    if not _HAS_PYNVML or pynvml is None:
        return []

    gpu_caps: list[dict[str, Any]] = []
    try:
        pynvml.nvmlInit()
        try:
            device_count = pynvml.nvmlDeviceGetCount()
            for idx in range(device_count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(idx)
                    try:
                        name_raw = pynvml.nvmlDeviceGetName(handle)
                        name = name_raw.decode("utf-8", errors="replace") if isinstance(name_raw, bytes) else str(name_raw)
                    except Exception:
                        name = f"NVIDIA GPU #{idx}"

                    try:
                        mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                        total_vram = int(mem.total)
                    except Exception:
                        total_vram = 0

                    gpu_caps.append(
                        {
                            "index": idx,
                            "name": name,
                            "total_vram_bytes": total_vram,
                        }
                    )
                except Exception as exc:
                    logger.debug("Failed querying static info for GPU %d: %s", idx, exc)
        finally:
            try:
                pynvml.nvmlShutdown()
            except Exception:
                pass
    except Exception as exc:
        logger.debug("NVML unavailable or failed during static capability collection: %s", exc)
        return []

    return gpu_caps


def collect_static_capabilities() -> dict[str, Any]:
    """Discover host hardware and OS static capabilities."""
    vm = psutil.virtual_memory()
    return {
        "hostname": platform.node(),
        "platform": platform.system(),
        "platform_release": platform.release(),
        "architecture": platform.machine(),
        "python_version": platform.python_version(),
        "cpu_count_logical": psutil.cpu_count(logical=True) or 1,
        "cpu_count_physical": psutil.cpu_count(logical=False) or 1,
        "ram_total_bytes": int(vm.total),
        "gpus": _get_gpu_static_capabilities(),
    }


def sample_resources() -> ResourceSnapshotPayload:
    """Sample current host resource utilization (CPU, RAM, GPU).

    Guarantees:
    - Never crashes even if NVML or GPU querying fails.
    - Accurately captures CPU, RAM, and any available GPUs.
    """
    cpu_pct = float(psutil.cpu_percent(interval=None))
    vm = psutil.virtual_memory()
    ram_used = int(vm.used)
    ram_total = int(vm.total)
    gpu_snapshots = tuple(_get_gpu_snapshots())

    return ResourceSnapshotPayload(
        cpu_utilization_pct=cpu_pct,
        ram_used_bytes=ram_used,
        ram_total_bytes=ram_total,
        gpus=gpu_snapshots,
    )
