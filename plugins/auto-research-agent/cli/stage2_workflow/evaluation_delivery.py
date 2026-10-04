"""Immutable evaluated delivery: core -> judge bundle -> projections -> manifest."""

import copy
import hashlib
import json
from html import escape
from pathlib import Path

from stage1_deliverable.common import private_output, safe_path
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_eval.evaluation_v3 import (
    CRITERIA_V3,
    DIMENSIONS_V3,
    prepare_content_view_v3,
    validate_judge_output_v3,
    validate_bundle_v3,
    merge_judgments_v3,
)
from stage2_check.report import render_proposal, _evidence_anchor
from stage2_check.report_html import render_selection_html
from stage2_check.report_evaluation import (
    validate_projection,
    render_evaluation_html,
    render_evaluation_markdown,
    evaluation_wiki_projection,
)


def _utf8(value):
    return value.decode("utf-8") if isinstance(value, bytes) else value


def _evaluation_fragment(view, presentation_version="1.0.0"):
    """Embed only the body of our escaped, validated standalone assessment."""
    document = _utf8(render_evaluation_html(view))
    if "<body>" not in document or "</body>" not in document:
        raise Stage2Error("evaluation-delivery-invalid-rendered-body")
    body = document.split("<body>", 1)[1].split("</body>", 1)[0]
    if (
        presentation_version == "1.2.0"
        and view["evaluation_status"] == "audit-required"
    ):
        for label in ("score", "status", "rationale"):
            body = body.replace(
                f"<dt>Final {label}</dt>", f"<dt>Provisional {label}</dt>"
            )
    return '<section id="external-evaluation">' + body + "</section>"


def _evaluation_markdown_fragment(view, presentation_version="1.0.0"):
    document = _utf8(render_evaluation_markdown(view))
    if (
        presentation_version == "1.2.0"
        and view["evaluation_status"] == "audit-required"
    ):
        lines = document.splitlines(keepends=True)
        for index, line in enumerate(lines):
            for label in ("score", "status", "rationale"):
                prefix = f"- Final {label}:"
                if line.startswith(prefix):
                    lines[index] = f"- Provisional {label}:" + line[len(prefix) :]
                    break
        document = "".join(lines)
    return document


def _evaluation_overview(view):
    """Expose validated dimensions before the detailed proposal, never infer null."""
    status = escape(view["evaluation_status"])
    notice = (
        "Scores and comments are provisional; the required named audit is pending."
        if view["evaluation_status"] == "audit-required"
        else "Evaluation is incomplete; unavailable scores are not zero."
        if view["evaluation_status"] != "completed"
        else "Independent assessment is complete; this is not an A/B improvement claim."
    )
    rows = []
    for name, dimension in view["dimensions"].items():
        score = (
            "Unknown"
            if dimension["score"] is None
            else f"{dimension['score']:g}% ({dimension['sum']}/6)"
        )
        rows.append(f"<tr><th>{escape(name)}</th><td>{escape(score)}</td></tr>")
    return (
        '<section id="evaluation-overview"><h2>Independent evaluation overview</h2>'
        f"<p>Status: {status}</p><p class=notice>{notice}</p>"
        "<table><thead><tr><th>Dimension</th><th>Score</th></tr></thead>"
        f"<tbody>{''.join(rows)}</tbody></table>"
        '<p><a href="#external-evaluation">Read all nine criteria, original '
        "R1/R2/ADJ comments, evidence and audit status.</a></p></section>"
    )


def _evaluated_html(selection, snapshots, view, presentation_version):
    document = _utf8(render_selection_html(selection, snapshots))
    if presentation_version in {"1.1.0", "1.2.0"}:
        document = document.replace(
            "</section>", "</section>" + _evaluation_overview(view), 1
        ).replace(
            '<a href="#brief">Brief</a>',
            '<a href="#evaluation-overview">Scores</a><a href="#brief">Brief</a>',
            1,
        )
    elif presentation_version != "1.0.0":
        raise Stage2Error("evaluation-delivery-presentation-version-invalid")
    return document.replace(
        "</main>", _evaluation_fragment(view, presentation_version) + "</main>"
    )


def _candidate_order_normalized(packet):
    if not isinstance(packet, dict) or not isinstance(packet.get("candidates"), list):
        raise Stage2Error("evaluation-delivery-selection-packet-shape")
    value = copy.deepcopy(packet)
    value["candidates"] = sorted(
        value["candidates"],
        key=canonical_hash,
    )
    return value


def workflow_source_selection_bindings(state, selection):
    """Bind a selection and delivery provenance to the current workflow snapshot."""

    if not isinstance(state, dict) or not isinstance(selection, dict):
        raise Stage2Error("evaluation-delivery-workflow-selection-shape")
    snapshot = state.get("latest_snapshot")
    if not isinstance(snapshot, dict) or not isinstance(snapshot.get("packet"), dict):
        raise Stage2Error("evaluation-delivery-workflow-snapshot-shape")
    packet = snapshot["packet"]
    if selection.get("packet_sha256") != canonical_hash(packet):
        raise Stage2Error("evaluation-delivery-selection-current-packet-mismatch")
    if _candidate_order_normalized(
        selection.get("evaluation_packet")
    ) != _candidate_order_normalized(packet):
        raise Stage2Error("evaluation-delivery-selection-current-snapshot-mismatch")
    checker = snapshot.get("checker")
    try:
        stored_packet_sha256 = checker["manifest"]["stored_packet_sha256"]
        event_head = state["head_sha256"]
    except (KeyError, TypeError) as error:
        raise Stage2Error("evaluation-delivery-workflow-binding-shape") from error
    return {
        "event_head": event_head,
        "stored_packet_sha256": stored_packet_sha256,
    }


def evaluation_projection(bundle, selection, source_root, *, expected_bundle_sha256):
    """Verify source bytes and judgments before exposing their comments and scores."""
    if canonical_hash(bundle) != expected_bundle_sha256:
        raise Stage2Error("evaluation-delivery-external-bundle-hash-mismatch")
    packet = selection["evaluation_packet"]
    validate_packet(packet, source_root)
    if (
        bundle.get("kind") != "Stage2EvaluationBundle"
        or bundle.get("schema_version") != "3.0.0"
    ):
        raise Stage2Error("evaluation-delivery-wrong-bundle-version")
    if bundle.get("core_selection_sha256") != canonical_hash(selection) or bundle.get(
        "sources_sha256"
    ) != canonical_hash(packet["sources"]):
        raise Stage2Error("evaluation-delivery-science-binding-mismatch")
    content = bundle.get("content_view")
    expected = prepare_content_view_v3(
        packet,
        content.get("subject_id"),
        content.get("input_sha256"),
        content.get("config_sha256"),
    )
    if (
        content != expected
        or content["input_sha256"] != canonical_hash(selection)
        or content["rubric_sha256"] != bundle.get("rubric_sha256")
    ):
        raise Stage2Error("evaluation-delivery-content-binding-mismatch")
    judgments = bundle.get("judgments", {})
    actions = bundle.get("action_views", {})
    for role, judgment in judgments.items():
        if role not in {"R1", "R2", "ADJ"} or judgment.get("role") != role:
            raise Stage2Error("evaluation-delivery-judge-role-mismatch")
        validate_judge_output_v3(judgment, content, actions[role], packet)
        if actions[role]["action_record"] != selection["action_record"]:
            raise Stage2Error("evaluation-delivery-action-record-mismatch")
    if bundle.get("merged") is not None:
        validate_bundle_v3(bundle["merged"])
        raw = bundle["merged"]["raw"]
        if (
            raw["r1"] != judgments["R1"]
            or raw["r2"] != judgments["R2"]
            or raw.get("adj") != judgments.get("ADJ")
        ):
            raise Stage2Error("evaluation-delivery-merged-judgment-mismatch")
    status = bundle.get("status")
    if status == "complete":
        if bundle.get("merged") is None or not bundle["merged"].get("usable"):
            raise Stage2Error("evaluation-delivery-complete-needs-validated-merge")
    elif status == "audit-required":
        if bundle.get("merged") is not None or not {"R1", "R2"}.issubset(judgments):
            raise Stage2Error("evaluation-delivery-invalid-pending-audit")
        try:
            merge_judgments_v3(
                judgments["R1"],
                judgments["R2"],
                content,
                actions["R1"],
                packet,
                action_view_r2=actions["R2"],
                adj=judgments.get("ADJ"),
                action_view_adj=actions.get("ADJ"),
                audit=None,
            )
        except Stage2Error as error:
            if "named audit" not in str(error):
                raise
        else:
            raise Stage2Error("evaluation-delivery-pending-audit-not-required")
    elif status != "failed":
        raise Stage2Error("evaluation-delivery-invalid-evaluation-status")
    completed = (
        bundle.get("status") in {"complete", "audit-required"}
        and {"R1", "R2"}.issubset(judgments)
        and all(row["evaluator_status"] == "complete" for row in judgments.values())
    )
    selected = judgments.get("ADJ") or judgments.get("R1")
    evidence = {row["evidence_id"]: row for row in packet["evidence"]}

    def project(row, judgment, *, final=False):
        value = {
            "score": row["score"],
            "status": row["status"],
            "rationale": row["rationale"],
            "confidence": judgment["confidence"],
            "unknown_reason": row["unknown_reason"],
            "evidence_refs": [
                {
                    "evidence_id": key,
                    "locator": evidence[key]["locator"],
                    "href": "#" + _evidence_anchor(key),
                }
                for key in row["evidence_ids"]
            ],
        }
        if final:
            value["audit_status"] = (
                "required"
                if bundle["status"] == "audit-required"
                else bundle.get("merged", {}).get("audit_status", "not-required")
            )
        return value

    rows = []
    if judgments:
        role_rows = {
            role: {row["criterion_id"]: row for row in judgment["criteria"]}
            for role, judgment in judgments.items()
        }
        for key in CRITERIA_V3:
            r1 = role_rows.get("R1", {}).get(key)
            r2 = role_rows.get("R2", {}).get(key)

            def signature(row):
                return row["status"], row["score"]

            disagreement = (
                r1 is not None
                and r2 is not None
                and (
                    signature(r1) != signature(r2)
                    or judgments["R1"]["major_error_ids"]
                    != judgments["R2"]["major_error_ids"]
                )
            )
            if completed and disagreement and "ADJ" not in judgments:
                raise Stage2Error("evaluation-delivery-missing-adjudication")
            rows.append(
                {
                    "criterion_id": key,
                    "final": project(
                        role_rows[selected["role"]][key], selected, final=True
                    )
                    if completed
                    else {
                        "score": None,
                        "status": "unknown",
                        "rationale": "Independent assessment is incomplete; retained comments are provisional.",
                        "evidence_refs": [],
                        "confidence": "low",
                        "unknown_reason": bundle.get("failure")
                        or "Required reviewer is unavailable.",
                        "audit_status": "assessment-incomplete",
                    },
                    "judges": {
                        role: project(role_rows[role][key], judgments[role])
                        if role in judgments
                        else None
                        for role in ("R1", "R2", "ADJ")
                    },
                    "disagreement": disagreement,
                }
            )
    dimensions = {}
    for dimension, keys in DIMENSIONS_V3.items():
        selected_rows = [row["final"] for row in rows if row["criterion_id"] in keys]
        assessed = sum(row["status"] == "assessed" for row in selected_rows)
        total = sum(row["score"] for row in selected_rows) if assessed == 3 else None
        dimensions[dimension] = {
            "score": round(100 * total / 6, 6) if total is not None else None,
            "sum": total,
            "max": 6,
            "assessed": assessed,
            "required": 3,
        }
    view = {
        "rubric_id": "stage2-general-v3",
        "evaluation_status": (
            "audit-required" if bundle["status"] == "audit-required" else "completed"
        )
        if completed
        else "failed",
        "dimensions": dimensions,
        "rows": rows,
        "provenance": {
            "selection_sha256": canonical_hash(selection),
            "source_sha256": bundle["sources_sha256"],
            "rubric_sha256": bundle["rubric_sha256"],
            "bundle_sha256": expected_bundle_sha256,
        },
        "errors": []
        if completed
        else [
            bundle.get("failure")
            or "Independent assessment is incomplete; unknown is not zero."
        ],
    }
    return validate_projection(view)


def build_evaluated_delivery(
    selection,
    source_snapshots,
    source_root,
    bundle,
    output_dir,
    *,
    expected_bundle_sha256,
    event_head,
    stored_packet_sha256,
):
    """Produce editable Markdown, HTML and wiki from the same verified projection."""
    view = evaluation_projection(
        bundle, selection, source_root, expected_bundle_sha256=expected_bundle_sha256
    )
    html = _evaluated_html(selection, source_snapshots, view, "1.2.0")
    markdown = render_proposal(
        selection,
        source_snapshots,
        event_head=event_head,
        stored_packet_sha256=stored_packet_sha256,
    )
    if isinstance(markdown, bytes):
        markdown = markdown.decode("utf-8")
    markdown += "\n\n" + _evaluation_markdown_fragment(view, "1.2.0")
    destination = private_output(output_dir)
    if destination.exists():
        raise Stage2Error("evaluation-delivery-output-already-exists")
    destination.mkdir(parents=True)
    values = {
        "core_selection.json": selection,
        "evaluation_bundle.json": bundle,
        "evaluation_projection.json": view,
        "wiki_projection.json": evaluation_wiki_projection(view),
        "selection.html": html.encode("utf-8"),
        "selection.md": markdown.encode("utf-8"),
    }
    for source in selection["evaluation_packet"]["sources"]:
        path = safe_path(source_root, source["path"])
        values["sources/" + source["path"]] = path.read_bytes()
    inventory = []
    for name, value in values.items():
        raw = (
            value
            if isinstance(value, bytes)
            else json.dumps(
                value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode("utf-8")
        )
        path = safe_path(destination, name)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
        inventory.append(
            {"path": name, "sha256": hashlib.sha256(raw).hexdigest(), "bytes": len(raw)}
        )
    manifest = {
        "kind": "Stage2EvaluatedDelivery",
        "schema_version": "3.0.0",
        "presentation_version": "1.2.0",
        "core_selection_sha256": canonical_hash(selection),
        "bundle_sha256": expected_bundle_sha256,
        "event_head": event_head,
        "stored_packet_sha256": stored_packet_sha256,
        "evaluation_status": view["evaluation_status"],
        "artifacts": inventory,
        "human_selection": "pending",
        "stage3_authorized": False,
        "formal_ready": False,
        "improvement_demonstrated": False,
    }
    manifest["manifest_sha256"] = canonical_hash(manifest)
    (destination / "evaluation_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest


def inspect_evaluated_delivery(output_dir, *, expected_manifest_sha256):
    """Recompute a delivery from an externally retained manifest receipt."""
    root = Path(output_dir).resolve()
    manifest = json.loads((root / "evaluation_manifest.json").read_bytes())
    unsigned = {
        key: value for key, value in manifest.items() if key != "manifest_sha256"
    }
    if (
        canonical_hash(unsigned) != expected_manifest_sha256
        or manifest.get("manifest_sha256") != expected_manifest_sha256
    ):
        raise Stage2Error("evaluation-delivery-manifest-receipt-mismatch")
    names = [row["path"] for row in manifest["artifacts"]]
    actual = [
        path.relative_to(root).as_posix()
        for path in root.rglob("*")
        if path.is_file() and path.name != "evaluation_manifest.json"
    ]
    if len(names) != len(set(names)) or set(names) != set(actual):
        raise Stage2Error("evaluation-delivery-inventory-mismatch")
    for row in manifest["artifacts"]:
        raw = safe_path(root, row["path"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != row["sha256"] or len(raw) != row["bytes"]:
            raise Stage2Error("evaluation-delivery-artifact-changed")
    selection = json.loads((root / "core_selection.json").read_bytes())
    bundle = json.loads((root / "evaluation_bundle.json").read_bytes())
    projection = evaluation_projection(
        bundle,
        selection,
        root / "sources",
        expected_bundle_sha256=manifest["bundle_sha256"],
    )
    if json.loads(
        (root / "evaluation_projection.json").read_bytes()
    ) != projection or json.loads(
        (root / "wiki_projection.json").read_bytes()
    ) != evaluation_wiki_projection(projection):
        raise Stage2Error("evaluation-delivery-projection-changed")
    snapshots = [
        {**source, "path": "sources/" + source["path"]}
        for source in selection["evaluation_packet"]["sources"]
    ]
    html = _evaluated_html(
        selection,
        snapshots,
        projection,
        manifest.get("presentation_version", "1.0.0"),
    )
    markdown = render_proposal(
        selection,
        snapshots,
        event_head=manifest["event_head"],
        stored_packet_sha256=manifest["stored_packet_sha256"],
    )
    if isinstance(markdown, bytes):
        markdown = markdown.decode("utf-8")
    markdown += "\n\n" + _evaluation_markdown_fragment(
        projection, manifest.get("presentation_version", "1.0.0")
    )
    if (root / "selection.html").read_bytes() != html.encode("utf-8") or (
        root / "selection.md"
    ).read_bytes() != markdown.encode("utf-8"):
        raise Stage2Error("evaluation-delivery-rendering-changed")
    return manifest
