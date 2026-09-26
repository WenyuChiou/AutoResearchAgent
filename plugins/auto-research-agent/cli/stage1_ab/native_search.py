"""Reconstruct hash-bound native web-search observations without re-execution."""

import json
from copy import deepcopy
from pathlib import Path, PurePosixPath

from stage1_eval.common import EvaluationError, canonical, sha


def _safe_name(name):
    if not isinstance(name, str) or not name or "\\" in name or ":" in name:
        return False
    path = PurePosixPath(name)
    return (
        not path.is_absolute()
        and path.as_posix() == name
        and all(part not in {"", ".", ".."} for part in path.parts)
    )


def _event_id(event):
    item = event.get("item")
    if isinstance(item, dict) and isinstance(item.get("id"), str):
        return item["id"]
    return event.get("id") if isinstance(event.get("id"), str) else None


def _event_ref(attempt_number, line_number, event, raw_line):
    item = event.get("item") if isinstance(event.get("item"), dict) else {}
    action = item.get("action")
    return {
        "attempt": attempt_number,
        "line": line_number,
        "event_id": _event_id(event),
        "event_type": event.get("type"),
        "item_type": item.get("type"),
        "raw_action": deepcopy(action) if isinstance(action, dict) else None,
        "raw_line_sha256": sha(raw_line),
    }


def _parse_attempt(root, attempt, attempt_number):
    files = attempt.get("files")
    if not isinstance(files, dict):
        raise EvaluationError("native search capture attempt lacks file bindings")
    if any(not _safe_name(name) for name in files):
        raise EvaluationError("native search capture contains an unsafe file name")
    expected_name = f"attempt-{attempt_number:02d}.jsonl"
    if expected_name not in files:
        raise EvaluationError(f"native search capture lacks {expected_name}")
    path = root / expected_name
    if not path.is_file():
        raise EvaluationError(f"native search transcript is missing: {expected_name}")
    raw = path.read_bytes()
    if sha(raw) != files[expected_name]:
        raise EvaluationError(f"native search transcript hash differs: {expected_name}")

    actions = []
    started = []
    errors = []
    completed_ids = set()
    completed_web_ids = set()
    result_counts = []
    exposed_failure = False
    for line_number, raw_line in enumerate(raw.splitlines(), 1):
        try:
            event = json.loads(raw_line)
        except (UnicodeDecodeError, ValueError) as exc:
            raise EvaluationError(
                f"native search transcript invalid JSON: attempt {attempt_number} line {line_number}"
            ) from exc
        if not isinstance(event, dict):
            raise EvaluationError(
                f"native search transcript event is not an object: attempt {attempt_number} line {line_number}"
            )
        event_type = event.get("type")
        item = event.get("item") if isinstance(event.get("item"), dict) else {}
        event_id = _event_id(event)
        if event_type == "item.completed" and event_id is not None:
            if event_id in completed_ids:
                raise EvaluationError(
                    f"duplicate completed event ID in attempt {attempt_number}: {event_id}"
                )
            completed_ids.add(event_id)
        if event_type == "item.started" and item.get("type") == "web_search":
            started.append(_event_ref(attempt_number, line_number, event, raw_line))
        if event_type == "item.completed" and item.get("type") == "web_search":
            if event_id is not None:
                completed_web_ids.add(event_id)
            ref = _event_ref(attempt_number, line_number, event, raw_line)
            action = item.get("action")
            action_type = action.get("type") if isinstance(action, dict) else None
            queries = action.get("queries") if isinstance(action, dict) else None
            valid_queries = (
                deepcopy(queries)
                if isinstance(queries, list)
                and all(isinstance(query, str) for query in queries)
                else []
            )
            explicit_results = item.get("results")
            result_count = (
                len(explicit_results) if isinstance(explicit_results, list) else None
            )
            if action_type == "search" and result_count is not None:
                result_counts.append(result_count)
            if item.get("error") is not None or item.get("status") == "failed":
                exposed_failure = True
            actions.append(
                {
                    **ref,
                    "action_type": action_type,
                    "queries": valid_queries if action_type == "search" else [],
                    "queries_exposed": action_type == "search"
                    and isinstance(queries, list)
                    and all(isinstance(query, str) for query in queries),
                    "result_count": result_count,
                    "retrieval_error_exposed": item.get("error") is not None
                    or item.get("status") == "failed",
                }
            )
        is_error = (
            event_type in {"error", "turn.failed", "item.failed"}
            or item.get("type") == "error"
        )
        if is_error:
            errors.append(_event_ref(attempt_number, line_number, event, raw_line))

    incomplete = [row for row in started if row["event_id"] not in completed_web_ids]
    search_actions = [row for row in actions if row["action_type"] == "search"]
    other_actions = [row for row in actions if row["action_type"] != "search"]
    return {
        "attempt": attempt_number,
        "started_at": attempt.get("started_at"),
        "ended_at": attempt.get("ended_at"),
        "exit_code": attempt.get("exit_code"),
        "transcript": {"path": expected_name, "sha256": sha(raw)},
        "actions": actions,
        "started_events": started,
        "incomplete_events": incomplete,
        "error_events": errors,
        "counts": {
            "completed_search_actions": len(search_actions),
            "completed_search_queries": sum(
                len(row["queries"]) for row in search_actions
            ),
            "completed_other_actions": len(other_actions),
            "search_actions_missing_queries": sum(
                not row["queries_exposed"] for row in search_actions
            ),
            "started_web_events": len(started),
            "incomplete_web_events": len(incomplete),
            "error_events": len(errors),
        },
        "explicit_result_counts": result_counts,
        "exposed_failure": exposed_failure,
    }


def native_search_receipt(capture_dir, attempts):
    """Build an observational receipt from saved native JSONL only."""
    root = Path(capture_dir)
    if not isinstance(attempts, list) or not attempts:
        raise EvaluationError("native search receipt needs captured attempts")
    run_path = root / "run.json"
    run_sha = None
    if run_path.is_file():
        raw_run = run_path.read_bytes()
        try:
            run = json.loads(raw_run)
        except ValueError as exc:
            raise EvaluationError("native search capture run.json is invalid") from exc
        if run.get("attempts") != attempts:
            raise EvaluationError("native search attempts differ from run.json")
        run_sha = sha(raw_run)
    observed = [
        _parse_attempt(root, attempt, number)
        for number, attempt in enumerate(attempts, 1)
    ]
    counts = {
        key: sum(row["counts"][key] for row in observed)
        for key in observed[0]["counts"]
    }
    all_result_counts = [
        count for row in observed for count in row["explicit_result_counts"]
    ]
    search_actions = counts["completed_search_actions"]
    exposed_for_every_search = (
        search_actions > 0 and len(all_result_counts) == search_actions
    )
    receipt = {
        "kind": "NativeSearchReceipt",
        "schema_version": "1.0.0",
        "status": "observational",
        "observation_state": (
            "native-search-observed"
            if search_actions
            else "no-completed-native-search-observed"
        ),
        "source": {
            "attempts_sha256": sha(canonical(attempts)),
            "run_json_sha256": run_sha,
        },
        "attempts": [
            {
                key: value
                for key, value in row.items()
                if key not in {"explicit_result_counts", "exposed_failure"}
            }
            for row in observed
        ],
        "counts": counts,
        "limitations": {
            "result_count": sum(all_result_counts)
            if exposed_for_every_search
            else None,
            "retrieval_failure_state": (
                "exposed-error"
                if any(row["exposed_failure"] for row in observed)
                else "not-exposed"
            ),
            "full_text_verified": False,
            "work_identity_verified": False,
            "search_success_inferred": False,
            "search_summaries_are_not_result_evidence": True,
        },
        "network_reexecution": False,
    }
    receipt["receipt_sha256"] = sha(canonical(receipt))
    return receipt


def verify_native_search_receipt(capture_dir, attempts, submitted_receipt):
    """Replay saved transcripts and require byte-equivalent receipt content."""
    expected = native_search_receipt(capture_dir, attempts)
    if canonical(submitted_receipt) != canonical(expected):
        raise EvaluationError("submitted native search receipt differs from replay")
    return expected
