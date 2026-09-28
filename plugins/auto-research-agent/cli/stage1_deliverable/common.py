"""Strict file and record boundaries shared by export and semantic replay."""

import hashlib
import json
import os
import re
import stat
import subprocess
from pathlib import Path, PurePosixPath


class DeliverableError(ValueError):
    """A missing or inconsistent package input blocks export."""


def canonical(value):
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def sha(data):
    return hashlib.sha256(data).hexdigest()


def read_json(path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DeliverableError("duplicate JSON key: " + key)
            result[key] = value
        return result

    return json.loads(Path(path).read_bytes(), object_pairs_hook=unique)


def write_json(path, value):
    Path(path).write_bytes(canonical(value) + b"\n")


def safe_path(root, name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        raise DeliverableError("unsafe artifact path")
    parts = PurePosixPath(name)
    if parts.is_absolute() or any(p in {"", ".", ".."} for p in name.split("/")):
        raise DeliverableError("unsafe artifact path")
    for part in name.split("/"):
        if (
            part.endswith((".", " "))
            or part.split(".")[0].upper()
            in {
                "CON",
                "PRN",
                "AUX",
                "NUL",
                *(f"COM{i}" for i in range(10)),
                *(f"LPT{i}" for i in range(10)),
            }
            or any(ord(char) < 32 or char in '<>"|?*' for char in part)
        ):
            raise DeliverableError("unsafe Windows artifact component")
    reject_links(root)
    root = Path(root).resolve()
    path = root
    for part in parts.parts:
        path = path / part
        reject_links(path)
    if not path.resolve().is_relative_to(root):
        raise DeliverableError("artifact escaped root")
    return path


def reject_links(path):
    for item in (Path(path).absolute(), *Path(path).absolute().parents):
        try:
            info = os.lstat(item)
        except FileNotFoundError:
            continue
        if stat.S_ISLNK(info.st_mode) or getattr(info, "st_file_attributes", 0) & 0x400:
            raise DeliverableError(
                "linked artifact or Windows reparse point is not allowed"
            )


def private_output(path):
    path = Path(path).absolute()
    reject_links(path)
    for parent in (path, *path.parents):
        if parent.is_symlink() or (parent / ".git").exists():
            raise DeliverableError(
                "private package must be outside a Git checkout and links"
            )
    probe = subprocess.run(
        ["git", "-C", str(path.parent), "rev-parse", "--show-toplevel"],
        capture_output=True,
        check=False,
    )
    if probe.returncode == 0:
        raise DeliverableError("private package cannot be inside Git")
    return path


def identifier(value):
    if not isinstance(value, str) or not re.fullmatch(
        r"[A-Za-z0-9][A-Za-z0-9._-]{0,119}", value
    ):
        raise DeliverableError("unsafe or missing record ID")
    return value


def inventory(root):
    files = {}
    for path in Path(root).rglob("*"):
        relative = path.relative_to(root).as_posix()
        safe_path(root, relative)
        if path.is_file() and relative != "provenance_manifest.json":
            files[relative] = sha(path.read_bytes())
    return dict(sorted(files.items()))
