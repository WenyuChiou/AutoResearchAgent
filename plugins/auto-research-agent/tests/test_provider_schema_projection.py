"""Provider schema projection keeps local planning constraints authoritative."""

import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))
from stage1_eval.common import EvaluationError  # noqa: E402
from stage1_eval.model import _api_schema  # noqa: E402
from stage1_eval.model_calls import (  # noqa: E402
    _validate_local_schema,
    call_model_v31,
    replay_native_model_call_archive,
)
from stage3_plan.native import NativePlanner  # noqa: E402

FORBIDDEN = {
    "allOf",
    "if",
    "then",
    "else",
    "not",
    "dependentRequired",
    "dependentSchemas",
}


def forbidden_schema_paths(value, path="$", mapping=False):
    found = []
    if isinstance(value, dict):
        for key, child in value.items():
            if not mapping and key in FORBIDDEN:
                found.append(path + "." + key)
            found.extend(
                forbidden_schema_paths(
                    child,
                    path + "." + key,
                    mapping=not mapping
                    and key in {"properties", "$defs", "definitions"},
                )
            )
    elif isinstance(value, list):
        for index, child in enumerate(value):
            found.extend(forbidden_schema_paths(child, path + f"[{index}]"))
    return found


class ProviderSchemaProjectionTests(unittest.TestCase):
    def test_native_planner_projects_both_real_schema_versions(self):
        for name in (
            "stage3-research-plan.v1.schema.json",
            "stage3-research-plan.v1_1.schema.json",
        ):
            with self.subTest(schema=name), tempfile.TemporaryDirectory() as directory:
                root = Path(directory).resolve()
                schema = PLUGIN / "schemas" / name
                original_bytes = schema.read_bytes()
                full = json.loads(original_bytes)
                with mock.patch(
                    "stage1_eval.model_calls.call_model_v31", return_value=({}, {})
                ) as call:
                    NativePlanner(
                        codex="unused-offline",
                        codex_home=root,
                        capture_dir=root / "capture",
                        timeout_seconds=600,
                    )(
                        prompt="explicit synthetic offline schema check",
                        schema_path=schema,
                        output_dir=root / "plan",
                        configuration={"model": "synthetic-model", "reasoning": "low"},
                    )
                projected = call.call_args.kwargs["api_schema"](full)
                self.assertEqual(forbidden_schema_paths(projected), [])
                for definition in ("comparisons", "resource"):
                    expected = json.dumps(
                        {"allOf": full["$defs"][definition]["allOf"]}, sort_keys=True
                    )
                    self.assertIn(
                        expected, projected["$defs"][definition]["description"]
                    )
                    self.assertEqual(
                        projected["$defs"][definition]["required"],
                        full["$defs"][definition]["required"],
                    )
                    self.assertEqual(
                        set(projected["$defs"][definition]["properties"]),
                        set(full["$defs"][definition]["properties"]),
                    )
                self.assertEqual(schema.read_bytes(), original_bytes)

    def test_original_conditional_rejections_remain_enforced_locally(self):
        full = json.loads(
            (PLUGIN / "schemas" / "stage3-research-plan.v1_1.schema.json").read_bytes()
        )
        resources = {"$defs": full["$defs"], "$ref": "#/$defs/resource"}
        value = {
            "resource_id": "R1",
            "origin": "proposed",
            "availability": "available",
            "access_conditions": "Access not established.",
            "fitness": "Proposed fit.",
            "scale_basis": "Planning assumption.",
            "minimum": "Proposed minimum.",
            "standard": "Proposed standard.",
            "uncertainties": [],
        }
        _validate_local_schema(value, _api_schema(resources, preserve_constraints=True))
        with self.assertRaisesRegex(EvaluationError, "local schema validation"):
            _validate_local_schema(value, resources)
        valid = dict(
            value, availability="unknown", uncertainties=["Access must be verified."]
        )
        _validate_local_schema(valid, resources)
        comparison = {"$defs": full["$defs"], "$ref": "#/$defs/comparisons"}
        with self.assertRaisesRegex(EvaluationError, "local schema validation"):
            _validate_local_schema(
                {
                    "status": "not-applicable",
                    "description": "No comparison.",
                    "reason": "",
                },
                comparison,
            )

    def test_property_and_definition_names_are_not_schema_keywords(self):
        full = {
            "type": "object",
            "additionalProperties": False,
            "required": ["if", "allOf"],
            "properties": {"if": {"type": "string"}, "allOf": {"type": "string"}},
            "$defs": {"then": {"type": "string"}},
        }
        self.assertEqual(_api_schema(full, preserve_constraints=True), full)

    def test_new_native_archive_replays_same_projection_without_dispatch(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            home = root / "home"
            home.mkdir()
            codex = root / "codex"
            codex.write_bytes(b"explicit offline fake executable")
            schema = root / "schema.json"
            full = {
                "type": "object",
                "additionalProperties": False,
                "required": ["kind", "detail"],
                "properties": {
                    "kind": {"enum": ["ready", "draft"]},
                    "detail": {"type": "string"},
                },
                "allOf": [
                    {
                        "if": {"properties": {"kind": {"const": "ready"}}},
                        "then": {"properties": {"detail": {"minLength": 1}}},
                    }
                ],
            }
            schema.write_text(json.dumps(full), encoding="utf-8")
            original = schema.read_bytes()
            answer = {"kind": "ready", "detail": "Explicit synthetic test output."}

            def completed(command, **kwargs):
                projected = json.loads(
                    Path(command[command.index("--output-schema") + 1]).read_bytes()
                )
                self.assertEqual(forbidden_schema_paths(projected), [])
                Path(command[command.index("-o") + 1]).write_text(
                    json.dumps(answer), encoding="utf-8"
                )
                events = [
                    {
                        "type": "item.completed",
                        "item": {"type": "agent_message", "text": json.dumps(answer)},
                    },
                    {"type": "turn.completed"},
                ]
                return SimpleNamespace(
                    returncode=0,
                    stdout=("\n".join(json.dumps(x) for x in events) + "\n").encode(),
                    stderr=b"",
                )

            with mock.patch(
                "stage1_eval.model_calls._execute_bound_process", side_effect=completed
            ) as run:
                actual, receipt = call_model_v31(
                    "explicit synthetic projection and replay test",
                    schema,
                    root / "capture",
                    "plan",
                    codex=codex,
                    evaluator_home=home,
                    model="synthetic-model",
                    reasoning="low",
                    timeout=600,
                    execution_policy={
                        "schema_version": "3.1.0",
                        "timeout_seconds": 600,
                        "max_transient_transport_retries": 0,
                        "evaluator_bundle_sha256": "a" * 64,
                        "tools": "none",
                        "execution_authorized": False,
                    },
                    resume_verified=False,
                    semantic_validator=None,
                    api_schema=lambda value: _api_schema(
                        value, preserve_constraints=True
                    ),
                )
                replayed, replay = replay_native_model_call_archive(
                    receipt["call_archive"],
                    expected_prompt="explicit synthetic projection and replay test",
                    expected_schema=schema,
                    expected_config=receipt["config"],
                    expected_policy=receipt["execution_policy"],
                )
            self.assertEqual(actual, answer)
            self.assertEqual(replayed, answer)
            self.assertEqual(run.call_count, 1)
            self.assertEqual(schema.read_bytes(), original)
            self.assertEqual(
                replay["request_fingerprint_sha256"],
                receipt["request_fingerprint_sha256"],
            )


if __name__ == "__main__":
    unittest.main()
