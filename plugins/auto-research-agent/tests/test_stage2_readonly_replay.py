# ruff: noqa: E402 -- import the repository CLI without installing a package.
"""Read-only Stage 2 archive replay tests."""

import copy
import hashlib
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
PLUGIN = HERE.parent
sys.path.insert(0, str(PLUGIN / "cli"))
sys.path.insert(0, str(HERE))

import test_stage2_diagnostics as diagnostics_fixtures
from stage1_eval.common import canonical
from stage2_common import Stage2Error, canonical_hash
from stage2_fixture_helpers import write_stage2_fixture
from stage2_ideation import build_extraction_task
from stage2_ideation.integration import build_next_packet
from stage2_live.calibration import diagnostic_schema, expand_source_ids
from stage2_live.extraction import (
    _prompt,
    _request,
    build_span_index,
    expand_span_ids,
    generation_schema,
)
from stage2_live.judges import _execution_policy
from stage2_live.replay import (
    replay_unit,
    verify_calibration_unit,
    verify_extraction,
)
from test_stage2_ideation import valid_extraction

SNAPSHOT = "a" * 64
POLICY = {
    "schema_version": "3.1.0",
    "evaluator_bundle_sha256": "b" * 64,
    "timeout_seconds": 600,
    "max_transient_transport_retries": 1,
    "max_semantic_corrections_per_unit": 1,
    "retry_timeouts": False,
}


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(canonical(value) + b"\n")
    return path


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def replayed_provenance():
    return {
        "attempt": 1,
        "execution_status": "native-replayed",
        "reused_completed_generation": False,
        "request_fingerprint_sha256": "c" * 64,
    }


def saved_provenance():
    return {
        "attempt": 1,
        "execution_status": "native-complete",
        "reused_completed_generation": False,
        "request_fingerprint_sha256": "c" * 64,
    }


class ReadOnlyReplayTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.codex = self.root / "codex.exe"
        self.codex.write_bytes(b"bound executable")
        self.home = self.root / "evaluator-home"
        self.home.mkdir()
        self.config = {
            "codex": str(self.codex.resolve()),
            "codex_executable_sha256": digest(self.codex),
            "evaluator_home": str(self.home.resolve()),
            "model": "test-model",
            "reasoning": "high",
        }

    def make_unit(self, root, label, schema, value):
        root.mkdir(parents=True, exist_ok=True)
        write_json(root / f"{label}.schema.json", schema)
        archive = root / f"{label}.model-call"
        archive.mkdir()
        (archive / "bound.txt").write_text("archive", encoding="utf-8")
        unit = {
            "label": label,
            "value": value,
            "provenance": {"initial": saved_provenance(), "correction": None},
        }
        path = write_json(root / f"{label}.unit.json", unit)
        return digest(path), unit

    def test_replay_unit_is_read_only_and_rejects_missing_tampered_or_unsafe_inputs(
        self,
    ):
        unit_root = self.root / "unit"
        schema = {"type": "object"}
        value = {"answer": "saved"}
        receipt, _ = self.make_unit(unit_root, "sample", schema, value)
        before = {
            path.relative_to(unit_root).as_posix(): path.read_bytes()
            for path in unit_root.rglob("*")
            if path.is_file()
        }
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                return_value=(copy.deepcopy(value), replayed_provenance()),
            ) as low_level,
            patch(
                "stage1_eval.model_calls.call_model_v31",
                side_effect=AssertionError("model dispatch forbidden"),
            ) as dispatch,
        ):
            result = replay_unit(
                unit_root,
                "sample",
                receipt,
                prompt="frozen prompt",
                schema=schema,
                config=self.config,
                policy=POLICY,
                validate=lambda row: row["answer"] == "saved",
            )
        self.assertEqual(result["value"], value)
        self.assertEqual(result["actual_call_count"], 1)
        self.assertEqual(low_level.call_count, 1)
        dispatch.assert_not_called()
        after = {
            path.relative_to(unit_root).as_posix(): path.read_bytes()
            for path in unit_root.rglob("*")
            if path.is_file()
        }
        self.assertEqual(after, before)

        with self.assertRaisesRegex(Stage2Error, "unit-receipt-mismatch"):
            replay_unit(
                unit_root,
                "sample",
                "f" * 64,
                prompt="frozen prompt",
                schema=schema,
                config=self.config,
                policy=POLICY,
                validate=lambda _row: True,
            )
        with self.assertRaisesRegex(Stage2Error, "unsafe-replay-label"):
            replay_unit(
                unit_root,
                "../sample",
                receipt,
                prompt="x",
                schema=schema,
                config=self.config,
                policy=POLICY,
                validate=lambda _row: True,
            )
        (unit_root / "sample.unit.json").unlink()
        with self.assertRaisesRegex(Stage2Error, "missing-replay-file"):
            replay_unit(
                unit_root,
                "sample",
                receipt,
                prompt="x",
                schema=schema,
                config=self.config,
                policy=POLICY,
                validate=lambda _row: True,
            )

    def test_schema_mismatch_fails_before_low_level_replay(self):
        unit_root = self.root / "schema"
        receipt, _ = self.make_unit(
            unit_root, "sample", {"type": "object"}, {"answer": "saved"}
        )
        with patch("stage2_live.replay.replay_native_model_call_archive") as low_level:
            with self.assertRaisesRegex(Stage2Error, "schema-bytes-mismatch"):
                replay_unit(
                    unit_root,
                    "sample",
                    receipt,
                    prompt="x",
                    schema={"type": "array"},
                    config=self.config,
                    policy=POLICY,
                    validate=lambda _row: True,
                )
            low_level.assert_not_called()

    def test_calibration_replays_source_ids_and_keeps_scientific_approval_false(self):
        fixture = diagnostics_fixtures.Stage2DiagnosticTests()
        fixture.setUp()
        raw = diagnostics_fixtures.output(copy.deepcopy(fixture.rows))
        for row in raw["results"]:
            groups = [
                row["evidence_refs"],
                *(check["evidence_refs"] for check in row["checks"].values()),
            ]
            for refs in groups:
                for ref in refs:
                    del ref["exact_quote"]
        prompt = __import__(
            "stage2_eval.diagnostics", fromlist=["prepare_diagnostic_prompt"]
        ).prepare_diagnostic_prompt(fixture.cases, source_ids=True)
        frozen = {
            "variant": "base",
            "cases": fixture.cases,
            "prompt": prompt,
            "prompt_sha256": hashlib.sha256(prompt.encode()).hexdigest(),
            "recipe_sha256": canonical_hash(
                {
                    "recipe_id": "base",
                    "presentation_note": "fixture",
                    "case_order": [1, 2],
                }
            ),
            "recipe": dict(
                recipe_id="base",
                presentation_note="fixture",
                case_order=[1, 2],
                recipe_sha256=canonical_hash(
                    {
                        "recipe_id": "base",
                        "presentation_note": "fixture",
                        "case_order": [1, 2],
                    }
                ),
            ),
            "case_count": len(fixture.cases),
            "evidence_transport": "source-id-v1",
        }
        unit_root = self.root / "calibration"
        receipt, unit = self.make_unit(
            unit_root, "diagnostic", diagnostic_schema(source_ids=True), raw
        )
        write_json(unit_root / "frozen-unit.json", frozen)
        expanded = expand_source_ids(raw, fixture.cases)
        result = {
            "kind": "Stage2CalibrationUnit",
            "schema_version": "2.1.0",
            "evidence_transport": "source-id-v1",
            "variant": "base",
            "unit_sha256": canonical_hash(frozen),
            "case_outputs": len(expanded["results"]),
            "value": expanded,
            "provenance": unit["provenance"],
            "evidence_class": "supplied-fact-live-diagnostic",
            "semantic_validation": "pending-independent-review",
            "formal_ready": False,
            "improvement_established": False,
            "unit_receipts": {"diagnostic": receipt},
        }
        result_path = write_json(unit_root / "calibration-result.json", result)
        external = {
            "result_sha256": digest(result_path),
            "unit_receipts": {"diagnostic": receipt},
        }
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                return_value=(copy.deepcopy(raw), replayed_provenance()),
            ),
            patch(
                "stage1_eval.model_calls.call_model_v31",
                side_effect=AssertionError("model dispatch forbidden"),
            ) as dispatch,
        ):
            verified = verify_calibration_unit(
                unit_root,
                external,
                frozen_unit=frozen,
                expected_config=self.config,
                expected_policy=POLICY,
            )
        dispatch.assert_not_called()
        self.assertFalse(verified["scientific_approval"])
        self.assertEqual(verified["actual_call_count"], 1)

    def extraction_fixture(self):
        sources = self.root / "sources"
        packet = write_stage2_fixture(sources, candidate_count=0)
        raw_proposal = (
            "The monthly and annual outcomes are not directly comparable. "
            "Both reports reuse the same survey frame. "
            "Improve the existing measure with a prespecified alignment rule. "
            "A new concept uses disagreement as the measured signal."
        )
        generated = valid_extraction(raw_proposal)
        span_id = build_span_index(raw_proposal)["spans"][0]["span_id"]
        for row in generated["comparison_rows"]:
            row["spans"] = [{"span_id": span_id}]
        for row in generated["candidates"]:
            row["spans"] = [{"span_id": span_id}]
            row["candidate"].pop("candidate_id")
            row["candidate"].pop("version")
            row["candidate"].pop("parent_version")
            row["existing_candidate_id"] = None
        return sources, packet, raw_proposal, generated

    def test_extraction_replays_and_rejects_cross_source_or_result_tamper(self):
        sources, packet, raw_proposal, generated = self.extraction_fixture()
        unit_root = self.root / "extraction"
        task = build_extraction_task(raw_proposal, packet, SNAPSHOT)
        spans = build_span_index(raw_proposal)
        schema = generation_schema(spans, packet)
        prompt = _prompt(task, packet, spans, schema)
        receipt, unit = self.make_unit(unit_root, "extraction", schema, generated)
        expanded = expand_span_ids(generated, raw_proposal, spans, packet)
        from stage2_ideation import validate_extraction

        validated = validate_extraction(raw_proposal, expanded, packet, SNAPSHOT)
        next_packet = build_next_packet(
            packet, sources, raw_proposal, validated, SNAPSHOT
        )
        policy = _execution_policy(POLICY)
        request = _request(
            task,
            packet,
            sources,
            spans,
            schema,
            prompt,
            self.config["codex"],
            self.config["evaluator_home"],
            self.config["model"],
            self.config["reasoning"],
            policy,
            "native",
        )
        write_json(unit_root / "request.json", request)
        (unit_root / "raw-proposal.bin").write_bytes(raw_proposal.encode())
        write_json(unit_root / "input-packet.json", packet)
        write_json(unit_root / "span-index.json", spans)
        write_json(
            unit_root / "normalization-receipt.json",
            {
                "kind": "Stage2ExtractionNormalizationReceipt",
                "schema_version": "1.0.0",
                "input_encoding": "utf-8",
                "normalization_applied": False,
                "raw_before_sha256": hashlib.sha256(raw_proposal.encode()).hexdigest(),
                "raw_after_sha256": hashlib.sha256(raw_proposal.encode()).hexdigest(),
                "packet_canonical_sha256": canonical_hash(packet),
                "source_bindings": request["source_bindings"],
            },
        )
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
            "unit_receipts": {"extraction": receipt},
        }
        result_path = write_json(unit_root / "result.json", result)
        external = {
            "result_sha256": digest(result_path),
            "unit_receipts": {"extraction": receipt},
        }
        with (
            patch(
                "stage2_live.replay.replay_native_model_call_archive",
                return_value=(copy.deepcopy(generated), replayed_provenance()),
            ),
            patch(
                "stage1_eval.model_calls.call_model_v31",
                side_effect=AssertionError("model dispatch forbidden"),
            ) as dispatch,
        ):
            verified = verify_extraction(
                unit_root,
                external,
                raw_proposal=raw_proposal,
                packet=packet,
                source_root=sources,
                snapshot_sha256=SNAPSHOT,
                expected_config=self.config,
                expected_policy=POLICY,
            )
        dispatch.assert_not_called()
        self.assertEqual(verified["result"], result)
        self.assertFalse(verified["scientific_approval"])

        original_result = result_path.read_bytes()
        result_path.write_bytes(original_result + b" ")
        with self.assertRaisesRegex(Stage2Error, "result-receipt-mismatch"):
            verify_extraction(
                unit_root,
                external,
                raw_proposal=raw_proposal,
                packet=packet,
                source_root=sources,
                snapshot_sha256=SNAPSHOT,
                expected_config=self.config,
                expected_policy=POLICY,
            )
        result_path.write_bytes(original_result)

        (sources / packet["sources"][0]["path"]).write_text(
            "cross-source tamper", encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "source.*hash"):
            verify_extraction(
                unit_root,
                external,
                raw_proposal=raw_proposal,
                packet=packet,
                source_root=sources,
                snapshot_sha256=SNAPSHOT,
                expected_config=self.config,
                expected_policy=POLICY,
            )


if __name__ == "__main__":
    unittest.main()
