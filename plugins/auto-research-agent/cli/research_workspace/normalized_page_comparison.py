"""Compare declared evidence for two saved page texts without doing I/O."""

from difflib import SequenceMatcher
import unicodedata

from stage1_deliverable.common import DeliverableError, sha

NORMALIZATION = "nfc-whitespace-v1"
_COMPARISON_KEYS = {
    "saved_normalized_sha256",
    "independent_normalized_sha256",
    "strict_equal",
    "differences",
}
_DIFFERENCE_KEYS = {
    "operation",
    "saved_extent",
    "independent_extent",
    "saved",
    "independent",
}


def _keys(value, expected, label):
    if type(value) is not dict or set(value) != expected:
        raise DeliverableError(label + " keys differ")


def _extent(value, expected, label):
    if (
        type(value) is not list
        or len(value) != 2
        or any(type(offset) is not int for offset in value)
        or tuple(value) != expected
    ):
        raise DeliverableError(label + " differs")


def _context(value, page, label):
    if type(value) is not str or not value.strip() or value.strip() not in page:
        raise DeliverableError(label + " differs")


def compare_normalized_page_evidence(saved_text, independent_text, declared_comparison):
    """Validate exact normalized hashes and ordered character edit operations.

    Extents index normalized Python strings, not UTF-8 bytes. Context strings
    need only occur in their respective normalized pages; they do not prove
    content completeness, identity, admission, or scientific quality.
    """
    if type(saved_text) is not str or type(independent_text) is not str:
        raise DeliverableError("page texts must be strings")
    _keys(declared_comparison, _COMPARISON_KEYS, "normalized comparison")
    saved = " ".join(unicodedata.normalize("NFC", saved_text).split())
    independent = " ".join(unicodedata.normalize("NFC", independent_text).split())
    try:
        saved_hash = sha(saved.encode("utf-8"))
        independent_hash = sha(independent.encode("utf-8"))
    except UnicodeError as error:
        raise DeliverableError("page text cannot be encoded as UTF-8") from error
    strict_equal = saved == independent
    for key, actual in (
        ("saved_normalized_sha256", saved_hash),
        ("independent_normalized_sha256", independent_hash),
    ):
        if (
            type(declared_comparison[key]) is not str
            or declared_comparison[key] != actual
        ):
            raise DeliverableError("normalized page hash differs")
    if (
        type(declared_comparison["strict_equal"]) is not bool
        or declared_comparison["strict_equal"] != strict_equal
    ):
        raise DeliverableError("normalized equality verdict differs")
    changes = (
        []
        if strict_equal
        else [
            opcode
            for opcode in SequenceMatcher(
                None, saved, independent, autojunk=False
            ).get_opcodes()
            if opcode[0] != "equal"
        ]
    )
    declared = declared_comparison["differences"]
    if type(declared) is not list or len(declared) != len(changes):
        raise DeliverableError("normalized difference count differs")
    operations = []
    for difference, (operation, a, b, c, d) in zip(declared, changes):
        _keys(difference, _DIFFERENCE_KEYS, "normalized difference")
        if (
            type(difference["operation"]) is not str
            or difference["operation"] != operation
        ):
            raise DeliverableError("normalized operation differs")
        _extent(difference["saved_extent"], (a, b), "saved extent")
        _extent(difference["independent_extent"], (c, d), "independent extent")
        _context(difference["saved"], saved, "saved context")
        _context(difference["independent"], independent, "independent context")
        operations.append(
            {
                "operation": operation,
                "saved_extent": [a, b],
                "independent_extent": [c, d],
            }
        )
    return {
        "normalization": NORMALIZATION,
        "normalization_unicode_version": unicodedata.unidata_version,
        "strict_equal": strict_equal,
        "saved_normalized_sha256": saved_hash,
        "independent_normalized_sha256": independent_hash,
        "operations": operations,
    }
