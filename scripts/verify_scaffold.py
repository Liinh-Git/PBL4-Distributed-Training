#!/usr/bin/env python3
"""PBL4 Scaffold Verifier.

Performs static bootstrap-level sanity checks on the repository:
1. Verifies required directory structure and core files exist.
2. Checks that all Python source files compile cleanly.
3. Invokes the standalone architecture constraint checker.
4. Verifies pyproject.toml does not contain forbidden dependencies.

Usage:
    python scripts/verify_scaffold.py
"""

from __future__ import annotations

import compileall
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src" / "pbl4"
SCRIPTS_DIR = ROOT_DIR / "scripts"

REQUIRED_PATHS: list[str] = [
    "AGENTS.md",
    "README.md",
    "CONTRIBUTING.md",
    ".editorconfig",
    ".gitattributes",
    ".node-version",
    "pyproject.toml",
    "docs/IMPLEMENTATION_CONTRACT.md",
    "docs/OPEN_ISSUES.md",
    "migrations/README.md",
    "tests/README.md",
    "scripts/check_architecture.py",
    "scripts/run_local_cluster.py",
    "scripts/verify_scaffold.py",
    # Source packages
    "src/pbl4/__init__.py",
    "src/pbl4/common",
    "src/pbl4/protocol",
    "src/pbl4/transport",
    "src/pbl4/runtime",
    "src/pbl4/worker",
    "src/pbl4/adapter",
    "src/pbl4/dataset_manager",
    "src/pbl4/management_backend",
    "src/pbl4/management_protocol",
    "src/pbl4/cli",
    # Dedicated entrypoints
    "src/pbl4/runtime/entrypoint.py",
    "src/pbl4/worker/entrypoint.py",
    "src/pbl4/dataset_manager/entrypoint.py",
    "src/pbl4/management_backend/entrypoint.py",
    "src/pbl4/cli/pblctl.py",
    # 5 nested AGENTS.md files
    "src/pbl4/protocol/AGENTS.md",
    "src/pbl4/runtime/AGENTS.md",
    "src/pbl4/management_backend/AGENTS.md",
    "src/pbl4/dataset_manager/AGENTS.md",
    "web/AGENTS.md",
    # Seven renamed skills
    ".agents/skills/architecture-guard/SKILL.md",
    ".agents/skills/protocol-change/SKILL.md",
    ".agents/skills/contract-change/SKILL.md",
    ".agents/skills/distributed-debug/SKILL.md",
    ".agents/skills/distributed-verification/SKILL.md",
    ".agents/skills/doc-sync/SKILL.md",
    ".agents/skills/release-gate/SKILL.md",
    # Web UI canonical top-level directories
    "web/package.json",
    "web/src/api",
    "web/src/app",
    "web/src/components",
    "web/src/domain",
    "web/src/features",
    "web/src/live",
    "web/src/pages",
    "web/src/strategies",
]

PROHIBITED_PATHS: list[str] = [
    "src/pbl4/backend",
    ".agents/skills/pbl4-architecture-guard",
    ".agents/skills/pbl4-protocol-change",
    ".agents/skills/pbl4-contract-change",
    ".agents/skills/pbl4-distributed-debug",
    ".agents/skills/pbl4-distributed-verification",
    ".agents/skills/pbl4-doc-sync",
    ".agents/skills/pbl4-release-gate",
]

FORBIDDEN_GLOBAL_DEPENDENCIES: list[str] = [
    "asyncpg",
    "structlog",
]

FORBIDDEN_RUNTIME_DEPENDENCIES: list[str] = [
    "sqlalchemy",
    "alembic",
    "asyncpg",
    "structlog",
]

# Explicit whitelists for migration tooling declarations
WHITELISTED_MIGRATION_TOOLING_EXTRAS: set[str] = {
    "management-backend",
}

WHITELISTED_MIGRATION_TOOLING_GROUPS: set[str] = {
    "dev",
}


def check_required_paths() -> bool:
    """Verify that expected repository files and directories exist."""
    missing: list[str] = []
    for rel_path in REQUIRED_PATHS:
        full_path = ROOT_DIR.joinpath(*rel_path.split("/"))
        if not full_path.exists():
            missing.append(rel_path)

    if missing:
        print(f"[FAIL] Missing required paths ({len(missing)}):", file=sys.stderr)
        for p in missing:
            print(f"  - {p}", file=sys.stderr)
        return False

    print("[PASS] All required repository structural paths exist.")
    return True


def check_prohibited_paths() -> bool:
    """Verify that obsolete paths do not exist."""
    found: list[str] = []
    for rel_path in PROHIBITED_PATHS:
        full_path = ROOT_DIR.joinpath(*rel_path.split("/"))
        if full_path.exists():
            found.append(rel_path)

    if found:
        print(f"[FAIL] Found prohibited obsolete paths ({len(found)}):", file=sys.stderr)
        for p in found:
            print(f"  - {p}", file=sys.stderr)
        return False

    print("[PASS] No prohibited obsolete paths found.")
    return True


def check_python_compilation() -> bool:
    """Check that all Python files compile without syntax errors."""
    success = compileall.compile_dir(str(SRC_DIR), quiet=1)
    if not success:
        print("[FAIL] Python compilation failed in src/pbl4", file=sys.stderr)
        return False

    success_scripts = compileall.compile_dir(str(SCRIPTS_DIR), quiet=1)
    if not success_scripts:
        print("[FAIL] Python compilation failed in scripts/", file=sys.stderr)
        return False

    print("[PASS] All Python sources in src/ and scripts/ compile cleanly.")
    return True


def check_architecture() -> bool:
    """Run standalone architecture checker."""
    proc = subprocess.run(
        [sys.executable, str(SCRIPTS_DIR / "check_architecture.py")],
        capture_output=True,
        text=True,
    )
    if proc.returncode != 0:
        print("[FAIL] Architecture constraint check failed:", file=sys.stderr)
        print(proc.stderr, file=sys.stderr)
        return False

    print("[PASS] Architecture boundary checks passed.")
    return True


def check_pyproject_dependencies() -> bool:
    """Verify that pyproject.toml respects architectural dependency boundaries."""
    pyproject_path = ROOT_DIR / "pyproject.toml"
    if not pyproject_path.exists():
        print("[FAIL] pyproject.toml not found", file=sys.stderr)
        return False

    try:
        data = tomllib.loads(pyproject_path.read_text(encoding="utf-8"))
    except Exception as e:
        print(f"[FAIL] Error parsing pyproject.toml: {e}", file=sys.stderr)
        return False

    found_forbidden: list[str] = []

    # 1. Base project dependencies must not declare runtime forbidden dependencies
    base_deps = data.get("project", {}).get("dependencies", [])
    for dep in base_deps:
        dep_lower = dep.lower()
        for forbidden in FORBIDDEN_RUNTIME_DEPENDENCIES:
            if forbidden in dep_lower:
                found_forbidden.append(f"{forbidden} (found in base dependency '{dep}')")

    # 2. Check optional dependencies: ONLY whitelisted extras can declare migration tooling
    for extra, deps in data.get("project", {}).get("optional-dependencies", {}).items():
        if extra in WHITELISTED_MIGRATION_TOOLING_EXTRAS:
            for dep in deps:
                dep_lower = dep.lower()
                for forbidden in FORBIDDEN_GLOBAL_DEPENDENCIES:
                    if forbidden in dep_lower:
                        found_forbidden.append(f"{forbidden} (found in extra '{extra}': '{dep}')")
        else:
            # All other extras (worker, runtime, dataset-manager, cli,
            # adapter, etc.) are strictly forbidden
            for dep in deps:
                dep_lower = dep.lower()
                for forbidden in FORBIDDEN_RUNTIME_DEPENDENCIES:
                    if forbidden in dep_lower:
                        found_forbidden.append(
                            f"{forbidden} "
                            f"(found in non-persistence extra '{extra}': '{dep}')"
                        )

    # 3. Check dependency groups: ONLY whitelisted groups can declare migration tooling
    for group, deps in data.get("dependency-groups", {}).items():
        if group in WHITELISTED_MIGRATION_TOOLING_GROUPS:
            for dep in deps:
                dep_lower = dep.lower()
                for forbidden in FORBIDDEN_GLOBAL_DEPENDENCIES:
                    if forbidden in dep_lower:
                        found_forbidden.append(f"{forbidden} (found in group '{group}': '{dep}')")
        else:
            for dep in deps:
                dep_lower = dep.lower()
                for forbidden in FORBIDDEN_RUNTIME_DEPENDENCIES:
                    if forbidden in dep_lower:
                        found_forbidden.append(f"{forbidden} (found in group '{group}': '{dep}')")

    if found_forbidden:
        print("[FAIL] Found forbidden dependencies in pyproject.toml:", file=sys.stderr)
        for item in found_forbidden:
            print(f"  - {item}", file=sys.stderr)
        return False

    print("[PASS] No forbidden dependencies declared in pyproject.toml.")
    return True


def main() -> int:
    """Run all scaffold checks."""
    print("Running PBL4 bootstrap scaffold verification...")
    checks = [
        check_required_paths,
        check_prohibited_paths,
        check_python_compilation,
        check_architecture,
        check_pyproject_dependencies,
    ]

    all_passed = True
    for check in checks:
        if not check():
            all_passed = False

    if not all_passed:
        print("\nScaffold verification FAILED.", file=sys.stderr)
        return 1

    print("\nScaffold verification PASSED: Repository layout and constraints are clean.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
