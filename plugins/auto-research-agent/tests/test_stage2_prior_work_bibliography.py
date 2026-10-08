"""The opt-in packet retains the existing source-bound bibliography."""

import copy
import unittest

import test_stage2_prior_work as prior_work_fixtures
from stage2_check.bibliography import build_bibliography


class PriorWorkBibliographyTests(unittest.TestCase):
    def test_opt_in_packet_keeps_bibliography_and_supplemental_versions(self):
        fixture = prior_work_fixtures.Stage2PriorWorkTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        packet = copy.deepcopy(fixture.packet)
        result = build_bibliography(
            packet,
            {row["source_id"]: row for row in packet["sources"]},
            {row["evidence_id"]: row for row in packet["evidence"]},
        )
        self.assertTrue(result["available"])
        self.assertEqual(len(result["works"]), len(packet["literature"]))
        self.assertTrue(
            all(row["supplemental_versions"] == [] for row in result["works"])
        )


if __name__ == "__main__":
    unittest.main()
