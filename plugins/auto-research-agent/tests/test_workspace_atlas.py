"""Bound atlas projections use existing synthetic cases, never native execution."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import patch


PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.atlas import atlas_files  # noqa: E402
from research_workspace.projection import validate_index  # noqa: E402
from research_workspace.stage2_comparison import build_comparison_view  # noqa: E402
from research_workspace.view import REFERENCE_HASHES, write_workspace  # noqa: E402
from stage1_deliverable.common import canonical, sha  # noqa: E402
from test_research_workspace_stage2_presentation import attachment  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402


def payload():
    index = fixture_index()
    return {"index": index, "index_sha256": sha(canonical(index)), "note_paths": []}


def emitted_data(files):
    prefix = "window.WORKSPACE_VIEW = "
    return json.loads(files["atlas-data.js"].decode()[len(prefix) : -2])


class WorkspaceAtlasTests(unittest.TestCase):
    def test_payload_and_identity_remain_exact_and_every_asset_is_bound(self):
        original = payload()
        before = deepcopy(original)
        files = atlas_files(original)
        self.assertEqual(original, before)
        self.assertEqual(emitted_data(files), original)
        binding = json.loads(files["atlas-binding.json"])
        self.assertEqual(binding["index_sha256"], sha(canonical(original["index"])))
        self.assertEqual(binding["project_id"], original["index"]["project_id"])
        self.assertIsNone(binding["stage2_attachment_sha256"])
        self.assertFalse(binding["execution_authority"])
        self.assertEqual(binding["research_execution"], "not-performed")
        self.assertEqual(
            binding["files"],
            {
                name: sha(raw)
                for name, raw in files.items()
                if name != "atlas-binding.json"
            },
        )

    def test_unknowns_original_text_and_script_escape_are_preserved(self):
        value = payload()
        value["index"]["topic"] = "</script><img onerror=alert(1)>"
        value["index"]["papers"][0]["findings"]["method"] = None
        value["index_sha256"] = sha(canonical(value["index"]))
        validate_index(value["index"])
        files = atlas_files(value)
        self.assertNotIn(b"</script>", files["atlas-data.js"])
        self.assertIn(b"\\u003c/script>", files["atlas-data.js"])
        projected = emitted_data(files)
        self.assertEqual(projected, value)
        self.assertIsNone(projected["index"]["papers"][0]["findings"]["method"])
        self.assertEqual(
            projected["index"]["native_session"]["status"], "not-connected"
        )
        self.assertEqual(projected["index"]["status"], "partial-review-only")

    def test_stage2_reuses_bound_view_and_retains_audit_and_all_comments(self):
        value = payload()
        value["stage2"] = attachment()
        packet = value["stage2"]["selection"]["evaluation_packet"]
        packet["literature"] = [
            {
                "work_id": "same-work",
                "version_id": "v2",
                "source_ids": ["s2"],
                "title": "Literal <img> title",
                "findings": {"method": None},
            },
        ]
        packet["evidence"] = [
            {
                "evidence_id": "foreign",
                "work_id": "same-work",
                "version_id": "v1",
                "source_id": "s1",
                "quote": "Unrelated version",
            },
        ]
        before = deepcopy(value)
        files = atlas_files(value)
        data = emitted_data(files)
        self.assertEqual(
            data["stage2_comparison"], build_comparison_view(value["stage2"])
        )
        self.assertEqual(value, before)
        self.assertEqual(data["stage2"], value["stage2"])
        self.assertEqual(len(data["stage2"]["evaluation"]["rows"]), 9)
        self.assertEqual(
            data["stage2"]["evaluation"]["evaluation_status"], "audit-required"
        )
        self.assertIsNone(data["stage2"]["evaluation"]["dimensions"]["P4"]["score"])
        self.assertFalse(data["stage2"]["bridge_receipt"]["stage3_authorized"])
        row = data["stage2_comparison"]["literature"][0]
        self.assertEqual(row["evidence_ids"], [])
        self.assertIsNone(row["cells"]["method"]["text"])
        self.assertEqual(
            json.loads(files["atlas-binding.json"])["stage2_attachment_sha256"],
            sha(canonical(value["stage2"])),
        )

    def test_view_atlas_is_opt_in_and_retains_original_assets_and_index(self):
        index = fixture_index()
        before = deepcopy(index)
        reference = PLUGIN / "references/research-workspace"
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory).resolve()
            with patch("research_workspace.view.private_output", side_effect=Path):
                default = write_workspace(index, reference, root / "default")
                opted = write_workspace(index, reference, root / "atlas", atlas=True)
            self.assertNotIn("atlas.html", default["files"])
            self.assertIn("atlas.html", opted["files"])
            self.assertTrue(opted["rebuild"]["atlas"])
            self.assertEqual(default["reference_assets"], REFERENCE_HASHES)
            self.assertEqual(opted["reference_assets"], REFERENCE_HASHES)
            self.assertEqual(
                (root / "default/workspace-index.json").read_bytes(),
                (root / "atlas/workspace-index.json").read_bytes(),
            )
            for name, digest in opted["files"].items():
                self.assertEqual(sha((root / "atlas" / name).read_bytes()), digest)
            self.assertEqual(index, before)

    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_model_navigation_and_360_record_fixture(self):
        result = subprocess.run(
            [shutil.which("node"), str(PLUGIN / "tests/test_workspace_atlas_model.js")],
            cwd=PLUGIN,
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("synthetic records only", result.stdout)


if __name__ == "__main__":
    unittest.main()
