"""Pinned Stage2 examples remain separate from project delivery and authority."""

from copy import deepcopy
import json
from pathlib import Path
import sys
import tempfile
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from research_workspace.atlas import atlas_files  # noqa: E402
from research_workspace_native.atlas_host import load_views  # noqa: E402
from research_workspace_native.project_ui_overlay import stage2_example_views  # noqa: E402
from stage1_deliverable.common import canonical, sha  # noqa: E402
from test_research_workspace_stage2_presentation import attachment  # noqa: E402
from test_workspace_atlas import payload  # noqa: E402


class Stage2ExampleViewTests(unittest.TestCase):
    def test_pinned_original_fixture_bytes_are_reused_without_project_adoption(self):
        value = payload()
        value["fixture"] = True
        value["stage2"] = attachment()
        value["stage2"]["fixture"] = True
        original = deepcopy(value)
        files = atlas_files(value)
        files["workspace-index.json"] = canonical(value["index"])
        with tempfile.TemporaryDirectory(prefix="stage2-example-") as directory:
            root = Path(directory).resolve()
            for name, raw in files.items():
                path = root / name
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_bytes(raw)
            manifest = canonical(
                {
                    "kind": "WorkspaceReadOnlyView",
                    "index_sha256": value["index_sha256"],
                    "files": {name: sha(raw) for name, raw in files.items()},
                }
            )
            (root / "view-manifest.json").write_bytes(manifest)
            config = canonical(
                {
                    "views": [
                        {
                            "ref": "saved-example",
                            "label": "Authored synthetic Stage2",
                            "fixture": True,
                            "manifest": str(root / "view-manifest.json"),
                            "sha256": sha(manifest),
                        }
                    ]
                }
            )
            (root / "views.json").write_bytes(config)
            source, views = load_views(root / "views.json", sha(config))
            before = deepcopy(source), deepcopy(views)
            copied, examples, routes = stage2_example_views(source, views)
            self.assertEqual((source, views), before)
            self.assertEqual(value, original)
            self.assertEqual(len(examples), 1)
            row = examples[0]
            self.assertEqual(row["project_id"], value["index"]["project_id"])
            self.assertEqual(row["index_sha256"], value["index_sha256"])
            self.assertEqual(row["manifest_sha256"], sha(manifest))
            self.assertEqual(row["payload_sha256"], sha(files["atlas-data.js"]))
            self.assertEqual(routes, frozenset({row["url"]}))
            self.assertEqual(copied[row["url"]], files["atlas.html"])
            self.assertNotIn(b"project-bootstrap", copied[row["url"]])
            self.assertNotIn(b"host-bootstrap", copied[row["url"]])
            for name, raw in files.items():
                self.assertEqual(
                    copied["/project-stage2-examples/saved-example/" + name], raw
                )
            # Registered real history is not relabelled as an interface fixture.
            views[0]["fixture"] = False
            self.assertEqual(stage2_example_views(source, views), ({}, [], frozenset()))
            views[0]["fixture"] = True
            for change in (
                {"fixture": False},
                {"stage2": {"fixture": False}},
                {"index_sha256": "f" * 64},
                {"stage2_comparison": None},
            ):
                altered = {
                    **json.loads(
                        files["atlas-data.js"][len(b"window.WORKSPACE_VIEW = ") : -2]
                    ),
                    **change,
                }
                source["/views/saved-example/atlas-data.js"] = (
                    b"window.WORKSPACE_VIEW = " + json.dumps(altered).encode() + b";\n"
                )
                with self.assertRaisesRegex(ValueError, "data binding differs"):
                    stage2_example_views(source, views)
                replacement = json.loads(manifest)
                replacement["files"]["atlas-data.js"] = sha(
                    source["/views/saved-example/atlas-data.js"]
                )
                replacement_raw = canonical(replacement)
                source["/views/saved-example/view-manifest.json"] = replacement_raw
                views[0]["manifest_sha256"] = sha(replacement_raw)
                self.assertEqual(
                    stage2_example_views(source, views), ({}, [], frozenset())
                )


if __name__ == "__main__":
    unittest.main()
