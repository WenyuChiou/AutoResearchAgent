"""Explicit external materials never become an executed or screened search."""

from copy import deepcopy
from pathlib import Path
import subprocess
import sys
from unittest.mock import patch

import unittest
import test_project_stage1 as project_tests
from test_stage1_ledger import SYNTHETIC, rewrite_for_tamper_test
from stage1_ledger.identity import work_key
from stage1_ledger.journal import LedgerError, canonical, digest
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run
from research_workspace_native.project_stage1_library import _project
from research_workspace_native.session_api import SessionApiError


class ProvidedCandidateTests(unittest.TestCase):
    new = project_tests.ProjectStage1Tests.new
    initialize_body = project_tests.ProjectStage1Tests.initialize_body
    initialize = project_tests.ProjectStage1Tests.initialize
    action_body = project_tests.ProjectStage1Tests.action_body
    query_body = project_tests.ProjectStage1Tests.query_body
    private_ledger = project_tests.ProjectStage1Tests.private_ledger
    tearDown = project_tests.ProjectStage1Tests.tearDown

    def setUp(self):
        project_tests.ProjectStage1Tests.setUp(self)
        self.ref = self.new()
        self.initialize(self.ref)
        self.service.plan_query("alice-token", self.ref, self.query_body(self.ref))
        self.material = self.root / "materials"
        self.material.mkdir()
        self.data = b"category,value\nfood,100\n"
        (self.material / "table.csv").write_bytes(self.data)
        self.record = deepcopy(SYNTHETIC)
        key = work_key(self.record)
        self.work = "work-" + digest(key.encode())
        self.version = "version-" + digest(canonical([key, self.record["version"]]))

    def body(self, key="admit"):
        return dict(
            self.action_body(self.ref, key),
            source_project_ref=self.ref,
            source_relative="table.csv",
            material_sha256=digest(self.data),
            source_uri="https://example.org/table",
            original_type="text/csv; operator-extracted-table",
            record=self.record,
            work_id=self.work,
            version_id=self.version,
            reason="Explicit saved material supplied by operator; not a retrieval result.",
        )

    def admit(self, body=None):
        return self.service.admit_saved_candidate(
            "alice-token",
            self.ref,
            self.body() if body is None else body,
            materials_root=self.material,
        )

    def test_admission_unblocks_original_source_without_search_or_decision(self):
        ledger = self.private_ledger(self.ref)
        before = validate_run(ledger.root)
        with self.assertRaisesRegex(LedgerError, "source-unknown-work-version"):
            ledger.start_source(
                work_id=self.work,
                version_id=self.version,
                source_uri="https://example.org/table",
                tool="saved-local",
                request={"operation": "saved"},
                actor="alice",
                reason="saved",
            )
        self.admit()
        source = ledger.start_source(
            work_id=self.work,
            version_id=self.version,
            source_uri="https://example.org/table",
            tool="saved-local",
            request={"operation": "saved"},
            actor="alice",
            reason="saved",
        )
        self.assertEqual(ledger.event(source)["work_id"], self.work)
        after = validate_run(ledger.root)
        self.assertTrue(after["valid"], after)
        self.assertEqual(after["counts"]["queries"], 0)
        self.assertEqual(after["counts"]["backend_attempts"], 0)
        self.assertEqual(after["counts"]["decisions"], 0)
        self.assertEqual(after["counts"]["works"], 1)
        self.assertIn(before["pending_actions"][0], after["pending_actions"])
        candidate = ledger.candidates()[self.work]
        self.assertEqual(candidate["identity_status"], "unverified")
        self.assertIsNone(candidate["discoveries"][0]["query_id"])
        state = self.intake._load("alice", self.ref)
        run, _, report = self.service._ledger(state, self.intake.binding(self.ref))
        library = _project(self.ref, self.intake.binding(self.ref), run, ledger, report)
        row = library["rows"][0]
        self.assertEqual(row["screening_status"], "not-screened")
        self.assertEqual(row["origin"], "provided-saved-material")
        self.assertEqual(row["counts"]["distinct_queries"], 0)
        self.assertEqual(row["counts"]["discovery_producing_backend_attempts"], 0)
        self.assertEqual(
            report["coverage"]["blockers"],
            validate_run(ledger.root)["coverage"]["blockers"],
        )
        self.runner.assert_not_called()

    def test_same_key_and_new_key_duplicate_reopen_without_new_candidate(self):
        body = self.body()
        first = self.admit(body)
        ledger = self.private_ledger(self.ref)
        events = ledger.events()
        self.assertTrue(self.admit(body)["replayed"])
        self.admit(self.body("another-key"))
        self.assertEqual(ledger.events(), events)
        self.intake.close()
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage1 import ProjectStage1Service
        from test_workspace_project_intake import authenticate

        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1Service(self.intake)
        self.assertEqual(self.admit(body)["event_id"], first["event_id"])
        self.assertTrue(validate_run(ledger.root)["valid"])

    def test_wrong_project_version_digest_and_stale_state_refuse(self):
        ledger = self.private_ledger(self.ref)
        before = ledger.events()
        for field, value in (
            ("source_project_ref", "project-other"),
            ("input_version", 999),
            ("version_id", "version-wrong"),
            ("material_sha256", "0" * 64),
            ("ledger_state_sha256", "0" * 64),
        ):
            with self.subTest(field=field):
                body = self.body("bad-" + field)
                body[field] = value
                expected = {
                    "source_project_ref": "provided-project-differs",
                    "input_version": "intake-source-version-differs",
                    "version_id": "provided-work-version-differs",
                    "material_sha256": "provided-material-hash-differs",
                    "ledger_state_sha256": "stage1-ledger-state-stale",
                }[field]
                with self.assertRaisesRegex((SessionApiError, LedgerError), expected):
                    self.admit(body)
                self.assertEqual(ledger.events(), before)

    def test_partial_artifact_registration_and_candidate_projection_recover(self):
        ledger = self.private_ledger(self.ref)
        original = Ledger.append

        def fail_before_candidate(obj, payload):
            if payload["kind"] == "CandidateRevision":
                raise OSError("simulated power loss before candidate journal append")
            return original(obj, payload)

        with patch.object(Ledger, "append", fail_before_candidate):
            with self.assertRaises(OSError):
                ledger.admit_saved_candidate(**self.core_request(ledger))
        self.assertTrue(validate_run(ledger.root)["valid"])
        result = ledger.admit_saved_candidate(**self.core_request(ledger))
        self.assertEqual(len(ledger.candidates()), 1)
        (ledger.root / "candidates.jsonl").write_bytes(b"")
        ledger.reconcile(repair=True)
        self.assertEqual(ledger.candidates()[self.work]["event_id"], result["event_id"])
        self.assertTrue(validate_run(ledger.root)["valid"])

    def core_request(self, ledger):
        return dict(
            record=self.record,
            material=self.data,
            material_sha256=digest(self.data),
            source_uri="https://example.org/table",
            original_type="text/csv",
            actor="alice",
            reason="Operator supplied table",
            expected_state_sha256=ledger.state_hash(),
            expected_manifest_sha256=digest(canonical(ledger.manifest)),
            work_id=self.work,
            version_id=self.version,
        )

    def test_rehashed_provenance_promotion_is_invalid(self):
        self.admit()
        ledger = self.private_ledger(self.ref)

        def corrupt(rows):
            candidate = next(
                r["payload"]
                for r in rows
                if r["payload"]["kind"] == "CandidateRevision"
            )
            candidate["discoveries"][0]["provided"]["identity_status"] = "verified"

        rewrite_for_tamper_test(ledger, corrupt)
        self.assertFalse(validate_run(ledger.root)["valid"])

    def test_cli_registers_real_saved_file_and_rejects_wrong_run(self):
        ledger = self.private_ledger(self.ref)
        request = self.core_request(ledger)
        request.pop("material")
        path = self.root / "request.json"
        path.write_bytes(canonical(request))
        cli = Path(__file__).resolve().parents[1] / "cli/stage1_ledger/__main__.py"
        command = [
            sys.executable,
            str(cli),
            "--run",
            str(ledger.root),
            "admit-saved-candidate",
            "--request",
            str(path),
            "--source",
            str(self.material / "table.csv"),
        ]
        first = subprocess.run(command, capture_output=True)
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        request.update(
            expected_state_sha256=ledger.state_hash(), expected_manifest_sha256="0" * 64
        )
        path.write_bytes(canonical(request))
        second = subprocess.run(command, capture_output=True)
        self.assertEqual(second.returncode, 1)
        self.assertIn(b"provided-run-binding-differs", second.stdout)

    def test_checkpoint_and_standard_export_keep_unreviewed_candidate(self):
        from stage1_export.bundle import validate_export

        self.admit()
        self.service.checkpoint(
            "alice-token", self.ref, self.action_body(self.ref, "checkpoint")
        )
        output = self.service.export(
            "alice-token", self.ref, self.action_body(self.ref, "export")
        )
        state = self.intake._load("alice", self.ref)
        artifact = state["stage1_exports"][output["artifact_ref"]]
        self.assertTrue(
            validate_export(self.intake._path(self.ref, artifact["path"]))["valid"]
        )
        self.assertFalse(output["stage1_complete"])
        self.assertIsNone(output["canonical_package"])

    def test_invalid_origin_and_credential_url_do_not_leave_journal_artifacts(self):
        ledger = self.private_ledger(self.ref)
        before = ledger.events()
        for value in (
            "file:///private/table",
            "https://example.org/table?api_key=private",
        ):
            request = self.core_request(ledger)
            request["source_uri"] = value
            with self.assertRaises(LedgerError):
                ledger.admit_saved_candidate(**request)
            self.assertEqual(ledger.events(), before)

    def test_core_write_before_lost_receipt_holds_reopen_and_new_keys(self):
        body = self.body()
        original = Ledger.admit_saved_candidate

        def write_then_fail(ledger, **request):
            original(ledger, **request)
            raise OSError("simulated loss after durable candidate")

        with patch.object(Ledger, "admit_saved_candidate", write_then_fail):
            with self.assertRaises(SessionApiError) as failure:
                self.admit(body)
        self.assertEqual(failure.exception.receipt["status"], "execution-unknown")
        ledger = self.private_ledger(self.ref)
        before = ledger.events()
        self.assertEqual(len(ledger.candidates()), 1)
        self.assertEqual(self.admit(body)["status"], "execution-unknown")
        self.assertTrue(
            self.service.read("alice-token", self.ref)["coverage_actions"]["held"]
        )
        with self.assertRaisesRegex(
            SessionApiError, "stage1-coverage-write-outcome-unobserved"
        ):
            self.admit(self.body("new-key-after-loss"))
        self.intake.close()
        from research_workspace_native.project_intake import ProjectIntakeService
        from research_workspace_native.project_stage1 import ProjectStage1Service
        from test_workspace_project_intake import authenticate

        self.intake = ProjectIntakeService(self.root, authenticate=authenticate)
        self.service = ProjectStage1Service(self.intake)
        self.assertEqual(self.admit(body)["status"], "execution-unknown")
        with self.assertRaisesRegex(
            SessionApiError, "stage1-coverage-write-outcome-unobserved"
        ):
            self.admit(self.body("new-key-after-reopen"))
        self.assertEqual(ledger.events(), before)

    def test_invalid_provenance_preflight_does_not_hold_a_corrected_request(self):
        ledger = self.private_ledger(self.ref)
        before = ledger.events()
        history = self.intake.history("alice-token", self.ref)
        view = self.intake.read("alice-token", self.ref)
        for field, value in (
            ("source_uri", "file:///wrong/table.csv"),
            ("source_uri", "https://example.org/?api_key=private"),
            ("original_type", ""),
            ("reason", ""),
        ):
            with self.subTest(field=field, value=value):
                body = self.body("invalid-provenance-" + field)
                body[field] = value
                with self.assertRaises(LedgerError):
                    self.admit(body)
                self.assertEqual(ledger.events(), before)
                self.assertEqual(self.intake.history("alice-token", self.ref), history)
                self.assertEqual(self.intake.read("alice-token", self.ref), view)
                self.assertNotIn(
                    "api_key=private", "\n".join(self.intake.db.iterdump())
                )
                self.assertFalse(
                    self.service.read("alice-token", self.ref)["coverage_actions"][
                        "held"
                    ]
                )
        self.assertEqual(self.admit(self.body("corrected"))["status"], "saved")

    def test_included_provided_candidate_keeps_its_origin_in_the_stage2_handoff(self):
        from stage1_ledger.handoff import PROVIDED_MARK, PROVIDED_ORIGIN, handoff

        self.admit()
        ledger = self.private_ledger(self.ref)
        discovery = ledger.candidates()[self.work]["discoveries"][0]
        ledger.decide(
            self.work,
            "include",
            reason="relevant-evidence",
            rationale="included for the handoff test",
            evidence_refs=[discovery["source_ref"]],
            actor="agent",
        )
        events = [row["payload"] for row in ledger.events()]
        value = handoff(
            ledger.manifest, ledger.state_hash(), events, [], {}, "stop-sufficient"
        )
        (paper,) = value["papers"]
        self.assertEqual(paper["origin"], PROVIDED_ORIGIN)
        self.assertEqual(paper["metadata_identity"], "unverified")
        (line,) = value["manual_paper_list"].splitlines()
        self.assertTrue(line.endswith(PROVIDED_MARK))
