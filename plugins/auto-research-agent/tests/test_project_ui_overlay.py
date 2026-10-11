"""Real HTTP presentation seam; base Atlas and API permissions stay intact."""

import hashlib
from pathlib import Path
import sys
import threading
import unittest

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

from research_workspace_native.atlas_host import load_views
from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_intake import ProjectIntakeService
import test_research_workspace_atlas_host as fixtures


class ProjectUiOverlayTests(unittest.TestCase):
    setUp = fixtures.AtlasHostTests.setUp
    save_config = fixtures.AtlasHostTests.save_config
    get = fixtures.AtlasHostTests.get

    def server(self):
        token = "overlay-local-test-credential-at-least-32-characters"
        projects = ProjectIntakeService(
            self.root / "projects",
            authenticate=token_authenticator({token: "local-viewer"}),
        )
        self.addCleanup(projects.close)
        files, views = load_views(self.config, self.pin)
        server = ProjectHost(
            projects=projects, credential=token, files=files, views=views, port=0
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(3)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server, token

    def test_original_route_relative_assets_and_pinned_bytes_retained(self):
        original = {
            p: p.read_bytes()
            for folder in self.outputs
            for p in folder.rglob("*")
            if p.is_file()
        }
        server, token = self.server()
        status, headers, raw = self.get(server, "/")
        self.assertEqual((status, raw), (302, b""))
        self.assertEqual(headers["Location"], "/views/stage1/atlas.html")
        for route in (
            "/views/stage1/atlas.html",
            "/views/stage1/atlas-data.js",
            "/views/stage1/atlas.css",
            "/views/stage2/atlas.html",
        ):
            self.assertEqual(self.get(server, route)[0], 200)
        html = self.get(server, headers["Location"])[2]
        self.assertIn(b"./atlas-data.js", html)
        self.assertIn(b"project-operations.js", html)
        self.assertNotIn(b"projects.css", html)
        self.assertNotIn(token.encode(), html)
        self.assertEqual(self.get(server, "/views/unknown/atlas.html")[0], 404)
        self.assertEqual({p: p.read_bytes() for p in original}, original)
        self.assertEqual(
            server.host_binding["base_files"][headers["Location"]],
            hashlib.sha256(original[self.outputs[0] / "atlas.html"]).hexdigest(),
        )

    def test_narrow_csp_and_read_only_panel_do_not_create_actions(self):
        server, token = self.server()
        for path in ("/views/stage1/atlas.html", "/project-atlas.html"):
            _, headers, raw = self.get(server, path)
            self.assertIn("frame-src 'self'", headers["Content-Security-Policy"])
            self.assertIn(b"frame-src 'self'", raw)
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
        for path, ancestor in (
            ("/projects-panel.html", "self"),
            ("/projects.html", "none"),
            ("/project-bootstrap.js", "none"),
        ):
            status, headers, raw = self.get(server, path)
            self.assertEqual(status, 200)
            self.assertIn(
                "frame-ancestors '" + ancestor + "'", headers["Content-Security-Policy"]
            )
            self.assertNotIn("frame-src", headers["Content-Security-Policy"])
            self.assertEqual(headers["Cache-Control"], "no-store")
            self.assertEqual(headers["Cross-Origin-Resource-Policy"], "same-origin")
            if path.endswith(".html"):
                self.assertNotIn(token.encode(), raw)
        panel = self.get(server, "/projects-panel.html")[2]
        self.assertIn(b'body class="project-embedded"', panel)
        self.assertIn(b"projects-saved-claims.js", panel)
        self.assertEqual(server.projects.list(token), [])
        self.assertEqual(
            server.projects.db.execute(
                "SELECT COUNT(*) FROM intake_actions"
            ).fetchone()[0],
            0,
        )

    def test_unsafe_panel_redirect_and_bootstrap_requests_still_refuse(self):
        server, _ = self.server()
        for route in ("/", "/projects-panel.html", "/project-bootstrap.js"):
            for headers in (
                {"Origin": "https://foreign.invalid"},
                {"Host": "foreign.invalid"},
                {"Sec-Fetch-Site": "cross-site"},
                {"Transfer-Encoding": "chunked"},
            ):
                with self.subTest(route=route, headers=headers):
                    self.assertEqual(
                        self.get(server, route, headers=headers)[0],
                        403
                        if route in ("/", "/project-bootstrap.js")
                        or "Transfer-Encoding" not in headers
                        else 400,
                    )
        self.assertEqual(self.get(server, "/api/projects")[0], 401)


if __name__ == "__main__":
    unittest.main()
