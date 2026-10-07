"""Supplemental source versions remain distinct without counting extra papers."""

from copy import deepcopy
import unittest

from test_stage2_topic_tables_html import prepared_attachment
from research_workspace.stage2_comparison import build_comparison_view
from research_workspace.stage2_comparison_html import render_comparison_workbench


def supplemented_attachment():
    value = prepared_attachment()
    packet = value["selection"]["evaluation_packet"]
    packet["schema_version"] = "2.3.0"
    row = deepcopy(packet["literature"][0])
    row.update(
        version_id="recovered-abstract",
        source_ids=["src-recovered"],
        evidence_level="abstract",
        origin="stage2",
        findings={
            "data": "Recovered data description",
            "method": "Bounded method description",
        },
    )
    packet["supplemental_literature"] = [row]
    packet["evidence"].append(
        {
            "evidence_id": "ev-recovered",
            "source_id": "src-recovered",
            "work_id": row["work_id"],
            "version_id": row["version_id"],
            "locator": "characters 0:16",
            "quote": "Recovered quote.",
            "evidence_level": "abstract",
        }
    )
    tables = packet["research_tables"]
    tables["work_refs"].append(
        {"work_id": row["work_id"], "version_id": row["version_id"]}
    )
    for original in deepcopy(tables["cells"][:2]):
        original.update(version_id=row["version_id"], evidence_ids=["ev-recovered"])
        tables["cells"].append(original)
    return value


class Stage2ComparisonVersionTests(unittest.TestCase):
    def test_primary_roster_stays_three_papers_and_supplement_has_own_field_path(self):
        value = supplemented_attachment()
        original = deepcopy(value)
        view = build_comparison_view(value)
        self.assertEqual(value, original)
        self.assertEqual(len(view["literature"]), 3)
        self.assertEqual(len(view["supplemental_literature"]), 1)
        recovered = view["supplemental_literature"][0]
        self.assertEqual(recovered["work_id"], view["literature"][0]["work_id"])
        self.assertNotEqual(
            recovered["version_id"], view["literature"][0]["version_id"]
        )
        self.assertEqual(recovered["evidence_ids"], ["ev-recovered"])
        self.assertEqual(
            recovered["cells"]["data"]["field"],
            "selection.evaluation_packet.supplemental_literature[0].findings.data",
        )
        self.assertEqual(view["literature"][0]["source_versions"], [recovered])

    def test_matrix_resolves_supplement_exact_source_and_overview_keeps_paper_count(
        self,
    ):
        html = render_comparison_workbench(
            build_comparison_view(supplemented_attachment())
        )
        self.assertEqual(html.count("<tr data-s2w-literature-row "), 3)
        self.assertIn("Additional source version of the same study", html)
        self.assertIn("Additional source versions (1)", html)
        self.assertIn("Recovered quote.", html)
        self.assertIn("Recovered data description", html)
        self.assertNotIn("Recorded work/version</strong>", html)

    def test_supplemental_text_is_escaped(self):
        value = supplemented_attachment()
        value["selection"]["evaluation_packet"]["supplemental_literature"][0][
            "findings"
        ]["method"] = "<script>attack()</script>"
        html = render_comparison_workbench(build_comparison_view(value))
        self.assertNotIn("<script>attack()</script>", html)
        self.assertIn("&lt;script&gt;attack()&lt;/script&gt;", html)

    def test_legacy_projection_does_not_admit_supplemental_fields(self):
        value = supplemented_attachment()
        packet = value["selection"]["evaluation_packet"]
        packet["schema_version"] = "2.2.0"
        view = build_comparison_view(value)
        self.assertNotIn("supplemental_literature", view)
        self.assertTrue(all("source_versions" not in row for row in view["literature"]))


if __name__ == "__main__":
    unittest.main()
