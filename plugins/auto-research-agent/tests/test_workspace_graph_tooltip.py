"""Offline geometry regression; does not claim browser visual verification."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from research_workspace.view import _literature  # noqa: E402


class GraphTooltipTests(unittest.TestCase):
    def test_tooltip_stays_in_frame_and_avoids_node_when_space_exists(self):
        node = shutil.which("node")
        if node is None:
            self.skipTest("Node.js is required for the offline JS geometry test")
        source = (
            Path(__file__).resolve().parents[1]
            / "references/research-workspace/literature-reference.js"
        ).read_text(encoding="utf-8")
        script = r"""
const vm = require('node:vm');
let input = '';
process.stdin.on('data', x => input += x);
process.stdin.on('end', () => {
  const sandbox = {window: {}};
  vm.runInNewContext(input, sandbox);
  const locate = sandbox.window.LiteratureReference.positionGraphTooltip;
  if (typeof locate !== 'function') throw new Error('missing shared tooltip geometry');
  const cases = [
    [960, 540, 450, 470, 250, 270, 270, 80],
    [320, 250, 270, 300, 215, 235, 260, 90],
    [320, 250, 5, 25, 5, 25, 260, 90],
    [320, 250, 140, 160, 215, 235, 260, 90],
    [320, 250, 140, 160, 15, 35, 260, 90],
    [640, 400, -80, -40, -70, -30, 260, 90],
    [640, 400, 700, 750, 420, 460, 260, 90],
    [320, 250, 140, 170, 110, 140, 304, 234],
  ];
  const results = cases.map(([width,height,left,right,top,bottom,tw,th]) => ({
    frame: {width,height}, anchor: {left,right,top,bottom}, tip: {width:tw,height:th},
    point: locate({width,height},{left,right,top,bottom},{width:tw,height:th}),
  }));
  process.stdout.write(JSON.stringify(results));
});
"""
        for label, content in [("reference", source), ("export", _literature(source))]:
            with self.subTest(projection=label):
                out = subprocess.run(
                    [node, "-e", script],
                    input=content,
                    text=True,
                    capture_output=True,
                    encoding="utf-8",
                    timeout=30,
                    check=True,
                )
                rows = json.loads(out.stdout)
                self.assertEqual(len(rows), 8)
                for i, row in enumerate(rows):
                    x, y = row["point"]["left"], row["point"]["top"]
                    f, a, t = row["frame"], row["anchor"], row["tip"]
                    self.assertGreaterEqual(x, 8)
                    self.assertGreaterEqual(y, 8)
                    self.assertLessEqual(x + t["width"], f["width"] - 8)
                    self.assertLessEqual(y + t["height"], f["height"] - 8)
                    if i < 5:
                        self.assertTrue(
                            x >= a["right"]
                            or x + t["width"] <= a["left"]
                            or y >= a["bottom"]
                            or y + t["height"] <= a["top"]
                        )
