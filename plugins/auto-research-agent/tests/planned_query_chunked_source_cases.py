"""Actual fresh raw-source guard with synthetic files; no executor is called."""

from copy import deepcopy
import io
from pathlib import Path
import stat
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import planned_query_fixture as fixture
from research_workspace_native.planned_queries import PlannedQueryService  # noqa: F401
from research_workspace_native.query_execution_source import check_execution_source
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
import stage1_retrieval.runner as runner


class ChunkedQuerySourceTests(unittest.TestCase):
    def setUp(self):
        self.proof = fixture.RAW_SOURCE_PROOF
        if self.proof is None:
            raise RuntimeError("fresh raw-loader child required")
        self.relative = "cli/synthetic-chunked-proof.bin"
        self.target = (
            Path(self.proof["repo"]) / "plugins/auto-research-agent" / self.relative
        )
        if self.target.exists() or self.relative in self.proof["files"]:
            raise RuntimeError("exclusive synthetic file required")
        self.addCleanup(self.cleanup)

    def cleanup(self):
        self.proof["files"].pop(self.relative, None)
        self.target.unlink(missing_ok=True)

    def bind(self, raw):
        self.target.write_bytes(raw)
        self.proof["files"][self.relative] = sha(raw)
        return dict(
            execution_source_sha256=sha(canonical(self.proof["files"])),
            execution_source_root=Path(self.proof["repo"]).as_posix(),
        )

    def check(self, item):
        return check_execution_source(
            lambda _: deepcopy(self.proof),
            "synthetic",
            item,
            "before-runner",
            runner.execute,
        )

    def test_all_chunks_and_empty_hash_keep_complete_source_manifest(self):
        raw = bytes(range(256)) * 1024 + b"end"
        self.assertTrue(self.check(self.bind(raw)))
        self.assertTrue(self.check(self.bind(b"")))

    def test_short_reads_continue_until_eof_with_bounded_requests(self):
        raw = b"source-short-read" * 10000
        item = self.bind(raw)
        requests, observed = [], []

        class ShortReader(io.BytesIO):
            def read(self, count=-1):
                requests.append(count)
                chunk = super().read(min(count, 17))
                observed.append(len(chunk))
                return chunk

        original = Path.open

        def opened(value, *args, **kwargs):
            return (
                ShortReader(raw)
                if value == self.target
                else original(value, *args, **kwargs)
            )

        with patch.object(Path, "open", autospec=True, side_effect=opened):
            self.assertTrue(self.check(item))
        self.assertLessEqual(max(requests), 64 * 1024)
        self.assertEqual(sum(observed), len(raw))

    def test_growth_after_regular_stat_stops_at_32mib_plus_one(self):
        item = self.bind(b"x")
        requests, observed = [], []

        class GrowingReader(io.BytesIO):
            def read(self, count=-1):
                requests.append(count)
                chunk = super().read(count)
                observed.append(len(chunk))
                return chunk

        original = Path.open

        def opened(value, *args, **kwargs):
            return (
                GrowingReader(b"x" * (32 * 1024 * 1024 + 17))
                if value == self.target
                else original(value, *args, **kwargs)
            )

        with patch.object(Path, "open", autospec=True, side_effect=opened):
            with self.assertRaisesRegex(
                SessionApiError, "query-execution-source-bytes-differ"
            ):
                self.check(item)
        self.assertLessEqual(max(requests), 64 * 1024)
        self.assertEqual(sum(observed), 32 * 1024 * 1024 + 1)

    def test_same_size_mutation_and_next_invocation_reparse_are_not_cached(self):
        item = self.bind(b"original")
        self.assertTrue(self.check(item))
        self.target.write_bytes(b"modified")
        with self.assertRaisesRegex(
            SessionApiError, "query-execution-source-bytes-differ"
        ):
            self.check(item)
        self.target.write_bytes(b"original")
        original = Path.lstat

        def reparse(value):
            if value == self.target.parent:
                return SimpleNamespace(st_mode=stat.S_IFDIR, st_file_attributes=0x400)
            return original(value)

        with patch.object(Path, "lstat", reparse):
            with self.assertRaisesRegex(
                SessionApiError, "query-execution-source-link-refused"
            ):
                self.check(item)
