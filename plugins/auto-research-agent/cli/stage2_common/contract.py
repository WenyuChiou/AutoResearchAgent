"""Fail-closed validation for the versioned Stage 2 scientific packet."""

import hashlib
import json
from pathlib import Path, PurePosixPath, PureWindowsPath

from jsonschema import Draft202012Validator
from referencing import Registry, Resource

from stage1_brief.brief import validate_brief

SCHEMA_PATHS = {
    "1.0.0": Path(__file__).resolve().parents[2]
    / "schemas/stage2-packet.v1.schema.json",
    "2.0.0": Path(__file__).resolve().parents[2]
    / "schemas/stage2-packet.v2.schema.json",
    "2.1.0": Path(__file__).resolve().parents[2]
    / "schemas/stage2-packet.v2_1.schema.json",
}


class Stage2Error(ValueError):
    """A Stage 2 binding or contract is invalid."""


def _canonical_bytes(value):
    try:
        return json.dumps(
            value,
            sort_keys=True,
            separators=(",", ":"),
            ensure_ascii=False,
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as error:
        raise Stage2Error(f"value is not canonical JSON: {error}") from error


def canonical_hash(value):
    """Return the contract SHA-256; callers must compare it to an external hash."""

    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def stage1_projection_hash(rows, *, omit=()):
    """Hash immutable Stage 1 rows while allowing declared storage relocation."""

    return canonical_hash(
        [
            {key: value for key, value in row.items() if key not in omit}
            for row in rows
            if row.get("origin") == "stage1"
        ]
    )


def _require(condition, message):
    if not condition:
        raise Stage2Error(message)


def _unique(rows, key, label):
    values = [row[key] for row in rows]
    _require(len(values) == len(set(values)), f"duplicate {label}")


def _schema_validate(packet):
    version = packet.get("schema_version") if isinstance(packet, dict) else None
    path = SCHEMA_PATHS.get(version)
    _require(path is not None, f"unsupported Stage 2 packet version: {version!r}")
    try:
        schema = json.loads(path.read_text(encoding="utf-8"))
        registry = Registry()
        dependencies = [SCHEMA_PATHS["2.0.0"]] if version == "2.1.0" else []
        for schema_path in dependencies:
            value = json.loads(schema_path.read_text(encoding="utf-8"))
            registry = registry.with_resource(
                schema_path.name, Resource.from_contents(value)
            )
    except (OSError, ValueError) as error:
        raise Stage2Error(f"cannot load Stage 2 packet schema: {error}") from error
    errors = sorted(
        Draft202012Validator(schema, registry=registry).iter_errors(packet), key=str
    )
    if errors:
        first = errors[0]
        where = "/".join(map(str, first.absolute_path)) or "$"
        raise Stage2Error(f"stage2 packet schema {where}: {first.message}")


def _bound_path(root, relative):
    _require(isinstance(relative, str), "source path must be text")
    posix = PurePosixPath(relative)
    windows = PureWindowsPath(relative)
    _require(
        not posix.is_absolute()
        and not windows.is_absolute()
        and windows.drive == ""
        and "\\" not in relative
        and relative == posix.as_posix()
        and all(part not in {"", ".", ".."} for part in posix.parts),
        f"source path must be portable and relative: {relative}",
    )
    reserved_files = {"packet.json", "manifest.json", "selection.json", "selection.md"}
    _require(
        posix.name.casefold() not in reserved_files
        and (not posix.parts or posix.parts[0].casefold() != "events"),
        f"source path collides with run-control files: {relative}",
    )
    root = Path(root).resolve()
    path = (root / Path(*posix.parts)).resolve()
    try:
        path.relative_to(root)
    except ValueError as error:
        raise Stage2Error(f"source path escapes root: {relative}") from error
    _require(path.is_file(), f"source file missing: {relative}")
    return path


def validate_packet(packet, root):
    """Validate structure, brief, version history, and exact source bytes."""

    _schema_validate(packet)
    try:
        validate_brief(packet["brief"], require_confirmed=True)
    except (ValueError, KeyError, TypeError) as error:
        raise Stage2Error(f"invalid confirmed ResearchBrief: {error}") from error

    if packet["schema_version"] in {"2.0.0", "2.1.0"}:
        upstream = packet["upstream"]
        unsigned = {
            key: value for key, value in upstream.items() if key != "binding_sha256"
        }
        _require(
            upstream["binding_sha256"] == canonical_hash(unsigned),
            "stage1-stage2-binding-hash-mismatch",
        )
        _require(
            upstream["research_brief_sha256"] == canonical_hash(packet["brief"]),
            "stage1-stage2-brief-binding-mismatch",
        )
        _require(
            upstream["resources_sha256"] == canonical_hash(packet["resources"]),
            "stage1-stage2-resources-binding-mismatch",
        )
        if packet["schema_version"] == "2.1.0":
            acceptance = upstream["acceptance"]
            _require(
                upstream["acceptance_sha256"] == canonical_hash(acceptance),
                "stage2-exploratory-acceptance-hash-mismatch",
            )
            for field, upstream_field in (
                ("deliverable_manifest_sha256", "stage1_deliverable_manifest_sha256"),
                ("stage1_records_sha256", "stage1_records_sha256"),
                ("research_brief_sha256", "research_brief_sha256"),
                ("resources_sha256", "resources_sha256"),
                ("included_work_ids", "included_work_ids"),
            ):
                _require(
                    acceptance[field] == upstream[upstream_field],
                    f"stage2-exploratory-acceptance-{field}-mismatch",
                )
            _require(
                all(item in packet["unresolved"] for item in acceptance["limitations"]),
                "stage2-exploratory-limitations-not-preserved",
            )

    sources = packet["sources"]
    evidence = packet["evidence"]
    literature = packet.get("literature", [])
    candidates = packet["candidates"]
    if packet["schema_version"] in {"2.0.0", "2.1.0"}:
        _unique(literature, "work_id", "literature work_id")
    _unique(sources, "source_id", "source_id")
    _unique(sources, "path", "source path")
    _require(
        len({row["path"].casefold() for row in sources}) == len(sources),
        "duplicate source path",
    )
    _unique(evidence, "evidence_id", "evidence_id")
    candidate_keys = [(row["candidate_id"], row["version"]) for row in candidates]
    _require(
        len(candidate_keys) == len(set(candidate_keys)), "duplicate candidate version"
    )

    source_by_id = {row["source_id"]: row for row in sources}
    evidence_by_id = {row["evidence_id"]: row for row in evidence}
    for row in literature:
        work_sources = {
            source_id
            for source_id in row["source_ids"]
            if source_id in source_by_id
            and source_by_id[source_id]["work_id"] == row["work_id"]
            and source_by_id[source_id]["version_id"] == row["version_id"]
        }
        _require(
            work_sources == set(row["source_ids"]),
            f"literature-source-binding-mismatch: {row['work_id']}",
        )
        work_evidence = {
            evidence_id
            for evidence_id in row["claim_ids"]
            if evidence_id in evidence_by_id
            and evidence_by_id[evidence_id]["work_id"] == row["work_id"]
            and evidence_by_id[evidence_id]["version_id"] == row["version_id"]
        }
        _require(
            work_evidence == set(row["claim_ids"]),
            f"literature-evidence-binding-mismatch: {row['work_id']}",
        )
        for role in row["roles"]:
            _require(
                set(role["claim_ids"]).issubset(row["claim_ids"]),
                f"literature-role-evidence-mismatch: {row['work_id']}",
            )
    source_text = {}
    for source in sources:
        path = _bound_path(root, source["path"])
        raw = path.read_bytes()
        actual = hashlib.sha256(raw).hexdigest()
        _require(
            actual == source["sha256"], f"source hash mismatch: {source['source_id']}"
        )
        try:
            source_text[source["source_id"]] = raw.decode("utf-8")
        except UnicodeDecodeError as error:
            raise Stage2Error(
                f"source is not a UTF-8 snapshot: {source['source_id']}"
            ) from error

    if packet["schema_version"] in {"2.0.0", "2.1.0"}:
        included = set(packet["upstream"]["included_work_ids"])
        stage1_literature = [row for row in literature if row["origin"] == "stage1"]
        stage1_sources = [row for row in sources if row["origin"] == "stage1"]
        stage1_evidence = [row for row in evidence if row["origin"] == "stage1"]
        _require(
            packet["upstream"]["stage1_literature_sha256"]
            == stage1_projection_hash(stage1_literature),
            "stage1-literature-projection-mismatch",
        )
        _require(
            packet["upstream"]["stage1_sources_sha256"]
            == stage1_projection_hash(stage1_sources, omit={"path"}),
            "stage1-source-projection-mismatch",
        )
        _require(
            packet["upstream"]["stage1_evidence_sha256"]
            == stage1_projection_hash(stage1_evidence),
            "stage1-evidence-projection-mismatch",
        )
        literature_works = {row["work_id"] for row in stage1_literature}
        _require(
            included == literature_works,
            "stage1-stage2-upstream-literature-set-mismatch",
        )
    for row in evidence:
        source = source_by_id.get(row["source_id"])
        _require(
            source is not None,
            f"evidence references unknown source: {row['evidence_id']}",
        )
        _require(
            row["work_id"] == source["work_id"]
            and row["version_id"] == source["version_id"],
            f"evidence work/version mismatch: {row['evidence_id']}",
        )
        _require(
            row["quote"] in source_text[row["source_id"]],
            f"evidence quote is not exact contiguous source text: {row['evidence_id']}",
        )

    histories = {}
    for candidate in candidates:
        histories.setdefault(candidate["candidate_id"], []).append(candidate)
        refs = candidate["evidence_ids"]
        _require(len(refs) == len(set(refs)), "duplicate candidate evidence reference")
        _require(
            set(refs).issubset(evidence_by_id), "candidate references unknown evidence"
        )
    for candidate_id, rows in histories.items():
        ordered = sorted(rows, key=lambda row: row["version"])
        versions = [row["version"] for row in ordered]
        _require(
            versions == list(range(1, len(ordered) + 1)),
            f"non-contiguous candidate history: {candidate_id}",
        )
        for index, row in enumerate(ordered):
            expected_parent = None if index == 0 else index
            _require(
                row["parent_version"] == expected_parent,
                f"wrong candidate parent version: {candidate_id} v{row['version']}",
            )
    return None


def validate_evidence_refs(refs, packet):
    """Validate unique references to packet evidence IDs."""

    _require(isinstance(refs, list), "evidence references must be a list")
    ids = []
    for ref in refs:
        if isinstance(ref, str):
            evidence_id = ref
        elif isinstance(ref, dict) and set(ref) == {"evidence_id"}:
            evidence_id = ref["evidence_id"]
        else:
            raise Stage2Error("evidence reference must be an ID or evidence_id object")
        _require(
            isinstance(evidence_id, str) and evidence_id.strip(), "empty evidence ID"
        )
        ids.append(evidence_id)
    _require(len(ids) == len(set(ids)), "duplicate evidence reference")
    known = {row["evidence_id"] for row in packet.get("evidence", [])}
    _require(set(ids).issubset(known), "unknown evidence reference")
    return None
