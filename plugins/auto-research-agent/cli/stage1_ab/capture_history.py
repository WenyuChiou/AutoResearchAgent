"""Read all saved attempt snapshots; never invent an unsaved file history."""

import argparse
import json
from pathlib import Path, PurePosixPath

from stage1_eval.adapter import adapt_subject
from stage1_eval.common import EvaluationError, canonical, read_json, sha, write_json

from . import runner

KIND = "Stage1SavedCaptureHistory.v1"


def _snapshot(root, attempt, number):
    prefix = f"workspace/{number:02d}/"
    expected = {}
    for name, digest in attempt["files"].items():
        if not name.startswith("workspace/"):
            continue
        path = PurePosixPath(name)
        if (
            not name.startswith(prefix)
            or "\\" in name
            or any(part in {".", ".."} or ":" in part for part in name.split("/"))
            or path.as_posix() != name
        ):
            raise EvaluationError("snapshot path or attempt binding is invalid")
        expected[name[len(prefix) :]] = digest
    directory = root / "workspace" / f"{number:02d}"
    if directory.is_symlink() or (root / "workspace").is_symlink():
        raise EvaluationError("snapshot root contains a symlink")
    actual = {}
    for path in directory.rglob("*"):
        if path.is_symlink() or not path.resolve().is_relative_to(directory.resolve()):
            raise EvaluationError("snapshot contains a symlink or escaped path")
        if path.is_file():
            actual[path.relative_to(directory).as_posix()] = path
    if set(actual) != set(expected):
        raise EvaluationError("saved snapshot inventory differs from recorded files")
    result = []
    for name in sorted(expected):
        raw = actual[name].read_bytes()
        if sha(raw) != expected[name]:
            raise EvaluationError("saved snapshot bytes changed: " + name)
        result.append((name, raw))
    return result


def _availability(subject):
    """Report literal field presence, not guessed backend or tool execution time."""
    fields = {
        "action_id": ("item", "id"),
        "item_type": ("item", "type"),
        "command": ("item", "command"),
        "arguments": ("item", "arguments"),
        "action": ("item", "action"),
        "aggregated_output": ("item", "aggregated_output"),
        "stdout": ("item", "stdout"),
        "stderr": ("item", "stderr"),
        "exit_code": ("item", "exit_code"),
        "status": ("item", "status"),
        "native_timestamp": ("timestamp",),
        "backend": ("item", "backend"),
        "result_count": ("item", "result_count"),
    }
    rows = []
    for key, row in subject["evidence"].items():
        if row["origin"] != "subject-native-trace":
            continue
        event = json.loads(row["text"])
        observed, paths = {}, {}
        for field, parts in fields.items():
            value = event
            for part in parts:
                value = value.get(part) if isinstance(value, dict) else None
            observed[field] = value
            paths[field] = ".".join(parts) if value is not None else None
        rows.append(
            {
                "evidence_id": key,
                "artifact_sha256": row["sha256"],
                "values": observed,
                "field_paths": paths,
            }
        )
    return {
        "kind": "Stage1NativeFieldAvailability.v1",
        "schema_version": "1.0.0",
        "events": rows,
        "scope": "Literal fields only. Null is unavailable; raw events remain authoritative.",
        "tool_time_semantics": "A native timestamp is preserved as supplied, not inferred start/end time.",
    }


def capture_saved_history(capture_dir, *, verify_runtime=True):
    """The same read-only adapter accepts A and B without a condition branch."""
    root = Path(capture_dir).resolve()
    # Containment precedes the shared verifier's file reads, not only attachment.
    raw_record = read_json(root / "run.json")
    if not isinstance(raw_record, dict):
        raise EvaluationError("capture record is not an object")
    for attempt in raw_record.get("attempts", []):
        for name in attempt["files"]:
            path = PurePosixPath(name)
            if (
                path.is_absolute()
                or "\\" in name
                or path.as_posix() != name
                or any(part in {".", ".."} or ":" in part for part in name.split("/"))
            ):
                raise EvaluationError("capture contains an unsafe relative path")
    record = runner.verify_capture(root, verify_runtime=verify_runtime)
    attempts = record["attempts"]
    if record.get("status") != "complete" or not attempts:
        raise EvaluationError("subject capture is not complete")
    final_name = f"attempt-{len(attempts):02d}.final.txt"
    final_path = root / final_name
    if attempts[-1]["files"].get(final_name) != sha(final_path.read_bytes()):
        raise EvaluationError("final answer binding changed")
    subject = adapt_subject(final_path)
    history, previous = [], {}
    for number, attempt in enumerate(attempts, 1):
        name = f"attempt-{number:02d}.jsonl"
        transcript = root / name
        raw = transcript.read_bytes()
        if attempt["files"].get(name) != sha(raw):
            raise EvaluationError("native attempt transcript binding changed")
        observation = adapt_subject(final_path, transcript, max_trace_bytes=2_000_000)
        for key, value in observation["evidence"].items():
            if key != "answer":
                subject["evidence"][f"attempt-{number:02d}-{key}"] = {
                    **value,
                    "artifact_path": name,
                    "source_version": sha(raw),
                    "locator": key,
                }
        current, files = {}, []
        for ordinal, (relative, content) in enumerate(
            _snapshot(root, attempt, number), 1
        ):
            digest = sha(content)
            current[relative] = digest
            key = f"attempt-{number:02d}-workspace-{ordinal}"
            try:
                text = content.decode("utf-8")
            except UnicodeError:
                text = None
            files.append(
                {
                    "path": relative,
                    "sha256": digest,
                    "bytes": len(content),
                    "change": "created"
                    if relative not in previous
                    else "unchanged"
                    if previous[relative] == digest
                    else "modified",
                    "evidence_id": key if text is not None else None,
                    "text_status": "available" if text is not None else "non-utf8",
                }
            )
            if text is not None:
                # Only final, explicitly delivered files enter the content inventory.
                # Earlier versions remain process evidence, including deleted files.
                delivered = (
                    PurePosixPath(relative).suffix.lower()
                    in {".md", ".txt", ".json", ".csv"}
                    and number == len(attempts)
                    and (
                        relative in subject["evidence"]["answer"]["text"]
                        or PurePosixPath(relative).name
                        in subject["evidence"]["answer"]["text"]
                    )
                )
                subject["evidence"][key] = {
                    "text": text,
                    "sha256": digest,
                    "origin": "subject-delivered-artifact"
                    if delivered
                    else "subject-captured-process-artifact",
                    "artifact_path": f"workspace/{number:02d}/{relative}",
                    "source_version": "sha256:" + digest,
                    "locator": {"attempt": number, "start": 0, "end": len(text)},
                }
        history.append(
            {
                "attempt": number,
                "observed_at": attempt.get("ended_at"),
                "timestamp_semantics": "Attempt end observation, not file-write or tool time",
                "files": files,
                "deleted_since_previous_snapshot": sorted(set(previous) - set(current)),
                "transcript_path": name,
                "transcript_sha256": sha(raw),
            }
        )
        previous = current
    manifest = {
        "kind": KIND,
        "schema_version": "1.0.0",
        "snapshots": history,
        "run_sha256": sha((root / "run.json").read_bytes()),
        "between_snapshot_history": "unavailable; no unsaved versions reconstructed",
    }
    text = canonical(manifest).decode("utf-8")
    subject["evidence"]["saved-workspace-history"] = {
        "text": text,
        "sha256": sha(text.encode()),
        "origin": "subject-captured-process-artifact",
    }
    return subject, manifest, _availability(subject)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("capture", type=Path)
    parser.add_argument("output", type=Path)
    args = parser.parse_args(argv)
    try:
        subject, history, availability = capture_saved_history(args.capture)
        args.output.mkdir(parents=True, exist_ok=False)
        for name, value in (
            ("subject.json", subject),
            ("workspace-history.json", history),
            ("native-field-availability.json", availability),
        ):
            write_json(args.output / name, value)
        print(
            json.dumps({"status": "captured", "snapshots": len(history["snapshots"])})
        )
        return 0
    except (
        EvaluationError,
        runner.ExecutionBlocked,
        OSError,
        KeyError,
        TypeError,
        ValueError,
    ) as error:
        print(json.dumps({"status": "evaluator-error", "error": str(error)}))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
