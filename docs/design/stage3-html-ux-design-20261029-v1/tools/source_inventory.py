"""Record immutable source identities without importing product code."""
import hashlib
import json
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = ROOT.parents[2]
REF = "57ae0509d7ccf17c92080434d8454b4e2352c33c"
PLUGIN = "plugins/auto-research-agent/"
PATHS = ["AGENTS.md", PLUGIN + "AGENTS.md"] + [PLUGIN + p for p in [
    "references/stage3-scientific-planning.md",
    "references/stage3-direction-planning.md",
    "references/stage3-evaluation-guidance.v1.md",
    "cli/research_workspace_native/web/project-stage3-planning.html",
    "cli/research_workspace_native/web/project-stage3-planning.js",
    "cli/research_workspace_native/web/project-stage3-planning.css",
    "schemas/stage3-research-plan.v1_1.schema.json",
    "schemas/stage3-direction-plan.v1.schema.json",
    "schemas/stage2-packet.v2_5.schema.json",
    "schemas/stage2-packet.v2_6.schema.json",
    "cli/stage3_plan/direction_intent.py",
    "cli/stage3_plan/direction_jobs.py",
    "cli/stage2_workflow/decision_cards.py",
    "cli/research_workspace_native/project_stage3_planning.py",
    "cli/research_workspace_native/project_stage3_direction_planning.py",
]]


def write(name, value):
    (ROOT / name).write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


rows = []
for path in PATHS:
    raw = subprocess.check_output(["git", "show", REF + ":" + path], cwd=REPO)
    blob = subprocess.check_output(["git", "rev-parse", REF + ":" + path], cwd=REPO, text=True).strip()
    rows.append({"path": path, "git_blob": blob, "bytes": len(raw), "sha256": hashlib.sha256(raw).hexdigest(),
                 "url": "https://github.com/WenyuChiou/AutoResearchAgent/blob/" + REF + "/" + path})
write("SOURCE_MANIFEST.json", {"baseline": REF, "sources": rows,
      "private_F03": "not-obtained/not-read/not-reproduced", "source_files_copied_into_design": False,
      "live_deployment_proven": False,
      "publication_scope": "docs artifact branch only; no source PR/workflow dispatch; artifact branch does not match main/tag/**full-ci** push selectors"})
mapping = json.loads((ROOT / "source-map.json").read_text(encoding="utf-8"))
for row in mapping["rows"]:
    row["source_locations"] = [
        {"path": "cli/stage3_plan/direction_intent.py", "lines": "228-258"},
        {"path": "schemas/stage2-packet.v2_5.schema.json", "section": "$defs/scientific_argument"},
    ] if row["id"] in {"motivation", "closest-work", "gap", "source-unknown", "user-condition", "user-unknown"} else [
        {"path": "cli/research_workspace_native/web/project-stage3-planning.js", "lines": "190-290",
         "note": "supplied renderer field or explicit missing/future, not Host admission proof"}]
write("source-map.json", mapping)
write("READING_NOTES.json", {"scope": "local utilities, not product tests", "events": [
    {"status": "FAILED", "original_error": "Windows rg literal path glob: os error123", "resolution": "-g direction*.py on directory read succeeded"},
    {"status": "FAILED", "original_error": "Missing saved worktree path: git exit128, checkpoint wrong root",
     "resolution": "Five artifacts moved intact to explicit intended tree; hashes preserved; absolute paths used"},
    {"status": "REJECTED", "original_error": "Combined manifest/commit/checkpoint command: blocked by policy",
     "resolution": "Split into reviewable source-inventory file, isolated execution and scoped Git steps"},
    {"status": "EXPECTED_NONZERO", "original_error": "No topic AGENTS matches; core.hooksPath unset", "resolution": "Parent rules/default hooks inspected"}],
    "product_tests": "NOT_RUN", "CI": "NOT_RUN", "browser_UI_control": "NOT_RUN"})
states = json.loads((ROOT / "state-matrix.json").read_text(encoding="utf-8"))["states"]
assert len(states) == len({s["id"] for s in states}) == 19
assert all(set(s["primary_action"]) == {"zh-CN", "zh-TW", "en"} for s in states)
assert len(mapping["rows"]) == 36
assert all(r["production_pointer"] is None or (r["production_pointer"].startswith("/") and "*" not in r["production_pointer"]) for r in mapping["rows"])
print(json.dumps({"source_files": len(rows), "states": len(states), "mapping_rows": len(mapping["rows"]), "product_tests": "NOT_RUN"}))
