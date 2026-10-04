"""Build a non-sufficient Stage 2 seed from a reviewed Stage 1 deliverable."""

from __future__ import annotations

import copy
from pathlib import Path
import shutil

from stage1_brief.brief import validate_brief
from stage1_deliverable import package as deliverable_package
from stage1_deliverable.common import (
    DeliverableError,
    private_output,
    read_json,
    reject_links,
)
from stage1_ledger.journal import LedgerError
from stage2_common import (
    Stage2Error,
    canonical_hash,
    stage1_projection_hash,
    validate_packet,
)

from .import_stage1 import (
    _canonical_bytes,
    _comparison_for_papers,
    _project_stage1,
    _read_bound_json,
    _revalidate_deliverable,
    _unresolved,
)


_ACCEPTANCE_FIELDS = {
    "kind",
    "schema_version",
    "accepted_by",
    "decision_source_ref",
    "purpose",
    "deliverable_manifest_sha256",
    "stage1_records_sha256",
    "research_brief_sha256",
    "resources_sha256",
    "included_work_ids",
    "limitations",
}


def _nonempty_text(value):
    return isinstance(value, str) and bool(value.strip())


def _plain_input_path(path, label):
    supplied = Path(path)
    if ".." in supplied.parts:
        raise Stage2Error(f"{label}-path-traversal")
    absolute = supplied.absolute()
    try:
        reject_links(absolute)
    except DeliverableError as error:
        raise Stage2Error(f"{label}-link-rejected") from error
    return absolute.resolve()


def _validate_acceptance(
    acceptance,
    *,
    deliverable_manifest_sha256,
    stage1_records_sha256,
    research_brief_sha256,
    resources_sha256,
    known_work_ids,
):
    if not isinstance(acceptance, dict) or set(acceptance) != _ACCEPTANCE_FIELDS:
        raise Stage2Error("stage2-exploratory-acceptance-fields-invalid")
    if (
        acceptance["kind"] != "Stage2ExploratoryAcceptance"
        or acceptance["schema_version"] != "1.0.0"
        or acceptance["purpose"] != "exploratory-stage2-planning"
    ):
        raise Stage2Error("stage2-exploratory-acceptance-contract-invalid")
    if not _nonempty_text(acceptance["accepted_by"]):
        raise Stage2Error("stage2-exploratory-accepted-by-invalid")
    if not _nonempty_text(acceptance["decision_source_ref"]):
        raise Stage2Error("stage2-exploratory-decision-source-ref-invalid")

    expected_hashes = {
        "deliverable_manifest_sha256": deliverable_manifest_sha256,
        "stage1_records_sha256": stage1_records_sha256,
        "research_brief_sha256": research_brief_sha256,
        "resources_sha256": resources_sha256,
    }
    for field, expected in expected_hashes.items():
        if acceptance[field] != expected:
            raise Stage2Error(f"stage2-exploratory-{field.replace('_', '-')}-mismatch")

    included = acceptance["included_work_ids"]
    if (
        not isinstance(included, list)
        or not included
        or any(not _nonempty_text(work_id) for work_id in included)
        or len(included) != len(set(included))
    ):
        raise Stage2Error("stage2-exploratory-included-work-ids-invalid")
    unknown = set(included) - set(known_work_ids)
    if unknown:
        raise Stage2Error(
            "stage2-exploratory-included-work-id-unknown: " + sorted(unknown)[0]
        )

    limitations = acceptance["limitations"]
    if (
        not isinstance(limitations, list)
        or not limitations
        or any(not _nonempty_text(item) for item in limitations)
    ):
        raise Stage2Error("stage2-exploratory-limitations-invalid")
    return set(included)


def build_exploratory_seed(
    deliverable_dir,
    deliverable_manifest_sha256,
    acceptance_path,
    acceptance_sha256,
    brief_path,
    resources_path,
    output_dir,
):
    """Create an unstarted exploratory packet without claiming Stage 1 sufficiency."""

    output = Path(output_dir).absolute()
    owned_output = False
    try:
        deliverable_root = _plain_input_path(deliverable_dir, "stage1-deliverable")
        output = private_output(output)
        if output.exists():
            raise Stage2Error(f"stage1-stage2-output-exists: {output}")
        deliverable_package.validate(deliverable_root, deliverable_manifest_sha256)
        manifest = _read_bound_json(
            deliverable_root / "provenance_manifest.json",
            deliverable_manifest_sha256,
            "stage1-deliverable-manifest",
        )
        records = manifest["canonical_records"]
        records_sha256 = manifest["original_input_sha256"]
        brief = read_json(_plain_input_path(brief_path, "stage2-exploratory-brief"))
        if not isinstance(brief, dict):
            raise Stage2Error("stage2-exploratory-brief-invalid")
        try:
            validate_brief(brief, require_confirmed=True)
        except (AttributeError, KeyError, TypeError, ValueError) as error:
            raise Stage2Error("stage2-exploratory-brief-invalid") from error
        resources = (
            _plain_input_path(resources_path, "stage2-exploratory-resources")
            .read_text(encoding="utf-8")
            .strip()
        )
        if not resources:
            raise Stage2Error("stage1-stage2-resources-empty")
        acceptance = _read_bound_json(
            _plain_input_path(acceptance_path, "stage2-exploratory-acceptance"),
            acceptance_sha256,
            "stage2-exploratory-acceptance",
        )

        papers = {row["work_id"]: row for row in records["papers"]}
        brief_sha256 = canonical_hash(brief)
        resources_sha256 = canonical_hash(resources)
        included = _validate_acceptance(
            acceptance,
            deliverable_manifest_sha256=deliverable_manifest_sha256,
            stage1_records_sha256=records_sha256,
            research_brief_sha256=brief_sha256,
            resources_sha256=resources_sha256,
            known_work_ids=papers,
        )

        output.mkdir(parents=False)
        owned_output = True
        reject_links(output)
        literature, stage2_sources, evidence, unavailable = _project_stage1(
            deliverable_root, output, records, included
        )
        unsigned_upstream = {
            "kind": "Stage1Stage2Binding",
            "schema_version": "2.0.0",
            "source_run_id": f"exploratory:{records_sha256[:16]}",
            "source_state_sha256": records_sha256,
            "stage1_handoff_sha256": None,
            "stage1_deliverable_manifest_sha256": deliverable_manifest_sha256,
            "stage1_records_sha256": records_sha256,
            "research_brief_sha256": brief_sha256,
            "resources_sha256": resources_sha256,
            "stage1_literature_sha256": stage1_projection_hash(literature),
            "stage1_sources_sha256": stage1_projection_hash(
                stage2_sources, omit={"path"}
            ),
            "stage1_evidence_sha256": stage1_projection_hash(evidence),
            "included_work_ids": copy.deepcopy(acceptance["included_work_ids"]),
            "eligible_for_stage2": False,
            "stage2": {"status": "not-started", "execution_authorized": False},
            "intake_mode": "exploratory",
            "acceptance": copy.deepcopy(acceptance),
            "acceptance_sha256": canonical_hash(acceptance),
            "acceptance_file_sha256": acceptance_sha256,
        }
        upstream = {
            **unsigned_upstream,
            "binding_sha256": canonical_hash(unsigned_upstream),
        }
        packet = {
            "kind": "Stage2Packet",
            "schema_version": "2.1.0",
            "packet_id": f"stage2-seed-{upstream['binding_sha256'][:16]}",
            "brief": brief,
            "resources": resources,
            "comparison": _comparison_for_papers(
                [papers[work_id] for work_id in sorted(included)]
            ),
            "literature": literature,
            "evidence": evidence,
            "sources": stage2_sources,
            "candidates": [],
            "unresolved": _unresolved(records, unavailable, included)
            + copy.deepcopy(acceptance["limitations"]),
            "upstream": upstream,
        }
        _revalidate_deliverable(deliverable_root, deliverable_manifest_sha256, manifest)
        validate_packet(packet, output)
        (output / "packet.json").write_bytes(_canonical_bytes(packet))
        return {
            "kind": "Stage1Stage2ImportReceipt",
            "schema_version": "2.0.0",
            "status": "ready-for-explicit-exploratory-stage2-start",
            "intake_mode": "exploratory",
            "scientific_sufficiency": "not-established",
            "packet_path": "packet.json",
            "packet_sha256": canonical_hash(packet),
            "binding_sha256": upstream["binding_sha256"],
            "acceptance_file_sha256": acceptance_sha256,
            "source_count": len(stage2_sources),
            "evidence_count": len(evidence),
            "candidate_count": 0,
            "stage2_execution_authorized": False,
        }
    except (DeliverableError, LedgerError, OSError, ValueError) as error:
        if owned_output and output.exists():
            reject_links(output)
            shutil.rmtree(output)
        if isinstance(error, Stage2Error):
            raise
        raise Stage2Error(
            f"stage1-stage2-exploratory-import-failed: {error}"
        ) from error
    except Exception:
        if owned_output and output.exists():
            reject_links(output)
            shutil.rmtree(output)
        raise
