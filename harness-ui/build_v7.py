"""Deterministic V7 renderer; the selected repository supplies shared vendors."""

import argparse
import hashlib
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SOURCE_NAMES = ("base.js", "shell.html", "runtime.js", "control-intent.js", "retirement-ui.js", "real-runtime.js", "expansion-ui.js", "query-feedback.js", "canonical-stage2.js", "canonical-runs.js", "native-case-ui.js", "runtime.css")
LOCAL_VENDORS = ("atlas-spatial.js", "three.core.js", "three-LICENSE.txt", "three.core.provenance.json")
SHARED_VENDORS = {
    "3d-force-graph-1.80.1.min.js": "vendor/3d-force-graph-1.80.1.min.js",
    "atlas-model.js": "atlas-model.js",
    "vendor-lock.json": "vendor/vendor-lock.json",
    "3d-force-graph-LICENSE.txt": "vendor/3d-force-graph-LICENSE.txt",
    "THIRD_PARTY_LICENSES.txt": "vendor/THIRD_PARTY_LICENSES.txt",
}
THREE_SHA256 = "9edde002b066a9a05676a6127f67735b62baf399bdea529f2f7e31657da769e6"


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def canonical(value):
    return json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode("utf-8")


def read_regular(root, name):
    path = root / name
    if path.is_symlink() or not path.is_file() or not path.resolve().is_relative_to(root.resolve()):
        raise ValueError("renderer asset is not a regular contained file: " + name)
    return path.read_bytes()


def snapshot(repo, package=HERE):
    """Read only this explicit allowlist once; returned bytes never hot reload."""
    src, vendor = package / "renderer/src", package / "renderer/vendor"
    inputs = {name: read_regular(src, name) for name in SOURCE_NAMES}
    marker = b"/* V7_RUNTIME_MODULES */"
    if inputs["base.js"].count(marker) != 1:
        raise ValueError("expected one V7 runtime insertion marker")
    if b'/project-bootstrap.js' not in inputs["shell.html"]:
        raise ValueError("production ProjectHost bootstrap required")
    modules = ('runtime.js', 'control-intent.js', 'retirement-ui.js', 'real-runtime.js',
               'expansion-ui.js', 'query-feedback.js', 'canonical-stage2.js',
               'canonical-runs.js', 'native-case-ui.js')
    app = inputs["base.js"].replace(marker, b'\n'.join(inputs[name] for name in modules))
    assets = {"/": inputs["shell.html"], "/index.html": inputs["shell.html"],
              "/app.js": app, "/runtime.css": inputs["runtime.css"]}
    local = {name: read_regular(vendor, name) for name in LOCAL_VENDORS}
    if sha(local["three.core.js"]) != THREE_SHA256:
        raise ValueError("Three.js local distribution differs from reviewed SHA256")
    provenance = json.loads(local["three.core.provenance.json"])
    if (provenance["archive_member_sha256"] != THREE_SHA256
            or provenance["license_archive_sha256"] != sha(local["three-LICENSE.txt"])):
        raise ValueError("Three.js distribution or license differs from recorded provenance")
    atlas = repo / "plugins/auto-research-agent/references/research-workspace/atlas"
    shared = {name: read_regular(atlas, relative) for name, relative in SHARED_VENDORS.items()}
    for name, raw in {**local, **shared}.items():
        assets["/vendor/" + name] = raw
    manifest = {
        "kind": "V7RendererSnapshot", "schema_version": "1.0.0",
        "source_sha256": {name: sha(raw) for name, raw in inputs.items()},
        "served_files": {route: sha(raw) for route, raw in assets.items()},
        "shared_vendors": SHARED_VENDORS,
        "three_core": {"sha256": THREE_SHA256, "license": "MIT; /vendor/three-LICENSE.txt",
                       "provenance": "/vendor/three.core.provenance.json",
                       "archive_member": provenance["archive_member"],
                       "tarball_sha256": provenance["tarball_sha256"],
                       "official_core_minified_member_available": False},
    }
    assets["/v7-renderer-manifest.json"] = canonical(manifest)
    return assets, manifest


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repo", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    assets, manifest = snapshot(args.repo.resolve())
    args.output.mkdir(parents=True, exist_ok=True)
    # Only generated allowlisted paths are written; unrelated files are untouched.
    for route, raw in assets.items():
        if route == "/":
            continue
        target = args.output / route.lstrip("/")
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(raw)
    print(json.dumps({"status": "built", "manifest_sha256": sha(canonical(manifest)),
                      "assets": len(assets)}, sort_keys=True))


if __name__ == "__main__":
    main()
