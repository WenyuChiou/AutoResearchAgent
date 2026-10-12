"""Add project operations to the reviewed Atlas; never replace its renderer."""

import json

from .atlas_host import CSP
from stage1_deliverable.common import sha

PANEL = "/projects-panel.html"
PARENT_CSP = CSP + "; frame-src 'self'"
PANEL_CSP = (
    CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    + "; frame-src 'self'"
)


def stage2_example_views(files, views):
    """Reuse only explicitly registered, pinned synthetic snapshots as examples."""
    examples, routes = [], set()
    assets = {}
    start, end = b"window.WORKSPACE_VIEW = ", b";\n"
    for row in views:
        if row.get("fixture") is not True:
            continue
        prefix = "/views/" + row["ref"] + "/"
        raw = files.get(prefix + "atlas-data.js", b"")
        if not raw.startswith(start) or not raw.endswith(end):
            continue
        manifest_raw = files.get(prefix + "view-manifest.json", b"")
        if sha(manifest_raw) != row["manifest_sha256"]:
            raise ValueError("Stage2 example manifest binding differs")
        manifest = json.loads(manifest_raw)
        if sha(raw) != manifest.get("files", {}).get("atlas-data.js"):
            raise ValueError("Stage2 example data binding differs")
        payload = json.loads(raw[len(start) : -len(end)])
        if (
            payload.get("fixture") is not True
            or not isinstance(payload.get("stage2"), dict)
            or payload["stage2"].get("fixture") is not True
            or payload.get("index_sha256") != row["index_sha256"]
            or payload.get("index", {}).get("project_id") != row["project_id"]
            or not isinstance(payload.get("stage2_comparison"), dict)
        ):
            continue
        target = "/project-stage2-examples/" + row["ref"] + "/"
        assets.update(
            {
                target + path[len(prefix) :]: value
                for path, value in files.items()
                if path.startswith(prefix)
            }
        )
        route = target + "atlas.html"
        # These are original saved HTML bytes, before any host/native overlay.
        routes.add(route)
        examples.append(
            dict(
                ref=row["ref"],
                label=row["label"],
                url=route,
                fixture=True,
                project_id=row["project_id"],
                index_sha256=row["index_sha256"],
                manifest_sha256=row["manifest_sha256"],
                payload_sha256=sha(raw),
            )
        )
    return assets, examples, frozenset(routes)


def install_project_overlay(assets, views, web_root):
    # The saved-delivery child only holds a read-only memory channel. Project
    # setup and execution stay in its owning workspace, reached by Return.
    parents = {row["url"] for row in views}
    for path in parents:
        text = assets[path].decode("utf-8")
        if text.count("</body>") != 1 or text.count("default-src 'none'") != 1:
            raise ValueError("reviewed Atlas overlay source differs")
        # A separate meta policy and the HTTP policy must both permit the one
        # same-origin panel. The base package and renderer bytes stay untouched.
        text = text.replace(
            "default-src 'none'", "default-src 'none'; frame-src 'self'", 1
        )
        text = text.replace(
            "</body>",
            '<link rel="stylesheet" href="/project-operations.css">'
            '<script src="/project-operations.js" defer></script></body>',
            1,
        )
        assets[path] = text.encode("utf-8")
    panel = assets["/projects.html"].decode("utf-8")
    if panel.count("<body>") != 1 or panel.count("</head>") != 1:
        raise ValueError("project panel source differs")
    panel = panel.replace("<body>", '<body class="project-embedded">', 1)
    panel = panel.replace(
        "</head>", '<link rel="stylesheet" href="/project-operations.css"></head>', 1
    )
    panel = panel.replace(
        "</body>", '<script src="/project-operations.js" defer></script></body>', 1
    )
    assets[PANEL] = panel.encode("utf-8")
    for name in ("project-operations.js", "project-operations.css"):
        if "/" + name not in assets:
            assets["/" + name] = (web_root / name).read_bytes()
    return frozenset(parents)
