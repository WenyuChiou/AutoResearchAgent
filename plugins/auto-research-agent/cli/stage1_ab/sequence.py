"""Persistent, fail-closed ordering for Stage 1 subject captures."""

import json
import os
from pathlib import Path
from contextlib import contextmanager


def registry_path(preflight_path):
    return Path(preflight_path).with_suffix(".sequence.json")


def expected_runs(lock):
    rows = lock["paired_repeats"]
    if not rows or len(rows) not in (1, 3):
        raise ValueError("sequence requires one pilot pair or three formal pairs")
    expected_orders = [
        ["baseline", "treatment"],
        ["treatment", "baseline"],
        ["baseline", "treatment"],
    ]
    result = []
    for index, row in enumerate(rows):
        if row["repeat"] != index + 1 or row["order"] != expected_orders[index]:
            raise ValueError("paired order differs from frozen B/T sequence")
        for condition in row["order"]:
            run = row[condition]
            result.append(
                {
                    "repeat": row["repeat"],
                    "condition": condition,
                    "run_id": run["run_id"],
                    "subject_id": run["subject_id"],
                }
            )
    if len({row["run_id"] for row in result}) != len(result):
        raise ValueError("duplicate run ID in frozen sequence")
    return result


def create(lock, lock_path, preflight_path, sha):
    path = registry_path(preflight_path)
    value = {
        "kind": "Stage1ABSequenceRegistry",
        "lock_sha256": sha(Path(lock_path).read_bytes()),
        "preflight_sha256": sha(Path(preflight_path).read_bytes()),
        "runs": expected_runs(lock),
        "next_index": 0,
        "active": None,
        "completed": [],
    }
    path.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
        errors="strict",
        newline="\n",
    )
    return path


def save(path, value):
    temp = Path(str(path) + ".tmp")
    if temp.exists():
        raise ValueError("unfinished sequence registry write")
    temp.write_text(
        json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    os.replace(temp, path)


@contextmanager
def exclusive(path):
    lock = Path(str(path) + ".busy")
    lock.mkdir()
    try:
        yield
    finally:
        lock.rmdir()


def verify(path, lock, lock_path, preflight_path, sha, verify_capture):
    path = Path(path)
    value = json.loads(path.read_text(encoding="utf-8"))
    runs = expected_runs(lock)
    if (
        value.get("kind") != "Stage1ABSequenceRegistry"
        or value.get("lock_sha256") != sha(Path(lock_path).read_bytes())
        or value.get("preflight_sha256") != sha(Path(preflight_path).read_bytes())
        or value.get("runs") != runs
    ):
        raise ValueError("sequence registry differs from frozen plan or preflight")
    index = value.get("next_index")
    completed = value.get("completed")
    if (
        not isinstance(index, int)
        or not 0 <= index <= len(runs)
        or not isinstance(completed, list)
        or len(completed) != index
    ):
        raise ValueError("sequence registry index is invalid")
    for ordinal, item in enumerate(completed):
        if item.get("run_id") != runs[ordinal]["run_id"]:
            raise ValueError("completed sequence differs from frozen plan")
        output = Path(item["output"])
        record = verify_capture(output)
        if (
            record.get("status") != "complete"
            or record.get("run_id") != item["run_id"]
            or sha((output / "run.json").read_bytes()) != item["run_sha256"]
        ):
            raise ValueError("prior subject is incomplete or changed")
    active = value.get("active")
    if active is not None and (
        index >= len(runs)
        or active.get("run_id") != runs[index]["run_id"]
        or not Path(active["output"]).is_absolute()
    ):
        raise ValueError("active sequence reservation is invalid")
    return value
