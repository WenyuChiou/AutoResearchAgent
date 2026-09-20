"""Synthetic public audit files; no network and no research-hub internals."""

import copy
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from stage1_ledger.journal import LedgerError, canonical, digest
from stage1_retrieval.audit import read_audit, result_records


def audit_fixture(root):
    root.mkdir()
    (root / "artifacts").mkdir()
    events = []

    def event(
        identifier,
        parent,
        operation,
        backend,
        kind,
        outcome=None,
        records=None,
        status=None,
    ):
        refs = []
        if records is not None:
            raw = canonical(records)
            path = "artifacts/" + identifier + ".json"
            (root / path).write_bytes(raw)
            refs.append(dict(path=path, bytes=len(raw), sha256=digest(raw)))
        value = dict(
            schema_version="1.0.0",
            type="audit_event",
            sequence=len(events) + 1,
            event=kind,
            attempt_id=identifier,
            parent_id=parent,
            operation=operation,
            backend=backend,
            timestamp="2026-01-01T00:00:00Z",
            parameters={},
            outcome=outcome,
            error_code=None,
            http_status=status,
            record_count=len(records) if records is not None else None,
            artifacts=refs,
        )
        events.append(value)
        return value

    command, query = "a" * 32, "b" * 32
    event(command, None, "command", None, "started")
    event(query, command, "search-query", None, "started")
    row = dict(
        title="Synthetic literature item",
        authors=["Synthetic Author"],
        year=2026,
        doi="10.5555/synthetic-audit",
    )
    for identifier, backend, values, outcome in [
        ("c" * 32, "openalex", [row], "success"),
        ("d" * 32, "crossref", [row], "success"),
        ("e" * 32, "semantic-scholar", [], "rate_limited"),
    ]:
        event(identifier, query, "backend-search", backend, "started")
        event(identifier, query, "backend-search", backend, "finished", outcome, values)
    event(query, command, "search-query", None, "finished", "partial", [row])
    event(command, None, "command", None, "finished", "partial")
    manifest = dict(
        schema_version="1.0.0",
        type="audit_manifest",
        created_at="2026-01-01T00:00:01Z",
        command_id=command,
        complete=True,
        outcome="partial",
        exit_code=0,
        event_count=len(events),
        events={},
    )
    seal(root, events, manifest)
    return events, manifest


def seal(root, events, manifest):
    raw = b"".join(canonical(event) + b"\n" for event in events)
    (root / "events.jsonl").write_bytes(raw)
    manifest["events"] = dict(path="events.jsonl", bytes=len(raw), sha256=digest(raw))
    (root / "audit_manifest.json").write_bytes(canonical(manifest))


class AuditTests(unittest.TestCase):
    def test_preserves_premerge_paths_and_partial_failure(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "audit"
            audit_fixture(root)
            audit = read_audit(root)
            backends = [
                e
                for e in audit["finishes"].values()
                if e["operation"] == "backend-search"
            ]
            self.assertEqual(
                [e["backend"] for e in backends],
                ["openalex", "crossref", "semantic-scholar"],
            )
            self.assertEqual(
                [len(result_records(audit, e)) for e in backends], [1, 1, 0]
            )
            self.assertEqual(backends[-1]["outcome"], "rate_limited")
            self.assertEqual(audit["manifest"]["outcome"], "partial")

    def test_hash_missing_raw_and_schema_fail_closed(self):
        for change in ("missing", "hash", "schema", "path"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory) / "audit"
                events, manifest = audit_fixture(root)
                ref = events[3]["artifacts"][0]
                if change == "missing":
                    (root / ref["path"]).unlink()
                elif change == "hash":
                    (root / ref["path"]).write_bytes(b"[]")
                elif change == "path":
                    ref["path"] = "../outside.json"
                else:
                    events[0]["schema_version"] = "99.0.0"
                seal(root, events, manifest)
                with self.assertRaises((LedgerError, FileNotFoundError)):
                    read_audit(root)

    def test_rehashed_broken_history_is_rejected(self):
        for change in (
            "sequence",
            "parent",
            "duplicate",
            "operation",
            "unfinished",
            "root",
            "outcome",
            "count",
            "time",
        ):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory) / "audit"
                events, manifest = audit_fixture(root)
                if change == "sequence":
                    events[2]["sequence"] = 9
                elif change == "parent":
                    events[2]["parent_id"] = "f" * 32
                elif change == "duplicate":
                    events[2]["attempt_id"] = events[1]["attempt_id"]
                elif change == "operation":
                    events[3]["operation"] = "invented"
                elif change == "unfinished":
                    events.pop(3)
                    for i, e in enumerate(events, 1):
                        e["sequence"] = i
                    manifest["event_count"] = len(events)
                elif change == "root":
                    manifest["command_id"] = "f" * 32
                elif change == "outcome":
                    manifest["outcome"] = "success"
                elif change == "count":
                    manifest["event_count"] += 2
                else:
                    manifest["created_at"] = "2025-12-31T23:59:59Z"
                seal(root, events, manifest)
                with self.assertRaises(LedgerError):
                    read_audit(root)

    def test_response_observations_extend_but_do_not_rewrite_parameters(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "audit"
            events, manifest = audit_fixture(root)
            events[2]["parameters"] = {"query": "synthetic query"}
            events[3]["parameters"] = {
                "query": "synthetic query",
                "resolved_url": "https://example.invalid/result",
            }
            seal(root, events, manifest)
            self.assertEqual(read_audit(root)["events"], events)
            events[3]["parameters"]["query"] = "changed"
            seal(root, events, manifest)
            with self.assertRaisesRegex(LedgerError, "changed-parameter"):
                read_audit(root)

    def test_result_content_and_bounds(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "audit"
            audit_fixture(root)
            audit = read_audit(root)
            event = copy.deepcopy(audit["finishes"]["c" * 32])
            event["record_count"] = 2
            with self.assertRaisesRegex(LedgerError, "result-count"):
                result_records(audit, event)
            with self.assertRaisesRegex(LedgerError, "file-size-limit"):
                read_audit(root, limit=4)
            with self.assertRaisesRegex(LedgerError, "total-size-limit"):
                read_audit(root, total_limit=4)


if __name__ == "__main__":
    unittest.main()
