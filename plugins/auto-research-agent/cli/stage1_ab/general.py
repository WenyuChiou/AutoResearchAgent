"""Freeze a no-answer-key Stage 1 v3 A/B series before any subject run."""

import copy
import json
import statistics
import subprocess
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path

from stage1_eval.common import (
    canonical,
    check_spec,
    load_rubric,
    read_json,
    validate_schema,
)
from stage1_eval.__main__ import (
    _code_sha,
    _evaluator_bundle_sha,
    _verify_background,
    _verify_source_receipts,
)
from stage1_eval.adapter import adapt_subject, extraction_prompt, validate_extraction
from stage1_eval.common import EVAL_ROOT, EvaluationError
from stage1_eval.formal import attach_workspace, verify_hub_receipts
from stage1_eval.judging import (
    _schema_for_phase,
    _signature,
    adjudication_prompt,
    make_packet,
    phase_prompt,
    validate_judgment,
)
from stage1_eval.model import _api_schema, completed_agent_json
from stage1_eval.runtime import executable_sha256, verify_installed_from_commit
from stage1_eval.score import aggregate

from . import runner, sequence


def _check_result_scores(result):
    """Reject a result whose displayed numbers differ from its atomic rubric rows."""
    rubric, rubric_sha = load_rubric()
    if result["rubric_sha256"] != rubric_sha:
        raise runner.ExecutionBlocked("paired v3 rubric bytes differ from result")
    confirmed = any(
        issue.get("status") == "confirmed" for issue in result["major_issues"]
    )
    if confirmed != (
        result["scientific_readiness_status"] == "fail-confirmed-major-issue"
    ):
        raise runner.ExecutionBlocked("paired v3 major-issue readiness changed")
    for dimension in rubric["dimensions"]:
        metric = dimension["id"]
        value = result["dimensions"][metric]
        expected_ids = {
            row["id"] for row in rubric["criteria"] if row["dimension"] == metric
        }
        rows = value["criteria"]
        if (
            len(rows) != len(expected_ids)
            or {row.get("criterion_id") for row in rows} != expected_ids
        ):
            raise runner.ExecutionBlocked("paired v3 atomic rubric rows differ")
        for row in rows:
            if row.get("status") == "scored":
                if type(row.get("score")) is not int or row["score"] not in (0, 1, 2):
                    raise runner.ExecutionBlocked("paired v3 atomic score is invalid")
            elif (
                row.get("status") not in {"unverifiable", "not-applicable"}
                or row.get("score") is not None
            ):
                raise runner.ExecutionBlocked("paired v3 atomic status is invalid")
        applicable = [row for row in rows if row["status"] != "not-applicable"]
        scored = [row for row in applicable if row["status"] == "scored"]
        unknown = len(applicable) - len(scored)
        points = sum(row["score"] for row in scored)
        denominator = 2 * len(applicable)
        expected = {
            "applicable_count": len(applicable),
            "scored_count": len(scored),
            "unknown_count": unknown,
            "not_applicable_count": len(rows) - len(applicable),
            "assessed_fraction": len(scored) / len(applicable) if applicable else None,
            "observed_score_100": round(100 * points / (2 * len(scored)), 2)
            if scored
            else None,
            "lower_bound_100": round(100 * points / denominator, 2)
            if denominator
            else None,
            "upper_bound_100": round(100 * (points + 2 * unknown) / denominator, 2)
            if denominator
            else None,
        }
        if any(value.get(key) != count for key, count in expected.items()):
            raise runner.ExecutionBlocked("paired v3 dimension counts or score changed")
        for status, field in (
            ("confirmed", "confirmed_major_issue_ids"),
            ("unresolved", "unresolved_major_issue_ids"),
        ):
            issue_ids = [
                row["issue_id"]
                for row in result["major_issues"]
                if row.get("dimension") == metric and row.get("status") == status
            ]
            if value.get(field) != issue_ids:
                raise runner.ExecutionBlocked("paired v3 major-issue summary changed")


def _verified_model_log(log_dir, label, provenance, prompt, schema, lock):
    """Bind saved output to the actual completed model event and invocation."""
    if provenance.get("reused_completed_generation"):
        raise runner.ExecutionBlocked("formal v3 cannot reuse pilot judge output")
    output = log_dir / f"{label}.json"
    trace = log_dir / f"{label}.jsonl"
    stderr = log_dir / f"{label}.stderr.txt"
    generation_schema = log_dir / f"{label}.generation-schema.json"
    expected_generation = json.dumps(
        _api_schema(read_json(schema)), sort_keys=True
    ).encode("utf-8")
    if (
        runner.sha(output.read_bytes()) != provenance.get("output_sha256")
        or runner.sha(trace.read_bytes()) != provenance.get("stdout_sha256")
        or any(
            (
                provenance.get("model") != lock["evaluator_runtime"]["model"],
                provenance.get("reasoning") != lock["evaluator_runtime"]["reasoning"],
                provenance.get("codex_executable_sha256")
                != lock["codex_executable_sha256"],
                provenance.get("prompt_sha256") != runner.sha(prompt.encode("utf-8")),
                provenance.get("schema_sha256")
                != runner.sha(Path(schema).read_bytes()),
                provenance.get("generation_schema_sha256")
                != runner.sha(expected_generation),
                generation_schema.read_bytes() != expected_generation,
                provenance.get("stderr_sha256") != runner.sha(stderr.read_bytes()),
            )
        )
    ):
        raise runner.ExecutionBlocked("formal v3 model invocation provenance changed")
    observed = read_json(output)
    if canonical(completed_agent_json(trace.read_bytes())) != canonical(observed):
        raise runner.ExecutionBlocked("formal v3 model output differs from transcript")
    return observed


def _verified_judge_log(root, label, provenance, prompt, schema, lock, packet, phase):
    """Replay the exact judge prompt and a bounded correction, if any."""
    if "correction" in provenance:
        initial = _verified_model_log(
            root / "judging" / "model-logs",
            label,
            provenance["initial_invalid"],
            prompt,
            schema,
            lock,
        )
        try:
            validate_judgment(initial, packet, phase)
        except EvaluationError as error:
            if provenance.get("correction_reason") != str(error):
                raise runner.ExecutionBlocked(
                    "formal v3 correction reason changed"
                ) from error
        else:
            raise runner.ExecutionBlocked("formal v3 correction followed a valid judge")
        prompt += (
            "\nYour previous output failed local evidence validation: "
            + provenance["correction_reason"]
            + ". Re-evaluate from the SAME packet, do not invent new evidence, "
            "and satisfy the exact evidence-ID and phase restrictions."
        )
        label += "-correction"
        provenance = provenance["correction"]
    result = _verified_model_log(
        root / "judging" / "model-logs", label, provenance, prompt, schema, lock
    )
    normalized = copy.deepcopy(result)
    validate_judgment(normalized, packet, phase)
    return normalized


def _verify_result_bundle(
    result_path, result, lock, background, background_path, capture_dir, last
):
    """Rebuild a formal score from saved subject, source, packet and judge files."""
    result_path = Path(result_path)
    if result_path.name != "result.json":
        raise runner.ExecutionBlocked("formal v3 result must be its evaluator bundle")
    root = result_path.resolve().parent
    subject = read_json(root / "subject-observation.json")
    replay = adapt_subject(
        Path(capture_dir) / f"attempt-{last:02d}.final.txt",
        Path(capture_dir) / f"attempt-{last:02d}.jsonl",
        status="complete",
        max_trace_bytes=2_000_000,
    )
    attach_workspace(
        replay,
        {"snapshot_path": str(Path(capture_dir) / "workspace" / f"{last:02d}")},
    )
    if canonical(subject) != canonical(replay):
        raise runner.ExecutionBlocked("formal v3 subject observation changed")
    packet = read_json(root / "evidence-packet.json")
    extraction = read_json(root / "subject-extraction.json")
    source_result = read_json(root / "subject-sources.json")
    judgments = read_json(root / "judgments.json")
    if runner.sha(packet["task"].encode("utf-8")) != lock["task_sha256"]:
        raise runner.ExecutionBlocked("formal v3 task text changed")
    _verify_background(background, background_path, packet["spec"])
    validated_extraction = validate_extraction(copy.deepcopy(extraction), subject)
    if canonical(validated_extraction) != canonical(extraction):
        raise runner.ExecutionBlocked("formal v3 extraction normalization changed")
    extraction_provenance = read_json(root / "extraction-provenance.json")
    extract_prompt = extraction_prompt(subject)
    extract_schema = EVAL_ROOT / "schemas/subject-extraction.v3.schema.json"
    if "correction" in extraction_provenance:
        original = _verified_model_log(
            root / "model-logs",
            "subject-extraction",
            extraction_provenance["initial"],
            extract_prompt,
            extract_schema,
            lock,
        )
        try:
            validate_extraction(copy.deepcopy(original), subject)
        except EvaluationError as error:
            if extraction_provenance.get("correction_reason") != str(error):
                raise runner.ExecutionBlocked(
                    "formal v3 extraction correction reason changed"
                ) from error
        else:
            raise runner.ExecutionBlocked(
                "formal v3 extraction correction followed valid output"
            )
        extract_prompt += (
            "\nThe first extraction failed exact-text validation: "
            + extraction_provenance["correction_reason"]
            + ". Re-extract from the same subject only; copy title and identifiers exactly, "
            "with no added punctuation or inferred facts."
        )
        extract_label = "subject-extraction-correction"
        extraction_provenance = extraction_provenance["correction"]
    else:
        extract_label = "subject-extraction"
    raw_extraction = _verified_model_log(
        root / "model-logs",
        extract_label,
        extraction_provenance,
        extract_prompt,
        extract_schema,
        lock,
    )
    if canonical(
        validate_extraction(copy.deepcopy(raw_extraction), subject)
    ) != canonical(extraction):
        raise runner.ExecutionBlocked(
            "formal v3 extraction differs from model transcript"
        )
    if (
        runner.sha(canonical(packet)) != result.get("packet_sha256")
        or runner.sha(canonical(packet["spec"])) != lock["spec_sha256"]
        or runner.sha(canonical(packet["challenge_receipts"]))
        != lock["background_receipts_sha256"]
        or canonical(packet["subject_source_receipts"])
        != canonical(source_result["receipts"])
        or packet["content_evidence"].get("answer") != subject["evidence"]["answer"]
        or any(
            packet["process_evidence"].get(key) != item
            for key, item in subject["evidence"].items()
        )
    ):
        raise runner.ExecutionBlocked("formal v3 evidence packet changed")
    hub_binding = {
        "hub_command_prefix": lock["hub_command_prefix"],
        "hub_executable_sha256": lock["hub_executable_sha256"],
        "research_hub_package_sha256": lock["research_hub_package_sha256"],
    }
    verify_hub_receipts(packet["challenge_receipts"], hub_binding)
    verify_hub_receipts(source_result["receipts"], hub_binding)
    _verify_source_receipts(source_result, root, extraction, packet["spec"])
    expected_packet = make_packet(
        packet["task"],
        packet["spec"],
        subject,
        extraction,
        background,
        source_result,
        mode="evidence-audited",
    )
    if canonical(expected_packet) != canonical(packet):
        raise runner.ExecutionBlocked("formal v3 packet differs from verified inputs")
    rubric, rubric_sha = load_rubric()
    for phase in ("content", "process"):
        schema = _schema_for_phase(root / "judging", phase)
        prompt = phase_prompt(packet, phase, rubric, rubric_sha)
        outputs = {}
        for role in ("r1", "r2"):
            label = f"{phase}-{role}"
            outputs[role] = _verified_judge_log(
                root,
                label,
                judgments["provenance"][label],
                prompt,
                schema,
                lock,
                packet,
                phase,
            )
        differs = _signature(outputs["r1"]) != _signature(outputs["r2"])
        if differs != (phase in judgments["adjudicated_phases"]):
            raise runner.ExecutionBlocked("formal v3 adjudication record changed")
        if differs:
            label = f"{phase}-adj"
            adj_prompt = adjudication_prompt(prompt, outputs["r1"], outputs["r2"])
            selected = _verified_judge_log(
                root,
                label,
                judgments["provenance"][label],
                adj_prompt,
                schema,
                lock,
                packet,
                phase,
            )
        else:
            selected = outputs["r1"]
        if canonical(judgments["selected"][phase]) != canonical(selected):
            raise runner.ExecutionBlocked("formal v3 selected judgment changed")
    expected = aggregate(
        packet,
        judgments,
        evaluator_identity=result["evaluator_identity"],
        costs=result["costs"],
    )
    observed = {
        key: value
        for key, value in result.items()
        if key not in {"created_at", "formal_capture"}
    }
    expected.pop("created_at")
    if canonical(observed) != canonical(expected):
        raise runner.ExecutionBlocked("formal v3 result differs from saved judgments")


def freeze_v3(
    codex,
    task_path,
    spec_path,
    background_path,
    prompt_path,
    runtime_probe_path,
    dependency_repo,
    treatment_runtime_pins,
    output,
    *,
    repeats=3,
    evaluator_dependency_repo=None,
    evaluator_dependency_sha=None,
    research_brief_path=None,
):
    """Create an immutable public lock with topic needs, not expected papers."""
    if repeats not in (1, 3):
        raise runner.ExecutionBlocked("v3 needs one pilot pair or three formal pairs")
    spec = read_json(spec_path)
    check_spec(spec)
    generation = spec.get("generation", {})
    if generation.get("prompt_sha256") is None or generation.get("recovery"):
        raise runner.ExecutionBlocked(
            "formal v3 requires original, non-recovered topic-spec generation"
        )
    task = Path(task_path).read_bytes()
    prompt = Path(prompt_path).read_bytes()
    if not task or task != prompt or runner.sha(task) != spec["task_sha256"]:
        raise runner.ExecutionBlocked(
            "formal task, frozen spec, and subject prompt differ"
        )
    if any(
        key in spec
        for key in ("gold_set", "holdout_sha256", "expected_titles", "core_hit")
    ):
        raise runner.ExecutionBlocked("v3 subject lock must not carry paper answers")
    background_raw = Path(background_path).read_bytes()
    background = json.loads(background_raw)
    _verify_background(background, background_path, spec)
    if (
        not background.get("sources")
        or not background.get("receipts")
        or any(receipt.get("status") != "results" for receipt in background["receipts"])
    ):
        raise runner.ExecutionBlocked(
            "formal v3 cannot freeze an unavailable or ambiguous challenge search"
        )
    probe = read_json(runtime_probe_path)
    expected_capability_sha = runner.sha(
        json.dumps(probe["native_capabilities"], sort_keys=True).encode()
    )
    if (
        probe.get("model") != "gpt-5.6-sol"
        or probe.get("reasoning") != "high"
        or probe.get("native_capabilities_sha256") != expected_capability_sha
        or probe.get("native_web_search") is not True
    ):
        raise runner.ExecutionBlocked(
            "formal v3 runtime probe is not the fixed subject configuration"
        )
    dependency = subprocess.run(
        ["git", "-C", str(dependency_repo), "rev-parse", "HEAD"],
        capture_output=True,
        text=True,
        timeout=20,
        check=True,
    ).stdout.strip()
    if dependency != runner.RESEARCH_HUB_SHA:
        raise runner.ExecutionBlocked(
            "formal v3 research-hub checkout differs from merged SHA"
        )
    v31 = evaluator_dependency_repo is not None
    if bool(research_brief_path) != v31 or bool(evaluator_dependency_sha) != v31:
        raise runner.ExecutionBlocked(
            "v3.1 needs a confirmed brief and separate evaluator dependency pin"
        )
    installed = verify_installed_from_commit(
        evaluator_dependency_repo if v31 else dependency_repo,
        evaluator_dependency_sha if v31 else dependency,
    )
    hub_command = [sys.executable, "-m", "research_hub"]
    hub_executable_sha = runner.sha(Path(sys.executable).read_bytes())
    if not background.get("receipts") or any(
        row.get("command", [])[:3] != hub_command
        or row.get("executable_sha256") != hub_executable_sha
        or row.get("research_hub_package_sha256") != installed["python_source_sha256"]
        for row in background["receipts"]
    ):
        raise runner.ExecutionBlocked("background sources use a different hub runtime")
    pins = runner._pin_paths(treatment_runtime_pins, repeats)
    pin_shas = {
        str(index): runner._runtime_pin(path)[1] for index, path in enumerate(pins, 1)
    }
    orders = [
        ["baseline", "treatment"],
        ["treatment", "baseline"],
        ["baseline", "treatment"],
    ]
    series = []
    for index in range(repeats):
        row = {"repeat": index + 1, "order": orders[index]}
        for condition in orders[index]:
            row[condition] = {
                "run_id": f"v3-{uuid.uuid4().hex}",
                "subject_id": f"anon-{uuid.uuid4().hex}",
            }
        series.append(row)
    sequence.expected_runs({"paired_repeats": series})
    lock = {
        "kind": "Stage1ABPublicLockV3",
        "schema_version": "3.0.0",
        "evaluation_mode": "rubric-evidence",
        "execution_class": "pilot" if repeats == 1 else "formal",
        "topic_id": spec["topic_id"],
        "case_id": spec["topic_id"],
        "task_sha256": runner.sha(task),
        "spec_sha256": runner.sha(canonical(spec)),
        "rubric_sha256": spec["rubric_sha256"],
        "background_sha256": runner.sha(background_raw),
        "background_receipts_sha256": runner.sha(canonical(background["receipts"])),
        "evaluator_bundle_sha256": _evaluator_bundle_sha(),
        "evaluator_code_sha256": _code_sha(),
        "prompt_sha256": runner.sha(prompt),
        "codex_runtime_sha256": runner.codex_runtime_sha(codex),
        "codex_executable_sha256": executable_sha256(codex),
        "plugin_tree_sha256": runner.tree_sha(runner.PLUGIN_ROOT),
        "research_hub_sha": dependency,
        "research_hub_repo_path": str(Path(dependency_repo).resolve()),
        "research_hub_package_sha256": installed["python_source_sha256"],
        "hub_executable_sha256": hub_executable_sha,
        "hub_command_prefix": hub_command,
        "treatment_runtime_pin_sha256_by_repeat": pin_shas,
        "runtime": {
            "app_version": probe["codex_version"],
            "model_id": probe["model"],
            "reasoning": probe["reasoning"],
            "mode": "default",
            "search_enabled": True,
            "tool_profile_sha256": expected_capability_sha,
        },
        "evaluator_runtime": {"model": "gpt-5.6-sol", "reasoning": "high"},
        "execution_policy": runner.SUBJECT_EXECUTION_POLICY,
        "builds": {
            "baseline": {"codex_version": probe["codex_version"]},
            "treatment": {
                "codex_version": probe["codex_version"],
                "plugin_tree_sha256": runner.tree_sha(runner.PLUGIN_ROOT),
                "research_hub_sha": dependency,
            },
        },
        "paired_repeats": series,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    if v31:
        from stage1_brief.brief import validate_brief
        from stage1_eval.pipeline_v31 import bundle_sha_v31, execution_policy

        brief = read_json(research_brief_path)
        validate_brief(brief, require_confirmed=True)
        lock.update(
            schema_version="3.1.0",
            evaluator_bundle_sha256=bundle_sha_v31(),
            evaluator_code_sha256=bundle_sha_v31(),
            evaluator_execution_policy=execution_policy(),
            evaluator_research_hub_repo_path=str(
                Path(evaluator_dependency_repo).resolve()
            ),
            evaluator_research_hub_sha=evaluator_dependency_sha,
            research_brief=brief,
            research_brief_sha256=runner.sha(canonical(brief)),
            search_observation_policy="native-or-cli",
        )
    if any("holdout" in key or "answer_key" in key for key in lock):
        raise runner.ExecutionBlocked("v3 public lock contains an answer-key field")
    runner.write_json(output, lock)
    return lock


def paired_v3(lock_path, background_path, result_paths, capture_dirs, output):
    """Apply the frozen three-pair rule without a paper-answer denominator."""
    lock_raw = Path(lock_path).read_bytes()
    lock = json.loads(lock_raw)
    if lock.get("schema_version") == "3.1.0":
        from .general_v31 import paired_v31

        return paired_v31(
            lock_path, background_path, result_paths, capture_dirs, output
        )
    if (
        lock.get("kind") != "Stage1ABPublicLockV3"
        or lock.get("execution_class") != "formal"
    ):
        raise runner.ExecutionBlocked("paired v3 needs a frozen formal no-gold lock")
    if lock.get("evaluator_bundle_sha256") != _evaluator_bundle_sha():
        raise runner.ExecutionBlocked(
            "paired v3 evaluator bytes differ from frozen lock"
        )
    if lock.get("evaluator_code_sha256") != _code_sha():
        raise runner.ExecutionBlocked(
            "paired v3 evaluator code differs from frozen lock"
        )
    if lock.get("plugin_tree_sha256") != runner.tree_sha(runner.PLUGIN_ROOT):
        raise runner.ExecutionBlocked(
            "paired v3 decision code differs from frozen lock"
        )
    background_raw = Path(background_path).read_bytes()
    if runner.sha(background_raw) != lock.get("background_sha256"):
        raise runner.ExecutionBlocked("paired v3 background differs from frozen lock")
    background = json.loads(background_raw)
    expected = sequence.expected_runs(lock)
    if len(expected) != 6 or len(result_paths) != 6 or len(capture_dirs) != 6:
        raise runner.ExecutionBlocked(
            "paired v3 needs exactly six frozen results and captures"
        )
    by_run = {}
    for result_path, capture_dir in zip(result_paths, capture_dirs):
        result = read_json(result_path)
        validate_schema(result, "stage-evaluation-result.v3.schema.json")
        _check_result_scores(result)
        record = runner.verify_capture(capture_dir, verify_runtime=True)
        binding = result.get("formal_capture", {})
        run_id = record["run_id"]
        last = len(record["attempts"])
        answer_sha = runner.sha(
            (Path(capture_dir) / f"attempt-{last:02d}.final.txt").read_bytes()
        )
        transcript_sha = runner.sha(
            (Path(capture_dir) / f"attempt-{last:02d}.jsonl").read_bytes()
        )
        if run_id in by_run:
            raise runner.ExecutionBlocked("paired v3 has duplicate run")
        if (
            record.get("lock_kind") != "Stage1ABPublicLockV3"
            or record.get("status") != "complete"
            or (
                record.get("condition") == "treatment"
                and not record.get("stage1_receipt")
            )
            or record.get("stage1_receipt_error")
            or binding.get("run_id") != run_id
            or binding.get("condition") != record.get("condition")
            or binding.get("repeat") != record.get("repeat")
            or binding.get("series_id") != record.get("series_id")
            or binding.get("lock_sha256") != runner.sha(lock_raw)
            or binding.get("capture_run_sha256")
            != runner.sha((Path(capture_dir) / "run.json").read_bytes())
            or result.get("rubric_sha256") != lock.get("rubric_sha256")
            or result.get("spec_sha256") != lock.get("spec_sha256")
            or result.get("evaluator_identity", {}).get("evaluator_bundle_sha256")
            != lock.get("evaluator_bundle_sha256")
            or result.get("evaluator_identity", {}).get("model")
            != lock.get("evaluator_runtime", {}).get("model")
            or result.get("evaluator_identity", {}).get("reasoning")
            != lock.get("evaluator_runtime", {}).get("reasoning")
            or result.get("evaluator_identity", {}).get("codex_runtime_sha256")
            != lock.get("codex_runtime_sha256")
            or result.get("evaluator_identity", {}).get("codex_executable_sha256")
            != lock.get("codex_executable_sha256")
            or result.get("evaluator_identity", {}).get("research_hub_package_sha256")
            != lock.get("research_hub_package_sha256")
            or result.get("evaluator_identity", {}).get("evaluator_code_sha256")
            != lock.get("evaluator_code_sha256")
            or result.get("evaluator_identity", {}).get("research_hub_commit")
            != lock.get("research_hub_sha")
            or result.get("evidence_mode") != "evidence-audited"
            or result.get("subject_sha256") != binding.get("answer_sha256")
            or binding.get("answer_sha256") != answer_sha
            or binding.get("transcript_sha256") != transcript_sha
        ):
            raise runner.ExecutionBlocked(
                "paired v3 result is not bound to its subject"
            )
        _verify_result_bundle(
            result_path, result, lock, background, background_path, capture_dir, last
        )
        by_run[run_id] = {
            "result": result,
            "capture": record,
            "result_sha256": runner.sha(Path(result_path).read_bytes()),
        }
    if set(by_run) != {row["run_id"] for row in expected}:
        raise runner.ExecutionBlocked("paired v3 results differ from frozen run IDs")
    if len({entry["capture"]["series_id"] for entry in by_run.values()}) != 1:
        raise runner.ExecutionBlocked("paired v3 mixes execution series")
    return _paired_decision(lock, by_run, runner.sha(lock_raw), output)


def _paired_decision(lock, by_run, lock_sha256, output):
    """One unchanged scientific decision rule shared by evaluator versions."""
    pairs = []
    has_unknown = False
    has_added_major = False
    for repeat in range(1, 4):
        row = lock["paired_repeats"][repeat - 1]
        a = by_run[row["baseline"]["run_id"]]["result"]
        b = by_run[row["treatment"]["run_id"]]["result"]
        a_issues = a.get("major_issues", [])
        b_issues = b.get("major_issues", [])
        if any(item.get("status") == "confirmed" for item in b_issues):
            has_added_major = True
        if any(item.get("status") == "unresolved" for item in a_issues + b_issues):
            has_unknown = True
        dimensions = {}
        for metric in ("P1", "P2", "P3"):
            left = a["dimensions"][metric]
            right = b["dimensions"][metric]
            if any(
                value["unknown_count"] or value["observed_score_100"] is None
                for value in (left, right)
            ):
                has_unknown = True
                delta = None
            else:
                delta = round(
                    right["observed_score_100"] - left["observed_score_100"], 2
                )
            dimensions[metric] = {
                "A": left["observed_score_100"],
                "B": right["observed_score_100"],
                "delta": delta,
                "A_assessed_fraction": left["assessed_fraction"],
                "B_assessed_fraction": right["assessed_fraction"],
            }
        if (
            a["evaluator_status"] != "complete"
            or b["evaluator_status"] != "complete"
            or a["subject_status"] != "complete"
            or b["subject_status"] != "complete"
            or a["extraction_status"] != "complete"
            or b["extraction_status"] != "complete"
            or a["scientific_readiness_status"] == "inconclusive"
            or b["scientific_readiness_status"] == "inconclusive"
        ):
            has_unknown = True
        pairs.append({"repeat": repeat, "dimensions": dimensions})
    deltas = {
        metric: [pair["dimensions"][metric]["delta"] for pair in pairs]
        for metric in ("P1", "P2", "P3")
    }
    if has_added_major:
        decision = "not-improved"
    elif has_unknown or any(
        value is None for values in deltas.values() for value in values
    ):
        decision = "inconclusive"
    elif any(value < 0 for values in deltas.values() for value in values):
        decision = "not-improved"
    elif all(
        sum(value > 0 for value in deltas[metric]) >= 2 for metric in ("P2", "P3")
    ):
        decision = "improved"
    else:
        decision = "not-improved"
    summary = {
        metric: {
            "pair_deltas": values,
            "median_delta": statistics.median(values)
            if all(value is not None for value in values)
            else None,
            "range": [min(values), max(values)]
            if all(value is not None for value in values)
            else None,
        }
        for metric, values in deltas.items()
    }
    value = {
        "kind": "Stage1ABGeneralDecisionV3",
        "schema_version": "3.0.0",
        "lock_sha256": lock_sha256,
        "decision": decision,
        "rule": "P2/P3 each >=2 positive and 0 negative; P1 0 negative; B 0 confirmed major; unknown inconclusive",
        "pairs": pairs,
        "summary": summary,
        "added_major_error_gate": has_added_major,
        "unknown_gate": has_unknown,
        "no_composite_total": True,
        "external_claim_ready": False,
        "input_result_sha256": {
            run_id: item["result_sha256"] for run_id, item in by_run.items()
        },
    }
    runner.write_json(output, value)
    return value
