"""Explicit SQLite reopen and old action recovery, without a producer replay."""

from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import stat
import tempfile
import threading
import time
import unittest
from unittest.mock import patch
from types import SimpleNamespace

from research_workspace.atlas import atlas_files
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.harness_host import create_harness_operations
from stage1_deliverable.common import canonical, sha
from test_workspace_atlas import payload


class HarnessReuseTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="harness-reuse-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "operations"
        self.token = "first-" + "t" * 40
        value = payload()
        self.raw = canonical(value["index"])
        self.files = {
            "/views/alpha/" + key: raw for key, raw in atlas_files(value).items()
        }
        self.files["/views/alpha/workspace-index.json"] = self.raw
        self.views = [
            dict(
                ref="alpha",
                project_id=value["index"]["project_id"],
                index_sha256=sha(self.raw),
                url="/views/alpha/atlas.html",
                label="Synthetic",
                fixture=True,
                manifest_sha256="a" * 64,
            )
        ]
        self.service = create_harness_operations(
            self.files, self.views, self.root, self.token
        )
        self.addCleanup(lambda: self.service.close())

    def request(self, key):
        view = self.service.view(self.token, "alpha")
        return dict(
            action="validate-index",
            key=key,
            index_sha256=view["index_sha256"],
            expected_revision=view["revision"],
        )

    def test_closed_database_reopens_new_owner_and_credential_with_get_only_recovery(
        self,
    ):
        prior_owner = self.service._projects["alpha"]["owner"]
        done = self.service.execute(
            self.token, "alpha", self.request("done"), deadline=time.monotonic() + 10
        )
        with patch.object(self.service, "_produce", side_effect=KeyboardInterrupt):
            with self.assertRaises(KeyboardInterrupt):
                self.service.execute(
                    self.token,
                    "alpha",
                    self.request("unfinished"),
                    deadline=time.monotonic() + 10,
                )
        self.service.close()
        self.token = "second-" + "s" * 40
        self.service = create_harness_operations(
            self.files, self.views, self.root, self.token, reuse=True
        )
        self.assertNotEqual(self.service._projects["alpha"]["owner"], prior_owner)
        server = AtlasHost(
            files=self.files,
            views=self.views,
            credential=self.token,
            harness_ops=self.service,
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()
        try:
            with patch.object(
                self.service, "_produce", wraps=self.service._produce
            ) as producer:
                for key, status in (
                    ("done", "completed"),
                    ("unfinished", "execution-unknown"),
                ):
                    client = http.client.HTTPConnection(
                        "127.0.0.1", server.server_port, timeout=3
                    )
                    try:
                        client.request(
                            "GET",
                            "/api/harness/projects/alpha/actions/" + key,
                            headers={"Authorization": "Bearer " + self.token},
                        )
                        response = client.getresponse()
                        self.assertEqual(response.status, 200)
                        row = json.loads(response.read())
                        self.assertEqual(row["status"], status)
                        if key == "done":
                            self.assertEqual(row, done)
                    finally:
                        client.close()
                self.assertEqual(producer.call_count, 0)
                self.assertEqual(
                    self.service.view(self.token, "alpha")["history_count"], 2
                )
        finally:
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

    def test_reuse_requires_regular_database_exact_source_and_registration_set(self):
        self.service.close()
        database = self.root / "operations.sqlite3"
        before = sha(database.read_bytes())
        with self.assertRaises(FileExistsError):
            create_harness_operations(self.files, self.views, self.root, self.token)
        changed = dict(self.files)
        changed["/views/alpha/workspace-index.json"] += b"\n"
        views = deepcopy(self.views)
        views[0]["index_sha256"] = sha(changed["/views/alpha/workspace-index.json"])
        with self.assertRaisesRegex(
            ValueError, "saved Harness operation binding differs"
        ):
            create_harness_operations(changed, views, self.root, self.token, reuse=True)
        renamed = deepcopy(self.views)
        renamed[0]["ref"] = "beta"
        files = {
            key.replace("/alpha/", "/beta/"): raw for key, raw in self.files.items()
        }
        with self.assertRaisesRegex(ValueError, "registration set differs"):
            create_harness_operations(files, renamed, self.root, self.token, reuse=True)
        self.assertEqual(sha(database.read_bytes()), before)
        missing = self.root.parent / "missing"
        missing.mkdir()
        with self.assertRaisesRegex(ValueError, "existing regular"):
            create_harness_operations(
                self.files, self.views, missing, self.token, reuse=True
            )
        (missing / "operations.sqlite3").mkdir()
        with self.assertRaisesRegex(ValueError, "existing regular"):
            create_harness_operations(
                self.files, self.views, missing, self.token, reuse=True
            )

    def test_linked_companions_rejected_before_readonly_sqlite_open(self):
        self.service.close()
        database = self.root / "operations.sqlite3"
        before = sha(database.read_bytes())
        original_lstat = os.lstat
        for suffix in ("-wal", "-shm", "-journal"):
            companion = database.with_name(database.name + suffix)
            for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFREG, 0x400)):
                with self.subTest(suffix=suffix, attributes=attributes):

                    def marked(path, *args, **kwargs):
                        if Path(path) == companion:
                            return SimpleNamespace(
                                st_mode=mode, st_file_attributes=attributes
                            )
                        return original_lstat(path, *args, **kwargs)

                    with (
                        patch("stage1_deliverable.common.os.lstat", marked),
                        patch(
                            "research_workspace_native.harness_host.sqlite3.connect",
                            side_effect=AssertionError(
                                "SQLite opened before link guard"
                            ),
                        ) as connection,
                    ):
                        with self.assertRaisesRegex(ValueError, "linked artifact"):
                            create_harness_operations(
                                self.files,
                                self.views,
                                self.root,
                                self.token,
                                reuse=True,
                            )
                        connection.assert_not_called()
        self.assertEqual(sha(database.read_bytes()), before)


if __name__ == "__main__":
    unittest.main()
