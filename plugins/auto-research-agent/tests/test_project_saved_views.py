"""Saved references preserve source identity; they never create native projects."""

from copy import deepcopy
import http.client
import json
from pathlib import Path
import sys
import tempfile
import threading
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from research_workspace_native.http import token_authenticator  # noqa: E402
from research_workspace_native.project_host import ProjectHost  # noqa: E402
from research_workspace_native.project_intake import ProjectIntakeService  # noqa: E402
from research_workspace_native.project_ui_overlay import saved_stage1_views  # noqa: E402
from stage1_deliverable.common import canonical, sha  # noqa: E402


def registered(version="20261009-A03"):
    index = canonical(
        {
            "project_id": "original-project",
            "provenance": {"deliverable_manifest_sha256": "d" * 64},
        }
    )
    snapshot = canonical(
        {
            "kind": "SavedSourceCandidateSnapshot",
            "schema_version": "1.0.0",
            "project_id": "original-project",
            "input_version": version,
            "bindings": {
                "view": {"sha256": "a" * 64},
                "deliverable": {"sha256": "d" * 64},
            },
        }
    )
    data = {
        "index.html": b"<html><body>Original saved reader</body></html>",
        "workspace-index.json": index,
        "receiving/snapshot.json": snapshot,
        "atlas.html": b"<html><head><meta content=\"default-src 'none'; connect-src 'none'\"></head><body></body></html>",
        "source.md": b"original complete note",
        "sources/raw.html": b'<html><script src="/project-bootstrap.js"></script><p>Untrusted source</p></html>',
    }
    manifest = {
        "kind": "WorkspaceReadOnlyView",
        "files": {name: sha(raw) for name, raw in data.items()},
        "browser_projection": {"parent_view_manifest_sha256": "a" * 64},
        "saved_stage1_reference": {
            "snapshot_path": "receiving/snapshot.json",
            "snapshot_sha256": sha(snapshot),
        },
    }
    data["view-manifest.json"] = canonical(manifest)
    views = [
        {
            "ref": "saved-A03",
            "label": "Saved A03",
            "project_id": "original-project",
            "fixture": False,
            "url": "/views/saved-A03/atlas.html",
            "manifest_sha256": sha(data["view-manifest.json"]),
            "index_sha256": sha(index),
        }
    ]
    return {"/views/saved-A03/" + name: raw for name, raw in data.items()}, views


class SavedStage1ViewTests(unittest.TestCase):
    def test_original_typed_identity_bytes_and_no_adoption(self):
        for version in ("20261009-A03", 7):
            with self.subTest(version=version):
                files, views = registered(version)
                before = deepcopy((files, views))
                aliases, references, routes = saved_stage1_views(files, views)
                self.assertEqual((files, views), before)
                self.assertEqual(references[0]["input_version"], version)
                self.assertIs(type(references[0]["input_version"]), type(version))
                self.assertFalse(references[0]["accepted"])
                self.assertFalse(references[0]["execution_authorized"])
                self.assertTrue(references[0]["read_only"])
                self.assertEqual(
                    routes, frozenset({"/project-stage1-saved/saved-A03/index.html"})
                )
                self.assertEqual(
                    aliases[references[0]["url"]], files["/views/saved-A03/index.html"]
                )
                self.assertNotIn("/project-bootstrap.js", aliases)
                self.assertEqual(
                    aliases["/project-stage1-saved/saved-A03/source.md"],
                    b"original complete note",
                )

    def test_tampered_pins_typed_identity_and_lineage_reject(self):
        for change in (
            "snapshot-bytes",
            "html-bytes",
            "index-pin",
            "manifest-pin",
            "parent-view",
            "deliverable",
            "foreign-project",
            "bool-version",
            "float-version",
            "array-snapshot",
            "path-traversal",
        ):
            with self.subTest(change=change):
                files, views = registered()
                prefix = "/views/saved-A03/"
                manifest = json.loads(files[prefix + "view-manifest.json"])
                if change == "snapshot-bytes":
                    files[prefix + "receiving/snapshot.json"] += b" "
                elif change == "html-bytes":
                    files[prefix + "index.html"] += b"changed"
                elif change == "index-pin":
                    views[0]["index_sha256"] = "b" * 64
                elif change == "manifest-pin":
                    views[0]["manifest_sha256"] = "b" * 64
                elif change == "path-traversal":
                    manifest["saved_stage1_reference"]["snapshot_path"] = (
                        "../snapshot.json"
                    )
                else:
                    snapshot = json.loads(files[prefix + "receiving/snapshot.json"])
                    if change == "parent-view":
                        snapshot["bindings"]["view"]["sha256"] = "f" * 64
                    if change == "deliverable":
                        snapshot["bindings"]["deliverable"]["sha256"] = "f" * 64
                    if change == "foreign-project":
                        snapshot["project_id"] = "foreign"
                    if change == "bool-version":
                        snapshot["input_version"] = True
                    if change == "float-version":
                        snapshot["input_version"] = 1.0
                    if change == "array-snapshot":
                        snapshot = []
                    raw = canonical(snapshot)
                    files[prefix + "receiving/snapshot.json"] = raw
                    manifest["files"]["receiving/snapshot.json"] = sha(raw)
                    manifest["saved_stage1_reference"]["snapshot_sha256"] = sha(raw)
                if change not in ("manifest-pin",):
                    files[prefix + "view-manifest.json"] = canonical(manifest)
                    views[0]["manifest_sha256"] = sha(
                        files[prefix + "view-manifest.json"]
                    )
                with self.assertRaises(ValueError):
                    saved_stage1_views(files, views)

    def test_http_frame_scope_and_empty_native_store(self):
        files, views = registered()
        with tempfile.TemporaryDirectory(prefix="saved-reference-http-") as directory:
            token = "saved-reference-http-test-credential-at-least-32"
            projects = ProjectIntakeService(
                Path(directory).resolve(),
                authenticate=token_authenticator({token: "local-viewer"}),
            )
            try:
                host = ProjectHost(
                    projects=projects,
                    credential=token,
                    files=files,
                    views=views,
                    port=0,
                )
            except Exception:
                projects.close()
                raise
            worker = threading.Thread(target=host.serve_forever, daemon=True)
            worker.start()
            try:

                def get(path, headers=None):
                    client = http.client.HTTPConnection(
                        "127.0.0.1", host.server_port, timeout=5
                    )
                    try:
                        client.request("GET", path, headers=headers or {})
                        response = client.getresponse()
                        return (
                            response.status,
                            dict(response.getheaders()),
                            response.read(),
                        )
                    finally:
                        client.close()

                status, headers, body = get(
                    "/project-stage1-saved/saved-A03/index.html"
                )
                self.assertEqual(
                    (status, body), (200, files["/views/saved-A03/index.html"])
                )
                self.assertIn(
                    "frame-ancestors 'self'", headers["Content-Security-Policy"]
                )
                self.assertIn(
                    "frame-ancestors 'none'",
                    get("/project-stage1-saved/saved-A03/source.md")[1][
                        "Content-Security-Policy"
                    ],
                )
                source_status, source_headers, source_body = get(
                    "/project-stage1-saved/saved-A03/sources/raw.html"
                )
                self.assertEqual(
                    (source_status, source_body),
                    (200, files["/views/saved-A03/sources/raw.html"]),
                )
                for directive in (
                    "sandbox",
                    "script-src 'none'",
                    "connect-src 'none'",
                    "frame-ancestors 'none'",
                    "form-action 'none'",
                ):
                    self.assertIn(directive, source_headers["Content-Security-Policy"])
                self.assertNotIn("sandbox", headers["Content-Security-Policy"])
                self.assertEqual(
                    get(
                        "/project-stage1-saved/saved-A03/index.html",
                        {"Origin": "https://foreign.invalid"},
                    )[0],
                    403,
                )
                self.assertEqual(
                    get("/project-stage1-saved/saved-A03/index.html?x=1")[0], 404
                )
                parent = get("/views/saved-A03/atlas.html")[2]
                self.assertIn(b"project-saved-view-bindings", parent)
                self.assertIn(b"20261009-A03", parent)
                self.assertNotIn(token.encode(), parent)
                self.assertEqual(projects.list(token), [])
                for table in ("intake_projects", "intake_actions"):
                    self.assertEqual(
                        projects.db.execute("SELECT COUNT(*) FROM " + table).fetchone()[
                            0
                        ],
                        0,
                    )
            finally:
                host.shutdown()
                host.server_close()
                worker.join(3)
                projects.close()
            self.assertFalse(worker.is_alive())

    def test_stage1_and_stage2_saved_readers_coexist_without_project_adoption(self):
        import test_project_stage2_reading as reading_cases

        case = reading_cases.Stage2ReadingTests("runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        files, views = registered()
        registry = case.registry()
        reading_assets, reading_refs = registry.snapshot()
        host = ProjectHost(
            projects=case.projects,
            credential=case.token,
            stage2_readings=registry,
            files=files,
            views=views,
            port=0,
        )
        self.addCleanup(host.server_close)
        self.assertEqual(
            host._assets["/project-stage1-saved/saved-A03/index.html"],
            files["/views/saved-A03/index.html"],
        )
        for path, raw in reading_assets.items():
            self.assertEqual(host._assets[path], raw)
        self.assertEqual(host.stage2_readings, reading_refs)
        self.assertEqual(case.projects.list(case.token), [])


if __name__ == "__main__":
    unittest.main()
