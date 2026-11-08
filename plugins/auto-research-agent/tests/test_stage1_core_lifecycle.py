"""Authored offline Core lifecycle; no research or scientific acceptance."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE.parent / "cli"), str(HERE)]

from current_core_stage12_fixtures import current_core_stage1_case  # noqa: E402
from stage1_deliverable.common import read_json, sha  # noqa: E402
from stage2_common import Stage2Error, canonical_hash, validate_packet  # noqa: E402
from stage2_live.content_revision import prepare_content_revision_input  # noqa: E402
from stage2_live.source_updates import prepare_source_update  # noqa: E402
from stage2_workflow import initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import build_delivery, inspect_delivery  # noqa: E402
from stage2_workflow.import_stage1 import build_stage2_seed  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402


class CoreLifecycleTests(unittest.TestCase):
    def test_screened_core_survives_preparation_and_ordinary_report_export(self):
        with current_core_stage1_case(screened=True) as fixture:
            root, seed_root = fixture["root"], fixture["root"] / "seed"
            build_stage2_seed(
                fixture["deliverable_dir"],
                fixture["manifest_sha256"],
                fixture["handoff_path"],
                fixture["handoff_sha256"],
                fixture["brief_path"],
                fixture["resources_path"],
                seed_root,
                allow_current_core=True,
            )
            seed = read_json(seed_root / "packet.json")
            original_bytes = {
                row["path"]: (seed_root / row["path"]).read_bytes()
                for row in seed["core_source"]["files"]
            }
            # This is an explicit authored unavailable observation, not an HTTP
            # acquisition or a claim that a source does not exist.
            unavailable = {
                "status": "unavailable",
                "url": "https://example.invalid/offline",
                "retrieved_at": "2026-11-08T00:00:00Z",
                "raw_sha256": None,
                "identity_status": "unknown",
                "evidence_level": None,
                "reason": "Authored offline unavailable observation; no request made.",
                "action_ref": "authored-offline-observation",
            }
            update = prepare_source_update(
                seed,
                seed_root,
                [{"acquisition": unavailable}],
                [],
                {},
                root / "updated",
                expected_packet_sha256=canonical_hash(seed),
            )
            updated_root = Path(update["source_root"])
            updated = read_json(update["packet_path"])
            self.assertEqual(update["acquisitions"], [unavailable])
            self.assertFalse(update["scientific_quality_verified"])
            self.assertFalse(update["prior_reviews_carried_forward"])
            revision_root = root / "revision-input"
            revision = prepare_content_revision_input(
                updated,
                updated_root,
                [],
                revision_root,
            )
            revised = read_json(revision_root / "packet.json")
            self.assertFalse(revision["sources_changed"])
            self.assertEqual(revision["evidence_additions"], [])
            workflow = root / "workflow"
            initialize_workflow(
                revision_root / "packet.json",
                updated_root,
                workflow,
                {},
                {},
                expected_packet_sha256=revision["packet_sha256"],
            )
            state = inspect_workflow(workflow)
            snapshot = state["latest_snapshot"]
            batch = prepare_review_batch(
                snapshot["packet"],
                snapshot["event"]["payload"]["snapshot_sha256"],
                [],
                "authored-offline-empty-batch",
            )
            self.assertEqual(batch["assignments"], [])
            output = root / "ordinary-report"
            manifest = build_delivery(
                workflow,
                batch,
                [],
                {
                    "candidate_resolutions": [],
                    "next_step": "Await genuine research and independent review.",
                },
                output,
                state["head_sha256"],
            )
            delivered = inspect_delivery(output, manifest["manifest_sha256"])
            checker = delivered["checker"]
            self.assertEqual(delivered["selection"]["recommendations"], [])
            self.assertEqual(manifest["human_selection"], "pending")
            self.assertFalse(manifest["actual_execution_attested"])
            self.assertFalse(manifest["stage3_execution_authorized"])
            self.assertIn(
                b"checker/stage1_core/core_claim_artifacts/",
                (output / "selection.html").read_bytes(),
            )
            for packet, source_root in (
                (seed, seed_root),
                (updated, updated_root),
                (revised, updated_root),
                (snapshot["checker"]["packet"], snapshot["checker"]["root"]),
                (checker["packet"], checker["root"]),
            ):
                with self.subTest(root=str(source_root)):
                    validate_packet(packet, source_root)
                    self.assertEqual(packet["schema_version"], "2.7.0")
                    self.assertEqual(packet["core_source"], seed["core_source"])
                    self.assertEqual(packet["evidence"], seed["evidence"])
                    self.assertEqual(
                        [
                            {k: v for k, v in row.items() if k != "path"}
                            for row in packet["sources"]
                        ],
                        [
                            {k: v for k, v in row.items() if k != "path"}
                            for row in seed["sources"]
                        ],
                    )
                    self.assertEqual(
                        {
                            name: (source_root / name).read_bytes()
                            for name in original_bytes
                        },
                        original_bytes,
                    )
            records = read_json(checker["root"] / "stage1_core/records.original.json")
            self.assertEqual(records, fixture["records"])
            self.assertEqual(records["schema_version"], "1.2.0")
            self.assertEqual(
                records["core_claim_history"],
                [
                    row
                    for row in fixture["ledger"].events()
                    if row["payload"]["kind"] == "ClaimEvidence"
                ],
            )
            pending = [
                row
                for row in checker["packet"]["evidence"]
                if row["relation"] == "pending"
            ]
            self.assertTrue(pending)
            for row in pending:
                self.assertEqual(
                    [row[k] for k in ("locator", "start", "end", "quote")],
                    [None, None, None, None],
                )
            artifact = next(
                row
                for row in seed["core_source"]["files"]
                if "/core_claim_artifacts/" in row["path"]
            )
            path = checker["root"] / artifact["path"]
            original = path.read_bytes()
            try:
                path.write_bytes(original + b"\nTampered authored fixture.\n")
                changed = deepcopy(checker["packet"])
                next(
                    row
                    for row in changed["core_source"]["files"]
                    if row["path"] == artifact["path"]
                )["sha256"] = sha(path.read_bytes())
                with self.assertRaisesRegex(Stage2Error, "stage1-core-"):
                    validate_packet(changed, checker["root"])
            finally:
                path.write_bytes(original)
            inspect_delivery(output, manifest["manifest_sha256"])
            self.assertEqual(
                sha(fixture["records_path"].read_bytes()), fixture["records_sha256"]
            )
            self.assertEqual(
                fixture["zero_callback_counts"],
                {"query_runner": 0, "source_service": 0, "model": 0},
            )
            fixture["case"].runner.assert_not_called()


if __name__ == "__main__":
    unittest.main()
