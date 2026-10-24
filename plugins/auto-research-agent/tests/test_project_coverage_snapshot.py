"""Opt-in analysis1.1 serializers and actual saved-context capture; no model call."""

from copy import deepcopy
import unittest
from research_workspace_native import project_full_analysis as analysis
from research_workspace_native.project_reading_dispatch import (
    model_reading_prompt,
    model_reading_draft,
    reading_metadata,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_project_coverage_analysis import case
from test_project_stage1_records import saved_stage1_case


def versioned():
    snapshot, checked, context, coverage = case()
    snapshot.update(schema_version="1.1.0", coverage_context=context)
    raw = {
        k: deepcopy(checked[k])
        for k in ("kind", "schema_version", "reading", "screening", "claims")
    }
    raw.update(schema_version="1.1.0", coverage=coverage)
    return snapshot, raw


class CoverageSnapshotTests(unittest.TestCase):
    def test_versioned_prompt_dispatch_and_exact_proposal_binding(self):
        snapshot, value = versioned()
        prompt = model_reading_prompt(snapshot)
        self.assertIn("schema_version must be 1.1.0", prompt)
        self.assertNotIn("schema_version must be 1.0.0", prompt)
        self.assertEqual(
            prompt.count(
                canonical(
                    snapshot["reading_input"]["full_source"]["sources"][0]["text"]
                ).decode("utf8")
            ),
            1,
        )
        checked = model_reading_draft(canonical(value), snapshot)
        self.assertEqual(checked["coverage"], value["coverage"])
        self.assertEqual(checked["snapshot_sha256"], sha(canonical(snapshot)))
        self.assertEqual(
            reading_metadata(snapshot), snapshot["reading_input"]["saved_reading"]
        )
        self.assertFalse(checked["core_claims_created"])
        self.assertFalse(checked["scientific_acceptance"])

    def test_default_prompt_remains_on_legacy_dispatch(self):
        snapshot, _ = versioned()
        snapshot = {k: v for k, v in snapshot.items() if k != "coverage_context"}
        snapshot["schema_version"] = "1.0.0"
        # The old route's serialized content is pinned by independent assertions;
        # no coverage fields or instructions may appear on the default route.
        prompt = analysis.full_analysis_prompt(snapshot)
        self.assertIn("schema_version must be 1.0.0", prompt)
        self.assertNotIn("identity_comparisons", prompt)
        self.assertNotIn("coverage_context", prompt)
        self.assertEqual(model_reading_prompt(snapshot), prompt)
        # Full old/new byte equality is measured separately in the task evidence.

    def test_versions_do_not_cross_admit_companions_or_rehashed_bindings(self):
        for mutation in ("old", "missing", "binding", "proposal-version", "extra"):
            snapshot, value = versioned()
            if mutation == "old":
                snapshot["schema_version"] = "1.0.0"
            elif mutation == "missing":
                del snapshot["coverage_context"]
            elif mutation == "binding":
                snapshot["coverage_context"]["binding"]["work_id"] = "foreign"
                value["coverage"]["context_sha256"] = sha(
                    canonical(snapshot["coverage_context"])
                )
            elif mutation == "proposal-version":
                value["schema_version"] = "1.0.0"
            else:
                value["authorization"] = True
            with self.subTest(mutation=mutation), self.assertRaises(SessionApiError):
                model_reading_draft(canonical(value), snapshot)

    def test_actual_guarded_candidate_and_compiled_clusters_are_captured(self):
        with saved_stage1_case() as (case_, fx):
            ref, ledger = fx["ref"], fx["ledger"]
            work = fx["records"]["papers"][0]["work_id"]
            old = analysis.saved_full_analysis_snapshot(case_.producer, ref, work)
            new = analysis.saved_full_analysis_snapshot(
                case_.producer, ref, work, coverage=True
            )
            self.assertEqual(old["schema_version"], "1.0.0")
            self.assertEqual(new["reading_input"], old["reading_input"])
            context = new["coverage_context"]
            candidate = ledger.candidates()[work]
            self.assertEqual(
                context["candidate_identity_status"], candidate["identity_status"]
            )
            clusters = ledger.coverage_state().plan["proposal"]["clusters"]
            self.assertEqual(
                context["clusters"],
                [
                    dict(
                        cluster_id=c["cluster_id"],
                        title=c.get("label", c["cluster_id"]),
                    )
                    for c in clusters
                ],
            )
            self.assertEqual(
                context["expected_identity"]["version"],
                old["reading_input"]["saved_reading"]["discovery"]["record"].get(
                    "version"
                ),
            )
            self.assertEqual(
                context["binding"]["version_id"],
                old["reading_input"]["saved_reading"]["version_id"],
            )
            self.assertFalse(
                new["reading_input"]["saved_reading"]["scientific_acceptance"]
            )

    def test_optin_mode_cannot_be_a_json_like_value(self):
        for value in (None, {}, [], 1, "true"):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(SessionApiError, "coverage-mode-invalid"),
            ):
                analysis.saved_full_analysis_snapshot(
                    None, "project", "work", coverage=value
                )


if __name__ == "__main__":
    unittest.main()
