"""Bounded, receipt-bound raw trace file reader; never establishes execution."""

import hashlib
import json
import math
import os
from pathlib import Path, PurePosixPath, PureWindowsPath
import stat

from stage2_common import Stage2Error, canonical_hash
from .trace_handles import TraceRoot

MAX_FILES = 512
MAX_FILE_BYTES = 4 * 1024 * 1024
MAX_TOTAL_BYTES = 32 * 1024 * 1024
MAX_EVENTS = 20_000
_HEX = set("0123456789abcdef")
_REPARSE = getattr(stat, "FILE_ATTRIBUTE_REPARSE_POINT", 0x400)


def _fail(message):
    raise Stage2Error(f"native-trace-{message}")


def _require(condition, message):
    if not condition:
        _fail(message)


def _regular(path, label):
    try:
        value = path.lstat()
    except OSError as error:
        _fail(f"{label}-missing: {error}")
    _require(
        not path.is_symlink()
        and not getattr(value, "st_file_attributes", 0) & _REPARSE,
        f"{label}-reparse",
    )
    return value


def _relative(value):
    _require(isinstance(value, str), "receipt-path-invalid")
    posix, windows = PurePosixPath(value), PureWindowsPath(value)
    if (
        not value
        or posix.is_absolute()
        or windows.is_absolute()
        or windows.drive
        or "\\" in value
        or value != posix.as_posix()
        or any(part in {"", ".", ".."} for part in posix.parts)
    ):
        _fail("receipt-path-invalid")
    return posix


def _load_inventory(root, receipt, expected_receipt_sha256):
    _require(isinstance(receipt, dict) and bool(receipt), "receipt-invalid")
    if (
        not isinstance(expected_receipt_sha256, str)
        or len(expected_receipt_sha256) != 64
        or any(c not in _HEX for c in expected_receipt_sha256)
        or canonical_hash(receipt) != expected_receipt_sha256
    ):
        _fail("receipt-hash-mismatch")
    expected = {}
    _require(len(receipt) <= MAX_FILES, "inventory-file-limit")
    for name, digest in receipt.items():
        posix = _relative(name)
        if (
            not isinstance(digest, str)
            or len(digest) != 64
            or any(c not in _HEX for c in digest)
            or name in expected
        ):
            _fail("receipt-invalid")
        expected[posix.as_posix()] = digest

    root = Path(os.path.abspath(os.fspath(root)))
    for ancestor in root.parents:
        _require(
            stat.S_ISDIR(_regular(ancestor, "root-parent").st_mode),
            "root-parent-not-directory",
        )
    root_stat = _regular(root, "root")
    _require(stat.S_ISDIR(root_stat.st_mode), "root-not-directory")
    payloads = root / "payloads"
    payload_stat = _regular(payloads, "payload-directory")
    _require(stat.S_ISDIR(payload_stat.st_mode), "payload-directory-invalid")

    raw, total = {}, 0
    try:
        with TraceRoot(root) as anchored:
            names = anchored.entries(MAX_FILES)
            _require(set(names) == set(expected), "inventory-mismatch")
            _require(
                {"manifest.json", "trace.jsonl"} <= set(names),
                "inventory-required-file-missing",
            )
            for name in sorted(names):
                _relative(name)
                with anchored.open_file(name) as stream:
                    status = os.fstat(stream.fileno())
                    _require(status.st_size <= MAX_FILE_BYTES, "file-size-limit")
                    _require(
                        total + status.st_size <= MAX_TOTAL_BYTES, "total-size-limit"
                    )
                    value = stream.read(MAX_FILE_BYTES + 1)
                    after = os.fstat(stream.fileno())
                    _require(
                        (status.st_dev, status.st_ino, status.st_size)
                        == (after.st_dev, after.st_ino, after.st_size),
                        "bound-file-changed-during-read",
                    )
                _require(len(value) <= MAX_FILE_BYTES, "file-size-limit")
                total += len(value)
                _require(total <= MAX_TOTAL_BYTES, "total-size-limit")
                _require(
                    hashlib.sha256(value).hexdigest() == expected[name],
                    f"file-hash-mismatch: {name}",
                )
                raw[name] = value
            _require(
                set(anchored.entries(MAX_FILES)) == set(names), "inventory-changed"
            )
    except OSError as error:
        _fail(f"inventory-read-failed: {error}")
    return raw


def _json(raw, label):
    def unique(pairs):
        value = {}
        for key, item in pairs:
            if key in value:
                _fail(f"duplicate-json-key: {label}")
            value[key] = item
        return value

    def finite(value):
        number = float(value)
        _require(math.isfinite(number), f"json-nonfinite: {label}")
        return number

    try:
        return json.loads(
            raw,
            object_pairs_hook=unique,
            parse_float=finite,
            parse_constant=lambda value: _fail(f"json-nonfinite: {label}"),
        )
    except (UnicodeDecodeError, ValueError, TypeError, RecursionError) as error:
        if isinstance(error, Stage2Error):
            raise
        _fail(f"json-invalid: {label}: {error}")


def _ref(payload, field, raw):
    _require(isinstance(payload, dict), f"payload-invalid: {field}")
    value = payload.get(field)
    if not isinstance(value, dict) or set(value) != {"raw_payload_id", "kind", "path"}:
        _fail(f"payload-reference-invalid: {field}")
    _require(
        isinstance(value["raw_payload_id"], str)
        and bool(value["raw_payload_id"])
        and isinstance(value["kind"], dict)
        and isinstance(value["kind"].get("type"), str)
        and bool(value["kind"]["type"]),
        f"payload-reference-invalid: {field}",
    )
    name = value["path"]
    if _relative(name).parts[:1] != ("payloads",) or name not in raw:
        _fail(f"payload-reference-invalid: {field}")
    return name, _json(raw[name], name), hashlib.sha256(raw[name]).hexdigest()
