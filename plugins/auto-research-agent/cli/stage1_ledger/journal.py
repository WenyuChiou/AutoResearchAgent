"""Durable event journal and append-only projections with explicit recovery."""

from contextlib import contextmanager
from datetime import datetime, timezone
from functools import wraps
import hashlib
import json
import os
from pathlib import Path, PurePosixPath


STREAMS = {
    "QueryEvent": "query_events.jsonl",
    "CandidateRevision": "candidates.jsonl",
    "DecisionEvent": "decision_events.jsonl",
    "ClaimEvidence": "claim_evidence.jsonl",
}


class LedgerError(ValueError):
    """A rejected operation; callers must preserve evidence and inspect its cause."""


def canonical(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def digest(data):
    return hashlib.sha256(data).hexdigest()


def utc_now():
    return datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")


def decode(data, path):
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise LedgerError(f"duplicate-json-key: {path}: {key}")
            result[key] = value
        return result

    def invalid(value):
        raise LedgerError(f"nonfinite-json: {path}: {value}")

    try:
        return json.loads(data, object_pairs_hook=unique, parse_constant=invalid)
    except (ValueError, UnicodeError) as error:
        raise LedgerError(f"invalid-json: {path}: {error}") from error


def contained(root, relative):
    if (
        not isinstance(relative, str)
        or not relative
        or any(ord(c) < 32 for c in relative)
    ):
        raise LedgerError(f"unsafe-path: {relative!r}")
    pieces = relative.split("/")
    if "\\" in relative or ":" in relative or any(p in {"", ".", ".."} for p in pieces):
        raise LedgerError(f"unsafe-path: {relative}")
    if PurePosixPath(relative).is_absolute():
        raise LedgerError(f"unsafe-path: {relative}")
    path = root.joinpath(*pieces)
    for parent in [path, *path.parents]:
        if parent == root:
            break
        if parent.is_symlink():
            raise LedgerError(f"symlink-path: {relative}")
    if not path.resolve().is_relative_to(root.resolve()):
        raise LedgerError(f"escaping-path: {relative}")
    return path


def write_new(path, data):
    with path.open("xb") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def append_bytes(path, data):
    with path.open("ab") as stream:
        stream.write(data)
        stream.flush()
        os.fsync(stream.fileno())


def mutation(method):
    @wraps(method)
    def locked(self, *args, **kwargs):
        with self.writing():
            return method(self, *args, **kwargs)

    return locked


class Journal:
    def __init__(self, root, *, clock=utc_now):
        self.root = Path(root).resolve()
        self.clock = clock

    @property
    def manifest(self):
        return decode(
            contained(self.root, "run_manifest.json").read_bytes(), "run_manifest.json"
        )

    def events(self):
        from .contracts import check_payload

        path = contained(self.root, "stage_events.jsonl")
        data = path.read_bytes()
        if data and not data.endswith(b"\n"):
            raise LedgerError(
                "incomplete-journal-tail: stage_events.jsonl; preserve bytes for review"
            )
        events, previous = [], "0" * 64
        previous_time = datetime.fromisoformat(
            self.manifest["research_run"]["created_at"].replace("Z", "+00:00")
        )
        for number, line in enumerate(data.splitlines(), 1):
            row = decode(line, f"stage_events.jsonl:{number}")
            if not isinstance(row, dict) or set(row) != {
                "schema_version",
                "sequence",
                "previous_sha256",
                "event_sha256",
                "payload",
            }:
                raise LedgerError(f"journal-shape: line {number}")
            unsigned = {k: v for k, v in row.items() if k != "event_sha256"}
            if (
                row["schema_version"] != "1.0.0"
                or row["sequence"] != number
                or row["previous_sha256"] != previous
                or row["event_sha256"] != digest(canonical(unsigned))
            ):
                raise LedgerError(f"journal-chain: line {number}")
            payload = row["payload"]
            check_payload(payload)
            if (
                not isinstance(payload, dict)
                or payload.get("event_id") != f"e{number:06d}"
            ):
                raise LedgerError(f"event-identity: line {number}")
            try:
                timestamp = datetime.fromisoformat(
                    payload["created_at"].replace("Z", "+00:00")
                )
                if not payload["created_at"].endswith("Z") or (
                    previous_time and timestamp < previous_time
                ):
                    raise ValueError("out of order or not UTC")
            except (KeyError, ValueError, AttributeError, TypeError) as error:
                raise LedgerError(f"event-time: line {number}") from error
            previous_time, previous = timestamp, row["event_sha256"]
            events.append(row)
        return events

    def records(self, name):
        if name not in STREAMS.values():
            raise LedgerError(f"unknown-stream: {name}")
        data = contained(self.root, name).read_bytes()
        if data and not data.endswith(b"\n"):
            raise LedgerError(f"incomplete-projection-tail: {name}")
        return [decode(line, name) for line in data.splitlines()]

    def reconcile(self, *, repair):
        events = self.events()
        for kind, name in STREAMS.items():
            expected = b"".join(
                canonical(e["payload"]) + b"\n"
                for e in events
                if e["payload"]["kind"] == kind
            )
            path = contained(self.root, name)
            actual = path.read_bytes()
            if not expected.startswith(actual) or (
                actual and not actual.endswith(b"\n")
            ):
                raise LedgerError(f"projection-conflict: {name}; no automatic rewrite")
            if expected != actual:
                if not repair:
                    raise LedgerError(f"projection-incomplete: {name}; use recover")
                append_bytes(path, expected[len(actual) :])
        return events

    @contextmanager
    def writing(self):
        from .contracts import check_manifest

        check_manifest(self.manifest)
        lock = contained(self.root, ".writer-lock")
        try:
            write_new(lock, canonical({"pid": os.getpid(), "created_at": self.clock()}))
        except FileExistsError as error:
            raise LedgerError(
                "writer-locked: verify the previous writer has stopped before removing .writer-lock"
            ) from error
        try:
            self.reconcile(repair=True)
            yield
        finally:
            lock.unlink()

    def append(self, payload):
        from .contracts import check_payload

        events = self.events()
        sequence = len(events) + 1
        payload = {
            **payload,
            "schema_version": "1.0.0",
            "event_id": f"e{sequence:06d}",
            "created_at": self.clock(),
        }
        check_payload(payload)
        if events and datetime.fromisoformat(
            payload["created_at"].replace("Z", "+00:00")
        ) < datetime.fromisoformat(
            events[-1]["payload"]["created_at"].replace("Z", "+00:00")
        ):
            raise LedgerError("clock-regression: event not appended")
        row = dict(
            schema_version="1.0.0",
            sequence=sequence,
            previous_sha256=events[-1]["event_sha256"] if events else "0" * 64,
            payload=payload,
        )
        row["event_sha256"] = digest(canonical(row))
        append_bytes(contained(self.root, "stage_events.jsonl"), canonical(row) + b"\n")
        if payload["kind"] in STREAMS:
            append_bytes(
                contained(self.root, STREAMS[payload["kind"]]),
                canonical(payload) + b"\n",
            )
        return payload

    def event(self, event_id, kind=None):
        for row in self.events():
            payload = row["payload"]
            if payload["event_id"] == event_id and (
                kind is None or payload["kind"] == kind
            ):
                return payload
        raise LedgerError(f"missing-event: {event_id} ({kind})")

    def read_ref(self, ref):
        path = contained(self.root, ref["path"])
        try:
            if path.stat().st_size > self.manifest["max_artifact_bytes"]:
                raise LedgerError(f"artifact-size-limit: {ref['path']}")
            data = path.read_bytes()
        except FileNotFoundError as error:
            raise LedgerError(f"missing-artifact: {ref['path']}") from error
        if digest(data) != ref["sha256"]:
            raise LedgerError(f"artifact-hash: {ref['path']}")
        return data

    def state_hash(self):
        material = []
        for row in self.events():
            payload = row["payload"]
            if payload["kind"] == "Checkpoint":
                continue
            if (
                payload["kind"] == "ArtifactStored"
                and payload["ref"]["artifact_type"] == "validator-report"
            ):
                continue
            material.append(payload)
        return digest(canonical({"manifest": self.manifest, "events": material}))

    def pending(self):
        events = [row["payload"] for row in self.events()]
        ended = {p["attempt_id"] for p in events if p["kind"] == "ActionFinished"}
        ended.update(p["query_id"] for p in events if p["kind"] == "QueryEvent")
        return [
            p["event_id"]
            for p in events
            if p["kind"] == "ActionStarted" and p["event_id"] not in ended
        ]

    @mutation
    def recover(self):
        from .readiness import coverage_text

        checkpoints = [
            e["payload"] for e in self.events() if e["payload"]["kind"] == "Checkpoint"
        ]
        contained(self.root, "coverage_and_stop.md").write_text(
            coverage_text(checkpoints[-1] if checkpoints else None),
            encoding="utf-8",
            newline="\n",
        )
        return {
            "pending_actions": self.pending(),
            "automatic_retries": 0,
            "state_sha256": self.state_hash(),
        }
