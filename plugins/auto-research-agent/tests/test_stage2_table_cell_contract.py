"""Focused regressions for the Stage 2 research-table cell contract."""

import copy
from pathlib import Path
import sys
import unittest

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))
sys.path.insert(0, str(Path(__file__).resolve().parent))

from stage2_ideation.prompts import build_extraction_task  # noqa: E402
from stage2_ideation.topic_tables import (  # noqa: E402
    TopicTableError,
    materialize_research_tables,
    validate_research_tables,
)
from stage2_live.extraction import (  # noqa: E402
    _prompt,
    build_span_index,
    generation_schema,
)
from test_stage2_topic_tables import (  # noqa: E402
    RAW,
    SNAPSHOT,
    extracted_candidate,
    extracted_tables,
    packet,
)


class Stage2TableCellContractTests(unittest.TestCase):
    def materialized(self):
        source_packet = packet()
        tables = materialize_research_tables(
            extracted_tables(), [extracted_candidate()], source_packet, RAW, SNAPSHOT
        )
        source_packet["candidates"].append(extracted_candidate()["candidate"])
        return source_packet, tables

    def test_prompt_states_compact_cell_contract(self):
        source_packet = packet()
        span_index = build_span_index(RAW)
        task = build_extraction_task(RAW, source_packet, SNAPSHOT)
        prompt = _prompt(
            task,
            source_packet,
            span_index,
            generation_schema(span_index, source_packet),
        )

        for expected in (
            "text dimension, described or partial requires a nonempty string value",
            "quantity dimension, described or partial requires a finite numeric value",
            "booleans are not numbers",
            "feature dimension, present uses true or null, absent uses false or null",
            "partial retains source-bound evidence",
            "Unknown and not-applicable always use a null value",
            "Unknown means the source does not establish the answer; it must not be used to mean absent",
            "negative_basis is allowed only for absent",
            "non-metadata evidence and an exact ISO-8601 UTC checked_at",
            "Saved-source possession does not establish current external access",
            "Never invent a date or a new check",
            "unknown with checked_at null",
            "every component must support the stated status",
        ):
            self.assertIn(expected, prompt)

    def test_known_resource_needs_dated_evidence_but_unknown_does_not(self):
        source_packet, tables = self.materialized()
        for missing_or_invalid in (None, "2026-10-07", "2026-10-07T12:00:00+01:00"):
            with self.subTest(checked_at=missing_or_invalid):
                invalid = copy.deepcopy(tables)
                invalid["direction_resources"][0]["checked_at"] = missing_or_invalid
                with self.assertRaisesRegex(
                    TopicTableError, "known resource checked_at"
                ):
                    validate_research_tables(invalid, source_packet)

        unknown = copy.deepcopy(tables)
        unknown["direction_resources"][0].update(
            status="unknown", evidence_ids=[], checked_at=None
        )
        self.assertEqual(validate_research_tables(unknown, source_packet), unknown)

    def test_reports_all_observed_cell_errors_with_exact_identity(self):
        source_packet, tables = self.materialized()
        tables["cells"][0]["value"] = "long feature description"
        tables["cells"][2]["status"] = "present"

        with self.assertRaises(TopicTableError) as raised:
            validate_research_tables(tables, source_packet)

        message = str(raised.exception)
        self.assertIn(
            "cell[0] (dimension_id='feature-use', work_id='work-1', version_id='v1')",
            message,
        )
        self.assertIn("present feature value must be true or null", message)
        self.assertIn(
            "cell[2] (dimension_id='measurement', work_id='work-1', version_id='v1')",
            message,
        )
        self.assertIn("text and quantity cells cannot use present or absent", message)

    def test_validates_feature_text_quantity_unknown_and_absence(self):
        source_packet, tables = self.materialized()
        quantity = copy.deepcopy(tables["dimensions"][1])
        quantity.update(dimension_id="sample-size", value_kind="quantity")
        tables["dimensions"].append(quantity)
        described = copy.deepcopy(tables["cells"][2])
        described.update(dimension_id="sample-size", value=12.5)
        unknown = copy.deepcopy(tables["cells"][3])
        unknown.update(dimension_id="sample-size")
        tables["cells"].extend([described, unknown])

        self.assertEqual(validate_research_tables(tables, source_packet), tables)

        invalid = copy.deepcopy(tables)
        invalid["cells"][1]["negative_basis"] = None
        with self.assertRaisesRegex(
            TopicTableError,
            "cell\\[1\\].*absent requires negative_basis",
        ):
            validate_research_tables(invalid, source_packet)

        invalid = copy.deepcopy(tables)
        invalid["cells"][3]["negative_basis"] = "explicit-statement"
        with self.assertRaisesRegex(
            TopicTableError,
            "cell\\[3\\].*unknown cannot claim a negative basis",
        ):
            validate_research_tables(invalid, source_packet)


if __name__ == "__main__":
    unittest.main()
