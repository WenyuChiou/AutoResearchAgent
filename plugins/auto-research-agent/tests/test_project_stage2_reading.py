"""Ordinary saved reports grant reading only; fixtures run no research or models."""

# ruff: noqa: E402 -- use the authored CLI fixture.
from copy import deepcopy
import http.client
import json
from pathlib import Path
import shutil
import subprocess
import sys
import threading
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).parents[1] / "cli"), str(Path(__file__).parent)]
import test_stage2_delivery as delivery_fixture
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.http import token_authenticator
from research_workspace_native.project_host import ProjectHost, main
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2_reading import Stage2ReadingRegistry
from stage1_deliverable.common import canonical, sha
from stage2_common import Stage2Error


class Stage2ReadingTests(unittest.TestCase):
    def setUp(self):
        self.fixture = delivery_fixture.Stage2DeliveryTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root.resolve()
        self.delivery = self.root / "ordinary"
        self.manifest = self.fixture._build(
            self.delivery,
            [],
            {
                "candidate_resolutions": [],
                "next_step": "Complete both independent reviews.",
            },
        )
        self.config_path = self.root / "reading.json"
        self.config = dict(
            kind="Stage2ReadingConfiguration",
            schema_version="1.0.0",
            readings=[
                dict(
                    ref="saved-report",
                    label="Saved <script>literal</script>",
                    delivery_root=str(self.delivery.resolve()),
                    delivery_manifest_sha256=self.manifest["manifest_sha256"],
                )
            ],
        )
        self.token = "reading-only-local-test-token-with-32-characters"
        self.projects = ProjectIntakeService(
            self.root / "projects",
            authenticate=token_authenticator({self.token: "local-viewer"}),
        )
        self.addCleanup(self.projects.close)

    def config_bytes(self, value=None):
        raw = canonical(self.config if value is None else value)
        self.config_path.write_bytes(raw)
        return sha(raw)

    def registry(self):
        return Stage2ReadingRegistry(self.config_path, self.config_bytes())

    def test_zero_recommendations_preserve_original_report_unknowns_and_no_state(self):
        before = delivery_fixture._tree_hash(self.delivery)
        registry = self.registry()
        assets, refs = registry.snapshot()
        self.assertEqual(refs[0]["recommendation_count"], 0)
        self.assertTrue(refs[0]["reading_only"])
        self.assertFalse(refs[0]["stage1_lineage_attested"])
        self.assertFalse(refs[0]["selection_authority"])
        self.assertFalse(refs[0]["execution_authorized"])
        prefix = "/project-stage2-readings/saved-report/"
        self.assertEqual(
            assets[prefix + "selection.md"],
            (self.delivery / "selection.md").read_bytes(),
        )
        self.assertEqual(
            assets[prefix + "selection.json"],
            (self.delivery / "selection.json").read_bytes(),
        )
        page = assets[prefix + "index.html"].decode()
        self.assertIn("Saved &lt;script&gt;literal&lt;/script&gt;", page)
        self.assertIn('class="stage2-reading-nav"', page)
        self.assertIn('href="reading.css"', page)
        self.assertEqual(
            assets[prefix + "reading.css"], b".stage2-reading-nav{flex-wrap:wrap}"
        )
        self.assertNotIn("<script>", page)
        self.assertNotIn("<form", page)
        self.assertIn("recommended candidates: 0", page)
        self.assertNotIn(str(self.delivery), page)
        self.assertEqual(before, delivery_fixture._tree_hash(self.delivery))
        self.assertEqual(self.projects.list(self.token), [])
        # Mutating returned projections cannot alter the sealed registry.
        refs[0]["selection_authority"] = True
        assets.clear()
        self.assertFalse(registry.snapshot()[1][0]["selection_authority"])

    def test_bad_config_hash_shape_duplicate_and_relative_paths_reject(self):
        good_hash = self.config_bytes()
        for value in ("0" * 64, None, 4, True):
            with self.subTest(hash=value), self.assertRaises((ValueError, TypeError)):
                Stage2ReadingRegistry(self.config_path, value)
        for mutate in (
            lambda c: c.update(execution_authorized=True),
            lambda c: c.update(readings=[]),
            lambda c: c["readings"].append(deepcopy(c["readings"][0])),
            lambda c: c["readings"][0].update(ref="../foreign"),
            lambda c: c["readings"][0].update(delivery_root="relative/delivery"),
            lambda c: c["readings"][0].update(label="bad\nlabel"),
            lambda c: c["readings"][0].update(delivery_manifest_sha256="0" * 64),
        ):
            config = deepcopy(self.config)
            mutate(config)
            with (
                self.subTest(config=config),
                self.assertRaises((ValueError, Stage2Error)),
            ):
                Stage2ReadingRegistry(self.config_path, self.config_bytes(config))
        raw = b'{"kind":"Stage2ReadingConfiguration","kind":"other"}'
        self.config_path.write_bytes(raw)
        with self.assertRaises(Stage2Error):
            Stage2ReadingRegistry(self.config_path, sha(raw))
        self.assertNotEqual(good_hash, sha(raw))

    def test_changed_config_and_payload_reject_before_listener_allocation(self):
        registry = self.registry()
        self.config_path.write_bytes(self.config_path.read_bytes() + b" ")
        with patch.object(AtlasHost, "__init__") as allocate:
            with self.assertRaisesRegex(ValueError, "configuration changed"):
                ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage2_readings=registry,
                    files={},
                    views=[],
                    port=0,
                )
            allocate.assert_not_called()
        registry = self.registry()
        report = self.delivery / "selection.md"
        report.write_bytes(report.read_bytes() + b"tampered")
        with patch.object(AtlasHost, "__init__") as allocate:
            with self.assertRaises(Stage2Error):
                ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage2_readings=registry,
                    files={},
                    views=[],
                    port=0,
                )
            allocate.assert_not_called()

    def test_untrusted_registry_and_route_collision_refuse_before_listener(self):
        with patch.object(AtlasHost, "__init__") as allocate:
            with self.assertRaisesRegex(ValueError, "trusted Stage2 reading registry"):
                ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage2_readings=object(),
                    files={},
                    views=[],
                    port=0,
                )
            allocate.assert_not_called()
        registry = self.registry()
        with patch.object(AtlasHost, "__init__") as allocate:
            with self.assertRaisesRegex(ValueError, "routes collide"):
                ProjectHost(
                    projects=self.projects,
                    credential=self.token,
                    stage2_readings=registry,
                    files={
                        "/project-stage2-readings/saved-report/index.html": b"untrusted view"
                    },
                    views=[],
                    port=0,
                )
            allocate.assert_not_called()

    def test_positive_recommendation_still_grants_no_project_choice(self):
        reviews, resolutions = self.fixture._complete_inputs()
        directory = self.root / "recommended-ordinary"
        manifest = self.fixture._build(directory, reviews, resolutions)
        self.config["readings"][0].update(
            delivery_root=str(directory),
            delivery_manifest_sha256=manifest["manifest_sha256"],
        )
        assets, refs = self.registry().snapshot()
        self.assertEqual(refs[0]["recommendation_count"], 1)
        self.assertFalse(refs[0]["selection_authority"])
        self.assertNotIn("<form", assets[refs[0]["url"]].decode())
        self.assertEqual(self.projects.list(self.token), [])

    def test_http_exact_routes_keep_origin_csp_and_no_selection_authority(self):
        registry = self.registry()
        host = ProjectHost(
            projects=self.projects,
            credential=self.token,
            stage2_readings=registry,
            files={},
            views=[],
            port=0,
        )
        worker = threading.Thread(target=host.serve_forever, daemon=False)
        worker.start()

        def get(path, method="GET", headers=None):
            conn = http.client.HTTPConnection(
                host.server_address[0], host.server_address[1], timeout=5
            )
            try:
                conn.request(method, path, headers=headers or {})
                response = conn.getresponse()
                return response.status, dict(response.getheaders()), response.read()
            finally:
                conn.close()

        try:
            code, headers, raw = get("/project-stage2-readings/saved-report/index.html")
            self.assertEqual(code, 200)
            self.assertIn("default-src", headers["Content-Security-Policy"])
            self.assertIn("frame-ancestors 'none'", headers["Content-Security-Policy"])
            self.assertEqual(headers["X-Content-Type-Options"], "nosniff")
            self.assertIn(b"Return to workspace", raw)
            css_code, _, css = get("/project-stage2-readings/saved-report/reading.css")
            self.assertEqual(css_code, 200)
            self.assertEqual(css, b".stage2-reading-nav{flex-wrap:wrap}")
            code, _, raw = get("/project-bootstrap.js")
            bootstrap = json.loads(
                raw.decode()
                .removeprefix("window.RESEARCH_PROJECTS=")
                .removesuffix(";\n")
            )
            self.assertEqual(code, 200)
            self.assertFalse(bootstrap["stage2"])
            self.assertEqual(bootstrap["stage2_selection_projects"], [])
            self.assertEqual(bootstrap["stage2_readings"][0]["ref"], "saved-report")
            for suffix in ("selection.html", "private.txt", "../foreign/index.html"):
                self.assertEqual(
                    get("/project-stage2-readings/saved-report/" + suffix)[0], 404
                )
            self.assertEqual(
                get(
                    "/project-stage2-readings/saved-report/index.html",
                    headers={"Origin": "https://foreign.invalid"},
                )[0],
                403,
            )
            self.assertIn(
                get("/project-stage2-readings/saved-report/index.html", "POST")[0],
                (403, 404, 405),
            )
            self.assertEqual(self.projects.list(self.token), [])
        finally:
            host.shutdown()
            host.server_close()
            worker.join(3)
            self.assertFalse(worker.is_alive())

    def test_config_pairing_fails_before_intake_or_listener(self):
        for args in (
            ["--stage2-reading-config", "missing.json"],
            ["--stage2-reading-sha256", "0" * 64],
        ):
            with (
                patch(
                    "research_workspace_native.project_host.ProjectIntakeService"
                ) as intake,
                patch.object(AtlasHost, "__init__") as allocate,
                self.assertRaises(SystemExit) as error,
            ):
                main(["--projects-root", str(self.root / "uncreated"), *args])
            self.assertEqual(error.exception.code, 2)
            intake.assert_not_called()
            allocate.assert_not_called()

    def test_actual_javascript_trilingual_registry_links_and_refusals(self):
        _, refs = self.registry().snapshot()
        node = shutil.which("node")
        self.assertIsNotNone(
            node, "Node is required for the actual JavaScript contract"
        )
        result = subprocess.run(
            [
                node,
                str(Path(__file__).parent / "browser/project-stage2-readings-test.cjs"),
            ],
            input=json.dumps(refs),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
