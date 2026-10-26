"""Versioned affected-suite routing; unknown inputs retain the broad runner."""

from fnmatch import fnmatchcase
import hashlib
import json
from pathlib import Path, PurePosixPath
import re


CATALOG_PATH = ".github/ci-test-routing.v1.json"
TEST_DIRECTORY = "plugins/auto-research-agent/tests"
ROUTING_FILES = {
    CATALOG_PATH,
    ".github/scripts/ci_test_routing.py",
}


def _unique_object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate CI routing field")
        result[key] = value
    return result


def _strings(value, maximum):
    if (
        not isinstance(value, list)
        or not 1 <= len(value) <= maximum
        or any(not isinstance(item, str) or not item for item in value)
        or len(set(value)) != len(value)
    ):
        raise ValueError("Invalid or duplicate CI routing list")
    return value


def load_catalog(repo):
    """Read the closed, bounded table; absence cannot enable a narrow suite."""
    path = Path(repo) / CATALOG_PATH
    if not path.exists():
        return None
    if path.is_symlink() or not path.is_file() or path.stat().st_size > 65536:
        raise ValueError("Invalid CI routing catalog file")
    raw = path.read_bytes()
    if len(raw) > 65536:
        raise ValueError("CI routing catalog is too large")
    value = json.loads(raw.decode("utf8"), object_pairs_hook=_unique_object)
    if (
        not isinstance(value, dict)
        or set(value) != {"schema_version", "routes"}
        or type(value["schema_version"]) is not int
        or value["schema_version"] != 1
        or not isinstance(value["routes"], list)
        or not 1 <= len(value["routes"]) <= 64
    ):
        raise ValueError("Invalid CI routing catalog schema")
    ids, owners = set(), set()
    for route in value["routes"]:
        if not isinstance(route, dict) or set(route) != {
            "id",
            "owners",
            "test_patterns",
        }:
            raise ValueError("Invalid CI route fields")
        name = route["id"]
        if not isinstance(name, str) or not re.fullmatch(r"[a-z][a-z0-9-]{0,63}", name):
            raise ValueError("Invalid CI route ID")
        if name in ids:
            raise ValueError("Duplicate CI route ID")
        ids.add(name)
        for owner in _strings(route["owners"], 64):
            parts = PurePosixPath(owner).parts
            if (
                not owner.startswith("plugins/auto-research-agent/cli/")
                or not re.fullmatch(r"[A-Za-z0-9_./-]+", owner)
                or ".." in parts
                or PurePosixPath(owner).as_posix() != owner
                or "." in owner.split("/")
                or owner in owners
                or PurePosixPath(owner).suffix not in {".py", ".js", ".css", ".html"}
            ):
                raise ValueError("Unsafe or duplicate CI route owner")
            owners.add(owner)
        for pattern in _strings(route["test_patterns"], 32):
            if not re.fullmatch(r"test_[A-Za-z0-9_*]+\.py", pattern):
                raise ValueError("Unsafe CI test pattern")
    return {"routes": value["routes"], "sha256": hashlib.sha256(raw).hexdigest()}


def routed_modules(path, repo, records):
    """Only a known regular-file modification may select a declared test domain."""
    catalog = load_catalog(repo)
    if catalog is None:
        return None
    route = next((row for row in catalog["routes"] if path in row["owners"]), None)
    if route is None:
        return None
    if not isinstance(records, list) or any(
        not isinstance(row, dict) for row in records
    ):
        return None
    matches = [
        row
        for row in (records or [])
        if row.get("old_path") == path or row.get("new_path") == path
    ]
    if len(matches) != 1:
        return None
    row = matches[0]
    if (
        row.get("status") != "M"
        or row.get("old_path") != path
        or row.get("new_path") != path
        or row.get("old_mode") != "100644"
        or row.get("new_mode") != "100644"
        or any(
            not isinstance(row.get(key), str)
            or not re.fullmatch(r"[0-9a-f]{40}", row[key])
            or row[key] == "0" * 40
            for key in ("old_sha", "new_sha")
        )
        or row["old_sha"] == row["new_sha"]
        or (Path(repo) / path).is_symlink()
    ):
        return None
    tests = sorted((Path(repo) / TEST_DIRECTORY).glob("test_*.py"))
    modules = set()
    for pattern in route["test_patterns"]:
        found = [test.stem for test in tests if fnmatchcase(test.name, pattern)]
        if not found:
            raise ValueError(f"CI route {route['id']} has no tests for {pattern}")
        modules.update(found)
    return {
        "id": route["id"],
        "catalog_sha256": catalog["sha256"],
        "modules": sorted(modules),
    }
