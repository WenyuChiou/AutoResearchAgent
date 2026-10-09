"""Offline vendor packaging and real loopback static routes; no native launch."""

from copy import deepcopy
from html.parser import HTMLParser
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import threading
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace import atlas  # noqa: E402
from research_workspace_native.atlas_host import AtlasHost, load_views  # noqa: E402
from stage1_deliverable.common import canonical, sha  # noqa: E402
from test_workspace_atlas import emitted_data, payload  # noqa: E402


class ScriptInventory(HTMLParser):
    def __init__(self):
        super().__init__()
        self.sources = []
        self.csp = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == "script":
            self.sources.append(attrs.get("src"))
        if tag == "meta" and attrs.get("http-equiv") == "Content-Security-Policy":
            self.csp = attrs["content"]


class WorkspaceAtlasAssetTests(unittest.TestCase):
    def run_node(self, name):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node.js is required for the atlas source contracts")
        result = subprocess.run(
            [node, str(PLUGIN / "tests" / name)],
            cwd=PLUGIN,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        return result.stdout

    def test_associations_literal_memberships_and_bounded_lexical_links(self):
        self.assertIn(
            "Atlas associations passed",
            self.run_node("test_workspace_atlas_associations.js"),
        )

    def test_spatial_identity_camera_selection_and_disposal(self):
        self.assertIn(
            "atlas spatial identity",
            self.run_node("test_workspace_atlas_spatial.js"),
        )

    def test_shared_network_lifecycle_settings_and_canonical_links(self):
        self.assertIn(
            "atlas network lifecycle",
            self.run_node("test_workspace_atlas_network.js"),
        )

    def asset_copy(self, root):
        destination = root / "assets"
        shutil.copytree(atlas.ATLAS_ROOT, destination)
        self.assertEqual(
            (destination / "atlas-layout.v1.md").read_bytes(),
            (atlas.ATLAS_ROOT / "atlas-layout.v1.md").read_bytes(),
        )
        return destination

    def bound_host(self, root):
        value = payload()
        files = atlas.atlas_files(value)
        files["workspace-index.json"] = canonical(value["index"])
        files["index.html"] = b"<h1>Original synthetic workspace</h1>"
        folder = root / "view"
        for name, raw in files.items():
            target = folder / name
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_bytes(raw)
        manifest = canonical(
            {
                "kind": "WorkspaceReadOnlyView",
                "index_sha256": value["index_sha256"],
                "files": {name: sha(raw) for name, raw in files.items()},
            }
        )
        path = folder / "view-manifest.json"
        path.write_bytes(manifest)
        config = root / "host.json"
        raw = canonical(
            {
                "views": [
                    {
                        "ref": "assets",
                        "label": "Synthetic vendor packaging",
                        "manifest": str(path),
                        "sha256": sha(manifest),
                        "fixture": True,
                    }
                ]
            }
        )
        config.write_bytes(raw)
        return config, sha(raw), folder, files

    def test_asset_inventory_preserves_payload_and_binds_official_vendor_bytes(self):
        value = payload()
        before = deepcopy(value)
        files = atlas.atlas_files(value)
        self.assertEqual(value, before)
        self.assertEqual(emitted_data(files), before)
        binding = json.loads(files["atlas-binding.json"])
        self.assertEqual(binding["presentation_version"], "1.3.0")
        self.assertEqual(
            binding["design_contract_sha256"],
            sha((atlas.ATLAS_ROOT / "atlas-layout.v3.md").read_bytes()),
        )
        self.assertEqual(
            binding["files"],
            {
                name: sha(raw)
                for name, raw in files.items()
                if name != "atlas-binding.json"
            },
        )
        self.assertEqual(set(atlas.atlas_asset_files()), set(atlas.ATLAS_ASSETS))
        lock_raw = files["vendor/vendor-lock.json"]
        self.assertEqual(sha(lock_raw), atlas.VENDOR_LOCK_SHA256)
        lock = json.loads(lock_raw)
        self.assertFalse(lock["verification"]["npm_lifecycle_executed"])
        package = lock["packages"][0]
        self.assertEqual(
            (package["name"], package["version"], package["license"]),
            ("3d-force-graph", "1.80.1", "MIT"),
        )
        for name, row in package["files"].items():
            self.assertEqual(
                (sha(files[name]), len(files[name])), (row["sha256"], row["bytes"])
            )
        notices = lock["packages"][1]
        self.assertEqual(notices["embedded_versions"], "not-attested")
        self.assertEqual(len(notices["license_sources"]), 34)
        self.assertIn(
            b"Exact versions embedded in the upstream prebuilt UMD are not attested.",
            files["vendor/THIRD_PARTY_LICENSES.txt"],
        )
        vendor = files["vendor/3d-force-graph-1.80.1.min.js"]
        self.assertTrue(
            vendor.startswith(
                b"// Version 1.80.1 3d-force-graph - https://github.com/vasturiano/3d-force-graph\n"
            )
        )
        self.assertNotIn(b"\r\n", vendor)
        self.assertIn(
            b"Copyright (c) 2017 Vasco Asturiano",
            files["vendor/3d-force-graph-LICENSE.txt"],
        )

    def test_scripts_load_in_order_from_same_origin_without_csp_weakening(self):
        inventory = ScriptInventory()
        inventory.feed(atlas.atlas_files(payload())["atlas.html"].decode("utf-8"))
        self.assertEqual(
            inventory.sources,
            [
                "./atlas-data.js",
                "./atlas-model.js",
                "./vendor/3d-force-graph-1.80.1.min.js",
                "./atlas-associations.js",
                "./atlas-spatial.js",
                "./atlas-network.js",
                "./atlas-ui.js",
            ],
        )
        self.assertIn("script-src 'self'", inventory.csp)
        self.assertIn("connect-src 'none'", inventory.csp)
        self.assertNotIn("unsafe-eval", inventory.csp)
        self.assertNotIn("script-src 'self' 'unsafe-inline'", inventory.csp)

    def test_missing_changed_vendor_and_rehashed_lock_fail_closed(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = self.asset_copy(Path(directory).resolve())
            with patch.object(atlas, "ATLAS_ROOT", assets):
                for name in (
                    "vendor/3d-force-graph-1.80.1.min.js",
                    "vendor/3d-force-graph-LICENSE.txt",
                ):
                    target = assets / name
                    original = target.read_bytes()
                    target.unlink()
                    with self.assertRaisesRegex(ValueError, "asset missing"):
                        atlas.atlas_files(payload())
                    target.write_bytes(original + b"tampered")
                    with self.assertRaisesRegex(ValueError, "vendor asset binding"):
                        atlas.atlas_files(payload())
                    target.write_bytes(original)
                lock_path = assets / "vendor/vendor-lock.json"
                lock = json.loads(lock_path.read_bytes())
                name = "vendor/3d-force-graph-1.80.1.min.js"
                changed = (assets / name).read_bytes() + b"tampered"
                (assets / name).write_bytes(changed)
                lock["packages"][0]["files"][name].update(
                    sha256=sha(changed), bytes=len(changed)
                )
                lock_path.write_bytes(canonical(lock))
                with self.assertRaisesRegex(ValueError, "vendor lock binding"):
                    atlas.atlas_files(payload())

    def test_only_fixed_asset_names_are_copied(self):
        with tempfile.TemporaryDirectory() as directory:
            assets = self.asset_copy(Path(directory).resolve())
            (assets / "vendor/unregistered.js").write_bytes(b"not allowed")
            with patch.object(atlas, "ATLAS_ROOT", assets):
                self.assertNotIn("vendor/unregistered.js", atlas.atlas_files(payload()))

    def test_nested_static_assets_have_exact_bytes_and_same_origin_headers(self):
        with tempfile.TemporaryDirectory() as directory:
            config, pin, _, expected = self.bound_host(Path(directory).resolve())
            files, views = load_views(config, pin)
            server = AtlasHost(files=files, views=views)
            worker = threading.Thread(target=server.serve_forever, daemon=True)
            worker.start()
            try:
                for name in (
                    "vendor/3d-force-graph-1.80.1.min.js",
                    "vendor/vendor-lock.json",
                ):
                    client = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=3
                    )
                    try:
                        client.request("GET", "/views/assets/" + name)
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        self.assertEqual(response.read(), expected[name])
                        self.assertEqual(
                            response.getheader("Cross-Origin-Resource-Policy"),
                            "same-origin",
                        )
                        self.assertEqual(
                            response.getheader("X-Content-Type-Options"), "nosniff"
                        )
                        self.assertEqual(
                            response.getheader("Content-Type"),
                            "text/javascript"
                            if name.endswith(".js")
                            else "application/json",
                        )
                    finally:
                        client.close()
                self.assertNotIn("/views/assets/vendor/unregistered.js", server._assets)
                for route, headers, status in (
                    ("/views/assets/vendor/unregistered.js", {}, 404),
                    ("/views/assets/vendor/../atlas-ui.js", {}, 404),
                    (
                        "/views/assets/vendor/vendor-lock.json",
                        {"Origin": "https://foreign.example"},
                        403,
                    ),
                ):
                    client = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=3
                    )
                    try:
                        client.request("GET", route, headers=headers)
                        response = client.getresponse()
                        self.assertEqual(response.status, status)
                        response.read()
                    finally:
                        client.close()
            finally:
                server.shutdown()
                server.server_close()
                worker.join(3)
                self.assertFalse(worker.is_alive())

    def test_host_rejects_missing_or_mismatched_nested_asset(self):
        with tempfile.TemporaryDirectory() as directory:
            config, pin, folder, _ = self.bound_host(Path(directory).resolve())
            target = folder / "vendor/3d-force-graph-1.80.1.min.js"
            raw = target.read_bytes()
            target.write_bytes(raw + b"tampered")
            with self.assertRaisesRegex(ValueError, "view file binding"):
                load_views(config, pin)
            target.unlink()
            with self.assertRaises(ValueError):
                load_views(config, pin)


if __name__ == "__main__":
    unittest.main()
