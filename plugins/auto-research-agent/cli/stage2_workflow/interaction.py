"""Record report-bound user input and a planning handoff, never grant execution."""

import copy
import hashlib
import json
from pathlib import Path

from stage2_check.contracts import decode_json
from stage2_common import Stage2Error, canonical_hash

from .delivery import inspect_delivery
from .store import finish_action, inspect_workflow, start_action

KINDS = {"select", "compare", "clarify", "revise", "merge", "reopen"}
SETTINGS = {"contract": "stage2-human-interaction", "version": "1.0.0"}


def _require(condition, reason):
    if not condition:
        raise Stage2Error(reason)


def _text(value, reason):
    _require(isinstance(value, str) and bool(value.strip()), reason)


def _user_text(raw, index):
    """Extract an exact native user message; neither assistant nor tool text counts."""
    _require(type(index) is int and index >= 0, "human-message-index-invalid")
    rows = [
        decode_json(line, "native message") for line in raw.splitlines() if line.strip()
    ]
    _require(index < len(rows), "human-message-index-missing")
    row = rows[index]
    _require(isinstance(row, dict), "human-message-object-required")
    if row.get("type") == "event_msg":
        item = row.get("payload")
        _require(
            isinstance(item, dict) and item.get("type") == "user_message",
            "native-user-message-required",
        )
        text = item.get("message")
    elif row.get("type") == "response_item":
        item = row.get("payload")
        _require(
            isinstance(item, dict)
            and item.get("type") == "message"
            and item.get("role") == "user",
            "native-user-message-required",
        )
        content = item.get("content")
        _require(isinstance(content, list) and content, "native-user-content-required")
        _require(
            all(
                isinstance(part, dict)
                and part.get("type") == "input_text"
                and isinstance(part.get("text"), str)
                for part in content
            ),
            "native-user-text-only-required",
        )
        text = "\n".join(part["text"] for part in content)
    else:
        raise Stage2Error("unsupported-native-user-message")
    _text(text, "native-user-text-required")
    return text


def _validate_decision(decision, text):
    _require(
        isinstance(decision, dict)
        and set(decision)
        == {
            "actor",
            "kind",
            "user_text",
            "selected",
            "conditions",
            "unresolved",
            "rationale",
            "scope_or_resource_change",
        },
        "human-decision-shape",
    )
    _text(decision["actor"], "human-actor-required")
    _text(decision["rationale"], "human-rationale-required")
    _require(
        isinstance(decision["kind"], str) and decision["kind"] in KINDS,
        "human-decision-kind",
    )
    _require(decision["user_text"] == text, "human-quote-mismatch")
    _require(
        type(decision["scope_or_resource_change"]) is bool, "human-scope-change-boolean"
    )
    for field in ("conditions", "unresolved"):
        _require(isinstance(decision[field], list), f"human-{field}-list")
        for value in decision[field]:
            _text(value, f"human-{field}-text")
    _require(isinstance(decision["selected"], list), "human-selected-list")
    keys = []
    for row in decision["selected"]:
        _require(
            isinstance(row, dict) and set(row) == {"candidate_id", "candidate_version"},
            "human-selected-shape",
        )
        _text(row["candidate_id"], "human-selected-id")
        _require(
            type(row["candidate_version"]) is int and row["candidate_version"] > 0,
            "human-selected-version",
        )
        keys.append((row["candidate_id"], row["candidate_version"]))
    _require(len(keys) == len(set(keys)), "human-duplicate-selection")
    if decision["kind"] == "select":
        _require(bool(keys), "human-selection-empty")
        _require(
            not decision["scope_or_resource_change"], "changed-scope-needs-recheck"
        )
    else:
        _require(not keys, "nonselection-cannot-select")


def _record(state, delivery, decision, raw, message_index):
    manifest = delivery["manifest"]
    snapshot_hash = state["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
    _require(
        manifest["workflow_manifest_sha256"] == state["manifest"]["manifest_sha256"],
        "human-foreign-workflow",
    )
    _require(
        manifest["workflow_head_sha256"] == state["head_sha256"]
        and manifest["snapshot_sha256"] == snapshot_hash,
        "human-report-stale",
    )
    snapshot = state["latest_snapshot"]
    _require(
        delivery["input_packet"] == snapshot["packet"]
        and manifest["snapshot_sequence"]
        == snapshot["event"]["payload"]["snapshot_sequence"]
        and manifest["snapshot_checker_manifest_sha256"]
        == snapshot["checker"]["manifest"]["manifest_sha256"],
        "human-report-current-packet-mismatch",
    )
    selected = decision["selected"]
    if decision["kind"] == "select":
        _require(
            manifest["delivery_status"] == "local-report-ready",
            "human-report-not-ready",
        )
        available = manifest["recommendation_candidate_versions"]
        _require(
            all(row in available for row in selected),
            "human-selection-not-current-recommendation",
        )
    packet = delivery["selection"]["evaluation_packet"]
    options = {
        (row["candidate"]["candidate_id"], row["candidate"]["version"]): row
        for row in delivery["selection"]["current_options"]
    }
    handoff = None
    if selected:
        handoff = {
            "kind": "Stage2ToStage3PlanningHandoff",
            "schema_version": "1.0.0",
            "report_manifest_sha256": manifest["manifest_sha256"],
            "snapshot_sha256": snapshot_hash,
            "selected_options": [
                copy.deepcopy(options[(row["candidate_id"], row["candidate_version"])])
                for row in selected
            ],
            "brief": packet["brief"],
            "resources": packet["resources"],
            "sources": packet["sources"],
            "source_base_in_delivery": "sources",
            "evidence": packet["evidence"],
            "review_audit_ref": "review_audit.json",
            "conditions": decision["conditions"],
            "unresolved": list(
                dict.fromkeys(packet["unresolved"] + decision["unresolved"])
            ),
            "return_to_stage2_when": "Evidence undermines a selected prerequisite, answerability, value, or agreed resource constraint; retain the evidence and request a new candidate version.",
            "next_work": "Detailed methods, data handling, baselines, analysis, validation and schedule; assess combined costs for multiple selected directions.",
            "execution_authorized": False,
        }
    result = {
        "kind": "Stage2HumanInteraction",
        "schema_version": "1.0.0",
        "workflow_head_sha256": state["head_sha256"],
        "report_manifest_sha256": manifest["manifest_sha256"],
        "snapshot_sha256": snapshot_hash,
        "message_sha256": hashlib.sha256(raw).hexdigest(),
        "message_index": message_index,
        "decision": copy.deepcopy(decision),
        "human_selection": "recorded" if selected else "pending",
        "requires_new_report": not bool(selected),
        "handoff": handoff,
        "identity_authenticated": False,
        "execution_authorized": False,
        "authority_boundary": "Native message role/text and file bytes are checked; the host must establish actual human origin and interpretation. This record grants no tool permissions.",
    }
    result["record_sha256"] = canonical_hash(result)
    return result


def record_interaction(
    run_dir,
    delivery_dir,
    manifest_sha256,
    decision,
    message_path,
    message_index,
    action_id,
    output_dir,
    expected_head,
):
    """Append one user decision through existing action records, retaining its source."""
    state = inspect_workflow(run_dir, expected_head)
    delivery = inspect_delivery(delivery_dir, manifest_sha256)
    raw = Path(message_path).read_bytes()
    text = _user_text(raw, message_index)
    _validate_decision(decision, text)
    inputs = {
        "delivery_manifest_sha256": manifest_sha256,
        "decision": decision,
        "message_sha256": hashlib.sha256(raw).hexdigest(),
        "message_index": message_index,
    }
    if action_id in state["actions"]:
        reused = start_action(
            run_dir, action_id, "human-interaction", inputs, SETTINGS, expected_head
        )
        ref = reused["result"]["artifacts"]["interaction.json"]
        saved = decode_json(
            (state["root"] / ref["stored_path"]).read_bytes(), "saved interaction"
        )
        return {"reuse": True, "record": saved, "head_sha256": state["head_sha256"]}
    record = _record(state, delivery, decision, raw, message_index)
    output = Path(output_dir).resolve()
    _require(not output.exists(), "human-output-exists")
    output.mkdir(parents=False)
    # Preserve complete user evidence before recording success; a partial
    # publication remains incomplete and is never silently retried.
    intent = start_action(
        run_dir, action_id, "human-interaction", inputs, SETTINGS, expected_head
    )
    artifacts = {}
    values = {
        "interaction.json": json.dumps(
            record, ensure_ascii=False, sort_keys=True, allow_nan=False
        ).encode("utf-8"),
        "native-user-message.jsonl": raw,
        "delivery_manifest.json": (
            delivery["root"] / "delivery_manifest.json"
        ).read_bytes(),
    }
    for name, data in values.items():
        path = output / name
        with path.open("xb") as stream:
            stream.write(data)
        artifacts[name] = {
            "path": str(path),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    finished = finish_action(
        run_dir,
        action_id,
        "complete",
        artifacts,
        None,
        None,
        intent["event"]["event_sha256"],
    )
    return {"reuse": False, "record": record, "head_sha256": finished["event_sha256"]}
