"""Independent architecture invariants for Lâm-owned wire packages."""

from __future__ import annotations

import ast
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def python_files(relative: str) -> list[Path]:
    return sorted((ROOT / relative).rglob("*.py"))


def imported_modules(path: Path) -> set[str]:
    tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
    modules: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            modules.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and node.module:
            modules.add(node.module)
    return modules


class ProtocolArchitectureTest(unittest.TestCase):
    def test_protocol_has_no_runtime_framework_or_database_imports(self) -> None:
        forbidden = (
            "pbl4.runtime",
            "pbl4.worker",
            "pbl4.management_backend",
            "pbl4.dataset_manager",
            "torch",
            "psycopg",
            "asyncpg",
            "sqlalchemy",
        )
        for path in python_files("src/pbl4/protocol"):
            for module in imported_modules(path):
                self.assertFalse(module.startswith(forbidden), f"{path}: {module}")

    def test_management_protocol_has_no_runtime_backend_or_database_imports(self) -> None:
        forbidden = (
            "pbl4.runtime",
            "pbl4.worker",
            "pbl4.management_backend",
            "pbl4.dataset_manager",
            "torch",
            "psycopg",
            "asyncpg",
            "sqlalchemy",
        )
        for path in python_files("src/pbl4/management_protocol"):
            for module in imported_modules(path):
                self.assertFalse(module.startswith(forbidden), f"{path}: {module}")

    def test_transport_has_no_protocol_or_training_imports(self) -> None:
        forbidden = ("pbl4.protocol", "pbl4.runtime", "pbl4.worker")
        for path in python_files("src/pbl4/transport"):
            for module in imported_modules(path):
                self.assertFalse(module.startswith(forbidden), f"{path}: {module}")

    def test_generic_code_has_no_worker_count_three_or_training_semantics(self) -> None:
        generic = python_files("src/pbl4/protocol") + python_files("src/pbl4/transport")
        for path in generic:
            tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
            for node in ast.walk(tree):
                if isinstance(node, ast.Compare) and any(
                    isinstance(item, ast.Constant) and item.value == 3
                    for item in (node.left, *node.comparators)
                ):
                    names = {n.id for n in ast.walk(node) if isinstance(n, ast.Name)}
                    self.assertNotIn("expected_workers", names, str(path))

        codec_tree = ast.parse((ROOT / "src/pbl4/protocol/codec.py").read_text(encoding="utf-8"))
        identifiers = {node.id for node in ast.walk(codec_tree) if isinstance(node, ast.Name)} | {
            node.attr for node in ast.walk(codec_tree) if isinstance(node, ast.Attribute)
        }
        self.assertNotIn("step_id", identifiers)
        self.assertNotIn("expected_workers", identifiers)


if __name__ == "__main__":
    unittest.main()
