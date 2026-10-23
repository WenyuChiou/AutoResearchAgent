"""Publish ordinary delivery only after validation; resume immutable metadata."""

import ctypes
import errno
import json
import os
import sys
from pathlib import Path

from stage1_deliverable.common import DeliverableError, private_output, reject_links
from stage2_common import Stage2Error, canonical_hash


def _private(path):
    try:
        return private_output(path)
    except DeliverableError as error:
        raise Stage2Error("delivery-publication-path-invalid") from error


def _json_value(value):
    if isinstance(value, Path):
        return str(value.absolute())
    if isinstance(value, dict):
        return {key: _json_value(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_value(item) for item in value]
    return value


def resume_write(path, value):
    """Existing bytes must match exactly; a failed write is never overwritten."""
    from .delivery import _canonical_bytes, _write_new

    path = Path(path)
    try:
        reject_links(path)
    except DeliverableError as error:
        raise Stage2Error("delivery-resume-link-forbidden") from error
    data = value if isinstance(value, bytes) else _canonical_bytes(value)
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise Stage2Error("delivery-resume-existing-bytes-differ")
        return
    _write_new(path, value)


def _verify(directory, request, expected_manifest_sha256):
    from .delivery import _read_json, inspect_delivery

    package = inspect_delivery(directory, expected_manifest_sha256)
    manifest = package["manifest"]
    for key in (
        "workflow_head_sha256",
        "workflow_manifest_sha256",
        "batch_sha256",
        "snapshot_sequence",
        "snapshot_sha256",
        "snapshot_checker_manifest_sha256",
    ):
        if manifest[key] != request[key]:
            raise Stage2Error("delivery-publication-request-differs")
    for name, field in (
        ("review_batch.json", "batch"),
        ("review_results.json", "reviews"),
        ("review_resolutions.json", "resolutions"),
    ):
        if _read_json(directory / name) != request[field]:
            raise Stage2Error("delivery-publication-review-input-differs")
    return package["manifest"]


def _seal_value(directory, request, manifest):
    from .delivery import MANIFEST, _file_sha

    return dict(
        kind="Stage2DeliveryPublicationSeal",
        schema_version="1.0.0",
        request_sha256=canonical_hash(request),
        manifest_sha256=manifest["manifest_sha256"],
        manifest_file_sha256=_file_sha(directory / MANIFEST),
    )


def _verify_sealed(directory, request, seal_path):
    from .delivery import _read_json

    seal = _read_json(seal_path)
    if not isinstance(seal, dict) or not isinstance(seal.get("manifest_sha256"), str):
        raise Stage2Error("delivery-publication-seal-invalid")
    if seal != _seal_value(directory, request, seal):
        raise Stage2Error("delivery-publication-seal-differs")
    return _verify(directory, request, seal["manifest_sha256"])


def _publish(staging, output):
    """Use exclusive native rename; never fall back to replacing POSIX rename."""
    try:
        if sys.platform == "win32":
            os.rename(staging, output)
            return
        libc = ctypes.CDLL(None, use_errno=True)
        source, target = os.fsencode(staging), os.fsencode(output)
        if sys.platform == "darwin":
            # Apple stdio.h: RENAME_EXCL=4, renamex_np(old, new, flags).
            rename = libc.renamex_np
            rename.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint]
            args = (source, target, 4)
        elif sys.platform.startswith("linux"):
            # Linux renameat2: AT_FDCWD=-100 and RENAME_NOREPLACE=1.
            rename = libc.renameat2
            rename.argtypes = [
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_int,
                ctypes.c_char_p,
                ctypes.c_uint,
            ]
            args = (-100, source, -100, target, 1)
        else:
            raise Stage2Error("delivery-publication-exclusive-rename-unavailable")
        rename.restype = ctypes.c_int
        if rename(*args) != 0:
            code = ctypes.get_errno()
            raise OSError(code, os.strerror(code), str(output))
    except AttributeError as error:
        raise Stage2Error(
            "delivery-publication-exclusive-rename-unavailable"
        ) from error
    except OSError as error:
        if error.errno in {errno.EEXIST, errno.ENOTEMPTY}:
            raise Stage2Error("delivery-publication-destination-exists") from error
        raise


def build_atomic_delivery(
    run_dir, batch, reviews, resolutions, output_dir, expected_head, **options
):
    """Reuse the ordinary builder and inspector; no model or workflow action runs.

    A process killed while holding the lock requires a verified lock recovery.
    Partial/truncated bytes are retained and rejected, never silently rewritten.
    """
    from .delivery import _write_new, build_delivery
    from .store import inspect_workflow

    if "_resume" in options:
        raise Stage2Error("delivery-publication-internal-option-forbidden")
    output = _private(output_dir)
    staging = _private(output.with_name("." + output.name + ".stage2-staging"))
    request_path = _private(
        output.with_name("." + output.name + ".stage2-request.json")
    )
    seal_path = _private(output.with_name("." + output.name + ".stage2-sealed.json"))
    lock = _private(output.with_name("." + output.name + ".stage2-publish.lock"))
    workflow = inspect_workflow(run_dir, expected_head=expected_head)
    snapshot = workflow["latest_snapshot"]
    request = _json_value(
        dict(
            kind="Stage2DeliveryPublicationRequest",
            schema_version="1.0.0",
            workflow_root=str(Path(run_dir).resolve()),
            workflow_head_sha256=expected_head,
            workflow_manifest_sha256=workflow["manifest"]["manifest_sha256"],
            snapshot_sequence=snapshot["event"]["payload"]["snapshot_sequence"],
            snapshot_sha256=snapshot["event"]["payload"]["snapshot_sha256"],
            snapshot_checker_manifest_sha256=snapshot["checker"]["manifest"][
                "manifest_sha256"
            ],
            batch_sha256=batch["batch_sha256"],
            batch=batch,
            reviews=reviews,
            resolutions=resolutions,
            options=options,
        )
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    try:
        stream = lock.open("xb")
    except FileExistsError as error:
        raise Stage2Error("delivery-publication-lock-requires-inspection") from error
    try:
        with stream:
            stream.write(
                json.dumps(
                    {"pid": os.getpid(), "request_sha256": canonical_hash(request)}
                ).encode()
            )
            stream.flush()
            os.fsync(stream.fileno())
        if request_path.exists():
            resume_write(request_path, request)
        else:
            if output.exists() or staging.exists() or seal_path.exists():
                raise Stage2Error("delivery-publication-unbound-existing-output")
            _write_new(request_path, request)
        if output.exists():
            if staging.exists():
                raise Stage2Error("delivery-publication-two-directories")
            if not seal_path.is_file():
                raise Stage2Error("delivery-publication-seal-missing")
            return _verify_sealed(output, request, seal_path)
        if not seal_path.exists():
            built = build_delivery(
                run_dir,
                batch,
                reviews,
                resolutions,
                staging,
                expected_head,
                _resume=staging.exists(),
                **options,
            )
            _verify(staging, request, built["manifest_sha256"])
            resume_write(seal_path, _seal_value(staging, request, built))
        _verify_sealed(staging, request, seal_path)
        inspect_workflow(run_dir, expected_head=expected_head)
        _publish(staging, output)
        return _verify_sealed(output, request, seal_path)
    finally:
        lock.unlink()
