"""Capture newly emitted native traces for already-authenticated v3.1 calls."""

from dataclasses import dataclass
from hashlib import sha256
import os
from pathlib import Path
import re

from stage2_common import Stage2Error, canonical_hash

from .judge_trace_replay import _path
from .no_tool_trace_evidence import _attempts, verify_no_tool_trace_evidence
from .no_execution_trace_evidence import verify_no_execution_trace_evidence
from .trace_files import MAX_FILE_BYTES, MAX_FILES, MAX_TOTAL_BYTES
from .trace_observation import inspect_native_trace


_TOKEN_MARKER = object()


def _fail(reason):
    raise Stage2Error("no-tool-trace-capture-" + reason)


class NoToolTraceCaptureFailure(Stage2Error):
    """Preserve original seal receipts when a later capture check fails."""

    def __init__(self, cause, receipts, completed):
        super().__init__(f"no-tool-trace-capture-incomplete: {cause}")
        self.retained_seal_receipts = dict(receipts)
        self.completed_units = dict(completed)


@dataclass(frozen=True)
class _CaptureToken:
    output: Path
    telemetry: Path
    telemetry_identity: tuple[int, int]
    existing_names: tuple[str, ...]
    marker: object


def _fresh(path):
    path = Path(os.path.abspath(os.fspath(path)))
    _path(path.parent, directory=True)
    if os.path.lexists(path):
        _fail("output-already-exists")
    return path


def _children(root):
    try:
        return tuple(sorted(item.name for item in root.iterdir()))
    except OSError as error:
        raise Stage2Error("no-tool-trace-capture-telemetry-read-failed") from error


def begin_no_tool_trace_capture(output_dir, telemetry_root):
    """Record a no-write boundary before the authentic caller dispatches."""
    output = _fresh(output_dir)
    telemetry = _path(telemetry_root, directory=True)
    status = os.stat(telemetry)
    return _CaptureToken(
        output,
        telemetry,
        (status.st_dev, status.st_ino),
        _children(telemetry),
        _TOKEN_MARKER,
    )


def _bounded_bytes(path):
    safe = _path(path)
    if safe.stat().st_size > MAX_FILE_BYTES:
        _fail("trace-size-limit")
    with safe.open("rb") as stream:
        raw = stream.read(MAX_FILE_BYTES + 1)
    if len(raw) > MAX_FILE_BYTES:
        _fail("trace-size-limit")
    return raw


def _bounded_entries(root):
    pending, count = [root], 0
    while pending:
        with os.scandir(pending.pop()) as entries:
            for entry in entries:
                count += 1
                if count > MAX_FILES * 2:
                    _fail("trace-entry-limit")
                path = Path(entry.path)
                yield path
                if entry.is_dir(follow_symlinks=False):
                    pending.append(path)


def _inventory(root):
    files, total = {}, 0
    for path in _bounded_entries(root):
        if path.is_dir():
            _path(path, directory=True)
            continue
        if len(files) >= MAX_FILES:
            _fail("trace-inventory-invalid")
        raw = _bounded_bytes(path)
        total += len(raw)
        if len(raw) > MAX_FILE_BYTES or total > MAX_TOTAL_BYTES:
            _fail("trace-size-limit")
        files[path.relative_to(root).as_posix()] = sha256(raw).hexdigest()
    if not files:
        _fail("trace-inventory-empty")
    return files


def _write_new(path, raw):
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as stream:
            stream.write(raw)
    except FileExistsError as error:
        raise Stage2Error("no-tool-trace-capture-refusing-overwrite") from error


def _copy_trace(source, target, inventory):
    for relative in sorted(inventory):
        source_path = _path(source / relative)
        raw = _bounded_bytes(source_path)
        if sha256(raw).hexdigest() != inventory[relative]:
            _fail("original-trace-changed")
        _write_new(target / relative, raw)
    if _inventory(target) != inventory:
        _fail("copied-trace-mismatch")


def _seal(provenance, inventories):
    return {
        "kind": "Stage2NoToolTraceSeal",
        "schema_version": "1.0.0",
        "request_fingerprint_sha256": provenance["request_fingerprint_sha256"],
        "attempt_record_sha256": provenance["attempt_record_sha256"],
        "stdout_sha256": provenance["stdout_sha256"],
        "traces": inventories,
    }


def _canonical(value):
    import json

    return (
        json.dumps(
            value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
        ).encode()
        + b"\n"
    )


def _finish_trace_capture(
    token, authenticated_provenances, *, expected_config, execution_policy
):
    """Copy and seal only traces created after ``begin``; never dispatch work."""
    if execution_policy not in {"no-offered-tools-v1", "no-executed-tools-v1"}:
        _fail("execution-policy-invalid")
    if not isinstance(token, _CaptureToken) or token.marker is not _TOKEN_MARKER:
        _fail("token-invalid")
    output = _fresh(token.output)
    telemetry = _path(token.telemetry, directory=True)
    status = os.stat(telemetry)
    if (status.st_dev, status.st_ino) != token.telemetry_identity:
        _fail("telemetry-replaced")
    if not isinstance(authenticated_provenances, dict) or not authenticated_provenances:
        _fail("provenance-map-invalid")
    units, wanted, portable_names = {}, {}, set()
    for unit, provenance in sorted(authenticated_provenances.items()):
        if (
            not isinstance(unit, str)
            or not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]*", unit)
            or unit.endswith(".")
        ):
            _fail("unit-name-invalid")
        name = unit.casefold()
        base = name.split(".", 1)[0]
        if base in {"con", "prn", "aux", "nul"} or (
            len(base) == 4 and base[:3] in {"com", "lpt"} and base[3].isdigit()
        ):
            _fail("unit-name-invalid")
        if name in portable_names:
            _fail("unit-directory-alias")
        portable_names.add(name)
        _, attempts = _attempts(provenance, expected_config)
        roots = {root for _, root in attempts}
        if len(roots) != len(attempts) or roots & set(wanted):
            _fail("attempt-root-duplicate")
        units[unit] = (provenance, roots)
        wanted.update({root: unit for root in roots})
    current = set(_children(telemetry))
    new_names = current - set(token.existing_names)
    if not new_names:
        _fail("new-trace-missing")
    observed = {}
    for name in sorted(new_names):
        if not re.fullmatch(r"trace-[A-Za-z0-9_.-]+", name):
            _fail("unexpected-new-telemetry-child")
        source = _path(telemetry / name, directory=True)
        inventory = _inventory(source)
        observation = inspect_native_trace(source, inventory, canonical_hash(inventory))
        root = observation.get("root_thread_id")
        if root not in wanted or root in observed:
            _fail("foreign-or-duplicate-new-root")
        observed[root] = (name, source, inventory)
    if set(observed) != set(wanted):
        _fail("attempt-trace-set-mismatch")
    output.mkdir()
    evidence = output / "native-trace-evidence"
    results, receipts = {}, {}
    unit_roots = [evidence / unit for unit in units]
    if len(set(unit_roots)) != len(units) or any(
        path.parent != evidence for path in unit_roots
    ):
        _fail("unit-directory-overlap")
    try:
        for unit, (provenance, roots) in units.items():
            unit_root, inventories = evidence / unit, {}
            trace_root = unit_root / "traces"
            for root in roots:
                name, source, inventory = observed[root]
                _copy_trace(source, trace_root / name, inventory)
                inventories[name] = inventory
            seal_path = unit_root / "seal.json"
            seal_bytes = _canonical(_seal(provenance, inventories))
            _write_new(seal_path, seal_bytes)
            seal_sha = sha256(seal_bytes).hexdigest()
            receipts[unit] = {
                "seal_path": str(seal_path),
                "seal_sha256": seal_sha,
                "trace_root": str(trace_root),
            }
            verifier = (
                verify_no_tool_trace_evidence
                if execution_policy == "no-offered-tools-v1"
                else verify_no_execution_trace_evidence
            )
            proof = verifier(
                provenance,
                trace_root,
                seal_path,
                seal_sha,
                expected_config=expected_config,
            )
            results[unit] = {**receipts[unit], "proof": proof}
    except BaseException as error:
        raise NoToolTraceCaptureFailure(error, receipts, results) from error
    return {
        "kind": "Stage2NoToolTraceCapture"
        if execution_policy == "no-offered-tools-v1"
        else "Stage2NoExecutionTraceCapture",
        "schema_version": "1.0.0",
        "units": results,
        "new_model_calls": 0,
        "new_tool_calls": 0,
        "resume_action": "capture-finished-no-execution",
    }


def finish_no_tool_trace_capture(token, authenticated_provenances, *, expected_config):
    """Keep the original empty offered-tool requirement unchanged."""
    return _finish_trace_capture(
        token,
        authenticated_provenances,
        expected_config=expected_config,
        execution_policy="no-offered-tools-v1",
    )


def finish_no_execution_trace_capture(
    token, authenticated_provenances, *, expected_config
):
    """Capture explicit zero-action evidence; retain offered native tools."""
    return _finish_trace_capture(
        token,
        authenticated_provenances,
        expected_config=expected_config,
        execution_policy="no-executed-tools-v1",
    )
