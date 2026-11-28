"""Runtime roots are hashed once per read request and never kept across requests."""

# ruff: noqa: E402 -- exercise repository CLI.
from pathlib import Path
import sys
import tempfile
import threading
import unittest
from types import SimpleNamespace
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from stage1_retrieval import runtime_identity as ri
from stage1_ledger.journal import LedgerError
from research_workspace_native.project_host import ProjectHandler


_FAKE_IDENTITY = None


class RequestScopeTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        (self.root / "a.py").write_text("one", encoding="utf-8")

    def test_inside_a_scope_a_root_is_hashed_once_outside_every_time(self):
        with patch.object(ri, "_tree_files", wraps=ri._tree_files) as real:
            ri.tree_files(self.root)
            ri.tree_files(self.root)
            self.assertEqual(real.call_count, 2)
            with ri.request_scope():
                first = ri.tree_files(self.root)
                second = ri.tree_files(self.root)
                ri.tree_files(self.root, code_only=True)
            self.assertEqual(first, second)
            self.assertEqual(real.call_count, 4)  # one per (root, code_only)

    def test_nothing_survives_the_request_so_a_changed_file_is_seen(self):
        with ri.request_scope():
            before = ri.tree_files(self.root)
        (self.root / "a.py").write_text("two", encoding="utf-8")
        with ri.request_scope():
            after = ri.tree_files(self.root)
        self.assertNotEqual(before, after)
        self.assertNotEqual(ri.tree_files(self.root), before)

    def test_callers_cannot_corrupt_the_scoped_copy_and_errors_end_the_scope(self):
        with self.assertRaises(RuntimeError):
            with ri.request_scope():
                one = ri.tree_files(self.root)
                one.clear()
                self.assertTrue(ri.tree_files(self.root))
                raise RuntimeError("boom")
        self.assertIsNone(ri._scope.trees)

    def test_scope_nests_without_ending_the_outer_one(self):
        with patch.object(ri, "_tree_files", wraps=ri._tree_files) as real:
            with ri.request_scope():
                ri.tree_files(self.root)
                with ri.request_scope():
                    ri.tree_files(self.root)
                ri.tree_files(self.root)
            self.assertEqual(real.call_count, 1)

    def test_chunked_hashing_matches_a_plain_per_file_reference_byte_for_byte(self):
        import hashlib
        import json

        for index in range(150):  # more than two chunks of 64
            folder = self.root / f"d{index % 7}"
            folder.mkdir(exist_ok=True)
            (folder / f"f{index}.py").write_bytes(b"x" * index)
            (folder / f"g{index}.txt").write_bytes(b"y" * index)
        for code_only in (False, True):
            suffixes = {".py", ".pyw", ".pyc", ".pyd", ".so", ".dll", ".zip", ".pth"}
            expected = {}
            for path in sorted(self.root.rglob("*")):
                if path.is_file() and (
                    not code_only or path.suffix.lower() in suffixes
                ):
                    expected[str(path.resolve())] = hashlib.sha256(
                        path.read_bytes()
                    ).hexdigest()
            actual = ri._tree_files(self.root, code_only=code_only)
            self.assertEqual(actual, expected)
            self.assertEqual(
                json.dumps(sorted(actual.items())), json.dumps(sorted(expected.items()))
            )
            with ri.request_scope():
                self.assertEqual(
                    ri.tree_files(self.root, code_only=code_only), expected
                )

    def test_get_requests_reuse_and_post_requests_never_do(self):
        calls = []

        def stub(method):
            def project(_method):
                calls.append((method, ri._scope.trees is not None))
                ri.tree_files(self.root)
                ri.tree_files(self.root)

            return SimpleNamespace(path="/api/projects/x", _project=project)

        with patch.object(ri, "_tree_files", wraps=ri._tree_files) as real:
            ProjectHandler.do_GET(stub("GET"))
            self.assertEqual(real.call_count, 1)  # reused inside the GET
            ProjectHandler.do_POST(stub("POST"))
            self.assertEqual(real.call_count, 3)  # a POST re-reads every time
            ProjectHandler.do_GET(stub("GET"))
            self.assertEqual(real.call_count, 4)  # nothing kept between requests
        self.assertEqual(calls, [("GET", True), ("POST", False), ("GET", True)])

    def test_a_reused_runtime_verification_is_not_counted_as_a_pass(self):
        # Review 2026-11-28 P1-3: inside one read request the second
        # verification of the same pin reuses every root and costs no hashing;
        # it must not use up the request's pass bound.
        from stage1_retrieval import verification_clock as clock

        executable = str(Path(sys.executable).resolve())
        pin = dict(
            argv_prefix=[executable, "-I", "-B", str(self.root / "a.py")],
            code_identity=dict(
                argv_prefix=[executable, "-I", "-B", str(self.root / "a.py")],
                absent_paths=[],
                roots={str(self.root): False},
                files={},
            ),
        )
        pin["code_identity"]["files_sha256"] = ri.digest(ri.canonical({}))
        meter = clock.Meter()
        with clock.metering(meter), ri.request_scope():
            for _ in range(3):
                with self.assertRaises(LedgerError):  # files differ on purpose
                    ri.verify_identity(pin)
        self.assertEqual(meter.snapshot()["passes"], 1)
        with clock.metering(meter):
            with self.assertRaises(LedgerError):
                ri.verify_identity(pin)  # outside a read scope: a real pass
        self.assertEqual(meter.snapshot()["passes"], 2)

    def test_another_thread_does_not_see_this_threads_scope(self):
        seen = []
        with patch.object(ri, "_tree_files", wraps=ri._tree_files) as real:
            with ri.request_scope():
                ri.tree_files(self.root)
                worker = threading.Thread(
                    target=lambda: seen.append(
                        (getattr(ri._scope, "trees", None), ri.tree_files(self.root))
                    )
                )
                worker.start()
                worker.join()
            self.assertEqual(real.call_count, 2)
        self.assertIsNone(seen[0][0])

    def test_a_failed_read_in_any_chunk_fails_the_whole_result(self):
        for index in range(150):
            (self.root / f"f{index}.py").write_bytes(b"z")
        target = self.root / "f130.py"
        real_read = Path.read_bytes

        def read(path):
            if path == target:
                raise OSError("synthetic read failure")
            return real_read(path)

        with patch.object(Path, "read_bytes", read):
            with self.assertRaisesRegex(OSError, "synthetic read failure"):
                ri._tree_files(self.root)

    def test_probe_is_refused_inside_a_read_scope(self):
        with ri.request_scope():
            with self.assertRaisesRegex(LedgerError, "runtime-probe-inside-read-scope"):
                ri.verify_identity(
                    {"code_identity": _FAKE_IDENTITY, "argv_prefix": ["x", "-I", "-B"]},
                    probe=True,
                )


if __name__ == "__main__":
    unittest.main()
