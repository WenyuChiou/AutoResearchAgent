"""Bind formal v3 scoring to pre-subject lock and native capture bytes."""

import json
import sys
from pathlib import Path

from stage1_ab import runner, sequence

from .common import EvaluationError, canonical, sha
from .runtime import verify_installed_from_commit


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
