"""Actual temporary HTTP and pinned repository fixtures; no Codex/model launch."""

import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from research_workspace.atlas import atlas_files
from research_workspace_native.atlas_host import AtlasHost, load_views
from stage1_deliverable.common import canonical, sha
from test_workspace_atlas import payload


class AtlasHostTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name).resolve()
        self.entries, self.outputs = [], []
        for ref in ("stage1", "stage2"):
            folder = self.root / ref
            folder.mkdir()
            value = payload()
            files = atlas_files(value)
            files["workspace-index.json"] = canonical(value["index"])
            files["index.html"] = b"<h1>Original read-only workspace</h1>"
            for name, raw in files.items():
                (folder / name).parent.mkdir(parents=True, exist_ok=True)
                (folder / name).write_bytes(raw)
            manifest = canonical(
                dict(
                    kind="WorkspaceReadOnlyView",
                    index_sha256=value["index_sha256"],
                    files={name: sha(raw) for name, raw in files.items()},
                )
            )
            path = folder / "view-manifest.json"
            path.write_bytes(manifest)
            self.entries.append(
                dict(
                    ref=ref,
                    label="Literal <img> case",
                    manifest=str(path),
                    sha256=sha(manifest),
                    fixture=True,
                )
            )
            self.outputs.append(folder)
        self.config = self.root / "host.json"
        self.pin = self.save_config()

    def save_config(self):
        raw = canonical(dict(views=self.entries))
        self.config.write_bytes(raw)
        return sha(raw)

    def server(self):
        files, views = load_views(self.config, self.pin)
        server = AtlasHost(
            files=files,
            views=views,
            connection=dict(
                status="check-passed",
                model_turn_tested=False,
                research_session_started=False,
            ),
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server

    def get(self, server, path, method="GET", headers=None):
        client = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=3)
        try:
            client.request(method, path, headers=headers or {})
            response = client.getresponse()
            return response.status, dict(response.getheaders()), response.read()
        finally:
            client.close()

    def report_files(self, names):
        folder = self.outputs[0]
        manifest_path = folder / "view-manifest.json"
        manifest = json.loads(manifest_path.read_bytes())
        for name, raw in names.items():
            path = folder / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            manifest["files"][name] = sha(raw)
        raw = canonical(manifest)
        manifest_path.write_bytes(raw)
        self.entries[0]["sha256"] = sha(raw)
        self.pin = self.save_config()

    def test_verified_stage2_report_has_scoped_frame_and_opaque_source(self):
        report = b"<h1>Original report</h1><script>parent.compromised=true</script>"
        reader = b'<iframe sandbox="" src="selection.html"></iframe>'
        self.report_files(
            {
                "stage2/report-reader.html": reader,
                "stage2/selection.html": report,
                "other/selection.html": report,
            }
        )
        server = self.server()
        status, headers, raw = self.get(
            server, "/views/stage1/stage2/report-reader.html"
        )
        self.assertEqual((status, raw), (200, reader))
        csp = headers["Content-Security-Policy"]
        self.assertIn(
            "frame-src "
            + server.expected_origin
            + "/views/stage1/stage2/selection.html",
            csp,
        )
        self.assertIn("frame-ancestors 'none'", csp)
        status, headers, raw = self.get(server, "/views/stage1/stage2/selection.html")
        self.assertEqual((status, raw), (200, report))
        csp = headers["Content-Security-Policy"]
        for directive in (
            "default-src 'none'",
            "script-src 'none'",
            "connect-src 'none'",
            "frame-src 'none'",
            "frame-ancestors 'self'",
            "form-action 'none'",
            "sandbox",
        ):
            self.assertIn(directive, csp)
        self.assertNotIn("allow-", csp)
        for path in ("/views/stage1/atlas.html", "/views/stage1/other/selection.html"):
            status, headers, _ = self.get(server, path)
            self.assertEqual(status, 200)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertNotIn("frame-src", headers["Content-Security-Policy"])
        for path in (
            "/views/stage1/stage2/selection.html?alias=1",
            "/views/stage1/stage2/%73election.html",
            "/views/unknown/stage2/selection.html",
        ):
            self.assertEqual(self.get(server, path)[0], 404)

    def test_partial_report_registration_does_not_enable_framing(self):
        self.report_files({"stage2/report-reader.html": b"reader without source"})
        server = self.server()
        status, headers, raw = self.get(
            server, "/views/stage1/stage2/report-reader.html"
        )
        self.assertEqual((status, raw), (200, b"reader without source"))
        self.assertNotIn("frame-src", headers["Content-Security-Policy"])
        self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])

    def test_binding_and_snapshot_leave_canonical_html_and_index_unchanged(self):
        originals = {
            (folder / name): (folder / name).read_bytes()
            for folder in self.outputs
            for name in ("atlas.html", "atlas-data.js", "workspace-index.json")
        }
        server = self.server()
        for folder in self.outputs:
            self.assertEqual(
                (folder / "atlas.html").read_bytes(), originals[folder / "atlas.html"]
            )
        status, _, raw = self.get(server, "/views/stage1/atlas.html")
        self.assertEqual(status, 200)
        self.assertIn(b"connect-src 'self'", raw)
        self.assertIn(b"/host-bootstrap/stage1.js", raw)
        self.assertNotIn(
            b"connect-src 'self'", originals[self.outputs[0] / "atlas.html"]
        )
        self.assertFalse(server.host_binding["execution_authority"])
        (self.outputs[0] / "atlas-data.js").write_bytes(b"tampered after admission")
        self.assertEqual(
            self.get(server, "/views/stage1/atlas-data.js")[2],
            originals[self.outputs[0] / "atlas-data.js"],
        )
        self.assertEqual(
            {p: p.read_bytes() for p in originals if p.name != "atlas-data.js"},
            {p: raw for p, raw in originals.items() if p.name != "atlas-data.js"},
        )

    def test_stale_config_manifest_file_and_cross_binding_reject(self):
        with self.assertRaises(ValueError):
            load_views(self.config, "0" * 64)
        path = self.outputs[0] / "view-manifest.json"
        original = path.read_bytes()
        path.write_bytes(original + b" ")
        with self.assertRaises(ValueError):
            load_views(self.config, self.pin)
        path.write_bytes(original)
        (self.outputs[0] / "atlas-data.js").write_bytes(b"different source")
        with self.assertRaises(ValueError):
            load_views(self.config, self.pin)

    def test_duplicate_refs_path_traversal_and_unregistered_routes_reject(self):
        self.entries[1]["ref"] = "stage1"
        with self.assertRaises(ValueError):
            load_views(self.config, self.save_config())
        self.entries[1]["ref"] = "../stage2"
        with self.assertRaises(ValueError):
            load_views(self.config, self.save_config())
        self.entries[1]["ref"] = "stage2"
        self.pin = self.save_config()
        server = self.server()
        for route in (
            "/views/stage1/../host.json",
            "/views/stage1/host.json",
            "/api/native/projects/stage1",
            "/host-bootstrap/unknown.js",
        ):
            self.assertEqual(self.get(server, route)[0], 404)

    def test_cached_connection_requires_credential_and_never_exposes_native_writes(
        self,
    ):
        server = self.server()
        self.assertEqual(self.get(server, "/api/connection")[0], 401)
        headers = {"Authorization": "Bearer " + server.credential}
        for _ in range(3):
            status, _, raw = self.get(server, "/api/connection", headers=headers)
            self.assertEqual(status, 200)
            value = json.loads(raw)
            self.assertFalse(value["model_turn_tested"])
            self.assertFalse(value["research_session_started"])
        self.assertEqual(server.api._projects, {})
        self.assertEqual(
            self.get(server, "/api/connection", method="POST", headers=headers)[0], 405
        )

    def test_same_title_views_separate_bootstrap_and_block_cross_site(self):
        server = self.server()
        for ref in ("stage1", "stage2"):
            status, headers, raw = self.get(server, "/host-bootstrap/" + ref + ".js")
            self.assertEqual(status, 200)
            self.assertEqual(headers["Cache-Control"], "no-store")
            data = json.loads(
                raw.decode().splitlines()[0][len("window.WORKSPACE_HOST=") : -1]
            )
            self.assertEqual(data["current_case"], ref)
            self.assertEqual(len(data["cases"]), 2)
        for headers in (
            {"Host": "attacker.invalid"},
            {"Origin": "https://example.com"},
            {"Sec-Fetch-Site": "cross-site"},
            {"Content-Length": "1"},
        ):
            self.assertIn(
                self.get(server, "/host-bootstrap/stage1.js", headers=headers)[0],
                (400, 403),
            )
        raw = self.get(server, "/")[2]
        self.assertNotIn(b"<img>", raw)
        self.assertIn(b"&lt;img&gt;", raw)


if __name__ == "__main__":
    unittest.main()
