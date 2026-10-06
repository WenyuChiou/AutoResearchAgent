"""End-to-end coverage for opt-in guarded Stage 2 delivery."""

import copy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import build_delivery, inspect_delivery  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.prerequisites import KINDS, prepare_prerequisite_review  # noqa: E402
from stage2_workflow.quality_guards import prepare_quality_record  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


class GuardedDeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        sources = self.root / "sources"
        self.packet = write_stage2_fixture(sources, candidate_count=1)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "workflow"
        initialize_workflow(
            packet_path,
            sources,
            self.workflow,
            {},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.state = inspect_workflow(self.workflow)
        self.snapshot = self.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        self.snapshot_sources = (
            self.state["latest_snapshot"]["checker"]["root"] / "sources"
        ).resolve()
        self.batch = prepare_review_batch(
            self.packet,
            self.snapshot,
            [
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "included": True,
                    "distance": 0,
                    "reason": "Keep the fixture candidate.",
                }
            ],
            "guarded-seed",
        )

    def _inputs(self, value):
        reviews = []
        for role in ("challenger", "feasibility"):
            view = prepare_review(self.packet, "candidate-1", self.snapshot, role)
            review = {
                "role": role,
                "view_sha256": canonical_hash(view),
                "snapshot_sha256": self.snapshot,
                "candidate_id": "candidate-1",
                "candidate_version": 1,
                "assessment": copy.deepcopy(value),
                "session_id": f"session-{role}",
                "native_artifact": {
                    "path": f"native/{role}.jsonl",
                    "sha256": canonical_hash([role]),
                },
                "initial": True,
                "assumptions": ["The bounded observations are comparable."],
                "strongest_alternative": "A measurement mismatch could explain it.",
                "change_conditions": ["Contradictory evidence changes the judgment."],
            }
            reviews.append(
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "role": role,
                    "status": "complete",
                    "review": review,
                    "error": None,
                }
            )
        resolution = {
            "review_sha256s": [canonical_hash(row["review"]) for row in reviews],
            "method": "synthesis",
            "reason": "The bounded evidence supports the retained disposition.",
            "evidence_ids": ["ev-1"],
            "addressed": [],
            "assessment": copy.deepcopy(value),
            "substantive_disagreements": [],
            "changed_judgment_reason": None,
        }
        return reviews, {
            "candidate_resolutions": [
                {"candidate_id": "candidate-1", "resolution": resolution}
            ],
            "next_step": (
                None
                if value["disposition"] == "recommend"
                else "Retain the honest disposition and its supporting reasons."
            ),
        }

    def _bundle(self, *, blocked=False, snapshot=None):
        named = {
            "comparability": ("counterexample", "different outcome interval"),
            "evidence-dependency": ("premise", "source access remains available"),
            "mechanism-distinction": (
                "distinguishing-observation",
                "held-out errors diverge",
            ),
            "critical-premise": ("premise", "measurements share an outcome"),
        }
        checks = []
        for category, (kind, element) in named.items():
            unknown = blocked and category == "critical-premise"
            checks.append(
                {
                    "check_id": f"candidate-1:{category}",
                    "candidate_id": "candidate-1",
                    "candidate_version": 1,
                    "category": category,
                    "critical": category
                    in {"mechanism-distinction", "critical-premise"},
                    "statement": f"Assess {kind} {element} against sources.",
                    "named_element_kind": kind,
                    "named_element": element,
                    "status": "unknown" if unknown else "supported",
                    "rationale": "The raw caller judgment and reason are retained.",
                    "evidence_ids": [] if unknown else ["ev-1"],
                    "next_check": "Obtain premise evidence." if unknown else None,
                }
            )
        quality = prepare_quality_record(
            self.packet, "candidate-1", snapshot or self.snapshot, checks
        )
        prerequisite_checks = [
            {
                "check_id": f"candidate-1:{kind}",
                "candidate_id": "candidate-1",
                "candidate_version": 1,
                "kind": kind,
                "statement": f"Check {kind} prerequisite.",
                "status": "supported",
                "evidence_ids": ["ev-1"],
                "reason": "The source-backed prerequisite is available.",
                "next_check": None,
            }
            for kind in sorted(KINDS)
        ]
        prerequisite = prepare_prerequisite_review(
            self.packet,
            self.snapshot_sources,
            ["candidate-1"],
            prerequisite_checks,
            [
                {
                    "component_id": "candidate-1",
                    "candidate_ids": ["candidate-1"],
                    "unit": "person-weeks",
                    "amount": 1,
                    "evidence_ids": ["ev-1"],
                    "basis": "Bounded fixture estimate",
                }
            ],
            [{"unit": "person-weeks", "amount": 2, "decision_ref": "fixture"}],
        )
        return {
            "quality_record": quality,
            "quality_sha256": canonical_hash(quality),
            "prerequisite_record": prerequisite,
            "prerequisite_sha256": canonical_hash(prerequisite),
            "source_root": str(self.snapshot_sources),
            "resource_mode": "alternatives",
            "selected_candidate_ids": ["candidate-1"],
            "joint_feasibility": "not-claimed",
        }

    def _build(self, name, value, bundle):
        reviews, resolutions = self._inputs(value)
        bundles = {"candidate-1": bundle}
        output = self.root / name
        manifest = build_delivery(
            self.workflow,
            self.batch,
            reviews,
            resolutions,
            output,
            self.state["head_sha256"],
            guard_bundles=bundles,
            expected_guard_bundles_sha256=canonical_hash(bundles),
        )
        return output, manifest

    def test_supported_recommendation_is_portable_and_retains_guard_receipts(self):
        output, manifest = self._build(
            "guarded", assessment(self.packet), self._bundle()
        )
        self.assertEqual(manifest["schema_version"], "1.2.0")
        self.assertTrue((output / "guard_bundles.json").is_file())
        self.assertTrue((output / "guarded_reconciliation.json").is_file())
        portable = self.root / "portable"
        shutil.copytree(output, portable)
        checked = inspect_delivery(portable, manifest["manifest_sha256"])
        self.assertEqual(
            checked["selection"]["recommendations"][0]["candidate_id"],
            "candidate-1",
        )
        self.assertFalse(checked["manifest"]["actual_execution_attested"])

    def test_blocked_recommendation_fails_before_export_but_park_is_retained(self):
        with self.assertRaisesRegex(
            Stage2Error, "candidate-1.*required evidence.*disposition"
        ):
            self._build("blocked", assessment(self.packet), self._bundle(blocked=True))
        self.assertFalse((self.root / "blocked").exists())

        parked = assessment(self.packet, disposition="park")
        output, manifest = self._build("parked", parked, self._bundle(blocked=True))
        checked = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(checked["selection"]["recommendations"], [])
        self.assertEqual(
            checked["reconciliation"]["candidates"][0]["reconciliation"]["assessment"][
                "disposition"
            ],
            "park",
        )

    def test_guard_set_stale_snapshot_and_legacy_behavior(self):
        reviews, resolutions = self._inputs(assessment(self.packet))
        with self.assertRaisesRegex(Stage2Error, "candidate-set-mismatch"):
            build_delivery(
                self.workflow,
                self.batch,
                reviews,
                resolutions,
                self.root / "missing",
                self.state["head_sha256"],
                guard_bundles={},
                expected_guard_bundles_sha256=canonical_hash({}),
            )
        stale = {"candidate-1": self._bundle(snapshot="f" * 64)}
        with self.assertRaisesRegex(Stage2Error, "reconstruction mismatch"):
            build_delivery(
                self.workflow,
                self.batch,
                reviews,
                resolutions,
                self.root / "stale",
                self.state["head_sha256"],
                guard_bundles=stale,
                expected_guard_bundles_sha256=canonical_hash(stale),
            )
        legacy = self.root / "legacy"
        manifest = build_delivery(
            self.workflow,
            self.batch,
            reviews,
            resolutions,
            legacy,
            self.state["head_sha256"],
        )
        self.assertEqual(manifest["schema_version"], "1.0.0")
        self.assertFalse((legacy / "guard_bundles.json").exists())

    def test_malformed_guard_json_returns_cli_error_without_export(self):
        import contextlib
        import io
        from stage2_workflow.__main__ import main

        reviews, resolutions = self._inputs(assessment(self.packet))
        for field in ("category", "named_element_kind", "status"):
            with self.subTest(field=field):
                bundle = self._bundle()
                quality = bundle["quality_record"]
                quality["checks"][0][field] = []
                quality["record_sha256"] = canonical_hash(
                    {k: v for k, v in quality.items() if k != "record_sha256"}
                )
                bundle["quality_sha256"] = canonical_hash(quality)
                bundles = {"candidate-1": bundle}
                for name, data in (
                    ("batch", self.batch),
                    ("reviews", reviews),
                    ("resolutions", resolutions),
                    ("guards", bundles),
                ):
                    (self.root / f"{name}.json").write_text(
                        json.dumps(data), encoding="utf-8"
                    )
                args = [
                    "reconcile",
                    "--run",
                    str(self.workflow),
                    "--expected-head",
                    self.state["head_sha256"],
                    "--batch",
                    str(self.root / "batch.json"),
                    "--reviews",
                    str(self.root / "reviews.json"),
                    "--resolutions",
                    str(self.root / "resolutions.json"),
                    "--guard-bundles",
                    str(self.root / "guards.json"),
                    "--expected-guard-bundles-sha256",
                    canonical_hash(bundles),
                    "--output",
                    str(self.root / "invalid-output.json"),
                ]
                error = io.StringIO()
                with contextlib.redirect_stderr(error):
                    self.assertEqual(main(args), 2)
                self.assertIn("stage2-workflow:", error.getvalue())
                self.assertNotIn("Traceback", error.getvalue())
                self.assertFalse((self.root / "invalid-output.json").exists())


if __name__ == "__main__":
    unittest.main()
