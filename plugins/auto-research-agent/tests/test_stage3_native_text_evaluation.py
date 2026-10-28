"""Offline raw-subject mechanics only; no native generation or scientific rating."""

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
    CRITERIA,
    inspect_evaluation_record,
    inspect_evaluation_request,
    prepare_evaluation,
    record_evaluation,
)
from stage3_plan.storage import MAX_ARTIFACT_BYTES, read_json  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


def raw_hash(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


class NativeTextEvaluationTests(unittest.TestCase):
    def setUp(self):
        parent = Path(PLUGIN.anchor) if os.name == "nt" else Path(tempfile.gettempdir())
        self.temp = tempfile.TemporaryDirectory(prefix="stage3-text-", dir=parent)
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.package, self.delivery = self.root / "handoff", self.root / "delivery"
        self.package.mkdir()
        self.delivery.mkdir()
        self.source_sha = "a" * 64
        self.intake = make_intake(make_plan("numeric", question_count=2))
        self.intake["source_manifest_sha256"] = self.source_sha
        self.raw = self.root / "native.md"
        self.original = b"\xef\xbb\xbf" + (
            "研究計畫\r\n材料適用性 unknown；方法與對照仍未決。\r\n"
            "此處不執行實驗。cafe\u0301\n"
        ).encode("utf-8")
        self.raw.write_bytes(self.original)
        self.output = self.root / "request.json"

        def admitted(package, delivery, *, expected_manifest_sha256):
            if (
                Path(package) != self.package
                or Path(delivery) != self.delivery
                or expected_manifest_sha256 != self.source_sha
            ):
                raise Stage3Error("synthetic source pin rejected")
            return copy.deepcopy(self.intake)

        # Existing admission remains the production boundary; fixture is explicit.
        self.admission = patch("stage3_plan.intake.admit_intake", side_effect=admitted)
        self.admitted = self.admission.start()
        self.addCleanup(self.admission.stop)
        native = patch(
            "stage3_plan.native.NativePlanner.__call__",
            side_effect=AssertionError("offline test must not dispatch"),
        )
        self.native = native.start()
        self.addCleanup(native.stop)
        self.addCleanup(self.native.assert_not_called)

    def prepare(self, **changes):
        args = dict(
            expected_manifest_sha256=self.source_sha,
            output=self.output,
            delivery=self.delivery,
            native_text=self.raw,
            expected_native_text_sha256=raw_hash(self.raw),
        )
        args.update(changes)
        return prepare_evaluation(self.package, **args)

    def judgment(self):
        request = read_json(self.output)
        return {
            "kind": "Stage3EvaluationJudgment",
            "schema_version": "1.0.0",
            "request_sha256": raw_hash(self.output),
            "reviewer": {
                "actor": "synthetic-only",
                "kind": "synthetic",
                "relationship_to_author": "unknown",
                "identity_authenticated": False,
                "evidence_ref": "offline-contract-fixture",
            },
            "criteria": [
                {
                    "criterion_id": criterion,
                    "status": "unverifiable",
                    "score": None,
                    "missing_evidence_reason": "Fixture only, no scientific rating.",
                    "question_assessments": [
                        {
                            "question_ref": ref,
                            "applicability_basis": "Synthetic mechanics only.",
                            "rationale": "Keep original missing design and unknown.",
                            "plan_locations": ["/lines/1"],
                        }
                        for ref in request["bindings"]["question_refs"]
                    ],
                }
                for criterion in CRITERIA.values()
            ],
        }

    def record(self, judgment, name="judgment.json", output="record.json"):
        path = self.root / name
        path.write_bytes(
            json.dumps(judgment, ensure_ascii=False, indent=2).encode("utf-8")
        )
        target = self.root / output
        record = record_evaluation(
            self.output,
            expected_request_sha256=raw_hash(self.output),
            judgment=path,
            expected_judgment_sha256=raw_hash(path),
            output=target,
        )
        return path, target, record

    def test_prepare_and_inspect_preserve_bytes_and_do_not_fill_design(self):
        request = self.prepare()
        subject = request["assessor_view"]["plan"]
        self.assertEqual(request["kind"], "Stage3NativeTextEvaluationRequest")
        self.assertEqual(
            set(subject), {"kind", "schema_version", "encoding", "raw_sha256", "lines"}
        )
        self.assertEqual("".join(subject["lines"]).encode("utf-8"), self.original)
        self.assertEqual(subject["raw_sha256"], raw_hash(self.raw))
        self.assertEqual(request["assessor_view"]["intake"], self.intake)
        self.assertFalse(request["bindings"]["native_execution_attested"])
        self.assertNotIn("plan_id", subject)
        self.assertNotIn("score_vector", request)
        self.assertEqual(
            inspect_evaluation_request(
                self.output, expected_sha256=raw_hash(self.output)
            ),
            request,
        )
        self.assertEqual(self.raw.read_bytes(), self.original)
        for key in (
            "execution_authorized",
            "evaluation_calls_authorized",
            "formal_execution_enabled",
            "external_claim_ready",
        ):
            self.assertIs(request["policy"][key], False)
        self.assertEqual(self.admitted.call_count, 2)

    def test_public_cli_and_existing_record_replay_keep_raw_judgment(self):
        with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
            code = main(
                [
                    "evaluation-prepare",
                    "--package",
                    str(self.package),
                    "--expected-manifest-sha256",
                    self.source_sha,
                    "--delivery",
                    str(self.delivery),
                    "--native-text",
                    str(self.raw),
                    "--expected-native-text-sha256",
                    raw_hash(self.raw),
                    "--output",
                    str(self.output),
                ]
            )
        self.assertEqual(code, 0)
        path, target, record = self.record(self.judgment())
        self.assertEqual(record["raw_judgment_text"].encode("utf-8"), path.read_bytes())
        self.assertTrue(
            all(row["score"] is None for row in record["score_vector"].values())
        )
        replay = inspect_evaluation_record(
            target,
            expected_sha256=raw_hash(target),
            request={"path": str(self.output), "sha256": raw_hash(self.output)},
            judgment={"path": str(path), "sha256": raw_hash(path)},
        )
        self.assertEqual(replay, record)
        self.assertEqual(self.raw.read_bytes(), self.original)

    def test_raw_and_source_pins_reject_before_output(self):
        with self.assertRaises(Stage3Error):
            self.prepare(expected_native_text_sha256="b" * 64)
        with self.assertRaises(Stage3Error):
            self.prepare(expected_manifest_sha256="b" * 64)
        self.assertFalse(self.output.exists())
        self.assertEqual(self.raw.read_bytes(), self.original)

    def test_inspection_rebuilds_raw_view_and_source_even_after_rehash(self):
        request = self.prepare()
        for mutation in ("lines", "authority", "identity"):
            altered = copy.deepcopy(request)
            if mutation == "lines":
                altered["assessor_view"]["plan"]["lines"][1] = (
                    "Fabricated completed design.\n"
                )
            elif mutation == "authority":
                altered["policy"]["execution_authorized"] = True
            else:
                altered["bindings"]["native_execution_attested"] = True
            self.output.write_bytes(canonical_bytes(altered))
            with self.subTest(mutation=mutation), self.assertRaises(Stage3Error):
                inspect_evaluation_request(
                    self.output, expected_sha256=raw_hash(self.output)
                )
        self.output.write_bytes(canonical_bytes(request))
        self.intake["unresolved"] = ["Changed source condition"]
        with self.assertRaises(Stage3Error):
            inspect_evaluation_request(
                self.output, expected_sha256=raw_hash(self.output)
            )
        self.intake.pop("unresolved", None)
        self.raw.write_bytes(self.original + b"changed")
        with self.assertRaises(Stage3Error):
            inspect_evaluation_request(
                self.output, expected_sha256=raw_hash(self.output)
            )

    def test_wrong_line_or_metadata_locator_retains_failed_record(self):
        self.prepare()
        for index, pointer in enumerate(("/lines/999", "/raw_sha256", "/lines/01")):
            with self.subTest(pointer=pointer):
                judgment = self.judgment()
                judgment["criteria"][0]["question_assessments"][0]["plan_locations"] = [
                    pointer
                ]
                path = self.root / f"bad-{index}.json"
                path.write_bytes(canonical_bytes(judgment))
                target = self.root / f"failure-{index}.json"
                with self.assertRaisesRegex(Stage3Error, "invalid judgment retained"):
                    record_evaluation(
                        self.output,
                        expected_request_sha256=raw_hash(self.output),
                        judgment=path,
                        expected_judgment_sha256=raw_hash(path),
                        output=target,
                    )
                self.assertEqual(
                    read_json(target)["raw_judgment_text"].encode("utf-8"),
                    path.read_bytes(),
                )
                self.assertEqual(self.raw.read_bytes(), self.original)

    def test_encoding_size_partial_options_and_write_once(self):
        for raw in (b" \r\n", b"\xff", b"x" * (MAX_ARTIFACT_BYTES + 1)):
            with self.subTest(size=len(raw)):
                self.raw.write_bytes(raw)
                with self.assertRaises(Stage3Error):
                    self.prepare()
                self.assertFalse(self.output.exists())
                self.assertEqual(self.raw.read_bytes(), raw)
        self.raw.write_bytes(self.original)
        with self.assertRaises(Stage3Error):
            self.prepare(delivery=None)
        self.prepare()
        before = self.output.read_bytes()
        with self.assertRaises(Stage3Error):
            self.prepare()
        self.assertEqual(self.output.read_bytes(), before)
        with self.assertRaises(Stage3Error):
            self.prepare(output=PLUGIN / "forbidden-native-evaluation.json")
        self.assertFalse((PLUGIN / "forbidden-native-evaluation.json").exists())

    def test_unresolved_source_questions_are_not_repaired(self):
        self.intake["questions"] = []
        with self.assertRaises(Stage3Error):
            self.prepare()
        self.assertFalse(self.output.exists())
        self.assertEqual(self.raw.read_bytes(), self.original)

    def test_structured_consumers_reject_before_dispatch_or_prose_masking(self):
        from stage3_plan.campaign_views import assessor_view
        from stage3_plan.evaluation_jobs import EvaluationJobs

        request = self.prepare()
        with self.assertRaisesRegex(Stage3Error, "native text"):
            assessor_view(request, "neutral-subject")
        jobs = object.__new__(EvaluationJobs)
        jobs.request = {"path": str(self.output), "sha256": raw_hash(self.output)}
        with self.assertRaisesRegex(Stage3Error, "native text"):
            jobs.prepare(
                "k",
                checkpoint=None,
                configuration={},
                adapter_context={},
                expected_revision=0,
            )
