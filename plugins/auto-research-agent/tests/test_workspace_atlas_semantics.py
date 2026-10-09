"""Render real repository daily-v3 fixtures in the atlas, without native calls."""

import json
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest


PLUGIN = Path(__file__).resolve().parents[1]
UI = PLUGIN / "references/research-workspace/atlas/atlas-ui.js"
JS = Path(__file__).with_suffix(".js")
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from research_workspace.stage2_comparison import build_comparison_view  # noqa: E402
from research_workspace.stage2_import import (  # noqa: E402
    import_evaluated_delivery,
    prepare_stage2_bridge,
)
from stage1_deliverable.common import canonical, sha  # noqa: E402
from test_research_workspace_view import fixture_index  # noqa: E402
import test_stage2_daily_v3 as daily  # noqa: E402


class AtlasSemanticsTests(unittest.TestCase):
    @unittest.skipUnless(shutil.which("node"), "Node.js is unavailable")
    def test_daily_v3_pending_audit_and_r2_failure_keep_units_and_original_records(
        self,
    ):
        cases = {}
        for label, options in (
            ("audit-required", {"disagree": True}),
            ("r2-failed", {"fail_label": "r2-judge"}),
        ):
            fixture = daily.DailyV3Tests()
            fixture.setUp()
            try:
                bundle = fixture.run_judges(**options)
                manifest = fixture.delivery(bundle)
                index = fixture_index()
                bridge = prepare_stage2_bridge(
                    index,
                    fixture.root / "delivery",
                    expected_manifest_sha256=manifest["manifest_sha256"],
                )
                attachment, _ = import_evaluated_delivery(
                    index,
                    fixture.root / "delivery",
                    bridge,
                    expected_bridge_sha256=sha(canonical(bridge)),
                )
                cases[label] = {
                    "index": index,
                    "index_sha256": sha(canonical(index)),
                    "stage2": attachment,
                    "stage2_comparison": build_comparison_view(attachment),
                }
                self.assertFalse(attachment["bridge_receipt"]["formal_ready"])
                self.assertFalse(attachment["bridge_receipt"]["stage3_authorized"])
                self.assertEqual(len(attachment["evaluation"]["rows"]), 9)
                if label == "r2-failed":
                    self.assertEqual(
                        attachment["evaluation"]["evaluation_status"], "failed"
                    )
                    for row in attachment["evaluation"]["rows"]:
                        self.assertIsNotNone(row["judges"]["R1"])
                        self.assertIsNone(row["judges"]["R2"])
                else:
                    self.assertEqual(
                        attachment["evaluation"]["evaluation_status"], label
                    )
            finally:
                fixture.doCleanups()
        with tempfile.TemporaryDirectory() as directory:
            case_file = Path(directory) / "daily-v3-ui.json"
            case_file.write_text(
                json.dumps(cases, ensure_ascii=False), encoding="utf-8"
            )
            result = subprocess.run(
                [shutil.which("node"), str(JS), str(UI), str(PLUGIN), str(case_file)],
                capture_output=True,
                text=True,
                timeout=30,
            )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn(
            "assertions passed; repository daily-v3 fixtures, no native calls",
            result.stdout,
        )
        print(result.stdout.strip())


if __name__ == "__main__":
    unittest.main()
