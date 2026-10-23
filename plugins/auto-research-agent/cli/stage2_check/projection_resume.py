"""Strictly resume deterministic checker projections without replacing evidence."""

from stage1_deliverable.common import DeliverableError, reject_links
from stage2_common import Stage2Error


def write_projection(path, value):
    from .run import _canonical_bytes, _write_new

    try:
        reject_links(path)
    except DeliverableError as error:
        raise Stage2Error("checker-projection-link-forbidden") from error
    data = value if isinstance(value, bytes) else _canonical_bytes(value)
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise Stage2Error("checker-projection-existing-bytes-differ")
        return
    _write_new(path, value)
