"""Passive native-output observations; receipt time is never tool duration."""

import json
import subprocess
import threading
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath

from stage1_eval.common import EvaluationError, canonical, read_json, sha

POLICY = {
    "id": "stage1-passive-observer-v1",
    "snapshot_triggers": ["before-start", "item.completed", "after-exit"],
    "timestamp_semantics": "observer receipt time, not tool start/end or file-write time",
    "history_limit": "Files between observations may change; unsampled versions are unavailable.",
    "subject_interventions": False,
}


def binding():
    return {"policy": POLICY, "implementation_sha256": sha(Path(__file__).read_bytes())}


def _snapshot(workspace, root, read_user=None):
    if read_user is not None:
        import base64
        from .vm_subject import call
        from .vm_common import safe_name

        observed = call(read_user, "snapshot", workspace=str(workspace))
        files = {}
        for name, encoded in observed["files"].items():
            safe_name(name)
            raw = base64.b64decode(encoded, validate=True)
            digest = sha(raw)
            blob = root / "blobs" / digest
            if blob.exists() and blob.read_bytes() != raw:
                raise EvaluationError("saved observer blob changed")
            blob.write_bytes(raw)
            files[name] = {"sha256": digest, "bytes": len(raw)}
        return {"files": files, "errors": observed["errors"]}

    files, errors = {}, []
    for path in sorted(workspace.rglob("*")):
        relative = path.relative_to(workspace).as_posix()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(workspace):
                raise OSError("symlink or escaped path")
            if not path.is_file():
                continue
            before = path.stat()
            raw = path.read_bytes()
            after = path.stat()
            if (before.st_size, before.st_mtime_ns) != (
                after.st_size,
                after.st_mtime_ns,
            ):
                raise OSError("file changed during observation")
            digest = sha(raw)
            blob = root / "blobs" / digest
            if not blob.exists():
                blob.write_bytes(raw)
            elif blob.read_bytes() != raw:
                raise OSError("saved observer blob changed")
            files[relative] = {"sha256": digest, "bytes": len(raw)}
        except OSError as error:
            errors.append({"path": relative, "error": str(error)})
    return {"files": files, "errors": errors}


def run_observed(
    command, *, input, env, cwd, output, process_options=None, read_user=None
):
    """Drain both pipes, save original bytes, and sample without subject prompts.

    Sampling cannot guarantee an atomic filesystem view or capture every write.
    Errors are retained and prevent complete observation, never a subject score.
    """
    workspace, root = Path(cwd).resolve(), Path(output).resolve()
    if root.is_relative_to(workspace):
        raise EvaluationError("observer output must be outside subject workspace")
    root.mkdir(parents=True, exist_ok=False)
    (root / "blobs").mkdir()
    observations = []

    def snapshot(trigger, line=None, raw=None):
        observations.append(
            {
                "trigger": trigger,
                "line": line,
                "event_sha256": sha(raw) if raw is not None else None,
                "observed_at": datetime.now(timezone.utc).isoformat(),
                **(
                    _snapshot(workspace, root, read_user=read_user)
                    if read_user is not None
                    else _snapshot(workspace, root)
                ),
            }
        )

    snapshot("before-start")
    errors = []
    with (
        (root / "stdout.bin").open("wb") as stdout,
        (root / "stderr.bin").open("wb") as stderr,
    ):
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            cwd=workspace,
            **(process_options or {}),
        )

        def read_stdout():
            try:
                for number, raw in enumerate(process.stdout, 1):
                    stdout.write(raw)
                    stdout.flush()
                    try:
                        event = json.loads(raw)
                    except ValueError:
                        continue
                    if (
                        isinstance(event, dict)
                        and event.get("type") == "item.completed"
                    ):
                        try:
                            snapshot("item.completed", number, raw)
                        except Exception as error:
                            errors.append({"stream": "snapshot", "error": str(error)})
            except Exception as error:
                errors.append({"stream": "stdout", "error": str(error)})

        def read_stderr():
            try:
                while raw := process.stderr.read(65536):
                    stderr.write(raw)
                    stderr.flush()
            except Exception as error:
                errors.append({"stream": "stderr", "error": str(error)})

        threads = [threading.Thread(target=f) for f in (read_stdout, read_stderr)]
        for thread in threads:
            thread.start()
        try:
            process.stdin.write(input)
            process.stdin.close()
        except BrokenPipeError:
            process.stdin.close()
        process.wait()
        for thread in threads:
            thread.join()
        process.stdout.close()
        process.stderr.close()
    snapshot("after-exit")
    manifest = {"binding": binding(), "observations": observations, "errors": errors}
    (root / "manifest.json").write_bytes(canonical(manifest))
    return subprocess.CompletedProcess(
        command,
        process.returncode,
        (root / "stdout.bin").read_bytes(),
        (root / "stderr.bin").read_bytes(),
    )


def verify_observation(root, transcript, expected_binding):
    """Rebuild the required event sequence and check every saved file version."""
    root = Path(root)
    if root.is_symlink() or any(
        p.is_symlink() or not p.resolve().is_relative_to(root.resolve())
        for p in root.rglob("*")
    ):
        raise EvaluationError("observer archive contains a symlink or escaped path")
    value = read_json(root / "manifest.json")
    if value["binding"] != expected_binding or expected_binding["policy"] != POLICY:
        raise EvaluationError("observer binding differs from frozen policy")
    if (root / "stdout.bin").read_bytes() != transcript:
        raise EvaluationError("observer transcript differs from native capture")
    expected = [("before-start", None, None)]
    for number, raw in enumerate(transcript.splitlines(keepends=True), 1):
        try:
            event = json.loads(raw)
        except ValueError:
            continue
        if isinstance(event, dict) and event.get("type") == "item.completed":
            expected.append(("item.completed", number, sha(raw)))
    expected.append(("after-exit", None, None))
    actual = [
        (r["trigger"], r["line"], r["event_sha256"]) for r in value["observations"]
    ]
    if actual != expected or value["errors"]:
        raise EvaluationError("observer events incomplete or stream failed")
    blobs = set()
    for row in value["observations"]:
        if row["errors"]:
            raise EvaluationError("observer workspace sampling failed")
        datetime.fromisoformat(row["observed_at"])
        for name, file in row["files"].items():
            path = PurePosixPath(name)
            digest = file["sha256"]
            if (
                path.is_absolute()
                or path.as_posix() != name
                or "\\" in name
                or any(p in {".", "..", ""} or ":" in p for p in name.split("/"))
                or len(digest) != 64
                or any(c not in "0123456789abcdef" for c in digest)
            ):
                raise EvaluationError("unsafe observer path or digest")
            raw = (root / "blobs" / digest).read_bytes()
            if sha(raw) != digest or len(raw) != file["bytes"]:
                raise EvaluationError("observer blob changed")
            blobs.add(digest)
    if {p.name for p in (root / "blobs").iterdir()} != blobs:
        raise EvaluationError("observer blob inventory changed")
    return value
