#!/usr/bin/env python3
"""Standalone Architecture Boundary Checker for PBL4.

Statically analyzes Python AST imports across packages to enforce canonical
architectural boundaries. Does NOT depend on pytest or third-party libraries.

Usage:
    uv run python scripts/check_architecture.py
"""

from __future__ import annotations

import ast
import sys
from pathlib import Path

SRC_ROOT = Path(__file__).resolve().parent.parent / "src" / "pbl4"


def get_python_files(package_dir: Path) -> list[Path]:
    """Recursively collect all .py files under a directory."""
    if not package_dir.exists():
        return []
    return sorted(p for p in package_dir.rglob("*.py") if p.is_file())


def extract_imports(filepath: Path) -> tuple[list[str], str | None]:
    """Extract imported module names from a Python source file using AST.

    Returns:
        (imports_list, syntax_error_message_or_None)
    """
    try:
        source = filepath.read_text(encoding="utf-8")
        tree = ast.parse(source, filename=str(filepath))
    except (SyntaxError, UnicodeDecodeError) as e:
        return [], f"AST parse failure in {filepath}: {e}"

    imports: list[str] = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                imports.append(alias.name)
        elif isinstance(node, ast.ImportFrom) and node.module:
            imports.append(node.module)
    return imports, None


def check_forbidden_imports(
    package_subpath: str,
    forbidden_prefixes: list[str],
    rule_description: str,
) -> list[str]:
    """Check that files under package_subpath do not import forbidden prefixes."""
    target_dir = SRC_ROOT.joinpath(*package_subpath.split("/"))
    violations: list[str] = []

    for file_path in get_python_files(target_dir):
        rel_path = file_path.relative_to(SRC_ROOT.parent)
        imports, parse_err = extract_imports(file_path)
        if parse_err:
            violations.append(
                f"  [SYNTAX ERROR] {rel_path}\n"
                f"    Detail: {parse_err}\n"
                f"    Violated architectural rule: Architecture check requires valid Python AST"
            )
            continue
        for imp in imports:
            for prefix in forbidden_prefixes:
                if imp == prefix or imp.startswith(prefix + "."):
                    violations.append(
                        f"  [VIOLATION] {rel_path}\n"
                        f"    Offending import: '{imp}' (matches forbidden prefix '{prefix}')\n"
                        f"    Violated architectural rule: {rule_description}"
                    )
    return violations


def main() -> int:
    """Run all canonical architectural boundary checks."""
    if not SRC_ROOT.exists():
        print(f"Source root not found: {SRC_ROOT}", file=sys.stderr)
        return 1

    violations: list[str] = []

    # 1. Protocol isolation (wire-only)
    violations.extend(
        check_forbidden_imports(
            "protocol",
            [
                "pbl4.runtime",
                "pbl4.worker",
                "pbl4.management_backend",
                "pbl4.dataset_manager",
                "torch",
                "torchvision",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "protocol must be wire-only: zero runtime/worker/backend/torch/db imports",
        )
    )

    # 2. Transport isolation (generic TCP primitives only)
    violations.extend(
        check_forbidden_imports(
            "transport",
            [
                "pbl4.protocol",
                "pbl4.runtime",
                "pbl4.worker",
                "pbl4.management_backend",
                "pbl4.dataset_manager",
                "torch",
                "torchvision",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "transport is generic TCP primitives only: no framing, runtime, or app imports",
        )
    )

    # 3. Common isolation (foundation primitives only)
    violations.extend(
        check_forbidden_imports(
            "common",
            [
                "pbl4.protocol",
                "pbl4.transport",
                "pbl4.runtime",
                "pbl4.worker",
                "pbl4.adapter",
                "pbl4.management_backend",
                "pbl4.dataset_manager",
                "pbl4.cli",
                "pbl4.management_protocol",
                "torch",
                "torchvision",
                "fastapi",
                "uvicorn",
                "starlette",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "common must not import higher project packages or frameworks (torch/fastapi/db)",
        )
    )

    # 4. Worker isolation
    violations.extend(
        check_forbidden_imports(
            "worker",
            [
                "pbl4.management_backend",
                "pbl4.dataset_manager",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "worker must not import management_backend, dataset_manager, or database libraries",
        )
    )

    # 5. Management Backend isolation
    violations.extend(
        check_forbidden_imports(
            "management_backend",
            [
                "pbl4.runtime",
                "pbl4.worker",
                "torch",
                "torchvision",
            ],
            "management_backend must not import runtime internals, worker, or torch",
        )
    )

    # 6. Dataset Manager isolation
    violations.extend(
        check_forbidden_imports(
            "dataset_manager",
            [
                "pbl4.runtime",
                "pbl4.management_backend",
                "torch",
                "torchvision",
            ],
            "dataset_manager must not import runtime internals, backend app code, or torch",
        )
    )

    # 7. Runtime isolation (framework-neutral coordinator/PS)
    violations.extend(
        check_forbidden_imports(
            "runtime",
            [
                "fastapi",
                "uvicorn",
                "starlette",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
                "pbl4.management_backend",
                "torch",
                "torchvision",
            ],
            "runtime must not import web frameworks, DB drivers, backend, or torch models",
        )
    )

    # 8. Runtime Synchronization isolation
    violations.extend(
        check_forbidden_imports(
            "runtime/synchronization",
            [
                "pbl4.runtime.checkpoint",
                "pbl4.runtime.checkpoint_policy",
                "pbl4.transport",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
                "fastapi",
                "pbl4.management_backend",
            ],
            "synchronization must not import checkpoint, transport, DB, HTTP, or backend",
        )
    )

    # 9. Management Protocol isolation (wire format only)
    violations.extend(
        check_forbidden_imports(
            "management_protocol",
            [
                "pbl4.runtime",
                "pbl4.management_backend",
                "pbl4.worker",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
                "torch",
                "torchvision",
            ],
            "management_protocol is wire format only: no runtime/backend/worker/DB/torch imports",
        )
    )

    # 10. Adapter isolation
    violations.extend(
        check_forbidden_imports(
            "adapter",
            [
                "pbl4.management_backend",
                "pbl4.dataset_manager",
                "pbl4.runtime",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "adapter is framework boundary-focused: no backend, DM, runtime, or DB imports",
        )
    )

    # 11. CLI isolation
    violations.extend(
        check_forbidden_imports(
            "cli",
            [
                "pbl4.runtime",
                "pbl4.dataset_manager",
                "pbl4.worker",
                "psycopg",
                "psycopg_pool",
                "asyncpg",
                "sqlalchemy",
            ],
            "cli must control through Management Backend: no direct runtime, DM, worker, or DB",
        )
    )

    if violations:
        print(f"Architecture check FAILED ({len(violations)} violations):", file=sys.stderr)
        for v in violations:
            print(v, file=sys.stderr)
        return 1

    print("Architecture import-boundary check PASSED: all configured package import rules passed.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
