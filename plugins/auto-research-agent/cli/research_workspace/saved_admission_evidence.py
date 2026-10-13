"""Read immutable admission evidence through an exact byte binding."""

import hashlib
import json
import re
import stat

from stage1_deliverable.common import DeliverableError, safe_path


_SHA256 = re.compile(r"[0-9a-f]{64}")
_REFERENCE_KEYS = {"path", "sha256", "bytes"}


def _reference(ref):
    if not isinstance(ref, dict) or set(ref) != _REFERENCE_KEYS:
        raise DeliverableError("invalid evidence reference")
    path = ref["path"]
    digest = ref["sha256"]
    size = ref["bytes"]
    if (
        not isinstance(path, str)
        or not isinstance(digest, str)
        or _SHA256.fullmatch(digest) is None
        or type(size) is not int
        or size < 0
    ):
        raise DeliverableError("invalid evidence reference")
    return path, digest, size


def read_bound(root, ref):
    """Return bytes from a contained regular file matching an exact reference."""

    name, expected_digest, expected_size = _reference(ref)
    path = safe_path(root, name)
    try:
        if not stat.S_ISREG(path.stat(follow_symlinks=False).st_mode):
            raise DeliverableError("evidence artifact is not a regular file")
        raw = path.read_bytes()
    except DeliverableError:
        raise
    except OSError as exc:
        raise DeliverableError("evidence artifact could not be read") from exc
    if len(raw) != expected_size or hashlib.sha256(raw).hexdigest() != expected_digest:
        raise DeliverableError("evidence artifact binding differs")
    return raw


def read_bound_json(root, ref):
    """Return strict JSON decoded from one verified byte snapshot."""

    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise DeliverableError("duplicate JSON key")
            result[key] = value
        return result

    def reject_constant(_value):
        raise DeliverableError("non-finite JSON value")

    raw = read_bound(root, ref)
    try:
        return json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=unique,
            parse_constant=reject_constant,
        )
    except DeliverableError:
        raise
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise DeliverableError("valid UTF-8 JSON evidence required") from exc
