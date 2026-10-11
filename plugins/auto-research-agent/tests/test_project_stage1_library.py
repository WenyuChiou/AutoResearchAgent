"""Actual Core/SQLite screening history; authored saved sources, no live calls."""

from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import research_workspace_native.project_stage1_library as library_module
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_library import ProjectStage1LibraryService
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import sha
from stage1_ledger.journal import canonical
from stage1_ledger.validation import validate_run
from test_workspace_project_intake import bound_body, compile_body, submit_body


def library_authenticate(credential):
    return {
        "local-library-test-token-with-at-least-32-characters": "local-viewer",
        "other-library-test-token-with-at-least-32-characters": "other-viewer",
    }.get(credential)


class Stage1LibraryFixture:
    """Reusable real services; HTTP tests may call setUp/tearDown directly."""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(prefix="stage1-library-")
        if callable(getattr(self, "addCleanup", None)):
            self.addCleanup(Stage1LibraryFixture.tearDown, self)
        try:
            self._setUp()
        except BaseException:
            Stage1LibraryFixture.tearDown(self)
            raise

    def _setUp(self):
        self.root = Path(self.tmp.name)
        self.token = "local-library-test-token-with-at-least-32-characters"
        self.principal = "local-viewer"
        self.intake = ProjectIntakeService(self.root, authenticate=library_authenticate)
        self.runner = Mock(side_effect=AssertionError("external query dispatched"))
        self.stage1 = ProjectStage1Service(self.intake, query_runner=self.runner)
        self.library = ProjectStage1LibraryService(self.stage1)
        self.ref = self.new("fixture-project")
        state = self.intake._load(self.principal, self.ref)
        run = state["stage1_runs"][state["stage1_active"]]
        self.ledger = CoverageLedger(self.intake._path(self.ref, run["path"]))
        self.metadata = [
            dict(
                title=f"Synthetic {name} evidence",
                authors=["Fixture Author"],
                year=2024,
                doi=f"10.5555/library-{name}",
                version="v1",
            )
            for name in ("retained", "excluded", "pending", "unscreened")
        ]
        self.planned = list(self.ledger.coverage_state().queries)
        self.query(0, self.metadata)
        self.query(1, [self.metadata[0], dict(self.metadata[1], version="v2")])
        self.query(2, [], failure=True)
        self.work_by_name = {
            name: next(
                c["work_id"]
                for c in self.ledger.candidates().values()
                if c["discoveries"][-1]["record"]["title"]
                == f"Synthetic {name} evidence"
            )
            for name in ("retained", "excluded", "pending", "unscreened")
        }
        for name, status in (
            ("retained", "include"),
            ("excluded", "include"),
            ("excluded", "exclude"),
            ("pending", "pending"),
        ):
            self.decision(name, status)
        self.source, self.source_text = self.source_attempt("retained", "available")
        candidate = self.ledger.candidates()[self.work_by_name["retained"]]
        self.claim = self.ledger.claim(
            work_id=candidate["work_id"],
            version_id=candidate["discoveries"][-1]["version_id"],
            claim_text="Authored retained observation.",
            relation="supports",
            evidence_level="full_text",
            locator={"section": "fixture", "quote": "Authored retained observation."},
            source_ref=self.source_text,
            verifier={
                "actor": "fixture",
                "actor_type": "agent",
                "method": "saved-span",
            },
        )
        self.ledger.review_work(
            work_id=candidate["work_id"],
            version_id=candidate["discoveries"][-1]["version_id"],
            cluster_claims={
                self.ledger.coverage_state().plan["proposal"]["clusters"][0][
                    "cluster_id"
                ]: self.claim
            },
            identity_status="unverifiable",
            identity_claims={
                field: None
                for field in ("title", "authors", "year", "identifier", "version")
            },
            closest=False,
            assessor="fixture",
            rationale="Saved claim; identity remains unverified.",
        )
        self.checkpoint = self.ledger.checkpoint()
        if not validate_run(self.ledger.root)["valid"]:
            raise AssertionError("invalid real Core fixture")

    def tearDown(self):
        try:
            if getattr(self, "intake", None) is not None:
                self.intake.close()
        finally:
            self.tmp.cleanup()

    def new(self, key, topic="Synthetic sensor evidence and validation"):
        ref = self.intake.create(self.token, {"key": key, "topic": topic})[
            "project_ref"
        ]
        self.intake.submit(
            self.token, ref, submit_body(self.intake.read(self.token, ref))
        )
        self.intake.compile(
            self.token, ref, compile_body(self.intake.read(self.token, ref))
        )
        offer = self.stage1.read(self.token, ref)["initialization_offer"]
        self.stage1.initialize(
            self.token,
            ref,
            dict(
                bound_body(self.intake.read(self.token, ref), "initialize"),
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            ),
        )
        return ref

    def query(self, planned_index, records, *, failure=False):
        coverage = self.ledger.coverage_state()
        query = self.ledger.start_planned(self.planned[planned_index])
        attempt = self.ledger.start(
            "backend",
            {"input": coverage.arguments(self.planned[planned_index])},
            backend="openalex",
            parent_id=query,
        )
        raw = self.ledger.save_bytes(
            b"authored rate limit" if failure else canonical(records), producer=attempt
        )
        empty = self.ledger.save_bytes(b"", producer=attempt)
        self.ledger.finish(
            attempt,
            outcome="rate_limited" if failure else "success_nonempty",
            http_status=429 if failure else 200,
            exit_code=1 if failure else 0,
            stdout=raw,
            stderr=empty,
            records=None if failure else raw,
        )
        completed = self.ledger.complete_query(query)
        self.ledger.receipt(
            completed,
            truncated=False,
            note="Saved synthetic response, no external execution.",
        )
        self.ledger.extract()

    def decision(self, name, status):
        work = self.work_by_name[name]
        return self.ledger.decide(
            work,
            status,
            reason="fixture-screening",
            rationale=f"Saved {status} rationale for {name}.",
            evidence_refs=[
                self.ledger.candidates()[work]["discoveries"][-1]["source_ref"]
            ],
        )

    def source_attempt(self, name, outcome=None):
        candidate = self.ledger.candidates()[self.work_by_name[name]]
        version = candidate["discoveries"][-1]["version_id"]
        source = self.ledger.start_source(
            work_id=candidate["work_id"],
            version_id=version,
            source_uri=f"https://example.org/{name}",
            tool="fixture-reader",
            request={"public_only": True},
            actor="fixture",
            reason="Authored saved observation; no network call.",
        )
        if outcome is None:
            return source, None
        text = self.ledger.save_bytes(
            b"Authored retained observation.", producer=source
        )
        self.ledger.finish_source(
            attempt_id=source,
            outcome=outcome,
            observed_at=self.ledger.clock(),
            http_status=200,
            resolved_uri=f"https://example.org/{name}",
            raw_ref=text,
            text_ref=text if outcome == "available" else None,
            extraction={"method": "identity", "version": "fixture"}
            if outcome == "available"
            else None,
            reason="Saved authored fixture outcome.",
        )
        return source, text

    def inventory(self):
        return (
            {
                p.relative_to(self.root).as_posix(): p.read_bytes()
                for p in self.root.rglob("*")
                if p.is_file() and not p.name.startswith("project-intake.sqlite")
            },
            tuple(self.intake.db.iterdump()),
        )


class ProjectStage1LibraryTests(Stage1LibraryFixture, unittest.TestCase):
    def test_all_candidates_and_exact_history_remain_distinct_from_reading(self):
        envelope = self.library.read(self.token, self.ref)
        projection = envelope["projection"]
        self.assertEqual(envelope["projection_sha256"], sha(canonical(projection)))
        binding = projection["binding"]
        self.assertEqual(binding["project_ref"], self.ref)
        self.assertEqual(
            binding["brief_sha256"], self.intake.binding(self.ref)["brief_sha256"]
        )
        self.assertEqual(binding["ledger_state_sha256"], self.ledger.state_hash())
        self.assertEqual(projection["counts"]["core"]["discoveries"], 6)
        self.assertEqual(projection["counts"]["core"]["backend_failures"], 1)
        self.assertEqual(
            [
                projection["counts"][name]
                for name in (
                    "total_candidates",
                    "include",
                    "exclude",
                    "pending",
                    "not_screened",
                )
            ],
            [4, 1, 1, 1, 1],
        )
        rows = {row["work_id"]: row for row in projection["rows"]}
        retained, excluded, pending, unscreened = (
            rows[self.work_by_name[name]]
            for name in ("retained", "excluded", "pending", "unscreened")
        )
        self.assertEqual(retained["counts"]["discoveries"], 2)
        self.assertEqual(retained["counts"]["distinct_queries"], 2)
        self.assertEqual(retained["counts"]["recorded_rounds"], 1)
        self.assertTrue(retained["counts"]["round_ids_known"])
        self.assertEqual(retained["reading"]["complete_body_reading"], "Unknown")
        self.assertEqual(retained["metadata_evidence_level"], "metadata")
        self.assertEqual(retained["reading"]["status"], "claim-evidence-recorded")
        self.assertEqual(len(excluded["versions"]), 2)
        self.assertEqual(
            excluded["decision_history"][1]["reverses_event_id"],
            excluded["decision_history"][0]["event_id"],
        )
        self.assertEqual(pending["current_decision"]["new_decision"], "pending")
        self.assertIsNone(unscreened["current_decision"])
        self.assertEqual(unscreened["screening_status"], "not-screened")
        for row in (excluded, pending, unscreened):
            self.assertEqual(row["source_status"], "not-acquired")
            self.assertEqual(row["reading"]["status"], "no-reading-evidence-recorded")
            self.assertIsNone(row["relevance"]["score"])
        for snapshot in projection["snapshots"]:
            core = {
                k: v
                for k, v in snapshot.items()
                if k not in {"sha256", "persisted_refs", "origin"}
            }
            self.assertEqual(snapshot["sha256"], sha(canonical(core)))
            self.assertEqual(
                self.ledger.read_ref(snapshot["persisted_refs"][0]), canonical(core)
            )
        self.assertFalse(projection["stage1_complete"])
        self.assertIsNone(projection["canonical_package"])
        self.assertFalse(projection["execution_authorized"])

    def test_repeated_get_and_sqlite_reopen_are_passive(self):
        before = self.inventory()
        with (
            patch.object(
                CoverageLedger, "checkpoint", side_effect=AssertionError("GET wrote")
            ),
            patch.object(
                CoverageLedger,
                "start_source",
                side_effect=AssertionError("GET acquired"),
            ),
            patch.object(
                CoverageLedger, "start", side_effect=AssertionError("GET searched")
            ),
            patch.object(self.intake, "_save", side_effect=AssertionError("GET saved")),
        ):
            first = self.library.read(self.token, self.ref)
            self.assertEqual(first, self.library.read(self.token, self.ref))
        self.assertEqual(before, self.inventory())
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=library_authenticate)
        self.stage1 = ProjectStage1Service(self.intake, query_runner=self.runner)
        self.library = ProjectStage1LibraryService(self.stage1)
        self.assertEqual(first, self.library.read(self.token, self.ref))
        self.assertEqual(before, self.inventory())
        self.runner.assert_not_called()

    def test_expected_hash_state_and_input_version_reject_stale_reads(self):
        old = self.library.read(self.token, self.ref)
        self.assertEqual(
            old,
            self.library.read(
                self.token,
                self.ref,
                expected_input_version=1,
                expected_ledger_state_sha256=self.ledger.state_hash(),
                expected_projection_sha256=old["projection_sha256"],
            ),
        )
        for kwargs in (
            {"expected_input_version": 2},
            {"expected_projection_sha256": "0" * 64},
            {"expected_ledger_state_sha256": "0" * 64},
            {"expected_input_version": True},
            {"expected_projection_sha256": "bad"},
        ):
            with self.subTest(kwargs=kwargs), self.assertRaises(SessionApiError):
                self.library.read(self.token, self.ref, **kwargs)
        self.decision("pending", "exclude")
        with self.assertRaisesRegex(SessionApiError, "ledger-state-stale"):
            self.library.read(
                self.token,
                self.ref,
                expected_ledger_state_sha256=old["projection"]["binding"][
                    "ledger_state_sha256"
                ],
            )
        fresh = self.library.read(self.token, self.ref)
        self.assertFalse(fresh["projection"]["checkpoint"]["current"])
        self.assertTrue(
            all(not s["persisted_refs"] for s in fresh["projection"]["snapshots"])
        )

    def test_source_failures_pending_and_import_intents_are_not_reading(self):
        self.source_attempt("excluded", "parse_error")
        self.source_attempt("pending")
        candidate = self.ledger.candidates()[self.work_by_name["unscreened"]]
        imported = self.ledger.start_source_import(
            work_id=candidate["work_id"],
            version_id=candidate["version_ids"][0],
            source_uri="https://example.org/saved",
            actor="fixture",
            reason="Saved import intent, not finished reading.",
        )
        projection = self.library.read(self.token, self.ref)["projection"]
        rows = {row["work_id"]: row for row in projection["rows"]}
        self.assertEqual(
            rows[self.work_by_name["excluded"]]["source_status"], "parse_error"
        )
        self.assertEqual(rows[self.work_by_name["pending"]]["source_status"], "pending")
        self.assertEqual(
            rows[candidate["work_id"]]["source_status"], "saved-import-intent-recorded"
        )
        self.assertEqual(
            (
                projection["counts"]["source_failures"],
                projection["counts"]["source_pending"],
            ),
            (1, 1),
        )
        self.ledger.save_bytes(
            b"Saved import bytes, not model reading.", producer=imported
        )
        row = next(
            r
            for r in self.library.read(self.token, self.ref)["projection"]["rows"]
            if r["work_id"] == candidate["work_id"]
        )
        self.assertEqual(row["source_status"], "saved-import-bytes-recorded")
        self.assertEqual(len(row["source_imports"][0]["artifacts"]), 1)
        self.assertEqual(row["reading"]["model_execution"], "Unknown")

    def test_principal_and_query_owner_refuse_without_restore(self):
        before = self.inventory()
        for credential in (
            "other-library-test-token-with-at-least-32-characters",
            "invalid",
        ):
            with self.assertRaises(SessionApiError):
                self.library.read(credential, self.ref)
        self.assertEqual(before, self.inventory())
        state = self.intake._load(self.principal, self.ref)
        state["stage1_runs"][state["stage1_active"]]["query_owned"] = True
        self.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (canonical(state).decode(), self.ref),
        )
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "query-owner-unconnected"):
            self.library.read(self.token, self.ref)
        self.assertEqual(before, self.inventory())

    def test_frontier_change_during_projection_refuses_old_envelope(self):
        original = library_module._project

        def changed(*args):
            result = original(*args)
            self.decision("pending", "exclude")
            return result

        with (
            patch.object(library_module, "_project", side_effect=changed),
            self.assertRaisesRegex(SessionApiError, "library-frontier-changed"),
        ):
            self.library.read(self.token, self.ref)
        self.assertEqual(
            next(
                row
                for row in self.library.read(self.token, self.ref)["projection"]["rows"]
                if row["work_id"] == self.work_by_name["pending"]
            )["screening_status"],
            "exclude",
        )

    def test_checkpoint_change_invalidates_projection_without_semantic_change(self):
        old = self.library.read(self.token, self.ref)
        state = self.ledger.state_hash()
        self.ledger.checkpoint()
        self.assertEqual(self.ledger.state_hash(), state)
        with self.assertRaisesRegex(SessionApiError, "projection-stale"):
            self.library.read(
                self.token,
                self.ref,
                expected_projection_sha256=old["projection_sha256"],
            )

    def test_original_artifact_hash_and_manifest_drift_fail_closed(self):
        path = self.ledger.root / self.source_text["path"]
        raw = path.read_bytes()
        path.write_bytes(b"Changed source bytes.")
        with self.assertRaisesRegex(SessionApiError, "ledger-replay-failed"):
            self.library.read(self.token, self.ref)
        path.write_bytes(raw)
        (self.ledger.root / "run_manifest.json").write_bytes(b"{}\n")
        with self.assertRaisesRegex(SessionApiError, "ledger-manifest-differs"):
            self.library.read(self.token, self.ref)

    def test_raw_brief_drift_refuses_without_saved_state_or_event_changes(self):
        binding = self.intake.binding(self.ref)
        path = binding["brief_path"]
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        try:
            before = self.inventory()
            with self.assertRaisesRegex(SessionApiError, "intake-source-bytes-differ"):
                self.library.read(self.token, self.ref)
            self.assertEqual(before, self.inventory())
        finally:
            path.write_bytes(original)
        self.assertEqual(
            self.library.read(self.token, self.ref)["projection"]["binding"][
                "brief_sha256"
            ],
            binding["brief_sha256"],
        )

    def test_confirmed_input_version_two_cannot_relabel_old_ledger(self):
        old = self.library.read(self.token, self.ref)
        old_binding = self.intake.binding(self.ref)
        old_brief = old_binding["brief_path"].read_bytes()
        old_journal = (self.ledger.root / "stage_events.jsonl").read_bytes()
        self.intake.revise(
            self.token,
            self.ref,
            dict(
                bound_body(self.intake.read(self.token, self.ref), "revise-v2"),
                topic="Synthetic battery safety with independent validation",
            ),
        )
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "library-input-version-stale"):
            self.library.read(self.token, self.ref, expected_input_version=1)
        self.assertEqual(before, self.inventory())
        body = submit_body(self.intake.read(self.token, self.ref))
        self.intake.submit(self.token, self.ref, dict(body, key="confirm-v2"))
        body = compile_body(self.intake.read(self.token, self.ref))
        self.intake.compile(self.token, self.ref, dict(body, key="compile-v2"))
        self.assertEqual(self.intake.binding(self.ref)["input_version"], 2)
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "ledger-source-version-differs"):
            self.library.read(self.token, self.ref, expected_input_version=2)
        self.assertEqual(before, self.inventory())
        self.assertEqual(old_binding["brief_path"].read_bytes(), old_brief)
        self.assertEqual(
            (self.ledger.root / "stage_events.jsonl").read_bytes(), old_journal
        )
        self.assertEqual(old["input_version"], 1)

    def test_projection_bound_refuses_instead_of_truncating_candidates(self):
        before = self.inventory()
        with (
            patch.object(library_module, "MAX_PROJECTION_BYTES", 32),
            self.assertRaisesRegex(
                SessionApiError, "complete-projection-bound-exceeded"
            ),
        ):
            self.library.read(self.token, self.ref)
        self.assertEqual(before, self.inventory())

    def test_selected_version_does_not_adopt_historical_claims_or_source(self):
        replacement = dict(self.metadata[0], version="v2")
        self.query(3, [replacement])
        projection = self.library.read(self.token, self.ref)["projection"]
        row = next(
            r
            for r in projection["rows"]
            if r["work_id"] == self.work_by_name["retained"]
        )
        self.assertEqual(len(row["versions"]), 2)
        self.assertEqual(row["source_status"], "not-acquired")
        self.assertEqual(row["reading"]["selected_version_claim_count"], 0)
        self.assertEqual(len(row["claims"]), 1)
        self.assertIsNone(row["current_review"])
        self.assertEqual(row["reading"]["status"], "no-reading-evidence-recorded")


if __name__ == "__main__":
    unittest.main()
