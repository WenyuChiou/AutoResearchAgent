"""Code-only v6 shell. Private project records never enter public assets."""

import re
from pathlib import Path

from research_workspace.atlas import atlas_asset_files
from research_workspace.atlas_model import model_asset

WEB_ROOT = Path(__file__).parent / "web"
LEDGER_ENTRY = b"  function ledgerContent(parent, paper) {"
LEDGER_HOOK = (
    b"\n    if (!window.ProjectAtlasScreening) throw new Error('saved ledger presenter unavailable');"
    b"\n    if (window.ProjectAtlasScreening.renderLedger(parent, paper, index, payload, state.language)) return;"
)


def renderer_assets(original, web_root=WEB_ROOT):
    """Pin a native read-only presenter while retaining the reviewed base bytes."""
    assets = dict(original)
    ui = assets["atlas-ui.js"]
    if ui.count(LEDGER_ENTRY) != 1 or b"ProjectAtlasScreening" in ui:
        raise ValueError("project atlas ledger source binding differs")
    newline = b"\r\n" if b"\r\n" in ui else b"\n"
    assets["atlas-ui.js"] = ui.replace(
        LEDGER_ENTRY, LEDGER_ENTRY + LEDGER_HOOK.replace(b"\n", newline), 1
    )
    assets["project-atlas-screening.js"] = (
        web_root / "project-atlas-screening.js"
    ).read_bytes()
    return assets


def shell_assets(web_root):
    """Derive an explicit host overlay without changing the reviewed v6 files."""
    original = atlas_asset_files()
    html = original.pop("atlas.html").decode("utf-8")
    # Only fixed script tags are removed; a source change must fail closed.
    scripts = re.findall(r'<script src="([^"]+)"></script>', html)
    expected = [
        "./atlas-data.js",
        "./atlas-model.js",
        "./vendor/3d-force-graph-1.80.1.min.js",
        "./atlas-associations.js",
        "./atlas-spatial.js",
        "./atlas-network.js",
        "./atlas-ui.js",
    ]
    if scripts != expected or html.count('href="./atlas.css"') != 1:
        raise ValueError("project atlas shell source binding differs")
    html = re.sub(r'<script src="[^"]+"></script>', "", html)
    html = html.replace('href="./atlas.css"', 'href="/project-atlas-static/atlas.css"')
    html = html.replace(
        "<body>",
        '<body><p id="project-atlas-status" role="status" style="margin:12px 24px">Open this saved view from the project workspace.</p>',
    )
    html = html.replace(
        "</body>", '<script src="/project-atlas-child.js" defer></script></body>'
    )
    original["atlas-model.js"] = model_asset()
    original = renderer_assets(original, web_root)
    return {
        **{"/project-atlas-static/" + name: raw for name, raw in original.items()},
        "/project-atlas.html": html.encode("utf-8"),
        "/project-atlas-child.js": (web_root / "project-atlas-child.js").read_bytes(),
    }
