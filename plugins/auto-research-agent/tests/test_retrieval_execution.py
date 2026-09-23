"""Exercise the real process boundary with a synthetic CLI, never the network."""

import inspect
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
# ruff: noqa: E402 -- load the repository CLI without installing it.
from stage1_ledger.journal import LedgerError, canonical, decode, digest
from stage1_ledger.store import Ledger
from stage1_ledger.validation import replay_artifacts, validate_run
from stage1_retrieval.audit import read_audit
from stage1_retrieval.projection import project
from stage1_retrieval.runner import execute, resume
from stage1_retrieval.receipt import command, validate_execution
from stage1_retrieval.runtime_identity import capture_identity
from test_retrieval_audit import seal
from test_stage1_ledger import SYNTHETIC, rewrite_for_tamper_test
from stage1_export.bundle import (
    export_run,
    replay_export_artifacts,
    validate_export,
)


def synthetic_audit(root, backend, mode, argv):
    root.mkdir()
    (root / "artifacts").mkdir()
    rows = [SYNTHETIC] if mode in {"rows", "partial"} else []
    status = 429 if mode in {"limited", "partial"} else 410 if mode == "gone" else 200
    outcome = (
        "rate_limited"
        if status == 429
        else "not_found"
        if status == 410
        else "success"
        if rows
        else "success_empty"
    )
    outer = "partial" if mode == "partial" else outcome
    events = []
    operation = {
        "search": "backend-search",
        "enrich": "backend-lookup",
        "verify": "verify-doi",
    }.get(argv[0], argv[0])
    absent = object()

    def event(i, parent, op, kind, result=None, http=None, artifact=absent):
        identifier = str(i) * 32
        refs = []
        if artifact is not absent:
            raw = canonical(artifact)
            path = "artifacts/" + identifier + ".json"
            (root / path).write_bytes(raw)
            refs = [dict(path=path, bytes=len(raw), sha256=digest(raw))]
        value = dict(
            schema_version="1.0.0",
            type="audit_event",
            sequence=len(events) + 1,
            event=kind,
            attempt_id=identifier,
            parent_id=str(parent) * 32 if parent else None,
            operation=op,
            backend=backend if i != 1 else None,
            timestamp="2026-01-01T00:00:00Z",
            parameters={"argv": argv} if i == 1 else {},
            outcome=result,
            error_code=None,
            http_status=http,
            record_count=1
            if isinstance(artifact, dict)
            else len(artifact)
            if isinstance(artifact, list)
            else 0
            if result == "success_empty"
            else None,
            artifacts=refs,
        )
        events.append(value)

    event(1, None, "command", "started")
    event(2, 1, operation, "started")
    event(3, 2, "http", "started")
    event(3, 2, "http", "finished", "success" if status == 200 else outcome, status)
    if status == 200 or rows:
        event(4, 2, "parse", "started")
        event(4, 2, "parse", "finished", "success")
    payload = rows[0] if rows else None
    if argv[0] == "verify":
        payload = (
            None
            if mode == "verify-null"
            else {
                "ok": mode == "rows",
                "source": "doi.org",
                "reason": "synthetic resolver",
            }
        )
    event(
        2,
        1,
        operation,
        "finished",
        outer,
        artifact=payload if argv[0] in {"enrich", "verify"} else rows,
    )
    event(1, None, "command", "finished", outer)
    manifest = dict(
        schema_version="1.0.0",
        type="audit_manifest",
        created_at="2026-01-01T00:00:01Z",
        command_id="1" * 32,
        complete=True,
        outcome=outer,
        exit_code=0,
        event_count=len(events),
        events={},
    )
    seal(root, events, manifest)
    return events, manifest


def runtime(root, mode="rows"):
    script = root / "synthetic_cli.py"
    script.write_text(
        "import sys, json, hashlib\nfrom pathlib import Path\n"
        + "def canonical(v): return json.dumps(v, ensure_ascii=False, sort_keys=True, separators=(',', ':')).encode('utf-8')\n"
        + "def digest(v): return hashlib.sha256(v).hexdigest()\n"
        + "SYNTHETIC="
        + repr(SYNTHETIC)
        + "\n"
        + inspect.getsource(seal)
        + "\n"
        + inspect.getsource(synthetic_audit)
        + "\n"
        + "argv=sys.argv[1:]\n"
        + "backend=argv[argv.index('--backend')+1] if '--backend' in argv else 'doi.org' if '--doi' in argv else 'semantic-scholar'\n"
        + "synthetic_audit(Path(argv[argv.index('--audit-output')+1]), backend, "
        + repr(mode)
        + ", argv)\nprint('[]')\n",
        encoding="utf-8",
    )
    config = root / "config.json"
    config.write_bytes(b"{}")
    prefix = [sys.executable, "-I", "-B", str(script)]
    return dict(
        code_identity=capture_identity(prefix),
        schema_version="1.0.0",
        revision="a" * 40,
        status="development-unmerged",
        version="synthetic",
        wheel_sha256="b" * 64,
        audit_schema_sha256=digest(
            (PLUGIN / "schemas/research-hub-audit.v1.schema.json").read_bytes()
        ),
        executable_sha256=digest(Path(sys.executable).read_bytes()),
        argv_prefix=prefix,
        config=dict(path=str(config), sha256=digest(b"{}")),
        cwd=str(root),
        timeout_seconds=20,
    )


class ProjectionTests(unittest.TestCase):
    def test_optional_plan_rank_uses_public_default_before_launch(self):
        argv = command(
            {"argv_prefix": ["synthetic-cli"]},
            "search",
            {"query": "synthetic", "limit": 3, "rank_by": None, "year": None},
            "openalex",
            "synthetic-audit",
        )
        self.assertEqual(argv[argv.index("--rank-by") + 1], "smart")
        self.assertTrue(all(isinstance(value, str) for value in argv))

    def test_observed_success_empty_429_gone_and_partial_are_distinct(self):
        for mode, expected, n in (
            ("rows", "success_nonempty", 1),
            ("empty", "success_empty", 0),
            ("limited", "rate_limited", 0),
            ("gone", "not_found", 0),
            ("partial", "partial_failure", 1),
        ):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory) / "audit"
                synthetic_audit(root, "openalex", mode, ["search"])
                files = read_audit(root)["files"]
                value = project(
                    files,
                    backend="openalex",
                    process={"failure": None, "exit_code": 0},
                    argv=["search"],
                )
                self.assertEqual(value["outcome"], expected)
                self.assertEqual(len(value["records"] or []), n)
                self.assertEqual(value["http_attempts"], 1)
                self.assertEqual(value["provider_attempts"], 1)
                self.assertEqual(len(value["paths"]), n)
                changed = project(
                    files,
                    backend="openalex",
                    process={"failure": None, "exit_code": 0},
                    argv=["wrong-query"],
                )
                self.assertEqual(changed["outcome"], "unknown_error")

    def test_incomplete_missing_wrong_backend_and_exit_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "audit"
            synthetic_audit(root, "openalex", "empty", ["search"])
            files = read_audit(root)["files"]
            for saved, backend, process in (
                ({}, "openalex", {"failure": None, "exit_code": 0}),
                (files, "crossref", {"failure": None, "exit_code": 0}),
                (files, "openalex", {"failure": None, "exit_code": 1}),
                (files, "openalex", {"failure": "timeout", "exit_code": -1}),
            ):
                self.assertNotIn(
                    project(saved, backend=backend, process=process)["outcome"],
                    {"success_empty", "success_nonempty"},
                )

    def test_success_requires_observed_parse_and_saved_results(self):
        for change in ("parse", "artifact"):
            with (
                self.subTest(change=change),
                tempfile.TemporaryDirectory() as directory,
            ):
                root = Path(directory) / "audit"
                events, manifest = synthetic_audit(root, "openalex", "rows", ["search"])
                if change == "parse":
                    for event in events:
                        if event["operation"] == "parse":
                            event["operation"] = "opaque-step"
                else:
                    next(
                        e
                        for e in events
                        if e["operation"] == "backend-search"
                        and e["event"] == "finished"
                    )["artifacts"] = []
                seal(root, events, manifest)
                value = project(
                    read_audit(root)["files"],
                    backend="openalex",
                    process={"failure": None, "exit_code": 0},
                )
                self.assertEqual(value["outcome"], "unknown_error")

    def test_empty_verification_result_cannot_be_success_evidence(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory) / "audit"
            synthetic_audit(root, "doi.org", "verify-null", ["verify"])
            value = project(
                read_audit(root)["files"],
                backend="doi.org",
                process={"failure": None, "exit_code": 0},
                operation="verify",
                argv=["verify"],
            )
            self.assertEqual(value["outcome"], "unknown_error")
            self.assertEqual(value["error"], "unknown")


class ExecutionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)

    def create(self, mode="rows"):
        pin = runtime(self.root, mode)
        return Ledger.create(
            self.root / "run",
            run_id="synthetic",
            objective="Synthetic query",
            research_hub_pin=pin,
        )

    def test_saved_artifact_replay_works_without_original_runtime(self):
        ledger = self.create()
        query = ledger.start("search", dict(query="synthetic query", limit=3))
        execute(ledger.root, query, "openalex")
        ledger.complete_query(query)
        ledger.extract()
        ledger.checkpoint()
        exported = self.root / "export"
        self.assertTrue(export_run(ledger.root, exported)["valid"])

        copied_run, copied_export = (
            self.root / "copied-run",
            self.root / "copied-export",
        )
        shutil.copytree(ledger.root, copied_run)
        shutil.copytree(exported, copied_export)
        Path(ledger.manifest["research_hub_pin"]["argv_prefix"][-1]).unlink()
        self.assertFalse(validate_run(copied_run)["valid"])
        self.assertFalse(validate_export(copied_export)["valid"])

        cli = Path(__file__).resolve().parents[1] / "cli"
        for argv in (
            ["stage1_ledger", "--run", str(copied_run), "validate"],
            ["stage1_export", "validate", str(copied_export)],
        ):
            result = subprocess.run(
                [sys.executable, "-m", *argv], cwd=cli, capture_output=True
            )
            self.assertEqual(result.returncode, 1)

        with (
            patch(
                "stage1_retrieval.runtime_identity.verify_identity",
                side_effect=AssertionError("portable replay must not inspect runtime"),
            ),
            patch(
                "stage1_retrieval.runner.subprocess.Popen",
                side_effect=AssertionError("portable replay must not launch runtime"),
            ),
            patch(
                "socket.socket",
                side_effect=AssertionError("portable replay must not open a socket"),
            ),
        ):
            run_report = replay_artifacts(copied_run)
            export_report = replay_export_artifacts(copied_export)
        self.assertTrue(run_report["artifact_valid"], run_report)
        self.assertTrue(export_report["artifact_valid"], export_report)
        self.assertEqual(run_report["kind"], "Stage1SavedArtifactReplay")
        self.assertEqual(export_report["kind"], "Stage1ExportArtifactReplay")
        self.assertEqual(run_report["scope"], "saved-artifacts-only")
        self.assertEqual(export_report["scope"], "saved-artifacts-only")
        self.assertEqual(run_report["runtime_attestation"], "not-rechecked")
        self.assertEqual(export_report["runtime_attestation"], "not-rechecked")
        self.assertEqual(
            run_report["state_sha256"], export_report["source_state_sha256"]
        )

        for argv in (
            ["stage1_ledger", "--run", str(copied_run), "replay-artifacts"],
            ["stage1_export", "replay-artifacts", str(copied_export)],
        ):
            result = subprocess.run(
                [sys.executable, "-m", *argv], cwd=cli, capture_output=True
            )
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertTrue(decode(result.stdout, "portable CLI")["artifact_valid"])

        artifact = next(
            row["payload"]["ref"]["path"]
            for row in ledger.events()
            if row["payload"]["kind"] == "ArtifactStored"
        )
        (copied_run / artifact).unlink()
        (copied_export / "source" / artifact).unlink()
        self.assertFalse(replay_artifacts(copied_run)["artifact_valid"])
        self.assertFalse(replay_export_artifacts(copied_export)["artifact_valid"])

    def test_real_process_dedup_provenance_reversal_and_missing_raw(self):
        ledger = self.create()
        query = ledger.start(
            "search",
            dict(query="synthetic query", limit=3, year="2024-2026", rank_by="year"),
        )
        for backend in ("openalex", "crossref"):
            execute(ledger.root, query, backend)
        ledger.complete_query(query)
        result = ledger.extract()
        self.assertEqual(
            result, dict(new_discoveries=2, works=1, extraction_failures=0)
        )
        work = next(iter(ledger.candidates().values()))
        for decision in ("include", "exclude"):
            ledger.decide(
                work["work_id"],
                decision,
                reason="synthetic",
                rationale="Synthetic reversal",
                evidence_refs=[work["discoveries"][0]["source_ref"]],
            )
        self.assertEqual(len(ledger.records("decision_events.jsonl")), 2)
        report = validate_run(ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertNotEqual(
            ledger.checkpoint()["stage_result"]["next_allowed_action"],
            "stop-sufficient",
        )
        exported = self.root / "export"
        self.assertTrue(export_run(ledger.root, exported)["valid"])
        self.assertTrue(validate_export(exported)["valid"])
        efficiency = decode((exported / "efficiency.json").read_bytes(), "efficiency")
        self.assertEqual(efficiency["source_mode"], "research-hub-cli")
        self.assertEqual(efficiency["retrieval_usage"]["completed_cli_invocations"], 2)
        self.assertEqual(efficiency["retrieval_usage"]["provider_attempts"], 2)
        completion = next(
            r["payload"]
            for r in ledger.events()
            if r["payload"]["kind"] == "ActionFinished"
        )
        receipt = decode(ledger.read_ref(completion["execution_ref"]), "receipt")
        self.assertEqual(len(receipt["projection"]["paths"]), 1)
        path = ledger.root / receipt["audit_files"]["events.jsonl"]["path"]
        path.unlink()
        self.assertFalse(validate_run(ledger.root)["valid"])

    def test_partial_results_are_extracted_but_query_remains_failed(self):
        ledger = self.create("partial")
        query = ledger.start("search", dict(query="synthetic query", limit=3))
        execute(ledger.root, query, "openalex")
        ledger.complete_query(query)
        ledger.extract()
        self.assertEqual(
            ledger.records("query_events.jsonl")[0]["outcome"], "partial_failure"
        )
        report = validate_run(ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertEqual(report["counts"]["works"], 1)
        self.assertEqual(report["counts"]["backend_failures"], 1)

    def test_resume_no_reexecution_and_rejects_changed_bytes(self):
        ledger = self.create()
        query = ledger.start("search", dict(query="synthetic query", limit=3))
        with patch(
            "stage1_retrieval.runner.resume",
            side_effect=RuntimeError("synthetic crash after process exit"),
        ):
            with self.assertRaises(RuntimeError):
                execute(ledger.root, query, "openalex")
        attempt = next(
            p["payload"]
            for p in ledger.events()
            if p["payload"]["kind"] == "ActionStarted"
            and p["payload"]["operation"] == "backend"
        )
        with self.assertRaisesRegex(LedgerError, "attempt-already-recorded"):
            ledger.start(
                "backend", attempt["arguments"], backend="openalex", parent_id=query
            )
        with patch(
            "stage1_retrieval.runner.subprocess.Popen",
            side_effect=AssertionError("must not retry"),
        ):
            with self.assertRaisesRegex(LedgerError, "attempt-already-recorded"):
                execute(ledger.root, query, "openalex")
            capture = (
                ledger.root / attempt["arguments"]["capture_directory"] / "stdout.bin"
            )
            original = capture.read_bytes()
            capture.write_bytes(b"changed")
            with self.assertRaisesRegex(LedgerError, "changed-capture"):
                resume(ledger.root, attempt["event_id"])
            capture.write_bytes(original)
            resume(ledger.root, attempt["event_id"])
            with self.assertRaisesRegex(LedgerError, "attempt-not-open"):
                resume(ledger.root, attempt["event_id"])

    def test_saved_replay_does_not_inspect_caller_working_directory(self):
        ledger = self.create()
        query = ledger.start("search", dict(query="synthetic query", limit=3))
        completion = ledger.event(
            execute(ledger.root, query, "openalex"), "ActionFinished"
        )
        attempt = ledger.event(completion["attempt_id"], "ActionStarted")
        with patch(
            "stage1_retrieval.receipt.Path.cwd",
            side_effect=AssertionError("saved replay must not inspect cwd"),
        ):
            validate_execution(ledger.manifest, attempt, completion, ledger.read_ref)

    def test_rehashed_forged_completion_is_rejected(self):
        ledger = self.create("limited")
        query = ledger.start("search", dict(query="synthetic query", limit=3))
        completion = ledger.event(
            execute(ledger.root, query, "openalex"), "ActionFinished"
        )
        ledger.complete_query(query)
        self.assertTrue(validate_run(ledger.root)["valid"])

        # Rehashing a receipt cannot let its nested audit borrow another producer.
        attempt = ledger.event(completion["attempt_id"], "ActionStarted")
        receipt = decode(ledger.read_ref(completion["execution_ref"]), "receipt")
        next(iter(receipt["audit_files"].values()))["producer"] = query
        forged = dict(
            completion,
            execution_ref=ledger.save_bytes(
                canonical(receipt), producer=attempt["event_id"]
            ),
        )
        with self.assertRaisesRegex(LedgerError, "audit-artifact-producer-mismatch"):
            validate_execution(ledger.manifest, attempt, forged, ledger.read_ref)

        def mutate(rows):
            next(
                r["payload"] for r in rows if r["payload"]["kind"] == "ActionFinished"
            )["exit_code"] = 9

        rewrite_for_tamper_test(ledger, mutate)
        report = validate_run(ledger.root)
        self.assertFalse(report["valid"])
        self.assertIn("receipt-exit-code", report["errors"][0])

    def test_timeout_and_missing_audit_do_not_become_empty_or_zero_provider_calls(self):
        for mode in ("timeout", "missing"):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                root = Path(directory)
                pin = runtime(root)
                script = root / "synthetic_cli.py"
                script.write_text(
                    "import time; time.sleep(5)\n"
                    if mode == "timeout"
                    else "print('[]')\n",
                    encoding="utf-8",
                )
                pin["timeout_seconds"] = 0.1 if mode == "timeout" else 20
                pin["code_identity"] = capture_identity(pin["argv_prefix"])
                ledger = Ledger.create(
                    root / "run",
                    run_id="synthetic",
                    objective="synthetic",
                    research_hub_pin=pin,
                )
                query = ledger.start("search", dict(query="synthetic", limit=3))
                finished = ledger.event(
                    execute(ledger.root, query, "openalex"), "ActionFinished"
                )
                self.assertEqual(
                    finished["outcome"],
                    "timeout" if mode == "timeout" else "unknown_error",
                )
                receipt = decode(ledger.read_ref(finished["execution_ref"]), "receipt")
                self.assertIsNone(receipt["projection"]["provider_attempts"])
                ledger.complete_query(query)
                ledger.extract()
                self.assertTrue(validate_run(ledger.root)["valid"])

    def test_lookup_and_resolver_do_not_authenticate_identity_or_claims(self):
        ledger = self.create()
        query = ledger.start("search", dict(query="synthetic", limit=3))
        execute(ledger.root, query, "openalex")
        ledger.complete_query(query)
        ledger.extract()
        work = next(iter(ledger.candidates().values()))
        for operation, backend in (
            ("enrich", "semantic-scholar"),
            ("verify", "doi.org"),
        ):
            query = ledger.start(
                "search",
                dict(
                    operation=operation,
                    limit=3,
                    coverage=dict(
                        seed_work_id=work["work_id"],
                        seed_version_id=work["version_ids"][0],
                    ),
                ),
            )
            completed = ledger.event(
                execute(ledger.root, query, backend), "ActionFinished"
            )
            self.assertEqual(
                completed["outcome"],
                "success_nonempty" if operation == "enrich" else "success_evidence",
            )
            ledger.complete_query(query)
            ledger.extract()
        resolver = completed["stdout"]
        comparison = ledger.compare_identity(
            target_work_id=work["work_id"],
            target_discovery_id=work["discoveries"][0]["discovery_id"],
            resolver_ref=resolver,
            assessor="synthetic",
        )
        self.assertEqual(
            ledger.event(comparison, "IdentityComparison")["work_agreement"],
            "unverified",
        )
        self.assertEqual(
            ledger.identity_status()["identity_verification"], "not-performed"
        )
        self.assertEqual(ledger.records("claim_evidence.jsonl"), [])
        self.assertEqual(len(ledger.candidates()[work["work_id"]]["discoveries"]), 2)
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_frozen_plan_and_citation_backends_and_development_gate(self):
        from test_stage1_coverage import proposal
        from stage1_coverage.plan import compile_plan
        from stage1_coverage.run import CoverageLedger
        from stage1_coverage.policy import query_complete

        value = proposal()
        value["clusters"] = value["clusters"][:1]
        bundle = self.root / "plan"
        compile_plan(value, bundle, as_of="2026-09-20", actor="synthetic")
        ledger = CoverageLedger.create(
            self.root / "run",
            run_id="synthetic",
            objective=value["topic"],
            research_hub_pin=runtime(self.root),
        )
        ledger.bind_plan(
            bundle,
            backends=["openalex", "crossref"],
            citation_backends=["semantic-scholar"],
            limit=10,
        )
        ledger.open_round()
        for planned in ledger.coverage_state().queries:
            query = ledger.start_planned(planned)
            for backend in ("openalex", "crossref"):
                execute(ledger.root, query, backend)
            completed = ledger.complete_query(query)
            ledger.receipt(
                completed, truncated=False, note="Synthetic complete response"
            )
        ledger.extract()
        work = next(iter(ledger.candidates().values()))
        for operation in ("references", "cited-by"):
            query = ledger.start_expansion(
                operation, work["work_id"], work["version_ids"][0]
            )
            execute(ledger.root, query, "semantic-scholar")
            completed = ledger.complete_query(query)
            ledger.receipt(
                completed, truncated=False, note="Synthetic complete citation response"
            )
            self.assertTrue(
                query_complete(
                    ledger.coverage_state(), ledger.event(completed, "QueryEvent")
                )
            )
        ledger.extract()
        self.assertTrue(ledger.close_round()["summary"]["complete"])
        report = validate_run(ledger.root)
        self.assertTrue(report["valid"], report)
        self.assertIn("development-dependency-unmerged", report["coverage"]["blockers"])
        self.assertNotEqual(
            ledger.checkpoint()["stage_result"]["next_allowed_action"],
            "stop-sufficient",
        )


if __name__ == "__main__":
    unittest.main()
