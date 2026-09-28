"""End-to-end tests for Stage 2 delivery packaging."""

import copy
import hashlib
import json
import re
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_check.contracts import decode_json  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402

from stage2_workflow.delivery import build_delivery, inspect_delivery  # noqa: E402
from stage2_workflow.__main__ import main  # noqa: E402


def _tree_hash(root):
    rows = []
    for path in sorted(root.rglob("*")):
        if path.is_file():
            rows.append(
                (
                    path.relative_to(root).as_posix(),
                    hashlib.sha256(path.read_bytes()).hexdigest(),
                )
            )
    return canonical_hash(rows)


class Stage2DeliveryTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=1)
        self.packet_path = self.root / "packet.json"
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "workflow"
        initialize_workflow(
            self.packet_path,
            self.sources,
            self.workflow,
            {"model": "declared-review-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.state = inspect_workflow(self.workflow)
        self.snapshot = self.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        screening = [
            {
                "candidate_id": "candidate-1",
                "candidate_version": 1,
                "included": True,
                "distance": 0,
                "reason": "The supplied screening keeps the only candidate.",
            }
        ]
        self.batch = prepare_review_batch(
            self.packet, self.snapshot, screening, "saved-seed"
        )

    def _review(self, role, value):
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
            "assumptions": ["The supplied observations are comparable."],
            "strongest_alternative": "A measurement mismatch could explain it.",
            "change_conditions": ["A source mismatch changes the judgment."],
        }
        return {
            "candidate_id": "candidate-1",
            "candidate_version": 1,
            "role": role,
            "status": "complete",
            "review": review,
            "error": None,
        }

    def _complete_inputs(self, value=None):
        value = value or assessment(self.packet)
        initial = copy.deepcopy(value)
        initial.pop("revised_candidate", None)
        if "revised_candidate" in value:
            initial = assessment(self.packet)
        reviews = [
            self._review("challenger", initial),
            self._review("feasibility", initial),
        ]
        resolution = {
            "review_sha256s": [canonical_hash(row["review"]) for row in reviews],
            "method": "synthesis",
            "reason": "The two supplied reviews support this bounded synthesis.",
            "evidence_ids": ["ev-1"],
            "addressed": [],
            "assessment": copy.deepcopy(value),
            "substantive_disagreements": [],
            "changed_judgment_reason": (
                "The explicit synthesis uses the supplied evidence to propose a revision."
                if "revised_candidate" in value
                else None
            ),
        }
        resolutions = {
            "candidate_resolutions": [
                {"candidate_id": "candidate-1", "resolution": resolution}
            ],
            "next_step": (
                None
                if value["disposition"] == "recommend"
                else "Create a new workflow snapshot and reassess the revised version."
            ),
        }
        return reviews, resolutions

    def _build(self, output, reviews, resolutions, batch=None):
        return build_delivery(
            self.workflow,
            batch or self.batch,
            reviews,
            resolutions,
            output,
            self.state["head_sha256"],
        )

    def test_full_cycle_binds_package_and_preserves_embedded_checker(self):
        reviews, resolutions = self._complete_inputs()
        embedded = self.state["latest_snapshot"]["checker"]["root"]
        before = _tree_hash(embedded)
        output = self.root / "delivery"
        manifest = self._build(output, reviews, resolutions)
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(inspected["root"], output.resolve())
        self.assertEqual(before, _tree_hash(embedded))
        self.assertEqual(manifest["delivery_status"], "local-report-ready")
        self.assertTrue(manifest["local_reconciliation_ready"])
        self.assertEqual(
            manifest["recommendation_candidate_versions"],
            [{"candidate_id": "candidate-1", "candidate_version": 1}],
        )
        self.assertEqual(manifest["pending_revision_candidate_versions"], [])
        self.assertEqual(manifest["human_selection"], "pending")
        self.assertFalse(manifest["stage3_execution_authorized"])
        self.assertFalse(manifest["actual_execution_attested"])
        self.assertEqual(
            [row["candidate_id"] for row in inspected["selection"]["recommendations"]],
            ["candidate-1"],
        )
        self.assertTrue((output / "selection.md").is_file())
        self.assertTrue((output / "selection.html").is_file())
        self.assertTrue((output / "review_audit.json").is_file())
        self.assertEqual(
            (output / "sources" / "source-1.txt").read_bytes(),
            (output / "checker" / "sources" / "source-1.txt").read_bytes(),
        )
        self.assertIn(
            'href="sources/source-1.txt"',
            (output / "selection.html").read_text(encoding="utf-8"),
        )

    def test_incomplete_reviewers_produce_draft_not_ready(self):
        output = self.root / "draft"
        manifest = self._build(
            output,
            [],
            {
                "candidate_resolutions": [],
                "next_step": "Complete both independent reviews.",
            },
        )
        self.assertEqual(manifest["delivery_status"], "draft-not-ready")
        selection = decode_json((output / "selection.json").read_bytes(), "selection")
        self.assertEqual(selection["recommendations"], [])
        self.assertIn("pending assessment", selection["blocking_items"][0])

    def test_zero_candidates_reports_preserve_next_step(self):
        self.packet = write_stage2_fixture(self.sources, candidate_count=0)
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "empty-workflow"
        initialize_workflow(
            self.packet_path,
            self.sources,
            self.workflow,
            {},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.state = inspect_workflow(self.workflow)
        self.snapshot = self.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        self.batch = prepare_review_batch(self.packet, self.snapshot, [], "saved-seed")
        next_step = (
            "Obtain the missing variable dictionary before proposing a new direction."
        )
        output = self.root / "empty-delivery"
        manifest = self._build(
            output, [], {"candidate_resolutions": [], "next_step": next_step}
        )
        inspect_delivery(output, manifest["manifest_sha256"])
        for name in ("selection.md", "selection.html"):
            self.assertIn(next_step, (output / name).read_text(encoding="utf-8"))

    def test_parked_alternative_does_not_veto_checked_recommendation(self):
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        self.packet_path.write_text(json.dumps(self.packet), encoding="utf-8")
        self.workflow = self.root / "two-candidate-workflow"
        initialize_workflow(
            self.packet_path,
            self.sources,
            self.workflow,
            {"model": "declared-review-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        self.state = inspect_workflow(self.workflow)
        self.snapshot = self.state["latest_snapshot"]["event"]["payload"][
            "snapshot_sha256"
        ]
        self.batch = prepare_review_batch(
            self.packet,
            self.snapshot,
            [
                {
                    "candidate_id": f"candidate-{n}",
                    "candidate_version": 1,
                    "included": n == 1,
                    "distance": n,
                    "reason": "Synthetic screening.",
                }
                for n in (1, 2)
            ],
            "saved-seed",
        )
        reviews, resolutions = self._complete_inputs()
        parked = assessment(self.packet, event_id="check-2", disposition="park")
        parked["candidate_id"] = "candidate-2"
        alternative_reviews = []
        for role in ("challenger", "feasibility"):
            row = self._review(role, parked)
            row["candidate_id"] = row["review"]["candidate_id"] = "candidate-2"
            row["review"]["view_sha256"] = canonical_hash(
                prepare_review(self.packet, "candidate-2", self.snapshot, role)
            )
            alternative_reviews.append(row)
        resolution = copy.deepcopy(
            resolutions["candidate_resolutions"][0]["resolution"]
        )
        resolution["assessment"] = parked
        resolution["review_sha256s"] = [
            canonical_hash(row["review"]) for row in alternative_reviews
        ]
        resolutions["candidate_resolutions"].append(
            {"candidate_id": "candidate-2", "resolution": resolution}
        )
        reviews.extend(alternative_reviews)
        output = self.root / "mixed"
        manifest = self._build(output, reviews, resolutions)
        result = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(manifest["delivery_status"], "local-report-ready")
        self.assertEqual(
            manifest["recommendation_candidate_versions"],
            [{"candidate_id": "candidate-1", "candidate_version": 1}],
        )
        self.assertEqual(
            result["selection"]["current_options"][1]["assessment"]["disposition"],
            "park",
        )

    def test_wrong_snapshot_and_existing_output_fail_before_replacement(self):
        reviews, resolutions = self._complete_inputs()
        stale = copy.deepcopy(self.batch)
        stale["snapshot_sha256"] = "f" * 64
        with self.assertRaisesRegex(Stage2Error, "current-snapshot-mismatch"):
            self._build(self.root / "wrong", reviews, resolutions, stale)
        output = self.root / "existing"
        output.mkdir()
        marker = output / "keep.txt"
        marker.write_text("keep", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "output-exists"):
            self._build(output, reviews, resolutions)
        self.assertEqual(marker.read_text(encoding="utf-8"), "keep")

    def test_recomputed_manifest_is_rejected_by_retained_receipt(self):
        reviews, resolutions = self._complete_inputs()
        output = self.root / "tamper"
        manifest = self._build(output, reviews, resolutions)
        receipt = manifest["manifest_sha256"]
        html_path = output / "selection.html"
        html_path.write_bytes(html_path.read_bytes() + b"\nchanged")
        manifest_path = output / "delivery_manifest.json"
        changed = decode_json(manifest_path.read_bytes(), str(manifest_path))
        for row in changed["files"]:
            if row["path"] == "selection.html":
                row["sha256"] = hashlib.sha256(html_path.read_bytes()).hexdigest()
                row["size"] = html_path.stat().st_size
        changed["manifest_sha256"] = canonical_hash(
            {key: value for key, value in changed.items() if key != "manifest_sha256"}
        )
        manifest_path.write_bytes(
            json.dumps(
                changed,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        )
        with self.assertRaisesRegex(Stage2Error, "manifest-receipt-mismatch"):
            inspect_delivery(output, receipt)

    def test_resolved_revision_is_pending_and_cannot_be_selected(self):
        revised_assessment = assessment(self.packet, disposition="revise")
        revised = copy.deepcopy(self.packet["candidates"][0])
        revised.update(
            version=2,
            parent_version=1,
            question="Revised question requires a new workflow snapshot and recheck.",
        )
        revised_assessment["revised_candidate"] = revised
        reviews, resolutions = self._complete_inputs(revised_assessment)
        output = self.root / "revision"
        manifest = self._build(output, reviews, resolutions)
        selection = decode_json((output / "selection.json").read_bytes(), "selection")
        self.assertEqual(manifest["delivery_status"], "local-report-ready")
        self.assertEqual(selection["recommendations"], [])
        self.assertEqual(selection["current_options"][0]["candidate"]["version"], 2)
        self.assertIsNone(selection["current_options"][0]["assessment"])
        self.assertIn("pending assessment", selection["blocking_items"][0])
        self.assertEqual(
            manifest["pending_revision_candidate_versions"],
            [
                {
                    "candidate_id": "candidate-1",
                    "candidate_version": 2,
                    "parent_version": 1,
                }
            ],
        )
        self.assertEqual(manifest["recommendation_candidate_versions"], [])

    def test_failed_build_retains_partial_output_for_diagnosis(self):
        reviews, resolutions = self._complete_inputs()
        output = self.root / "partial"
        with (
            patch(
                "stage2_workflow.delivery.initialize_run",
                side_effect=Stage2Error("synthetic-checker-failure"),
            ),
            self.assertRaisesRegex(Stage2Error, "synthetic-checker-failure"),
        ):
            self._build(output, reviews, resolutions)
        self.assertTrue(output.is_dir())
        self.assertTrue((output / "input_packet.json").is_file())
        self.assertTrue((output / "review_audit.json").is_file())
        self.assertFalse((output / "delivery_manifest.json").exists())

    def test_root_markdown_links_resolve_and_cli_inspects_retained_receipt(self):
        reviews, resolutions = self._complete_inputs()
        output = self.root / "linked"
        files = []
        for name, value in (
            ("batch", self.batch),
            ("reviews", reviews),
            ("resolutions", resolutions),
        ):
            path = self.root / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            files.extend(("--" + name, str(path)))
        stdout = io.StringIO()
        with contextlib.redirect_stdout(stdout):
            code = main(
                [
                    "deliver",
                    "--run",
                    str(self.workflow),
                    "--expected-head",
                    self.state["head_sha256"],
                    "--output",
                    str(output),
                    *files,
                ]
            )
        self.assertEqual(code, 0)
        manifest = json.loads(stdout.getvalue())
        links = re.findall(
            r"\[[^]]*\]\(([^)]+)\)",
            (output / "selection.md").read_text(encoding="utf-8"),
        )
        self.assertTrue(
            all((output / link).is_file() for link in links if not link.startswith("#"))
        )
        with contextlib.redirect_stdout(io.StringIO()):
            self.assertEqual(
                main(
                    [
                        "inspect-delivery",
                        "--delivery",
                        str(output),
                        "--manifest-sha256",
                        manifest["manifest_sha256"],
                    ]
                ),
                0,
            )

    def test_two_rehashed_selection_copies_cannot_replace_verified_events(self):
        from stage2_workflow.delivery import _relative_files, _manifest_hash

        reviews, resolutions = self._complete_inputs()
        output = self.root / "forged"
        manifest = self._build(output, reviews, resolutions)
        selection = json.loads((output / "selection.json").read_text(encoding="utf-8"))
        selection["recommendations"][0]["question"] = "A forged unreviewed direction"
        for relative in ("selection.json", "checker/selection.json"):
            (output / relative).write_text(json.dumps(selection), encoding="utf-8")
        manifest["selection_sha256"] = canonical_hash(selection)
        manifest["files"] = _relative_files(output)
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        (output / "delivery_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "delivery-selection-mismatch"):
            inspect_delivery(output, manifest["manifest_sha256"])

    def test_outer_rehash_cannot_relabel_review_snapshot_or_escape_package(self):
        from stage2_workflow.delivery import _relative_files, _manifest_hash

        reviews, resolutions = self._complete_inputs()
        for attack in ("snapshot", "path"):
            with self.subTest(attack=attack):
                output = self.root / attack
                manifest = self._build(output, reviews, resolutions)
                if attack == "snapshot":
                    manifest["snapshot_sha256"] = "f" * 64
                    audit_path = output / "review_audit.json"
                    audit = json.loads(audit_path.read_text(encoding="utf-8"))
                    audit["snapshot_sha256"] = manifest["snapshot_sha256"]
                    audit_path.write_text(json.dumps(audit), encoding="utf-8")
                    expected = "delivery-batch-snapshot-mismatch"
                else:
                    (self.root / "external.json").write_bytes(
                        (output / "review_batch.json").read_bytes()
                    )
                    manifest["review_input_files"]["batch"] = "../external.json"
                    expected = "delivery-review-input-paths-invalid"
                manifest["files"] = _relative_files(output)
                manifest["manifest_sha256"] = _manifest_hash(manifest)
                (output / "delivery_manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                with self.assertRaisesRegex(Stage2Error, expected):
                    inspect_delivery(output, manifest["manifest_sha256"])


if __name__ == "__main__":
    unittest.main()
