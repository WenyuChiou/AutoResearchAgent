"""Stage3 no-tool adapter over the existing native model-call primitive.

The primitive's archive identity is retained. It is never called a Stage2 proof,
strict delivery or independent scientific review. There is no subject policy.
"""

import hashlib
import math
from pathlib import Path

from .contracts import Stage3Error, canonical_bytes, digest
from .storage import private_output


class NativePlanner:
    def __init__(self, *, codex, codex_home, capture_dir, timeout_seconds):
        self.codex = codex
        self.home = codex_home
        self.capture = private_output(capture_dir)
        if (
            type(timeout_seconds) not in (int, float)
            or timeout_seconds <= 0
            or not math.isfinite(timeout_seconds)
        ):
            raise Stage3Error("finite positive native planning deadline required")
        self.timeout = timeout_seconds

    @property
    def request_context(self):
        return {
            "kind": "Stage3NativePlanner",
            "codex": str(self.codex),
            "codex_home": str(self.home),
            "capture_dir": str(self.capture),
            "timeout_seconds": self.timeout,
        }

    def __call__(self, *, prompt, schema_path, output_dir, configuration):
        # Imports are lazy: inspect, check and render never initialize a model.
        from stage1_eval.model import _api_schema
        from stage1_eval.model_calls import call_model_v31

        if self.capture.exists():
            raise Stage3Error(
                "native capture already attempted; inspect retained evidence"
            )
        output = Path(output_dir).resolve()
        capture = self.capture.resolve()
        if (
            capture == output
            or capture.is_relative_to(output)
            or output.is_relative_to(capture)
        ):
            raise Stage3Error("native capture and plan evidence must be separate")
        policy = {
            "kind": "Stage3PlanningExecutionPolicy",
            "schema_version": "3.1.0",
            "timeout_seconds": self.timeout,
            "max_transient_transport_retries": 0,
            "evaluator_bundle_sha256": digest(
                {
                    "operation": "stage3.scientific-plan.v1",
                    "schema_sha256": hashlib.sha256(
                        Path(schema_path).read_bytes()
                    ).hexdigest(),
                }
            ),
            "tools": "none",
            "execution_authorized": False,
        }
        result, primitive = call_model_v31(
            prompt,
            schema_path,
            capture,
            "stage3-plan",
            codex=self.codex,
            evaluator_home=self.home,
            model=configuration["model"],
            reasoning=configuration["reasoning"],
            timeout=self.timeout,
            execution_policy=policy,
            resume_verified=False,
            semantic_validator=None,
            api_schema=lambda value: _api_schema(value, preserve_constraints=True),
            operation_config={"web_search": "disabled", "approval_policy": "never"},
        )
        return {
            "raw_response": canonical_bytes(result),
            "provenance": {
                "operation": "stage3.scientific-plan.v1",
                "kind": "Stage3PlanningGeneration",
                "capture_dir": str(capture),
                "primitive_provenance": primitive,
                "scientific_acceptance": "not-established",
                "execution_authorized": False,
            },
        }


def verify_native_generation(root, generation):
    """Read-only replay original native bytes; never dispatch or relabel proofs."""
    from stage1_eval.model_calls import replay_native_model_call_archive
    from .storage import read_bytes

    primitive = generation["primitive_provenance"]
    if (
        generation.get("operation") != "stage3.scientific-plan.v1"
        or primitive.get("config", {}).get("operation_config")
        != {"web_search": "disabled", "approval_policy": "never"}
        or primitive.get("execution_policy", {}).get("kind")
        != "Stage3PlanningExecutionPolicy"
    ):
        raise Stage3Error("native planning operation/policy is not source-only Stage3")
    output, replay = replay_native_model_call_archive(
        primitive["call_archive"],
        expected_prompt=read_bytes(root / "prompt.txt").decode("utf-8"),
        expected_schema=root / "schema.json",
        expected_config=primitive["config"],
        expected_policy=primitive["execution_policy"],
    )
    for field in (
        "request_fingerprint_sha256",
        "attempt_record_sha256",
        "output_sha256",
        "stdout_sha256",
        "stderr_sha256",
        "model",
        "reasoning",
    ):
        if primitive[field] != replay[field]:
            raise Stage3Error("native planning receipt changed")
    if canonical_bytes(output) != read_bytes(root / "raw-response.json"):
        raise Stage3Error("native planning output differs from saved response")
