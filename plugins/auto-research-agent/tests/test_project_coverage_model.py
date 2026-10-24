"""Actual saved Core/model permits across opt-in format changes; no provider call."""

import unittest
from unittest.mock import patch
import test_project_stage1_delivery as delivery_fixture
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.session_api import SessionApiError
from test_project_stage1_records import saved_stage1_case
from test_workspace_project_intake import bound_body


class CoverageModelTests(unittest.TestCase):
    def test_saved_old_and_new_offers_rebuild_their_own_version_after_reopen(self):
        original = delivery_fixture.submit_body

        def funded(view):
            body = original(view)
            body["budgets"].update(model_calls=2, seconds=120)
            return body

        with (
            patch.object(delivery_fixture, "submit_body", side_effect=funded),
            saved_stage1_case() as (case, fx),
        ):
            ref, ledger = fx["ref"], fx["ledger"]
            work = fx["records"]["papers"][0]["work_id"]
            providers = []

            def factory(**kw):
                providers.append(kw)
                raise AssertionError("This receiving test must never start a model")

            def model(coverage):
                return ProjectModelService(
                    case.intake,
                    provider_factory=factory,
                    model="synthetic-no-run",
                    clock=lambda: 1_900_000_000,
                    reading_records=case.producer,
                    analysis_coverage=coverage,
                )

            old = model(False)
            try:
                preview = old.full_analysis_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=1,
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
                v = case.intake.read("alice-token", ref)
                saved = old.authorize(
                    "alice-token",
                    ref,
                    dict(
                        **bound_body(v, "legacy-analysis"),
                        operation="analyze-full-paper",
                        work_ref=work,
                        snapshot_sha256=preview["snapshot_sha256"],
                        confirmed=True,
                        user_input="Synthetic saved-context authorization only, no model execution.",
                    ),
                )
                self.assertTrue(saved["connected"], saved)
                state = case.intake._load("alice", ref)
                auth = old._row(state)["authorizations"]["legacy-analysis"]
                path = case.intake._path(ref, auth["artifact"]["path"])
                permit_hash = auth["artifact"]["sha256"]
                old_offer = old._row(state)["offers"][saved["offer"]["offer_ref"]]
                self.assertEqual(
                    old_offer["context"]["saved_reading"]["schema_version"], "1.0.0"
                )
            finally:
                old.close()
            new = model(True)
            try:
                reopened = new.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=path,
                    permit_sha256=permit_hash,
                )
                self.assertEqual(reopened["offer_ref"], saved["offer"]["offer_ref"])
                state = case.intake._load("alice", ref)
                new._guard(ref, new._row(state)["offers"][reopened["offer_ref"]])
                preview = new.full_analysis_offer(
                    "alice-token",
                    ref,
                    work,
                    expected_input_version=1,
                    expected_ledger_state_sha256=ledger.state_hash(),
                )
                v = case.intake.read("alice-token", ref)
                saved_new = new.authorize(
                    "alice-token",
                    ref,
                    dict(
                        **bound_body(v, "covered-analysis"),
                        operation="analyze-full-paper",
                        work_ref=work,
                        snapshot_sha256=preview["snapshot_sha256"],
                        confirmed=True,
                        user_input="Synthetic versioned analysis authorization only, no model execution.",
                    ),
                )
                self.assertTrue(saved_new["connected"], saved_new)
                state = case.intake._load("alice", ref)
                auth_new = new._row(state)["authorizations"]["covered-analysis"]
                newpath = case.intake._path(ref, auth_new["artifact"]["path"])
                newhash = auth_new["artifact"]["sha256"]
                offer_new = new._row(state)["offers"][saved_new["offer"]["offer_ref"]]
                self.assertEqual(
                    offer_new["context"]["saved_reading"]["schema_version"], "1.1.0"
                )
                self.assertIn("coverage_context", offer_new["context"]["saved_reading"])
            finally:
                new.close()
            reverse = model(False)
            try:
                reopened = reverse.register(
                    ref,
                    operation="analyze-full-paper",
                    permit_path=newpath,
                    permit_sha256=newhash,
                )
                self.assertEqual(reopened["offer_ref"], saved_new["offer"]["offer_ref"])
                reverse._guard(
                    ref,
                    reverse._row(case.intake._load("alice", ref))["offers"][
                        reopened["offer_ref"]
                    ],
                )
                self.assertEqual(providers, [])
                self.assertEqual(reverse.read("alice-token", ref)["calls_reserved"], 0)
            finally:
                reverse.close()

    def test_json_like_mode_cannot_select_analysis_format(self):
        with saved_stage1_case() as (case, _):
            for value in (None, 1, {}, [], "true"):
                with (
                    self.subTest(value=value),
                    self.assertRaisesRegex(SessionApiError, "coverage-mode-invalid"),
                ):
                    ProjectModelService(case.intake, analysis_coverage=value)


if __name__ == "__main__":
    unittest.main()
