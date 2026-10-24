"""Add project operations to the reviewed Atlas; never replace its renderer."""

import json
import re

from .atlas_host import CSP
from .transport import _decode
from stage1_deliverable.common import sha

PANEL = "/projects-panel.html"
PARENT_CSP = CSP + "; frame-src 'self'"
PANEL_CSP = (
    CSP.replace("frame-ancestors 'none'", "frame-ancestors 'self'")
    + "; frame-src 'self'"
)
SOURCE_HTML_CSP = (
    "default-src 'none'; script-src 'none'; connect-src 'none'; "
    "style-src 'unsafe-inline'; img-src 'none'; object-src 'none'; "
    "base-uri 'none'; form-action 'none'; frame-ancestors 'none'; sandbox"
)


def saved_stage1_views(files, views):
    """Bind explicitly registered saved candidates without adopting native state."""
    assets, references, routes = {}, [], set()
    for row in views:
        prefix = "/views/" + row["ref"] + "/"
        raw = files.get(prefix + "view-manifest.json", b"")
        if sha(raw) != row["manifest_sha256"]:
            raise ValueError("saved Stage1 manifest binding differs")
        manifest = _decode(raw.decode("utf-8"))
        if not isinstance(manifest, dict):
            raise ValueError("saved Stage1 manifest object required")
        reference = manifest.get("saved_stage1_reference")
        if reference is None:
            continue
        if (
            row.get("fixture") is not False
            or not isinstance(reference, dict)
            or set(reference) != {"snapshot_path", "snapshot_sha256"}
            or not isinstance(reference["snapshot_path"], str)
            or re.fullmatch(r"[A-Za-z0-9_/-]+\.json", reference["snapshot_path"])
            is None
            or any(
                part in ("", ".", "..")
                for part in reference["snapshot_path"].split("/")
            )
            or not isinstance(reference["snapshot_sha256"], str)
            or re.fullmatch(r"[0-9a-f]{64}", reference["snapshot_sha256"]) is None
        ):
            raise ValueError("explicit saved Stage1 reference required")
        inventory = manifest.get("files", {})
        snapshot_raw = files.get(prefix + reference["snapshot_path"], b"")
        index_raw = files.get(prefix + "workspace-index.json", b"")
        html_raw = files.get(prefix + "index.html", b"")
        if (
            not snapshot_raw
            or len(snapshot_raw) > 1024 * 1024
            or sha(snapshot_raw) != reference["snapshot_sha256"]
            or inventory.get(reference["snapshot_path"]) != sha(snapshot_raw)
            or sha(index_raw) != row["index_sha256"]
            or inventory.get("workspace-index.json") != sha(index_raw)
            or not html_raw
            or inventory.get("index.html") != sha(html_raw)
        ):
            raise ValueError("saved Stage1 source binding differs")
        snapshot, index = (
            _decode(snapshot_raw.decode("utf-8")),
            _decode(index_raw.decode("utf-8")),
        )
        if not isinstance(snapshot, dict) or not isinstance(index, dict):
            raise ValueError("saved Stage1 source objects required")
        version = snapshot.get("input_version")
        version_valid = (type(version) is str and 0 < len(version) <= 128) or (
            type(version) is int and 0 < version <= 2**53 - 1
        )
        bindings = snapshot.get("bindings", {})
        projection = manifest.get("browser_projection", {})
        provenance = index.get("provenance", {})
        if (
            not isinstance(bindings, dict)
            or not isinstance(projection, dict)
            or not isinstance(provenance, dict)
        ):
            raise ValueError("saved Stage1 lineage objects required")
        view_binding, delivery_binding = (
            bindings.get("view", {}),
            bindings.get("deliverable", {}),
        )
        if not isinstance(view_binding, dict) or not isinstance(delivery_binding, dict):
            raise ValueError("saved Stage1 lineage references required")
        parent_manifest = projection.get("parent_view_manifest_sha256")
        if (
            snapshot.get("kind") != "SavedSourceCandidateSnapshot"
            or snapshot.get("schema_version") != "1.0.0"
            or not version_valid
            or snapshot.get("project_id") != row["project_id"]
            or index.get("project_id") != row["project_id"]
            or view_binding.get("sha256") != parent_manifest
            or not isinstance(parent_manifest, str)
            or re.fullmatch(r"[0-9a-f]{64}", parent_manifest) is None
            or delivery_binding.get("sha256")
            != provenance.get("deliverable_manifest_sha256")
            or not re.fullmatch(r"[0-9a-f]{64}", str(delivery_binding.get("sha256")))
        ):
            raise ValueError("saved Stage1 typed identity or lineage differs")
        target = "/project-stage1-saved/" + row["ref"] + "/"
        # Aliases share immutable in-memory bytes. Only this pinned entry may be
        # framed; no credential/bootstrap or native-operation route is copied.
        assets.update({target + name: files[prefix + name] for name in inventory})
        route = target + "index.html"
        routes.add(route)
        references.append(
            dict(
                ref=row["ref"],
                label=row["label"],
                project_id=row["project_id"],
                input_version=version,
                index_sha256=row["index_sha256"],
                manifest_sha256=row["manifest_sha256"],
                html_sha256=sha(html_raw),
                snapshot_sha256=sha(snapshot_raw),
                url=route,
                fixture=False,
                read_only=True,
                accepted=False,
                execution_authorized=False,
            )
        )
    return assets, references, frozenset(routes)


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


def install_project_overlay(assets, views, web_root, saved_views=()):
    # The saved-delivery child only holds a read-only memory channel. Project
    # setup and execution stay in its owning workspace, reached by Return.
    parents = {row["url"] for row in views}
    for path in parents:
        text = assets[path].decode("utf-8")
        if text.count("</body>") != 1 or text.count("default-src 'none'") != 1:
            raise ValueError("reviewed Atlas overlay source differs")
        # A separate meta policy and the HTTP policy must both permit the one
        # same-origin panel. The base package and renderer bytes stay untouched.
        saved_markup = ""
        if saved_views:
            payload = json.dumps(
                dict(
                    kind="SavedStage1References",
                    schema_version="1.0.0",
                    views=saved_views,
                ),
                ensure_ascii=True,
                allow_nan=False,
            ).replace("<", "\\u003c")
            saved_markup = (
                '<script type="application/json" id="project-saved-view-bindings">'
                + payload
                + '</script><script src="/project-saved-views.js" defer></script>'
            )
        text = text.replace(
            "default-src 'none'", "default-src 'none'; frame-src 'self'", 1
        )
        text = text.replace(
            "</body>",
            '<link rel="stylesheet" href="/project-operations.css">'
            + saved_markup
            + '<script src="/project-operations.js" defer></script></body>',
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
