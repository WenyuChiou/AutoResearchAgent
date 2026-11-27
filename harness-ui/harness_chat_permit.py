"""Verify a fixed local chat-only grant without issuing permissions.

The embedding operator establishes the private key directory's OS permissions
and pins a receipt created from actual user authorization. HMAC establishes
local integrity, not independent human identity. No account/config/budget,
native process, model, or network is accessed here.
"""

import hashlib
import hmac
import json
import math
import os
from pathlib import Path
import re
import stat
import time


LIMIT = 64 * 1024
PIN = re.compile(r"[0-9a-f]{64}\Z")
READ_ACTIONS = frozenset({"state", "materials", "read_material", "read_saved_stage",
                          "read_paper", "inspect_workflow", "handoff_status"})
RECEIPT_FIELDS = frozenset({"kind", "version", "contract_sha256", "request_sha256",
                            "authorization_source_sha256", "issued_at", "expires_at",
                            "signature"})


class PermitError(ValueError):
    """Content-free refusal suitable for a local host status message."""


def _require(ok, code):
    if not ok:
        raise PermitError(code)


def _sha(value):
    _require(type(value) is str and PIN.fullmatch(value) is not None,
             "chat-permit-sha256-invalid")
    return value


def canonical(value):
    """The exact UTF-8 encoding signed and used for the request fingerprint."""
    try:
        raw = json.dumps(value, ensure_ascii=False, sort_keys=True, allow_nan=False,
                         separators=(",", ":")).encode("utf-8")
    except (TypeError, ValueError, UnicodeError, RecursionError):
        raise PermitError("chat-permit-canonical-json-invalid") from None
    _require(len(raw) <= LIMIT, "chat-permit-json-too-large")
    return raw


def _absolute(value):
    _require(isinstance(value, (str, os.PathLike)) and not isinstance(value, bytes),
             "chat-permit-path-invalid")
    try:
        path = Path(value)
        _require(path.is_absolute(), "chat-permit-absolute-path-required")
        # Refuse traversal spelling, even if the eventual resolution is private.
        _require(".." not in path.parts, "chat-permit-path-traversal-refused")
        return path
    except PermitError:
        raise
    except (TypeError, ValueError, OSError):
        raise PermitError("chat-permit-path-invalid") from None


def _identity(value):
    return value.st_dev, value.st_ino, value.st_size, value.st_mtime_ns, value.st_ctime_ns


def _private_key_path(path):
    _require(any(part.lower() in {"private", "_private"} for part in path.parts[:-1]),
             "chat-permit-private-key-directory-required")
    # Runtime keys must not be in Git, including worktrees with a .git pointer.
    for parent in (path.parent, *path.parent.parents):
        _require(not (parent / ".git").exists(), "chat-permit-key-in-git-refused")
    try:
        for component in reversed((path, *path.parents)):
            info = component.lstat()
            _require(not stat.S_ISLNK(info.st_mode)
                     and not (getattr(info, "st_file_attributes", 0) & 0x400),
                     "chat-permit-key-link-refused")
        # POSIX mode bits are meaningful there; Windows ACLs are operator-owned.
        if os.name != "nt":
            _require(not (path.stat().st_mode & 0o077), "chat-permit-key-permissions-not-private")
    except PermitError:
        raise
    except (OSError, ValueError):
        raise PermitError("chat-permit-key-unavailable") from None


def _read(path, limit, *, key=False):
    try:
        if key:
            _private_key_path(path)
        before = path.stat()
        _require(stat.S_ISREG(before.st_mode), "chat-permit-regular-file-required")
        _require(before.st_size <= limit, "chat-permit-file-too-large")
        with path.open("rb") as stream:
            opened = os.fstat(stream.fileno())
            _require(_identity(before) == _identity(opened), "chat-permit-file-changed")
            raw = stream.read(limit + 1)
            closed = os.fstat(stream.fileno())
        _require(len(raw) <= limit, "chat-permit-file-too-large")
        _require(_identity(before) == _identity(closed) == _identity(path.stat())
                 and len(raw) == before.st_size, "chat-permit-file-changed")
        if key:
            _private_key_path(path)
            _require(len(raw) == 32, "chat-permit-key-size-invalid")
        return raw
    except PermitError:
        raise
    except (OSError, ValueError, RuntimeError):
        raise PermitError("chat-permit-file-unavailable") from None


def _unique(pairs):
    result = {}
    for key, value in pairs:
        _require(key not in result, "chat-permit-json-duplicate-key")
        result[key] = value
    return result


def _nonfinite(_value):
    raise PermitError("chat-permit-json-nonfinite")


def _parse(raw):
    try:
        value = json.loads(raw.decode("utf-8"), object_pairs_hook=_unique,
                           parse_constant=_nonfinite)
    except PermitError:
        raise
    except (ValueError, UnicodeError, RecursionError):
        raise PermitError("chat-permit-json-invalid") from None
    _require(type(value) is dict and set(value) == RECEIPT_FIELDS,
             "chat-permit-receipt-fields-differ")
    _require(value["kind"] == "V9LocalChatOnlyPermit"
             and type(value["version"]) is int and value["version"] == 1,
             "chat-permit-receipt-version-invalid")
    for field in ("contract_sha256", "request_sha256", "authorization_source_sha256", "signature"):
        _sha(value[field])
    _window(value)
    return value


def _number(value):
    try:
        return type(value) in (int, float) and math.isfinite(value)
    except (ValueError, OverflowError):
        return False


def _window(value):
    _require(_number(value.get("issued_at")) and _number(value.get("expires_at"))
             and 0 < value["issued_at"] < value["expires_at"], "chat-permit-time-invalid")


def _receipt(path, pin, key):
    raw = _read(path, LIMIT)
    _require(hmac.compare_digest(hashlib.sha256(raw).hexdigest(), pin),
             "chat-permit-receipt-pin-differs")
    value = _parse(raw)
    payload = {name: item for name, item in value.items() if name != "signature"}
    expected = hmac.new(key, canonical(payload), hashlib.sha256).hexdigest()
    _require(hmac.compare_digest(expected, value["signature"]), "chat-permit-signature-differs")
    _require(value["issued_at"] <= time.time() < value["expires_at"], "chat-permit-not-current")
    return value


def load_permit_verifier(receipt_path, receipt_sha, key_path):
    """Return a verifier fixed to one externally pinned grant and request SHA.

    Each invocation rechecks key location/content, receipt bytes/HMAC/time, and
    the exact request fingerprint. This API never signs a request or derives
    permission from arbitrary JSON booleans.
    """
    receipt_path, key_path = _absolute(receipt_path), _absolute(key_path)
    receipt_sha = _sha(receipt_sha)
    initial_key = _read(key_path, 32, key=True)
    _receipt(receipt_path, receipt_sha, initial_key)

    def verify(request):
        key = _read(key_path, 32, key=True)
        _require(hmac.compare_digest(key, initial_key), "chat-permit-key-changed")
        receipt = _receipt(receipt_path, receipt_sha, key)
        _require(type(request) is dict and set(request) == {
            "kind", "contract_sha256", "contract", "research_execution"},
            "chat-permit-request-fields-differ")
        _require(request["kind"] == "V9ChatContinuationPermissionCheck"
                 and request["research_execution"] is False,
                 "chat-permit-request-chat-only-required")
        _require(_sha(request["contract_sha256"]) == receipt["contract_sha256"],
                 "chat-permit-contract-pin-differs")
        fingerprint = hashlib.sha256(canonical(request)).hexdigest()
        _require(hmac.compare_digest(fingerprint, receipt["request_sha256"]),
                 "chat-permit-fixed-request-differs")
        contract = request["contract"]
        _require(type(contract) is dict and contract.get("kind") == "V9ChatContinuation"
                 and type(contract.get("version")) is int and contract["version"] == 2
                 and type(contract.get("scope")) is dict, "chat-permit-contract-shape-invalid")
        scope = contract["scope"]
        _require(scope.get("model_messages_authorized") is True
                 and scope.get("research_execution") is False, "chat-permit-scope-chat-only-required")
        actions = scope.get("actions")
        _require(type(actions) is list and actions
                 and all(type(action) is str and action in READ_ACTIONS for action in actions)
                 and len(set(actions)) == len(actions), "chat-permit-read-actions-only")
        _window(scope)
        _require(scope["issued_at"] <= receipt["issued_at"] < receipt["expires_at"] <= scope["expires_at"],
                 "chat-permit-time-outside-contract")
        _require(scope["issued_at"] <= time.time() < scope["expires_at"], "chat-permit-contract-not-current")
        return {"kind": "V9VerifiedChatOnlyPermit", "request_sha256": fingerprint,
                "model_messages_authorized": True, "research_execution": False}

    return verify
