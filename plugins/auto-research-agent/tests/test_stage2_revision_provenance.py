"""Delivery-level provenance for genuine workflow source-update revisions."""

import copy
import contextlib
import hashlib
import io
import json
import shutil
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_eval import validate_action_record  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_workflow import add_snapshot, initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import build_delivery, inspect_delivery  # noqa: E402
from stage2_workflow.__main__ import main as workflow_main  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402


class RevisionProvenanceTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        # Use the physical host temp root; production still rejects linked paths.
        self.root = Path(temporary.name).resolve()
        self.sources = self.root / "sources"
        self.parent = write_stage2_fixture(self.sources, candidate_count=2)
        self.parent_path = self.root / "parent.json"
        self.parent_path.write_text(json.dumps(self.parent), encoding="utf-8")
        self.workflow = self.root / "workflow"
        initialize_workflow(
            self.parent_path,
            self.sources,
            self.workflow,
            {},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        initial = inspect_workflow(self.workflow)
        self.current = copy.deepcopy(self.parent)
        self.current["packet_id"] = "packet-with-two-authentic-revisions"
        revisions = []
        for number, new_evidence in ((1, "ev-2"), (2, "ev-1")):
            previous = self.parent["candidates"][number - 1]
            revised = copy.deepcopy(previous)
            revised.update(
                version=2,
                parent_version=1,
                question=f"Revised bounded question {number}",
                evidence_ids=previous["evidence_ids"] + [new_evidence],
            )
            revisions.append(revised)
        self.current["candidates"].extend(revisions)
        self.update = self.root / "update"
        self.update.mkdir()
        for source in self.sources.iterdir():
            shutil.copy2(source, self.update / source.name)
        self.packet_path = self.update / "packet.json"
        self.packet_path.write_text(json.dumps(self.current), encoding="utf-8")
        reason = "A genuine source update requires both revisions and fresh review."
        self.impact = [
            {
                "candidate_id": f"candidate-{number}",
                "status": "affected",
                "reason": reason,
            }
            for number in (1, 2)
        ]
        event = add_snapshot(
            self.workflow,
            self.packet_path,
            self.update,
            reason,
            self.impact,
            initial["head_sha256"],
        )
        self.state = inspect_workflow(self.workflow, event["event_sha256"])
        self.receipt = {
            "kind": "Stage2SourceUpdate",
            "schema_version": "1.0.0",
            "parent_packet_sha256": canonical_hash(self.parent),
            "packet_sha256": canonical_hash(self.current),
            "packet_path": str(self.packet_path),
            "source_root": str(self.update),
            "impact": self.impact,
            "acquisitions": [],
            "review_required": True,
            "scientific_quality_verified": False,
            "prior_reviews_carried_forward": False,
        }
        self.receipt_path = self.update / "source_update.json"
        self._write_receipt(self.receipt)

    def _write_receipt(self, value):
        self.receipt_path.write_text(json.dumps(value), encoding="utf-8")
        return hashlib.sha256(self.receipt_path.read_bytes()).hexdigest()

    def _assessment(self, candidate_id):
        version = max(
            row["version"]
            for row in self.current["candidates"]
            if row["candidate_id"] == candidate_id
        )
        value = assessment(
            self.current,
            event_id=f"check-{candidate_id}-v{version}",
            version=version,
        )
        value["candidate_id"] = candidate_id
        value["checks"] = copy.deepcopy(value["checks"])
        return value

    def _inputs(self):
        snapshot = self.state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        versions = {
            candidate_id: max(
                row["version"]
                for row in self.current["candidates"]
                if row["candidate_id"] == candidate_id
            )
            for candidate_id in ("candidate-1", "candidate-2")
        }
        screening = [
            {
                "candidate_id": f"candidate-{number}",
                "candidate_version": versions[f"candidate-{number}"],
                "included": True,
                "distance": number,
                "reason": "Review both revisions.",
            }
            for number in (1, 2)
        ]
        batch = prepare_review_batch(self.current, snapshot, screening, "seed")
        reviews, resolutions = [], []
        for number in (1, 2):
            candidate_id = f"candidate-{number}"
            value = self._assessment(candidate_id)
            candidate_reviews = []
            for role in ("challenger", "feasibility"):
                view = prepare_review(self.current, candidate_id, snapshot, role)
                review = {
                    "role": role,
                    "view_sha256": canonical_hash(view),
                    "snapshot_sha256": snapshot,
                    "candidate_id": candidate_id,
                    "candidate_version": versions[candidate_id],
                    "assessment": copy.deepcopy(value),
                    "session_id": f"{candidate_id}-{role}",
                    "native_artifact": {
                        "path": f"native/{candidate_id}-{role}.jsonl",
                        "sha256": hashlib.sha256(
                            f"{candidate_id}-{role}".encode()
                        ).hexdigest(),
                    },
                    "initial": True,
                    "assumptions": ["Bounded synthetic assumption."],
                    "strongest_alternative": "Another measurement may matter.",
                    "change_conditions": ["Contrary evidence changes the judgment."],
                }
                row = {
                    "candidate_id": candidate_id,
                    "candidate_version": versions[candidate_id],
                    "role": role,
                    "status": "complete",
                    "review": review,
                    "error": None,
                }
                reviews.append(row)
                candidate_reviews.append(row)
            resolutions.append(
                {
                    "candidate_id": candidate_id,
                    "resolution": {
                        "review_sha256s": [
                            canonical_hash(row["review"]) for row in candidate_reviews
                        ],
                        "method": "synthesis",
                        "reason": "Both independent reviews agree.",
                        "evidence_ids": value["checks"]["opportunity"]["evidence_ids"],
                        "addressed": [],
                        "assessment": value,
                        "substantive_disagreements": [],
                        "changed_judgment_reason": None,
                    },
                }
            )
        return batch, reviews, {"candidate_resolutions": resolutions, "next_step": None}

    def _build(self, name="delivery", receipt=None, sha=None, bindings=None):
        if receipt is not None:
            sha = self._write_receipt(receipt)
        sha = sha or hashlib.sha256(self.receipt_path.read_bytes()).hexdigest()
        batch, reviews, resolutions = self._inputs()
        output = self.root / name
        manifest = build_delivery(
            self.workflow,
            batch,
            reviews,
            resolutions,
            output,
            self.state["head_sha256"],
            source_update_receipts=bindings or [(self.receipt_path, sha)],
        )
        return output, manifest

    def _append_third_version_update(self):
        previous = copy.deepcopy(self.current)
        destination = self.root / "update-v3"
        destination.mkdir()
        for source in previous["sources"]:
            shutil.copy2(self.update / source["path"], destination / source["path"])
        raw = b"A third source records another bounded constraint.\n"
        (destination / "source-3.txt").write_bytes(raw)
        current = copy.deepcopy(previous)
        current["packet_id"] = "packet-with-two-more-authentic-revisions"
        current["sources"].append(
            {
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "path": "source-3.txt",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_level": "full-text",
            }
        )
        current["evidence"].append(
            {
                "evidence_id": "ev-3",
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "locator": "line 1",
                "quote": "A third source records another bounded constraint.",
            }
        )
        for candidate_id in ("candidate-1", "candidate-2"):
            prior = next(
                row
                for row in previous["candidates"]
                if row["candidate_id"] == candidate_id and row["version"] == 2
            )
            revised = copy.deepcopy(prior)
            revised.update(
                version=3,
                parent_version=2,
                question=f"Third bounded question for {candidate_id}",
                evidence_ids=prior["evidence_ids"] + ["ev-3"],
            )
            current["candidates"].append(revised)
        packet_path = destination / "packet.json"
        packet_path.write_text(json.dumps(current), encoding="utf-8")
        reason = "The third source requires another exact revision and fresh review."
        impact = [
            {"candidate_id": candidate_id, "status": "affected", "reason": reason}
            for candidate_id in ("candidate-1", "candidate-2")
        ]
        event = add_snapshot(
            self.workflow,
            packet_path,
            destination,
            reason,
            impact,
            self.state["head_sha256"],
        )
        receipt = copy.deepcopy(self.receipt)
        receipt.update(
            parent_packet_sha256=canonical_hash(previous),
            packet_sha256=canonical_hash(current),
            packet_path=str(packet_path),
            source_root=str(destination),
            impact=impact,
        )
        receipt_path = destination / "source_update.json"
        receipt_path.write_text(json.dumps(receipt), encoding="utf-8")
        self.current = current
        self.state = inspect_workflow(self.workflow, event["event_sha256"])
        return (
            receipt_path,
            hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
            destination,
        )

    def test_two_genuine_revisions_are_evaluator_valid_and_portable(self):
        output, manifest = self._build()
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(manifest["schema_version"], "1.1.0")
        self.assertEqual(
            inspected["checker_selection"]["action_record_status"], "unavailable"
        )
        self.assertEqual(inspected["selection"]["action_record_status"], "complete")
        self.assertEqual(
            len(inspected["selection"]["action_record"]["revision_history"]), 2
        )
        validate_action_record(
            inspected["selection"]["action_record"],
            inspected["selection"]["evaluation_packet"],
        )
        self.assertEqual(inspected["manifest"]["human_selection"], "pending")
        self.assertFalse(inspected["manifest"]["stage3_execution_authorized"])
        portable = self.root / "portable"
        shutil.copytree(output, portable)
        shutil.rmtree(self.workflow)
        shutil.rmtree(self.update)
        replay = inspect_delivery(portable, manifest["manifest_sha256"])
        self.assertEqual(replay["selection"], inspected["selection"])

    def test_legacy_delivery_keeps_unavailable_default(self):
        batch, reviews, resolutions = self._inputs()
        output = self.root / "legacy"
        manifest = build_delivery(
            self.workflow,
            batch,
            reviews,
            resolutions,
            output,
            self.state["head_sha256"],
        )
        self.assertEqual(manifest["schema_version"], "1.0.0")
        self.assertEqual(
            inspect_delivery(output, manifest["manifest_sha256"])["selection"][
                "action_record_status"
            ],
            "unavailable",
        )

    def test_delivery_cli_uses_retained_source_update_receipt(self):
        batch, reviews, resolutions = self._inputs()
        arguments = []
        for name, value in (
            ("batch", batch),
            ("reviews", reviews),
            ("resolutions", resolutions),
        ):
            path = self.root / (name + ".json")
            path.write_text(json.dumps(value), encoding="utf-8")
            arguments.extend(["--" + name, str(path)])
        output = self.root / "actual-cli-delivery"
        receipt_sha = hashlib.sha256(self.receipt_path.read_bytes()).hexdigest()
        with contextlib.redirect_stdout(io.StringIO()):
            status = workflow_main(
                [
                    "deliver",
                    "--run",
                    str(self.workflow),
                    "--expected-head",
                    self.state["head_sha256"],
                    "--output",
                    str(output),
                    "--source-update-receipt",
                    str(self.receipt_path),
                    receipt_sha,
                    *arguments,
                ]
            )
        self.assertEqual(status, 0)
        manifest = json.loads(
            (output / "delivery_manifest.json").read_text(encoding="utf-8")
        )
        self.assertEqual(manifest["schema_version"], "1.1.0")
        checked = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(checked["selection"]["action_record_status"], "complete")
        self.assertTrue((output / "revision_provenance.json").is_file())

    def test_human_record_cli_preserves_original_dispatch_signature(self):
        decision = self.root / "synthetic-decision.json"
        decision.write_text(json.dumps({"test": "dispatch-only"}), encoding="utf-8")
        arguments = ["human-record"]
        values = {
            "run": str(self.workflow),
            "delivery": str(self.root / "delivery"),
            "manifest-sha256": "a" * 64,
            "decision": str(decision),
            "message-log": str(self.root / "synthetic-message.jsonl"),
            "action-id": "dispatch-only",
            "output": str(self.root / "human-output"),
            "expected-head": self.state["head_sha256"],
            "message-index": "0",
        }
        for name, value in values.items():
            arguments.extend(["--" + name, value])
        with (
            patch(
                "stage2_workflow.__main__.record_interaction",
                autospec=True,
                return_value={"test": "dispatch-only; no human action recorded"},
            ) as record,
            contextlib.redirect_stdout(io.StringIO()),
        ):
            status = workflow_main(arguments)
        self.assertEqual(status, 0)
        self.assertEqual(record.call_args.kwargs, {})
        self.assertEqual(len(record.call_args.args), 9)
        self.assertFalse((self.root / "human-output").exists())

    def test_receipt_hash_packet_impact_and_claim_mismatches_reject(self):
        with self.assertRaisesRegex(Stage2Error, "receipt-hash-mismatch"):
            self._build("bad-hash", sha="f" * 64)
        attacks = [
            ("packet", "packet_sha256", "f" * 64, "snapshot-match-not-unique"),
            (
                "impact",
                "impact",
                [{**self.impact[0], "reason": "changed"}, self.impact[1]],
                "workflow-snapshot-mismatch",
            ),
            ("claim", "scientific_quality_verified", True, "claims-invalid"),
        ]
        for name, field, value, expected in attacks:
            with self.subTest(name=name):
                receipt = copy.deepcopy(self.receipt)
                receipt[field] = value
                with self.assertRaisesRegex(Stage2Error, expected):
                    self._build(name, receipt=receipt)

    def test_changed_root_selection_rehash_is_rejected_semantically(self):
        output, manifest = self._build()
        selection_path = output / "selection.json"
        selection = json.loads(selection_path.read_text(encoding="utf-8"))
        selection["action_record"]["selected_candidate_ids"] = []
        selection_path.write_text(json.dumps(selection), encoding="utf-8")
        from stage2_workflow.delivery import _manifest_hash, _relative_files

        manifest["selection_sha256"] = canonical_hash(selection)
        manifest["files"] = _relative_files(output)
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        (output / "delivery_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "delivery-selection-mismatch"):
            inspect_delivery(output, manifest["manifest_sha256"])

    def test_rehashed_provenance_cannot_replace_retained_manifest_receipt(self):
        from stage2_workflow.delivery import _manifest_hash, _relative_files

        output, manifest = self._build()
        retained = manifest["manifest_sha256"]
        path = output / "revision_provenance.json"
        provenance = json.loads(path.read_text(encoding="utf-8"))
        provenance["steps"][0]["snapshot_reason"] = "forged after delivery"
        path.write_text(json.dumps(provenance), encoding="utf-8")
        manifest["revision_provenance_sha256"] = canonical_hash(provenance)
        manifest["files"] = _relative_files(output)
        manifest["manifest_sha256"] = _manifest_hash(manifest)
        (output / "delivery_manifest.json").write_text(
            json.dumps(manifest), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "manifest-receipt-mismatch"):
            inspect_delivery(output, retained)

    def test_rehashed_snapshot_candidate_version_reason_and_evidence_tampering_rejects(
        self,
    ):
        from stage2_workflow.delivery import _manifest_hash, _relative_files

        attacks = {
            "snapshot": (
                lambda value: value["steps"][0].update(snapshot_sha256="f" * 64),
                "portable-binding-mismatch",
            ),
            "candidate": (
                lambda value: value["steps"][0]["revisions"][0].update(
                    candidate_id="candidate-x"
                ),
                "revision-mismatch",
            ),
            "version": (
                lambda value: value["steps"][0]["revisions"][0].update(to_version=3),
                "revision-mismatch",
            ),
            "reason": (
                lambda value: value["steps"][0]["revisions"][0].update(
                    reason="invented"
                ),
                "revision-mismatch",
            ),
            "evidence": (
                lambda value: value["steps"][0]["revisions"][0].update(evidence_ids=[]),
                "revision-mismatch",
            ),
        }
        for name, (mutate, expected) in attacks.items():
            with self.subTest(name=name):
                output, manifest = self._build(name)
                path = output / "revision_provenance.json"
                provenance = json.loads(path.read_text(encoding="utf-8"))
                mutate(provenance)
                path.write_text(json.dumps(provenance), encoding="utf-8")
                manifest["revision_provenance_sha256"] = canonical_hash(provenance)
                manifest["files"] = _relative_files(output)
                manifest["manifest_sha256"] = _manifest_hash(manifest)
                (output / "delivery_manifest.json").write_text(
                    json.dumps(manifest), encoding="utf-8"
                )
                with self.assertRaisesRegex(Stage2Error, expected):
                    inspect_delivery(output, manifest["manifest_sha256"])

    def test_incomplete_revision_rows_remain_unavailable(self):
        from stage2_workflow.revision_provenance import derive_selection

        output, manifest = self._build()
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        one = inspected["selection"]["action_record"]["revision_history"][:1]
        incomplete = derive_selection(inspected["checker_selection"], one)
        self.assertEqual(incomplete["action_record_status"], "unavailable")
        self.assertIsNone(incomplete["action_record"])

    def test_nullable_revised_candidate_and_neutral_fallback_are_safe(self):
        from stage2_workflow.revision_provenance import derive_selection

        output, manifest = self._build()
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        checker = copy.deepcopy(inspected["checker_selection"])
        for event in checker["assessment_history"]:
            event["assessment"]["revised_candidate"] = None
        revisions = inspected["selection"]["action_record"]["revision_history"]
        derived = derive_selection(checker, revisions)
        self.assertEqual(derived["action_record_status"], "complete")
        self.assertEqual(
            {row["next_step"] for row in derived["action_record"]["history"]},
            {
                "Follow the recorded disposition and its documented evidence constraints."
            },
        )

    def test_two_source_updates_replay_portably_and_reverse_order_rejects(self):
        first = (
            self.receipt_path,
            hashlib.sha256(self.receipt_path.read_bytes()).hexdigest(),
        )
        second_path, second_sha, second_dir = self._append_third_version_update()
        bindings = [first, (second_path, second_sha)]
        output, manifest = self._build("two-updates", bindings=bindings)
        inspected = inspect_delivery(output, manifest["manifest_sha256"])
        self.assertEqual(
            [
                row["to_version"]
                for row in inspected["selection"]["action_record"]["revision_history"]
            ],
            [2, 3, 2, 3],
        )
        from stage2_workflow.revision_provenance import capture_revision_provenance

        with self.assertRaisesRegex(Stage2Error, "bindings-out-of-order"):
            capture_revision_provenance(self.state, list(reversed(bindings)))
        portable = self.root / "two-updates-portable"
        shutil.copytree(output, portable)
        shutil.rmtree(self.workflow)
        shutil.rmtree(self.update)
        shutil.rmtree(second_dir)
        replay = inspect_delivery(portable, manifest["manifest_sha256"])
        self.assertEqual(replay["selection"], inspected["selection"])


if __name__ == "__main__":
    unittest.main()
