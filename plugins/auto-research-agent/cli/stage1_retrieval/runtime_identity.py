"""Bind a Python entry point to its code bytes, independently of build labels."""

import json
import os
from pathlib import Path
import re
import subprocess
from concurrent.futures import ThreadPoolExecutor

from stage1_ledger.journal import LedgerError, canonical, digest


def absolute(value):
    path = Path(value)
    if not path.is_absolute() or not path.is_file():
        raise LedgerError("runtime-code-path-must-be-absolute-file: " + str(value))
    return path.resolve()


def inspect_python(prefix):
    """Use the pinned interpreter's public import paths, without importing the CLI."""
    absolute(prefix[0])
    if prefix[1:3] != ["-I", "-B"]:
        raise LedgerError("runtime-requires-isolated-python-and-no-bytecode-writes")
    args = prefix[3:]
    if len(args) == 1:
        entry = absolute(args[0])
        mode, module = "script", None
    elif len(args) == 2 and args[0] == "-m" and re.fullmatch(r"[A-Za-z_]\w*", args[1]):
        entry, mode, module = None, "module", args[1]
    else:
        raise LedgerError("runtime-prefix-must-name-one-script-or-top-level-module")
    probe = (
        "import json,sys,importlib.machinery; "
        "s=importlib.machinery.PathFinder.find_spec(sys.argv[1],sys.path) if sys.argv[1] else None; "
        "print(json.dumps({'paths':sys.path,'origin':s.origin if s else None,'package':list(s.submodule_search_locations or []) if s else []}))"
    )
    try:
        result = subprocess.run(
            [prefix[0], "-I", "-B", "-c", probe, module or ""],
            capture_output=True,
            check=True,
            timeout=30,
            encoding="utf-8",
        )
        info = json.loads(result.stdout)
    except (OSError, ValueError, subprocess.SubprocessError) as error:
        raise LedgerError("runtime-import-path-probe-failed") from error
    if mode == "module":
        if not info["origin"]:
            raise LedgerError("runtime-module-not-found")
        entry = absolute(info["origin"])
    return mode, str(entry), info


def tree_files(root, *, code_only=False):
    """Include executable/cache bytes and detect additions, not just old filenames."""
    root = Path(root)
    if not root.is_absolute():
        raise LedgerError("runtime-root-not-absolute")
    if root.is_file():
        return {str(root.resolve()): digest(root.read_bytes())}
    if not root.is_dir():
        raise LedgerError("runtime-code-root-missing: " + str(root))
    paths = []
    for folder, dirs, names in os.walk(root, followlinks=False):
        # A stdlib root may contain an inactive global installation. The active
        # environment's site-packages is inventoried separately from sys.path.
        dirs[:] = [
            d
            for d in dirs
            if d not in {".git", ".pytest_cache", ".ruff_cache"}
            and d not in {"site-packages", "dist-packages"}
        ]
        for directory in dirs:
            if (Path(folder) / directory).is_symlink():
                raise LedgerError("runtime-code-symlink-directory")
        for name in names:
            path = Path(folder) / name
            if code_only and path.suffix.lower() not in {
                ".py",
                ".pyw",
                ".pyc",
                ".pyd",
                ".so",
                ".dll",
                ".zip",
                ".pth",
            }:
                continue
            if path.is_symlink():
                raise LedgerError("runtime-code-symlink-file")
            paths.append(path)

    def hash_file(path):
        return str(path.resolve()), digest(path.read_bytes())

    with ThreadPoolExecutor(max_workers=8) as workers:
        return dict(workers.map(hash_file, paths))


def capture_identity(prefix):
    mode, entry, info = inspect_python(prefix)
    roots = {
        str(Path(p).resolve()): False for p in info["paths"] if p and Path(p).exists()
    }
    if mode == "script":
        roots.setdefault(str(Path(entry).parent), True)
    # Venv selection changes import resolution even when python itself is a symlink.
    venv_config = Path(prefix[0]).parent.parent / "pyvenv.cfg"
    if venv_config.is_file():
        roots[str(venv_config.resolve())] = False
    # Avoid hashing overlapping interpreter roots several times. Active package
    # directories remain separate because tree_files excludes nested installations.
    roots = {
        p: code_only
        for p, code_only in roots.items()
        if not any(
            p != parent
            and not parent_code_only
            and Path(p).is_relative_to(Path(parent))
            and not {"site-packages", "dist-packages"}.intersection(
                Path(p).relative_to(Path(parent)).parts
            )
            for parent, parent_code_only in roots.items()
        )
    }
    files = {str(absolute(prefix[0])): digest(Path(prefix[0]).read_bytes())}
    for root, code_only in roots.items():
        files.update(tree_files(root, code_only=code_only))
    if entry not in files:
        raise LedgerError("runtime-entry-not-in-inventory")
    return dict(
        scope="isolated-python-import-paths-and-entry-tree",
        mode=mode,
        argv_prefix=prefix,
        entry=entry,
        roots=roots,
        files=files,
        absent_paths=[
            str(Path(p).resolve()) for p in info["paths"] if p and not Path(p).exists()
        ],
        files_sha256=digest(canonical(files)),
    )


def verify_identity(pin, *, probe=False):
    identity = pin.get("code_identity")
    if not identity:
        raise LedgerError("runtime-code-identity-required")
    files = identity["files"]
    if digest(canonical(files)) != identity["files_sha256"]:
        raise LedgerError("runtime-code-inventory-hash")
    prefix = pin["argv_prefix"]
    if identity["argv_prefix"] != prefix or any(
        Path(p).exists() for p in identity["absent_paths"]
    ):
        raise LedgerError("runtime-import-resolution-changed")
    if prefix[1:3] != ["-I", "-B"]:
        raise LedgerError("runtime-requires-isolated-python-and-no-bytecode-writes")
    executable = str(absolute(prefix[0]))
    actual = {executable: digest(Path(executable).read_bytes())}
    for root, code_only in identity["roots"].items():
        actual.update(tree_files(root, code_only=code_only))
    if actual != files:
        changed = sorted(
            k for k in set(actual) | set(files) if actual.get(k) != files.get(k)
        )
        raise LedgerError("runtime-code-changed: " + ", ".join(changed[:3]))
    args = prefix[3:]
    if identity["mode"] == "script":
        if len(args) != 1 or str(absolute(args[0])) != identity["entry"]:
            raise LedgerError("runtime-entry-mismatch")
    elif (
        len(args) != 2 or args[0] != "-m" or not re.fullmatch(r"[A-Za-z_]\w*", args[1])
    ):
        raise LedgerError("runtime-entry-mismatch")
    if (
        identity["entry"] not in files
        or files.get(executable) != pin["executable_sha256"]
    ):
        raise LedgerError("runtime-entry-not-in-inventory")
    if probe:
        # Recheck import resolution before launch; replay itself starts no process.
        fresh = capture_identity(prefix)
        if fresh != identity:
            raise LedgerError("runtime-import-resolution-changed")
