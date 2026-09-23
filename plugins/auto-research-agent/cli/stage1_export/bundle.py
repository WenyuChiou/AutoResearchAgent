"""Seal and replay known run files; unrelated source-directory files stay out."""

from pathlib import Path
from stage1_ledger.journal import (
    LedgerError,
    STREAMS,
    canonical,
    contained,
    decode,
    digest,
    write_new,
)
from stage1_ledger.store import Ledger
from stage1_ledger.validation import validate_run
from .contracts import check
from .derive import derive
from . import native


def source_state(root, *, verify_runtime=True):
    ledger = Ledger(root)
    report = validate_run(root, verify_runtime=verify_runtime)
    if not report["valid"]:
        raise LedgerError("invalid-export-source: " + "; ".join(report["errors"]))
    events = [row["payload"] for row in ledger.events()]
    checkpoints = [p for p in events if p["kind"] == "Checkpoint"]
    if not checkpoints or checkpoints[-1]["state_sha256"] != report["state_sha256"]:
        raise LedgerError("current-checkpoint-required")
    return ledger, report, events, checkpoints[-1]


def source_paths(events):
    return sorted(
        {
            "run_manifest.json",
            "stage_events.jsonl",
            "coverage_and_stop.md",
            *STREAMS.values(),
            *(p["ref"]["path"] for p in events if p["kind"] == "ArtifactStored"),
        }
    )


def manifest_for(data, ledger, report, checkpoint):
    result = dict(
        kind="Stage1ExportManifest",
        schema_version="1.0.0",
        exporter_version="1.0.0",
        source_run_id=ledger.manifest["research_run"]["run_id"],
        source_mode=ledger.manifest["mode"],
        source_state_sha256=report["state_sha256"],
        source_checkpoint_event_id=checkpoint["event_id"],
        source_journal_sha256=digest(data["source/stage_events.jsonl"]),
        evaluation_status="not-scored",
        files=[
            dict(path=name, bytes=len(raw), sha256=digest(raw))
            for name, raw in sorted(data.items())
        ],
    )
    if "native/capture.json" in data:
        result["native_capture_contract"] = native.CONTRACT
    return result


def export_run(root, output, *, native_capture=None):
    ledger, target = Ledger(root), Path(output).resolve()
    if target.is_relative_to(ledger.root):
        raise LedgerError("export-must-be-outside-source-run")
    # Same writer lock, but no automatic projection repair during read-only export.
    with ledger.writing(repair=False):
        ledger, report, events, checkpoint = source_state(ledger.root)
        inputs, efficiency = derive(
            ledger.manifest, events, report, checkpoint, ledger.read_ref
        )
        check(inputs)
        data = {
            "source/" + name: contained(ledger.root, name).read_bytes()
            for name in source_paths(events)
        }
        if native_capture is not None:
            data.update(native.read_capture(native_capture))
            data["native_usage.json"] = native.attach(data, efficiency, ledger, report)
        check(efficiency)
        data.update(
            {
                "metric_inputs.json": canonical(inputs) + b"\n",
                "efficiency.json": canonical(efficiency) + b"\n",
            }
        )
        manifest = manifest_for(data, ledger, report, checkpoint)
        check(manifest)
        target.mkdir(parents=True, exist_ok=False)
        for name, raw in data.items():
            path = contained(target, name)
            path.parent.mkdir(parents=True, exist_ok=True)
            write_new(path, raw)
        # A partial I/O failure has no completed export manifest and remains visible.
        write_new(target / "export_manifest.json", canonical(manifest) + b"\n")
    return validate_export(target)


def _validate_export(root, *, verify_runtime):
    root = Path(root).resolve()
    try:
        manifest = decode(
            contained(root, "export_manifest.json").read_bytes(), "export manifest"
        )
        check(manifest)
        entries = manifest["files"]
        paths = [entry["path"] for entry in entries]
        if len(paths) != len(set(paths)):
            raise LedgerError("duplicate-export-path")
        actual = list(root.rglob("*"))
        if any(p.is_symlink() for p in actual):
            raise LedgerError("export-symlink")
        if {p.relative_to(root).as_posix() for p in actual if p.is_file()} != set(
            paths
        ) | {"export_manifest.json"}:
            raise LedgerError("export-file-set")
        data = {}
        for entry in entries:
            raw = contained(root, entry["path"]).read_bytes()
            if len(raw) != entry["bytes"] or digest(raw) != entry["sha256"]:
                raise LedgerError("export-file-hash: " + entry["path"])
            data[entry["path"]] = raw
        ledger, report, events, checkpoint = source_state(
            root / "source", verify_runtime=verify_runtime
        )
        expected_paths = {"source/" + p for p in source_paths(events)} | {
            "metric_inputs.json",
            "efficiency.json",
        }
        if "native_capture_contract" in manifest:
            expected_paths |= native.FILES
        if set(paths) != expected_paths:
            raise LedgerError("export-source-file-set")
        inputs, efficiency = derive(
            ledger.manifest, events, report, checkpoint, ledger.read_ref
        )
        if "native_capture_contract" in manifest:
            if data["native_usage.json"] != native.attach(
                data, efficiency, ledger, report
            ):
                raise LedgerError("native-usage-replay")
        for name, value in [
            ("metric_inputs.json", inputs),
            ("efficiency.json", efficiency),
        ]:
            check(decode(data[name], name))
            if data[name] != canonical(value) + b"\n":
                raise LedgerError("metric-input-replay: " + name)
        if manifest != manifest_for(data, ledger, report, checkpoint):
            raise LedgerError("export-manifest-replay")
        return dict(
            valid=True,
            errors=[],
            source_state_sha256=report["state_sha256"],
            evaluation_status="not-scored",
        )
    except (LedgerError, OSError, KeyError, TypeError, ValueError) as error:
        return dict(valid=False, errors=[str(error)], evaluation_status="not-scored")


def validate_export(root):
    """Strict source and export replay, including the original host runtime."""
    return _validate_export(root, verify_runtime=True)


def replay_export_artifacts(root):
    """Check saved source and metrics on another host without executing a CLI."""
    report = _validate_export(root, verify_runtime=False)
    return dict(
        kind="Stage1ExportArtifactReplay",
        schema_version="1.0.0",
        scope="saved-artifacts-only",
        artifact_valid=report["valid"],
        errors=report["errors"],
        source_state_sha256=report.get("source_state_sha256"),
        runtime_attestation="not-rechecked",
        evaluation_status="not-scored",
    )
