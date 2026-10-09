"""Build a private read-only view; canonical research records remain unchanged."""

import argparse
import json
from pathlib import Path

from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    private_output,
    safe_path,
    sha,
)

from .json_bytes import decode_json
from .projection import validate_index
from .wiki import wiki_files

REFERENCE_COMMIT = "085f363179a79375fc8e3590dda9725e25eda71a"
REFERENCE_HASHES = {
    "prototype.html": "dfd49e7d0baf5cbf1645a08c34dafb48bba7b3db9d867adf313e91b1a810298e",
    "literature-reference.js": "6a6cad0f744988da523cf548f9e0013269ac3c96d0366d208d63815128305b55",
    "workspace-i18n.js": "d24fadd875728abfdd9d6a1734f430d82abf80ecf4538cf959d91245ce1bc24d",
    "workspace.css": "7d61618949a42c9afdbbdedcad2556bf71a0d647c5d33b950063100cc932f4e4",
}


def _replace(value, old, new):
    if old not in value:
        raise DeliverableError("reference template contract changed")
    return value.replace(old, new)


def _literature(source):
    source = (
        source[: source.index("  const freezeRecord")]
        + source[source.index("  const svgNS") :]
    )
    start, end = source.index("  function bibEscape"), source.index("  function render")
    source = source[:start] + source[end:]
    changes = {
        "function render(root, records = demoRecords)": "function render(root, records, hooks)",
        "let selectedId = records[0]?.workId || null;": "let selectedId = hooks.selectedId || records[0]?.workId || null;",
        'const filters = { text: "", keyword: "", role: "" };': 'const filters = { text: "", keyword: "", role: "", ...hooks.filters };',
        "root.append(toolbar);": "textFilter.value = filters.text; keywordFilter.value = filters.keyword; roleFilter.value = filters.role; root.append(toolbar);",
        "Stage 1 / Synthetic Literature Reference": "Stage 1 / Bound literature records",
        "Export visible .bib (synthetic)": "Export canonical .bib",
        "Synthetic literature graph of papers, keywords, and recorded roles": "Recorded paper-to-keyword and paper-to-role assignments",
        "Synthetic UI demo only. Every source is metadata-only; no record represents full-text access. BibTeX export is separate from the canonical research deliverable exporter.": "Read-only projection of the original package. Source access and claim judgments remain unchanged.",
        "No synthetic records match these filters.": "No records match these filters.",
        "synthetic records visible": "records visible",
        "keywords": "classifications",
        "Keyword": "Classification",
        "keyword assignment": "classification assignment",
        '["Work ID", paper.workId]': '["Work ID", paper.identity]',
        "          paper.workId,\n          paper.title,": "          paper.identity,\n          paper.title,",
        '      detail.append(source("strong", paper.title));': '      hooks.select(paper.workId);\n      detail.append(source("strong", paper.title));',
        '      paper.roles.forEach((role) => detail.append(source("p", `${role.name}: ${role.basis}`)));': '      paper.roles.forEach((role) => detail.append(source("p", `${role.name}: ${role.basis}`)));\n      hooks.detail(detail, paper);',
        '        const row = create("tr");': '        const row = create("tr"); row.tabIndex = 0; row.dataset.paperId = paper.workId; row.onclick = () => setSelection(paper.workId); row.onkeydown = (event) => { if (event.key === "Enter") setSelection(paper.workId); };',
        "    toBibTeX,\n    demoRecords,\n": "",
    }
    for old, new in changes.items():
        source = _replace(source, old, new)
    start, end = (
        source.index("    exportButton.onclick ="),
        source.index("    updateAll();\n  }"),
    )
    return (
        source[:start]
        + "    exportButton.onclick = () => hooks.export(visible());\n"
        + source[end:]
    )


def render_view(
    index_path, output, reference_root, expected_index_sha256, *, atlas=False
):
    """Bind an externally approved index and pinned presentation assets to a new view."""
    index_path = private_output(index_path)
    raw = Path(index_path).read_bytes()
    if sha(raw) != expected_index_sha256:
        raise DeliverableError("WorkspaceIndex hash differs")
    index = decode_json(raw)
    options = {}
    if index.get("schema_version") == "3.0.0":
        options["source_rerun_root"] = Path(index_path).parent / "source-rerun"
    if atlas:
        options["atlas"] = True
    return _write_view(index, raw, reference_root, output, **options)


def write_workspace(
    index,
    reference_root,
    output_dir,
    *,
    stage2_delivery=None,
    stage2_bridge=None,
    expected_stage2_bridge_sha256=None,
    source_rerun_root=None,
    atlas=False,
):
    """Write a freshly projected index with its canonical-byte receipt."""
    return _write_view(
        index,
        canonical(index),
        reference_root,
        output_dir,
        stage2_delivery=stage2_delivery,
        stage2_bridge=stage2_bridge,
        expected_stage2_bridge_sha256=expected_stage2_bridge_sha256,
        source_rerun_root=source_rerun_root,
        atlas=atlas,
    )


def _write_view(
    index,
    raw,
    reference_root,
    output,
    *,
    stage2_delivery=None,
    stage2_bridge=None,
    expected_stage2_bridge_sha256=None,
    source_rerun_root=None,
    atlas=False,
):
    validate_index(index)
    if index["schema_version"] in {"2.0.0", "3.0.0"}:
        index = decode_json(canonical(index))
    stage2_attachment, stage2_files = None, {}
    supplied = (stage2_delivery, stage2_bridge, expected_stage2_bridge_sha256)
    if any(value is not None for value in supplied):
        if not all(value is not None for value in supplied):
            raise DeliverableError(
                "Stage 2 delivery, bridge and receipt hash are required"
            )
        from .stage2_import import import_evaluated_delivery
        from .stage2_presentation import render_stage2_card, stage2_wiki_notes

        stage2_attachment, stage2_files = import_evaluated_delivery(
            index,
            stage2_delivery,
            stage2_bridge,
            expected_bridge_sha256=expected_stage2_bridge_sha256,
        )
        stage2_files.update(stage2_wiki_notes(stage2_attachment))
    expected_index_sha256 = sha(raw)
    if index.get("kind") != "WorkspaceIndex" or index.get("schema_version") not in {
        "1.0.0",
        "2.0.0",
        "3.0.0",
    }:
        raise DeliverableError("unsupported WorkspaceIndex")
    identities = [(p["work_id"], p["version_id"]) for p in index["papers"]]
    if len(set(identities)) != len(identities):
        raise DeliverableError("duplicate work/version identity")
    destination = private_output(output)
    if destination.exists():
        raise DeliverableError("view output must be a new directory")
    assets = {}
    for name, expected in REFERENCE_HASHES.items():
        raw_asset = safe_path(reference_root, name).read_bytes()
        if sha(raw_asset) != expected:
            raise DeliverableError("reference asset hash differs: " + name)
        assets[name] = raw_asset.decode("utf-8").replace("\r\n", "\n")
    html = assets["prototype.html"].split('    <script src="./workspace-i18n.js">')[0]
    html = _replace(
        html,
        "<title>Research Workspace | Offline Interaction Reference</title>",
        "<title>Research Workspace | Read-only package view</title>",
    )
    html = _replace(
        html,
        "SYNTHETIC DATA · OFFLINE WORKFLOW PROTOTYPE · EXECUTOR NOT\n              CONNECTED",
        "BOUND SOURCE RECORDS · READ-ONLY · EXECUTOR NOT CONNECTED",
    )
    html = _replace(
        html,
        "A readable, traceable editorial desk for research workflows. This\n              page demonstrates information architecture only; every record is\n              synthetic.",
        "Read the original package without changing its evidence, judgments or execution state.",
    )
    html = _replace(
        html,
        "Offline interaction reference · Refreshing resets this prototype only.\n        It cannot execute research or modify canonical records; only synthetic\n        bibliography export is available.",
        "Read-only projection of the original package. Source access and claim judgments remain unchanged.",
    )
    html = html.replace("Offline interaction reference", "Read-only package view")
    if stage2_attachment is not None:
        stage2_card = render_stage2_card(stage2_attachment).replace(
            '<section id="stage2-delivery">',
            '<section id="stage2-delivery" hidden>',
            1,
        )
        html = _replace(html, "</header>", "</header>" + stage2_card)
    html = html.replace(
        "<head>",
        "<head>\n<meta http-equiv=\"Content-Security-Policy\" content=\"default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; connect-src 'none'; object-src 'none'; base-uri 'none'; form-action 'none'\">",
    )
    script_names = ["workspace-i18n.js", "literature-reference.js", "workspace-data.js"]
    repaired = (
        index["schema_version"] in {"2.0.0", "3.0.0"}
        and index["supplement"]["status"] != "not-provided"
    )
    rerun = index["schema_version"] == "3.0.0"
    if repaired:
        html = _replace(html, "<body>", '<body class="stage1-closeout">')
        html = _replace(
            html,
            "</head>",
            '<link rel="stylesheet" href="./workspace-closeout.css">\n</head>',
        )
        script_names.append("workspace-repairs.js")
    if rerun:
        html = _replace(
            html,
            "</head>",
            '<link rel="stylesheet" href="./workspace-source-rerun.css">\n</head>',
        )
        script_names.append("workspace-source-rerun.js")
    html = _replace(
        html,
        "</head>",
        '<link rel="stylesheet" href="./workspace-selection.css">\n</head>',
    )
    script_names.append("workspace-literature-selection.js")
    script_names.append("workspace-records.js")
    if stage2_attachment is not None:
        html = html.replace("<body>", '<body class="stage2-workspace">').replace(
            '<body class="stage1-closeout">',
            '<body class="stage1-closeout stage2-workspace">',
        )
        html = _replace(
            html,
            "</head>",
            '<link rel="stylesheet" href="./workspace-stage2.css">\n</head>',
        )
        script_names.append("workspace-stage2.js")
    html += (
        "".join(f'<script src="./{name}"></script>\n' for name in script_names)
        + "</body></html>\n"
    )
    i18n = _replace(
        assets["workspace-i18n.js"],
        "window.WorkspaceI18n = { apply, t,",
        "window.WorkspaceI18n = { extend(rows) { rows.forEach(([key, ...values]) => catalog.set(key, values)); }, apply, t,",
    )
    notes = wiki_files(index)
    payload = {
        "index": index,
        "index_sha256": expected_index_sha256,
        "note_paths": [
            {
                "work_id": paper["work_id"],
                "version_id": paper["version_id"],
                "path": "wiki/"
                + sha(canonical([paper["work_id"], paper["version_id"]]))
                + ".md",
            }
            for paper in index["papers"]
        ],
    }
    if repaired:
        for row in payload["note_paths"]:
            row["text"] = notes[row["path"]].decode("utf-8")
    if rerun:
        from .source_availability import derive_source_availability

        payload["source_availability"] = derive_source_availability(index)
    from .literature_selection import derive_literature_selection, selection_files

    payload["literature_selection"] = derive_literature_selection(index)
    if stage2_attachment is not None:
        payload["stage2"] = stage2_attachment
    encoded = (
        json.dumps(payload, ensure_ascii=True)
        .replace("<", "\\u003c")
        .replace(">", "\\u003e")
        .replace("&", "\\u0026")
    )
    adapter = (
        Path(__file__).parents[2] / "references/research-workspace/workspace-records.js"
    )
    css = (
        assets["workspace.css"]
        + "\npre{white-space:pre-wrap;overflow-wrap:anywhere;max-height:420px;overflow:auto} details{margin:12px 0} .node-list p,.detail p{overflow-wrap:anywhere}\n"
    )
    if stage2_attachment is not None:
        css += (
            "\n#stage2-delivery{margin:24px;padding:24px;background:#fff;"
            "border:1px solid #d4dce6;border-radius:12px;overflow-wrap:anywhere}"
            "#stage2-delivery h2{margin-top:0}"
            "#stage2-delivery li{margin-bottom:16px}"
            "#stage2-delivery dd{margin:4px 0 12px 16px}"
            "#stage2-delivery summary{cursor:pointer;padding:12px;background:#eef3f9}"
            "#stage2-delivery .stage2-audit{padding:12px;background:#fff5db}"
            "@media(max-width:600px){#stage2-delivery{margin:12px;padding:16px}}\n"
        )
    files = {
        "index.html": html.encode(),
        "workspace.css": css.encode(),
        "workspace-i18n.js": i18n.encode(),
        "literature-reference.js": _literature(
            assets["literature-reference.js"]
        ).encode(),
        "workspace-data.js": ("window.WORKSPACE_VIEW = " + encoded + ";\n").encode(),
        "workspace-records.js": adapter.read_bytes(),
        "workspace-literature-selection.js": adapter.with_name(
            "workspace-literature-selection.js"
        ).read_bytes(),
        "workspace-selection.css": adapter.with_name(
            "workspace-selection.css"
        ).read_bytes(),
        "workspace-index.json": raw,
        "references.bib": (
            index["source_rerun"]["bibliography"] if rerun else index["bibliography"]
        )["all_bibtex"].encode("utf-8"),
        **notes,
        **stage2_files,
    }
    files.update(selection_files(index))
    if atlas:
        from .atlas import atlas_files

        files.update(atlas_files(payload))
        files["index.html"] = files["index.html"].replace(
            b"</header>",
            b'<p><a href="atlas.html">Open literature map and comparison atlas</a></p></header>',
            1,
        )
    if repaired:
        from .closeout import closeout_files

        files.update(closeout_files(index))
        files["workspace-repairs.js"] = adapter.with_name(
            "workspace-repairs.js"
        ).read_bytes()
        files["workspace-closeout.css"] = adapter.with_name(
            "workspace-closeout.css"
        ).read_bytes()
    if rerun:
        from .source_rerun import rerun_files

        if source_rerun_root is None:
            raise DeliverableError("source rerun artifacts are required")
        files.update(rerun_files(index, source_rerun_root))
        for name in ("workspace-source-rerun.js", "workspace-source-rerun.css"):
            files[name] = adapter.with_name(name).read_bytes()
    if stage2_attachment is not None:
        from .stage2_comparison import build_comparison_view

        files["stage2/comparison-view.json"] = canonical(
            build_comparison_view(stage2_attachment)
        )
        for asset_name in ("workspace-stage2.js", "workspace-stage2.css"):
            files[asset_name] = adapter.with_name(asset_name).read_bytes()
        files["wiki/README.md"] += (
            b"\n## Stage 2 direction proposal and independent assessment\n\n"
            b"[Read the Stage 2 notes](../stage2/README.md). "
            b"[Open the proposal](../stage2/report-reader.html). "
            b"Unknowns and pending audits remain unresolved.\n"
        )
    manifest = {
        "kind": "WorkspaceReadOnlyView",
        "index_sha256": expected_index_sha256,
        "reference_commit": REFERENCE_COMMIT,
        "reference_assets": REFERENCE_HASHES,
        "reference_provenance": {
            "commit_role": "historical-reference-base",
            "asset_binding": "exact reference_assets SHA-256 values",
            "commit_alone_reconstructs_assets": False,
        },
        "bibtex_producer": index["bibliography"]["producer"],
        "files": {name: sha(data) for name, data in files.items()},
        "research_execution": "not-performed",
        "rebuild": {
            "entrypoint": "python -m research_workspace",
            "project_id": index["project_id"],
            "expected_manifest_sha256": index["provenance"]["package_manifest_sha256"],
            "reference_commit": REFERENCE_COMMIT,
            "reference_asset_policy": "use exact reference_assets hashes; commit is historical provenance",
            "output_policy": "new directory outside Git",
            "validation_mode": "byte-inventory",
        },
        "adapter_sources": {
            name: sha(Path(__file__).with_name(name).read_bytes())
            for name in (
                "__main__.py",
                "projection.py",
                "stages.py",
                "view.py",
                "wiki.py",
                "literature_selection.py",
                "body_completeness.py",
                "body_review.py",
                "body_review_attachment.py",
                "json_bytes.py",
                "WorkspaceIndex.v1.schema.json",
            )
        },
        "ui_sources": {
            name: sha(adapter.with_name(name).read_bytes())
            for name in (
                "workspace-records.js",
                "workspace-literature-selection.js",
                "workspace-selection.css",
            )
        },
    }
    if atlas:
        manifest["rebuild"]["atlas"] = True
        manifest["atlas_binding_sha256"] = sha(files["atlas-binding.json"])
        for name in ("atlas.py", "atlas_model.py"):
            manifest["adapter_sources"][name] = sha(
                Path(__file__).with_name(name).read_bytes()
            )
        manifest["ui_sources"].update(
            {
                name: sha(files[name])
                for name in ("atlas.html", "atlas.css", "atlas-model.js", "atlas-ui.js")
            }
        )
    if repaired:
        from .closeout import runtime_binding

        manifest["repair_binding"] = {
            "manifest_sha256": index["supplement"]["manifest_sha256"],
            "review_sha256": index["supplement"]["review_sha256"],
            "runtime": runtime_binding(),
            "original_replay_upgraded": False,
        }
        manifest["adapter_sources"].update(
            {
                name: sha(Path(__file__).with_name(name).read_bytes())
                for name in (
                    "repair.py",
                    "closeout.py",
                    "WorkspaceIndex.v2.schema.json",
                )
            }
        )
    if rerun:
        manifest["source_rerun_binding"] = {
            "manifest_sha256": index["source_rerun"]["manifest_sha256"],
            "parser_runtime": index["source_rerun"]["data"]["parser_runtime"],
            "original_claims_changed": False,
            "scientific_quality_scored": False,
        }
        manifest["adapter_sources"]["source_rerun.py"] = sha(
            Path(__file__).with_name("source_rerun.py").read_bytes()
        )
        manifest["adapter_sources"]["source_availability.py"] = sha(
            Path(__file__).with_name("source_availability.py").read_bytes()
        )
    if repaired or rerun:
        manifest["adapter_sources"].update(
            {
                "stage1_deliverable/" + name: sha(
                    (
                        Path(__file__).parent.parent / "stage1_deliverable" / name
                    ).read_bytes()
                )
                for name in (
                    "views.py",
                    "common.py",
                    "records.py",
                    "sources.py",
                    "package.py",
                )
            }
        )
    if stage2_attachment is not None:
        manifest["stage2_attachment"] = {
            "schema_version": "1.0.0",
            "attachment_sha256": sha(canonical(stage2_attachment)),
            "bridge_receipt_sha256": expected_stage2_bridge_sha256,
            "stage2_manifest_sha256": stage2_bridge["stage2_manifest_sha256"],
            "evaluation_status": stage2_attachment["evaluation"]["evaluation_status"],
            "original_stage1_lineage_attested": False,
            "stage3_authorized": False,
            "formal_ready": False,
            "improvement_demonstrated": False,
        }
        manifest["adapter_sources"].update(
            {
                name: sha(Path(__file__).with_name(name).read_bytes())
                for name in (
                    "stage2_import.py",
                    "stage2_presentation.py",
                    "stage2_comparison.py",
                    "stage2_comparison_html.py",
                )
            }
        )
    destination.mkdir(parents=True)
    for name, data in files.items():
        target = safe_path(destination, name)
        target.parent.mkdir(parents=True, exist_ok=True)
        safe_path(destination, name).write_bytes(data)
    safe_path(destination, "view-manifest.json").write_text(
        json.dumps(manifest, indent=2) + "\n", encoding="utf-8"
    )
    return manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--index", required=True)
    parser.add_argument("--expected-index-sha256", required=True)
    parser.add_argument(
        "--reference-root",
        required=True,
        help="Pinned #88 reference assets; never fetched automatically",
    )
    parser.add_argument(
        "--output", required=True, help="New directory outside every Git checkout"
    )
    parser.add_argument(
        "--atlas", action="store_true", help="Include the read-only evidence atlas"
    )
    args = parser.parse_args()
    print(
        json.dumps(
            render_view(
                args.index,
                args.output,
                args.reference_root,
                args.expected_index_sha256,
                atlas=args.atlas,
            )
        )
    )


if __name__ == "__main__":
    main()
