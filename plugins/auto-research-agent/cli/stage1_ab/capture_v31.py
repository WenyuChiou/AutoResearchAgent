"""Collect every recorded subject attempt, including zero-file workspaces."""

from pathlib import Path

from stage1_eval.adapter import adapt_subject
from stage1_eval.common import EvaluationError, canonical, sha
from stage1_eval.formal import attach_workspace

from . import runner


def capture_subject(capture_dir, *, verify_runtime=True):
    root = Path(capture_dir).resolve()
    record = runner.verify_capture(root, verify_runtime=verify_runtime)
    attempts = record["attempts"]
    if record.get("status") != "complete" or not attempts:
        raise EvaluationError("subject capture is not complete")
    final_name = f"attempt-{len(attempts):02d}.final.txt"
    final_path = root / final_name
    if not final_path.is_file() or attempts[-1]["files"].get(final_name) != sha(
        final_path.read_bytes()
    ):
        raise EvaluationError("final answer is absent from its capture byte manifest")
    subject = adapt_subject(final_path)
    bindings = []
    for number, attempt in enumerate(attempts, 1):
        name = f"attempt-{number:02d}.jsonl"
        path = root / name
        raw = path.read_bytes()
        if attempt["files"].get(name) != sha(raw):
            raise EvaluationError("native attempt transcript binding changed")
        observation = adapt_subject(
            final_path,
            path,
            max_trace_bytes=2_000_000,
        )
        for key, value in observation["evidence"].items():
            if key == "answer":
                continue
            subject["evidence"][f"attempt-{number:02d}-{key}"] = {
                **value,
                "artifact_path": name,
                "source_version": sha(raw),
                "locator": key,
            }
        bindings.append({"attempt": number, "path": name, "sha256": sha(raw)})
    snapshot = root / "workspace" / f"{len(attempts):02d}"
    prefix = f"workspace/{len(attempts):02d}/"
    recorded = [name for name in attempts[-1]["files"] if name.startswith(prefix)]
    if not snapshot.is_dir() and recorded:
        raise EvaluationError("recorded workspace files missing")
    # An absent empty directory is valid only when no files were recorded.
    attach_workspace(subject, {"snapshot_path": str(snapshot)})
    inventory = {
        "attempts": bindings,
        "empty_workspace": not recorded,
        "run_sha256": sha((root / "run.json").read_bytes()),
    }
    text = canonical(inventory).decode("utf-8")
    subject["evidence"]["attempt-inventory"] = {
        "text": text,
        "sha256": sha(text.encode()),
        "origin": "evaluator-mechanical-inventory",
    }
    return subject, record
