"""Replay one frozen pilot pair and report engineering readiness without a claim."""

import json
from pathlib import Path

from stage1_eval.common import read_json
from stage1_eval.pipeline_v31 import bundle_sha_v31, execution_policy

from . import runner, sequence
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
    if (
        lock.get("kind") != "Stage1ABPublicLockV3"
        or lock.get("schema_version") != "3.1.0"
        or lock.get("execution_class") != "pilot"
        or lock.get("evaluator_bundle_sha256") != bundle_sha_v31()
        or lock.get("evaluator_execution_policy") != execution_policy()
        or lock.get("plugin_tree_sha256") != runner.tree_sha(runner.PLUGIN_ROOT)
        or runner.sha(Path(background_path).read_bytes())
        != lock.get("background_sha256")
        or lock.get("passive_observer") != _observer_binding()
        or lock.get("evaluator_runtime")
        != {"model": "gpt-5.6-sol", "reasoning": "high"}
        or any(
            lock.get("runtime", {}).get(k) != v
            for k, v in {
                "model_id": "gpt-5.6-sol",
                "reasoning": "high",
                "mode": "default",
                "search_enabled": True,
            }.items()
        )
    ):
        raise runner.ExecutionBlocked("pilot lock, observer or frozen bytes changed")
    expected = sequence.expected_runs(lock)
    if len(expected) != 2 or len(result_paths) != 2 or len(capture_dirs) != 2:
        raise runner.ExecutionBlocked(
            "unscored pilot report needs exactly one A/B pair"
        )
    by_run = {}
    for result_path, capture in zip(result_paths, capture_dirs, strict=True):
        record = runner.verify_capture(capture, verify_runtime=True)
        if (
            record.get("status") != "complete"
            or record.get("lock_kind") != "Stage1ABPublicLockV3"
            or record.get("lock_sha256") != runner.sha(raw)
            or record.get("stage1_receipt_error")
            or (
                record.get("condition") == "treatment"
                and not record.get("stage1_receipt")
            )
            or record["run_id"] in by_run
        ):
            raise runner.ExecutionBlocked(
                "pilot capture is incomplete, duplicated or unbound"
            )
        result = _replay_result(
            result_path,
            capture,
            lock_path,
            background_path,
            lock,
            execution_class="exploratory-pilot",
        )
        root = Path(result_path).parent
        binding = read_json(root / "evaluation-input.json")["binding"]
        if (
            binding.get("run_id") != record["run_id"]
            or binding.get("series_id") != record["series_id"]
        ):
            raise runner.ExecutionBlocked("pilot result belongs to a different capture")
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
                raise runner.ExecutionBlocked("pilot review artifact missing: " + name)
            artifacts[name] = {
                "path": str(path.resolve()),
                "sha256": runner.sha(path.read_bytes()),
            }
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
        raise runner.ExecutionBlocked("pilot results mix runs or execution series")
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
        "acceptance_status": "requires-cause-review"
        if cause_review
        else "replay-complete",
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
