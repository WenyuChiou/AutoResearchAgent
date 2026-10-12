"""Saved delivery GETs over actual temporary SQLite; no dispatch or live I/O."""

import http.client
import json
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest
from contextlib import ExitStack, contextmanager
from copy import deepcopy
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import PropertyMock, patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_delivery_http as http_fixture
from research_workspace.canonical_delivery import project_canonical_atlas
from research_workspace_native import project_stage1_atlas as atlas
from research_workspace_native.project_stage1_atlas import ProjectStage1AtlasService
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import inventory, sha
from stage1_ledger.journal import canonical
from test_project_stage1_records import saved_stage1_case


class ProjectStage1AtlasChannelTests(unittest.TestCase):
    def test_inline_parent_and_child_channels_remain_bound_and_readonly(self):
        node = shutil.which("node")
        self.assertIsNotNone(node, "Node is required for actual channel source checks")
        folder = Path(__file__).parent / "browser"
        for name in ("project-atlas-channel-test.cjs", "project-atlas-child-test.cjs"):
            with self.subTest(script=name):
                result = subprocess.run(
                    [node, str(folder / name)],
                    capture_output=True,
                    text=True,
                    encoding="utf8",
                    timeout=30,
                )
                self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
                print(result.stdout.strip())


class ProjectStage1AtlasTests(unittest.TestCase):
    def setUp(self):
        self.saved = saved_stage1_case()
        self.case, self.fixture = self.saved.__enter__()
        self.addCleanup(lambda: self.saved.__exit__(None, None, None))
        self.ref = self.fixture["ref"]
        offer = self.case.produce(self.fixture)
        self.case.delivery.deliver(
            "alice-token", self.ref, self.case.body(self.fixture, offer)
        )
        self.case.reopen()
        self.service = ProjectStage1AtlasService(self.case.delivery)
        state = self.case.intake._load("alice", self.ref)
        self.artifact = deepcopy(state["stage1_canonical_package"])
        self.args = {
            "input_version": state["input_version"],
            "revision": state["revision"],
            "artifact_ref": self.artifact["artifact_ref"],
            "manifest_sha256": self.artifact["manifest_sha256"],
        }
        self.root = self.case.delivery._saved_artifact(
            "alice", state, self.artifact, self.case.delivery._context(self.ref)
        )
        # The saved authored fixture is built before this guard. Every service
        # read must be byte-only and must never dispatch its producer again.
        self.guards = self.enterContext(ExitStack())
        self.forbidden = [
            self.guards.enter_context(
                patch(name, side_effect=AssertionError("read executed " + name))
            )
            for name in (
                "stage1_deliverable.package.build",
                "stage1_deliverable.package.validate",
                "stage1_deliverable.sources.validate_archive",
            )
        ]
        self.forbidden.extend(
            self.guards.enter_context(
                patch.object(
                    self.case.intake,
                    name,
                    side_effect=AssertionError("read wrote state"),
                )
            )
            for name in ("_save", "_perform")
        )

    def tearDown(self):
        for guard in self.forbidden:
            guard.assert_not_called()
        self.case.runner.assert_not_called()

    def read(self, credential="alice-token", **changes):
        return self.service.read(credential, self.ref, **(self.args | changes))

    def change_state(self, **changes):
        state = self.case.intake._load("alice", self.ref)
        state.update(changes)
        self.case.intake.db.execute(
            "UPDATE intake_projects SET state=? WHERE ref=?",
            (canonical(state).decode(), self.ref),
        )

    def test_reopened_get_preserves_evidence_and_performs_no_dispatch_or_write(self):
        before = inventory(self.root)
        rows = self.case.intake.db.execute(
            "SELECT COUNT(*) FROM intake_events"
        ).fetchone()[0]
        changes = self.case.intake.db.total_changes
        first = self.read()
        second = self.read()
        self.assertEqual(first, second)
        self.assertEqual(first["schema"], "ProjectStage1AtlasView/1")
        self.assertEqual(first["payload"]["index_sha256"], first["index_sha256"])
        index = first["payload"]["index"]
        self.assertEqual(first["index_sha256"], sha(canonical(index)))
        self.assertEqual(len(index["papers"]), 2)
        self.assertIn("Unknown", str(index))
        self.assertIn("partial", str(index))
        self.assertEqual(index["readiness"]["status"], "not-provided")
        self.assertFalse(index["readiness"]["stage2_execution_authorized"])
        self.assertNotIn("stage2", first["payload"])
        self.assertEqual(before, inventory(self.root))
        self.assertEqual(self.case.intake.db.total_changes, changes)
        self.assertEqual(
            rows,
            self.case.intake.db.execute(
                "SELECT COUNT(*) FROM intake_events"
            ).fetchone()[0],
        )
        self.assertEqual(len(first["files"]), 5)
        self.assertNotIn(str(self.case.intake_root), str(first))

    def test_file_catalog_is_opaque_bound_and_only_exposes_notes_and_bibtex(self):
        view = self.read()
        for entry in view["files"]:
            with self.subTest(path=entry["path"]):
                result = self.read(
                    file_ref=entry["file_ref"], file_sha256=entry["sha256"]
                )
                self.assertEqual(result["index_sha256"], view["index_sha256"])
                self.assertEqual(
                    result["file"]["sha256"], sha(result["file"]["content"].encode())
                )
                self.assertEqual(
                    result["file"]["filename"], entry["path"].rsplit("/", 1)[-1]
                )
                self.assertNotIn("payload", result)
                self.assertNotIn("path", result["file"])
        entry = view["files"][0]
        with self.assertRaisesRegex(SessionApiError, "file-hash-differs"):
            self.read(file_ref=entry["file_ref"], file_sha256="0" * 64)
        with self.assertRaisesRegex(SessionApiError, "file-unavailable"):
            self.read(file_ref="0" * 64, file_sha256="0" * 64)
        with self.assertRaisesRegex(SessionApiError, "request-invalid"):
            self.read(file_ref="../records.original.json", file_sha256="0" * 64)
        with self.assertRaisesRegex(SessionApiError, "request-invalid"):
            self.read(file_ref=entry["file_ref"])

    def test_principal_revision_input_artifact_and_hash_must_match_latest_saved_delivery(
        self,
    ):
        for credential, code in (
            ("bad", "unauthorized"),
            ("bob-token", "project-unavailable"),
        ):
            with (
                self.subTest(credential=credential),
                self.assertRaisesRegex(SessionApiError, code),
            ):
                self.read(credential)
        for change, code in (
            ({"revision": self.args["revision"] + 1}, "stale-revision"),
            ({"input_version": self.args["input_version"] + 1}, "stale-input-version"),
            (
                {"artifact_ref": "stage1-canonical-" + "0" * 32},
                "artifact-binding-differs",
            ),
            ({"manifest_sha256": "0" * 64}, "artifact-binding-differs"),
            ({"input_version": True}, "request-invalid"),
            ({"revision": False}, "request-invalid"),
        ):
            with (
                self.subTest(change=change),
                self.assertRaisesRegex(SessionApiError, code),
            ):
                self.read(**change)

    def test_saved_artifact_and_canonical_bytes_tampering_are_refused(self):
        raw = (self.root / "records.original.json").read_bytes()
        (self.root / "records.original.json").write_bytes(raw + b" ")
        with self.assertRaisesRegex(SessionApiError, "source-bytes-differ"):
            self.read()
        (self.root / "records.original.json").write_bytes(raw)
        altered = deepcopy(self.artifact)
        altered["status"] = "forged-validated"
        self.change_state(stage1_canonical_package=altered)
        with self.assertRaisesRegex(SessionApiError, "artifact-receipt-differs"):
            self.read()

    def test_scope_revision_and_delivery_change_during_projection_fail_closed(self):
        real = atlas.project_canonical_atlas

        def change(*args, **kwargs):
            result = real(*args, **kwargs)
            self.change_state(revision=self.args["revision"] + 1)
            return result

        with (
            patch.object(atlas, "project_canonical_atlas", side_effect=change),
            self.assertRaisesRegex(SessionApiError, "stale-revision"),
        ):
            self.read()

    def test_source_change_after_projection_and_current_brief_bytes_are_refused(self):
        real = atlas.project_canonical_atlas

        def change(*args, **kwargs):
            result = real(*args, **kwargs)
            (self.root / "papers.jsonl").write_bytes(b"changed")
            return result

        original = (self.root / "papers.jsonl").read_bytes()
        with (
            patch.object(atlas, "project_canonical_atlas", side_effect=change),
            self.assertRaisesRegex(SessionApiError, "source-bytes-differ"),
        ):
            self.read()
        (self.root / "papers.jsonl").write_bytes(original)
        state = self.case.intake._load("alice", self.ref)
        brief = self.case.intake._path(self.ref, state["briefs"][-1]["path"])
        brief.write_bytes(brief.read_bytes() + b" ")
        with self.assertRaisesRegex(SessionApiError, "source-bytes-differ"):
            self.read()

    def test_deadline_checks_refuse_before_validation_after_projection_and_after_final_recheck(
        self,
    ):
        for stop in (1, 2, 4, 5):
            calls = []

            def deadline(calls=calls, stop=stop):
                calls.append(None)
                if len(calls) == stop:
                    raise SessionApiError("deadline-expired", 408)

            with (
                self.subTest(stop=stop),
                self.assertRaisesRegex(SessionApiError, "deadline-expired"),
            ):
                self.read(check_deadline=deadline)
            self.assertEqual(len(calls), stop)

    def test_projection_json_and_bounds_cannot_be_bypassed(self):
        real = atlas.project_canonical_atlas

        def bad_data(*args, **kwargs):
            index, files = real(*args, **kwargs)
            files["atlas-data.js"] = atlas.PREFIX + b'{}; alert("bad");\n'
            return index, files

        with (
            patch.object(atlas, "project_canonical_atlas", side_effect=bad_data),
            self.assertRaisesRegex(SessionApiError, "source-binding-failed"),
        ):
            self.read()
        with (
            patch.object(atlas, "MAX_FILE_BYTES", 1),
            self.assertRaisesRegex(SessionApiError, "file-bound"),
        ):
            self.read()
        with (
            patch.object(atlas, "MAX_PAYLOAD_BYTES", 1),
            self.assertRaisesRegex(SessionApiError, "payload-invalid"),
        ):
            self.read()
        with (
            patch.object(atlas, "MAX_RESPONSE", 1),
            self.assertRaisesRegex(SessionApiError, "response-bound"),
        ):
            self.read()

    def test_renderer_snapshot_is_readonly_and_projection_drift_is_refused(self):
        self.assertNotIn("atlas.html", self.service.renderer_sha256)
        self.assertIn("atlas-model.js", self.service.renderer_sha256)
        with self.assertRaises(TypeError):
            self.service.renderer_sha256["atlas.css"] = "0" * 64
        real = atlas.project_canonical_atlas

        def drift(*args, **kwargs):
            index, files = real(*args, **kwargs)
            files["atlas.css"] += b" /* changed after host initialization */"
            return index, files

        with (
            patch.object(atlas, "project_canonical_atlas", side_effect=drift),
            self.assertRaisesRegex(SessionApiError, "renderer-bytes-differ"),
        ):
            self.read()

    def test_immutable_snapshot_projection_never_reopens_package_content(self):
        snapshot = atlas._source(self.root, self.args["manifest_sha256"])
        baseline, _ = project_canonical_atlas(
            self.root, self.ref, self.args["manifest_sha256"]
        )
        with self.assertRaises(TypeError):
            snapshot["papers.jsonl"] = b"changed"
        real_read = Path.read_bytes

        def no_package_read(path):
            if path.resolve().is_relative_to(self.root.resolve()):
                raise AssertionError("snapshot projection reopened package content")
            return real_read(path)

        (self.root / "papers.jsonl").write_bytes(b"changed after bounded snapshot")
        with (
            patch.object(Path, "read_bytes", no_package_read),
            patch(
                "research_workspace.canonical_delivery.inventory",
                side_effect=AssertionError("unbounded inventory"),
            ),
        ):
            index, _ = project_canonical_atlas(
                self.root,
                self.ref,
                self.args["manifest_sha256"],
                artifact_bytes=snapshot,
            )
        self.assertEqual(index, baseline)
        with self.assertRaisesRegex(SessionApiError, "source-bytes-differ"):
            self.read()


class ProjectStage1AtlasBoundedReadTests(unittest.TestCase):
    def setUp(self):
        temporary = self.enterContext(
            tempfile.TemporaryDirectory(prefix="atlas-bounded-")
        )
        self.root = Path(temporary).resolve()
        self.manifest = self.root / "provenance_manifest.json"

    def package(self, files):
        for name, raw in files.items():
            path = self.root / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        raw = canonical({"files": {name: sha(raw) for name, raw in files.items()}})
        self.manifest.write_bytes(raw)
        return sha(raw)

    def test_unlisted_sparse_large_file_is_refused_before_any_artifact_content_read(
        self,
    ):
        digest = self.package({"paper.txt": b"authored"})
        with (self.root / "unlisted.bin").open("wb") as stream:
            stream.truncate(atlas.MAX_FILE_BYTES + 1)
        with (
            patch.object(atlas, "_read_bounded", wraps=atlas._read_bounded) as read,
            self.assertRaisesRegex(SessionApiError, "source-path-unlisted"),
        ):
            atlas._source(self.root, digest)
        self.assertEqual(
            [row.args[0].name for row in read.call_args_list], [self.manifest.name]
        )

    def test_special_file_and_windows_reparse_metadata_are_rejected_without_open(self):
        digest = self.package({"paper.txt": b"authored"})
        scandir = os.scandir

        for mode, attributes in ((stat.S_IFIFO, 0), (stat.S_IFREG, 0x400)):

            @contextmanager
            def altered(path, mode=mode, attributes=attributes):
                with scandir(path) as entries:
                    result = []
                    for entry in entries:
                        if entry.name == "paper.txt":
                            info = SimpleNamespace(
                                st_mode=mode, st_size=8, st_file_attributes=attributes
                            )
                            result.append(
                                SimpleNamespace(
                                    path=entry.path, stat=lambda info=info, **_: info
                                )
                            )
                        else:
                            result.append(entry)
                    yield result

            with (
                self.subTest(mode=mode, attributes=attributes),
                patch.object(atlas.os, "scandir", altered),
                patch.object(atlas, "_read_bounded", wraps=atlas._read_bounded) as read,
                self.assertRaisesRegex(SessionApiError, "special-path"),
            ):
                atlas._source(self.root, digest)
            self.assertEqual(len(read.call_args_list), 1)

    def test_whole_path_count_and_aggregate_bytes_are_bounded_before_content(self):
        digest = self.package({"a/b/c/d/e/paper.txt": b"authored"})
        with (
            patch.object(atlas, "MAX_FILES", 1),
            patch.object(atlas, "_read_bounded", wraps=atlas._read_bounded) as read,
            self.assertRaisesRegex(SessionApiError, "path-bound"),
        ):
            atlas._source(self.root, digest)
        self.assertEqual(len(read.call_args_list), 1)
        with (
            patch.object(atlas, "MAX_PACKAGE_BYTES", self.manifest.stat().st_size + 7),
            patch.object(atlas, "_read_bounded", wraps=atlas._read_bounded) as read,
            self.assertRaisesRegex(SessionApiError, "package-bound"),
        ):
            atlas._source(self.root, digest)
        self.assertEqual(len(read.call_args_list), 1)

    def test_growth_after_fstat_uses_max_plus_one_instead_of_unbounded_read(self):
        digest = self.package({"paper.txt": b"authored"})
        paper = self.root / "paper.txt"
        inode = paper.stat().st_ino
        fstat, fdopen = os.fstat, os.fdopen
        reads = []

        def growth(descriptor):
            info = fstat(descriptor)
            if info.st_ino == inode:
                paper.write_bytes(b"x" * 20)
            return info

        @contextmanager
        def observed(descriptor, mode):
            with fdopen(descriptor, mode) as stream:

                def read(size):
                    reads.append(size)
                    return stream.read(size)

                yield SimpleNamespace(fileno=stream.fileno, read=read)

        with (
            patch.object(atlas, "MAX_FILE_BYTES", 16),
            patch.object(atlas.os, "fstat", growth),
            patch.object(atlas.os, "fdopen", observed),
            self.assertRaisesRegex(SessionApiError, "file-bound"),
        ):
            atlas._source(self.root, digest)
        self.assertEqual(reads, [atlas.MAX_MANIFEST_BYTES + 1, 17])


class ProjectStage1AtlasHttpTests(unittest.TestCase):
    def test_actual_http_bound_view_file_and_auth_rejections_are_private_and_readonly(
        self,
    ):
        fixture = http_fixture.ProjectStage1DeliveryHttpTests(methodName="runTest")
        fixture.setUpClass()
        self.addCleanup(fixture.tearDownClass)
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        status, raw = fixture.request(fixture.base + "/stage1/deliver", fixture.body)
        self.assertEqual(status, 200, raw)
        artifact = json.loads(raw)
        view = fixture.fixture.intake.read(fixture.token, fixture.saved["ref"])
        path = (
            fixture.base
            + f"/stage1/atlas/{view['input_version']}/{view['revision']}"
            + f"/{artifact['artifact_ref']}/{artifact['manifest_sha256']}"
        )

        def request(path, *, method="GET", token=True, origin=None):
            client = http.client.HTTPConnection(
                "127.0.0.1", fixture.host.server_port, timeout=30
            )
            headers = {}
            if token is not None:
                headers["Authorization"] = "Bearer " + (
                    fixture.token if token is True else token
                )
            if origin is not None:
                headers["Origin"] = origin
            if method == "POST":
                headers.update(
                    Origin=fixture.host.expected_origin,
                    **{"Content-Type": "application/json"},
                )
            try:
                client.request(
                    method, path, b"{}" if method == "POST" else None, headers
                )
                reply = client.getresponse()
                return reply.status, reply.read()
            finally:
                client.close()

        changes = fixture.fixture.intake.db.total_changes
        actions = fixture.fixture.intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions"
        ).fetchone()[0]
        with ExitStack() as stack:
            blocked = [
                stack.enter_context(
                    patch(name, side_effect=AssertionError("GET executed producer"))
                )
                for name in (
                    "stage1_deliverable.package.build",
                    "stage1_deliverable.package.validate",
                    "stage1_deliverable.sources.validate_archive",
                )
            ]
            status, raw = request(path)
            self.assertEqual(status, 200, raw)
            result = json.loads(raw)
            self.assertEqual(result["schema"], "ProjectStage1AtlasView/1")
            entry = next(
                item for item in result["files"] if item["path"].endswith(".md")
            )
            file_path = path + f"/files/{entry['file_ref']}/{entry['sha256']}"
            status, raw = request(file_path)
            self.assertEqual(status, 200, raw)
            self.assertEqual(json.loads(raw)["file"]["sha256"], entry["sha256"])
            for kwargs in (
                {"token": None},
                {"token": "wrong"},
                {"origin": "https://unrelated.example"},
            ):
                with self.subTest(kwargs=kwargs):
                    status, raw = request(path, **kwargs)
                    self.assertIn(status, (401, 403), raw)
            for altered in (
                path.replace(f"/{view['revision']}/", "/99999/"),
                path.replace(artifact["artifact_ref"], "stage1-canonical-" + "0" * 32),
                path.replace(artifact["manifest_sha256"], "0" * 64),
                file_path.replace(entry["file_ref"], "0" * 64),
                file_path.replace(entry["sha256"], "0" * 64),
            ):
                with self.subTest(path=altered):
                    status, raw = request(altered)
                    self.assertIn(status, (400, 404, 409), raw)
            status, raw = request(path, method="POST")
            self.assertIn(status, (400, 404, 405), raw)
            status, raw = request("/project-atlas.html", token=None)
            self.assertEqual(status, 200, raw)
            self.assertNotIn(
                fixture.saved["records"]["papers"][0]["title"].encode(), raw
            )
            # The helper and derived UI are code-only assets bound to this host.
            for name in ("atlas-ui.js", "project-atlas-screening.js"):
                status, raw = request("/project-atlas-static/" + name, token=None)
                self.assertEqual(status, 200, raw)
                self.assertEqual(
                    sha(raw), fixture.host.project_stage1_atlas.renderer_sha256[name]
                )
            status, raw = request("/project-atlas-child.js", token=None)
            self.assertEqual(status, 200, raw)
            self.assertLess(
                raw.index(b'"project-atlas-screening.js"'), raw.index(b'"atlas-ui.js"')
            )
            with (
                patch.object(
                    atlas.ProjectStage1AtlasService,
                    "renderer_sha256",
                    new_callable=PropertyMock,
                    return_value={},
                ),
                patch(
                    "research_workspace_native.project_host.AtlasHost.__init__"
                ) as bind,
                self.assertRaisesRegex(ValueError, "renderer snapshot differs"),
            ):
                from research_workspace_native.project_host import ProjectHost

                ProjectHost(
                    projects=fixture.fixture.intake,
                    credential=fixture.token,
                    stage1=fixture.fixture.stage1,
                    files={},
                    views=[],
                    port=0,
                )
            bind.assert_not_called()
            for absent in ("/atlas-data.js", "/wiki/" + "0" * 64 + ".md"):
                status, raw = request(absent)
                self.assertEqual(status, 404, raw)
            for check in blocked:
                check.assert_not_called()
        fixture.fixture.runner.assert_not_called()
        self.assertEqual(fixture.fixture.intake.db.total_changes, changes)
        self.assertEqual(
            actions,
            fixture.fixture.intake.db.execute(
                "SELECT COUNT(*) FROM intake_actions"
            ).fetchone()[0],
        )


if __name__ == "__main__":
    unittest.main()
