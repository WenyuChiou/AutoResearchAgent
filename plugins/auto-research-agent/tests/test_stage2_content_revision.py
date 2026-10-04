"""Source-free content revision contracts and portable delivery provenance."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage1_eval.common import EvaluationError, canonical  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_live.content_revision import (  # noqa: E402
    UPDATE_MODE,
    _authenticate_extraction,
    prepare_content_revision,
    prepare_content_revision_input,
)
from stage2_live.extraction import (  # noqa: E402
    _prompt,
    _request,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_live.judges import _execution_policy  # noqa: E402
from stage2_ideation import build_extraction_task, validate_extraction  # noqa: E402
from stage2_ideation.integration import build_next_packet  # noqa: E402
from stage2_workflow import add_snapshot, initialize_workflow, inspect_workflow  # noqa: E402
from stage2_workflow.delivery import build_delivery, inspect_delivery  # noqa: E402
from stage2_workflow.orchestration import prepare_review_batch  # noqa: E402
from stage2_workflow.reviews import prepare_review  # noqa: E402
from test_stage2_checker import assessment  # noqa: E402
from test_stage2_controller import _write_faithful_model_archive  # noqa: E402
from test_stage2_live_extraction import POLICY, generated_extraction  # noqa: E402
from test_stage2_readonly_replay import digest, write_json  # noqa: E402


class ContentRevisionTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.sources = self.root / "sources"
        self.parent = write_stage2_fixture(self.sources, candidate_count=1)

    def addition(self):
        source = self.parent["sources"][0]
        line = (
            (self.sources / source["path"]).read_text(encoding="utf-8").splitlines()[0]
        )
        return {
            "evidence_id": "ev-context-correction",
            "source_id": source["source_id"],
            "work_id": source["work_id"],
            "version_id": source["version_id"],
            "locator": "lines 1-1",
            "quote": line,
        }

    def test_revision_input_allows_zero_or_exact_existing_source_excerpt(self):
        zero = prepare_content_revision_input(
            self.parent, self.sources, [], self.root / "zero"
        )
        self.assertEqual(zero["evidence_additions"], [])
        self.assertFalse(zero["sources_changed"])
        added = prepare_content_revision_input(
            self.parent, self.sources, [self.addition()], self.root / "added"
        )
        self.assertEqual(
            added["evidence_additions"][0]["evidence_id"], "ev-context-correction"
        )
        packet = json.loads(
            (self.root / "added/packet.json").read_text(encoding="utf-8")
        )
        self.assertEqual(packet["sources"], self.parent["sources"])

    def test_revision_input_rejects_foreign_source_and_mutated_quote(self):
        foreign = self.addition()
        foreign["source_id"] = "foreign"
        with self.assertRaisesRegex(Stage2Error, "foreign-source"):
            prepare_content_revision_input(
                self.parent, self.sources, [foreign], self.root / "foreign"
            )
        changed = self.addition()
        changed["quote"] += " changed"
        with self.assertRaisesRegex(Stage2Error, "quote-mismatch"):
            prepare_content_revision_input(
                self.parent, self.sources, [changed], self.root / "changed"
            )

    def test_multiline_crlf_excerpt_preserves_original_source_bytes(self):
        source = self.parent["sources"][0]
        source_path = self.sources / source["path"]
        source_bytes = b"first line\r\nsecond line\r\nthird line\r\n"
        source_path.write_bytes(source_bytes)
        source["sha256"] = hashlib.sha256(source_bytes).hexdigest()
        for evidence in self.parent["evidence"]:
            if evidence["source_id"] == source["source_id"]:
                evidence["quote"] = "first line"
                evidence["locator"] = "lines 1-1"
        exact = {
            "evidence_id": "ev-crlf-context",
            "source_id": source["source_id"],
            "work_id": source["work_id"],
            "version_id": source["version_id"],
            "locator": "lines 1-2",
            "quote": "first line\r\nsecond line",
        }
        receipt = prepare_content_revision_input(
            self.parent, self.sources, [exact], self.root / "crlf-exact"
        )
        self.assertEqual(receipt["evidence_additions"][0]["quote"], exact["quote"])
        self.assertEqual(source_path.read_bytes(), source_bytes)
        normalized = copy.deepcopy(exact)
        normalized["quote"] = "first line\nsecond line"
        with self.assertRaisesRegex(Stage2Error, "quote-mismatch"):
            prepare_content_revision_input(
                self.parent, self.sources, [normalized], self.root / "crlf-normalized"
            )

    def test_revision_input_rejects_changed_frozen_source_bytes(self):
        source = self.parent["sources"][0]
        (self.sources / source["path"]).write_text("changed", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "hash mismatch"):
            prepare_content_revision_input(
                self.parent, self.sources, [], self.root / "changed-source"
            )

    def test_extraction_authentication_rejects_forged_producer_receipt(self):
        extraction = self.root / "forged-extraction"
        extraction.mkdir()
        (extraction / "result.json").write_text("{}", encoding="utf-8")
        (extraction / "extraction.unit.json").write_text("{}", encoding="utf-8")
        forged = {
            "result_sha256": hashlib.sha256(b"{}").hexdigest(),
            "unit_receipts": {"extraction": "f" * 64},
        }
        with self.assertRaisesRegex(Stage2Error, "artifact-changed"):
            _authenticate_extraction(
                extraction,
                forged,
                self.parent,
                self.sources,
                "a" * 64,
            )

    def _archive_backed_content_revision(self):
        snapshot = "a" * 64
        raw = (
            "The corrected comparison retains the frozen source boundary.\n"
            "Revise the existing candidate question before fresh review."
        )
        spans = build_span_index(raw)
        generated = generated_extraction(
            raw, self.parent, span_id=spans["spans"][0]["span_id"]
        )
        candidate = copy.deepcopy(self.parent["candidates"][0])
        candidate["question"] = "A corrected source-bound research question."
        for key in ("candidate_id", "version", "parent_version"):
            candidate.pop(key)
        generated["candidates"] = [
            {
                "candidate": candidate,
                "existing_candidate_id": self.parent["candidates"][0]["candidate_id"],
                "route": "improvement",
                "mechanism": "Correct the comparison before a fresh review.",
                "closest_work_refs": [],
                "strong_alternatives": ["Retain the current candidate as parked."],
                "change_mind_conditions": [
                    "The corrected source-bound interpretation is contradicted."
                ],
                "claim_labels": [
                    {
                        "text": "A corrected source-bound research question.",
                        "status": "untested-benefit",
                        "evidence_ids": [],
                    }
                ],
                "spans": [{"span_id": spans["spans"][0]["span_id"]}],
            }
        ]
        generated["unresolved"] = ["Current artifact access remains unknown."]
        task = build_extraction_task(raw, self.parent, snapshot)
        schema = generation_schema(spans, self.parent)
        prompt = _prompt(task, self.parent, spans, schema, UPDATE_MODE)
        output = self.root / "archive-backed"
        output.mkdir()
        codex = self.root / "synthetic-codex.exe"
        codex.write_bytes(b"synthetic test executable; no model dispatch")
        home = self.root / "synthetic-evaluator-home"
        home.mkdir()
        config = {
            "codex": str(codex.resolve()),
            "codex_executable_sha256": digest(codex),
            "evaluator_home": str(home.resolve()),
            "model": "synthetic-test-model",
            "reasoning": "high",
        }
        write_json(output / "extraction.schema.json", schema)
        replayed = _write_faithful_model_archive(
            output, "extraction", prompt, schema, generated, config, POLICY
        )
        unit = {
            "label": "extraction",
            "value": generated,
            "provenance": {"initial": replayed, "correction": None},
        }
        unit_path = write_json(output / "extraction.unit.json", unit)
        expanded = expand_span_ids(generated, raw, spans, self.parent)
        validated = validate_extraction(raw, expanded, self.parent, snapshot)
        next_packet = build_next_packet(
            self.parent,
            self.sources,
            raw,
            validated,
            snapshot,
            update_mode=UPDATE_MODE,
        )
        policy = _execution_policy(POLICY)
        request = _request(
            task,
            self.parent,
            self.sources,
            spans,
            schema,
            prompt,
            config["codex"],
            config["evaluator_home"],
            config["model"],
            config["reasoning"],
            policy,
            "native",
            UPDATE_MODE,
        )
        write_json(output / "request.json", request)
        (output / "raw-proposal.bin").write_bytes(raw.encode())
        write_json(output / "input-packet.json", self.parent)
        write_json(output / "span-index.json", spans)
        result = {
            "kind": "Stage2LiveExtractionResult",
            "schema_version": "1.0.0",
            "status": "passed",
            "request_sha256": canonical_hash(request),
            "extraction": validated,
            "next_packet": next_packet,
            "model_call_provenance": unit["provenance"],
            "native_execution_verified": True,
            "scientific_approval": None,
            "usage": None,
            "cost": None,
            "packet_update_mode": UPDATE_MODE,
            "unit_receipts": {"extraction": digest(unit_path)},
        }
        result_path = write_json(output / "result.json", result)
        receipt = {
            "result_sha256": digest(result_path),
            "unit_receipts": {"extraction": digest(unit_path)},
        }
        return output, receipt, snapshot, next_packet

    def test_real_extraction_authentication_replays_archive_and_rejects_rehashes(self):
        output, receipt, snapshot, next_packet = self._archive_backed_content_revision()
        with patch(
            "stage1_eval.model_calls.call_model_v31",
            side_effect=AssertionError("synthetic archive test must not call a model"),
        ) as model_call:
            proof = _authenticate_extraction(
                output, receipt, self.parent, self.sources, snapshot
            )
        model_call.assert_not_called()
        self.assertEqual(proof["next_packet"], next_packet["packet"])
        self.assertEqual(proof["actual_call_count"], 1)
        self.assertEqual(proof["next_packet"]["sources"], self.parent["sources"])
        self.assertEqual(proof["next_packet"]["evidence"], self.parent["evidence"])

        request_path = output / "request.json"
        request_bytes = request_path.read_bytes()
        request_receipt = copy.deepcopy(receipt)
        request = json.loads(request_path.read_text(encoding="utf-8"))
        request["model"] = "changed-synthetic-model"
        write_json(request_path, request)
        with self.assertRaisesRegex(EvaluationError, "request fingerprint"):
            _authenticate_extraction(
                output, request_receipt, self.parent, self.sources, snapshot
            )
        request_path.write_bytes(request_bytes)

        input_path = output / "input-packet.json"
        input_bytes = input_path.read_bytes()
        changed_packet = copy.deepcopy(self.parent)
        changed_packet["packet_id"] = "changed-after-production"
        write_json(input_path, changed_packet)
        with self.assertRaisesRegex(Stage2Error, "input-packet-mismatch"):
            _authenticate_extraction(
                output, receipt, self.parent, self.sources, snapshot
            )
        input_path.write_bytes(input_bytes)

        result_receipt = copy.deepcopy(receipt)
        result_path = output / "result.json"
        result_bytes = result_path.read_bytes()
        result = json.loads(result_path.read_text(encoding="utf-8"))
        result["next_packet"]["packet"]["packet_id"] = "changed-result"
        write_json(result_path, result)
        result_receipt["result_sha256"] = digest(result_path)
        with self.assertRaisesRegex(Stage2Error, "result-mismatch"):
            _authenticate_extraction(
                output, result_receipt, self.parent, self.sources, snapshot
            )
        result_path.write_bytes(result_bytes)

        prompt_path = output / "extraction.model-call/prompt.txt"
        prompt_bytes = prompt_path.read_bytes()
        prompt_path.write_bytes(prompt_path.read_bytes() + b"\nchanged")
        with self.assertRaisesRegex(EvaluationError, "archived model prompt changed"):
            _authenticate_extraction(
                output, receipt, self.parent, self.sources, snapshot
            )
        prompt_path.write_bytes(prompt_bytes)

        unit_receipt = copy.deepcopy(receipt)
        unit_path = output / "extraction.unit.json"
        unit_bytes = unit_path.read_bytes()
        unit = json.loads(unit_path.read_text(encoding="utf-8"))
        unit["value"]["unresolved"] = ["Changed after the archived call."]
        write_json(unit_path, unit)
        unit_receipt["unit_receipts"]["extraction"] = digest(unit_path)
        unit_result_path = output / "result.json"
        unit_result_bytes = unit_result_path.read_bytes()
        unit_result = json.loads(unit_result_path.read_text(encoding="utf-8"))
        unit_result["unit_receipts"] = unit_receipt["unit_receipts"]
        write_json(unit_result_path, unit_result)
        unit_receipt["result_sha256"] = digest(unit_result_path)
        with self.assertRaisesRegex(Stage2Error, "replay-unit-value-mismatch"):
            _authenticate_extraction(
                output, unit_receipt, self.parent, self.sources, snapshot
            )
        unit_path.write_bytes(unit_bytes)
        unit_result_path.write_bytes(unit_result_bytes)

    def _fresh_inputs(self, current, state):
        candidate_id = current["candidates"][0]["candidate_id"]
        snapshot = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        batch = prepare_review_batch(
            current,
            snapshot,
            [
                {
                    "candidate_id": candidate_id,
                    "candidate_version": 2,
                    "included": True,
                    "distance": 1,
                    "reason": "Freshly review the corrected v2 candidate.",
                }
            ],
            "seed",
        )
        value = assessment(current, event_id="check-v2", version=2)
        value["candidate_id"] = candidate_id
        reviews, candidate_reviews = [], []
        for role in ("challenger", "feasibility"):
            view = prepare_review(current, candidate_id, snapshot, role)
            review = {
                "role": role,
                "view_sha256": canonical_hash(view),
                "snapshot_sha256": snapshot,
                "candidate_id": candidate_id,
                "candidate_version": 2,
                "assessment": copy.deepcopy(value),
                "session_id": f"v2-{role}",
                "native_artifact": {
                    "path": f"native/v2-{role}.jsonl",
                    "sha256": hashlib.sha256(role.encode()).hexdigest(),
                },
                "initial": True,
                "assumptions": ["Synthetic contract test."],
                "strongest_alternative": "Park the candidate.",
                "change_conditions": ["Contrary evidence changes the result."],
            }
            row = {
                "candidate_id": candidate_id,
                "candidate_version": 2,
                "role": role,
                "status": "complete",
                "review": review,
                "error": None,
            }
            reviews.append(row)
            candidate_reviews.append(row)
        resolutions = {
            "candidate_resolutions": [
                {
                    "candidate_id": candidate_id,
                    "resolution": {
                        "review_sha256s": [
                            canonical_hash(row["review"]) for row in candidate_reviews
                        ],
                        "method": "synthesis",
                        "reason": "Fresh v2 reviews agree.",
                        "evidence_ids": value["checks"]["opportunity"]["evidence_ids"],
                        "addressed": [],
                        "assessment": value,
                        "substantive_disagreements": [],
                        "changed_judgment_reason": None,
                    },
                }
            ],
            "next_step": None,
        }
        return batch, reviews, resolutions

    def test_content_revision_makes_only_fresh_v2_delivery_portable(self):
        parent_path = self.root / "parent.json"
        parent_path.write_text(json.dumps(self.parent), encoding="utf-8")
        workflow = self.root / "workflow"
        initialize_workflow(
            parent_path,
            self.sources,
            workflow,
            {},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        initial = inspect_workflow(workflow)
        current = copy.deepcopy(self.parent)
        previous = current["candidates"][0]
        revised = copy.deepcopy(previous)
        revised.update(version=2, parent_version=1, question="Corrected v2 question")
        current["candidates"].append(revised)
        current["comparison"] = "Corrected current comparison."
        current["unresolved"] = ["Current access remains unknown."]
        current["packet_id"] = "content-revision-current"
        current_path = self.root / "current.json"
        current_path.write_text(json.dumps(current), encoding="utf-8")
        impact = [
            {
                "candidate_id": previous["candidate_id"],
                "status": "affected",
                "reason": "Correct the comparison and candidate text.",
            }
        ]
        event = add_snapshot(
            workflow,
            current_path,
            self.sources,
            impact[0]["reason"],
            impact,
            initial["head_sha256"],
        )
        state = inspect_workflow(workflow, event["event_sha256"])
        extraction = self.root / "extraction"
        extraction.mkdir()
        (extraction / "input-packet.json").write_bytes(canonical(self.parent) + b"\n")
        external = self.root / "extraction-receipt.json"
        external.write_text(
            json.dumps(
                {
                    "result_sha256": "b" * 64,
                    "unit_receipts": {"extraction": "c" * 64},
                }
            ),
            encoding="utf-8",
        )
        proof = {
            "raw_repaired_prose_sha256": "d" * 64,
            "request_sha256": "e" * 64,
            "result_sha256": "b" * 64,
            "unit_receipt": "c" * 64,
            "archive_sha256s": {"initial": "f" * 64},
            "actual_call_count": 1,
            "next_packet": current,
        }
        with patch(
            "stage2_live.content_revision._authenticate_extraction",
            return_value=proof,
        ):
            receipt = prepare_content_revision(
                workflow,
                state["head_sha256"],
                extraction,
                external,
                self.sources,
                impact,
                self.root / "revision",
            )
            receipt_path = self.root / "revision/content_revision.json"
            batch, reviews, resolutions = self._fresh_inputs(current, state)
            delivery = self.root / "delivery"
            manifest = build_delivery(
                workflow,
                batch,
                reviews,
                resolutions,
                delivery,
                state["head_sha256"],
                source_update_receipts=[
                    (
                        receipt_path,
                        hashlib.sha256(receipt_path.read_bytes()).hexdigest(),
                    )
                ],
            )
            stale_screening = copy.deepcopy(batch["screening"])
            stale_screening[0]["candidate_version"] = 1
            with self.assertRaisesRegex(Stage2Error, "stale-candidate-version"):
                prepare_review_batch(
                    current,
                    state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"],
                    stale_screening,
                    "seed",
                )

            tampered = copy.deepcopy(receipt)
            tampered["revisions"][0]["reason"] = "Forged after producer completion."
            receipt_path.write_text(json.dumps(tampered), encoding="utf-8")
            tampered_sha = hashlib.sha256(receipt_path.read_bytes()).hexdigest()
            with self.assertRaisesRegex(Stage2Error, "semantic-binding-mismatch"):
                build_delivery(
                    workflow,
                    batch,
                    reviews,
                    resolutions,
                    self.root / "tampered-delivery",
                    state["head_sha256"],
                    source_update_receipts=[(receipt_path, tampered_sha)],
                )
        checked = inspect_delivery(delivery, manifest["manifest_sha256"])
        self.assertEqual(checked["selection"]["action_record_status"], "complete")
        self.assertEqual(
            checked["selection"]["action_record"]["revision_history"][0]["to_version"],
            2,
        )
        self.assertEqual(receipt["affected_candidate_ids"], [previous["candidate_id"]])


if __name__ == "__main__":
    unittest.main()
