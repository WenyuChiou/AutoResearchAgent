"""Bind formal v3 scoring to pre-subject lock and native capture bytes."""

import json
import sys
from pathlib import Path

from stage1_ab import runner, sequence

from .common import EvaluationError, canonical, sha
from .runtime import verify_installed_from_commit


def capture_module_binding():
    from stage1_ab import capture_v31

    path = Path(capture_v31.__file__)
    return {"path": "capture-adapter-v31", "sha256": sha(path.read_bytes())}


def observe_capture_v31(capture, *, portable=False):
    from stage1_ab.capture_v31 import capture_subject

    return capture_subject(capture, verify_runtime=not portable)


def verify_binding_v31(args, spec, record, policy):
    """Keep subject dependency pins distinct from evaluator source tooling."""
    if args.execution_class == "repair-diagnostic":
        return {
            "diagnostic": True,
            "original_subject_lock_sha256": record["lock_sha256"],
            "evaluator_research_hub_sha": None,
        }
    if getattr(args, "portable_diagnostic", False):
        raise EvaluationError("portable capture replay cannot attest new execution")
    if not args.lock or not args.background:
        raise EvaluationError(
            "v3.1 live evaluation requires its pre-subject lock/background"
        )
    raw = Path(args.lock).read_bytes()
    lock = json.loads(raw)
    expected_class = "formal" if args.execution_class == "formal" else "pilot"
    if (
        lock.get("schema_version") != "3.1.0"
        or lock.get("kind") != "Stage1ABPublicLockV3"
        or lock.get("execution_class") != expected_class
        or lock.get("evaluator_execution_policy") != policy
        or lock.get("evaluator_bundle_sha256") != policy["evaluator_bundle_sha256"]
        or lock.get("spec_sha256") != sha(canonical(spec))
        or lock.get("task_sha256") != spec["task_sha256"]
        or lock.get("prompt_sha256") != sha(Path(args.task).read_bytes())
        or lock.get("rubric_sha256") != spec["rubric_sha256"]
        or lock.get("background_sha256") != sha(Path(args.background).read_bytes())
        or record.get("lock_sha256") != sha(raw)
        or record.get("lock_kind") != "Stage1ABPublicLockV3"
        or record.get("status") != "complete"
        or lock.get("evaluator_runtime")
        != {"model": args.model, "reasoning": args.reasoning}
        or runner.codex_runtime_sha(args.codex) != lock.get("codex_runtime_sha256")
    ):
        raise EvaluationError("v3.1 frozen evaluation binding changed")
    runs = {r["run_id"]: r for r in sequence.expected_runs(lock)}
    row = runs.get(record["run_id"])
    if not row or any(record.get(k) != row[k] for k in ("condition", "repeat")):
        raise EvaluationError("subject is outside v3.1 frozen run order")
    from stage1_brief.brief import validate_brief

    brief = lock.get("research_brief")
    validate_brief(brief, require_confirmed=True)
    if sha(canonical(brief)) != lock.get("research_brief_sha256"):
        raise EvaluationError("frozen ResearchBrief changed")
    dependency = verify_installed_from_commit(
        lock["evaluator_research_hub_repo_path"], lock["evaluator_research_hub_sha"]
    )
    if (
        dependency["python_source_sha256"] != lock.get("research_hub_package_sha256")
        or lock.get("hub_command_prefix") != [sys.executable, "-m", "research_hub"]
        or lock.get("hub_executable_sha256") != sha(Path(sys.executable).read_bytes())
        or lock.get("codex_executable_sha256") != sha(Path(args.codex).read_bytes())
        or lock.get("plugin_tree_sha256") != runner.tree_sha(runner.PLUGIN_ROOT)
        or args.mode != "evidence-audited"
    ):
        raise EvaluationError("evaluator research-hub package differs from its pin")
    verify_hub_receipts(
        json.loads(Path(args.background).read_bytes())["receipts"], lock
    )
    last = len(record["attempts"])
    root = Path(args.capture)
    return {
        "run_id": record["run_id"],
        "condition": record["condition"],
        "repeat": record["repeat"],
        "series_id": record["series_id"],
        "lock_sha256": sha(raw),
        "capture_run_sha256": sha((root / "run.json").read_bytes()),
        "answer_sha256": sha((root / f"attempt-{last:02d}.final.txt").read_bytes()),
        "transcript_sha256": sha((root / f"attempt-{last:02d}.jsonl").read_bytes()),
        "subject_research_hub_sha": lock["research_hub_sha"],
        "evaluator_research_hub_sha": lock["evaluator_research_hub_sha"],
        "hub_command_prefix": lock["hub_command_prefix"],
        "hub_executable_sha256": lock["hub_executable_sha256"],
        "research_hub_package_sha256": dependency["python_source_sha256"],
        "codex_runtime_sha256": lock["codex_runtime_sha256"],
    }


def verify_hub_receipts(receipts, binding):
    """All source calls must use the frozen installed research-hub runtime."""
    prefix = binding["hub_command_prefix"]
    for row in receipts:
        if (
            row.get("command", [])[:3] != prefix
            or row.get("executable_sha256") != binding["hub_executable_sha256"]
            or row.get("research_hub_package_sha256")
            != binding["research_hub_package_sha256"]
        ):
            raise EvaluationError(
                "source receipt used an unfrozen research-hub runtime"
            )


def bind_capture(args, spec, evaluator_bundle_sha):
    """Reject operator-selected answers or post-hoc evaluation settings."""
    if not args.lock or not args.capture:
        raise EvaluationError("formal v3 evaluation needs --lock and --capture")
    if args.mode != "evidence-audited" or args.resume_pilot or args.saved_extraction:
        raise EvaluationError("formal v3 requires fresh evidence-audited evaluation")
    if args.artifact or args.subject_status != "complete":
        raise EvaluationError(
            "formal v3 derives artifacts and status from native capture"
        )
    lock_raw = Path(args.lock).read_bytes()
    lock = json.loads(lock_raw)
    if (
        lock.get("kind") != "Stage1ABPublicLockV3"
        or lock.get("execution_class") != "formal"
    ):
        raise EvaluationError("formal evaluation needs a three-pair v3 lock")
    if len(lock.get("paired_repeats", [])) != 3:
        raise EvaluationError("formal v3 lock lacks three pairs")
    if (
        args.hub
        or not args.hub_command_json
        or json.loads(args.hub_command_json) != ["@python", "-m", "research_hub"]
    ):
        raise EvaluationError("formal v3 requires the frozen research-hub command")
    dependency = verify_installed_from_commit(
        lock.get("research_hub_repo_path"), lock.get("research_hub_sha")
    )
    expected_prefix = [sys.executable, "-m", "research_hub"]
    expected_executable_sha = sha(Path(sys.executable).read_bytes())
    if (
        lock.get("hub_command_prefix") != expected_prefix
        or lock.get("hub_executable_sha256") != expected_executable_sha
        or lock.get("research_hub_package_sha256") != dependency["python_source_sha256"]
    ):
        raise EvaluationError("formal v3 research-hub runtime differs from lock")
    try:
        record = runner.verify_capture(args.capture, verify_runtime=True)
        runs = {row["run_id"]: row for row in sequence.expected_runs(lock)}
    except (OSError, ValueError, KeyError) as exc:
        raise EvaluationError(f"native capture failed verification: {exc}") from exc
    if (
        record.get("status") != "complete"
        or record.get("lock_kind") != "Stage1ABPublicLockV3"
        or record.get("run_id") not in runs
    ):
        raise EvaluationError(
            "formal v3 subject is incomplete or outside frozen series"
        )
    row = runs[record["run_id"]]
    if (
        record.get("condition") != row["condition"]
        or record.get("repeat") != row["repeat"]
        or record.get("lock_sha256") != sha(lock_raw)
        or lock.get("task_sha256") != spec["task_sha256"]
        or lock.get("spec_sha256") != sha(canonical(spec))
        or lock.get("rubric_sha256") != spec["rubric_sha256"]
        or lock.get("topic_id") != spec["topic_id"]
        or lock.get("evaluator_bundle_sha256") != evaluator_bundle_sha
        or lock.get("evaluator_runtime")
        != {"model": args.model, "reasoning": args.reasoning}
        or runner.codex_runtime_sha(args.codex) != lock.get("codex_runtime_sha256")
        or not args.background
        or sha(Path(args.background).read_bytes()) != lock.get("background_sha256")
        or lock.get("prompt_sha256") != sha(Path(args.task).read_bytes())
        or record.get("profile_probe", {}).get("codex_version")
        != lock["runtime"]["app_version"]
    ):
        raise EvaluationError("formal v3 lock, topic, evaluator, or capture differs")
    capture = Path(args.capture).resolve()
    last = len(record["attempts"])
    answer = capture / f"attempt-{last:02d}.final.txt"
    transcript = capture / f"attempt-{last:02d}.jsonl"
    if (
        Path(args.answer).resolve() != answer
        or not args.transcript
        or Path(args.transcript).resolve() != transcript
        or answer.name not in record["attempts"][-1]["files"]
        or transcript.name not in record["attempts"][-1]["files"]
    ):
        raise EvaluationError(
            "formal v3 answer/trace must be the captured native files"
        )
    snapshot = capture / "workspace" / f"{last:02d}"
    if not snapshot.is_dir():
        raise EvaluationError("formal v3 capture lacks workspace snapshot")
    return {
        "run_id": record["run_id"],
        "condition": record["condition"],
        "repeat": record["repeat"],
        "series_id": record["series_id"],
        "lock_sha256": sha(lock_raw),
        "capture_run_sha256": sha((capture / "run.json").read_bytes()),
        "answer_sha256": sha(answer.read_bytes()),
        "transcript_sha256": sha(transcript.read_bytes()),
        "snapshot_path": str(snapshot),
        "research_hub_commit": lock["research_hub_sha"],
        "codex_runtime_sha256": lock["codex_runtime_sha256"],
        "hub_command_prefix": expected_prefix,
        "hub_executable_sha256": expected_executable_sha,
        "research_hub_package_sha256": dependency["python_source_sha256"],
    }


def attach_workspace(subject, binding):
    """Expose captured process files neutrally; keep complete byte inventory."""
    root = Path(binding["snapshot_path"])
    inventory = []
    visible_bytes = 0
    answer = subject["evidence"].get("answer", {}).get("text", "")
    for path in sorted(root.rglob("*")):
        if not path.is_file():
            continue
        raw = path.read_bytes()
        relative = path.relative_to(root).as_posix()
        inventory.append({"path": relative, "sha256": sha(raw), "bytes": len(raw)})
        if path.suffix.lower() not in {".md", ".txt", ".json", ".jsonl", ".csv"}:
            continue
        try:
            value = raw.decode("utf-8")
        except UnicodeError:
            continue
        delivered = path.suffix.lower() in {".md", ".txt", ".json", ".csv"} and (
            relative in answer or path.name in answer
        )
        if delivered:
            if len(raw) > 120_000:
                raise EvaluationError(
                    "captured delivered artifact exceeds lossless limit"
                )
            subject["evidence"][f"workspace-{len(inventory)}"] = {
                "text": value,
                "sha256": sha(raw),
                "origin": "subject-delivered-artifact",
            }
            continue
        if visible_bytes >= 160_000:
            continue
        excerpt = value[: min(6_000, 160_000 - visible_bytes)]
        visible_bytes += len(excerpt.encode("utf-8"))
        text = (
            f"Captured path: {relative}\nFull SHA-256: {sha(raw)}\n"
            f"Full bytes: {len(raw)}\nExcerpt truncated: {len(excerpt) < len(value)}\n"
            f"Excerpt:\n{excerpt}"
        )
        subject["evidence"][f"workspace-{len(inventory)}"] = {
            "text": text,
            "sha256": sha(text.encode("utf-8")),
            "origin": "subject-captured-process-artifact",
        }
    manifest = json.dumps(inventory, ensure_ascii=False, sort_keys=True)
    subject["evidence"]["workspace-inventory"] = {
        "text": manifest,
        "sha256": sha(manifest.encode("utf-8")),
        "origin": "subject-captured-process-artifact",
    }
    return subject
