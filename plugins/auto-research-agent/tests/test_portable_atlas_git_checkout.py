"""Actual Git checkout regression for all 53 observed Atlas CRLF mismatches."""

from pathlib import Path
import subprocess
import tempfile
import unittest


REPO_ROOT = Path(__file__).resolve().parents[3]
ASSETS = (
    "plugins/auto-research-agent/cli/research_workspace_native/web/atlas-host.css",
    "plugins/auto-research-agent/cli/research_workspace_native/web/atlas-host.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/harness-panel.css",
    "plugins/auto-research-agent/cli/research_workspace_native/web/harness-panel.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/native-atlas-chat.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/session-panel.css",
    "plugins/auto-research-agent/cli/research_workspace_native/web/session-panel.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/session-scope.css",
    "plugins/auto-research-agent/cli/research_workspace_native/web/session-scope.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/stage-panel.css",
    "plugins/auto-research-agent/cli/research_workspace_native/web/stage-panel.js",
    "plugins/auto-research-agent/cli/research_workspace_native/web/stage-query-panel.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas-associations.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas-model.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas-network.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas-spatial.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas-ui.js",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas.css",
    "plugins/auto-research-agent/references/research-workspace/atlas/atlas.html",
    "plugins/auto-research-agent/references/research-workspace/examples/planned-query-fixture-notice.js",
    "plugins/auto-research-agent/references/research-workspace/tests/localization.html",
    "plugins/auto-research-agent/references/research-workspace/workspace-closeout.css",
    "plugins/auto-research-agent/references/research-workspace/workspace-literature-selection.js",
    "plugins/auto-research-agent/references/research-workspace/workspace-records.js",
    "plugins/auto-research-agent/references/research-workspace/workspace-repairs.js",
    "plugins/auto-research-agent/references/research-workspace/workspace-selection.css",
    "plugins/auto-research-agent/references/research-workspace/workspace-source-rerun.css",
    "plugins/auto-research-agent/references/research-workspace/workspace-source-rerun.js",
    "plugins/auto-research-agent/references/research-workspace/workspace-stage2.css",
    "plugins/auto-research-agent/references/research-workspace/workspace-stage2.js",
    "plugins/auto-research-agent/references/stage1-source-capability-resolution.csv",
    "plugins/auto-research-agent/tests/browser/native-session/browser_driver.cjs",
    "plugins/auto-research-agent/tests/browser/workspace-records.js",
    "plugins/auto-research-agent/tests/research_workspace_native_browser/core_panel_path.js",
    "plugins/auto-research-agent/tests/test-atlas-feedback-pagination.cjs",
    "plugins/auto-research-agent/tests/test-native-atlas-chat.cjs",
    "plugins/auto-research-agent/tests/test-native-atlas-drawer.cjs",
    "plugins/auto-research-agent/tests/test-native-readable.cjs",
    "plugins/auto-research-agent/tests/test-native-status-labels.cjs",
    "plugins/auto-research-agent/tests/test-scope-stale.cjs",
    "plugins/auto-research-agent/tests/test-workspace-planned-query.cjs",
    "plugins/auto-research-agent/tests/test_harness_panel.cjs",
    "plugins/auto-research-agent/tests/test_literature_graph.js",
    "plugins/auto-research-agent/tests/test_literature_graph_browser.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_associations.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_browser.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_language.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_model.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_network.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_review.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_semantics.js",
    "plugins/auto-research-agent/tests/test_workspace_atlas_spatial.js",
    "plugins/auto-research-agent/tests/test_workspace_stage_panel.cjs",
)
VENDOR = Path(
    "plugins/auto-research-agent/references/research-workspace/atlas/vendor/"
    "3d-force-graph-1.80.1.min.js"
)


class PortableAtlasGitCheckoutTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="atlas-eol-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.git("init", "--quiet")
        self.git("config", "core.autocrlf", "true")
        self.git("config", "user.name", "Synthetic checkout fixture")
        self.git("config", "user.email", "fixture@invalid")
        (self.root / ".gitattributes").write_bytes(
            (REPO_ROOT / ".gitattributes").read_bytes()
        )
        self.expected = {}
        for name in ASSETS:
            relative = Path(name)
            raw = ("/* synthetic LF fixture: " + name + " */\n").encode()
            path = self.root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.expected[relative.as_posix()] = raw
        vendor = self.root / VENDOR
        vendor.parent.mkdir(parents=True, exist_ok=True)
        vendor.write_bytes(b"synthetic verbatim bundle\r\nsecond line\n")
        self.git("add", ".gitattributes", "plugins")
        self.git("commit", "--quiet", "-m", "Synthetic web checkout")
        # Force a real re-materialization, rather than checking bytes written above.
        for relative in self.expected:
            (self.root / relative).unlink()
        vendor.unlink()
        self.git("checkout-index", "--all", "--force")

    def git(self, *args):
        return subprocess.check_output(
            [
                "git",
                "-c",
                "core.longpaths=true",
                "-c",
                "maintenance.auto=false",
                "-c",
                "gc.auto=0",
                "-C",
                str(self.root),
                *args,
            ],
            stdin=subprocess.DEVNULL,
            stderr=subprocess.PIPE,
            timeout=15,
        )

    def test_autocrlf_checkout_preserves_all_fifty_three_identified_atlas_paths(self):
        self.assertEqual(self.git("config", "--get", "core.autocrlf").strip(), b"true")
        for relative, expected in self.expected.items():
            with self.subTest(path=relative):
                raw_git = self.git("show", "HEAD:" + relative)
                self.assertEqual(raw_git, expected)
                self.assertEqual((self.root / relative).read_bytes(), raw_git)
        self.assertEqual(self.git("status", "--porcelain"), b"")

    def test_scoped_rules_keep_the_upstream_vendor_bundle_verbatim(self):
        raw = self.git("show", "HEAD:" + VENDOR.as_posix())
        self.assertEqual(raw, b"synthetic verbatim bundle\r\nsecond line\n")
        self.assertEqual((self.root / VENDOR).read_bytes(), raw)
        attributes = self.git("check-attr", "text", "eol", "--", VENDOR.as_posix())
        self.assertIn(b": text: unset", attributes)
        self.assertIn(b": eol: unspecified", attributes)


if __name__ == "__main__":
    unittest.main()
