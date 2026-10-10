"""Versioned extraction-only recovery; failed native actions remain immutable.

The saved capture and its original environment are read-only inputs. A separate
current production preflight authorizes the new extraction. No historical
binding, injected adapter, native dispatcher, or terminal-result rewrite exists.
"""

from copy import deepcopy
import hashlib
import json
from pathlib import Path

from stage1_eval.model_calls import _request_config
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_workflow import finish_action, inspect_workflow, start_action
from stage2_workflow.reviews import validate_review

from .environment import verify_environment_capture, verify_environment_start
from .native import _path_binding
from .review_models import (
    _adapter_binding,
    _captured_input,
    _review_view_version,
    extract_review,
    review_task,
)

VERSION = "1.0.0"


def _sha(path):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise Stage2Error("review-recovery-regular-file-required")
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _write_new(path, value):
    raw = (
        json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2).encode() + b"\n"
    )
    with Path(path).open("xb") as stream:
        stream.write(raw)


def _original_capture_binding(request, record, original_preflight, inventory, sources):
    settings = request["settings"]
    environments = settings.get("environment_bindings", {})
    roles = [row for key, row in environments.items() if key != "extractor"]
    if settings.get("mode") != "native" or len(roles) != 1:
        raise Stage2Error("review-recovery-original-production-role-required")
    expected = roles[0]
    stable = record["stable_request_binding"]
    for field, value in (
        ("codex_home", expected["home"]),
        ("workspace", expected["workspace"]),
        ("model", settings["bindings"]["model"]),
        ("reasoning", settings["bindings"]["reasoning"]),
    ):
        if stable.get(field) != value:
            raise Stage2Error(f"review-recovery-original-{field}-mismatch")
    profile = stable.get("codex_profile_config", {})
    if (
        {key: value for key, value in profile.items() if key != "path"}
        != expected["profile_config"]
        or canonical_hash(stable.get("policy_bindings")) != expected["policy_sha256"]
        or canonical_hash(original_preflight) != expected["preflight_sha256"]
        or canonical_hash(inventory) != expected["preflight_inventory_receipt_sha256"]
    ):
        raise Stage2Error("review-recovery-original-environment-mismatch")
    saved_sources = stable.get("input_bindings", {}).get("sources", {})
    actual_sources = _path_binding(sources)
    if (
        saved_sources.get("kind") != "directory"
        or saved_sources.get("files") != actual_sources.get("files")
        or saved_sources.get("sha256") != actual_sources.get("sha256")
    ):
        raise Stage2Error("review-recovery-original-sources-mismatch")


def _current_execution_binding(preflight, native, home, workspace):
    # An old proof pointing to the frozen subject is not proof for this executor.
    library = Path(__file__).resolve().parents[2]
    if Path(native["config_bindings"].get("capture_cli", "")).resolve() != library:
        raise Stage2Error("review-recovery-current-executor-source-required")
    _, report = verify_environment_start(preflight, native, home, workspace)
    if (
        report.get("status") != "passed"
        or report.get("runtime_gate") is not True
        or report.get("validation_scope") != "production-single"
    ):
        raise Stage2Error("review-recovery-current-production-proof-required")
    config = _request_config(
        native["codex"], home, native["model"], native["reasoning"]
    )
    # Legacy extraction uses a scratch cwd; it cannot satisfy this interface's
    # separately proven workspace. The opt-in namespace pins the actual cwd.
    if "native_namespace" not in config or config.get("effective_cwd") != str(
        workspace
    ):
        raise Stage2Error("review-recovery-proven-extraction-workspace-required")
    return deepcopy(
        {
            "preflight_sha256": canonical_hash(preflight),
            "native": {
                **native,
                "codex": str(native["codex"]),
                "config_bindings": {
                    key: str(Path(value).resolve())
                    for key, value in native["config_bindings"].items()
                },
            },
            "home": str(home),
            "workspace": str(workspace),
            "model_call_config": config,
            "configs": {
                key: _path_binding(value)
                for key, value in native["config_bindings"].items()
            },
            "implementation": {
                **_adapter_binding(native["codex"]),
                "recovery_source_sha256": _sha(Path(__file__)),
            },
        }
    )


def recover_failed_review(
    run_dir,
    failed_action_id,
    capture_dir,
    capture_receipt,
    original_preflight,
    original_inventory_receipt,
    *,
    candidate_id,
    role,
    source_root,
    expected_snapshot_sha256,
    expected_head,
    execution_preflight,
    native,
    evaluator_home,
    extractor_workspace,
    output_dir,
):
    """Append one authenticated missing extraction; never repeat a native review.

    Repeating the exact completed request invokes only externally receipted
    extraction replay. Failed/partial recoveries require a separately authorized
    recovery interface; this operation never creates retry IDs to bypass them.
    """
    state = inspect_workflow(run_dir, expected_head=expected_head)
    snapshot = state["latest_snapshot"]
    snapshot_sha = snapshot["event"]["payload"]["snapshot_sha256"]
    target = state["actions"].get(failed_action_id)
    if (
        snapshot_sha != expected_snapshot_sha256
        or target is None
        or target["result"] is None
        or target["result"]["status"] != "failed"
        or target["request"]["action_kind"] != "stage2-independent-review"
        or target["request"]["snapshot_sha256"] != snapshot_sha
        or failed_action_id != f"review-{snapshot_sha[:12]}-{candidate_id}-{role}"
    ):
        raise Stage2Error("review-recovery-failed-current-review-required")
    packet = snapshot["packet"]
    validate_packet(packet, source_root)
    inputs = target["request"]["inputs"]
    if inputs.get("role") != role:
        raise Stage2Error("review-recovery-role-mismatch")
    # Reconstruct the exact retained view version instead of upgrading it.
    view = review_task(
        packet,
        candidate_id,
        snapshot_sha,
        role,
        review_view_version=(
            _review_view_version(
                packet, candidate_id, snapshot_sha, role, inputs.get("view_sha256")
            )
        ),
    )
    capture = Path(capture_dir).resolve()
    if _sha(capture / "run.json") != capture_receipt:
        raise Stage2Error("review-recovery-capture-receipt-mismatch")
    record, _ = _captured_input(capture, capture_receipt, view, "review_view")
    _original_capture_binding(
        target["request"],
        record,
        original_preflight,
        original_inventory_receipt,
        source_root,
    )
    original_environment = verify_environment_capture(
        capture, capture_receipt, original_preflight, original_inventory_receipt
    )
    if original_environment.get("status") != "verified":
        raise Stage2Error("review-recovery-original-environment-not-verified")
    capture_binding = _path_binding(capture)
    home = Path(evaluator_home).resolve()
    workspace = Path(extractor_workspace).resolve()
    output = Path(output_dir).resolve()
    protected = [state["root"], capture, Path(source_root).resolve(), home, workspace]
    if Path(output_dir).is_symlink() or any(
        output == item or output in item.parents or item in output.parents
        for item in protected
    ):
        raise Stage2Error("review-recovery-output-collision")
    if home == Path(record["stable_request_binding"]["codex_home"]).resolve():
        raise Stage2Error("review-recovery-separate-extractor-required")
    current = _current_execution_binding(execution_preflight, native, home, workspace)
    recovery_inputs = {
        "schema_version": VERSION,
        "failed_action_id": failed_action_id,
        "failed_request_sha256": target["request"]["request_sha256"],
        "failed_result_sha256": target["result"]["result_sha256"],
        "candidate_id": candidate_id,
        "role": role,
        "view_sha256": canonical_hash(view),
        "capture_dir": str(capture),
        "capture_receipt": capture_receipt,
        "capture_tree_sha256": capture_binding["sha256"],
        "original_environment": original_environment,
    }
    settings = {"execution": current, "output_dir": str(output), "formal_ready": False}
    action_id = (
        "review-recovery-"
        + canonical_hash([VERSION, failed_action_id, snapshot_sha, capture_receipt])[
            :24
        ]
    )
    existing = state["actions"].get(action_id)
    if existing is None and output.exists() and any(output.iterdir()):
        raise Stage2Error("review-recovery-orphan-output-needs-recovery")
    started = start_action(
        state["root"],
        action_id,
        "stage2-independent-review-recovery",
        recovery_inputs,
        settings,
        state["head_sha256"],
    )
    saved = None
    if started["reuse"]:
        artifact = started["result"]["artifacts"]["summary.json"]
        saved = json.loads(
            (state["root"] / artifact["stored_path"]).read_text(encoding="utf-8")
        )
    output.mkdir(parents=True, exist_ok=True)
    try:
        if (
            _current_execution_binding(execution_preflight, native, home, workspace)
            != current
        ):
            raise Stage2Error("review-recovery-execution-changed-before-handoff")
        if _path_binding(capture) != capture_binding:
            raise Stage2Error("review-recovery-capture-changed-before-handoff")
        value = extract_review(
            packet,
            source_root,
            candidate_id,
            snapshot_sha,
            role,
            capture,
            capture_receipt,
            codex=native["codex"],
            evaluator_home=home,
            model=native["model"],
            reasoning=native["reasoning"],
            execution_policy=native["extraction_policy"],
            output_dir=output / "extraction",
            resume=saved is not None,
            resume_receipt=saved["review_result"]["replay_receipt"] if saved else None,
            review_view_version=view["schema_version"],
        )
        if (
            value.get("adapter_mode") != "native"
            or value.get("native_capture_verified") is not True
            or value.get("capture_evidence_class") != "host-native-capture"
            or value.get("scientific_truth_attested") is not False
        ):
            raise Stage2Error("review-recovery-authentic-extraction-required")
        validate_review(value["review"], view, packet)
        if value.get("native_receipt") != capture_receipt:
            raise Stage2Error("review-recovery-extraction-capture-mismatch")
        # The failed record and selected source snapshot remain the same after
        # the extraction; optimistic journal locking rejects concurrent updates.
        retained = inspect_workflow(
            state["root"],
            expected_head=(
                state["head_sha256"] if saved else started["event"]["event_sha256"]
            ),
        )
        if (
            retained["actions"][failed_action_id] != target
            or _sha(capture / "run.json") != capture_receipt
        ):
            raise Stage2Error("review-recovery-original-changed-during-extraction")
        if _path_binding(capture) != capture_binding:
            raise Stage2Error("review-recovery-capture-changed-during-extraction")
        replayed_record, _ = _captured_input(
            capture, capture_receipt, view, "review_view"
        )
        replayed_environment = verify_environment_capture(
            capture, capture_receipt, original_preflight, original_inventory_receipt
        )
        if replayed_record != record or replayed_environment != original_environment:
            raise Stage2Error("review-recovery-original-replay-changed")
        _original_capture_binding(
            target["request"],
            replayed_record,
            original_preflight,
            original_inventory_receipt,
            source_root,
        )
        if (
            _current_execution_binding(execution_preflight, native, home, workspace)
            != current
        ):
            raise Stage2Error("review-recovery-execution-changed-during-extraction")
        for label in ("initial-review", "initial-review-correction"):
            request_path = output / "extraction" / f"{label}.model-call/request.json"
            if label == "initial-review-correction" and not request_path.exists():
                continue
            _sha(request_path)
            request = json.loads(request_path.read_text(encoding="utf-8"))
            if request.get("config") != current["model_call_config"]:
                raise Stage2Error("review-recovery-extraction-handoff-mismatch")
        summary = {
            "kind": "Stage2FailedReviewExtractionRecovery",
            "schema_version": VERSION,
            "action_id": action_id,
            "binding": recovery_inputs,
            "review_result": value,
            "requested_native_calls": 0,
            "scientific_truth_attested": False,
            "formal_ready": False,
            "cost": None,
        }
        if saved is not None:
            if saved != summary:
                raise Stage2Error("review-recovery-completed-result-mismatch")
            return {**summary, "replayed": True, "head_sha256": state["head_sha256"]}
        summary_path = output / "recovery-summary.json"
        _write_new(summary_path, summary)
        event = finish_action(
            state["root"],
            action_id,
            "complete",
            {"summary.json": {"path": str(summary_path), "sha256": _sha(summary_path)}},
            None,
            None,
            started["event"]["event_sha256"],
        )
        return {**summary, "replayed": False, "head_sha256": event["event_sha256"]}
    except Exception as error:
        if saved is None:
            failure_path = output / "recovery-failure.json"
            _write_new(
                failure_path, {"error_type": type(error).__name__, "error": str(error)}
            )
            finish_action(
                state["root"],
                action_id,
                "failed",
                {
                    "failure.json": {
                        "path": str(failure_path),
                        "sha256": _sha(failure_path),
                    }
                },
                None,
                str(error),
                started["event"]["event_sha256"],
            )
        raise
