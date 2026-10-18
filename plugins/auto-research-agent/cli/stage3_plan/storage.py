"""Bounded, private, write-once plan evidence; no research execution."""

import hashlib
import json
import os
from pathlib import Path
import stat

from .contracts import Stage3Error, canonical_bytes, digest

MAX_ARTIFACT_BYTES = 2_000_000


def safe_path(value):
    path = Path(os.path.abspath(value))
    for component in (path, *path.parents):
        if component.exists() or component.is_symlink():
            info = component.lstat()
            if (
                stat.S_ISLNK(info.st_mode)
                or getattr(info, "st_file_attributes", 0) & 0x400
            ):
                raise Stage3Error(f"linked/reparse evidence path: {component}")
    return path


def private_output(value):
    path = safe_path(value)
    if any((parent / ".git").exists() for parent in (path, *path.parents)):
        raise Stage3Error("private planning evidence must stay outside Git checkouts")
    return path


def read_bytes(value):
    path = safe_path(value)
    if not path.is_file() or path.stat().st_size > MAX_ARTIFACT_BYTES:
        raise Stage3Error(f"artifact missing, nonregular or over bounded size: {path}")
    with path.open("rb") as handle:
        raw = handle.read(MAX_ARTIFACT_BYTES + 1)
    if len(raw) > MAX_ARTIFACT_BYTES:
        raise Stage3Error("artifact grew beyond limit")
    return raw


def read_json(value):
    try:

        def unique(pairs):
            result = {}
            for key, item in pairs:
                if key in result:
                    raise ValueError(f"duplicate key: {key}")
                result[key] = item
            return result

        return json.loads(
            read_bytes(value),
            object_pairs_hook=unique,
            parse_constant=lambda value: (_ for _ in ()).throw(ValueError(value)),
        )
    except (ValueError, UnicodeError) as error:
        raise Stage3Error(f"invalid JSON: {value}: {error}") from error


def write_new(path, value, *, raw=False):
    path = safe_path(path)
    data = value if raw else canonical_bytes(value)
    if len(data) > MAX_ARTIFACT_BYTES:
        raise Stage3Error("artifact exceeds bounded size")
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())


def publish_manifest(root, names, *, request_sha256, state):
    rows = [
        {"path": name, "sha256": hashlib.sha256(read_bytes(root / name)).hexdigest()}
        for name in sorted(names)
    ]
    value = {
        "kind": "Stage3PlanManifest",
        "schema_version": "1.0.0",
        "request_sha256": request_sha256,
        "state": state,
        "files": rows,
        "execution_authorized": False,
    }
    value["manifest_sha256"] = digest(value)
    write_new(root / "manifest.json", value)
    return value


def inspect_package(root, expected_manifest_sha256):
    root = safe_path(root)
    manifest = read_json(root / "manifest.json")
    if (
        not isinstance(manifest, dict)
        or set(manifest)
        != {
            "kind",
            "schema_version",
            "request_sha256",
            "state",
            "files",
            "execution_authorized",
            "manifest_sha256",
        }
        or manifest.get("state") not in {"draft", "needs-information", "failed"}
        or not isinstance(manifest.get("files"), list)
        or any(
            not isinstance(row, dict)
            or set(row) != {"path", "sha256"}
            or not isinstance(row["path"], str)
            for row in manifest["files"]
        )
    ):
        raise Stage3Error("invalid plan manifest shape")
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        manifest.get("kind") != "Stage3PlanManifest"
        or manifest.get("schema_version") != "1.0.0"
        or manifest.get("execution_authorized") is not False
        or manifest.get("manifest_sha256") != expected_manifest_sha256
        or digest(unsigned) != expected_manifest_sha256
    ):
        raise Stage3Error("plan manifest external binding mismatch")
    names = [row["path"] for row in manifest["files"]]
    if len(set(names)) != len(names) or any(
        Path(name).name != name
        or any(c in name for c in ":/\\")
        or name in {"", ".", "..", "manifest.json"}
        for name in names
    ):
        raise Stage3Error("invalid plan inventory")
    if {p.name for p in root.iterdir()} != set(names) | {"manifest.json"}:
        raise Stage3Error("plan inventory mismatch or incomplete attempt")
    values = {}
    for row in manifest["files"]:
        raw = read_bytes(root / row["path"])
        if hashlib.sha256(raw).hexdigest() != row["sha256"]:
            raise Stage3Error("plan artifact hash mismatch")
        if row["path"].endswith(".json") and row["path"] != "raw-response.json":
            values[row["path"]] = read_json(root / row["path"])
    request = values.get("request.json")
    if request is None or digest(request) != manifest["request_sha256"]:
        raise Stage3Error("plan request binding mismatch")
    generation = values.get("generation.json", {})
    if generation.get("kind") == "Stage3PlanningGeneration":
        from .native import verify_native_generation

        verify_native_generation(root, generation)
    return {"manifest": manifest, "artifacts": values}
