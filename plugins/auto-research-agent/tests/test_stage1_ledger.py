"""Offline acceptance: independent of any research-hub branch or network."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run
from stage1_ledger.journal import LedgerError, STREAMS, canonical, digest, contained
from stage1_ledger.identity import work_key


SYNTHETIC = dict(
    doi="10.5555/stage1-synthetic",
    title="Synthetic household record",
    authors=["Synthetic Author"],
    year=2024,
    version="record-v1",
)


def add_query(ledger, rows):
    query = ledger.start("search", {"query": "synthetic follow-up"})
    attempt = ledger.start(
        "backend", {"variant": "base"}, backend="synthetic", parent_id=query
    )
    raw = ledger.save_bytes(canonical(rows), producer=attempt)
    empty = ledger.save_bytes(b"", producer=attempt)
    ledger.finish(
        attempt,
        outcome="success_nonempty" if rows else "success_empty",
        http_status=200,
        exit_code=0,
        stdout=raw,
        stderr=empty,
        records=raw,
    )
    ledger.complete_query(query)
    return attempt, raw


def rewrite_for_tamper_test(ledger, mutate):
    """Rehash a changed event so semantic tests do not merely test chain hashing."""
    events = ledger.events()
    mutate(events)
    previous = "0" * 64
    for event in events:
        event["previous_sha256"] = previous
        event["event_sha256"] = digest(
            canonical({k: v for k, v in event.items() if k != "event_sha256"})
        )
        previous = event["event_sha256"]
    (ledger.root / "stage_events.jsonl").write_bytes(
        b"".join(canonical(e) + b"\n" for e in events)
    )
    for kind, name in STREAMS.items():
        (ledger.root / name).write_bytes(
            b"".join(
                canonical(e["payload"]) + b"\n"
                for e in events
                if e["payload"]["kind"] == kind
            )
        )


def fixture(root):
    ledger = Ledger.create(
        root,
        run_id="synthetic-run",
        objective="Synthetic household question",
        clock=lambda: "2026-01-01T00:00:00Z",
    )
    raw_refs = []
    for number, backends, outcome, status in [
        (1, ["synthetic-a", "synthetic-b"], "success_nonempty", 200),
        (2, ["synthetic-a"], "success_empty", 200),
        (3, ["synthetic-c"], "rate_limited", 429),
    ]:
        query = ledger.start("search", {"query": f"synthetic family {number}"})
        for backend in backends:
            attempt = ledger.start(
                "backend", {"variant": "base"}, backend=backend, parent_id=query
            )
            rows = []
            if number == 1:
                rows = [
                    dict(
                        doi="10.5555/stage1-synthetic",
                        title="Synthetic household record",
                        authors=["Synthetic Author"],
                        year=2024,
                        version="record-v1",
                    )
                ]
            data = (
                json.dumps(rows).encode()
                if status == 200
                else b'{"error":"rate limit"}'
            )
            raw = ledger.save_bytes(data, producer=attempt)
            stderr = ledger.save_bytes(b"", producer=attempt)
            raw_refs.append(raw)
            ledger.finish(
                attempt,
                outcome=outcome,
                http_status=status,
                exit_code=0 if status == 200 else 1,
                stdout=raw,
                stderr=stderr,
                records=raw if status == 200 else None,
            )
        ledger.complete_query(query)
    ledger.extract()
    work = next(iter(ledger.candidates()))
    first = ledger.decide(
        work,
        "include",
        reason="scope-match",
        rationale="Synthetic screening",
        evidence_refs=[raw_refs[0]],
    )
    ledger.decide(
        work,
        "exclude",
        reason="scope-reassessment",
        rationale="Synthetic reversal",
        evidence_refs=[raw_refs[1]],
    )
    return ledger, raw_refs, work, first


class Stage1LedgerTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.ledger = Ledger.create(
            Path(self.directory.name) / "basic",
            run_id="synthetic",
            objective="Synthetic scope",
            clock=lambda: "2026-01-01T00:00:00Z",
        )

    def test_three_queries_preserve_failures_provenance_and_reversal(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, refs, work, first = fixture(Path(directory) / "run")
            report = validate_run(ledger.root)
            self.assertTrue(report["valid"], report)
            self.assertEqual(
                report["counts"],
                dict(
                    queries=3,
                    backend_attempts=4,
                    backend_failures=1,
                    success_empty=1,
                    discoveries=2,
                    works=1,
                    candidate_revisions=2,
                    decisions=2,
                    claims=0,
                ),
            )
            candidate = ledger.candidates()[work]
            self.assertEqual(len(candidate["discoveries"]), 2)
            self.assertEqual(candidate["identity_status"], "unverified")
            decisions = ledger.records("decision_events.jsonl")
            self.assertEqual(
                [d["new_decision"] for d in decisions], ["include", "exclude"]
            )
            self.assertEqual(decisions[1]["reverses_event_id"], first)
            checkpoint = ledger.checkpoint()
            self.assertIn(
                checkpoint["stage_result"]["next_allowed_action"],
                ["continue", "human-review"],
            )
            self.assertNotEqual(
                checkpoint["stage_result"]["next_allowed_action"], "stop-sufficient"
            )
            self.assertTrue(validate_run(ledger.root)["valid"])
            ledger.checkpoint()
            self.assertTrue(validate_run(ledger.root)["valid"])

    def test_missing_file_cli_failure_then_exact_restore(self):
        with tempfile.TemporaryDirectory() as directory:
            ledger, refs, _, _ = fixture(Path(directory) / "run")
            path = ledger.root / refs[0]["path"]
            original = path.read_bytes()
            path.unlink()
            command = [
                sys.executable,
                str(PLUGIN / "cli/stage1_ledger"),
                "--run",
                str(ledger.root),
                "validate",
            ]
            failed = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(failed.returncode, 1, failed.stderr)
            self.assertIn(refs[0]["path"], failed.stdout)
            path.write_bytes(original)
            repaired = subprocess.run(
                command, capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(repaired.returncode, 0, repaired.stdout + repaired.stderr)
            self.assertTrue(json.loads(repaired.stdout)["valid"])

    def test_cross_query_dedup_keeps_versions_and_conflicts(self):
        ledger = self.ledger
        add_query(ledger, [SYNTHETIC])
        add_query(
            ledger,
            [
                dict(
                    SYNTHETIC,
                    doi="https://doi.org/10.5555/STAGE1-SYNTHETIC",
                    version="record-v2",
                    year=2025,
                )
            ],
        )
        ledger.extract()
        candidate = next(iter(ledger.candidates().values()))
        self.assertEqual(candidate["identity_status"], "conflict")
        self.assertEqual(len(candidate["version_ids"]), 2)
        self.assertEqual(len({d["query_id"] for d in candidate["discoveries"]}), 2)
        before = (ledger.root / "stage_events.jsonl").read_bytes()
        self.assertEqual(ledger.extract()["new_discoveries"], 0)
        self.assertEqual(before, (ledger.root / "stage_events.jsonl").read_bytes())
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_unicode_identity_and_separate_identifier_namespaces(self):
        base = dict(title="합성 가계", authors=["合成人名"], year=2024)
        self.assertEqual(work_key(base), work_key(dict(base, title="  합성   가계 ")))
        self.assertNotEqual(work_key(base), work_key(dict(base, title="다른 제목")))
        self.assertNotEqual(
            work_key(dict(base, doi=SYNTHETIC["doi"])),
            work_key(dict(base, arxiv="2401.00001v1")),
        )
        self.assertEqual(
            work_key(dict(base, arxiv="2401.00001v1")),
            work_key(dict(base, arxiv="2401.00001v2")),
        )
        for field, value in [("doi", "garbage"), ("arxiv", "garbage"), ("pmid", "NaN")]:
            with self.subTest(field=field), self.assertRaises(LedgerError):
                work_key(dict(base, **{field: value}))

    def test_unstated_versions_are_not_merged(self):
        record = {k: v for k, v in SYNTHETIC.items() if k != "version"}
        add_query(self.ledger, [record, record])
        self.ledger.extract()
        self.assertEqual(
            len(next(iter(self.ledger.candidates().values()))["version_ids"]), 2
        )

    def test_backend_failures_are_not_success_empty_and_no_automatic_retry(self):
        ledger = self.ledger
        query = ledger.start("search", {"query": "synthetic failure family"})
        for outcome, status in [
            ("not_found", 404),
            ("rate_limited", 429),
            ("timeout", None),
            ("network_error", None),
            ("parse_error", 200),
            ("unknown_error", None),
        ]:
            attempt = ledger.start(
                "backend", {"variant": outcome}, backend="synthetic", parent_id=query
            )
            raw = ledger.save_bytes(b"synthetic error", producer=attempt)
            with self.assertRaises(LedgerError):
                ledger.finish(
                    attempt,
                    outcome="success_empty",
                    http_status=status,
                    exit_code=1,
                    stdout=raw,
                    stderr=raw,
                )
            ledger.finish(
                attempt,
                outcome=outcome,
                http_status=status,
                exit_code=1,
                stdout=raw,
                stderr=raw,
            )
        ledger.complete_query(query)
        report = validate_run(ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["counts"]["backend_failures"], 6)
        self.assertEqual(report["counts"]["success_empty"], 0)
        self.assertEqual(ledger.records("query_events.jsonl")[0]["outcome"], "failed")
        self.assertEqual(ledger.recover()["automatic_retries"], 0)

    def test_pending_attempts_and_projection_recovery(self):
        ledger = self.ledger
        query = ledger.start("search", {"query": "synthetic interrupted action"})
        attempt = ledger.start(
            "backend", {"variant": "base"}, backend="synthetic", parent_id=query
        )
        self.assertEqual(ledger.recover()["pending_actions"], [query, attempt])
        raw = ledger.save_bytes(b"[]", producer=attempt)
        ledger.finish(
            attempt,
            outcome="success_empty",
            http_status=200,
            exit_code=0,
            stdout=raw,
            stderr=raw,
            records=raw,
        )
        ledger.complete_query(query)
        expected = (ledger.root / "query_events.jsonl").read_bytes()
        (ledger.root / "query_events.jsonl").write_bytes(b"")
        self.assertFalse(validate_run(ledger.root)["valid"])
        self.assertEqual(ledger.recover()["pending_actions"], [])
        self.assertEqual(expected, (ledger.root / "query_events.jsonl").read_bytes())
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_corrupt_projection_and_torn_journal_are_preserved(self):
        ledger = self.ledger
        add_query(ledger, [])
        projection = ledger.root / "query_events.jsonl"
        original = projection.read_bytes()
        projection.write_bytes(b'{"corrupt":true}\n')
        with self.assertRaisesRegex(LedgerError, "projection-conflict"):
            ledger.recover()
        self.assertEqual(projection.read_bytes(), b'{"corrupt":true}\n')
        projection.write_bytes(original)
        journal = ledger.root / "stage_events.jsonl"
        journal.write_bytes(journal.read_bytes() + b'{"unfinished"')
        before = journal.read_bytes()
        with self.assertRaisesRegex(LedgerError, "incomplete-journal-tail"):
            ledger.recover()
        self.assertEqual(before, journal.read_bytes())

    def test_writer_lock_is_not_stolen(self):
        lock = self.ledger.root / ".writer-lock"
        lock.write_text("synthetic unfinished writer", encoding="utf-8")
        with self.assertRaisesRegex(LedgerError, "writer-locked"):
            self.ledger.recover()
        self.assertTrue(lock.exists())

    def test_partial_failure_is_not_a_complete_success(self):
        ledger = self.ledger
        query = ledger.start("search", {"query": "synthetic mixed response"})
        for number, outcome, status in [
            (1, "success_empty", 200),
            (2, "rate_limited", 429),
        ]:
            attempt = ledger.start(
                "backend",
                {"variant": str(number)},
                backend=f"synthetic-{number}",
                parent_id=query,
            )
            raw = ledger.save_bytes(b"[]", producer=attempt)
            ledger.finish(
                attempt,
                outcome=outcome,
                http_status=status,
                exit_code=0 if status == 200 else 1,
                stdout=raw,
                stderr=raw,
                records=raw if status == 200 else None,
            )
        ledger.complete_query(query)
        self.assertEqual(
            ledger.records("query_events.jsonl")[0]["outcome"], "partial_failure"
        )
        self.assertTrue(validate_run(ledger.root)["valid"])
        self.assertEqual(
            ledger.checkpoint()["stage_result"]["next_allowed_action"], "human-review"
        )

    def test_clock_regression_is_rejected_before_append(self):
        ledger = self.ledger
        ledger.start("search", {"query": "synthetic"})
        before = (ledger.root / "stage_events.jsonl").read_bytes()
        ledger.clock = lambda: "2025-12-31T23:59:59Z"
        with self.assertRaisesRegex(LedgerError, "clock-regression"):
            ledger.start("search", {"query": "synthetic"})
        self.assertEqual((ledger.root / "stage_events.jsonl").read_bytes(), before)
        ledger.clock = lambda: "2026-01-01T00:00:00.100Z"
        ledger.start("search", {"query": "synthetic fractional time"})
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_first_event_cannot_precede_manifest(self):
        ledger = self.ledger
        ledger.clock = lambda: "2025-12-31T23:59:59Z"
        with self.assertRaisesRegex(LedgerError, "clock-regression"):
            ledger.start("search", {"query": "synthetic early clock"})
        self.assertEqual((ledger.root / "stage_events.jsonl").read_bytes(), b"")

    def test_coverage_view_tampering_and_interrupted_checkpoint_recover(self):
        ledger = self.ledger
        ledger.checkpoint()
        path = ledger.root / "coverage_and_stop.md"
        expected = path.read_bytes()
        path.write_text("Decision: stop-sufficient", encoding="utf-8")
        report = validate_run(ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("coverage-view-mismatch", report["errors"][0])
        ledger.recover()
        self.assertEqual(path.read_bytes(), expected)
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_human_reversal_is_bound_to_state_and_preserves_input(self):
        ledger = self.ledger
        _, raw = add_query(ledger, [SYNTHETIC])
        ledger.extract()
        work = next(iter(ledger.candidates()))
        authorization = {
            "input": "Synthetic human: exclude this record",
            "state_sha256": ledger.state_hash(),
        }
        ledger.checkpoint()
        ledger.decide(
            work,
            "exclude",
            reason="human-override",
            rationale="Synthetic instruction",
            evidence_refs=[raw],
            actor="synthetic-reviewer",
            authorization=authorization,
        )
        self.assertEqual(
            ledger.records("decision_events.jsonl")[0]["authorization"], authorization
        )
        self.assertTrue(validate_run(ledger.root)["valid"])
        with self.assertRaisesRegex(LedgerError, "stale-human-authorization"):
            ledger.decide(
                work,
                "include",
                reason="human-override",
                rationale="Synthetic stale instruction",
                evidence_refs=[raw],
                actor="synthetic-reviewer",
                authorization=authorization,
            )

    def test_bad_record_is_recorded_once_and_blocks_readiness(self):
        ledger = self.ledger
        add_query(ledger, [dict(SYNTHETIC, doi="invalid"), SYNTHETIC])
        result = ledger.extract()
        self.assertEqual(
            result, {"new_discoveries": 1, "works": 1, "extraction_failures": 1}
        )
        before = len(ledger.events())
        ledger.extract()
        self.assertEqual(len(ledger.events()), before)
        report = validate_run(ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(len(report["missing_discoveries"]), 1)
        self.assertEqual(
            ledger.checkpoint()["stage_result"]["next_allowed_action"], "human-review"
        )

    def test_claim_locator_does_not_upgrade_identity_or_evidence(self):
        ledger = self.ledger
        attempt, _ = add_query(ledger, [SYNTHETIC])
        ledger.extract()
        candidate = next(iter(ledger.candidates().values()))
        attempt = ledger.start_source_import(
            work_id=candidate["work_id"],
            version_id=candidate["version_ids"][0],
            source_uri="https://example.invalid/abstract",
            actor="synthetic-reviewer",
            reason="Import saved synthetic abstract",
        )
        raw = ledger.save_bytes(
            b"Synthetic abstract: households differ.", producer=attempt
        )
        claim = dict(
            work_id=candidate["work_id"],
            version_id=candidate["version_ids"][0],
            claim_text="Synthetic household difference",
            relation="supports",
            evidence_level="abstract",
            locator={"section": "abstract", "quote": "households differ"},
            source_ref=raw,
            verifier={
                "actor": "synthetic-reviewer",
                "actor_type": "agent",
                "method": "read saved abstract",
            },
        )
        ledger.claim(**claim)
        with self.assertRaisesRegex(LedgerError, "claim-quote-not-in-source"):
            ledger.claim(
                **dict(claim, locator={"section": "abstract", "quote": "not present"})
            )
        with self.assertRaisesRegex(LedgerError, "claim-needs-text"):
            ledger.claim(**dict(claim, evidence_level="metadata"))
        self.assertEqual(
            ledger.candidates()[candidate["work_id"]]["evidence_level"], "metadata"
        )
        self.assertEqual(candidate["identity_status"], "unverified")
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_missing_file_and_hash_change_fail_closed(self):
        ledger = self.ledger
        _, raw = add_query(ledger, [SYNTHETIC])
        path = ledger.root / raw["path"]
        original = path.read_bytes()
        path.write_bytes(b"changed")
        report = validate_run(ledger.root)
        self.assertFalse(report["valid"])
        self.assertTrue(all(value is None for value in report["counts"].values()))
        self.assertIn("artifact-hash", report["errors"][0])
        path.write_bytes(original)
        altered_ref = dict(raw, producer="invented")
        with self.assertRaisesRegex(LedgerError, "unregistered-or-altered"):
            ledger.read_ref(altered_ref)

    def test_semantic_replay_rejects_rehashed_inventions(self):
        for kind, field, value in [
            ("QueryEvent", "result_count", 99),
            ("CandidateRevision", "canonical_key", "invented"),
            ("DecisionEvent", "prior_decision", "invented"),
            ("Checkpoint", "state_sha256", "0" * 64),
        ]:
            with self.subTest(kind=kind), tempfile.TemporaryDirectory() as directory:
                ledger, _, _, _ = fixture(Path(directory) / "run")
                ledger.checkpoint()

                def change(events):
                    next(e["payload"] for e in events if e["payload"]["kind"] == kind)[
                        field
                    ] = value

                rewrite_for_tamper_test(ledger, change)
                self.assertFalse(validate_run(ledger.root)["valid"])

    def test_unknown_schema_and_bad_json(self):
        path = self.ledger.root / "run_manifest.json"
        original = path.read_bytes()
        manifest = json.loads(original)
        manifest["schema_version"] = "99.0.0"
        path.write_bytes(canonical(manifest))
        self.assertFalse(validate_run(self.ledger.root)["valid"])
        with self.assertRaisesRegex(LedgerError, "schema"):
            self.ledger.start("search", {"query": "synthetic"})
        for invalid in [b'{"a":1,"a":2}', b'{"a":NaN}', b"{", b"\xff"]:
            path.write_bytes(invalid)
            self.assertFalse(validate_run(self.ledger.root)["valid"])

    def test_paths_reject_escape_and_symlink(self):
        for path in [
            "../outside",
            "C:/outside",
            "/absolute",
            "raw\\windows",
            "raw//empty",
            "raw/./dot",
        ]:
            with self.subTest(path=path), self.assertRaises(LedgerError):
                contained(self.ledger.root, path)
        link = self.ledger.root / "link"
        try:
            link.symlink_to(Path(self.directory.name), target_is_directory=True)
        except OSError:
            self.skipTest("Host does not grant symlink creation; path escape cases ran")
        with self.assertRaisesRegex(LedgerError, "symlink-path"):
            contained(self.ledger.root, "link/outside")

    def test_cli_skill_path_and_guardrail(self):
        root = Path(self.directory.name) / "cli-run"
        base = [sys.executable, str(PLUGIN / "cli/stage1_ledger"), "--run", str(root)]

        def command(*args, expected=0):
            completed = subprocess.run(
                [*base, *args], capture_output=True, text=True, encoding="utf-8"
            )
            self.assertEqual(
                completed.returncode, expected, completed.stdout + completed.stderr
            )
            return json.loads(completed.stdout)

        def request(operation, value):
            path = Path(self.directory.name) / "request.json"
            path.write_bytes(canonical(value))
            return command(operation, "--request", str(path))["event_id"]

        command(
            "init",
            "--run-id",
            "synthetic-cli",
            "--objective",
            "Synthetic household scope",
        )
        query = request(
            "start", {"operation": "search", "arguments": {"query": "synthetic family"}}
        )
        attempt = request(
            "start",
            {
                "operation": "backend",
                "arguments": {"variant": "base"},
                "backend": "synthetic",
                "parent_id": query,
            },
        )
        source = Path(self.directory.name) / "source.json"
        source.write_bytes(canonical([SYNTHETIC]))
        ref = command("save", "--source", str(source), "--producer", attempt)
        request(
            "finish",
            {
                "attempt_id": attempt,
                "outcome": "success_nonempty",
                "http_status": 200,
                "exit_code": 0,
                "stdout": ref,
                "stderr": ref,
                "records": ref,
            },
        )
        command("complete-query", "--query-id", query)
        self.assertEqual(command("extract")["works"], 1)
        self.assertTrue(command("validate")["valid"])
        result = command("checkpoint")
        self.assertEqual(result["stage_result"]["next_allowed_action"], "continue")
        self.assertIn(
            "closest-work-unverified", result["stage_result"]["gate"]["reasons"]
        )
        for script in ["validators/stage1_run.py", "gates/stage1_readiness.py"]:
            ran = subprocess.run(
                [sys.executable, str(PLUGIN / script), str(root)],
                capture_output=True,
                text=True,
                encoding="utf-8",
            )
            self.assertEqual(ran.returncode, 0, ran.stdout + ran.stderr)
        for name in [
            "run_manifest.json",
            "query_events.jsonl",
            "candidates.jsonl",
            "decision_events.jsonl",
            "claim_evidence.jsonl",
            "coverage_and_stop.md",
        ]:
            self.assertTrue((root / name).is_file(), name)

    def test_packet_claim_states_preserve_partial_and_unavailable_evidence(self):
        ledger = self.ledger
        attempt, _ = add_query(ledger, [SYNTHETIC])
        ledger.extract()
        candidate = next(iter(ledger.candidates().values()))
        attempt = ledger.start_source_import(
            work_id=candidate["work_id"],
            version_id=candidate["version_ids"][0],
            source_uri="https://example.invalid/results",
            actor="synthetic-reviewer",
            reason="Import saved synthetic results",
        )
        raw = ledger.save_bytes(
            b"Synthetic result: some households differ.", producer=attempt
        )
        base = dict(
            work_id=candidate["work_id"],
            version_id=candidate["version_ids"][0],
            claim_text="Synthetic difference",
            source_ref=raw,
            verifier={
                "actor": "synthetic-reviewer",
                "actor_type": "agent",
                "method": "read supplied text",
            },
        )
        ledger.claim(
            **base,
            relation="partial",
            evidence_level="full_text",
            locator={"section": "results", "quote": "some households differ"},
        )
        ledger.claim(
            **base,
            relation="supports",
            evidence_level="primary_data_or_table",
            locator={"section": "results", "quote": "some households differ"},
        )
        ledger.claim(
            **base, relation="unclear", evidence_level="abstract", locator=None
        )
        ledger.claim(
            **base, relation="unverifiable", evidence_level="unavailable", locator=None
        )
        with self.assertRaisesRegex(LedgerError, "claim-needs-text"):
            ledger.claim(
                **base, relation="supports", evidence_level="unavailable", locator=None
            )
        with self.assertRaisesRegex(LedgerError, "unavailable-evidence-has-locator"):
            ledger.claim(
                **base,
                relation="unverifiable",
                evidence_level="unavailable",
                locator={"section": "results", "quote": "some households differ"},
            )
        self.assertEqual(
            [r["relation"] for r in ledger.records("claim_evidence.jsonl")],
            ["partial", "supports", "unclear", "unverifiable"],
        )
        self.assertTrue(validate_run(ledger.root)["valid"])


if __name__ == "__main__":
    unittest.main()
