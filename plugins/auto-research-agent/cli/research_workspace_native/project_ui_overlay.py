"""Add project operations to the reviewed Atlas; never replace its renderer."""

from .atlas_host import CSP

PANEL = "/projects-panel.html"
PARENT_CSP = CSP + "; frame-src 'self'"
PANEL_CSP = (
    CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    + "; frame-src 'self'"
)


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
