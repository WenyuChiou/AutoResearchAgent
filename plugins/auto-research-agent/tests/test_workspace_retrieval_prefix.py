"""Actual offline ledger prefix, unrelated queries, retries and pending starts."""

from copy import deepcopy
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace.projection import validate_index
from research_workspace.retrieval_prefix import _history, derive_retrieval_prefix
from research_workspace.retrieval_trace import work_trace
from research_workspace_native.project_stage1_library import _project
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import DeliverableError, canonical, sha
from stage1_deliverable.records import CLASSIFICATION, FINDINGS
from stage1_deliverable.screening_records import artifacts
from stage1_deliverable.views import bibtex
from stage1_ledger.validation import validate_run
from test_research_workspace_view import fixture_index


class RetrievalPrefixTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temp = tempfile.TemporaryDirectory(prefix="retrieval-prefix-")
        cls.addClassCleanup(cls.temp.cleanup)
        cls.root = Path(cls.temp.name).resolve()
        ledger = CoverageLedger.create(
            cls.root / "ledger",
            run_id="prefix-run",
            objective="Authored prefix fixture",
        )

        def start(text):
            return ledger.start("search", {"query": text})

        def backend(query, name, rows=None, failed=False):
            attempt = ledger.start(
                "backend", {"variant": "authored"}, backend=name, parent_id=query
            )
            if rows is None and not failed:
                return attempt
            empty = ledger.save_bytes(b"", producer=attempt)
            ref = (
                None if failed else ledger.save_bytes(canonical(rows), producer=attempt)
            )
            ledger.finish(
                attempt,
                outcome="rate_limited"
                if failed
                else "success_nonempty"
                if rows
                else "success_empty",
                http_status=429 if failed else 200,
                exit_code=1 if failed else 0,
                stdout=empty,
                stderr=empty,
                records=ref,
            )
            return attempt

        first = start("empty after retry")
        backend(first, "synthetic", failed=True)
        backend(first, "synthetic", [])
        ledger.complete_query(first)
        other = start("different work")
        metadata = dict(
            title="Authored target",
            authors=["Fixture"],
            year=2024,
            doi="10.5555/prefix-target",
            version="v1",
        )
        backend(other, "synthetic", [dict(metadata, doi="10.5555/other")])
        ledger.complete_query(other)
        cls.pending = start("still pending at first discovery")
        pending_attempt = backend(cls.pending, "synthetic")
        target = start("target first")
        backend(target, "synthetic", [metadata])
        ledger.complete_query(target)
        ledger.extract()
        later = ledger.start(
            "search", {"query": "target later", "coverage": {"round_number": 3}}
        )
        backend(later, "synthetic", [dict(metadata, version="v2")])
        ledger.complete_query(later)
        ledger.extract()
        empty = ledger.save_bytes(b"", producer=pending_attempt)
        ledger.finish(
            pending_attempt,
            outcome="interrupted",
            http_status=None,
            exit_code=1,
            stdout=empty,
            stderr=empty,
            records=None,
        )
        ledger.complete_query(cls.pending)
        report = validate_run(ledger.root)
        if not report["valid"]:
            raise AssertionError(report)
        binding = dict(
            project_id="prefix-project",
            input_version=1,
            brief_sha256="1" * 64,
            plan_manifest_sha256="2" * 64,
            settings={"authored": True},
        )
        library = _project(
            "project-ref",
            binding,
            dict(
                run_ref="run-ref",
                manifest_sha256=sha((ledger.root / "run_manifest.json").read_bytes()),
            ),
            ledger,
            report,
        )
        index = fixture_index()
        index.update(
            schema_version="1.2.0",
            canonical_records_version="1.2.0",
            project_id="prefix-project",
            papers=[],
            sources=[],
            core_claim_history=[],
            core_artifacts=[],
            stage2_canonical_consumer=dict(
                status="unconnected", reason="canonical-records-1.2-consumer-required"
            ),
            screening_library=library,
            screening_artifacts=artifacts(library),
            screening_journal=dict(
                path="screening_events.jsonl",
                sha256=library["binding"]["journal_sha256"],
            ),
        )
        for row in library["rows"]:
            data = row["metadata"]
            index["papers"].append(
                dict(
                    work_id=row["work_id"],
                    version_id=row["selected_version_id"],
                    title=data["title"],
                    authors=data["authors"],
                    year=data["year"],
                    venue="Unknown",
                    doi=data["doi"],
                    url=None,
                    evidence_level="metadata",
                    source_ids=[],
                    claim_ids=[],
                    roles=[],
                    reading_status="discovery-only",
                    classification=dict.fromkeys(CLASSIFICATION, "Unknown"),
                    findings=dict.fromkeys(FINDINGS, "Unknown"),
                )
            )
        index["bibliography"].update(
            entries=[
                dict(
                    work_id=p["work_id"],
                    version_id=p["version_id"],
                    bibtex=bibtex({"papers": [p]}).decode(),
                )
                for p in index["papers"]
            ],
            all_bibtex=bibtex(index).decode(),
        )
        validate_index(index)
        cls.index = index
        cls.journal = (ledger.root / "stage_events.jsonl").read_bytes()
        cls.work = next(
            p["work_id"] for p in index["papers"] if p["doi"] == "10.5555/prefix-target"
        )

    def derive(self, index=None, journal=None, **overrides):
        raw = canonical(self.index if index is None else index)
        options = dict(
            trusted_index_sha256=sha(raw),
            project_id="prefix-project",
            input_version=1,
            run_id="prefix-run",
        )
        options.update(overrides)
        return derive_retrieval_prefix(
            raw, self.journal if journal is None else journal, **options
        )

    def test_failure_distinct_from_empty_and_all_query_prefix(self):
        before = deepcopy(self.index)
        result = self.derive()
        row = next(r for r in result["rows"] if r["work_id"] == self.work)
        prefix = row["search_attempts_until_first_discovery"]
        self.assertEqual(
            prefix["counts"],
            dict(
                query_starts=4,
                backend_attempt_starts=5,
                query_completions=2,
                backend_attempt_completions=4,
                backend_failures=1,
                success_empty=1,
            ),
        )
        self.assertEqual(prefix["queries"][2]["query_id"], self.pending)
        self.assertEqual(
            prefix["queries"][2]["backend_attempts"][0]["status"], "pending-at-cutoff"
        )
        self.assertIsNone(prefix["round_number"])
        selected = next(
            p["version_id"] for p in self.index["papers"] if p["work_id"] == self.work
        )
        self.assertNotEqual(prefix["first_version_id"], selected)
        self.assertEqual(row["counts"]["distinct_queries"], 2)
        self.assertEqual(len(prefix["queries"]), 4)
        self.assertEqual(self.index, before)
        self.assertFalse(result["execution_authorized"])
        self.assertIsNone(
            work_trace(self.index, self.work)["search_attempts_until_first_discovery"]
        )

    def test_missing_evidence_fails_closed_and_legacy_is_unknown(self):
        raw = canonical(self.index)
        missing = derive_retrieval_prefix(
            raw,
            None,
            trusted_index_sha256=sha(raw),
            project_id="prefix-project",
            input_version=1,
            run_id="prefix-run",
        )
        self.assertTrue(
            all(
                r["search_attempts_until_first_discovery"] is None
                for r in missing["rows"]
            )
        )
        legacy = fixture_index()
        legacy_raw = canonical(legacy)
        result = derive_retrieval_prefix(
            legacy_raw,
            None,
            trusted_index_sha256=sha(legacy_raw),
            project_id=legacy["project_id"],
            input_version=1,
            run_id="requested-but-not-recorded",
        )
        self.assertIsNone(result["binding"])

    def test_mixed_input_or_run_rejected(self):
        for overrides in (
            dict(input_version=2),
            dict(run_id="other"),
            dict(project_id="foreign"),
            dict(input_version=True),
        ):
            with self.subTest(overrides=overrides), self.assertRaises(DeliverableError):
                self.derive(**overrides)

    def test_rehash_tamper_rejected_by_external_index_pin(self):
        index = deepcopy(self.index)
        events = [json.loads(line) for line in self.journal.splitlines()][1:]
        previous = "0" * 64
        for number, event in enumerate(events, 1):
            event.update(sequence=number, previous_sha256=previous)
            event["payload"]["event_id"] = f"e{number:06d}"
            event["event_sha256"] = sha(
                canonical({k: v for k, v in event.items() if k != "event_sha256"})
            )
            previous = event["event_sha256"]
        altered = b"".join(canonical(event) + b"\n" for event in events)
        index["screening_journal"]["sha256"] = sha(altered)
        index["screening_library"]["binding"]["journal_sha256"] = sha(altered)
        with self.assertRaisesRegex(DeliverableError, "external index hash"):
            self.derive(index, altered, trusted_index_sha256=sha(canonical(self.index)))

    def test_missing_prefix_reordering_duplicate_and_incomplete_tail_rejected(self):
        lines = self.journal.splitlines(keepends=True)
        for raw in (
            b"".join(lines[1:]),
            b"".join([lines[1], lines[0], *lines[2:]]),
            lines[0] + self.journal,
            self.journal.rstrip(b"\n"),
        ):
            index = deepcopy(self.index)
            index["screening_journal"]["sha256"] = sha(raw)
            index["screening_library"]["binding"]["journal_sha256"] = sha(raw)
            with self.subTest(length=len(raw)), self.assertRaises(ValueError):
                self.derive(index, raw)

    def test_cli_matches_callable_and_rejects_wrong_external_pin(self):
        raw = canonical(self.index)
        path, journal = self.root / "index.json", self.root / "events.jsonl"
        path.write_bytes(raw)
        journal.write_bytes(self.journal)
        env = dict(os.environ, PYTHONPATH=str(Path(__file__).parents[1] / "cli"))
        command = [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "research_workspace.retrieval_prefix",
            str(path),
            "--journal",
            str(journal),
            "--project-id",
            "prefix-project",
            "--input-version",
            "1",
            "--run-id",
            "prefix-run",
            "--trusted-index-sha256",
            sha(raw),
        ]
        actual = subprocess.run(command, env=env, capture_output=True, timeout=30)
        self.assertEqual(actual.returncode, 0, actual.stderr.decode())
        self.assertEqual(json.loads(actual.stdout), self.derive())
        command[-1] = "0" * 64
        failed = subprocess.run(command, env=env, capture_output=True, timeout=30)
        self.assertEqual(failed.returncode, 2)
        self.assertIn(b"external index hash", failed.stderr)

    def test_causal_start_finish_and_closed_query_guards(self):
        original = [json.loads(line) for line in self.journal.splitlines()]
        finish = next(
            i
            for i, r in enumerate(original)
            if r["payload"]["kind"] == "ActionFinished"
        )
        query_end = next(
            i for i, r in enumerate(original) if r["payload"]["kind"] == "QueryEvent"
        )
        for case in (
            "finish-before-start",
            "duplicate-finish",
            "backend-after-query",
            "changed-query-completion",
        ):
            rows = deepcopy(original)
            if case == "finish-before-start":
                rows[finish]["payload"]["attempt_id"] = "e999999"
            elif case == "duplicate-finish":
                rows.insert(finish + 1, deepcopy(rows[finish]))
            elif case == "backend-after-query":
                start = next(
                    deepcopy(r)
                    for r in rows
                    if r["payload"]["kind"] == "ActionStarted"
                    and r["payload"]["operation"] == "backend"
                )
                start["payload"]["event_id"] = "e999999"
                rows.insert(query_end + 1, start)
            else:
                rows[query_end]["payload"]["result_count"] += 1
            with self.subTest(case=case), self.assertRaises(DeliverableError):
                _history(rows)


if __name__ == "__main__":
    unittest.main()
