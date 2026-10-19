"""Explicit legacy planning preparation; never manufacture a strict delivery.

Legacy author assessments and A/B scores are not independent candidate reviews.
This module makes the saved questions readable and byte-bound. It does not make
them recommendation-eligible, authenticate a person, or authorize generation.
"""

import copy
import hashlib
from pathlib import Path
import tempfile

from stage2_common.contract import validate_packet

from .contracts import Stage3Error, digest
from .storage import private_output, read_bytes, read_json, safe_path, write_new

KIND = "Stage2LegacyPlanningMapping"
MANIFEST_KIND = "Stage2LegacyPlanningMappingManifest"
VERSION = "1.0.0"


def _require(value, message):
    if not value:
        raise Stage3Error(message)


def _source_paths(packet):
    _require(
        isinstance(packet, dict) and isinstance(packet.get("sources"), list),
        "legacy packet/source shape invalid",
    )
    rows = []
    for source in packet["sources"]:
        _require(
            isinstance(source, dict) and isinstance(source.get("path"), str),
            "legacy source path invalid",
        )
        name = source["path"]
        relative = Path(name)
        _require(
            name
            and not relative.anchor
            and ".." not in relative.parts
            and ":" not in name
            and "\\" not in name
            and relative.as_posix() == name,
            "legacy source path escapes root",
        )
        rows.append((relative, source))
    return rows


def _validated_source_bytes(packet, root, temporary_parent):
    """Validate only bounded byte snapshots, never reread original source files."""
    captured = {}
    for relative, source in _source_paths(packet):
        content = read_bytes(root / relative)
        _require(
            hashlib.sha256(content).hexdigest() == source["sha256"],
            "legacy source changed during preparation",
        )
        captured[relative.as_posix()] = content
    temporary_parent.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(
        prefix=".legacy-source-validation-", dir=temporary_parent
    ) as directory:
        snapshot = Path(directory)
        for name, content in captured.items():
            target = snapshot / name
            target.parent.mkdir(parents=True, exist_ok=True)
            write_new(target, content, raw=True)
        validate_packet(packet, snapshot)
    return {"sources/" + name: content for name, content in captured.items()}


def _mapping(packet):
    """Copy existing meanings, rather than create new scientific questions."""
    current = {}
    for candidate in packet["candidates"]:
        old = current.get(candidate["candidate_id"])
        if old is None or candidate["version"] > old["version"]:
            current[candidate["candidate_id"]] = candidate
    evidence = {row["evidence_id"]: row for row in packet["evidence"]}
    sources = {row["source_id"]: row for row in packet["sources"]}
    candidates = []
    for candidate in current.values():
        identity = dict(
            candidate_id=candidate["candidate_id"],
            candidate_version=candidate["version"],
        )
        source_ids = {evidence[eid]["source_id"] for eid in candidate["evidence_ids"]}
        refs = [
            {key: row[key] for key in ("source_id", "work_id", "version_id")}
            for sid, row in sources.items()
            if sid in source_ids
        ]

        def claim(field):
            return dict(
                text=candidate[field],
                status="inference" if field == "opportunity" else "proposal",
                evidence_ids=list(candidate["evidence_ids"]),
                source_refs=copy.deepcopy(refs),
                proposal_spans=[],
            )

        resources = [
            dict(
                **identity,
                resource_id=f"{candidate['candidate_id']}@{candidate['version']}/R{i}",
                description=text,
                status="unknown",
                authority="legacy-author-requirement; acquisition and fitness unverified",
            )
            for i, text in enumerate(candidate["requirements"], 1)
        ]
        argument = dict(
            motivation=claim("value"),
            current_state=[claim("opportunity")],
            gaps=[
                dict(
                    gap_id="G1",
                    statement=claim("opportunity"),
                    importance=claim("value"),
                )
            ],
            challenges=[],
            questions=[
                dict(
                    question_id="Q1",
                    text=candidate["question"],
                    priority="core",
                    gap_ids=["G1"],
                    object=candidate["research_mode"],
                    intended_claim=candidate["question"],
                    status="proposal",
                )
            ],
            contribution_claims=[
                dict(text=candidate["value"], question_ids=["Q1"], status="proposal")
            ],
            resource_refs=[
                dict(
                    resource_id=row["resource_id"],
                    question_ids=["Q1"],
                    purpose=row["description"],
                    fit_status="unknown",
                    evidence_ids=[],
                )
                for row in resources
            ],
        )
        candidates.append(
            dict(
                **identity,
                scientific_argument=argument,
                original_approach=candidate["approach"],
                limitations=copy.deepcopy(candidate["limitations"]),
                resources=resources,
                recommendation_eligible=None,
                review_status="independent-current-candidate-review-required",
                mapping_origin="literal legacy candidate fields; no new scientific findings",
            )
        )
    return dict(
        kind=KIND,
        schema_version=VERSION,
        mapping_version=1,
        packet_id=packet["packet_id"],
        origin="legacy-manual-v1",
        candidates=candidates,
        unresolved=copy.deepcopy(packet["unresolved"]),
        scientific_quality_verified=False,
        human_selection=None,
        execution_authorized=False,
    )


def prepare_legacy_mapping(
    packet_path, source_root, *, expected_packet_sha256, output_dir
):
    """Validate original sources/quotes and save a new, distinct mapping package."""
    raw = read_bytes(packet_path)
    _require(
        hashlib.sha256(raw).hexdigest() == expected_packet_sha256,
        "legacy packet external hash mismatch",
    )
    packet = read_json(packet_path)
    _require(
        isinstance(packet, dict)
        and packet.get("kind") == "Stage2Packet"
        and packet.get("schema_version") == "1.0.0",
        "explicit legacy v1 packet required",
    )
    root = safe_path(source_root)
    _source_paths(packet)
    output = private_output(output_dir)
    _require(
        not output.exists(),
        "legacy mapping output exists; inspect without regeneration",
    )
    source_bytes = _validated_source_bytes(packet, root, output.parent)
    mapping = _mapping(packet)
    output.mkdir(parents=True)
    write_new(output / "original-packet.json", raw, raw=True)
    write_new(output / "mapping.json", mapping)
    for name, content in source_bytes.items():
        target = safe_path(output / name)
        target.parent.mkdir(parents=True, exist_ok=True)
        write_new(target, content, raw=True)
    names = ["original-packet.json", "mapping.json", *source_bytes]
    manifest = dict(
        kind=MANIFEST_KIND,
        schema_version=VERSION,
        origin="legacy-manual-v1",
        original_packet_sha256=expected_packet_sha256,
        files=[
            dict(
                path=name, sha256=hashlib.sha256(read_bytes(output / name)).hexdigest()
            )
            for name in sorted(names)
        ],
        execution_authorized=False,
    )
    manifest["manifest_sha256"] = digest(manifest)
    write_new(output / "manifest.json", manifest)
    return inspect_legacy_mapping(
        output, expected_manifest_sha256=manifest["manifest_sha256"]
    )


def inspect_legacy_mapping(package_dir, *, expected_manifest_sha256):
    """Recheck exact input, inventory, source bytes, quotes and literal projection."""
    root = safe_path(package_dir)
    manifest = read_json(root / "manifest.json")
    _require(
        isinstance(manifest, dict)
        and set(manifest)
        == {
            "kind",
            "schema_version",
            "origin",
            "original_packet_sha256",
            "files",
            "execution_authorized",
            "manifest_sha256",
        },
        "legacy manifest shape differs",
    )
    unsigned = {k: v for k, v in manifest.items() if k != "manifest_sha256"}
    _require(
        manifest["kind"] == MANIFEST_KIND
        and manifest["schema_version"] == VERSION
        and manifest["origin"] == "legacy-manual-v1"
        and manifest["execution_authorized"] is False
        and manifest["manifest_sha256"] == expected_manifest_sha256
        and digest(unsigned) == expected_manifest_sha256,
        "legacy manifest external binding mismatch",
    )
    _require(isinstance(manifest["files"], list), "legacy inventory must be a list")
    names = []
    for row in manifest["files"]:
        _require(
            isinstance(row, dict)
            and set(row) == {"path", "sha256"}
            and isinstance(row["path"], str),
            "legacy inventory row differs",
        )
        name = row["path"]
        path = Path(name)
        _require(
            name
            and "\\" not in name
            and ":" not in name
            and not path.anchor
            and ".." not in path.parts
            and path.as_posix() == name
            and name != "manifest.json",
            "legacy inventory path invalid",
        )
        names.append(name)
        _require(
            hashlib.sha256(read_bytes(root / name)).hexdigest() == row["sha256"],
            "legacy artifact hash mismatch",
        )
    _require(len(names) == len(set(names)), "duplicate legacy inventory entry")
    actual = set()
    for path in root.rglob("*"):
        safe_path(path)
        if path.is_file():
            actual.add(path.relative_to(root).as_posix())
    _require(
        actual == set(names) | {"manifest.json"},
        "legacy inventory incomplete or unexpected",
    )
    raw = read_bytes(root / "original-packet.json")
    _require(
        hashlib.sha256(raw).hexdigest() == manifest["original_packet_sha256"],
        "legacy original packet mismatch",
    )
    packet = read_json(root / "original-packet.json")
    _require(
        isinstance(packet, dict) and packet.get("schema_version") == "1.0.0",
        "legacy packet version differs",
    )
    _source_paths(packet)
    _validated_source_bytes(packet, root / "sources", private_output(root).parent)
    expected_names = {"original-packet.json", "mapping.json"} | {
        "sources/" + Path(row["path"]).as_posix() for row in packet["sources"]
    }
    _require(set(names) == expected_names, "legacy source inventory differs")
    mapping = read_json(root / "mapping.json")
    _require(
        mapping == _mapping(packet),
        "legacy meaning/projection differs; explicit revision required",
    )
    return dict(
        manifest=manifest,
        mapping=mapping,
        packet=packet,
        status="mapped-awaiting-current-review-and-human-selection",
        can_prepare_selected_handoff=False,
        blockers=[
            "independent current candidate review is missing",
            "actual version-bound human selection is missing",
        ],
        strict_delivery=False,
        execution_authorized=False,
    )
