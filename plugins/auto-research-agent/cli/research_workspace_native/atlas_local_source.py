"""Raw source inventory and loader; no processes, sessions or model calls."""

import hashlib
import importlib.abc
import importlib.util
import json
import os
from pathlib import Path
import re
import stat
import sys


class LauncherError(ValueError):
    pass


def require(condition, reason):
    if not condition:
        raise LauncherError(reason)


def canonical(value):
    return json.dumps(
        value,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
        allow_nan=False,
    ).encode("utf8")


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def pairs(items):
    result = {}
    for key, value in items:
        require(key not in result, "duplicate JSON field")
        result[key] = value
    return result


def unlinked(path):
    path = Path(path)
    require(path.is_absolute(), "absolute path required")
    for parent in (path, *path.parents):
        if parent.exists():
            info = parent.lstat()
            require(
                not stat.S_ISLNK(info.st_mode)
                and not getattr(info, "st_file_attributes", 0) & 0x400,
                "links/reparse points refused",
            )
    return path


def read(path, maximum=256 * 1024):
    path = unlinked(path)
    require(stat.S_ISREG(path.stat().st_mode), "regular file required")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    require(0 < len(raw) <= maximum, "file bound exceeded")
    return raw


def pinned(path, expected, maximum=256 * 1024):
    require(
        isinstance(expected, str) and re.fullmatch("[0-9a-f]{64}", expected),
        "SHA256 pin required",
    )
    raw = read(path, maximum)
    require(digest(raw) == expected, "pinned bytes differ")
    return raw


def decode(raw):
    value = json.loads(
        raw.decode("utf8"),
        object_pairs_hook=pairs,
        parse_constant=lambda _: (_ for _ in ()).throw(
            LauncherError("nonfinite JSON refused")
        ),
    )
    canonical(value)
    require(isinstance(value, dict), "JSON object required")
    return value


def inventory(root):
    root = unlinked(root)
    require(root.is_absolute() and root.is_dir(), "inventory root required")
    files = {}
    for base, directories, names in os.walk(root, followlinks=False):
        directories[:] = sorted(
            n
            for n in directories
            if n not in {"__pycache__", ".ruff_cache", ".pytest_cache"}
        )
        for name in directories:
            item = Path(base) / name
            require(
                not item.is_symlink()
                and not getattr(item.lstat(), "st_file_attributes", 0) & 0x400,
                "linked inventory directory refused",
            )
        for name in sorted(names):
            if name.endswith((".pyc", ".pyo")):
                continue
            item = Path(base) / name
            require(len(files) < 4096, "inventory file bound exceeded")
            files[item.relative_to(root).as_posix()] = digest(
                read(item, 32 * 1024 * 1024)
            )
    return files


class PinnedLoader(importlib.abc.MetaPathFinder, importlib.abc.Loader):
    """Compile owned Python source bytes directly; never use owned cached pyc."""

    def __init__(self, repo, files):
        self.root = repo / "plugins/auto-research-agent/cli"
        self.files, self.paths = files, {}
        self.names = {
            p.name
            for p in self.root.iterdir()
            if p.is_dir() and (p / "__init__.py").is_file()
        }
        self.names |= {p.stem for p in self.root.glob("*.py")}
        require(
            not any(n.split(".")[0] in self.names for n in sys.modules),
            "owned modules already loaded; use a fresh process",
        )

    def find_spec(self, fullname, path=None, target=None):
        if fullname.split(".")[0] not in self.names:
            return None
        selected = self.root.joinpath(*fullname.split("."))
        package = selected.is_dir()
        selected = selected / "__init__.py" if package else selected.with_suffix(".py")
        require(selected.is_file(), "owned module absent")
        self.paths[fullname] = selected
        return importlib.util.spec_from_file_location(
            fullname,
            selected,
            loader=self,
            submodule_search_locations=[str(selected.parent)] if package else None,
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        path = self.paths[module.__name__]
        relative = "cli/" + path.relative_to(self.root).as_posix()
        raw = pinned(path, self.files[relative], 32 * 1024 * 1024)
        exec(compile(raw, str(path), "exec"), module.__dict__)
