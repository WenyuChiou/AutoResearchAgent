"""Source admission guards only; ordinary CI never launches a browser."""

from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent))
from research_workspace_native_browser import core_panel_fixture as browser


class CoreBrowserSourceTests(unittest.TestCase):
    def setUp(self):
        folder = tempfile.TemporaryDirectory()
        self.addCleanup(folder.cleanup)
        self.root = Path(folder.name).resolve()
        self.repo = self.root / "candidate"
        self.repo.mkdir()
        browser.git(self.repo, "init", "-q")
        for name in browser.REQUIRED:
            path = self.repo / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b"# synthetic guard fixture\n")
        browser.git(self.repo, "add", "--", *(p.as_posix() for p in browser.REQUIRED))
        browser.git(
            self.repo,
            "-c",
            "user.name=Fixture",
            "-c",
            "user.email=fixture@example.invalid",
            "-c",
            "core.hooksPath=disabled-fixture-hooks",
            "commit",
            "-qm",
            "Synthetic source guard",
        )
        self.head = browser.git(self.repo, "rev-parse", "HEAD").decode().strip()

    def test_complete_candidate_and_verified_origins(self):
        root, source = browser.candidate(str(self.repo), self.head)
        path = self.repo / browser.REQUIRED[0]
        loaded = browser.origins(
            root,
            {
                "research_workspace_native.wiki_http": SimpleNamespace(
                    __file__=str(path)
                )
            },
        )
        self.assertEqual(
            loaded["research_workspace_native.wiki_http"],
            source[browser.REQUIRED[0].as_posix()],
        )

    def test_wrong_missing_or_partial_root_rejected(self):
        for root in (self.root / "missing", self.root, self.repo / browser.PLUGIN):
            with (
                self.subTest(root=root),
                self.assertRaises(
                    (
                        ValueError,
                        FileNotFoundError,
                        browser.subprocess.CalledProcessError,
                    )
                ),
            ):
                browser.candidate(str(root), self.head)
        (self.repo / browser.REQUIRED[0]).unlink()
        with self.assertRaises(ValueError):
            browser.candidate(str(self.repo), self.head)

    def test_stale_head_and_dirty_bytes_rejected(self):
        with self.assertRaises(ValueError):
            browser.candidate(str(self.repo), "0" * 40)
        (self.repo / browser.REQUIRED[0]).write_bytes(b"changed\n")
        with self.assertRaises(ValueError):
            browser.candidate(str(self.repo), self.head)

    def test_mixed_origin_and_index_byte_mismatch_rejected(self):
        outside = self.root / "other.py"
        outside.write_bytes(b"# not candidate\n")
        with self.assertRaises(ValueError):
            browser.origins(
                self.repo,
                {
                    "research_workspace_native.http": SimpleNamespace(
                        __file__=str(outside)
                    )
                },
            )
        inside = self.repo / browser.REQUIRED[0]
        inside.write_bytes(b"# wrong bytes\n")
        with self.assertRaises(ValueError):
            browser.file_receipt(self.repo, inside)

    def test_staged_fingerprint_and_bytecode_cache(self):
        path = self.repo / browser.REQUIRED[0]
        path.write_bytes(b"# explicit staged change\n")
        browser.git(self.repo, "add", "--", browser.REQUIRED[0].as_posix())
        digest = browser.hashlib.sha256(
            browser.git(self.repo, "diff", "--cached", "--binary", "--full-index")
        ).hexdigest()
        browser.candidate(str(self.repo), self.head, digest)
        with self.assertRaises(ValueError):
            browser.candidate(str(self.repo), self.head, "0" * 64)
        path.with_suffix(".pyc").write_bytes(b"stale cache")
        with self.assertRaises(ValueError):
            browser.candidate(str(self.repo), self.head, digest)

    def test_output_inside_git_or_reused_is_rejected(self):
        with self.assertRaises(ValueError):
            browser.output_root(str(self.repo / "output"), self.repo)
        output = browser.output_root(str(self.root / "output"), self.repo)
        self.assertTrue(output.is_dir())
        with self.assertRaises(ValueError):
            browser.output_root(str(output), self.repo)

    def test_reference_assets_use_retained_blobs_not_current_presentation(self):
        paths = [p for p in browser.REQUIRED if p.parent.name == "research-workspace"]
        expected = {p.name: (self.repo / p).read_bytes() for p in paths}
        pins = {
            name: browser.hashlib.sha256(raw).hexdigest()
            for name, raw in expected.items()
        }
        for path in paths:
            (self.repo / path).write_bytes(b"# changed current presentation\n")
        browser.git(self.repo, "add", "--", *(p.as_posix() for p in paths))
        staged = browser.hashlib.sha256(
            browser.git(self.repo, "diff", "--cached", "--binary", "--full-index")
        ).hexdigest()
        browser.candidate(str(self.repo), self.head, staged)
        assets, receipts = browser.reference_assets(self.repo, self.head, pins)
        self.assertEqual(assets, expected)
        for path in paths:
            self.assertEqual(
                receipts[path.name],
                dict(commit=self.head, path=path.as_posix(), sha256=pins[path.name]),
            )
            self.assertNotEqual(assets[path.name], (self.repo / path).read_bytes())

    def test_missing_or_mismatched_reference_rejects_without_fetch_or_fallback(self):
        path = browser.PLUGIN / "references/research-workspace/prototype.html"
        pin = browser.hashlib.sha256((self.repo / path).read_bytes()).hexdigest()
        with patch.object(
            browser.subprocess, "check_output", wraps=browser.subprocess.check_output
        ) as calls:
            for commit, pins, error in (
                ("0" * 40, {path.name: pin}, browser.subprocess.CalledProcessError),
                (self.head, {"absent.css": pin}, browser.subprocess.CalledProcessError),
                (self.head, {path.name: "0" * 64}, ValueError),
            ):
                with self.subTest(commit=commit, pins=pins), self.assertRaises(error):
                    browser.reference_assets(self.repo, commit, pins)
            for call in calls.call_args_list:
                self.assertEqual(call.kwargs["env"]["GIT_NO_LAZY_FETCH"], "1")
                self.assertEqual(call.kwargs["env"]["GIT_NO_REPLACE_OBJECTS"], "1")

    def test_real_testcase_cleanup_fault_is_not_pass(self):
        fixture = unittest.TestCase()
        diagnostics = browser.record_cleanups(fixture)

        def fault():
            raise OSError("synthetic cleanup failure")

        fixture.addCleanup(fault)
        errors = browser.cleanup(fixture, None, None, None, diagnostics)
        self.assertEqual(
            errors,
            [
                "fixture doCleanups reported failure",
                "fixture callback: OSError: synthetic cleanup failure",
            ],
        )

    def test_interruption_reaps_owned_child_and_continues_cleanup(self):
        process = Mock(pid=123456, poll=Mock(return_value=None))
        process.communicate.side_effect = [
            InterruptedError("synthetic interruption"),
            ("", None),
        ]
        fixture, server, worker = Mock(), Mock(), Mock()
        worker.is_alive.side_effect = [True, False]
        try:
            process.communicate(timeout=120)
        except InterruptedError:
            with patch.object(browser.subprocess, "run") as terminate:
                with patch.object(browser.os, "killpg", create=True) as kill_group:
                    errors = browser.cleanup(fixture, process, server, worker)
        self.assertEqual(errors, [])
        process.kill.assert_called_once_with()
        self.assertEqual(process.communicate.call_count, 2)
        if browser.os.name == "nt":
            self.assertEqual(
                terminate.call_args.args[0], ["taskkill", "/PID", "123456", "/T", "/F"]
            )
        else:
            kill_group.assert_called_once_with(123456, browser.signal.SIGKILL)
        server.shutdown.assert_called_once_with()
        server.server_close.assert_called_once_with()
        worker.join.assert_called_once_with(2)
        fixture.doCleanups.assert_called_once_with()


if __name__ == "__main__":
    unittest.main()
