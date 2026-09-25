"""Bind evaluator executables and installed Python source bytes."""

import importlib.util
import re
import subprocess
from pathlib import Path

from .common import EvaluationError, sha


def executable_sha256(path):
    target = Path(path).resolve()
    if not target.is_file():
        raise EvaluationError(f"runtime executable is missing: {target}")
    return sha(target.read_bytes())


def python_tree_sha256(root):
    root = Path(root).resolve()
    files = sorted(root.rglob("*.py"))
    if not files:
        raise EvaluationError(f"Python package tree is missing: {root}")
    raw = b"".join(
        path.relative_to(root).as_posix().encode("utf-8")
        + b"\0"
        + sha(path.read_bytes()).encode("ascii")
        + b"\n"
        for path in files
    )
    return sha(raw)


def installed_package_sha256(module_name):
    spec = importlib.util.find_spec(module_name)
    if spec is None or spec.origin is None:
        raise EvaluationError(f"installed dependency is missing: {module_name}")
    return python_tree_sha256(Path(spec.origin).parent)


def require_expected(actual, expected, label):
    if not isinstance(expected, str) or len(expected) != 64 or actual != expected:
        raise EvaluationError(f"{label} SHA-256 differs from the frozen expected value")


def verify_installed_from_commit(repo, commit, module_name="research_hub"):
    repo = Path(repo).resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise EvaluationError("dependency commit must be a full lowercase Git SHA")
    head = subprocess.run(
        ["git", "-C", str(repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        check=False,
    )
    dirty = subprocess.run(
        ["git", "-C", str(repo), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        check=False,
    )
    if (
        head.returncode
        or dirty.returncode
        or head.stdout.strip() != commit
        or dirty.stdout.strip()
    ):
        raise EvaluationError("dependency checkout is not the clean declared commit")
    source_hash = python_tree_sha256(repo / "src" / module_name)
    installed_hash = installed_package_sha256(module_name)
    require_expected(installed_hash, source_hash, "installed dependency")
    return {"commit": commit, "python_source_sha256": source_hash}
