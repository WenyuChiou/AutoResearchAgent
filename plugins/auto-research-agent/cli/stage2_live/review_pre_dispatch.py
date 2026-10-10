"""Read-only proof of a deterministic namespace rejection before model dispatch."""

import hashlib
import json
from pathlib import Path

from stage1_eval.common import canonical
from stage1_eval.model import _api_schema
from stage1_eval.model_calls import _normalize_policy, _request_record
from stage2_common import Stage2Error, canonical_hash

from .judge_schemas import _object, _text
from .judges import _execution_policy
from .native import _path_binding
from .review_models import _review_prompt, _schema

VERSION = "1.1.0"
_FILES = {
    "recovery-failure.json",
    "extraction/capture-binding.json",
    "extraction/initial-review.schema.json",
    *{
        "extraction/initial-review.model-call/" + name
        for name in (
            "request.json",
            "prompt.txt",
            "schema.json",
            "generation-schema.json",
            "native-namespace.json",
        )
    },
}


def namespace_output_allowed(config, output):
    namespace = config.get("native_namespace", {}).get("scope", {})
    if not all(
        isinstance(namespace.get(key), str) for key in ("capture_root", "workspace")
    ):
        raise Stage2Error("review-recovery-proven-extraction-workspace-required")
    roots = [Path(namespace[key]).resolve() for key in ("capture_root", "workspace")]
    return any(Path(output).resolve().is_relative_to(root) for root in roots)


def authenticate_pre_dispatch_predecessor(state, binding, inputs, packet, view, raw):
    """Missing attempts are insufficient: the authenticated guard must reject.

    The default current model-call source digest is checked by _request_record.
    No historical override, archived code import, or process invocation exists.
    """
    keys = {"schema_version", "action_id", "action_sha256", "output_tree_sha256"}
    if (
        not isinstance(binding, dict)
        or set(binding) != keys
        or binding["schema_version"] != VERSION
    ):
        raise Stage2Error("review-recovery-pre-dispatch-binding-required")
    previous = state["actions"].get(binding["action_id"])
    expected_id = (
        "review-recovery-"
        + canonical_hash(
            [
                "1.0.0",
                inputs["failed_action_id"],
                view["snapshot_sha256"],
                inputs["capture_receipt"],
            ]
        )[:24]
    )
    if (
        previous is None
        or binding["action_id"] != expected_id
        or canonical_hash(previous) != binding["action_sha256"]
        or previous["request"]["action_kind"] != "stage2-independent-review-recovery"
        or previous["request"]["inputs"] != {**inputs, "schema_version": "1.0.0"}
        or previous["result"] is None
        or previous["result"]["status"] != "failed"
    ):
        raise Stage2Error("review-recovery-pre-dispatch-predecessor-mismatch")
    settings = previous["request"]["settings"]
    output = Path(settings["output_dir"])
    if not output.is_absolute() or any(
        p.is_symlink() for p in (output, *output.parents)
    ):
        raise Stage2Error("review-recovery-pre-dispatch-output-aliased")
    paths = list(output.rglob("*"))
    if (
        any(p.is_symlink() for p in paths)
        or {p.relative_to(output).as_posix() for p in paths if p.is_file()} != _FILES
    ):
        raise Stage2Error("review-recovery-pre-dispatch-attempt-or-extra-evidence")
    tree = _path_binding(output)
    if tree["sha256"] != binding["output_tree_sha256"]:
        raise Stage2Error("review-recovery-pre-dispatch-tree-mismatch")
    failure = output / "recovery-failure.json"
    if hashlib.sha256(failure.read_bytes()).hexdigest() != previous["result"][
        "artifacts"
    ]["failure.json"]["sha256"] or json.loads(failure.read_bytes()) != {
        "error_type": "EvaluationError",
        "error": "model-call archive violates frozen attempt limit",
    }:
        raise Stage2Error("review-recovery-pre-dispatch-failure-mismatch")
    extraction = output / "extraction"
    archive = extraction / "initial-review.model-call"
    execution = settings["execution"]
    config = execution["model_call_config"]
    capture_binding = json.loads((extraction / "capture-binding.json").read_bytes())
    if capture_binding != {
        "receipt": inputs["capture_receipt"],
        "view_sha256": canonical_hash(view),
        "raw_sha256": hashlib.sha256(raw.encode("utf-8")).hexdigest(),
        "implementation": {
            k: v
            for k, v in execution["implementation"].items()
            if k != "recovery_source_sha256"
        },
    }:
        raise Stage2Error("review-recovery-pre-dispatch-capture-binding-mismatch")
    # This rejection precedes _execute_bound_process in the bound model-call
    # implementation. A valid path with missing receipts remains ambiguous.
    if namespace_output_allowed(config, archive / "generation-schema.json"):
        raise Stage2Error("review-recovery-pre-dispatch-rejection-not-established")
    schema = _object(
        {
            "assessment": _schema(packet),
            "assumptions": {"type": "array", "items": _text()},
            "strongest_alternative": _text(),
            "change_conditions": {"type": "array", "items": _text()},
        }
    )
    schema_raw = (extraction / "initial-review.schema.json").read_bytes()
    if json.loads(schema_raw) != schema:
        raise Stage2Error("review-recovery-pre-dispatch-schema-mismatch")
    prompt = _review_prompt(view, raw)
    generation = canonical(_api_schema(schema, preserve_constraints=True))
    policy = _normalize_policy(
        _execution_policy(execution["native"]["extraction_policy"]), None
    )
    expected = _request_record(
        prompt, schema_raw, generation, config, policy, "initial-review"
    )
    if (
        json.loads((archive / "request.json").read_bytes()) != expected
        or (archive / "prompt.txt").read_bytes() != prompt.encode("utf-8")
        or (archive / "schema.json").read_bytes() != schema_raw
        or (archive / "generation-schema.json").read_bytes() != generation
        or hashlib.sha256((archive / "native-namespace.json").read_bytes()).hexdigest()
        != config["native_namespace"]["sha256"]
    ):
        raise Stage2Error("review-recovery-pre-dispatch-preparation-mismatch")
    return {**binding, "output_dir": str(output), "requested_model_calls": 0}
