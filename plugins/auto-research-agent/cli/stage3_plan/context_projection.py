"""Losslessly share repeated source values inside a bounded planning prompt."""

from collections import Counter
from copy import deepcopy

from .contracts import Stage3Error, canonical_bytes, digest

REF = "$"
LITERAL = "$literal"


def pack_context(context):
    counts = Counter()

    def count(value):
        raw = canonical_bytes(value)
        if len(raw) >= 32:
            counts[raw] += 1
        if isinstance(value, dict):
            for item in value.values():
                count(item)
        elif isinstance(value, list):
            for item in value:
                count(item)

    count(context)
    references, shared = {}, []

    def encode(value, defining=False):
        raw = canonical_bytes(value)
        if not defining and counts[raw] > 1:
            if raw not in references:
                ref = len(shared)
                references[raw] = ref
                shared.append(None)
                shared[ref] = encode(value, defining=True)
            return {REF: references[raw]}
        if isinstance(value, dict):
            result = {key: encode(item) for key, item in value.items()}
            if set(result) in ({REF}, {LITERAL}):
                return {LITERAL: list(map(list, result.items()))}
            return result
        if isinstance(value, list):
            return [encode(item) for item in value]
        return value

    data = encode(context)
    packed = {
        "kind": "Stage3SharedPlanningContext",
        "schema_version": "1.0.0",
        "context_sha256": digest(context),
        "data": data,
        "shared": shared,
    }
    if digest(expand_context(packed)) != digest(context):
        raise Stage3Error("planning context sharing changed source content")
    return packed


def expand_context(packed):
    """Reconstruct exact JSON values; reserved source keys are explicitly escaped."""
    if (
        type(packed) is not dict
        or set(packed) != {"kind", "schema_version", "context_sha256", "data", "shared"}
        or packed.get("kind") != "Stage3SharedPlanningContext"
        or packed.get("schema_version") != "1.0.0"
        or type(packed.get("shared")) is not list
    ):
        raise Stage3Error("invalid shared planning context")
    active, cache = set(), {}

    def decode(value):
        if isinstance(value, dict):
            if set(value) == {REF}:
                ref = value[REF]
                if (
                    type(ref) is not int
                    or not 0 <= ref < len(packed["shared"])
                    or ref in active
                ):
                    raise Stage3Error("missing or cyclic shared source value")
                if ref not in cache:
                    active.add(ref)
                    cache[ref] = decode(packed["shared"][ref])
                    active.remove(ref)
                return deepcopy(cache[ref])
            if set(value) == {LITERAL}:
                rows = value[LITERAL]
                if (
                    not isinstance(rows, list)
                    or any(
                        not isinstance(row, list)
                        or len(row) != 2
                        or not isinstance(row[0], str)
                        for row in rows
                    )
                    or len({row[0] for row in rows}) != len(rows)
                ):
                    raise Stage3Error("invalid literal shared source object")
                return {key: decode(item) for key, item in rows}
            return {key: decode(item) for key, item in value.items()}
        if isinstance(value, list):
            return [decode(item) for item in value]
        return value

    result = decode(packed["data"])
    if digest(result) != packed["context_sha256"]:
        raise Stage3Error("expanded planning context hash differs")
    return result
