"""Bound native-capture tests for Stage 2 review-model extraction."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest


HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

from stage1_eval.common import EvaluationError, canonical  # noqa: E402
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
from stage2_live.review_models import (  # noqa: E402
    _schema,
    extract_resolution,
    extract_review,
    _resolution_extraction_label,
    reconciliation_task,
    review_task,
)
from test_stage2_checker import assessment  # noqa: E402


SNAPSHOT = "a" * 64
POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "b" * 64,
    "timeout_seconds": 600,
    "max_transient_transport_retries": 1,
    "max_semantic_corrections_per_unit": 1,
    "retry_timeouts": False,
}


def extraction_assessment(packet):
    full = assessment(packet)
    return {
        key: copy.deepcopy(full[key])
        for key in (
            "checks",
            "disposition",
            "reason",
            "next_step",
            "scope_change_requested",
        )
    }


def initial_payload(packet):
    return {
        "assessment": extraction_assessment(packet),
        "assumptions": ["The observations use compatible outcome definitions."],
        "strongest_alternative": "A measurement artifact could explain the result.",
        "change_conditions": ["A conflicting source would change this assessment."],
    }


def resolution_payload(packet):
    return {
        "assessment": extraction_assessment(packet),
        "method": "synthesis",
        "reason": "The independent records agree on the evidence-bound checks.",
        "evidence_ids": ["ev-1"],
        "addressed": [],
        "substantive_disagreements": [],
        "changed_judgment_reason": None,
    }


class StubModel:
    def __init__(self, values):
        self.values = values
        self.calls = []

    def __call__(self, prompt, schema_path, output_dir, label, **_options):
        self.calls.append(
            {
                "label": label,
                "prompt": prompt,
                "schema": json.loads(Path(schema_path).read_text(encoding="utf-8")),
            }
        )
        return copy.deepcopy(self.values[label]), {
            "execution_status": "injected-test",
            "label": label,
        }


class OutputWritingStubModel(StubModel):
    """Mirror the production adapter's label.json side effect."""

    def __init__(self, values):
        super().__init__(values)
        self.raw_outputs = {}

    def __call__(self, prompt, schema_path, output_dir, label, **options):
        value, provenance = super().__call__(
            prompt, schema_path, output_dir, label, **options
        )
        raw = canonical(value) + b"\n"
        (Path(output_dir) / f"{label}.json").write_bytes(raw)
        self.raw_outputs[label] = raw
        return value, provenance


class Stage2LiveReviewModelTests(unittest.TestCase):
    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self.sources = self.root / "sources"
        self.packet = write_stage2_fixture(self.sources, candidate_count=2)
        self.codex = self.root / "codex"
        self.codex.write_bytes(b"test executable identity")
        self.extractor_home = self.root / "extractor-home"
        self.extractor_home.mkdir()

    def capture(self, name, key, view, raw, session):
        root = self.root / name
        archived = root / "archive" / "input_bindings" / key
        archived.parent.mkdir(parents=True)
        view_raw = canonical(view) + b"\n"
        archived.write_bytes(view_raw)
        (root / "stdout.jsonl").write_text(
            json.dumps({"type": "synthetic-test-transcript", "text": raw}) + "\n",
            encoding="utf-8",
        )
        subject_home = self.root / f"subject-home-{name}"
        subject_home.mkdir()
        record = {
            "capture_mode": "injected-test-adapter",
            "evidence_class": "synthetic-test-only",
            "stable_request_binding": {
                "codex_home": str(subject_home.resolve()),
                "input_bindings": {
                    key: {
                        "kind": "file",
                        "path": str((self.root / f"{name}-{key}.json").resolve()),
                        "sha256": hashlib.sha256(view_raw).hexdigest(),
                    }
                },
            },
            "event_summary": {
                "status": "complete",
                "thread_id": session,
                "usage": {"input_tokens": 1, "output_tokens": 1},
                "tool_events": [],
                "final_output": raw,
                "parse_error": None,
            },
        }
        run = root / "run.json"
        run.write_bytes(canonical(record) + b"\n")
        receipt = hashlib.sha256(run.read_bytes()).hexdigest()
        return root, receipt, record

    @staticmethod
    def synthetic_verifier(capture_dir, receipt):
        run = Path(capture_dir) / "run.json"
        if hashlib.sha256(run.read_bytes()).hexdigest() != receipt:
            raise AssertionError("test verifier received a mismatched receipt")
        record = json.loads(run.read_text(encoding="utf-8"))
        return record, record["event_summary"]["final_output"]

    def review_args(self, capture, receipt, output, adapter, role="challenger"):
        return {
            "packet": self.packet,
            "source_root": self.sources,
            "candidate_id": "candidate-1",
            "snapshot_sha256": SNAPSHOT,
            "role": role,
            "capture_dir": capture,
            "receipt": receipt,
            "codex": self.codex,
            "evaluator_home": self.extractor_home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
            "output_dir": self.root / output,
            "call_adapter": adapter,
            "capture_verifier": self.synthetic_verifier,
        }

    def independent_reviews(self, *, disagree_on_opportunity=False):
        reviews = []
        for role in ("challenger", "feasibility"):
            view = review_task(self.packet, "candidate-1", SNAPSHOT, role)
            capture, receipt, _ = self.capture(
                f"contract-{role}",
                "review_view",
                view,
                f"Independent {role} reconciliation input.",
                f"session-contract-{role}",
            )
            payload = initial_payload(self.packet)
            if disagree_on_opportunity and role == "challenger":
                payload["assessment"]["checks"]["opportunity"]["score"] = 1
                payload["assessment"]["disposition"] = "revise"
                payload["assessment"]["next_step"] = (
                    "Verify the bounded measurement before recommendation."
                )
            adapter = StubModel({"initial-review": payload})
            reviews.append(
                extract_review(
                    **self.review_args(
                        capture,
                        receipt,
                        f"contract-out-{role}",
                        adapter,
                        role,
                    )
                )["review"]
            )
        return reviews

    def resolution_args(self, reviews, capture, receipt, output, adapter):
        return {
            "packet": self.packet,
            "source_root": self.sources,
            "candidate_id": "candidate-1",
            "snapshot_sha256": SNAPSHOT,
            "reviews": reviews,
            "capture_dir": capture,
            "receipt": receipt,
            "codex": self.codex,
            "evaluator_home": self.extractor_home,
            "model": "test-model",
            "reasoning": "high",
            "execution_policy": POLICY,
            "output_dir": self.root / output,
            "call_adapter": adapter,
            "capture_verifier": self.synthetic_verifier,
        }

    def test_schema_uses_canonical_five_axis_assessment_statuses(self):
        schema = _schema(self.packet)
        checks = schema["properties"]["checks"]
        self.assertEqual(
            set(checks["required"]),
            {"opportunity", "value", "answerability", "materials", "execution"},
        )
        for axis in checks["required"]:
            finding = checks["properties"][axis]
            self.assertEqual(
                finding["properties"]["status"]["enum"],
                ["assessed", "unknown", "not-applicable"],
            )
            self.assertEqual(
                set(finding["required"]),
                {
                    "status",
                    "score",
                    "rationale",
                    "evidence_ids",
                    "blocking",
                    "next_check",
                },
            )

    def test_wrong_receipt_or_archived_role_view_is_rejected_before_model(self):
        view = review_task(self.packet, "candidate-1", SNAPSHOT, "challenger")
        capture, receipt, _ = self.capture(
            "wrong-binding", "review_view", view, "Independent prose.", "session-a"
        )
        adapter = StubModel({"initial-review": initial_payload(self.packet)})
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            extract_review(
                **self.review_args(capture, "0" * 64, "wrong-receipt", adapter)
            )
        self.assertEqual(adapter.calls, [])

        archived = capture / "archive/input_bindings/review_view"
        archived.write_bytes(canonical({**view, "role": "feasibility"}) + b"\n")
        record = json.loads((capture / "run.json").read_text())
        record["stable_request_binding"]["input_bindings"]["review_view"]["sha256"] = (
            hashlib.sha256(archived.read_bytes()).hexdigest()
        )
        (capture / "run.json").write_bytes(canonical(record) + b"\n")
        receipt = hashlib.sha256((capture / "run.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "view-mismatch"):
            extract_review(**self.review_args(capture, receipt, "wrong-view", adapter))
        self.assertEqual(adapter.calls, [])

    def test_wrong_candidate_or_version_cannot_be_filled_by_model(self):
        view = review_task(self.packet, "candidate-1", SNAPSHOT, "challenger")
        capture, receipt, _ = self.capture(
            "candidate-binding",
            "review_view",
            view,
            "Candidate one prose.",
            "session-b",
        )
        adapter = StubModel({"initial-review": initial_payload(self.packet)})
        args = self.review_args(capture, receipt, "wrong-candidate", adapter)
        args["candidate_id"] = "candidate-2"
        with self.assertRaisesRegex(Stage2Error, "view-mismatch"):
            extract_review(**args)

        result = extract_review(
            **self.review_args(capture, receipt, "right-candidate", adapter)
        )
        self.assertEqual(
            (result["review"]["candidate_id"], result["review"]["candidate_version"]),
            ("candidate-1", 1),
        )

        revised = copy.deepcopy(self.packet)
        version_two = copy.deepcopy(revised["candidates"][0])
        version_two.update(version=2, parent_version=1)
        revised["candidates"].append(version_two)
        stale_args = self.review_args(capture, receipt, "stale-version", adapter)
        stale_args["packet"] = revised
        with self.assertRaisesRegex(Stage2Error, "view-mismatch"):
            extract_review(**stale_args)

        current_view = review_task(revised, "candidate-1", SNAPSHOT, "challenger")
        current_capture, current_receipt, _ = self.capture(
            "current-version",
            "review_view",
            current_view,
            "Current version prose.",
            "session-current",
        )
        current_args = self.review_args(
            current_capture, current_receipt, "current-version-out", adapter
        )
        current_args["packet"] = revised
        current = extract_review(**current_args)
        self.assertEqual(current["review"]["candidate_version"], 2)

    def test_stale_forged_or_self_declared_native_capture_is_rejected(self):
        view = review_task(self.packet, "candidate-1", SNAPSHOT, "challenger")
        capture, receipt, record = self.capture(
            "forged", "review_view", view, "I declare native success.", "session-c"
        )
        adapter = StubModel({"initial-review": initial_payload(self.packet)})
        record["event_summary"]["thread_id"] = "forged-session"
        (capture / "run.json").write_bytes(canonical(record) + b"\n")
        with self.assertRaisesRegex(Stage2Error, "receipt-mismatch"):
            extract_review(**self.review_args(capture, receipt, "stale", adapter))

        receipt = hashlib.sha256((capture / "run.json").read_bytes()).hexdigest()
        record["capture_mode"] = "authentic-subprocess"
        record["evidence_class"] = "host-native-capture"
        (capture / "run.json").write_bytes(canonical(record) + b"\n")
        receipt = hashlib.sha256((capture / "run.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "capture-label-mismatch"):
            extract_review(
                **self.review_args(capture, receipt, "false-native", adapter)
            )

    def test_missing_reviewer_cannot_produce_resolution(self):
        view = review_task(self.packet, "candidate-1", SNAPSHOT, "challenger")
        capture, receipt, _ = self.capture(
            "single", "review_view", view, "Only one review.", "session-one"
        )
        adapter = StubModel({"initial-review": initial_payload(self.packet)})
        review = extract_review(
            **self.review_args(capture, receipt, "single-out", adapter)
        )["review"]
        with self.assertRaisesRegex(Stage2Error, "all-independent-reviewers"):
            extract_resolution(
                self.packet,
                self.sources,
                "candidate-1",
                SNAPSHOT,
                [review],
                self.root / "unused-capture",
                "0" * 64,
                codex=self.codex,
                evaluator_home=self.extractor_home,
                model="test-model",
                reasoning="high",
                execution_policy=POLICY,
                output_dir=self.root / "unused-output",
                call_adapter=adapter,
                capture_verifier=self.synthetic_verifier,
            )

    def test_independent_initial_reviews_and_evidence_resolution_are_test_labeled(self):
        reviews = []
        prompts = []
        for role, session in (
            ("challenger", "session-challenge"),
            ("feasibility", "session-feasible"),
        ):
            view = review_task(self.packet, "candidate-1", SNAPSHOT, role)
            raw = f"Independent {role} prose with its own assumptions."
            capture, receipt, _ = self.capture(role, "review_view", view, raw, session)
            adapter = StubModel({"initial-review": initial_payload(self.packet)})
            result = extract_review(
                **self.review_args(capture, receipt, f"out-{role}", adapter, role)
            )
            self.assertEqual(result["adapter_mode"], "injected-test")
            self.assertEqual(result["capture_evidence_class"], "synthetic-test-only")
            self.assertIsNone(result["native_capture_verified"])
            self.assertFalse(result["scientific_truth_attested"])
            self.assertIn(raw, adapter.calls[0]["prompt"])
            self.assertNotIn(
                "Independent feasibility",
                adapter.calls[0]["prompt"] if role == "challenger" else "",
            )
            prompts.append(adapter.calls[0]["prompt"])
            reviews.append(result["review"])

        self.assertNotEqual(reviews[0]["session_id"], reviews[1]["session_id"])
        self.assertNotEqual(
            reviews[0]["native_artifact"]["sha256"],
            reviews[1]["native_artifact"]["sha256"],
        )
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        capture, receipt, _ = self.capture(
            "resolution",
            "reconciliation_task",
            task,
            "Resolution prose cites ev-1 and preserves the independent records.",
            "session-resolution",
        )
        adapter = StubModel({"resolution-extraction": resolution_payload(self.packet)})
        result = extract_resolution(
            self.packet,
            self.sources,
            "candidate-1",
            SNAPSHOT,
            reviews,
            capture,
            receipt,
            codex=self.codex,
            evaluator_home=self.extractor_home,
            model="test-model",
            reasoning="high",
            execution_policy=POLICY,
            output_dir=self.root / "out-resolution",
            call_adapter=adapter,
            capture_verifier=self.synthetic_verifier,
        )
        self.assertEqual(result["adapter_mode"], "injected-test")
        self.assertIsNone(result["native_capture_verified"])
        self.assertEqual(result["resolution"]["evidence_ids"], ["ev-1"])
        self.assertEqual(
            result["resolution"]["review_sha256s"],
            [canonical_hash(row) for row in reviews],
        )

    def test_resolution_contract_accepts_exact_categorical_and_substantive_ids(self):
        reviews = self.independent_reviews(disagree_on_opportunity=True)
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        self.assertEqual(
            task["pending"]["disagreements"], ["opportunity", "disposition"]
        )
        substantive = "The reviews disagree about the measurement boundary."
        raw = "Evidence verification resolves the opportunity and measurement boundary disagreements."
        capture, receipt, _ = self.capture(
            "exact-resolution",
            "reconciliation_task",
            task,
            raw,
            "session-exact-resolution",
        )
        payload = resolution_payload(self.packet)
        payload.update(
            method="source-verification",
            substantive_disagreements=[substantive],
            addressed=["opportunity", "disposition", substantive],
            changed_judgment_reason="The source-bound measurement record supports score 2.",
        )
        adapter = StubModel({"resolution-extraction": payload})

        result = extract_resolution(
            **self.resolution_args(
                reviews, capture, receipt, "exact-resolution-out", adapter
            )
        )

        self.assertEqual(
            result["resolution"]["addressed"],
            ["opportunity", "disposition", substantive],
        )
        prompt_payload = json.loads(adapter.calls[0]["prompt"].split("\n", 1)[1])
        contract = prompt_payload["field_contract"]
        self.assertEqual(
            contract,
            {
                "contract_id": "stage2-reconciliation-extraction-fields",
                "schema_version": "1.0.0",
                "pending_categorical_ids": ["opportunity", "disposition"],
                "rules": contract["rules"],
            },
        )
        self.assertIn("verbatim", contract["rules"]["addressed"])
        self.assertIn("reason", contract["rules"]["addressed"])
        self.assertIn(
            "existing, source-supported evidence ID",
            contract["rules"]["assessment_evidence"],
        )
        self.assertIn("status unknown", contract["rules"]["assessment_evidence"])
        self.assertIn("Do not infer", contract["rules"]["resolution"])

    def test_resolution_rejects_prose_in_addressed_instead_of_exact_ids(self):
        reviews = self.independent_reviews(disagree_on_opportunity=True)
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        capture, receipt, _ = self.capture(
            "prose-addressed",
            "reconciliation_task",
            task,
            "The reviewers discussed and resolved the opportunity disagreement.",
            "session-prose-addressed",
        )
        invalid = resolution_payload(self.packet)
        invalid.update(
            method="source-verification",
            addressed=["The opportunity disagreement was resolved."],
            changed_judgment_reason="The source-bound record supports score 2.",
        )
        adapter = StubModel(
            {
                "resolution-extraction": invalid,
                "resolution-extraction-correction": invalid,
            }
        )

        with self.assertRaisesRegex(Stage2Error, "unresolved-disagreement"):
            extract_resolution(
                **self.resolution_args(
                    reviews, capture, receipt, "prose-addressed-out", adapter
                )
            )
        self.assertEqual(
            [call["label"] for call in adapter.calls],
            ["resolution-extraction", "resolution-extraction-correction"],
        )

    def test_empty_assessed_evidence_is_corrected_once_to_valid_resolution(self):
        reviews = self.independent_reviews()
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        capture, receipt, _ = self.capture(
            "evidence-correction",
            "reconciliation_task",
            task,
            "The saved reconciliation supports each assessed axis with ev-1.",
            "session-evidence-correction",
        )
        invalid = resolution_payload(self.packet)
        for axis in ("opportunity", "value"):
            invalid["assessment"]["checks"][axis]["evidence_ids"] = []
        valid = resolution_payload(self.packet)
        adapter = StubModel(
            {
                "resolution-extraction": invalid,
                "resolution-extraction-correction": valid,
            }
        )

        result = extract_resolution(
            **self.resolution_args(
                reviews, capture, receipt, "evidence-correction-out", adapter
            )
        )

        self.assertEqual(
            [call["label"] for call in adapter.calls],
            ["resolution-extraction", "resolution-extraction-correction"],
        )
        self.assertIn(
            "evidence_ids: [] should be non-empty",
            result["extraction_provenance"]["correction_reason"],
        )
        for axis in ("opportunity", "value"):
            self.assertEqual(
                result["resolution"]["assessment"]["checks"][axis]["evidence_ids"],
                ["ev-1"],
            )
        correction_prompt = adapter.calls[1]["prompt"]
        self.assertIn("stage2-reconciliation-extraction-fields", correction_prompt)
        self.assertIn('"pending_categorical_ids": []', correction_prompt)

    def test_model_output_and_public_resolution_envelope_use_distinct_paths(self):
        reviews = self.independent_reviews()
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        capture, receipt, _ = self.capture(
            "separate-resolution-paths",
            "reconciliation_task",
            task,
            "The saved reconciliation supports the bounded synthesis.",
            "session-separate-resolution-paths",
        )
        adapter = OutputWritingStubModel(
            {"resolution-extraction": resolution_payload(self.packet)}
        )
        output = "separate-resolution-paths-out"

        result = extract_resolution(
            **self.resolution_args(reviews, capture, receipt, output, adapter)
        )

        output_dir = self.root / output
        raw_path = output_dir / "resolution-extraction.json"
        envelope_path = output_dir / "resolution.json"
        self.assertEqual(result["extraction_unit_label"], "resolution-extraction")
        self.assertEqual(
            result["replay_receipt"]["unit_receipts"].keys(),
            {"resolution-extraction"},
        )
        self.assertEqual(
            raw_path.read_bytes(), adapter.raw_outputs["resolution-extraction"]
        )
        self.assertNotEqual(raw_path.read_bytes(), envelope_path.read_bytes())
        envelope = json.loads(envelope_path.read_text(encoding="utf-8"))
        self.assertEqual(envelope["extraction_unit_label"], "resolution-extraction")
        self.assertEqual(envelope["resolution"], result["resolution"])

    def test_interrupted_legacy_collision_fails_closed_without_regeneration(self):
        reviews = self.independent_reviews()
        task = reconciliation_task(self.packet, "candidate-1", SNAPSHOT, reviews)
        capture, receipt, _ = self.capture(
            "legacy-collision",
            "reconciliation_task",
            task,
            "The legacy saved reconciliation was accepted before envelope finalization.",
            "session-legacy-collision",
        )
        output = self.root / "legacy-collision-out"
        output.mkdir()
        collided_raw = canonical(resolution_payload(self.packet)) + b"\n"
        (output / "resolution.json").write_bytes(collided_raw)
        replay_receipt = {
            "result_sha256": None,
            "unit_receipts": {"resolution": "a" * 64},
        }
        self.assertEqual(
            _resolution_extraction_label(True, replay_receipt), "resolution"
        )
        adapter = StubModel({})

        with self.assertRaisesRegex(EvaluationError, "saved result differs"):
            extract_resolution(
                **self.resolution_args(
                    reviews, capture, receipt, "legacy-collision-out", adapter
                ),
                resume=True,
                resume_receipt=replay_receipt,
            )

        self.assertEqual(adapter.calls, [])
        self.assertEqual((output / "resolution.json").read_bytes(), collided_raw)


if __name__ == "__main__":
    unittest.main()
