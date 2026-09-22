"""Read the versioned public audit contract; no research-hub Python imports."""

from datetime import datetime
from functools import lru_cache
from pathlib import Path

from jsonschema import Draft202012Validator, FormatChecker

from stage1_ledger.journal import LedgerError, contained, decode, digest


@lru_cache(maxsize=1)
def schema_validator():
    path = (
        Path(__file__).resolve().parents[2]
        / "schemas/research-hub-audit.v1.schema.json"
    )
    schema = decode(path.read_bytes(), str(path))
    return Draft202012Validator(schema, format_checker=FormatChecker())


def require(condition, reason):
    if not condition:
        raise LedgerError("hub-audit:" + reason)


def checked(value):
    errors = list(schema_validator().iter_errors(value))
    if errors:
        raise LedgerError("hub-audit:schema:" + errors[0].message)
    return value


def read_audit(
    directory=None, *, saved=None, limit=16 * 1024 * 1024, total_limit=128 * 1024 * 1024
):
    """Validate a sealed invocation and return exact referenced bytes and events."""
    root = Path(directory).resolve() if directory is not None else None
    files = {}

    def read(name):
        if name not in files:
            if saved is None:
                path = contained(root, name)
                require(path.stat().st_size <= limit, "file-size-limit:" + name)
                raw = path.read_bytes()
            else:
                require(name in saved, "missing-file:" + name)
                raw = saved[name]
            require(len(raw) <= limit, "file-size-limit:" + name)
            require(
                sum(map(len, files.values())) + len(raw) <= total_limit,
                "total-size-limit",
            )
            files[name] = raw
        return files[name]

    def reference(ref):
        raw = read(ref["path"])
        require(len(raw) == ref["bytes"], "byte-count:" + ref["path"])
        require(digest(raw) == ref["sha256"], "hash:" + ref["path"])
        return raw

    manifest = checked(decode(read("audit_manifest.json"), "audit_manifest.json"))
    require(manifest["type"] == "audit_manifest", "manifest-type")
    require(manifest["complete"], "incomplete-manifest")
    require(manifest["events"]["path"] == "events.jsonl", "events-path")
    raw = reference(manifest["events"])
    require(raw.endswith(b"\n"), "incomplete-events-tail")
    events, starts, finishes = [], {}, {}
    previous = None
    for sequence, line in enumerate(raw.splitlines(), 1):
        event = checked(decode(line, f"events.jsonl:{sequence}"))
        require(event["type"] == "audit_event", "event-type")
        require(event["sequence"] == sequence, "sequence")
        current = datetime.fromisoformat(event["timestamp"].replace("Z", "+00:00"))
        require(current.utcoffset() is not None, "timestamp-zone")
        require(previous is None or current >= previous, "timestamp-order")
        previous = current
        identifier = event["attempt_id"]
        if event["event"] == "started":
            require(identifier not in starts, "duplicate-start")
            parent = event["parent_id"]
            require(
                parent is None or (parent in starts and parent not in finishes),
                "parent-not-open",
            )
            starts[identifier] = event
        else:
            start = starts.get(identifier)
            require(
                start is not None and identifier not in finishes,
                "finish-without-open-start",
            )
            for key in ("operation", "backend", "parent_id"):
                require(event[key] == start[key], "changed-attempt:" + key)
            # HTTP finish parameters add observed redirects/response headers.
            for key, value in start["parameters"].items():
                require(
                    event["parameters"].get(key) == value, "changed-parameter:" + key
                )
            require(
                not any(
                    s["parent_id"] == identifier and i not in finishes
                    for i, s in starts.items()
                ),
                "unfinished-child",
            )
            for ref in event["artifacts"]:
                reference(ref)
            finishes[identifier] = event
        events.append(event)
    require(len(events) == manifest["event_count"], "event-count")
    require(starts.keys() == finishes.keys(), "unfinished-attempts")
    roots = [i for i, e in starts.items() if e["parent_id"] is None]
    require(roots == [manifest["command_id"]], "command-root")
    command = finishes[manifest["command_id"]]
    require(command["outcome"] == manifest["outcome"], "command-outcome")
    created = datetime.fromisoformat(manifest["created_at"].replace("Z", "+00:00"))
    require(created.utcoffset() is not None and created >= previous, "manifest-time")
    return {
        "manifest": manifest,
        "events": events,
        "starts": starts,
        "finishes": finishes,
        "files": files,
    }


def descendants(audit, identifier):
    selected = {identifier}
    for event in audit["events"]:
        if event["parent_id"] in selected:
            selected.add(event["attempt_id"])
    return [
        event for event in audit["finishes"].values() if event["attempt_id"] in selected
    ]


def result_records(audit, event, *, single=False):
    """Return saved pre-merge result objects; their bibliographic truth is unknown."""
    refs = [r for r in event["artifacts"] if r["path"].endswith(".json")]
    require(len(refs) == 1, "one-result-artifact-required")
    value = decode(audit["files"][refs[0]["path"]], refs[0]["path"])
    if single:
        require(value is None or isinstance(value, dict), "lookup-result-shape")
        value = [] if value is None else [value]
    require(isinstance(value, list), "results-not-array")
    require(all(isinstance(record, dict) for record in value), "result-not-object")
    require(event["record_count"] == len(value), "result-count")
    return value
