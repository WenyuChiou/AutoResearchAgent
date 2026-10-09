"""An opt-in presentation companion; no research or execution authority."""

from pathlib import Path
import json

from stage1_deliverable.common import canonical, safe_path, sha


ATLAS_ROOT = Path(__file__).parents[2] / "references/research-workspace/atlas"
ATLAS_ASSETS = (
    "atlas.html",
    "atlas.css",
    "atlas-ui.js",
    "atlas-associations.js",
    "atlas-spatial.js",
    "atlas-network.js",
    "vendor/3d-force-graph-1.80.1.min.js",
    "vendor/3d-force-graph-LICENSE.txt",
    "vendor/THIRD_PARTY_LICENSES.txt",
    "vendor/vendor-lock.json",
)
VENDOR_LOCK_SHA256 = "4ea67bed252da979c0adeb5a0ece6568bc0a4bc2bf0ff412571c04e6358388aa"


def atlas_asset_files():
    """Read only the fixed assets and reject changed vendor provenance or bytes."""
    try:
        files = {
            name: safe_path(ATLAS_ROOT, name).read_bytes() for name in ATLAS_ASSETS
        }
    except OSError as error:
        raise ValueError("atlas asset missing or unreadable") from error
    lock_name = "vendor/vendor-lock.json"
    if sha(files[lock_name]) != VENDOR_LOCK_SHA256:
        raise ValueError("atlas vendor lock binding differs")
    lock = json.loads(files[lock_name])
    for package in lock["packages"]:
        for name, row in package["files"].items():
            if len(files[name]) != row["bytes"] or sha(files[name]) != row["sha256"]:
                raise ValueError("atlas vendor asset binding differs")
    return files


def atlas_files(payload):
    """Bind the canonical view payload and reviewed atlas assets to private output."""
    from .stage2_comparison import build_comparison_view
    from .atlas_model import model_asset

    data = dict(payload)
    if payload.get("stage2") is not None:
        data["stage2_comparison"] = build_comparison_view(payload["stage2"])
    files = atlas_asset_files()
    files["atlas-model.js"] = model_asset()
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    files["atlas-data.js"] = ("window.WORKSPACE_VIEW = " + encoded + ";\n").encode()
    files["atlas-binding.json"] = canonical(
        {
            "kind": "WorkspaceEvidenceAtlas",
            "presentation_version": "1.2.0",
            "design_reference": "reviewed-local-v6",
            "design_contract_sha256": sha(
                safe_path(ATLAS_ROOT, "atlas-layout.v1.md").read_bytes()
            ),
            "design_sha256": "a3dfafeafb5890a9e82cff4b42f77c04aca19699e5ded09e453d45be9e485540",
            "project_id": payload["index"]["project_id"],
            "index_sha256": payload["index_sha256"],
            "stage2_attachment_sha256": (
                sha(canonical(payload["stage2"])) if payload.get("stage2") else None
            ),
            "research_execution": "not-performed",
            "execution_authority": False,
            "files": {name: sha(raw) for name, raw in files.items()},
        }
    )
    return files
