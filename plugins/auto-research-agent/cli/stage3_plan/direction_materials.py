"""Read a caller-configured registered-material frontier without promoting its claims."""

from copy import deepcopy
import hashlib
from pathlib import Path
import re

from .contracts import Stage3Error, canonical_bytes, digest
from .direction_research import _bounded_lookup_context
from .preparation import closed, file_binding, sha256, text
from .prompts import MAX_CONTEXT_BYTES
from .storage import (
    MAX_ARTIFACT_BYTES,
    decode_json,
    private_output,
    read_bytes,
    read_json,
    write_new,
)

KIND = "Stage3RegisteredMaterialFrontier"
MAX_MATERIAL_FRAGMENT_BYTES = 768
SCOPE = ("project_ref", "input_version", "intent_sha256", "source_manifest_sha256")
SELECTION = {
    "file_id",
    "sha256",
    "bytes",
    "pointers",
    "question_refs",
    "purpose",
    "limits",
}
META = (
    "id",
    "kind",
    "project_ref",
    "stage",
    "name",
    "bytes",
    "sha256",
    "status",
    "content_status",
    "registered_at",
    "execution_authorized",
)


def validate_material_context(context):
    """Reject large injected fragments without trimming their pinned originals."""
    if "registered_materials" not in context:
        return
    projection = context["registered_materials"]
    reason = (
        "registered material fragment exceeds 768 UTF-8 JSON bytes; "
        "select smaller explicit JSON pointers"
    )
    try:
        if (
            type(projection) is not dict
            or type(projection.get("materials")) is not list
        ):
            raise Stage3Error("invalid registered material context")
        pending, active, scalars = [(projection, False)], set(), []
        while pending:
            value, exiting = pending.pop()
            if exiting:
                active.remove(id(value))
            elif type(value) in (dict, list):
                if type(value) is dict and any(type(key) is not str for key in value):
                    raise Stage3Error("invalid registered material JSON type")
                if id(value) in active:
                    raise Stage3Error("invalid registered material JSON type")
                active.add(id(value))
                pending.append((value, True))
                children = (
                    [*value.keys(), *value.values()] if type(value) is dict else value
                )
                pending.extend((item, False) for item in children)
            elif type(value) is str:
                scalars.append(value)
            elif value is None or type(value) in (bool, int, float):
                scalars.append(value)
            else:
                raise Stage3Error("invalid registered material JSON type")
        if len(canonical_bytes(projection)) > MAX_CONTEXT_BYTES:
            raise Stage3Error("registered material context exceeds existing bound")
        for row in projection["materials"]:
            if type(row) is not dict or type(row.get("values")) is not list:
                raise Stage3Error("invalid registered material fragments")
            for fragment in row["values"]:
                if len(canonical_bytes(fragment)) > MAX_MATERIAL_FRAGMENT_BYTES:
                    raise Stage3Error(reason)
        if any(
            len(canonical_bytes(value)) > MAX_MATERIAL_FRAGMENT_BYTES
            for value in scalars
        ):
            raise Stage3Error(reason)
    except (RecursionError, UnicodeError) as error:
        raise Stage3Error("invalid registered material JSON encoding") from error


def _scope(context):
    if not isinstance(context, dict) or not set(SCOPE) <= set(context):
        raise Stage3Error("registered material consumer scope missing")
    value = {key: deepcopy(context[key]) for key in SCOPE}
    text(value["project_ref"], "material project")
    version = value["input_version"]
    if not (
        (type(version) is int and version >= 1)
        or (isinstance(version, str) and version.strip())
    ):
        raise Stage3Error("current material consumer input version required")
    for key in ("intent_sha256", "source_manifest_sha256"):
        sha256(value[key])
    return value


def _selections(context, selections):
    if type(selections) is not list or not selections:
        raise Stage3Error("explicit registered material selections required")
    questions = {row["question_ref"] for row in context["questions"]}
    seen = set()
    for row in selections:
        closed(row, SELECTION, "registered material selection")
        if (
            not isinstance(row["file_id"], str)
            or re.fullmatch(r"file-[0-9a-f]{32}", row["file_id"]) is None
            or row["file_id"] in seen
        ):
            raise Stage3Error("registered material identity differs")
        seen.add(row["file_id"])
        sha256(row["sha256"])
        if type(row["bytes"]) is not int or not 0 < row["bytes"] <= MAX_ARTIFACT_BYTES:
            raise Stage3Error("registered material exceeds existing artifact bound")
        for key in ("pointers", "question_refs"):
            if (
                type(row[key]) is not list
                or not row[key]
                or any(not isinstance(v, str) for v in row[key])
                or len(set(row[key])) != len(row[key])
            ):
                raise Stage3Error(
                    "explicit unique material pointers and questions required"
                )
        if not set(row["question_refs"]) <= questions:
            raise Stage3Error("registered material question differs")
        for key in ("purpose", "limits"):
            text(row[key], "registered material " + key)
        # Validate pointer syntax before invoking any trusted service.
        for pointer in row["pointers"]:
            if pointer and (
                not pointer.startswith("/") or re.search(r"~(?![01])", pointer)
            ):
                raise Stage3Error("invalid registered material JSON pointer")
    _bounded_lookup_context(context, selections)
    return deepcopy(selections)


def _value(document, pointer):
    result = document
    for key in pointer.split("/")[1:] if pointer else []:
        key = key.replace("~1", "/").replace("~0", "~")
        try:
            if isinstance(result, dict):
                result = result[key]
            elif isinstance(result, list) and re.fullmatch(r"0|[1-9][0-9]*", key):
                result = result[int(key)]
            else:
                raise ValueError("pointer does not address a JSON member")
        except (KeyError, IndexError, ValueError) as error:
            raise Stage3Error(
                "registered material JSON pointer is unavailable"
            ) from error
    return deepcopy(result)


def _metadata(entry, scope, selection):
    if not isinstance(entry, dict) or any(key not in entry for key in META):
        raise Stage3Error("registered material catalog metadata missing")
    value = {key: deepcopy(entry[key]) for key in META}
    if (
        value["id"] != selection["file_id"]
        or value["project_ref"] != scope["project_ref"]
        or value["kind"] != "manual-file"
        or value["stage"] != 3
        or value["status"] != "registered"
        or value["sha256"] != selection["sha256"]
        or type(value["bytes"]) is not int
        or value["bytes"] != selection["bytes"]
        or value["execution_authorized"] is not False
    ):
        raise Stage3Error("registered material catalog project, status or bytes differ")
    for key in ("name", "content_status", "registered_at"):
        text(value[key], "registered material " + key)
    return value


def _project(root, request, rows, context):
    closed(request, {"kind", "consumer", "selections"}, "material frontier request")
    consumer = _scope(context)
    original = _scope(request["consumer"])
    if (
        request["kind"] != KIND + "Request"
        or original != consumer
        or type(original["input_version"]) is not type(consumer["input_version"])
    ):
        raise Stage3Error("registered material consumer frontier differs")
    selections = _selections(context, request["selections"])
    if type(rows) is not list or len(rows) != len(selections):
        raise Stage3Error("registered material inventory differs")
    result = {
        "kind": KIND,
        "consumer": deepcopy(request["consumer"]),
        "catalog_input_version": "not-recorded",
        "scientific_quality_verified": False,
        "rights_verified": False,
        "execution_authorized": False,
        "materials": [],
    }
    for row, selection in zip(rows, selections):
        closed(row, {"catalog", "selection"}, "registered material row")
        if row["selection"] != selection:
            raise Stage3Error("registered material selection differs")
        catalog = _metadata(row["catalog"], request["consumer"], selection)
        raw = read_bytes(root / (selection["file_id"] + ".json"))
        if (
            len(raw) != selection["bytes"]
            or hashlib.sha256(raw).hexdigest() != selection["sha256"]
        ):
            raise Stage3Error("registered material saved bytes differ")
        document = decode_json(raw)
        projected = {
            "catalog": catalog,
            "purpose": selection["purpose"],
            "limits": selection["limits"],
            "question_refs": selection["question_refs"],
            "values": [
                {"pointer": p, "value": _value(document, p)}
                for p in selection["pointers"]
            ],
        }
        result["materials"].append(projected)
        _bounded_lookup_context(context, result)
    return result


def inspect_registered_materials(binding, context):
    """Recompute every projection from externally pinned original source bytes."""
    closed(binding, {"path", "sha256"}, "registered material frontier binding")
    packet = file_binding(binding["path"], binding["sha256"])
    closed(
        packet,
        {"kind", "request_sha256", "rows", "projection"},
        "registered material packet",
    )
    root = private_output(Path(binding["path"]).parent)
    request = read_json(root / "request.json")
    if packet["kind"] != KIND or packet["request_sha256"] != digest(request):
        raise Stage3Error("registered material request differs")
    if read_json(root / "catalog.json") != [row["catalog"] for row in packet["rows"]]:
        raise Stage3Error("registered material catalog snapshot differs")
    projection = _project(root, request, packet["rows"], context)
    if packet["projection"] != projection:
        raise Stage3Error("registered material projection differs")
    return projection


def prepare_registered_materials(context, selections, output, *, catalog, read_file):
    """Persist actual trusted reads; reuse matching partial files without redispatch.

    The Host owns authentication and same-origin access. Catalog metadata has no
    source input-version field: only the current consumer version is recorded.
    No callback, credentials or local source path enters the model projection.
    """
    root = private_output(output)
    request = {
        "kind": KIND + "Request",
        "consumer": _scope(context),
        "selections": _selections(context, selections),
    }
    if not callable(catalog) or not callable(read_file):
        raise Stage3Error("trusted material catalog and reader required")
    root.mkdir(parents=True, exist_ok=True)
    request_path = root / "request.json"
    if request_path.exists():
        if read_json(request_path) != request:
            raise Stage3Error("material frontier already belongs to another request")
    else:
        write_new(request_path, request)
    packet_path = root / "packet.json"
    if packet_path.exists():
        binding = {
            "path": str(packet_path),
            "sha256": hashlib.sha256(read_bytes(packet_path)).hexdigest(),
        }
        inspect_registered_materials(binding, context)
        return binding
    catalog_path = root / "catalog.json"
    if not catalog_path.exists():
        entries = catalog(request["consumer"]["project_ref"])
        if type(entries) is not list:
            raise Stage3Error("trusted material catalog must return entries")
        matches = []
        for selection in request["selections"]:
            found = [
                row
                for row in entries
                if isinstance(row, dict) and row.get("id") == selection["file_id"]
            ]
            if len(found) != 1:
                raise Stage3Error("unique registered material catalog entry required")
            matches.append(_metadata(found[0], request["consumer"], selection))
        write_new(catalog_path, matches)
    metadata = read_json(catalog_path)
    if type(metadata) is not list or len(metadata) != len(request["selections"]):
        raise Stage3Error("saved material catalog differs")
    rows = []
    for entry, selection in zip(metadata, request["selections"]):
        entry = _metadata(entry, request["consumer"], selection)
        path = root / (selection["file_id"] + ".json")
        if not path.exists():
            raw = read_file(selection["file_id"])
            if (
                not isinstance(raw, bytes)
                or len(raw) != selection["bytes"]
                or hashlib.sha256(raw).hexdigest() != selection["sha256"]
            ):
                raise Stage3Error("trusted registered material byte/hash mismatch")
            decode_json(raw)
            write_new(path, raw, raw=True)
        rows.append({"catalog": entry, "selection": selection})
        _project(
            root,
            dict(request, selections=request["selections"][: len(rows)]),
            rows,
            context,
        )
    packet = {
        "kind": KIND,
        "request_sha256": digest(request),
        "rows": rows,
        "projection": _project(root, request, rows, context),
    }
    write_new(packet_path, packet)
    binding = {
        "path": str(packet_path),
        "sha256": hashlib.sha256(read_bytes(packet_path)).hexdigest(),
    }
    inspect_registered_materials(binding, context)
    return binding
