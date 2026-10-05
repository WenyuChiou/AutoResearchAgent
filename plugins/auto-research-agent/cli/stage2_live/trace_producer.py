"""Produce a receipt-bound native capture plus rollout trace bundle."""

from datetime import datetime
import hashlib
import os
from pathlib import Path
import stat

from stage2_common import canonical_hash

from . import native, native_policy, observation, trace_capture
from .trace_files import (
    MAX_FILE_BYTES,
    MAX_FILES,
    MAX_TOTAL_BYTES,
    _fail,
    _json,
    _regular,
    _require,
)
from .trace_handles import TraceRoot
from .trace_seal_io import SealDirectory


CONTROL = "producer.json"


def _telemetry(policy):
    _require(
        isinstance(policy, dict)
        and policy.get("kind") == native_policy.NAMED_POLICY_KIND
        and isinstance(policy.get("telemetry_path"), str),
        "producer-named-policy-required",
    )
    ambient = os.environ.get("CODEX_ROLLOUT_TRACE_ROOT")
    declared = policy["telemetry_path"]
    _require(
        isinstance(ambient, str)
        and ambient
        and Path(ambient).is_absolute()
        and Path(declared).is_absolute()
        and ambient == declared
        and str(trace_capture._absolute(ambient)) == ambient,
        "producer-telemetry-binding-mismatch",
    )
    root = Path(ambient)
    status = _regular(root, "producer-telemetry-root")
    _require(stat.S_ISDIR(status.st_mode), "producer-telemetry-root-invalid")
    return root


def _trace_root(root):
    names = set()
    with SealDirectory(root) as bound:
        with os.scandir(bound.target) as entries:
            for entry in entries:
                _require(len(names) < 2, "producer-telemetry-inventory-mismatch")
                names.add(entry.name)
    _require(
        "bundle" in names and len(names) == 2, "producer-telemetry-inventory-mismatch"
    )
    name = next(iter(names - {"bundle"}))
    _require(
        name.startswith("trace-") and name != "trace-", "producer-trace-name-invalid"
    )
    status = _regular(root / name, "producer-trace-root")
    _require(stat.S_ISDIR(status.st_mode), "producer-trace-root-invalid")
    return root / name


def _snapshot(root):
    receipt, total = {}, 0
    try:
        with TraceRoot(root) as anchored:
            names = anchored.entries(MAX_FILES)
            _require(
                {"manifest.json", "trace.jsonl"} <= set(names),
                "inventory-required-file-missing",
            )
            for name in sorted(names):
                with anchored.open_file(name) as stream:
                    before = os.fstat(stream.fileno())
                    _require(before.st_size <= MAX_FILE_BYTES, "file-size-limit")
                    _require(
                        total + before.st_size <= MAX_TOTAL_BYTES, "total-size-limit"
                    )
                    raw = stream.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                    _require(
                        (before.st_dev, before.st_ino, before.st_size)
                        == (after.st_dev, after.st_ino, after.st_size),
                        "bound-file-changed-during-read",
                    )
                _require(len(raw) <= MAX_FILE_BYTES, "file-size-limit")
                total += len(raw)
                receipt[name] = hashlib.sha256(raw).hexdigest()
            _require(
                set(anchored.entries(MAX_FILES)) == set(names), "inventory-changed"
            )
    except OSError as error:
        _fail(f"producer-trace-read-failed: {error}")
    return receipt, canonical_hash(receipt)


def _source_sha():
    return hashlib.sha256(Path(__file__).read_bytes()).hexdigest()


def _policy_preflight(args):
    request = _request(args)
    config = trace_capture._absolute(args["codex_home"]) / "config.toml"
    native_policy.named_policy_args(request, config.read_bytes(), args["capture_dir"])
    return request


def _request(args):
    return native._stable_request(
        native._request_binding(
            args["codex"],
            args["codex_home"],
            args["workspace"],
            native._prompt_bytes(args["prompt"]),
            args["model"],
            args["reasoning"],
            args["input_bindings"],
            args["config_bindings"],
            args["policy_bindings"],
        )
    )


def _time_bound(raw, capture):
    manifest = _json(raw, "manifest.json")
    started_ms = (
        manifest.get("started_at_unix_ms") if isinstance(manifest, dict) else None
    )
    _require(type(started_ms) is int, "producer-trace-time-invalid")
    try:
        low = datetime.fromisoformat(capture["started_at"]).timestamp() * 1000
        high = datetime.fromisoformat(capture["ended_at"]).timestamp() * 1000
    except (KeyError, TypeError, ValueError) as error:
        _fail(f"producer-capture-time-invalid: {error}")
    _require(low <= started_ms <= high, "producer-trace-time-outside-capture")


def _write(bundle, value):
    raw = trace_capture._manifest_bytes(value)
    with SealDirectory(bundle) as bound:
        bound.write(CONTROL, raw)
    return hashlib.sha256(raw).hexdigest()


def _capture_binding(capture):
    return {
        "status": capture.get("status"),
        "exit_code": capture.get("exit_code"),
        "capture_mode": capture.get("capture_mode"),
        "stable_request_binding": capture.get("stable_request_binding"),
        "workspace_start": capture.get("workspace_start"),
        "workspace_end": capture.get("workspace_end"),
        "started_at": capture.get("started_at"),
        "ended_at": capture.get("ended_at"),
        "root_thread_id": capture.get("event_summary", {}).get("thread_id"),
    }


def _record(capture, inventory, source, telemetry_root, trace=None):
    capture_synthetic = capture.get("capture_mode") == "injected-test-adapter"
    inventory_synthetic = inventory.get("evidence_class") == "synthetic-test-only"
    _require(
        capture_synthetic == inventory_synthetic, "producer-evidence-mode-mismatch"
    )
    status = "complete" if trace is not None else "failed"
    return {
        "kind": "Stage2ObservedNativeProducer",
        "schema_version": "1.0.0",
        "status": status,
        "evidence_class": "synthetic-test-only"
        if capture_synthetic
        else "host-observed-producer",
        "formal_ready": False,
        "telemetry_root": str(telemetry_root),
        "producer_source_sha256": source,
        "runtime_observation_receipt": inventory["record_sha256_receipt"],
        "native_capture_receipt": capture["record_sha256_receipt"],
        "capture": _capture_binding(capture),
        "trace": trace,
        "limitations": [
            "producer evidence remains non-formal",
            "all-role admission, pilot, and calibration are separate",
        ],
    }


def _observation_binding(inventory, request):
    profile = request.get("codex_profile_config")
    expected = {
        "runtime_sha256": request.get("codex_runtime_sha256"),
        "profile_config_sha256": profile.get("sha256") if profile else None,
        "workspace": request.get("workspace"),
        "codex_home": request.get("codex_home"),
        "thread_id": None,
    }
    _require(
        isinstance(inventory, dict)
        and canonical_hash(inventory.get("binding")) == canonical_hash(expected),
        "producer-observation-binding-mismatch",
    )


def _read(bundle, receipt):
    _require(
        isinstance(receipt, str) and len(receipt) == 64, "producer-receipt-invalid"
    )
    expected = {CONTROL, "inventory", "sealed"}
    names = set()
    with SealDirectory(bundle) as bound:
        with os.scandir(bound.target) as entries:
            for entry in entries:
                _require(
                    entry.name in expected
                    and entry.name not in names
                    and len(names) < 3,
                    "producer-bundle-inventory-mismatch",
                )
                names.add(entry.name)
        _require(names == expected, "producer-bundle-inventory-mismatch")
        status = bound.status(CONTROL)
        _require(
            stat.S_ISREG(status.st_mode) and status.st_size <= MAX_FILE_BYTES,
            "producer-control-invalid",
        )
        with bound.reader(CONTROL) as stream:
            before = os.fstat(stream.fileno())
            _require(
                (status.st_dev, status.st_ino, status.st_size)
                == (before.st_dev, before.st_ino, before.st_size),
                "producer-control-replaced",
            )
            raw = stream.read(MAX_FILE_BYTES + 1)
            after = os.fstat(stream.fileno())
    _require(
        (before.st_dev, before.st_ino, before.st_size)
        == (after.st_dev, after.st_ino, after.st_size)
        and len(raw) <= MAX_FILE_BYTES,
        "producer-control-changed",
    )
    _require(hashlib.sha256(raw).hexdigest() == receipt, "producer-receipt-mismatch")
    value = _json(raw, CONTROL)
    required = {
        "kind",
        "schema_version",
        "status",
        "evidence_class",
        "formal_ready",
        "telemetry_root",
        "producer_source_sha256",
        "runtime_observation_receipt",
        "native_capture_receipt",
        "capture",
        "trace",
        "limitations",
    }
    _require(
        isinstance(value, dict)
        and set(value) == required
        and value.get("kind") == "Stage2ObservedNativeProducer"
        and value.get("schema_version") == "1.0.0"
        and value.get("status") == "complete"
        and value.get("formal_ready") is False,
        "producer-schema-invalid",
    )
    return value


def _verify(args, root, receipt, *, allow_synthetic):
    bundle = root / "bundle"
    record = _read(bundle, receipt)
    _require(
        record["telemetry_root"] == str(root), "producer-telemetry-record-mismatch"
    )
    _require(
        record["producer_source_sha256"] == _source_sha(), "producer-source-changed"
    )
    _require(
        record["evidence_class"] in {"synthetic-test-only", "host-observed-producer"},
        "producer-evidence-class-invalid",
    )
    synthetic = record["evidence_class"] == "synthetic-test-only"
    _require(synthetic == allow_synthetic, "producer-synthetic-mode-mismatch")
    inventory = observation.verify_runtime_observation(
        bundle / "inventory",
        record["runtime_observation_receipt"],
        allow_synthetic=synthetic,
    )
    current_request = _request(args)
    _observation_binding(inventory, current_request)
    capture, _ = native.verify_capture(
        args["capture_dir"],
        record["native_capture_receipt"],
        allow_injected_test_capture=synthetic,
    )
    _require(
        canonical_hash(record["capture"]) == canonical_hash(_capture_binding(capture)),
        "producer-capture-binding-mismatch",
    )
    _require(
        capture.get("kind") == "Stage2NativeCapture"
        and capture.get("status") == "complete"
        and capture.get("cost")
        == {
            "amount": None,
            "currency": None,
            "state": "unknown-not-reported-by-codex-cli",
        }
        and inventory.get("evidence_class")
        == ("synthetic-test-only" if synthetic else "host-app-server-observation")
        and capture.get("evidence_class")
        == ("synthetic-test-only" if synthetic else "host-native-capture"),
        "producer-evidence-binding-invalid",
    )
    _require(
        canonical_hash(capture["stable_request_binding"])
        == canonical_hash(current_request),
        "producer-current-binding-changed",
    )
    _require(
        capture["workspace_end"] == native._path_binding(args["workspace"]),
        "producer-workspace-changed",
    )
    trace = record["trace"]
    _require(
        isinstance(trace, dict)
        and set(trace) == {"root", "inventory", "receipt_sha256", "seal_receipt"},
        "producer-trace-binding-invalid",
    )
    source = _trace_root(root)
    _require(source.name == trace["root"], "producer-trace-root-changed")
    inventory, digest = _snapshot(source)
    _require(
        inventory == trace["inventory"] and digest == trace["receipt_sha256"],
        "producer-trace-binding-changed",
    )
    sealed = trace_capture.verify_trace_capture(
        bundle / "sealed",
        trace["seal_receipt"],
        args["capture_dir"],
        record["native_capture_receipt"],
    )
    with TraceRoot(source) as anchored, anchored.open_file("manifest.json") as stream:
        _time_bound(stream.read(MAX_FILE_BYTES + 1), capture)
    _require(
        sealed["capture"]["root_thread_id"] == record["capture"]["root_thread_id"]
        and capture["stable_request_binding"]["model"]
        == sealed["capture"]["requested_model"],
        "producer-seal-binding-mismatch",
    )
    return {
        **record,
        "producer_receipt": receipt,
        "resume_action": "verified-replay-no-execution",
    }


def _capture_observed_native(
    *, process_runner=None, rpc_transport=None, allow_synthetic_test=False, **args
):
    _require(type(allow_synthetic_test) is bool, "producer-synthetic-flag-invalid")
    process_injected, rpc_injected = (
        process_runner is not None,
        rpc_transport is not None,
    )
    _require(process_injected == rpc_injected, "producer-mixed-synthetic-seam")
    _require(
        process_injected == allow_synthetic_test, "producer-synthetic-seam-mismatch"
    )
    root = _telemetry(args["policy_bindings"])
    native._assert_separate(
        root, args["codex_home"], args["workspace"], args["capture_dir"]
    )
    current_request = _policy_preflight(args)
    if args.get("resume"):
        _require(
            isinstance(args.get("producer_receipt"), str), "producer-receipt-required"
        )
        return _verify(
            args, root, args["producer_receipt"], allow_synthetic=allow_synthetic_test
        )
    _require(args.get("producer_receipt") is None, "unexpected-producer-receipt")
    source_sha = _source_sha()
    with SealDirectory(root) as root_handle:
        with os.scandir(root_handle.target) as entries:
            _require(next(entries, None) is None, "producer-telemetry-not-empty")
        with root_handle.make_dir("bundle") as bundle_handle:
            with bundle_handle.make_dir("inventory") as inventory_handle:
                inventory = observation.collect_runtime_observation(
                    codex=args["codex"],
                    codex_home=args["codex_home"],
                    workspace=args["workspace"],
                    output_dir=root / "bundle" / "inventory",
                    rpc_transport=rpc_transport,
                    _output_handle=inventory_handle,
                )
    _observation_binding(inventory, current_request)
    capture_args = {
        key: value
        for key, value in args.items()
        if key not in {"capture_dir", "resume", "producer_receipt"}
    }
    capture = native.capture_native(
        **capture_args, output_dir=args["capture_dir"], process_runner=process_runner
    )
    bundle = root / "bundle"
    source_unchanged = source_sha == _source_sha()
    if capture.get("status") != "complete":
        failure = _record(capture, inventory, source_sha, root)
        receipt = _write(bundle, failure)
        return {**failure, "producer_receipt": receipt}
    if not source_unchanged:
        failure = _record(capture, inventory, source_sha, root)
        receipt = _write(bundle, failure)
        return {**failure, "producer_receipt": receipt}
    _require(
        canonical_hash(current_request)
        == canonical_hash(capture["stable_request_binding"]),
        "producer-capture-request-mismatch",
    )
    trace_root = _trace_root(root)
    receipt_map, trace_receipt = _snapshot(trace_root)
    with (
        TraceRoot(trace_root) as anchored,
        anchored.open_file("manifest.json") as stream,
    ):
        _time_bound(stream.read(MAX_FILE_BYTES + 1), capture)
    seal_args = {
        "capture_dir": args["capture_dir"],
        "capture_receipt": capture["record_sha256_receipt"],
        "trace_root": trace_root,
        "inventory_receipt": receipt_map,
        "trace_receipt_sha256": trace_receipt,
        "output_dir": bundle / "sealed",
    }
    if allow_synthetic_test:
        sealed = trace_capture._seal_trace_capture(
            **seal_args, allow_injected_test_capture=True
        )
    else:
        sealed = trace_capture.seal_trace_capture(**seal_args)
    trace = {
        "root": trace_root.name,
        "inventory": receipt_map,
        "receipt_sha256": trace_receipt,
        "seal_receipt": sealed["seal_receipt"],
    }
    _require(source_sha == _source_sha(), "producer-source-changed-during-seal")
    record = _record(capture, inventory, source_sha, root, trace)
    receipt = _write(bundle, record)
    return {**record, "producer_receipt": receipt}


def capture_observed_native(*, producer_receipt=None, resume=False, **args):
    """Run one authentic named-policy capture, or verify its completed bundle."""
    return _capture_observed_native(
        **args,
        producer_receipt=producer_receipt,
        resume=resume,
        allow_synthetic_test=False,
    )
