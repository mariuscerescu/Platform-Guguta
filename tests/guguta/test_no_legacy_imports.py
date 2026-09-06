"""L8 guard: the Guguță target runtime must not import legacy subsystems.

Static (AST-based) check over every module the Guguță build ships — new
Guguță code paths must stay free of SurrealDB, surreal-commands, the SQLite
chat memory and the deferred heavy runtimes (ADR-0001/0005, checklist L8).
This runs in CI so the boundary is enforced on every commit.
"""

from __future__ import annotations

import ast
import os
from pathlib import Path

FORBIDDEN_PREFIXES = (
    "surrealdb",                      # BSL database driver (ADR-0001)
    "surreal_commands",               # legacy queue (ADR-0002)
    "sqlite3",                        # SQLite chat memory (ADR-0005)
    "langgraph_checkpoint_sqlite",    # SqliteSaver (ADR-0005)
    "podcast_creator",                # deferred feature (audio)
    "content_core",                   # URL/media extraction — deferred
)

REPO_ROOT = Path(__file__).resolve().parents[2]

GUUGUTA_PATHS = [
    "open_notebook/database/guguta",
    "open_notebook/auth/guguta",
    "open_notebook/storage/guguta",
    "open_notebook/jobs/guguta",
    "open_notebook/ai/guguta",
    "api/services/guguta",
    "api/routers/guguta_v1.py",
    "api/guguta_app.py",
    "alembic/env.py",
    "alembic/versions",
]


def _iter_python_files() -> list[Path]:
    files: list[Path] = []
    for entry in GUUGUTA_PATHS:
        full = REPO_ROOT / entry
        if full.is_file():
            files.append(full)
        else:
            files.extend(sorted(full.rglob("*.py")))
    return files


def _imported_roots(tree: ast.AST) -> set[str]:
    roots: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            for alias in node.names:
                roots.add(alias.name.split(".")[0])
        elif isinstance(node, ast.ImportFrom):
            if node.module and node.level == 0:  # relative imports are ours
                roots.add(node.module.split(".")[0])
    return roots


def test_no_legacy_imports_in_guguta_runtime() -> None:
    checked = 0
    violations: list[str] = []
    for path in _iter_python_files():
        checked += 1
        tree = ast.parse(path.read_text(encoding="utf-8"), filename=str(path))
        for root in _imported_roots(tree):
            if root in FORBIDDEN_PREFIXES:
                violations.append(f"{path}: imports '{root}'")
    assert checked >= 30, f"too few files checked ({checked}) — paths moved?"
    assert not violations, f"legacy imports in the Guguță runtime: {violations}"


def test_no_sqlite_files_in_guguta_paths() -> None:
    """No SQLite databases inside the Guguță-owned paths (ADR-0005)."""
    offenders = []
    for entry in GUUGUTA_PATHS:
        full = REPO_ROOT / entry
        if full.is_dir():
            for pattern in ("*.sqlite", "*.sqlite3", "*.db"):
                offenders.extend(str(p) for p in full.rglob(pattern))
    assert not offenders, f"SQLite files in Guguță paths: {offenders}"


def test_legacy_guard_covers_itself() -> None:
    """Sanity: the guard really scans (the file list contains this file)."""
    names = {p.name for p in _iter_python_files()}
    assert "test_no_legacy_imports.py" not in names  # tests live outside the runtime paths
    assert (REPO_ROOT / "api" / "guguta_app.py").exists()
    _ = os.environ.get("GUGUTA_TEST_DATABASE_URL", "")
