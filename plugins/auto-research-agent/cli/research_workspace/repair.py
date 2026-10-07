"""Apply an independently accepted private repair as a read-only overlay."""

from copy import deepcopy
import csv
import io
import re
from pathlib import Path
from jsonschema import Draft202012Validator, ValidationError
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    safe_path,
    sha,
)
from .json_bytes import decode_json


def _require(condition, message):
    if not condition:
        raise DeliverableError(message)


def _snapshot(root, relative, expected=None):
    path = safe_path(root, relative)
    _require(path.is_file(), "missing repair member: " + relative)
    raw = path.read_bytes()
    if expected is not None:
        _require(sha(raw) == expected, "repair member hash mismatch: " + relative)
    return raw


def _members(value):
    _require(
        value.get("kind") == "PrivateRepairCandidateManifest"
        and value.get("schema_version") == "1.0.0",
        "unsupported repair manifest",
    )
    rows = value.get("files")
    _require(
        isinstance(rows, list) and value.get("member_count") == len(rows),
        "repair manifest count mismatch",
    )
    files = {}
    for row in rows:
        _require(isinstance(row, dict), "invalid manifest member")
        relative = row.get("path")
        _require(
            isinstance(relative, str)
            and bool(relative)
            and isinstance(row.get("sha256"), str)
            and re.fullmatch(r"[a-f0-9]{64}", row["sha256"]) is not None
            and type(row.get("bytes")) is int
            and row["bytes"] >= 0,
            "invalid manifest member binding",
        )
        _require(relative not in files, "duplicate repair member")
        files[relative] = row
    return files


def _manifest(root, expected_sha256):
    _require(
        isinstance(expected_sha256, str)
        and re.fullmatch(r"[a-f0-9]{64}", expected_sha256) is not None,
        "invalid external manifest hash",
    )
    raw = _snapshot(root, "checks/candidate_manifest.json", expected_sha256)
    value = decode_json(raw)
    files = _members(value)
    for relative, row in files.items():
        member = _snapshot(root, relative, row["sha256"])
        _require(
            len(member) == row.get("bytes"),
            "repair member byte count mismatch: " + str(relative),
        )
    return raw, value, files


def _source_text(base_root, evidence, base_sources, snapshots):
    source = base_sources.get(evidence.get("source_id"))
    _require(source is not None, "repair evidence source is absent from base")
    _require(
        evidence.get("text_sha256")
        == source.get("receipt", {}).get("extracted_text_sha256"),
        "repair evidence differs from canonical source extraction",
    )
    _require(
        (evidence.get("work_id"), evidence.get("version_id"))
        == (source.get("work_id"), source.get("version_id")),
        "repair evidence work/version differs from base",
    )
    supplied = Path(evidence.get("text_path", ""))
    _require(supplied.is_absolute(), "repair evidence path is not absolute")
    try:
        relative = supplied.resolve().relative_to(base_root.resolve()).as_posix()
    except ValueError as error:
        raise DeliverableError("repair evidence escaped base package") from error
    path = safe_path(base_root, relative)
    raw = path.read_bytes()
    _require(
        sha(raw) == evidence.get("text_sha256"), "repair evidence text hash mismatch"
    )
    text = raw.decode("utf-8")
    start, end, quote = (
        evidence.get("start"),
        evidence.get("end"),
        evidence.get("quote"),
    )
    _require(
        isinstance(start, int)
        and isinstance(end, int)
        and 0 <= start <= end <= len(text)
        and text[start:end] == quote,
        "repair evidence quote binding mismatch",
    )
    snapshots[path] = sha(raw)


def _passage_bindings(root, relative, passage_ids, base_sources):
    value = decode_json(_snapshot(root, relative))
    passages = {row.get("passage_id"): row for row in value.get("passages", [])}
    _require(
        len(passages) == len(value.get("passages", [])), "duplicate repair passage"
    )
    for passage_id in passage_ids:
        passage = passages.get(passage_id)
        _require(passage is not None, "atomic repair passage is missing")
        source = base_sources.get(passage.get("source_id"))
        _require(
            source is not None
            and (passage.get("work_id"), passage.get("version_id"))
            == (source.get("work_id"), source.get("version_id")),
            "atomic repair passage work/version differs",
        )
        binding = passage.get("clean_source") or passage.get("clean_abstract")
        supplied = Path(binding.get("path", ""))
        try:
            local = safe_path(
                root, supplied.resolve().relative_to(root.resolve()).as_posix()
            )
        except ValueError as error:
            raise DeliverableError(
                "atomic repair passage escaped repair root"
            ) from error
        raw = local.read_bytes()
        text = raw.decode("utf-8")
        start, end = binding.get("start"), binding.get("end")
        _require(
            sha(raw) == binding.get("sha256")
            and isinstance(start, int)
            and isinstance(end, int)
            and 0 <= start <= end <= len(text)
            and text[start:end] == passage.get("quote"),
            "atomic repair passage quote binding mismatch",
        )


def _validate_content(index, root, supplement, files):
    _require(
        supplement.get("kind") == "Stage1PrivateContentRepairSupplement"
        and supplement.get("schema_version") == "1.0.0",
        "unsupported repair supplement",
    )
    for field in (
        "official_stage2_import_eligible",
        "protected_execution_authorized",
        "scientific_scores_changed",
    ):
        _require(
            supplement.get(field) is False,
            "repair cannot grant scores or execution: " + field,
        )
    _require(
        supplement.get("all_original_obligations_retained") is True,
        "repair dropped original obligations",
    )
    _require(
        supplement.get("source_reading")
        == {"abstract": "success", "required_full_methods": "failure"},
        "repair source-reading boundary differs",
    )
    provenance = index["provenance"]
    _require(
        supplement.get("base_package_manifest_sha256")
        == provenance["package_manifest_sha256"],
        "repair base package differs",
    )
    _require(
        supplement.get("base_deliverable_manifest_sha256")
        == provenance["deliverable_manifest_sha256"],
        "repair base deliverable differs",
    )
    _require(
        supplement.get("base_records_sha256") == provenance["records_sha256"],
        "repair base records differ",
    )
    base_papers = {(row["work_id"], row["version_id"]): row for row in index["papers"]}
    repair_papers = supplement.get("papers", [])
    identities = [(row.get("work_id"), row.get("version_id")) for row in repair_papers]
    _require(len(identities) == len(set(identities)), "duplicate repair work/version")
    _require(
        all(identity in base_papers for identity in identities),
        "repair work/version is absent from base",
    )
    versions = {work: version for work, version in identities}
    claims = {row["claim_id"]: row for row in index["claims"]}
    base_sources = {row["source_id"]: row for row in index["sources"]}
    atom_ids = set()
    for atom in supplement.get("atomic_revisions", []):
        atom_id = atom.get("atom_id")
        _require(atom_id and atom_id not in atom_ids, "duplicate atomic revision")
        atom_ids.add(atom_id)
        parent = claims.get(atom.get("parent_claim_id"))
        _require(
            parent is not None and parent.get("work_id") == atom.get("work_id"),
            "atomic revision parent differs",
        )
        _require(
            versions.get(atom.get("work_id")) == parent.get("version_id"),
            "atomic revision version differs",
        )
        relative = (root / "integrated" / atom.get("evidence_ref", "")).resolve()
        try:
            relative = relative.relative_to(root.resolve()).as_posix()
        except ValueError as error:
            raise DeliverableError("atomic evidence escaped repair root") from error
        _require(relative in files, "atomic evidence is not manifest-bound")
        if atom.get("passage_ids"):
            _passage_bindings(root, relative, atom["passage_ids"], base_sources)
    base_root = private_output(supplement.get("base_package_path", ""))
    _require(base_root.is_dir(), "repair base package is missing")
    manifest_raw = (base_root / "package_manifest.json").read_bytes()
    _require(
        sha(manifest_raw) == provenance["package_manifest_sha256"],
        "repair base package hash mismatch",
    )
    snapshots = {base_root / "package_manifest.json": sha(manifest_raw)}
    finding_ids = set()
    for finding in supplement.get("core_findings", []):
        finding_id = finding.get("finding_id")
        _require(
            finding_id and finding_id not in finding_ids, "duplicate repair finding"
        )
        finding_ids.add(finding_id)
        _require(finding.get("work_id") in versions, "repair finding work is absent")
        for evidence in finding.get("evidence", []):
            _source_text(base_root, evidence, base_sources, snapshots)
    return snapshots


def _edges(supplement):
    papers = {row["work_id"]: row["version_id"] for row in supplement["papers"]}
    output = []
    for pos, atom in enumerate(supplement["atomic_revisions"]):
        origin = {
            "path": "integrated/repair_supplement.json",
            "pointer": f"/atomic_revisions/{pos}",
        }
        output.append(
            {
                "type": "atomic-revision-claim",
                "atom_id": atom["atom_id"],
                "claim_id": atom["parent_claim_id"],
                "work_id": atom["work_id"],
                "version_id": papers[atom["work_id"]],
                "assessment": atom["assessment"],
                "provenance": origin,
            }
        )
        output.append(
            {
                "type": "atomic-revision-source",
                "atom_id": atom["atom_id"],
                "evidence_ref": atom["evidence_ref"],
                "passage_ids": deepcopy(atom.get("passage_ids", [])),
                "provenance": origin,
            }
        )
    for pos, finding in enumerate(supplement["core_findings"]):
        origin = {
            "path": "integrated/repair_supplement.json",
            "pointer": f"/core_findings/{pos}",
        }
        output.append(
            {
                "type": "finding-work",
                "finding_id": finding["finding_id"],
                "work_id": finding["work_id"],
                "version_id": papers[finding["work_id"]],
                "provenance": origin,
            }
        )
        for evidence in finding["evidence"]:
            output.append(
                {
                    "type": "finding-source",
                    "finding_id": finding["finding_id"],
                    "source_id": evidence["source_id"],
                    "work_id": evidence["work_id"],
                    "version_id": evidence["version_id"],
                    "quote": evidence["quote"],
                    "locator": evidence["context_locator"],
                    "provenance": origin,
                }
            )
    return output


def validate_repair_projection(index):
    """Validate only the v2 overlay; the caller validates the unchanged v1 base."""
    schema = decode_json(
        Path(__file__).with_name("WorkspaceIndex.v2.schema.json").read_bytes()
    )
    try:
        Draft202012Validator(schema).validate(index)
    except ValidationError as error:
        raise DeliverableError("workspace repair schema: " + error.message) from error
    supplement = index["supplement"]
    acceptance, data, evidence = (
        supplement["acceptance"],
        supplement["data"],
        supplement["evidence_files"],
    )
    _require(
        acceptance["candidate_manifest_sha256"] == supplement["manifest_sha256"]
        and acceptance["independent_review_sha256"] == supplement["review_sha256"],
        "repair acceptance external hashes differ",
    )
    for name, row in evidence.items():
        _require(
            sha(row["text"].encode("utf-8")) == row["sha256"],
            "repair evidence snapshot hash differs: " + name,
        )
    required = {
        "checks/candidate_manifest.json",
        "acceptance/actual_content_delta_review.json",
        "acceptance/final_delivery_receipt.json",
        "integrated/repair_supplement.json",
    }
    _require(required <= set(evidence), "repair evidence snapshot is incomplete")
    _require(
        evidence["checks/candidate_manifest.json"]["sha256"]
        == supplement["manifest_sha256"]
        and evidence["acceptance/actual_content_delta_review.json"]["sha256"]
        == supplement["review_sha256"],
        "repair snapshot external hashes differ",
    )
    _require(
        decode_json(
            evidence["integrated/repair_supplement.json"]["text"].encode("utf-8")
        )
        == data,
        "repair supplement snapshot differs from data",
    )
    _require(
        decode_json(
            evidence["acceptance/final_delivery_receipt.json"]["text"].encode("utf-8")
        )
        == acceptance,
        "repair receipt snapshot differs from acceptance",
    )
    review = decode_json(
        evidence["acceptance/actual_content_delta_review.json"]["text"].encode("utf-8")
    )
    prior = review.get("prior_review", {})
    _require(
        review.get("verdict") == "PASS"
        and review.get("action_hash") == supplement["manifest_sha256"],
        "repair review snapshot differs",
    )
    _require(
        prior.get("immutable_original_verdict") == "REQUEST_CHANGES"
        and prior.get("path") in evidence
        and evidence[prior["path"]]["sha256"] == prior.get("sha256")
        and decode_json(evidence[prior["path"]]["text"].encode("utf-8")).get("verdict")
        == "REQUEST_CHANGES",
        "repair prior review was not retained",
    )
    manifest = decode_json(
        evidence["checks/candidate_manifest.json"]["text"].encode("utf-8")
    )
    members = _members(manifest)
    _require(
        "integrated/repair_supplement.json" in members,
        "accepted manifest members differ",
    )
    external = required - {"integrated/repair_supplement.json"} | {prior["path"]}
    for name, snapshot in evidence.items():
        member = members.get(name)
        if member is None:
            _require(
                name in external, "snapshot not bound to accepted manifest: " + name
            )
        else:
            _require(
                snapshot["sha256"] == member.get("sha256")
                and len(snapshot["text"].encode("utf-8")) == member.get("bytes"),
                "snapshot differs from accepted manifest: " + name,
            )
    _require(
        data["source_reading"]
        == {"abstract": "success", "required_full_methods": "failure"},
        "repair source-reading boundary differs",
    )
    _require(
        data["all_original_obligations_retained"] is True,
        "repair obligations not retained",
    )
    _require(
        all(
            data[field] is False
            for field in (
                "official_stage2_import_eligible",
                "protected_execution_authorized",
                "scientific_scores_changed",
            )
        ),
        "repair granted scores or execution",
    )
    _require(
        data.get("base_package_manifest_sha256")
        == index["provenance"]["package_manifest_sha256"]
        and data.get("base_deliverable_manifest_sha256")
        == index["provenance"]["deliverable_manifest_sha256"]
        and data.get("base_records_sha256") == index["provenance"]["records_sha256"],
        "repair base hashes differ",
    )
    _require(
        data.get("original_canonical_claim_rows", len(index["claims"]))
        == len(index["claims"]),
        "repair canonical claim count differs",
    )
    audit = next(
        (
            row
            for row in index.get("audit_documents", [])
            if row.get("path") == "audit/claim_audit.csv"
        ),
        None,
    )
    if audit is not None:
        counts = {"supported": 0, "partial": 0, "unknown": 0}
        for row in csv.DictReader(io.StringIO(audit["text"].lstrip("\ufeff"))):
            if row.get("verdict") in counts:
                counts[row["verdict"]] += 1
        stated = data.get("original_compound_counts", {})
        _require(
            all(stated.get(key) == value for key, value in counts.items())
            and stated.get("denominator") == sum(counts.values()),
            "repair compound counts differ from base audit",
        )
    papers = {(row["work_id"], row["version_id"]) for row in data["papers"]}
    _require(
        len(papers) == len(data["papers"])
        and papers <= {(row["work_id"], row["version_id"]) for row in index["papers"]},
        "repair work/version differs from base",
    )
    claims = {
        row["claim_id"]: (row["work_id"], row["version_id"]) for row in index["claims"]
    }
    atom_ids = {row["atom_id"] for row in data["atomic_revisions"]}
    _require(
        len(atom_ids) == len(data["atomic_revisions"])
        and all(
            claims.get(row["parent_claim_id"], (None,))[0] == row["work_id"]
            for row in data["atomic_revisions"]
        ),
        "repair atomic parent mapping differs",
    )
    denominator = data.get("atomic_revision_denominator", {})
    _require(
        denominator.get("entries", len(atom_ids)) == len(atom_ids)
        and denominator.get(
            "cases", len({row["parent_claim_id"] for row in data["atomic_revisions"]})
        )
        == len({row["parent_claim_id"] for row in data["atomic_revisions"]}),
        "repair atomic denominator differs",
    )
    _require(supplement["edges"] == _edges(data), "repair overlay edges differ")
    return index


def apply_repair(index, repair_root, expected_manifest_sha256, expected_review_sha256):
    """Return a non-mutating WorkspaceIndex v2 projection of an accepted repair."""
    root = private_output(repair_root)
    _require(root.is_dir(), "repair root is missing")
    manifest_raw, _, files = _manifest(root, expected_manifest_sha256)
    review_raw = _snapshot(
        root, "acceptance/actual_content_delta_review.json", expected_review_sha256
    )
    review = decode_json(review_raw)
    receipt_raw = _snapshot(root, "acceptance/final_delivery_receipt.json")
    receipt = decode_json(receipt_raw)
    _require(
        review.get("verdict") == "PASS"
        and review.get("action_hash") == expected_manifest_sha256,
        "repair independent review binding differs",
    )
    _require(
        receipt.get("candidate_manifest_sha256") == expected_manifest_sha256
        and receipt.get("independent_review_sha256") == expected_review_sha256
        and receipt.get("independent_verdict") == "PASS",
        "repair final receipt binding differs",
    )
    supplement = decode_json(
        _snapshot(
            root,
            "integrated/repair_supplement.json",
            files.get("integrated/repair_supplement.json", {}).get("sha256"),
        )
    )
    snapshots = _validate_content(index, root, supplement, files)
    prior = review.get("prior_review", {})
    _snapshot(root, prior.get("path", ""), prior.get("sha256"))
    evidence_names = {
        "checks/candidate_manifest.json",
        "acceptance/actual_content_delta_review.json",
        "acceptance/final_delivery_receipt.json",
        prior.get("path"),
        "integrated/repair_supplement.json",
        "integrated/original_input_check.json",
        "integrated/notes/beckman-et-al-1996.md",
        "integrated/notes/li-et-al-2024.md",
        "integrated/notes/Core_Findings.md",
        "beckman/passages.json",
        "beckman/failure_history.json",
        "beckman/clean/abstract.txt",
        "beckman/clean/source.txt",
        "econagent/atomic_claims.json",
        "top3/core_findings.json",
    }
    evidence = {}
    external = {
        "checks/candidate_manifest.json",
        "acceptance/actual_content_delta_review.json",
        "acceptance/final_delivery_receipt.json",
        prior.get("path"),
    }
    for name in sorted(evidence_names & (set(files) | external)):
        expected = files.get(name, {}).get("sha256")
        if name == prior.get("path"):
            expected = prior.get("sha256")
        raw = _snapshot(root, name, expected)
        evidence[name] = {"sha256": sha(raw), "text": raw.decode("utf-8")}
    result = deepcopy(index)
    result["schema_version"] = "2.0.0"
    result["supplement"] = {
        "status": "accepted-scoped-private",
        "manifest_sha256": expected_manifest_sha256,
        "review_sha256": expected_review_sha256,
        "acceptance": deepcopy(receipt),
        "data": deepcopy(supplement),
        "evidence_files": evidence,
        "edges": _edges(supplement),
    }
    _require(
        sha(manifest_raw) == expected_manifest_sha256
        and sha(review_raw) == expected_review_sha256
        and sha(receipt_raw)
        == sha(_snapshot(root, "acceptance/final_delivery_receipt.json")),
        "repair acceptance changed during projection",
    )
    for path, digest in snapshots.items():
        _require(
            sha(path.read_bytes()) == digest,
            "repair base evidence changed during projection",
        )
    _manifest(root, expected_manifest_sha256)
    canonical(result)
    return validate_repair_projection(result)
