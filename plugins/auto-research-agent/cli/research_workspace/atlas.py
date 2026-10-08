"""An opt-in presentation companion; no research or execution authority."""

from pathlib import Path
import json

from stage1_deliverable.common import canonical, sha


def atlas_files(payload):
    """Bind the canonical view payload and reviewed atlas assets to private output."""
    from .stage2_comparison import build_comparison_view
    from .atlas_model import model_asset

    data = dict(payload)
    if payload.get("stage2") is not None:
        data["stage2_comparison"] = build_comparison_view(payload["stage2"])
    assets = Path(__file__).parents[2] / "references/research-workspace/atlas"
    files = {
        name: (assets / name).read_bytes()
        for name in ("atlas.html", "atlas.css", "atlas-ui.js")
    }
    files["atlas-model.js"] = model_asset()
    encoded = json.dumps(data, ensure_ascii=True).replace("<", "\\u003c")
    files["atlas-data.js"] = ("window.WORKSPACE_VIEW = " + encoded + ";\n").encode()
    files["atlas-binding.json"] = canonical(
        {
            "kind": "WorkspaceEvidenceAtlas",
            "presentation_version": "1.0.0",
            "design_reference": "reviewed-local-v9",
            "design_sha256": "e0e3da65acb96cc2d1901c5f5b77f4619f999302d367247d4c6c59991ae4dbd9",
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
