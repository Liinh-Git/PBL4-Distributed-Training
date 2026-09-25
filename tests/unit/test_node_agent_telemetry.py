"""Unit tests for Node Agent telemetry collection.

Tests:
1. CPU/RAM resource sampling.
2. GPU capabilities and resource snapshot with NVML mocked successfully.
3. Graceful handling of pynvml ImportError (non-NVIDIA host).
4. Graceful handling of NVML runtime failure (driver error or initialization failure).
5. Invariant: Agent never crashes when GPU is unavailable.
"""

from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from pbl4.agent_protocol.messages import GpuSnapshotItem, ResourceSnapshotPayload
from pbl4.node_agent.telemetry import collect_static_capabilities, sample_resources


class TestNodeAgentTelemetry(unittest.TestCase):
    """Test suite for host telemetry and capability discovery."""

    def test_1_cpu_ram_sample_resources(self) -> None:
        """Verify CPU and RAM are sampled accurately into ResourceSnapshotPayload."""
        snapshot = sample_resources()
        self.assertIsInstance(snapshot, ResourceSnapshotPayload)
        self.assertIsInstance(snapshot.cpu_utilization_pct, float)
        self.assertGreaterEqual(snapshot.cpu_utilization_pct, 0.0)
        self.assertIsInstance(snapshot.ram_used_bytes, int)
        self.assertGreater(snapshot.ram_used_bytes, 0)
        self.assertIsInstance(snapshot.ram_total_bytes, int)
        self.assertGreater(snapshot.ram_total_bytes, snapshot.ram_used_bytes)
        self.assertIsInstance(snapshot.gpus, tuple)

    def test_2_gpu_capability_and_resource_success_mocked_nvml(self) -> None:
        """When NVML returns valid device data, GPU snapshots and static caps are populated."""
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 2

        # Device 0
        h0 = MagicMock()
        mock_pynvml.nvmlDeviceGetHandleByIndex.side_effect = lambda idx: (
            h0 if idx == 0 else MagicMock()
        )
        mock_pynvml.nvmlDeviceGetName.return_value = b"NVIDIA GeForce RTX 4090"

        util_mock = MagicMock()
        util_mock.gpu = 45.0
        mock_pynvml.nvmlDeviceGetUtilizationRates.return_value = util_mock

        mem_mock = MagicMock()
        mem_mock.used = 4 * 1024**3
        mem_mock.total = 24 * 1024**3
        mock_pynvml.nvmlDeviceGetMemoryInfo.return_value = mem_mock

        with (
            patch("pbl4.node_agent.telemetry.pynvml", mock_pynvml),
            patch("pbl4.node_agent.telemetry._HAS_PYNVML", True),
        ):
            # Static capabilities
            caps = collect_static_capabilities()
            self.assertIn("gpus", caps)
            self.assertEqual(len(caps["gpus"]), 2)
            self.assertEqual(caps["gpus"][0]["name"], "NVIDIA GeForce RTX 4090")
            self.assertEqual(caps["gpus"][0]["total_vram_bytes"], 24 * 1024**3)

            # Realtime snapshot
            snapshot = sample_resources()
            self.assertEqual(len(snapshot.gpus), 2)
            gpu0 = snapshot.gpus[0]
            self.assertIsInstance(gpu0, GpuSnapshotItem)
            self.assertEqual(gpu0.index, 0)
            self.assertEqual(gpu0.gpu_utilization_pct, 45.0)
            self.assertEqual(gpu0.vram_used_bytes, 4 * 1024**3)
            self.assertEqual(gpu0.vram_total_bytes, 24 * 1024**3)

    def test_3_import_error_pynvml_absent(self) -> None:
        """When pynvml cannot be imported, telemetry falls back gracefully to gpus=[]."""
        with (
            patch("pbl4.node_agent.telemetry.pynvml", None),
            patch("pbl4.node_agent.telemetry._HAS_PYNVML", False),
        ):
            caps = collect_static_capabilities()
            self.assertEqual(caps["gpus"], [])

            snapshot = sample_resources()
            self.assertEqual(snapshot.gpus, ())
            self.assertGreater(snapshot.ram_total_bytes, 0)

    def test_4_nvml_initialization_failure(self) -> None:
        """When pynvml.nvmlInit raises an error, telemetry logs and returns empty GPU list."""
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlInit.side_effect = Exception("NVML Shared Library Not Found")

        with (
            patch("pbl4.node_agent.telemetry.pynvml", mock_pynvml),
            patch("pbl4.node_agent.telemetry._HAS_PYNVML", True),
        ):
            caps = collect_static_capabilities()
            self.assertEqual(caps["gpus"], [])

            snapshot = sample_resources()
            self.assertEqual(snapshot.gpus, ())
            self.assertGreater(snapshot.ram_total_bytes, 0)

    def test_5_agent_never_crashes_on_partial_gpu_error(self) -> None:
        """A device query failure does not suppress other metrics."""
        mock_pynvml = MagicMock()
        mock_pynvml.nvmlDeviceGetCount.return_value = 1
        mock_pynvml.nvmlDeviceGetHandleByIndex.side_effect = RuntimeError("Device lost")

        with (
            patch("pbl4.node_agent.telemetry.pynvml", mock_pynvml),
            patch("pbl4.node_agent.telemetry._HAS_PYNVML", True),
        ):
            caps = collect_static_capabilities()
            self.assertIsInstance(caps, dict)
            self.assertEqual(caps["gpus"], [])

            snapshot = sample_resources()
            self.assertIsInstance(snapshot, ResourceSnapshotPayload)
            self.assertEqual(snapshot.gpus, ())


if __name__ == "__main__":
    unittest.main()
