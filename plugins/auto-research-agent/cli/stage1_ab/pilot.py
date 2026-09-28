"""Replay one frozen pilot pair and report engineering readiness without a claim."""

import json
from pathlib import Path

from stage1_eval.common import read_json
from stage1_eval.pipeline_v31 import bundle_sha_v31, execution_policy

from . import runner, sequence
from .admission import AdmissionBlocked
from .comparison import capture_costs, compare_results, export_report
from .general_v31 import _replay_result


def _observer_binding():
    try:
        from .observer import binding
    except ImportError as error:
        raise runner.ExecutionBlocked(
            "common passive observer integration is required"
        ) from error
    return binding()


def _require_complete_evaluator():
    try:
        from stage1_eval.complete_judging import judge_packet_complete
        from stage1_eval.pipeline_v31 import judge_packet_v31
    except ImportError as error:
        raise runner.ExecutionBlocked(
            "complete evaluator integration is required"
        ) from error
    if judge_packet_v31 is not judge_packet_complete:
        raise runner.ExecutionBlocked("pilot evaluator still uses incomplete judging")


def pilot_report(lock_path, background_path, result_paths, capture_dirs, output):
    """This read-only replay never calls capture, freezes a formal run, or approves it."""
    raw = Path(lock_path).read_bytes()
    lock = json.loads(raw)
    _require_complete_evaluator()
    required = {
        "kind": "Stage1ABPublicLockV3",
        "schema_version": "3.1.0",
        "execution_class": "pilot",
        "evaluator_bundle_sha256": bundle_sha_v31(),
        "evaluator_execution_policy": execution_policy(),
        "plugin_tree_sha256": runner.tree_sha(runner.PLUGIN_ROOT),
        "background_sha256": runner.sha(Path(background_path).read_bytes()),
        "passive_observer": _observer_binding(),
        "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
    }
    reasons = [
        "different-" + key
        for key, expected_value in required.items()
        if lock.get(key) != expected_value
    ]
    reasons += [
        "different-runtime-" + key
        for key, expected_value in {
            "model_id": "gpt-5.6-sol",
            "reasoning": "high",
            "mode": "default",
            "search_enabled": True,
        }.items()
        if lock.get("runtime", {}).get(key) != expected_value
    ]
    if reasons:
        raise AdmissionBlocked("pilot lock, observer or frozen bytes changed", reasons)
    expected = sequence.expected_runs(lock)
    if len(expected) != 2 or len(result_paths) != 2 or len(capture_dirs) != 2:
        raise runner.ExecutionBlocked(
            "unscored pilot report needs exactly one A/B pair"
        )
    by_run = {}
    for result_path, capture in zip(result_paths, capture_dirs, strict=True):
        record = runner.verify_capture(capture, verify_runtime=True)
        capture_reasons = [
            "capture-" + key + "-mismatch"
            for key, expected_value in {
                "status": "complete",
                "lock_kind": "Stage1ABPublicLockV3",
                "lock_sha256": runner.sha(raw),
            }.items()
            if record.get(key) != expected_value
        ]
        if record.get("stage1_receipt_error"):
            capture_reasons.append("capture-stage1-receipt-error")
        if record.get("condition") == "treatment" and not record.get("stage1_receipt"):
            capture_reasons.append("capture-stage1-receipt-unavailable")
        if record["run_id"] in by_run:
            capture_reasons.append("duplicate-run-id")
        if capture_reasons:
            raise AdmissionBlocked(
                "pilot capture is incomplete, duplicated or unbound", capture_reasons
            )
        root = Path(result_path).parent
        artifacts = {}
        for name in (
            "result.json",
            "evaluation-input.json",
            "model-costs.json",
            "judgments.json",
            "subject-sources.json",
            "source-audits.json",
            "native-field-availability.json",
            "judging/result.json",
            "original-fields/result.json",
            "source-audits/r1/result.json",
            "source-audits/r2/result.json",
        ):
            path = root / name
            if not path.is_file():
                raise AdmissionBlocked(
                    "pilot review artifact missing: " + name,
                    ["cause-evidence-unavailable", "missing-artifact:" + name],
                )
            artifacts[name] = {
                "path": str(path.resolve()),
                "sha256": runner.sha(path.read_bytes()),
            }
        result = _replay_result(
            result_path,
            capture,
            lock_path,
            background_path,
            lock,
            execution_class="exploratory-pilot",
        )
        binding = read_json(root / "evaluation-input.json")["binding"]
        if (
            binding.get("run_id") != record["run_id"]
            or binding.get("series_id") != record["series_id"]
        ):
            raise AdmissionBlocked(
                "pilot result belongs to a different capture",
                [
                    "different-capture-" + key
                    for key in ("run_id", "series_id")
                    if binding.get(key) != record[key]
                ],
            )
        by_run[record["run_id"]] = {
            "result": result,
            "capture": record,
            "model_costs": read_json(root / "model-costs.json"),
            "review_artifacts": artifacts,
        }
    if (
        set(by_run) != {r["run_id"] for r in expected}
        or len({r["capture"]["series_id"] for r in by_run.values()}) != 1
    ):
        raise AdmissionBlocked(
            "pilot results mix runs or execution series",
            ["different-run-set-or-execution-series"],
        )
    pair = lock["paired_repeats"][0]
    arms = {
        arm: by_run[pair[condition]["run_id"]]
        for arm, condition in (("A", "baseline"), ("B", "treatment"))
    }
    compared = compare_results(arms["A"]["result"], arms["B"]["result"])
    cause_review = []
    for row in compared["criteria"]:
        for arm in ("A", "B"):
            if row[arm + "_status"] == "unverifiable":
                cause_review.append(
                    {
                        "arm": arm,
                        "criterion_id": row["criterion_id"],
                        "unknown_reason": row[arm + "_unknown_reason"],
                        "evidence_ids": row[arm + "_evidence_ids"],
                        "review_artifacts": arms[arm]["review_artifacts"],
                    }
                )
    acceptance_reasons = list(compared["binding_ineligibility_reasons"])
    for row in [*compared["dimensions"].values(), *compared["criteria"]]:
        if not row["delta_eligible"]:
            acceptance_reasons.extend(row["ineligibility_reasons"])
    major_review = []
    for arm, item in arms.items():
        for issue in item["result"].get("major_issues", []):
            status = issue.get("status", "unavailable")
            reason = arm + "-major-issue-" + status
            acceptance_reasons.append(reason)
            major_review.append(
                {
                    "arm": arm,
                    "reason_code": reason,
                    "issue": issue,
                    "review_artifacts": item["review_artifacts"],
                }
            )
    if cause_review:
        acceptance_reasons.append("cause-evidence-review-required")
    acceptance_reasons = sorted(set(acceptance_reasons))
    # Scores remain diagnostic model outputs. No formal improvement rule is run.
    compared.update(
        repeat=1,
        capture_costs={a: capture_costs(r["capture"]) for a, r in arms.items()},
        evaluator_model_costs={a: r["model_costs"] for a, r in arms.items()},
    )
    value = {
        "kind": "Stage1UnscoredPilotReport.v1",
        "decision": "unscored-pilot",
        "lock_sha256": runner.sha(raw),
        "replay_verified": True,
        "replay_status": "replay-complete",
        "pairs": [compared],
        "summary": {
            metric: {
                "pair_deltas": [r["delta"]],
                "median_delta": None,
                "range": None,
                "delta_eligible": r["delta_eligible"],
                "ineligibility_reasons": r["ineligibility_reasons"],
            }
            for metric, r in compared["dimensions"].items()
        },
        "unknown_cause_review": cause_review,
        "review_artifacts": {a: r["review_artifacts"] for a, r in arms.items()},
        "major_issue_review": major_review,
        "acceptance_reason_codes": acceptance_reasons,
        "acceptance_status": "requires-cause-review"
        if acceptance_reasons
        else "comparison-eligible-awaiting-review",
        "acceptance_scope": "Archive integrity and comparison eligibility only; operator must check cause evidence and all pilot acceptance requirements before readiness.",
        "formal_quality_score": None,
        "formal_subject_runs_authorized": False,
        "freeze_ready": False,
        "no_composite_total": True,
        "external_claim_ready": False,
    }
    if Path(output).exists():
        raise runner.ExecutionBlocked("pilot output already exists")
    export_report(value, output)
    runner.write_json(output, value)
    return value
