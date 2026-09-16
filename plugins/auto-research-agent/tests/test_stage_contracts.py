"""Synthetic public-contract examples; no research or evaluator answers."""

import copy
import json
from pathlib import Path
import unittest

from jsonschema import Draft202012Validator, FormatChecker


SCHEMA = Path(__file__).resolve().parents[1] / "schemas/stage-contracts.v1.schema.json"
NOW = "2026-01-01T00:00:00Z"


def examples():
    artifact = dict(
        kind="ArtifactRef",
        schema_version="1.0.0",
        artifact_id="a1",
        artifact_type="validator-report",
        path="reports/validation.json",
        sha256="a" * 64,
        producer="s1",
        created_at=NOW,
    )
    gate = dict(
        kind="GateResult",
        schema_version="1.0.0",
        gate_name="coverage",
        outcome="review-required",
        reasons=["closest-unverified"],
        blocking_items=["closest-work evidence"],
        evidence_refs=[artifact],
    )
    return {
        "ArtifactRef": artifact,
        "ResearchRun": dict(
            kind="ResearchRun",
            schema_version="1.0.0",
            run_id="r1",
            objective="Synthetic research question",
            created_at=NOW,
            current_stage=1,
            constraints=["three query rounds"],
            versions={"plugin": "0.1.0"},
            input_refs=[],
        ),
        "StageRun": dict(
            kind="StageRun",
            schema_version="1.0.0",
            stage_run_id="s1",
            run_id="r1",
            stage=1,
            phase="plan",
            status="pending",
            attempt=1,
            started_at=None,
            ended_at=None,
            input_refs=[],
        ),
        "DecisionEvent": dict(
            kind="DecisionEvent",
            schema_version="1.0.0",
            event_id="d1",
            run_id="r1",
            stage_run_id="s1",
            sequence=1,
            created_at=NOW,
            actor="agent-1",
            actor_type="agent",
            subject_id="c1",
            prior_decision=None,
            new_decision="pending",
            reason_code="metadata-insufficient",
            rationale="Inspect saved evidence",
            evidence_refs=[],
            reverses_event_id=None,
            authorization=None,
        ),
        "GateResult": gate,
        "StageResult": dict(
            kind="StageResult",
            schema_version="1.0.0",
            stage_run_id="s1",
            status="human-review",
            outputs=[],
            validator_report=artifact,
            metrics={"verified_claims": None},
            gate=gate,
            next_allowed_action="human-review",
        ),
    }


class StageContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        schema = json.loads(SCHEMA.read_text(encoding="utf-8"))
        Draft202012Validator.check_schema(schema)
        cls.validator = Draft202012Validator(schema, format_checker=FormatChecker())

    def test_all_six_interfaces_accept_roundtrip_examples(self):
        for kind, example in examples().items():
            with self.subTest(kind=kind):
                self.validator.validate(json.loads(json.dumps(example)))

    def test_required_fields_and_unknown_versions_fail(self):
        for kind, example in examples().items():
            for field in example:
                with self.subTest(kind=kind, missing=field):
                    invalid = copy.deepcopy(example)
                    del invalid[field]
                    self.assertFalse(self.validator.is_valid(invalid))
            example["schema_version"] = "99.0.0"
            self.assertFalse(self.validator.is_valid(example))

    def test_artifact_reference_rejects_unsafe_paths_bad_hash_and_time(self):
        for field, value in [
            ("path", p)
            for p in [
                "/tmp/a",
                "C:/a",
                "../a",
                "raw/../a",
                "raw\\a",
                "raw//a",
                "raw/./a",
                "raw/a\n",
            ]
        ] + [
            ("sha256", "unknown"),
            ("sha256", "a" * 64 + "\n"),
            ("created_at", "yesterday"),
        ]:
            with self.subTest(field=field, value=value):
                artifact = examples()["ArtifactRef"]
                artifact[field] = value
                self.assertFalse(self.validator.is_valid(artifact))

    def test_unicode_path_and_nullable_metrics_are_preserved(self):
        artifact = examples()["ArtifactRef"] | {"path": "raw/家庭.json"}
        self.validator.validate(artifact)
        result = examples()["StageResult"]
        self.validator.validate(result)
        self.assertIsNone(json.loads(json.dumps(result))["metrics"]["verified_claims"])

    def test_stage_states_and_later_stage_interfaces(self):
        for stage in range(1, 7):
            record = examples()["StageRun"]
            record.update(
                stage=stage, status="running", phase="execute", started_at=NOW
            )
            self.validator.validate(record)
        for changes in [
            {"stage": 7},
            {"attempt": 0},
            {"status": "done"},
            {"phase": "search"},
            {"status": "completed"},
            {"status": "running"},
            {"unexpected": True},
        ]:
            record = examples()["StageRun"] | changes
            with self.subTest(changes=changes):
                self.assertFalse(self.validator.is_valid(record))

    def test_human_decision_requires_exact_input_and_state_hash(self):
        event = examples()["DecisionEvent"]
        event.update(
            actor="reviewer-1",
            actor_type="human",
            prior_decision="include",
            new_decision="exclude",
            reverses_event_id="d0",
        )
        self.assertFalse(self.validator.is_valid(event))
        event["authorization"] = {
            "input": "Exclude this candidate",
            "state_sha256": "b" * 64,
        }
        self.validator.validate(event)
        event["authorization"]["state_sha256"] = "not-a-hash"
        self.assertFalse(self.validator.is_valid(event))

    def test_stop_requires_pass_without_blockers(self):
        result = examples()["StageResult"]
        result.update(status="completed", next_allowed_action="stop-sufficient")
        self.assertFalse(self.validator.is_valid(result))
        result["gate"].update(outcome="pass", blocking_items=[])
        self.validator.validate(result)
        result["gate"]["blocking_items"] = ["missing evidence"]
        self.assertFalse(self.validator.is_valid(result))
        result["gate"]["blocking_items"] = []
        result["status"] = "running"
        self.assertFalse(self.validator.is_valid(result))
