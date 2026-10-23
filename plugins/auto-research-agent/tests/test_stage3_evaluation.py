"""Offline Stage 3 evaluation wiring; fixtures establish mechanics only."""

import copy
from contextlib import redirect_stderr, redirect_stdout
import hashlib
import io
import json
import os
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage3_plan.__main__ import main  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes  # noqa: E402
from stage3_plan.evaluation import (  # noqa: E402
    CATALOG_PATH,
    CRITERIA,
    GUIDANCE_PATH,
    prepare_evaluation,
    record_evaluation,
)
from stage3_plan.planner import draft_synthetic_plan  # noqa: E402
from stage3_plan.storage import read_json  # noqa: E402
from stage3_plan_fixtures import TOPICS, make_intake, make_plan  # noqa: E402


def raw_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class Stage3EvaluationTests(unittest.TestCase):
    def setUp(self):
        # The Windows host may redirect TEMP and HOME into a Git worktree.
        private_parent = (
            Path(PLUGIN.anchor) if os.name == "nt" else Path(tempfile.gettempdir())
        )
        self.temp = tempfile.TemporaryDirectory(
            prefix="stage3-eval-", dir=private_parent
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = make_plan("numeric", question_count=3, shared_path=True)
        self.intake = make_intake(self.plan)
        self.package = self.root / "package"

        def callback(**_kwargs):
            return {
                "raw_response": canonical_bytes(self.plan),
                "provenance": {"kind": "synthetic"},
            }

        saved = draft_synthetic_plan(
            self.intake,
            self.package,
            callback,
            configuration={"model": "synthetic-model", "reasoning": "medium"},
            plan_id=self.plan["plan_id"],
        )
        self.manifest_sha256 = saved["manifest"]["manifest_sha256"]
        self.request_path = self.root / "evaluation-request.json"
        self.request = prepare_evaluation(
            self.package,
            expected_manifest_sha256=self.manifest_sha256,
            output=self.request_path,
        )

    def judgment(self, statuses=None, *, request_sha256=None):
        statuses = statuses or {dimension: ("scored", 2) for dimension in CRITERIA}
        rows = []
        for dimension, criterion_id in CRITERIA.items():
            status, detail = statuses[dimension]
            if status == "grader_error":
                rows.append(
                    {
                        "criterion_id": criterion_id,
                        "status": status,
                        "score": None,
                        "error": {"kind": detail[0], "message": detail[1]},
                    }
                )
                continue
            row = {
                "criterion_id": criterion_id,
                "status": status,
                "score": detail,
                "question_assessments": [
                    {
                        "question_ref": question["question_ref"],
                        "applicability_basis": "This plan-level criterion applies to the selected question.",
                        "rationale": "Synthetic assessment for contract verification only.",
                        "plan_locations": [f"/question_plans/{index}"],
                    }
                    for index, question in enumerate(self.plan["questions"])
                ],
            }
            if status == "unverifiable":
                row["missing_evidence_reason"] = (
                    "Necessary independent evidence is unavailable."
                )
            rows.append(row)
        return {
            "kind": "Stage3EvaluationJudgment",
            "schema_version": "1.0.0",
            "request_sha256": request_sha256 or raw_hash(self.request_path),
            "reviewer": {
                "actor": "synthetic-rater",
                "kind": "synthetic",
                "relationship_to_author": "unknown",
                "identity_authenticated": False,
                "evidence_ref": "synthetic-contract-test",
            },
            "criteria": rows,
        }

    def save_judgment(self, value, name="judgment.json", *, pretty=False):
        path = self.root / name
        if pretty:
            path.write_text(
                json.dumps(value, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
        else:
            path.write_bytes(canonical_bytes(value))
        return path

    def test_prepare_is_generic_version_bound_and_preserves_plan_bytes(self):
        before = {
            name: (self.package / name).read_bytes()
            for name in ("plan.json", "request.json", "manifest.json")
        }
        self.assertEqual(
            self.request["bindings"]["question_refs"],
            [row["question_ref"] for row in self.plan["questions"]],
        )
        self.assertEqual(self.request["bindings"]["admission_scope"], "synthetic-test")
        self.assertEqual(
            [row["id"] for row in self.request["catalog"]["selected_criteria"]],
            list(CRITERIA.values()),
        )
        self.assertEqual(
            self.request["guidance"]["raw_sha256"], raw_hash(GUIDANCE_PATH)
        )
        self.assertEqual(self.request["catalog"]["raw_sha256"], raw_hash(CATALOG_PATH))
        self.assertTrue(self.request["semantic_rubric"]["distinct_from_scoring"])
        self.assertEqual(
            self.request["assessor_view"], {"plan": self.plan, "intake": self.intake}
        )
        self.assertTrue(
            all(
                value is False
                for key, value in self.request["policy"].items()
                if key != "scores_are_separate"
            )
        )
        self.assertEqual(
            before, {name: (self.package / name).read_bytes() for name in before}
        )

        for topic in (*TOPICS, "simulation-method"):
            with self.subTest(topic=topic):
                candidate = make_plan(
                    topic if topic in TOPICS else "numeric",
                    question_count=4,
                    shared_path=True,
                )
                if topic == "simulation-method":
                    candidate["designs"][0]["family"] = "simulation method development"
                intake = make_intake(candidate)

                def callback(**_kwargs):
                    return {
                        "raw_response": canonical_bytes(candidate),
                        "provenance": {"kind": "synthetic"},
                    }

                package = self.root / f"{topic}-package"
                saved = draft_synthetic_plan(
                    intake,
                    package,
                    callback,
                    configuration={"model": "synthetic-model", "reasoning": "medium"},
                    plan_id=candidate["plan_id"],
                )
                prepared = prepare_evaluation(
                    package,
                    expected_manifest_sha256=saved["manifest"]["manifest_sha256"],
                    output=self.root / f"{topic}-request.json",
                )
                self.assertEqual(len(prepared["bindings"]["question_refs"]), 4)
                self.assertEqual(candidate["results"][0]["status"], "not-run")
                self.assertIsNone(candidate["results"][0]["observed_value"])

    def test_public_cli_round_trip_keeps_vector_raw_text_and_null_error_distinct(self):
        cli_request = self.root / "cli-request.json"
        stdout = io.StringIO()
        with redirect_stdout(stdout):
            exit_code = main(
                [
                    "evaluation-prepare",
                    "--package",
                    str(self.package),
                    "--expected-manifest-sha256",
                    self.manifest_sha256,
                    "--output",
                    str(cli_request),
                ]
            )
        self.assertEqual(exit_code, 0)
        statuses = {
            "P7": ("scored", 0),
            "P8": ("unverifiable", None),
            "P9": ("grader_error", ("timeout", "HTTP 429 before any rating")),
        }
        judgment = self.judgment(statuses, request_sha256=raw_hash(cli_request))
        judgment_path = self.save_judgment(judgment, "cli-judgment.json", pretty=True)
        record_path = self.root / "record.json"
        with redirect_stdout(io.StringIO()):
            exit_code = main(
                [
                    "evaluation-record",
                    "--request",
                    str(cli_request),
                    "--expected-request-sha256",
                    raw_hash(cli_request),
                    "--judgment",
                    str(judgment_path),
                    "--expected-judgment-sha256",
                    raw_hash(judgment_path),
                    "--output",
                    str(record_path),
                ]
            )
        self.assertEqual(exit_code, 0)
        record = read_json(record_path)
        self.assertEqual(
            record["score_vector"],
            {
                "P7": {"criterion_id": CRITERIA["P7"], "status": "scored", "score": 0},
                "P8": {
                    "criterion_id": CRITERIA["P8"],
                    "status": "unverifiable",
                    "score": None,
                },
                "P9": {
                    "criterion_id": CRITERIA["P9"],
                    "status": "grader_error",
                    "score": None,
                },
            },
        )
        self.assertNotIn("total", record)
        self.assertEqual(
            record["raw_judgment_text"].encode("utf-8"), judgment_path.read_bytes()
        )
        self.assertFalse(record["reviewer"]["identity_authenticated"])
        self.assertFalse(record["execution_authorized"])
        self.assertFalse(record["evaluation_calls_authorized"])

    def test_invalid_judgments_are_retained_as_failures_without_repair(self):
        base = self.judgment()
        cases = {}
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["score"] = True
        cases["bool-score"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["score"] = 3
        cases["range-score"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][2] = copy.deepcopy(invalid["criteria"][0])
        cases["duplicate-id"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"].pop()
        cases["missing-id"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["criterion_id"] = "P10.UNKNOWN"
        cases["unknown-id"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["question_assessments"][0]["question_ref"] = (
            "unknown/question"
        )
        cases["unknown-question"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["question_assessments"][0]["plan_locations"] = [
            "/missing"
        ]
        cases["bad-pointer"] = invalid
        for pointer in (
            "/question_plans/-1",
            "/question_plans/01",
            "/question_plans/~2",
        ):
            invalid = copy.deepcopy(base)
            invalid["criteria"][0]["question_assessments"][0]["plan_locations"] = [
                pointer
            ]
            cases["invalid-pointer-" + str(len(cases))] = invalid
        invalid = copy.deepcopy(base)
        invalid["reviewer"]["kind"] = []
        cases["reviewer-kind-type"] = invalid
        invalid = copy.deepcopy(base)
        invalid["criteria"][0]["status"] = {}
        cases["status-type"] = invalid

        for name, value in cases.items():
            with self.subTest(name=name):
                judgment_path = self.save_judgment(value, f"{name}.json", pretty=True)
                output = self.root / f"{name}-record.json"
                with self.assertRaisesRegex(Stage3Error, "retained in failure record"):
                    record_evaluation(
                        self.request_path,
                        expected_request_sha256=raw_hash(self.request_path),
                        judgment=judgment_path,
                        expected_judgment_sha256=raw_hash(judgment_path),
                        output=output,
                    )
                failure = read_json(output)
                self.assertEqual(failure["record_status"], "failed")
                self.assertEqual(
                    failure["raw_judgment_text"].encode("utf-8"),
                    judgment_path.read_bytes(),
                )
                with self.assertRaisesRegex(Stage3Error, "output exists"):
                    record_evaluation(
                        self.request_path,
                        expected_request_sha256=raw_hash(self.request_path),
                        judgment=judgment_path,
                        expected_judgment_sha256=raw_hash(judgment_path),
                        output=output,
                    )

    def test_rehash_tamper_rejected_for_stale_inputs_and_private_path(self):
        judgment_path = self.save_judgment(self.judgment())
        with self.assertRaisesRegex(Stage3Error, "request hash mismatch"):
            record_evaluation(
                self.request_path,
                expected_request_sha256="0" * 64,
                judgment=judgment_path,
                expected_judgment_sha256=raw_hash(judgment_path),
                output=self.root / "stale-request.json",
            )
        with self.assertRaisesRegex(Stage3Error, "judgment hash mismatch"):
            record_evaluation(
                self.request_path,
                expected_request_sha256=raw_hash(self.request_path),
                judgment=judgment_path,
                expected_judgment_sha256="0" * 64,
                output=self.root / "stale-judgment.json",
            )

        tampered = copy.deepcopy(self.request)
        tampered["bindings"]["admission_scope"] = "strict-selected"
        tampered_path = self.root / "tampered-request.json"
        tampered_path.write_bytes(canonical_bytes(tampered))
        tampered_judgment = self.save_judgment(
            self.judgment(request_sha256=raw_hash(tampered_path)),
            "tampered-judgment.json",
        )
        with self.assertRaisesRegex(Stage3Error, "binding mismatch"):
            record_evaluation(
                tampered_path,
                expected_request_sha256=raw_hash(tampered_path),
                judgment=tampered_judgment,
                expected_judgment_sha256=raw_hash(tampered_judgment),
                output=self.root / "tampered-record.json",
            )

        numeric_flag = copy.deepcopy(self.request)
        numeric_flag["policy"]["execution_authorized"] = 0
        numeric_flag_path = self.root / "numeric-flag-request.json"
        numeric_flag_path.write_bytes(canonical_bytes(numeric_flag))
        with self.assertRaisesRegex(Stage3Error, "binding mismatch"):
            record_evaluation(
                numeric_flag_path,
                expected_request_sha256=raw_hash(numeric_flag_path),
                judgment=judgment_path,
                expected_judgment_sha256=raw_hash(judgment_path),
                output=self.root / "numeric-flag-record.json",
            )

        with self.assertRaisesRegex(Stage3Error, "outside Git"):
            prepare_evaluation(
                self.package,
                expected_manifest_sha256=self.manifest_sha256,
                output=PLUGIN / "forbidden-evaluation.json",
            )

    def test_revalidates_catalog_guidance_and_source_bytes(self):
        catalog = self.root / "catalog.json"
        guidance = self.root / "guidance.md"
        catalog.write_bytes(CATALOG_PATH.read_bytes())
        guidance.write_bytes(GUIDANCE_PATH.read_bytes())
        request_path = self.root / "copied-bindings-request.json"
        prepare_evaluation(
            self.package,
            expected_manifest_sha256=self.manifest_sha256,
            output=request_path,
            catalog_path=catalog,
            guidance_path=guidance,
        )
        judgment_path = self.save_judgment(
            self.judgment(request_sha256=raw_hash(request_path)),
            "copied-bindings-judgment.json",
        )
        guidance.write_text(
            guidance.read_text(encoding="utf-8") + "\nchanged", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage3Error, "binding mismatch"):
            record_evaluation(
                request_path,
                expected_request_sha256=raw_hash(request_path),
                judgment=judgment_path,
                expected_judgment_sha256=raw_hash(judgment_path),
                output=self.root / "guidance-tamper-record.json",
            )

        catalog2 = self.root / "catalog2.json"
        guidance2 = self.root / "guidance2.md"
        catalog2.write_bytes(CATALOG_PATH.read_bytes())
        guidance2.write_bytes(GUIDANCE_PATH.read_bytes())
        request2 = self.root / "catalog-binding-request.json"
        prepare_evaluation(
            self.package,
            expected_manifest_sha256=self.manifest_sha256,
            output=request2,
            catalog_path=catalog2,
            guidance_path=guidance2,
        )
        judgment2 = self.save_judgment(
            self.judgment(request_sha256=raw_hash(request2)),
            "catalog-binding-judgment.json",
        )
        catalog_value = json.loads(catalog2.read_text(encoding="utf-8"))
        catalog_value["criteria"][-1]["anchors"]["2"] = "Rehashed tampering."
        catalog2.write_bytes(canonical_bytes(catalog_value))
        with self.assertRaisesRegex(Stage3Error, "binding mismatch"):
            record_evaluation(
                request2,
                expected_request_sha256=raw_hash(request2),
                judgment=judgment2,
                expected_judgment_sha256=raw_hash(judgment2),
                output=self.root / "catalog-tamper-record.json",
            )

        # Source packages are immutable inputs; changing bytes invalidates their manifest.
        plan_path = self.package / "plan.json"
        plan_path.write_bytes(plan_path.read_bytes() + b" ")
        with self.assertRaisesRegex(Stage3Error, "plan artifact hash mismatch"):
            record_evaluation(
                self.request_path,
                expected_request_sha256=raw_hash(self.request_path),
                judgment=self.save_judgment(
                    self.judgment(), "source-tamper-judgment.json"
                ),
                expected_judgment_sha256=raw_hash(
                    self.root / "source-tamper-judgment.json"
                ),
                output=self.root / "source-tamper-record.json",
            )

    def test_malformed_json_is_preserved_in_failure_record(self):
        judgment_path = self.root / "malformed.json"
        judgment_path.write_text(
            '{"kind":"Stage3EvaluationJudgment",', encoding="utf-8"
        )
        output = self.root / "malformed-record.json"
        with self.assertRaisesRegex(Stage3Error, "retained in failure record"):
            record_evaluation(
                self.request_path,
                expected_request_sha256=raw_hash(self.request_path),
                judgment=judgment_path,
                expected_judgment_sha256=raw_hash(judgment_path),
                output=output,
            )
        self.assertEqual(
            read_json(output)["raw_judgment_text"].encode("utf-8"),
            judgment_path.read_bytes(),
        )

    def test_deep_json_and_invalid_unicode_are_retained_as_failures(self):
        invalid_text = self.judgment()
        invalid_text["criteria"][0]["question_assessments"][0]["rationale"] = "\ud800"
        cases = {
            "deep-json": ("[" * 1200 + "0" + "]" * 1200).encode("utf-8"),
            "invalid-unicode": json.dumps(invalid_text, ensure_ascii=True).encode(
                "utf-8"
            ),
        }
        for name, raw in cases.items():
            with self.subTest(name=name):
                judgment = self.root / f"{name}-judgment.json"
                judgment.write_bytes(raw)
                output = self.root / f"{name}-record.json"
                stderr = io.StringIO()
                with redirect_stdout(io.StringIO()), redirect_stderr(stderr):
                    code = main(
                        [
                            "evaluation-record",
                            "--request",
                            str(self.request_path),
                            "--expected-request-sha256",
                            raw_hash(self.request_path),
                            "--judgment",
                            str(judgment),
                            "--expected-judgment-sha256",
                            raw_hash(judgment),
                            "--output",
                            str(output),
                        ]
                    )
                self.assertEqual(code, 1)
                failure = read_json(output)
                self.assertEqual(failure["record_status"], "failed")
                self.assertEqual(failure["raw_judgment_text"].encode("utf-8"), raw)
                self.assertEqual(judgment.read_bytes(), raw)
                error = json.loads(stderr.getvalue())
                self.assertEqual(error["status"], "failed")
                for flag in (
                    "execution_authorized",
                    "evaluation_calls_authorized",
                    "formal_execution_enabled",
                    "external_claim_ready",
                ):
                    self.assertIs(error[flag], False)

    def test_verified_snapshot_is_parsed_once_and_guidance_identity_is_checked(self):
        judgment = self.save_judgment(self.judgment(), "snapshot-judgment.json")
        from stage3_plan import evaluation

        original_read = evaluation.read_bytes
        reads = {}

        def read_once(path):
            key = Path(path)
            if key in {self.request_path, judgment}:
                reads[key] = reads.get(key, 0) + 1
                if reads[key] > 1:
                    raise AssertionError("verified input was reopened")
            return original_read(path)

        with patch.object(evaluation, "read_bytes", side_effect=read_once):
            record = record_evaluation(
                self.request_path,
                expected_request_sha256=raw_hash(self.request_path),
                judgment=judgment,
                expected_judgment_sha256=raw_hash(judgment),
                output=self.root / "snapshot-record.json",
            )
        self.assertEqual(reads, {self.request_path: 1, judgment: 1})
        self.assertEqual(record["record_status"], "recorded")
        guidance = self.root / "wrong-guidance.md"
        guidance.write_text("Unversioned guidance", encoding="utf-8")
        with self.assertRaisesRegex(Stage3Error, "version marker missing"):
            prepare_evaluation(
                self.package,
                expected_manifest_sha256=self.manifest_sha256,
                output=self.root / "wrong-guidance-request.json",
                guidance_path=guidance,
            )


if __name__ == "__main__":
    unittest.main()
