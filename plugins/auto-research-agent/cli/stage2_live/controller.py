"""Sequential, receipt-bound Stage 2 controller.

This module composes the existing workflow, native capture, extraction, review,
reconciliation, and delivery APIs.  It does not select a candidate or attest
scientific truth.  The private adapter seam exists only for deterministic tests;
results produced through it are permanently labelled synthetic.
"""

import copy
import hashlib
import json
import shutil
from pathlib import Path, PurePosixPath, PureWindowsPath

from stage2_check.contracts import latest_candidates
from stage2_common import (
    Stage2Error,
    canonical_hash,
    current_prior_work_reviews,
    validate_packet,
)
from stage2_ideation import build_research_task
from stage2_ideation.integration import build_next_packet
from stage2_workflow.completion import inspect_completion
from stage2_workflow.delivery import build_delivery, inspect_delivery
from stage2_workflow.orchestration import prepare_review_batch, reconcile_batch
from stage2_workflow.reviews import REVIEW_VIEW_VERSION_CURRENT
from stage2_workflow.store import (
    add_snapshot,
    finish_action,
    inspect_workflow,
    start_action,
)

from stage2_live import review_models
from stage2_live.environment import (
    environment_key,
    native_for_environment,
    preflight_for_environment,
    verify_environment_capture,
    verify_environment_start,
)
from stage2_live.extraction import run_live_extraction
from stage2_live.judges import _execution_policy
from stage2_live.native import (
    SUBJECT_EXECUTION_POLICY,
    capture_native,
    codex_runtime_sha,
    verify_capture,
)
from stage2_live.native_proposal import choose_captured_proposal
from stage2_live.preflight import require_matching_preflight_contract, verify_preflight
from stage2_live.replay import replay_unit, verify_extraction
from stage2_live.research_followups import (
    build_research_followup_task,
    validate_research_followup_policy,
)
from stage2_live.review_models import (
    extract_resolution,
    extract_review,
    reconciliation_task,
)

VERSION = "1.0.0"
ROLE_POLICY_VERSION = "1.1.0"
ROLES = ("challenger", "feasibility")


def _json_bytes(value):
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        + b"\n"
    )


def _write_new(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    data = value if isinstance(value, bytes) else _json_bytes(value)
    try:
        with path.open("xb") as stream:
            stream.write(data)
    except FileExistsError as error:
        raise Stage2Error(f"controller-output-collision: {path}") from error


def _file_sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _tree_binding(path):
    root = Path(path).resolve()
    if root.is_file() and not root.is_symlink():
        return {"kind": "file", "sha256": _file_sha(root)}
    if not root.is_dir() or root.is_symlink():
        raise Stage2Error(f"controller-binding-missing: {root}")
    files = {}
    for item in sorted(root.rglob("*"), key=lambda row: row.as_posix()):
        if item.is_symlink():
            raise Stage2Error(f"controller-binding-symlink: {item}")
        if item.is_file():
            files[item.relative_to(root).as_posix()] = _file_sha(item)
    return {"kind": "directory", "files": files, "sha256": canonical_hash(files)}


def _native_binding_bytes(path):
    """Recompute native.py's byte identity while deliberately ignoring paths."""

    root = Path(path).resolve()
    if root.is_file() and not root.is_symlink():
        return {"kind": "file", "sha256": _file_sha(root)}
    if not root.is_dir() or root.is_symlink():
        raise Stage2Error(f"controller-binding-missing: {root}")
    files = {}
    for item in sorted(root.rglob("*"), key=lambda row: row.as_posix()):
        if item.is_symlink():
            raise Stage2Error(f"controller-binding-symlink: {item}")
        if item.is_file():
            files[item.relative_to(root).as_posix()] = _file_sha(item)
    rows = [f"{name}\0{digest}".encode() for name, digest in sorted(files.items())]
    return {
        "kind": "directory",
        "sha256": hashlib.sha256(b"\n".join(rows)).hexdigest(),
        "files": files,
    }


def _latest_map(packet):
    _, current = latest_candidates(packet, [])
    return current


def _initial_review_view_version(packet):
    """Select the opt-in prior-work view without changing historical packets."""

    return (
        "1.2.0"
        if packet.get("schema_version") == "2.4.0"
        else REVIEW_VIEW_VERSION_CURRENT
    )


def _prior_work_basis_sha256(packet):
    value = copy.deepcopy(packet)
    value["prior_work_reviews"] = []
    return canonical_hash(value)


def _prior_work_completion(packet, snapshot_sha256):
    """Describe the explicit dossier gate needed before independent review."""

    if packet.get("schema_version") != "2.4.0":
        return None
    current = _latest_map(packet)
    reviews = current_prior_work_reviews(packet)
    missing = sorted(set(current) - set(reviews))
    return {
        "kind": "Stage2PriorWorkCompletion",
        "schema_version": "1.0.0",
        "status": "pending" if missing else "complete",
        "snapshot_sha256": snapshot_sha256,
        "packet_basis_sha256": _prior_work_basis_sha256(packet),
        "candidate_ids": sorted(current),
        "missing_candidate_ids": missing,
    }


def _snapshot_hash(snapshot):
    return snapshot["event"]["payload"]["snapshot_sha256"]


def _portable_input_path(root, relative):
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    if (
        not isinstance(relative, str)
        or not relative
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in relative
        or relative != posix.as_posix()
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        raise Stage2Error(f"controller-input-view-path-invalid: {relative!r}")
    path = root.joinpath(*posix.parts)
    if not path.resolve().is_relative_to(root.resolve()):
        raise Stage2Error(f"controller-input-view-path-escape: {relative}")
    return path


def materialize_snapshot_input_root(snapshot, controller_dir, *, create=True):
    """Build or verify a snapshot-bound combined source and receipt input view."""

    if snapshot["packet"].get("schema_version") != "2.4.0":
        root = Path(snapshot["checker"]["root"]) / "sources"
        validate_packet(snapshot["packet"], root)
        return root

    snapshot_sha256 = _snapshot_hash(snapshot)
    checker = snapshot["checker"]
    checker_root = Path(checker["root"]).resolve()
    manifest = checker["manifest"]
    artifacts = [
        {
            "kind": "source",
            "binding_id": row["source_id"],
            "path": row["original_path"],
            "stored_path": row["stored_path"],
            "sha256": row["sha256"],
        }
        for row in manifest["source_snapshots"]
    ] + [
        {
            "kind": "prior-work-receipt",
            "binding_id": f"{row['candidate_id']}:{row['search_id']}",
            "path": row["original_path"],
            "stored_path": row["stored_path"],
            "sha256": row["sha256"],
        }
        for row in manifest.get("prior_work_receipts", [])
    ]
    view_manifest = {
        "kind": "Stage2ControllerInputView",
        "schema_version": "1.0.0",
        "snapshot_sha256": snapshot_sha256,
        "packet_sha256": canonical_hash(snapshot["packet"]),
        "checker_manifest_sha256": manifest["manifest_sha256"],
        "artifacts": artifacts,
    }
    view_manifest["manifest_sha256"] = canonical_hash(view_manifest)
    root = Path(controller_dir).resolve() / "prior_work_inputs" / snapshot_sha256
    manifest_path = root / "input_manifest.json"

    def verify():
        try:
            saved = json.loads(manifest_path.read_text(encoding="utf-8"))
        except (OSError, ValueError) as error:
            raise Stage2Error("controller-input-view-manifest-invalid") from error
        if saved != view_manifest:
            raise Stage2Error("controller-input-view-manifest-mismatch")
        expected_paths = {row["path"] for row in artifacts}
        actual_paths = {
            path.relative_to(root).as_posix()
            for path in root.rglob("*")
            if path.is_file() and path != manifest_path
        }
        if actual_paths != expected_paths:
            raise Stage2Error("controller-input-view-inventory-mismatch")
        for row in artifacts:
            path = _portable_input_path(root, row["path"])
            if (
                path.is_symlink()
                or hashlib.sha256(path.read_bytes()).hexdigest() != row["sha256"]
            ):
                raise Stage2Error("controller-input-view-artifact-mismatch")
        validate_packet(snapshot["packet"], root)
        return root

    if root.exists():
        return verify()
    if not create:
        raise Stage2Error("controller-input-view-missing")
    root.parent.mkdir(parents=True, exist_ok=True)
    try:
        root.mkdir()
    except FileExistsError:
        return verify()
    try:
        copied = {}
        for row in artifacts:
            source = _portable_input_path(checker_root, row["stored_path"])
            raw = source.read_bytes()
            if hashlib.sha256(raw).hexdigest() != row["sha256"]:
                raise Stage2Error("controller-input-view-source-mismatch")
            previous = copied.get(row["path"])
            if previous is not None and previous != row["sha256"]:
                raise Stage2Error("controller-input-view-path-conflict")
            destination = _portable_input_path(root, row["path"])
            if previous is None:
                destination.parent.mkdir(parents=True, exist_ok=True)
                destination.write_bytes(raw)
                copied[row["path"]] = row["sha256"]
        manifest_path.write_bytes(_json_bytes(view_manifest))
        return verify()
    except Exception:
        shutil.rmtree(root)
        raise


def _validate_spec(spec, packet, snapshot_sha256, *, synthetic):
    if not isinstance(spec, dict):
        raise Stage2Error("controller-spec-must-be-object")
    required = {
        "confirmed_brief_sha256",
        "base_snapshot_sha256",
        "seed",
        "native",
        "preflight",
        "workspaces",
    }
    allowed = {"execution_preflights", "execution_inventories", "followup_policy"}
    role_policy = spec.get("schema_version") == ROLE_POLICY_VERSION
    if "schema_version" in spec and not role_policy:
        raise Stage2Error("controller-spec-version-unsupported")
    if role_policy:
        required |= {
            "schema_version",
            "execution_policies",
            "execution_preflights",
            "execution_inventories",
        }
    extras = set(spec) - required
    if (
        not required.issubset(spec)
        or not extras.issubset(allowed)
        or (("execution_preflights" in extras) != ("execution_inventories" in extras))
    ):
        raise Stage2Error("controller-spec-shape")
    _material_followup_policy(spec.get("followup_policy"))
    if spec["confirmed_brief_sha256"] != canonical_hash(packet["brief"]):
        raise Stage2Error("controller-brief-not-confirmed")
    if spec["base_snapshot_sha256"] != snapshot_sha256:
        raise Stage2Error("controller-base-snapshot-mismatch")
    if not isinstance(spec["seed"], str) or not spec["seed"].strip():
        raise Stage2Error("controller-seed-required")
    native = spec["native"]
    native_keys = {
        "codex",
        "model",
        "reasoning",
        "extraction_policy",
        "config_bindings",
        "policy_bindings",
    }
    if not isinstance(native, dict) or set(native) != native_keys:
        raise Stage2Error("controller-native-settings-shape")
    if native["policy_bindings"] != SUBJECT_EXECUTION_POLICY:
        raise Stage2Error("controller-cannot-relax-subject-policy")
    if not isinstance(native["config_bindings"], dict):
        raise Stage2Error("controller-config-bindings-must-be-object")
    if not isinstance(spec["workspaces"], dict):
        raise Stage2Error("controller-workspaces-must-be-object")
    if role_policy:
        _assert_workspace_isolation(spec)
        policies = spec["execution_policies"]
        expected_keys = {
            environment_key(row["home"], row["workspace"])
            for row in spec["workspaces"].values()
        }
        if (
            not isinstance(policies, dict)
            or not isinstance(spec["execution_preflights"], dict)
            or not isinstance(spec["execution_inventories"], dict)
            or set(policies) != expected_keys
            or set(spec["execution_preflights"]) != expected_keys
        ):
            raise Stage2Error("controller-execution-policy-environments-mismatch")
        for row in spec["workspaces"].values():
            resolved = native_for_environment(spec, row["home"], row["workspace"])
            if not synthetic:
                verify_environment_start(
                    preflight_for_environment(spec, row["home"], row["workspace"]),
                    resolved,
                    row["home"],
                    row["workspace"],
                )
    if synthetic:
        return
    preflight = spec["preflight"]
    if not isinstance(preflight, dict) or set(preflight) != {
        "report",
        "capture_dir",
        "receipt",
        "probe_spec",
        "inventory_receipt",
    }:
        raise Stage2Error("controller-preflight-shape")
    verified = verify_preflight(
        preflight["report"],
        preflight["capture_dir"],
        preflight["receipt"],
        preflight["probe_spec"],
        inventory_receipt=preflight["inventory_receipt"],
    )
    require_matching_preflight_contract(verified, preflight["probe_spec"])
    if verified.get("runtime_gate") is not True or verified.get("status") != "passed":
        raise Stage2Error("controller-preflight-not-ready")
    native = spec["native"]
    actual = verified.get("actual_runtime", {})
    requested = verified.get("requested_runtime", {})
    if any(
        row.get("model") != native["model"]
        or row.get("reasoning") != native["reasoning"]
        for row in (actual, requested)
    ):
        raise Stage2Error("controller-preflight-model-reasoning-mismatch")
    record, _ = verify_capture(preflight["capture_dir"], preflight["receipt"])
    stable = record.get("stable_request_binding", {})
    if role_policy:
        native = native_for_environment(spec, stable["codex_home"], stable["workspace"])
    if (
        stable.get("codex_runtime_sha256") != codex_runtime_sha(native["codex"])
        or stable.get("policy_bindings") != native["policy_bindings"]
    ):
        raise Stage2Error("controller-preflight-runtime-policy-mismatch")
    captured_configs = {
        k: v for k, v in stable.get("config_bindings", {}).items() if k != "probe_shell"
    }
    expected_configs = {
        name: _native_binding_bytes(path)
        for name, path in sorted(native["config_bindings"].items())
    }
    if not isinstance(captured_configs, dict) or set(captured_configs) != set(
        expected_configs
    ):
        raise Stage2Error("controller-preflight-config-binding-mismatch")
    for name, expected in expected_configs.items():
        captured = captured_configs[name]
        if any(captured.get(key) != value for key, value in expected.items()):
            raise Stage2Error("controller-preflight-config-binding-mismatch")


def _settings_binding(spec, adapter):
    if adapter.synthetic:
        settings = {
            "mode": "synthetic-test-only",
            "formal_ready": False,
            "adapter_identity": adapter.identity,
            "declared_native_sha256": canonical_hash(spec["native"]),
            "declared_preflight_sha256": canonical_hash(spec["preflight"]),
        }
        if spec.get("schema_version") == ROLE_POLICY_VERSION:
            settings["execution_policies_sha256"] = canonical_hash(
                spec["execution_policies"]
            )
            settings["workspaces_sha256"] = canonical_hash(spec["workspaces"])
        return settings
    native = spec["native"]
    bindings = {
        "codex": _tree_binding(native["codex"]),
        "configs": {
            name: _tree_binding(path)
            for name, path in sorted(native["config_bindings"].items())
        },
        "policy": copy.deepcopy(native["policy_bindings"]),
        "extraction_policy": copy.deepcopy(native["extraction_policy"]),
        "model": native["model"],
        "reasoning": native["reasoning"],
        "preflight_report_sha256": canonical_hash(spec["preflight"]["report"]),
        "preflight_spec_sha256": canonical_hash(spec["preflight"]["probe_spec"]),
        "preflight_receipt": spec["preflight"]["receipt"],
        "preflight_inventory_receipt_sha256": canonical_hash(
            spec["preflight"]["inventory_receipt"]
        ),
        "execution_preflights_sha256": canonical_hash(
            spec.get("execution_preflights", {})
        ),
        "execution_inventories_sha256": canonical_hash(
            spec.get("execution_inventories", {})
        ),
    }
    if spec.get("schema_version") == ROLE_POLICY_VERSION:
        bindings["execution_policies_sha256"] = canonical_hash(
            spec["execution_policies"]
        )
        bindings["workspaces_sha256"] = canonical_hash(spec["workspaces"])
    return {"mode": "native", "formal_ready": False, "bindings": bindings}


def _artifact_value(state, result):
    row = result["artifacts"].get("summary.json")
    if row is None:
        raise Stage2Error("controller-action-summary-missing")
    path = state["root"] / row["stored_path"]
    if _file_sha(path) != row["sha256"]:
        raise Stage2Error("controller-action-summary-hash-mismatch")
    return json.loads(path.read_text(encoding="utf-8"))


def _execute_unit(
    run_dir,
    controller_dir,
    action_id,
    action_kind,
    inputs,
    settings,
    snapshot_sha256,
    invoke,
):
    state = inspect_workflow(run_dir)
    existing = state["actions"].get(action_id)
    if existing is not None:
        request = existing["request"]
        if (
            request["inputs"] != inputs
            or request["settings"] != settings
            or request["snapshot_sha256"] != snapshot_sha256
        ):
            raise Stage2Error(f"controller-action-binding-changed: {action_id}")
        result = existing["result"]
        if result is None:
            return {"state": "needs-recovery", "action_id": action_id}
        if result["status"] != "complete":
            return {
                "state": "needs-recovery",
                "action_id": action_id,
                "terminal_status": result["status"],
                "error": result["error"],
            }
        return {
            "state": "complete",
            "action_id": action_id,
            "replayed": True,
            "value": _artifact_value(state, result),
        }
    if _snapshot_hash(state["latest_snapshot"]) != snapshot_sha256:
        raise Stage2Error(f"controller-unit-snapshot-not-current: {action_id}")
    summary = Path(controller_dir) / "results" / f"{action_id}.json"
    if summary.exists():
        raise Stage2Error(f"controller-orphan-output-needs-recovery: {summary}")
    started = start_action(
        run_dir,
        action_id,
        action_kind,
        inputs,
        settings,
        state["head_sha256"],
    )
    head = started["event"]["event_sha256"]
    try:
        value = invoke()
        _write_new(summary, value)
        event = finish_action(
            run_dir,
            action_id,
            "complete",
            {"summary.json": {"path": str(summary), "sha256": _file_sha(summary)}},
            value.get("cost") if isinstance(value, dict) else None,
            None,
            head,
        )
        return {
            "state": "complete",
            "action_id": action_id,
            "replayed": False,
            "value": value,
            "head_sha256": event["event_sha256"],
        }
    except (Stage2Error, OSError, RuntimeError, ValueError) as error:
        failure = {"error_type": type(error).__name__, "error": str(error)}
        _write_new(summary, failure)
        finish_action(
            run_dir,
            action_id,
            "failed",
            {"summary.json": {"path": str(summary), "sha256": _file_sha(summary)}},
            None,
            str(error),
            head,
        )
        return {
            "state": "needs-recovery",
            "action_id": action_id,
            "terminal_status": "failed",
            "error": str(error),
        }


def _isolated_paths(spec, key):
    workspaces = spec["workspaces"]
    row = workspaces.get(key)
    if not isinstance(row, dict) or set(row) != {"workspace", "home"}:
        raise Stage2Error(f"controller-workspace-missing: {key}")
    return {name: str(Path(path).resolve()) for name, path in row.items()}


def _allocated_workspace_key(spec, candidate_index, candidate_id, role=None):
    """Resolve an explicit legacy key or a caller-provisioned indexed slot."""

    exact = (
        f"review:{candidate_id}:{role}"
        if role is not None
        else f"resolution:{candidate_id}"
    )
    slot = (
        f"review-slot:{candidate_index}:{role}"
        if role is not None
        else f"resolution-slot:{candidate_index}"
    )
    if exact in spec["workspaces"]:
        return exact
    if slot in spec["workspaces"]:
        return slot
    return None


def _assert_workspace_isolation(spec):
    paths = []
    for key, row in sorted(spec["workspaces"].items()):
        if not isinstance(row, dict) or set(row) != {"workspace", "home"}:
            raise Stage2Error(f"controller-workspace-missing: {key}")
        for kind, value in row.items():
            path = Path(value).resolve()
            for other_key, other_kind, other in paths:
                if path == other or path in other.parents or other in path.parents:
                    raise Stage2Error(
                        "controller-workspace-not-isolated: "
                        f"{key}/{kind} and {other_key}/{other_kind}"
                    )
            paths.append((key, kind, path))


class _ProductionAdapter:
    synthetic = False
    identity = "stage2-native-controller-v1"

    @staticmethod
    def _capture(task, source_root, paths, spec, output, *, binding_key="task"):
        workspace = Path(paths["workspace"])
        home = Path(paths["home"])
        if not workspace.is_dir() or not home.is_dir():
            raise Stage2Error("controller-caller-workspace-home-required")
        preflight = preflight_for_environment(spec, home, workspace)
        native = native_for_environment(spec, home, workspace)
        verify_environment_start(preflight, native, home, workspace)
        policy = native.get("extraction_policy")
        deadline = (
            {"timeout_seconds": _execution_policy(policy)["timeout_seconds"]}
            if policy is not None
            else {}
        )
        if any(path.name != ".git" for path in workspace.iterdir()):
            raise Stage2Error("controller-subject-workspace-must-start-empty")
        task_path = workspace / "input.json"
        _write_new(task_path, task)
        staged_sources = workspace / "sources"
        staged_sources.mkdir()
        source_root = Path(source_root).resolve()
        for source in sorted(source_root.rglob("*"), key=lambda item: item.as_posix()):
            if source.is_symlink():
                raise Stage2Error(f"controller-source-symlink: {source}")
            if source.is_file():
                target = staged_sources / source.relative_to(source_root)
                target.parent.mkdir(parents=True, exist_ok=True)
                shutil.copyfile(source, target)
        capture = capture_native(
            codex=native["codex"],
            codex_home=paths["home"],
            workspace=paths["workspace"],
            prompt=task["prompt"] if "prompt" in task else json.dumps(task),
            model=native["model"],
            reasoning=native["reasoning"],
            input_bindings={binding_key: task_path, "sources": staged_sources},
            config_bindings=native["config_bindings"],
            policy_bindings=native["policy_bindings"],
            output_dir=output,
            **deadline,
        )
        if capture.get("status") != "complete":
            raise Stage2Error(
                "controller-native-capture-incomplete: "
                + str(capture.get("status", "unknown"))
            )
        verify_environment_capture(
            output,
            capture["record_sha256_receipt"],
            preflight,
            spec.get("execution_inventories", {}).get(
                capture["event_summary"]["thread_id"]
            ),
        )
        return capture

    def research(self, context):
        capture = self._capture(
            context["task"],
            context["source_root"],
            context["paths"],
            context["spec"],
            context["output"],
        )
        if capture.get("status") != "complete":
            raise Stage2Error(
                "controller-native-research-incomplete: "
                + str(capture.get("status", "unknown"))
            )
        proposal = choose_captured_proposal(context["output"], capture)
        return {
            "raw_proposal": proposal["text"],
            "proposal_provenance": proposal["provenance"],
            "record_sha256_receipt": capture["record_sha256_receipt"],
            "capture_dir": str(context["output"]),
            "capture_evidence_class": capture["evidence_class"],
            "synthetic": False,
        }

    def extract(self, context):
        native = context["spec"]["native"]
        return run_live_extraction(
            context["raw_proposal"],
            context["packet"],
            context["source_root"],
            context["snapshot_sha256"],
            context["output"],
            native["codex"],
            context["paths"]["home"],
            native["model"],
            native["reasoning"],
            native["extraction_policy"],
        )

    def review(self, context):
        capture_dir = context["output"].with_name(context["output"].name + "-capture")
        capture = self._capture(
            context["view"],
            context["source_root"],
            context["paths"],
            context["spec"],
            capture_dir,
            binding_key="review_view",
        )
        native = context["spec"]["native"]
        return extract_review(
            context["packet"],
            context["source_root"],
            context["candidate_id"],
            context["snapshot_sha256"],
            context["role"],
            capture_dir,
            capture["record_sha256_receipt"],
            codex=native["codex"],
            evaluator_home=context["extractor_home"],
            model=native["model"],
            reasoning=native["reasoning"],
            execution_policy=native["extraction_policy"],
            output_dir=context["output"],
            review_view_version=context["view"]["schema_version"],
        )

    def resolve(self, context):
        capture_dir = context["output"].with_name(context["output"].name + "-capture")
        capture = self._capture(
            context["task"],
            context["source_root"],
            context["paths"],
            context["spec"],
            capture_dir,
            binding_key="reconciliation_task",
        )
        native = context["spec"]["native"]
        return extract_resolution(
            context["packet"],
            context["source_root"],
            context["candidate_id"],
            context["snapshot_sha256"],
            context["reviews"],
            capture_dir,
            capture["record_sha256_receipt"],
            codex=native["codex"],
            evaluator_home=context["extractor_home"],
            model=native["model"],
            reasoning=native["reasoning"],
            execution_policy=native["extraction_policy"],
            output_dir=context["output"],
            review_view_version=context["task"]["schema_version"],
        )


def _material_followup_policy(policy):
    if policy is None:
        return False
    legacy = {
        "kind": "Stage2FollowupPolicy",
        "schema_version": "2.0.0",
        "investigate_material_partial": True,
    }
    research = (
        isinstance(policy, dict)
        and policy.get("kind") == "Stage2FollowupPolicy"
        and policy.get("schema_version") == "3.0.0"
        and policy.get("investigate_material_partial") is True
        and set(policy)
        == {
            "kind",
            "schema_version",
            "investigate_material_partial",
            "research_task_policy",
        }
        and isinstance(policy.get("research_task_policy"), dict)
    )
    if (
        not isinstance(policy, dict)
        or policy.get("investigate_material_partial") is not True
        or (policy != legacy and not research)
    ):
        raise Stage2Error("unsupported-controller-followup-policy")
    if research:
        validate_research_followup_policy(policy["research_task_policy"])
    return True


def _research_followup_policy(policy):
    if isinstance(policy, dict) and policy.get("schema_version") == "3.0.0":
        return policy["research_task_policy"]
    return None


def _followups(reconciliation, policy=None):
    material_partial = _material_followup_policy(policy)
    rows = []
    for candidate in reconciliation["candidates"]:
        resolved = candidate["reconciliation"]
        assessment = resolved.get("assessment")
        if assessment is None:
            continue
        missing = sorted(
            {
                finding["next_check"]
                for finding in assessment["checks"].values()
                if (finding["status"] == "unknown" and finding["blocking"])
                or (
                    material_partial
                    and finding["status"] == "assessed"
                    and finding["score"] in {0, 1}
                    and finding["next_check"]
                    and assessment["disposition"] in {"revise", "park"}
                )
            }
        )
        if (
            material_partial
            and assessment["disposition"] in {"revise", "park"}
            and assessment["next_step"]
        ):
            missing = sorted(set(missing) | {assessment["next_step"]})
        if assessment["scope_change_requested"] or missing:
            rows.append(
                {
                    "candidate_id": candidate["candidate_id"],
                    "candidate_version": candidate["candidate_version"],
                    "missing_evidence": missing,
                    "decision_affected": assessment["reason"],
                    "scope_change_requested": assessment["scope_change_requested"],
                }
            )
    return rows


def run_controller(run_dir, controller_dir, delivery_dir, expected_head, spec):
    """Run or resume the production controller; never records human selection."""

    return _run_controller(
        run_dir,
        controller_dir,
        delivery_dir,
        expected_head,
        spec,
        _ProductionAdapter(),
    )


def _run_controller(
    run_dir, controller_dir, delivery_dir, expected_head, spec, adapter
):
    result = _run_controller_impl(
        run_dir, controller_dir, delivery_dir, expected_head, spec, adapter
    )
    if "delivery_manifest" in result:
        completion = inspect_completion(
            delivery_dir, result["delivery_manifest"]["manifest_sha256"]
        )
        result["completion"] = completion
        result["selection_ready"] = completion["research_delivery_ready"]
        result["stage2_complete"] = completion["stage2_complete"]
    manifest = _persist_controller_manifest(
        run_dir, controller_dir, delivery_dir, spec, adapter, result
    )
    return {
        **result,
        "schema_version": spec.get("schema_version", VERSION),
        "controller_manifest_sha256": manifest["manifest_sha256"],
    }


def _run_controller_impl(
    run_dir, controller_dir, delivery_dir, expected_head, spec, adapter
):
    """Internal deterministic seam. Synthetic adapters can never be formal-ready."""

    if not hasattr(adapter, "synthetic") or not hasattr(adapter, "identity"):
        raise Stage2Error("controller-adapter-contract")
    state = inspect_workflow(run_dir, expected_head=expected_head)
    base = next(
        (
            row
            for row in state["snapshots"]
            if _snapshot_hash(row) == spec.get("base_snapshot_sha256")
        ),
        None,
    )
    if base is None:
        raise Stage2Error("controller-base-snapshot-not-found")
    packet = copy.deepcopy(base["packet"])
    base_hash = _snapshot_hash(base)
    _validate_spec(spec, packet, base_hash, synthetic=adapter.synthetic)
    _assert_workspace_isolation(spec)
    settings = _settings_binding(spec, adapter)
    controller_dir = Path(controller_dir).resolve()
    delivery_dir = Path(delivery_dir).resolve()
    run_root = state["root"]
    protected = [run_root, Path(base["checker"]["root"]).resolve()]
    for row in spec["workspaces"].values():
        protected.extend(Path(value).resolve() for value in row.values())
    outputs = [controller_dir, delivery_dir]
    if controller_dir == delivery_dir or any(
        output == item or output in item.parents or item in output.parents
        for output in outputs
        for item in protected
    ):
        raise Stage2Error("controller-input-output-collision")
    controller_dir.mkdir(parents=True, exist_ok=True)
    source_root = materialize_snapshot_input_root(base, controller_dir)

    task = build_research_task(packet, base_hash)
    research_id = f"ideation-{base_hash[:16]}"
    research = _execute_unit(
        run_dir,
        controller_dir,
        research_id,
        "stage2-ideation-native",
        {"task_sha256": canonical_hash(task)},
        settings,
        base_hash,
        lambda: adapter.research(
            {
                "task": task,
                "packet": packet,
                "source_root": source_root,
                "paths": _isolated_paths(spec, "research"),
                "spec": spec,
                "output": controller_dir / "native" / research_id,
            }
        ),
    )
    if research["state"] != "complete":
        return _terminal(
            "needs-recovery" if research["state"] == "needs-recovery" else "failed",
            state,
            adapter,
            [research],
        )

    raw = research["value"].get("raw_proposal")
    if not isinstance(raw, str):
        raise Stage2Error("controller-research-output-missing")
    extraction_id = f"extraction-{base_hash[:16]}"
    extraction = _execute_unit(
        run_dir,
        controller_dir,
        extraction_id,
        "stage2-ideation-extraction",
        {
            "raw_sha256": hashlib.sha256(raw.encode()).hexdigest(),
            "packet_sha256": canonical_hash(packet),
        },
        settings,
        base_hash,
        lambda: adapter.extract(
            {
                "raw_proposal": raw,
                "packet": packet,
                "source_root": source_root,
                "snapshot_sha256": base_hash,
                "paths": _isolated_paths(spec, "extractor"),
                "spec": spec,
                "output": controller_dir / "native" / extraction_id,
            }
        ),
    )
    if extraction["state"] != "complete":
        return _terminal(
            "needs-recovery" if extraction["state"] == "needs-recovery" else "failed",
            inspect_workflow(run_dir),
            adapter,
            [research, extraction],
        )
    envelope = extraction["value"].get("next_packet")
    next_packet = envelope.get("packet") if isinstance(envelope, dict) else None
    if not isinstance(next_packet, dict):
        raise Stage2Error("controller-extraction-next-packet-missing")
    validate_packet(next_packet, source_root)

    state = inspect_workflow(run_dir)
    matching = [
        row
        for row in state["snapshots"]
        if canonical_hash(row["packet"]) == canonical_hash(next_packet)
    ]
    if next_packet.get("schema_version") == "2.4.0":
        basis_sha256 = _prior_work_basis_sha256(next_packet)
        matching = [
            row
            for row in state["snapshots"]
            if row["packet"].get("schema_version") == "2.4.0"
            and _prior_work_basis_sha256(row["packet"]) == basis_sha256
        ]
    if matching:
        review_snapshot = matching[-1]
    else:
        if _snapshot_hash(state["latest_snapshot"]) != base_hash:
            raise Stage2Error("controller-next-snapshot-conflict")
        packet_path = controller_dir / "packets" / f"{canonical_hash(next_packet)}.json"
        _write_new(packet_path, next_packet)
        impact = {
            candidate_id: {
                "status": "affected",
                "reason": "The ideation snapshot requires a new independent review.",
            }
            for candidate_id in _latest_map(next_packet)
        }
        event = add_snapshot(
            run_dir,
            packet_path,
            source_root,
            "Validated ideation extraction; independent review required.",
            impact,
            state["head_sha256"],
        )
        state = inspect_workflow(run_dir, expected_head=event["event_sha256"])
        review_snapshot = state["latest_snapshot"]
    packet = copy.deepcopy(review_snapshot["packet"])
    snapshot_sha256 = _snapshot_hash(review_snapshot)
    source_root = materialize_snapshot_input_root(review_snapshot, controller_dir)
    current = _latest_map(packet)
    prior_work_completion = _prior_work_completion(packet, snapshot_sha256)
    units = [research, extraction]
    if (
        prior_work_completion is not None
        and prior_work_completion["status"] == "pending"
    ):
        return _terminal(
            "needs-prior-work",
            state,
            adapter,
            units,
            candidate_ids=sorted(current),
            prior_work_completion=prior_work_completion,
        )
    screening = [
        {
            "candidate_id": candidate_id,
            "candidate_version": current[candidate_id]["version"],
            "included": True,
            "distance": 0,
            "reason": "Conservative include-all initial review; no exclusion score inferred.",
        }
        for candidate_id in sorted(current)
    ]
    batch = prepare_review_batch(
        packet,
        snapshot_sha256,
        screening,
        spec["seed"],
        review_view_version=_initial_review_view_version(packet),
    )
    reviews = []
    candidate_indexes = {
        candidate_id: index for index, candidate_id in enumerate(sorted(current))
    }
    allocated = {}
    required_workspace_keys = []
    for assignment in batch["assignments"]:
        candidate_id, role = assignment["candidate_id"], assignment["role"]
        key = _allocated_workspace_key(
            spec, candidate_indexes[candidate_id], candidate_id, role
        )
        if key is None:
            required_workspace_keys.append(
                f"review-slot:{candidate_indexes[candidate_id]}:{role}"
            )
        else:
            allocated[(candidate_id, role)] = key
    for candidate_id in sorted(current):
        key = _allocated_workspace_key(
            spec, candidate_indexes[candidate_id], candidate_id
        )
        if key is None:
            required_workspace_keys.append(
                f"resolution-slot:{candidate_indexes[candidate_id]}"
            )
        else:
            allocated[(candidate_id, None)] = key
    if required_workspace_keys:
        return _terminal(
            "needs-workspace",
            inspect_workflow(run_dir),
            adapter,
            units,
            batch=batch,
            candidate_ids=sorted(current),
            required_workspace_keys=sorted(set(required_workspace_keys)),
        )
    for assignment in batch["assignments"]:
        candidate_id, role = assignment["candidate_id"], assignment["role"]
        action_id = f"review-{snapshot_sha256[:12]}-{candidate_id}-{role}"
        paths = _isolated_paths(spec, allocated[(candidate_id, role)])
        unit = _execute_unit(
            run_dir,
            controller_dir,
            action_id,
            "stage2-independent-review",
            {"view_sha256": assignment["view_sha256"], "role": role},
            settings,
            snapshot_sha256,
            lambda a=assignment, p=paths, aid=action_id: adapter.review(
                {
                    "packet": packet,
                    "source_root": source_root,
                    "candidate_id": a["candidate_id"],
                    "role": a["role"],
                    "view": a["view"],
                    "snapshot_sha256": snapshot_sha256,
                    "paths": p,
                    "extractor_home": _isolated_paths(spec, "extractor")["home"],
                    "spec": spec,
                    "output": controller_dir / "native" / aid,
                }
            ),
        )
        units.append(unit)
        reviews.append(
            {
                "candidate_id": candidate_id,
                "candidate_version": assignment["candidate_version"],
                "role": role,
                "status": "complete" if unit["state"] == "complete" else "failed",
                "review": unit.get("value", {}).get("review")
                if unit["state"] == "complete"
                else None,
                "error": None
                if unit["state"] == "complete"
                else unit.get("error", unit["state"]),
            }
        )
    if any(row["status"] != "complete" for row in reviews):
        reconciliation = reconcile_batch(
            packet,
            batch,
            reviews,
            {
                "candidate_resolutions": [],
                "next_step": "Recover missing independent reviews before reconciliation.",
            },
        )
        return _terminal(
            "blocked",
            inspect_workflow(run_dir),
            adapter,
            units,
            batch=batch,
            reconciliation=reconciliation,
        )

    resolutions = []
    for candidate_id in sorted(current):
        candidate_reviews = [
            row["review"] for row in reviews if row["candidate_id"] == candidate_id
        ]
        task = reconciliation_task(
            packet,
            candidate_id,
            snapshot_sha256,
            candidate_reviews,
            review_view_version=batch["schema_version"],
        )
        action_id = f"resolution-{snapshot_sha256[:12]}-{candidate_id}"
        paths = _isolated_paths(spec, allocated[(candidate_id, None)])
        unit = _execute_unit(
            run_dir,
            controller_dir,
            action_id,
            "stage2-review-reconciliation",
            {"task_sha256": canonical_hash(task)},
            settings,
            snapshot_sha256,
            lambda cid=candidate_id, rs=candidate_reviews, t=task, p=paths, aid=action_id: (
                adapter.resolve(
                    {
                        "packet": packet,
                        "source_root": source_root,
                        "candidate_id": cid,
                        "reviews": rs,
                        "task": t,
                        "snapshot_sha256": snapshot_sha256,
                        "paths": p,
                        "extractor_home": _isolated_paths(spec, "extractor")["home"],
                        "spec": spec,
                        "output": controller_dir / "native" / aid,
                    }
                )
            ),
        )
        units.append(unit)
        if unit["state"] != "complete":
            return _terminal(
                "blocked", inspect_workflow(run_dir), adapter, units, batch=batch
            )
        resolutions.append(
            {"candidate_id": candidate_id, "resolution": unit["value"]["resolution"]}
        )
    resolution_input = {
        "candidate_resolutions": resolutions,
        "next_step": "Review unresolved evidence and scope before selecting if no candidate is eligible.",
    }
    reconciliation = reconcile_batch(packet, batch, reviews, resolution_input)
    followups = _followups(reconciliation, spec.get("followup_policy"))
    if followups:
        research_policy = _research_followup_policy(spec.get("followup_policy"))
        research_task = (
            build_research_followup_task(
                packet,
                snapshot_sha256,
                followups,
                research_policy,
            )
            if research_policy is not None
            else None
        )
        return _terminal(
            "follow-up-needed",
            inspect_workflow(run_dir),
            adapter,
            units,
            batch=batch,
            reconciliation=reconciliation,
            followups=followups,
            research_followup_task=research_task,
        )

    state = inspect_workflow(run_dir)
    if delivery_dir.exists():
        manifest_path = delivery_dir / "delivery_manifest.json"
        if not manifest_path.is_file():
            raise Stage2Error("controller-delivery-partial-needs-recovery")
        submitted = json.loads(manifest_path.read_text(encoding="utf-8"))
        manifest = inspect_delivery(delivery_dir, submitted.get("manifest_sha256"))[
            "manifest"
        ]
        if (
            manifest["workflow_head_sha256"] != state["head_sha256"]
            or manifest["snapshot_sha256"] != snapshot_sha256
            or manifest["batch_sha256"] != batch["batch_sha256"]
        ):
            raise Stage2Error("controller-delivery-binding-changed")
    else:
        manifest = build_delivery(
            run_dir,
            batch,
            reviews,
            resolution_input,
            delivery_dir,
            state["head_sha256"],
        )
    return _terminal(
        "awaiting-human",
        inspect_workflow(run_dir),
        adapter,
        units,
        batch=batch,
        reconciliation=reconciliation,
        delivery_manifest=manifest,
    )


def _terminal(status, state, adapter, units, **extra):
    next_steps = {
        "follow-up-needed": "Complete the bound follow-up, save a new snapshot, and recheck affected directions.",
        "needs-prior-work": "Complete source-bound precedent positioning before independent review.",
        "needs-workspace": "Prepare and verify the missing role environments before further calls.",
        "needs-recovery": "Recover the recorded incomplete unit; do not rerun completed units.",
        "failed": "Inspect the retained failed unit and repair its cause before a retry.",
        "blocked": "Resolve missing or failed independent checks before preparing a final package.",
        "awaiting-human": "Inspect content completeness and independent assessment before treating this as a final package.",
    }
    return {
        "kind": "Stage2ControllerResult",
        "schema_version": VERSION,
        "status": status,
        "workflow_head_sha256": state["head_sha256"],
        "synthetic_test_only": bool(adapter.synthetic),
        "formal_ready": False,
        "selection_ready": False,
        "stage2_complete": False,
        "pilot_executable": False,
        "human_selection": "pending",
        "stage3_execution_authorized": False,
        "next_step": next_steps.get(status, "Inspect the retained workflow state."),
        "units": copy.deepcopy(units),
        **copy.deepcopy(extra),
    }


def _persist_controller_manifest(
    run_dir, controller_dir, delivery_dir, spec, adapter, result
):
    state = inspect_workflow(run_dir, expected_head=result["workflow_head_sha256"])
    action_ids = sorted(unit["action_id"] for unit in result["units"])
    summaries = []
    for action_id in action_ids:
        action = state["actions"].get(action_id)
        if action is None or action["result"] is None:
            status = "incomplete"
            summary_sha256 = None
        else:
            status = action["result"]["status"]
            row = action["result"]["artifacts"].get("summary.json")
            summary_sha256 = None if row is None else row["sha256"]
        summaries.append(
            {
                "action_id": action_id,
                "status": status,
                "summary_sha256": summary_sha256,
            }
        )
    delivery_receipt = None
    if "delivery_manifest" in result:
        delivery_receipt = result["delivery_manifest"]["manifest_sha256"]
    controller_root = Path(controller_dir).resolve()
    spec_sha256 = canonical_hash(spec)
    spec_relative = f"controller_specs/{spec_sha256}.json"
    spec_path = controller_root / spec_relative
    if spec_path.exists():
        if json.loads(spec_path.read_text(encoding="utf-8")) != spec:
            raise Stage2Error("controller-saved-spec-binding-changed")
    else:
        _write_new(spec_path, spec)
    legacy_spec = controller_root / "controller_spec.json"
    if not legacy_spec.exists():
        _write_new(legacy_spec, spec)
    manifest = {
        "kind": "Stage2ControllerManifest",
        "schema_version": spec.get("schema_version", VERSION),
        "status": result["status"],
        "workflow_root": str(Path(run_dir).resolve()),
        "workflow_head_sha256": result["workflow_head_sha256"],
        "controller_spec_path": spec_relative,
        "controller_spec_sha256": spec_sha256,
        "controller_code_sha256": _file_sha(__file__),
        "adapter_mode": "synthetic-test-only" if adapter.synthetic else "native",
        "synthetic_test_only": bool(adapter.synthetic),
        "action_summaries": summaries,
        "delivery_root": str(Path(delivery_dir).resolve()),
        "delivery_manifest_sha256": delivery_receipt,
        "human_selection": "pending",
        "stage3_execution_authorized": False,
    }
    if "prior_work_completion" in result:
        manifest["prior_work_completion"] = copy.deepcopy(
            result["prior_work_completion"]
        )
    if "completion" in result:
        manifest["completion"] = copy.deepcopy(result["completion"])
    manifest["manifest_sha256"] = canonical_hash(manifest)
    versioned = (
        controller_root
        / "controller_manifests"
        / (manifest["manifest_sha256"] + ".json")
    )
    if versioned.exists():
        if json.loads(versioned.read_text(encoding="utf-8")) != manifest:
            raise Stage2Error("controller-manifest-binding-changed")
    else:
        _write_new(versioned, manifest)
    path = controller_root / "controller_manifest.json"
    if not path.exists():
        _write_new(path, manifest)
    return manifest


def _require_saved_unit(output, label, result_name, receipt):
    """Prevent a resume validator from creating a missing unit or result."""
    if not isinstance(receipt, dict) or set(receipt) != {
        "result_sha256",
        "unit_receipts",
    }:
        raise Stage2Error("controller-read-only-receipt-missing")
    if set(receipt["unit_receipts"]) != {label}:
        raise Stage2Error("controller-read-only-unit-set-mismatch")
    expected = {
        result_name: receipt["result_sha256"],
        f"{label}.unit.json": receipt["unit_receipts"][label],
    }
    for name, digest in expected.items():
        path = output / name
        if not path.is_file() or path.is_symlink() or _file_sha(path) != digest:
            raise Stage2Error("controller-read-only-artifact-missing-or-changed")
    for name in (f"{label}.schema.json", f"{label}.model-call/request.json"):
        path = output / name
        if not path.is_file() or path.is_symlink():
            raise Stage2Error("controller-read-only-call-missing")


def _saved_resolution_unit_label(value):
    label = value.get(
        "extraction_unit_label", review_models.LEGACY_RESOLUTION_EXTRACTION_LABEL
    )
    if (
        not isinstance(label, str)
        or label not in review_models.RESOLUTION_EXTRACTION_LABELS
    ):
        raise Stage2Error("controller-resolution-unit-label-invalid")
    try:
        unit_receipts = value["replay_receipt"]["unit_receipts"]
    except (KeyError, TypeError) as error:
        raise Stage2Error("controller-resolution-unit-label-receipt-missing") from error
    if not isinstance(unit_receipts, dict):
        raise Stage2Error("controller-resolution-unit-label-receipt-missing")
    receipt_labels = set(unit_receipts)
    if receipt_labels != {label}:
        raise Stage2Error("controller-resolution-unit-label-receipt-mismatch")
    return label


def _replay_model_config(extraction_request):
    """Reconstruct the exact native model-call config frozen in its archive."""

    try:
        runtime_sha256 = extraction_request.get("codex_executable_sha256")
        if runtime_sha256 is None:
            runtime_sha256 = extraction_request["codex_runtime_sha256"]
        return {
            "codex": extraction_request["codex"],
            "codex_executable_sha256": runtime_sha256,
            "evaluator_home": extraction_request["evaluator_home"],
            "model": extraction_request["model"],
            "reasoning": extraction_request["reasoning"],
        }
    except (KeyError, TypeError) as error:
        raise Stage2Error("controller-extraction-request-config-missing") from error


def _review_replay_schema(packet):
    return review_models._object(
        {
            "assessment": review_models._schema(packet),
            "assumptions": {"type": "array", "items": review_models._text()},
            "strongest_alternative": review_models._text(),
            "change_conditions": {"type": "array", "items": review_models._text()},
        }
    )


def _resolution_replay_schema(packet):
    return review_models._object(
        {
            "assessment": review_models._schema(packet),
            "method": {
                "type": "string",
                "enum": ["source-verification", "evidence-debate", "synthesis"],
            },
            "reason": review_models._text(),
            "evidence_ids": {"type": "array", "items": review_models._text()},
            "addressed": {"type": "array", "items": review_models._text()},
            "substantive_disagreements": {
                "type": "array",
                "items": review_models._text(),
            },
            "changed_judgment_reason": {"type": ["string", "null"]},
        }
    )


def _verify_referenced_environment(spec, capture_dir, receipt, expected_paths=None):
    """Verify the capture actually referenced by an authenticated action.

    Archives may reside outside the controller directory. Never infer coverage
    from a directory scan or replace the retained receipt with a fresh hash.
    """
    record, _ = verify_capture(capture_dir, receipt)
    stable = record["stable_request_binding"]
    own_preflight = preflight_for_environment(
        spec, stable["codex_home"], stable["workspace"]
    )
    if spec.get("schema_version") == ROLE_POLICY_VERSION:
        if expected_paths is None or any(
            stable.get(field) != expected_paths[name]
            for field, name in (("codex_home", "home"), ("workspace", "workspace"))
        ):
            raise Stage2Error("controller-capture-role-allocation-mismatch")
        resolved = native_for_environment(
            spec, stable["codex_home"], stable["workspace"]
        )
        if stable["policy_bindings"] != resolved["policy_bindings"]:
            raise Stage2Error("controller-replayed-role-policy-mismatch")
    return verify_environment_capture(
        capture_dir,
        receipt,
        own_preflight,
        spec.get("execution_inventories", {}).get(record["event_summary"]["thread_id"]),
    )


def _verify_action_environments(spec, state, values):
    """Cover every retained native action, including captures outside the bundle."""
    for action_id, value in values.items():
        request = state["actions"][action_id]["request"]
        kind = request["action_kind"]
        if kind == "stage2-ideation-native":
            capture_dir, receipt = value["capture_dir"], value["record_sha256_receipt"]
        elif kind == "stage2-independent-review":
            capture_dir = (
                Path(value["review"]["native_artifact"]["path"]).resolve().parent
            )
            receipt = value["native_receipt"]
        elif kind == "stage2-review-reconciliation":
            capture_dir = Path(value["native_artifact"]["path"]).resolve().parent
            receipt = value["native_receipt"]
        elif kind == "stage2-ideation-extraction":
            # The tool-free extractor has its own model-call archive replay.
            continue
        else:
            raise Stage2Error(f"controller-unrecognized-capture-action: {kind}")
        expected_paths = None
        if spec.get("schema_version") == ROLE_POLICY_VERSION:
            if kind == "stage2-ideation-native":
                key = "research"
            else:
                review = (
                    value["review"]
                    if kind == "stage2-independent-review"
                    else value["resolution"]["assessment"]
                )
                candidate_id = review["candidate_id"]
                role = (
                    review.get("role") if kind == "stage2-independent-review" else None
                )
                if (
                    kind == "stage2-independent-review"
                    and role != request["inputs"]["role"]
                ):
                    raise Stage2Error("controller-capture-review-role-mismatch")
                snapshot = next(
                    (
                        row
                        for row in state["snapshots"]
                        if _snapshot_hash(row) == request["snapshot_sha256"]
                    ),
                    None,
                )
                candidates = (
                    sorted(_latest_map(snapshot["packet"]))
                    if snapshot is not None
                    else []
                )
                if candidate_id not in candidates:
                    raise Stage2Error("controller-capture-role-candidate-mismatch")
                key = _allocated_workspace_key(
                    spec, candidates.index(candidate_id), candidate_id, role
                )
            expected_paths = _isolated_paths(spec, key)
        _verify_referenced_environment(spec, capture_dir, receipt, expected_paths)


def _verify_saved_review(output, value, packet, snapshot_sha256, config, policy):
    review = value["review"]
    capture_dir = Path(review["native_artifact"]["path"]).resolve().parent
    review_view_version = review_models._review_view_version(
        packet,
        review["candidate_id"],
        snapshot_sha256,
        review["role"],
        review["view_sha256"],
    )
    view = review_models.review_task(
        packet,
        review["candidate_id"],
        snapshot_sha256,
        review["role"],
        review_view_version=review_view_version,
    )
    record, raw = review_models._captured_input(
        capture_dir, value["native_receipt"], view, "review_view"
    )
    prompt = review_models._review_prompt(view, raw)
    event_id = (
        "review-"
        + canonical_hash(
            [
                review["candidate_id"],
                snapshot_sha256,
                review["role"],
                value["native_receipt"],
            ]
        )[:24]
    )

    def normalize(payload):
        normalized = {
            "role": review["role"],
            "view_sha256": canonical_hash(view),
            "snapshot_sha256": snapshot_sha256,
            "candidate_id": review["candidate_id"],
            "candidate_version": view["candidate"]["version"],
            "assessment": review_models._assessment(
                payload["assessment"], packet, review["candidate_id"], event_id
            ),
            "session_id": record["event_summary"]["thread_id"],
            "native_artifact": {
                "path": str(capture_dir / "stdout.jsonl"),
                "sha256": _file_sha(capture_dir / "stdout.jsonl"),
            },
            "initial": True,
            "assumptions": payload["assumptions"],
            "strongest_alternative": payload["strongest_alternative"],
            "change_conditions": payload["change_conditions"],
        }
        review_models.validate_review(normalized, view, packet)
        return normalized

    replayed = replay_unit(
        output,
        "initial-review",
        value["replay_receipt"]["unit_receipts"]["initial-review"],
        prompt=prompt,
        schema=_review_replay_schema(packet),
        config=config,
        policy=policy,
        validate=normalize,
    )
    if normalize(replayed["value"]) != review or replayed["provenance"] != value.get(
        "extraction_provenance"
    ):
        raise Stage2Error("controller-review-model-replay-mismatch")


def _verify_saved_resolution(
    output, value, packet, snapshot_sha256, reviews, unit_label, config, policy
):
    resolution = value["resolution"]
    candidate_id = resolution["assessment"]["candidate_id"]
    review_view_version = review_models._common_review_view_version(
        packet, candidate_id, snapshot_sha256, reviews
    )
    task = reconciliation_task(
        packet,
        candidate_id,
        snapshot_sha256,
        reviews,
        review_view_version=review_view_version,
    )
    capture_dir = Path(value["native_artifact"]["path"]).resolve().parent
    record, raw = review_models._captured_input(
        capture_dir,
        value["native_receipt"],
        task,
        "reconciliation_task",
    )
    prompt = review_models._resolution_prompt(task, raw)
    event_id = (
        "resolution-"
        + canonical_hash([candidate_id, snapshot_sha256, value["native_receipt"]])[:24]
    )

    def normalize(payload):
        normalized = {
            **copy.deepcopy(payload),
            "review_sha256s": [canonical_hash(row) for row in reviews],
        }
        normalized["assessment"] = review_models._assessment(
            payload["assessment"], packet, candidate_id, event_id
        )
        review_models.reconcile_reviews(
            packet,
            candidate_id,
            snapshot_sha256,
            reviews,
            normalized,
            review_view_version=review_view_version,
        )
        return normalized

    replayed = replay_unit(
        output,
        unit_label,
        value["replay_receipt"]["unit_receipts"][unit_label],
        prompt=prompt,
        schema=_resolution_replay_schema(packet),
        config=config,
        policy=policy,
        validate=normalize,
    )
    if (
        normalize(replayed["value"]) != resolution
        or replayed["provenance"] != value.get("extraction_provenance")
        or value.get("native_session_id") != record["event_summary"]["thread_id"]
    ):
        raise Stage2Error("controller-resolution-model-replay-mismatch")


def verify_controller(
    output_dir,
    externally_retained_receipt,
    *,
    evaluation_dir=None,
    expected_evaluation_manifest_sha256=None,
):
    """Recompute a saved controller run and return its formal-admission facts."""

    root = Path(output_dir).resolve()
    if (
        not isinstance(externally_retained_receipt, str)
        or len(externally_retained_receipt) != 64
        or any(char not in "0123456789abcdef" for char in externally_retained_receipt)
    ):
        raise Stage2Error("controller-manifest-invalid")
    versioned = root / "controller_manifests" / (externally_retained_receipt + ".json")
    path = versioned if versioned.is_file() else root / "controller_manifest.json"
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as error:
        raise Stage2Error(f"controller-manifest-read-failed: {error}") from error
    required = {
        "kind",
        "schema_version",
        "status",
        "workflow_root",
        "workflow_head_sha256",
        "controller_spec_path",
        "controller_spec_sha256",
        "controller_code_sha256",
        "adapter_mode",
        "synthetic_test_only",
        "action_summaries",
        "delivery_root",
        "delivery_manifest_sha256",
        "human_selection",
        "stage3_execution_authorized",
        "manifest_sha256",
    }
    allowed = (
        required,
        required | {"prior_work_completion"},
        required | {"completion"},
        required | {"prior_work_completion", "completion"},
    )
    if (
        not isinstance(manifest, dict)
        or set(manifest) not in allowed
        or manifest["kind"] != "Stage2ControllerManifest"
        or manifest["schema_version"] not in {VERSION, ROLE_POLICY_VERSION}
        or manifest["manifest_sha256"]
        != canonical_hash(
            {key: value for key, value in manifest.items() if key != "manifest_sha256"}
        )
        or externally_retained_receipt != manifest["manifest_sha256"]
        or manifest["controller_code_sha256"] != _file_sha(__file__)
        or manifest["human_selection"] != "pending"
        or manifest["stage3_execution_authorized"] is not False
    ):
        raise Stage2Error("controller-manifest-invalid")
    if "prior_work_completion" in manifest:
        completion = manifest["prior_work_completion"]
        keys = {
            "kind",
            "schema_version",
            "status",
            "snapshot_sha256",
            "packet_basis_sha256",
            "candidate_ids",
            "missing_candidate_ids",
        }
        if (
            manifest["status"] != "needs-prior-work"
            or not isinstance(completion, dict)
            or set(completion) != keys
            or completion["kind"] != "Stage2PriorWorkCompletion"
            or completion["schema_version"] != "1.0.0"
            or completion["status"] != "pending"
            or not completion["missing_candidate_ids"]
            or not isinstance(completion["candidate_ids"], list)
            or not isinstance(completion["missing_candidate_ids"], list)
            or any(
                not isinstance(candidate_id, str) or not candidate_id
                for candidate_id in [
                    *completion["candidate_ids"],
                    *completion["missing_candidate_ids"],
                ]
            )
            or completion["candidate_ids"] != sorted(set(completion["candidate_ids"]))
            or completion["missing_candidate_ids"]
            != sorted(set(completion["missing_candidate_ids"]))
            or not set(completion["missing_candidate_ids"]).issubset(
                completion["candidate_ids"]
            )
        ):
            raise Stage2Error("controller-prior-work-completion-invalid")
        for label in ("snapshot_sha256", "packet_basis_sha256"):
            digest = completion[label]
            if (
                not isinstance(digest, str)
                or len(digest) != 64
                or any(char not in "0123456789abcdef" for char in digest)
            ):
                raise Stage2Error("controller-prior-work-completion-invalid")
    state = inspect_workflow(manifest["workflow_root"])
    if "prior_work_completion" in manifest:
        completion = manifest["prior_work_completion"]
        snapshot = next(
            (
                row
                for row in state["snapshots"]
                if _snapshot_hash(row) == completion["snapshot_sha256"]
            ),
            None,
        )
        if (
            snapshot is None
            or _prior_work_completion(snapshot["packet"], completion["snapshot_sha256"])
            != completion
        ):
            raise Stage2Error("controller-prior-work-completion-binding-mismatch")
        materialize_snapshot_input_root(snapshot, root, create=False)
    historical_head = manifest["workflow_head_sha256"]
    if historical_head != state["head_sha256"] and historical_head not in {
        row["event_sha256"] for row in state["events"]
    }:
        raise Stage2Error("controller-workflow-head-not-retained")
    spec_path = (root / manifest["controller_spec_path"]).resolve()
    try:
        spec_path.relative_to(root)
    except ValueError as error:
        raise Stage2Error("controller-saved-spec-path-invalid") from error
    if spec_path.is_symlink() or not spec_path.is_file():
        raise Stage2Error("controller-saved-spec-path-invalid")
    spec = json.loads(spec_path.read_text(encoding="utf-8"))
    if canonical_hash(spec) != manifest["controller_spec_sha256"]:
        raise Stage2Error("controller-saved-spec-hash-mismatch")
    if manifest["schema_version"] != spec.get("schema_version", VERSION):
        raise Stage2Error("controller-saved-spec-version-mismatch")
    base = next(
        (
            row
            for row in state["snapshots"]
            if _snapshot_hash(row) == spec.get("base_snapshot_sha256")
        ),
        None,
    )
    if base is None:
        raise Stage2Error("controller-saved-spec-snapshot-missing")
    _validate_spec(
        spec,
        base["packet"],
        _snapshot_hash(base),
        synthetic=manifest["synthetic_test_only"],
    )
    declared_base_hash = _snapshot_hash(base)
    action_ids = [row.get("action_id") for row in manifest["action_summaries"]]
    if len(action_ids) != len(set(action_ids)):
        raise Stage2Error("controller-action-summary-duplicate")
    modes = set()
    values = {}
    expected_rows = []
    for row in manifest["action_summaries"]:
        action_id = row.get("action_id")
        action = state["actions"].get(action_id)
        if action is None:
            raise Stage2Error(f"controller-action-missing: {action_id}")
        modes.add(action["request"]["settings"].get("mode"))
        result = action["result"]
        actual_status = "incomplete" if result is None else result["status"]
        summary_sha256 = None
        if result is not None:
            artifact = result["artifacts"].get("summary.json")
            summary_sha256 = None if artifact is None else artifact["sha256"]
        expected_rows.append(
            {
                "action_id": action_id,
                "status": actual_status,
                "summary_sha256": summary_sha256,
            }
        )
        if result is not None and result["status"] == "complete":
            values[action_id] = _artifact_value(state, result)
    if expected_rows != manifest["action_summaries"]:
        raise Stage2Error("controller-action-summary-binding-mismatch")
    authentic = modes == {"native"} and manifest["adapter_mode"] == "native"
    synthetic = (
        modes == {"synthetic-test-only"}
        and manifest["adapter_mode"] == "synthetic-test-only"
        and manifest["synthetic_test_only"] is True
    )
    if not (authentic or synthetic):
        raise Stage2Error("controller-action-mode-mismatch")

    model_call_verification = "synthetic-not-authenticatable"
    model_call_blockers = []
    if authentic:
        _verify_action_environments(spec, state, values)
        research_actions = [
            (action_id, state["actions"][action_id])
            for action_id in values
            if state["actions"][action_id]["request"]["action_kind"]
            == "stage2-ideation-native"
        ]
        extraction_actions = [
            (action_id, state["actions"][action_id])
            for action_id in values
            if state["actions"][action_id]["request"]["action_kind"]
            == "stage2-ideation-extraction"
        ]
        if len(research_actions) != 1 or len(extraction_actions) != 1:
            raise Stage2Error("controller-ideation-action-set-invalid")
        research_id, _ = research_actions[0]
        research = values[research_id]
        extraction_id, extraction_action = extraction_actions[0]
        extraction = values[extraction_id]
        base_hash = extraction_action["request"]["snapshot_sha256"]
        extraction_base = next(
            (row for row in state["snapshots"] if _snapshot_hash(row) == base_hash),
            None,
        )
        if extraction_base is None or base_hash != declared_base_hash:
            raise Stage2Error("controller-extraction-base-snapshot-missing")
        rebuilt = build_next_packet(
            extraction_base["packet"],
            materialize_snapshot_input_root(extraction_base, root, create=False),
            research["raw_proposal"],
            extraction["extraction"],
            base_hash,
        )
        if rebuilt != extraction["next_packet"]:
            raise Stage2Error("controller-extraction-reconstruction-mismatch")
        extraction_output = root / "native" / extraction_id
        _require_saved_unit(
            extraction_output, "extraction", "result.json", extraction["replay_receipt"]
        )
        extraction_request = json.loads(
            (extraction_output / "request.json").read_text(encoding="utf-8")
        )
        model_config = _replay_model_config(extraction_request)
        replayed_extraction = verify_extraction(
            extraction_output,
            extraction["replay_receipt"],
            raw_proposal=research["raw_proposal"],
            packet=extraction_base["packet"],
            source_root=materialize_snapshot_input_root(
                extraction_base, root, create=False
            ),
            snapshot_sha256=base_hash,
            expected_config=model_config,
            expected_policy=extraction_request["execution_policy"],
        )
        if replayed_extraction["result"] != extraction:
            raise Stage2Error("controller-extraction-model-replay-mismatch")
        review_values = {}
        for action_id, value in values.items():
            action = state["actions"][action_id]
            kind = action["request"]["action_kind"]
            snapshot_hash = action["request"]["snapshot_sha256"]
            snapshot = next(
                (
                    row
                    for row in state["snapshots"]
                    if _snapshot_hash(row) == snapshot_hash
                ),
                None,
            )
            if snapshot is None:
                raise Stage2Error("controller-model-call-snapshot-missing")
            if kind == "stage2-independent-review":
                _require_saved_unit(
                    root / "native" / action_id,
                    "initial-review",
                    "review.json",
                    value["replay_receipt"],
                )
                review = value["review"]
                _verify_saved_review(
                    root / "native" / action_id,
                    value,
                    snapshot["packet"],
                    snapshot_hash,
                    model_config,
                    extraction_request["execution_policy"],
                )
                review_values.setdefault(review["candidate_id"], []).append(review)
        for action_id, value in values.items():
            action = state["actions"][action_id]
            if action["request"]["action_kind"] != "stage2-review-reconciliation":
                continue
            snapshot_hash = action["request"]["snapshot_sha256"]
            snapshot = next(
                row
                for row in state["snapshots"]
                if _snapshot_hash(row) == snapshot_hash
            )
            resolution = value["resolution"]
            candidate_id = resolution["assessment"]["candidate_id"]
            reviews = review_values.get(candidate_id, [])
            if len(reviews) != len(ROLES):
                model_call_blockers.append(
                    f"resolution-review-set-incomplete:{candidate_id}"
                )
                continue
            unit_label = _saved_resolution_unit_label(value)
            _require_saved_unit(
                root / "native" / action_id,
                unit_label,
                "resolution.json",
                value["replay_receipt"],
            )
            _verify_saved_resolution(
                root / "native" / action_id,
                value,
                snapshot["packet"],
                snapshot_hash,
                reviews,
                unit_label,
                model_config,
                extraction_request["execution_policy"],
            )
        incomplete = [
            row["action_id"]
            for row in manifest["action_summaries"]
            if row["status"] != "complete"
        ]
        model_call_blockers.extend(
            f"unit-not-complete:{action_id}" for action_id in incomplete
        )
        model_call_verification = (
            "authenticated" if not model_call_blockers else "incomplete"
        )

    delivery = None
    if manifest["delivery_manifest_sha256"] is not None:
        delivery = inspect_delivery(
            manifest["delivery_root"], manifest["delivery_manifest_sha256"]
        )
        if delivery["manifest"]["workflow_head_sha256"] != historical_head:
            raise Stage2Error("controller-delivery-workflow-head-mismatch")
    elif manifest["status"] == "awaiting-human":
        raise Stage2Error("controller-ready-status-requires-delivery")
    completion = None
    if delivery is not None:
        snapshot_hash = delivery["manifest"]["snapshot_sha256"]
        snapshot = next(
            row for row in state["snapshots"] if _snapshot_hash(row) == snapshot_hash
        )
        required_actions = {
            f"ideation-{declared_base_hash[:16]}": (
                "stage2-ideation-native",
                declared_base_hash,
            ),
            f"extraction-{declared_base_hash[:16]}": (
                "stage2-ideation-extraction",
                declared_base_hash,
            ),
        }
        for candidate_id in _latest_map(snapshot["packet"]):
            for role in ROLES:
                required_actions[
                    f"review-{snapshot_hash[:12]}-{candidate_id}-{role}"
                ] = ("stage2-independent-review", snapshot_hash)
            required_actions[f"resolution-{snapshot_hash[:12]}-{candidate_id}"] = (
                "stage2-review-reconciliation",
                snapshot_hash,
            )
        if set(values) != set(required_actions):
            raise Stage2Error("controller-required-action-set-incomplete")
        for action_id, (kind, bound_snapshot) in required_actions.items():
            request = state["actions"][action_id]["request"]
            if (
                request["action_kind"] != kind
                or request["snapshot_sha256"] != bound_snapshot
            ):
                raise Stage2Error("controller-required-action-binding-mismatch")
        review_inputs = delivery["manifest"]["review_input_files"]
        delivery_root = delivery["root"]
        saved_reviews = json.loads(
            (delivery_root / review_inputs["reviews"]).read_text(encoding="utf-8")
        )
        for row in saved_reviews:
            action_id = (
                f"review-{snapshot_hash[:12]}-{row['candidate_id']}-{row['role']}"
            )
            if row["review"] != values[action_id]["review"]:
                raise Stage2Error("controller-delivery-review-binding-mismatch")
        saved_resolutions = json.loads(
            (delivery_root / review_inputs["resolutions"]).read_text(encoding="utf-8")
        )
        for row in saved_resolutions["candidate_resolutions"]:
            action_id = f"resolution-{snapshot_hash[:12]}-{row['candidate_id']}"
            if row["resolution"] != values[action_id]["resolution"]:
                raise Stage2Error("controller-delivery-resolution-binding-mismatch")
        recorded = inspect_completion(
            manifest["delivery_root"], manifest["delivery_manifest_sha256"]
        )
        if "completion" in manifest and manifest["completion"] != recorded:
            raise Stage2Error("controller-completion-reconstruction-mismatch")
        completion = (
            inspect_completion(
                manifest["delivery_root"],
                manifest["delivery_manifest_sha256"],
                evaluation_dir=evaluation_dir,
                expected_evaluation_manifest_sha256=expected_evaluation_manifest_sha256,
            )
            if evaluation_dir is not None
            or expected_evaluation_manifest_sha256 is not None
            else recorded
        )
    elif evaluation_dir is not None or expected_evaluation_manifest_sha256 is not None:
        raise Stage2Error("controller-assessment-requires-delivery")
    selection_ready = bool(completion and completion["research_delivery_ready"])
    stage2_complete = bool(completion and completion["stage2_complete"])
    pilot_executable = bool(
        authentic
        and manifest["status"] == "awaiting-human"
        and selection_ready
        and stage2_complete
        and model_call_verification == "authenticated"
    )
    return {
        "kind": "Stage2ControllerVerification",
        "schema_version": VERSION,
        "manifest": manifest,
        "workflow": state,
        "delivery": delivery,
        "authentic_native_execution": authentic,
        "synthetic_test_only": synthetic,
        "selection_ready": selection_ready,
        "stage2_complete": stage2_complete,
        "completion": completion,
        "model_call_verification": model_call_verification,
        "model_call_blockers": model_call_blockers,
        "pilot_executable": pilot_executable,
        "formal_ready": False,
        "formal_readiness_blocker": (
            "A separate four-gate manifest, calibration, two authentic pilots, "
            "and a frozen plan are required."
        ),
        "human_selection": "pending",
        "stage3_execution_authorized": False,
    }


def apply_revision(run_dir, packet_path, source_root, impact, reason, expected_head):
    """Add an externally validated append-only packet and require fresh reviews."""

    state = inspect_workflow(run_dir, expected_head=expected_head)
    packet = json.loads(Path(packet_path).read_text(encoding="utf-8"))
    validate_packet(packet, source_root)
    before = _latest_map(state["latest_snapshot"]["packet"])
    after = _latest_map(packet)
    revised = {
        candidate_id
        for candidate_id, candidate in after.items()
        if candidate_id not in before
        or candidate["version"] != before[candidate_id]["version"]
    }
    if not revised:
        raise Stage2Error("controller-revision-requires-new-candidate-version")
    normalized = impact if isinstance(impact, dict) else {}
    for candidate_id in revised:
        row = normalized.get(candidate_id)
        if not isinstance(row, dict) or row.get("status") != "affected":
            raise Stage2Error(
                f"controller-revised-candidate-must-be-affected: {candidate_id}"
            )
    event = add_snapshot(
        run_dir,
        packet_path,
        source_root,
        reason,
        impact,
        expected_head,
    )
    return {
        "kind": "Stage2ControllerRevision",
        "schema_version": VERSION,
        "snapshot_sha256": event["payload"]["snapshot_sha256"],
        "workflow_head_sha256": event["event_sha256"],
        "affected_candidate_ids": sorted(revised),
        "prior_reviews_carried_forward": False,
        "human_selection": "pending",
    }
