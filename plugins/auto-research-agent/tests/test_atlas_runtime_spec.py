"""Pinned configuration tests are offline; no child, native session or model."""

from pathlib import Path
import os
import stat
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from research_workspace_native.runtime_spec import _load
from research_workspace_native.codex_probe import _file_sha
from stage1_deliverable.common import canonical, sha


class RuntimeSpecTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        root = Path(self.tmp.name).resolve()
        source, storage = root / "source", root / "storage"
        source.mkdir()
        storage.mkdir()
        index, research_input = source / "index.json", source / "input.json"
        index.write_bytes(canonical(dict(project_id="synthetic-spec-only")))
        research_input.write_bytes(b"synthetic-input")
        self.spec = dict(
            kind="NativeAtlasRuntimeSpec",
            schema_version="1.0.0",
            project_ref="case",
            project_id="synthetic-spec-only",
            principals=["principal"],
            source_root=source.as_posix(),
            index_path=index.as_posix(),
            index_sha256=sha(index.read_bytes()),
            input_path=research_input.as_posix(),
            input_version=sha(research_input.read_bytes()),
            store_path=(storage / "new.sqlite").as_posix(),
            executable=Path(sys.executable).resolve().as_posix(),
            executable_sha256=_file_sha(Path(sys.executable)),
            model="synthetic-model",
            approval_policy="on-request",
            permit_sha256=sha(b"synthetic-permit"),
            limits=dict(
                lifetime_seconds=30,
                max_stream_bytes=65536,
                max_text_bytes=4096,
                max_starts=4,
                timeout_seconds=2,
            ),
        )
        self.path = root / "spec.json"

    def load(self, value=None, expected=None):
        self.path.write_bytes(canonical(self.spec if value is None else value))
        return _load(
            self.path, sha(self.path.read_bytes()) if expected is None else expected
        )

    def test_valid_spec_is_read_only_and_preserves_bytes(self):
        with patch(
            "research_workspace_native.process_channel.OwnedProcessChannel"
        ) as channel:
            path, digest, spec = self.load()
            channel.assert_not_called()
        self.assertEqual(spec, self.spec)
        self.assertEqual(sha(path.read_bytes()), digest)
        self.assertFalse(Path(spec["store_path"]).exists())

    def test_hash_project_schema_principal_and_limits_fail_closed(self):
        cases = [
            {"index_sha256": "0" * 64},
            {"project_id": "different"},
            {"project_id": "bad:id"},
            {"project_ref": "bad/ref"},
            {"principals": [{}]},
            {"principals": ["principal"] * 2},
            {"kind": "Other"},
            {"limits": {**self.spec["limits"], "max_starts": True}},
            {"limits": {**self.spec["limits"], "lifetime_seconds": 601}},
        ]
        for change in cases:
            with self.subTest(change=change), self.assertRaises(ValueError):
                self.load({**self.spec, **change})
        with self.assertRaises(ValueError):
            self.load(expected="0" * 64)
        self.assertFalse(Path(self.spec["store_path"]).exists())

    def test_source_input_executable_drift_and_historical_store_refuse(self):
        for name in ("input_version", "executable_sha256"):
            with self.subTest(name=name), self.assertRaises(ValueError):
                self.load({**self.spec, name: "0" * 64})
        Path(self.spec["store_path"]).write_bytes(b"retained-history")
        with self.assertRaises(ValueError):
            self.load()
        self.assertEqual(
            Path(self.spec["store_path"]).read_bytes(), b"retained-history"
        )

    def test_external_input_and_source_storage_overlap_refuse(self):
        external = self.path.parent / "external.json"
        external.write_bytes(b"external")
        with self.assertRaises(ValueError):
            self.load(
                {
                    **self.spec,
                    "input_path": external.as_posix(),
                    "input_version": sha(b"external"),
                }
            )
        with self.assertRaises(ValueError):
            self.load(
                {
                    **self.spec,
                    "store_path": (
                        Path(self.spec["source_root"]) / "state.sqlite"
                    ).as_posix(),
                }
            )

    def test_stale_sidecars_remain_untouched_and_prevent_fresh_store(self):
        for suffix in ("-wal", "-shm", "-journal"):
            sidecar = Path(self.spec["store_path"] + suffix)
            sidecar.write_bytes(b"retained-sidecar")
            with (
                self.subTest(suffix=suffix),
                self.assertRaisesRegex(ValueError, "sidecars"),
            ):
                self.load()
            self.assertEqual(sidecar.read_bytes(), b"retained-sidecar")
            self.assertFalse(Path(self.spec["store_path"]).exists())
            sidecar.unlink()

    def test_sidecar_link_and_windows_reparse_evidence_is_rejected(self):
        sidecar = Path(self.spec["store_path"] + "-wal")
        sidecar.write_bytes(b"retained-sidecar")
        original = os.lstat
        for mode, attributes in ((stat.S_IFLNK, 0), (stat.S_IFREG, 0x400)):

            def inspect(path, *args, **kwargs):
                if Path(path) == sidecar:
                    return SimpleNamespace(st_mode=mode, st_file_attributes=attributes)
                return original(path, *args, **kwargs)

            with patch("stage1_deliverable.common.os.lstat", side_effect=inspect):
                with self.assertRaisesRegex(ValueError, "linked|reparse"):
                    self.load()
            self.assertEqual(sidecar.read_bytes(), b"retained-sidecar")
            self.assertFalse(Path(self.spec["store_path"]).exists())


if __name__ == "__main__":
    unittest.main()
