"""Editable projections of an accepted repair; never new scientific judgments."""

import platform
from importlib.metadata import version

from stage1_deliverable.common import canonical, sha
from stage1_deliverable.views import csv_bytes, workbook_bytes

from .projection import validate_index


def fence(value):
    """Fence arbitrary source text without allowing Markdown injection."""
    from .wiki import _fence

    return _fence(value)


def repair_note(index, paper):
    data = index["supplement"]["data"]
    versions = {row["work_id"]: row["version_id"] for row in data["papers"]}
    if versions.get(paper["work_id"]) != paper["version_id"]:
        return ""
    result = "## Accepted repair supplement\n\n"
    result += (
        "Original findings and judgments above are historical and unchanged. "
        "The entries below distinguish source findings, interpretation, "
        "hypotheses and unresolved obligations.\n\n"
    )
    result += fence(
        {
            "manifest_sha256": index["supplement"]["manifest_sha256"],
            "review_sha256": index["supplement"]["review_sha256"],
            "work_id": paper["work_id"],
            "version_id": paper["version_id"],
            "atomic_revisions": [
                row
                for row in data["atomic_revisions"]
                if row["work_id"] == paper["work_id"]
            ],
            "core_findings": [
                row
                for row in data["core_findings"]
                if row["work_id"] == paper["work_id"]
            ],
            "supplement_wide_reading_and_obligations": {
                "scope": "Entire accepted supplement; these states are not attributed to every work in this note",
                "source_reading": data["source_reading"],
                "unresolved": data["unresolved"],
            },
        }
    )
    return result


def _rows(values):
    present = {key for row in values for key in row}
    identity = (
        "work_id",
        "version_id",
        "claim_id",
        "atom_id",
        "finding_id",
        "source_id",
    )
    keys = [key for key in identity if key in present]
    keys += sorted(present.difference(keys))
    return [{key: row.get(key) for key in keys} for row in values]


def closeout_tables(index):
    """Keep original denominators separate from the accepted atomic revisions."""
    data = index["supplement"]["data"]
    versions = {row["work_id"]: row["version_id"] for row in data["papers"]}
    bindings = {
        "records_sha256": index["provenance"]["records_sha256"],
        "repair_manifest_sha256": index["supplement"]["manifest_sha256"],
        "repair_review_sha256": index["supplement"]["review_sha256"],
    }
    tables = {
        "Papers": _rows(index["papers"]),
        "Classification": _rows(
            [
                {
                    key: paper.get(key)
                    for key in ("work_id", "version_id", "classification", "roles")
                }
                for paper in index["papers"]
            ]
        ),
        "Findings": _rows(
            [
                {
                    key: paper.get(key)
                    for key in ("work_id", "version_id", "findings", "claim_ids")
                }
                for paper in index["papers"]
            ]
        ),
        "Claims": _rows(index["claims"]),
        "Screening": _rows(index["screening"]),
        "Coverage": _rows(index["coverage"]),
        "Sources": _rows(
            [
                {
                    key: row.get(key)
                    for key in (
                        "source_id",
                        "work_id",
                        "version_id",
                        "result_sha256",
                        "result_path",
                        "package_extracted_sha256",
                        "package_raw_sha256",
                    )
                }
                for row in index["sources"]
            ]
        ),
        "AtomicRevisions": _rows(
            [
                {**row, "version_id": versions[row["work_id"]], **bindings}
                for row in data["atomic_revisions"]
            ]
        ),
        "CoreFindings": _rows(
            [
                {**row, "version_id": versions[row["work_id"]], **bindings}
                for row in data["core_findings"]
            ]
        ),
        "Unresolved": [
            {"key": key, "value": data["unresolved"][key]}
            for key in sorted(data["unresolved"])
        ],
        "Bindings": [{"key": key, "value": value} for key, value in bindings.items()],
    }
    # Empty sections remain present as JSON; avoid inventing spreadsheet rows.
    return {name: rows for name, rows in tables.items() if rows}


def runtime_binding():
    return {
        "python": platform.python_version(),
        "implementation": platform.python_implementation(),
        "dependencies": {
            name: version(name) for name in ("jsonschema", "openpyxl", "python-docx")
        },
        "original_runtime_replay": "not-reexecuted-by-this-exporter",
        "scientific_quality_scored": False,
        "native_execution": "not-performed",
    }


def closeout_files(index):
    validate_index(index)
    if (
        index["schema_version"] not in {"2.0.0", "3.0.0"}
        or index["supplement"]["status"] == "not-provided"
    ):
        return {}
    overlay, data = index["supplement"], index["supplement"]["data"]
    binding = {
        "project_id": index["project_id"],
        "index_sha256": sha(canonical(index)),
        "original_records_sha256": index["provenance"]["records_sha256"],
        "manifest_sha256": overlay["manifest_sha256"],
        "review_sha256": overlay["review_sha256"],
        "runtime": runtime_binding(),
        "original_compound_counts": data["original_compound_counts"],
        "original_claim_rows": len(index["claims"]),
        "atomic_revision_entries": len(data["atomic_revisions"]),
        "distinct_works": len(index["papers"]),
        "core_findings": len(data["core_findings"]),
        "official_stage2_import_eligible": False,
    }
    tables = closeout_tables(index)
    files = {
        "closeout/manifest.json": canonical(binding),
        "closeout/repair-supplement.json": canonical(data),
        "closeout/claim-revision-map.json": canonical(data["atomic_revisions"]),
        "closeout/typed-relationships.json": canonical(overlay["edges"]),
        "closeout/literature-catalog.xlsx": workbook_bytes(tables),
    }
    for name, rows in tables.items():
        files[f"closeout/{name}.csv"] = csv_bytes(name, rows)
    for name, row in overlay["evidence_files"].items():
        files["repair/" + name] = row["text"].encode("utf-8")
    findings = "# Core Stage 1 findings\n\n"
    findings += "Source findings, interpretation and hypotheses retain their accepted labels. Stage 2 implications do not select a direction.\n\n"
    for row in data["core_findings"]:
        findings += "## Finding\n\n" + fence(row)
    files["closeout/core-findings.md"] = findings.encode("utf-8")
    counts = data["original_compound_counts"]
    summary = (
        "# Stage 1 研究成果收尾\n\n"
        "本版整合原始 v2 與通過獨立審查的內容修復補充。原始套件及修復檔案不覆寫。\n\n"
        f"完整書目：{len(index['papers'])} 篇；原始 canonical claims：{len(index['claims'])} 筆。\n\n"
        f"歷史 compound groups：{counts['denominator']} 組，其中 {counts['supported']} supported／{counts['partial']} partial／{counts['unknown']} unknown。"
        f"另列 {len(data['atomic_revisions'])} 項原子修訂、{len(data['core_findings'])} 項核心發現；不產生新品質分數。\n\n"
        "## 已修復與限制\n\n"
        "下列結果取自通過審查的補充。來源擷取結果、斷言修正、版本限制與未解義務分別保留；斷言縮窄不等於新增支持證據。\n\n"
        + fence(data.get("source_findings_resolution"))
        + fence(data.get("assertion_correction"))
        + "## 仍未解與下一步\n\n"
        + fence(data["unresolved"])
        + "後續責任與授權依原專案紀錄；本匯出不指定新的負責人，也不啟動搜尋、下載、評分或 browser fallback。\n\n"
        + "## 工程失敗與交付驗證\n\n"
        + fence(data.get("engineering"))
        + "原始 runtime replay 結果依保存的輸入紀錄。本匯出器的程式與依賴另行綁定；新交付重建檢查不能覆寫任何原失敗。\n\n"
        + "正式 Stage 2 import、真實原生流程與完整 Wiki 驗收不由本匯出授權；本版保留 review-only、partial 與未解 coverage。\n\n"
        + fence(binding)
    )
    files["closeout/README.zh-TW.md"] = summary.encode("utf-8")
    return files
