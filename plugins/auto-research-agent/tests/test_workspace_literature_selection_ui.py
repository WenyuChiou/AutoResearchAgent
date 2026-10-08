"""Node-only semantic checks for the formal literature UI selection helper."""

import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

import test_research_workspace_view as view_fixture
from research_workspace.view import write_workspace
from stage1_deliverable.common import sha


HELPER = (
    Path(__file__).parents[1]
    / "references/research-workspace/workspace-literature-selection.js"
)

HARNESS = r"""
const selection = require(process.argv[1]);
const records = [
  {original:{work_id:'work-a', version_id:'v1', claims:[{relation:'Unknown'}]}},
  {original:{work_id:'work-a', version_id:'v2', claims:[{relation:'supports'}]}},
  {original:{work_id:'work-b', version_id:'v1', claims:[]}},
];
const payload = {counts:{screened:3,included:1,pending:1,excluded:1}, rows:[
  {work_id:'work-a',version_id:'v1',citation_key:'a-v1',status:'included',reasons:['readable-full-text-identity-confirmed']},
  {work_id:'work-a',version_id:'v2',citation_key:'a-v2',status:'pending',reasons:['identity-unverified']},
  {work_id:'work-b',version_id:'v1',citation_key:'b-v1',status:'excluded',reasons:['abstract-only']},
]};
const formal = selection.create({schema_version:'3.0.0'}, payload);
const empty = selection.create({schema_version:'3.0.0'}, {counts:{screened:1,included:0,pending:0,excluded:1},rows:[payload.rows[2]]});
const legacy = selection.create({schema_version:'2.0.0'}, undefined);
const summarize = rows => rows.map(row => [row.original.work_id, row.original.version_id]);
let duplicateRejected = false;
try { selection.create({schema_version:'3.0.0'}, {rows:[payload.rows[0],payload.rows[0]]}); }
catch (error) { duplicateRejected = /duplicate/.test(error.message); }
console.log(JSON.stringify({
  defaultScope:formal.defaultScope,
  included:summarize(formal.filter(records, 'included')),
  pending:summarize(formal.filter(records, 'pending')),
  all:summarize(formal.filter(records, 'all')),
  unknownRelation:formal.filter(records, 'included')[0].original.claims[0].relation,
  pendingReason:formal.row(records[1]).reasons[0],
  counts:formal.counts,
  emptyIncluded:summarize(empty.filter(records, 'included')),
  emptyPending:summarize(empty.filter(records, 'pending')),
  emptyAll:summarize(empty.filter(records, 'all')),
  citations:['included','screening','original'].map(scope => formal.citationTarget(scope)),
  legacyDefault:legacy.defaultScope,
  legacyAll:summarize(legacy.filter(records, legacy.defaultScope)),
  duplicateRejected,
}));
"""


class WorkspaceLiteratureSelectionUITests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        result = subprocess.run(
            ["node", "-e", HARNESS, str(HELPER)],
            capture_output=True,
            text=True,
            check=True,
            timeout=30,
        )
        cls.result = json.loads(result.stdout)

    def test_schema_three_defaults_to_included_without_filtering_unknown_claims(self):
        self.assertEqual(self.result["defaultScope"], "included")
        self.assertEqual(self.result["included"], [["work-a", "v1"]])
        self.assertEqual(self.result["unknownRelation"], "Unknown")

    def test_exact_work_version_identity_isolation(self):
        self.assertEqual(self.result["pending"], [["work-a", "v2"]])
        self.assertEqual(self.result["pendingReason"], "identity-unverified")
        self.assertTrue(self.result["duplicateRejected"])

    def test_all_screened_preserves_every_row_and_counts(self):
        self.assertEqual(
            self.result["all"],
            [["work-a", "v1"], ["work-a", "v2"], ["work-b", "v1"]],
        )

    def test_empty_included_and_pending_keep_full_screening_available(self):
        self.assertEqual(self.result["emptyIncluded"], [])
        self.assertEqual(self.result["emptyPending"], [])
        self.assertEqual(self.result["emptyAll"], self.result["all"])
        self.assertEqual(
            self.result["counts"],
            {"screened": 3, "included": 1, "pending": 1, "excluded": 1},
        )

    def test_legacy_payload_defaults_to_all_without_formal_acceptance(self):
        self.assertEqual(self.result["legacyDefault"], "all")
        self.assertEqual(self.result["legacyAll"], self.result["all"])

    def test_citation_targets_keep_selection_and_original_exports_distinct(self):
        self.assertEqual(
            [row["href"] for row in self.result["citations"]],
            [
                "./literature/included.bib",
                "./literature/screening.bib",
                "./references.bib",
            ],
        )


class WorkspaceLiteratureSelectionLoaderTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.temporary = tempfile.TemporaryDirectory(prefix="selection-ui-")
        cls.output = Path(cls.temporary.name).resolve() / "view"
        reference = Path(__file__).parents[1] / "references/research-workspace"
        cls.manifest = write_workspace(
            view_fixture.fixture_index(), reference, cls.output
        )

    @classmethod
    def tearDownClass(cls):
        cls.temporary.cleanup()

    def test_view_loads_selection_overlay_before_records_adapter(self):
        html = (self.output / "index.html").read_text(encoding="utf-8")
        self.assertIn('href="./workspace-selection.css"', html)
        helper = html.index('src="./workspace-literature-selection.js"')
        records = html.index('src="./workspace-records.js"')
        self.assertLess(helper, records)

    def test_ui_sources_are_copied_and_hash_bound(self):
        source = Path(__file__).parents[1] / "references/research-workspace"
        for name in (
            "workspace-records.js",
            "workspace-literature-selection.js",
            "workspace-selection.css",
        ):
            with self.subTest(name=name):
                raw = (self.output / name).read_bytes()
                self.assertEqual(raw, (source / name).read_bytes())
                self.assertEqual(self.manifest["files"][name], sha(raw))
                self.assertEqual(self.manifest["ui_sources"][name], sha(raw))

    def test_legacy_index_payload_retains_pending_selection_without_promotion(self):
        text = (self.output / "workspace-data.js").read_text(encoding="utf-8")
        payload = json.loads(
            text.removeprefix("window.WORKSPACE_VIEW = ").strip().removesuffix(";")
        )
        selection = payload["literature_selection"]
        self.assertEqual(selection["counts"]["included"], 0)
        self.assertEqual(
            selection["counts"]["pending"], len(payload["index"]["papers"])
        )
        self.assertFalse(selection["official_stage2_import_eligible"])


if __name__ == "__main__":
    unittest.main()
