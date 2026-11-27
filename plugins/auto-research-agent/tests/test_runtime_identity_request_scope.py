"""Runtime roots are hashed once per read request and never kept across requests."""

# ruff: noqa: E402 -- exercise repository CLI.
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path[:0] = [str(Path(__file__).resolve().parents[1] / "cli")]
from stage1_retrieval import runtime_identity as ri


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


if __name__ == "__main__":
    unittest.main()
