"""Regression tests for replacing exploratory unresolved content."""

import copy
from pathlib import Path
import sys
import unittest


TESTS = Path(__file__).resolve().parent
sys.path[:0] = [str(TESTS.parents[0] / "cli"), str(TESTS)]

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_ideation import build_extraction_task  # noqa: E402
from stage2_ideation.integration import build_next_packet  # noqa: E402
import test_stage2_exploratory_contract as exploratory_fixture_module  # noqa: E402


RAW = "The corrected exploratory proposal records current unresolved prerequisites."
SNAPSHOT = "a" * 64


class Stage2ExploratoryRevisionTests(unittest.TestCase):
    def setUp(self):
        fixture = exploratory_fixture_module.ExploratoryContractTests(
            methodName="runTest"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.packet = copy.deepcopy(fixture.packet)
        self.sources = fixture.fixture.output

    def packet_for_version(self, version):
        packet = copy.deepcopy(self.packet)
        packet["schema_version"] = version
        if version in {"2.2.0", "2.3.0"}:
            packet["research_tables"] = None
        if version == "2.3.0":
            packet["supplemental_literature"] = []
        return packet

    def extraction(self, packet, unresolved):
        task = build_extraction_task(RAW, packet, SNAPSHOT)
        value = {
            "kind": "Stage2IdeationExtraction",
            "schema_version": task["schema_version"],
            "snapshot_sha256": SNAPSHOT,
            "packet_sha256": task["packet_sha256"],
            "raw_proposal_sha256": task["raw_proposal_sha256"],
            "input_hash": task["input_hash"],
            "receipt": {
                "policy_boundary": "declared-task-policy",
                "tools_policy": "none",
                "tool_calls": [],
                "isolation_verified": False,
            },
            "bibliography": [],
            "comparison_rows": [],
            "candidates": [],
            "unresolved": unresolved,
        }
        if task["schema_version"] == "1.1.0":
            value["research_tables"] = None
        return value

    def convert(
        self, packet, unresolved, *, update_mode="replace-comparison-unresolved"
    ):
        return build_next_packet(
            packet,
            self.sources,
            RAW,
            self.extraction(packet, unresolved),
            SNAPSHOT,
            update_mode=update_mode,
        )

    def test_replace_preserves_exact_limits_and_replaces_transient_issues_all_versions(
        self,
    ):
        for version in ("2.1.0", "2.2.0", "2.3.0"):
            with self.subTest(version=version):
                packet = self.packet_for_version(version)
                acceptance_before = copy.deepcopy(packet["upstream"]["acceptance"])
                limitations = acceptance_before["limitations"]
                packet["unresolved"] = ["Superseded transient issue.", *limitations]
                result = self.convert(
                    packet,
                    [limitations[0], "New current issue.", limitations[0]],
                )
                current = result["packet"]
                self.assertEqual(
                    current["unresolved"], [limitations[0], "New current issue."]
                )
                self.assertNotIn("Superseded transient issue.", current["unresolved"])
                self.assertEqual(current["unresolved"].count(limitations[0]), 1)
                self.assertEqual(current["upstream"]["acceptance"], acceptance_before)

    def test_restoring_omitted_acceptance_limit_is_not_substantive_change(self):
        packet = self.packet_for_version("2.3.0")
        limitation = packet["upstream"]["acceptance"]["limitations"][0]
        packet["unresolved"] = ["Current transient issue.", limitation]
        with self.assertRaisesRegex(Stage2Error, "no-substantive-change"):
            self.convert(packet, ["Current transient issue."])

    def test_all_accepted_limits_are_retained_without_promoting_intake(self):
        packet = self.packet_for_version("2.3.0")
        upstream = packet["upstream"]
        limitations = [
            "Partial source coverage remains exploratory.",
            "Unverified central claims remain unknown.",
            "This intake is not authorization for experiments.",
        ]
        upstream["acceptance"]["limitations"] = limitations
        upstream["acceptance_sha256"] = canonical_hash(upstream["acceptance"])
        upstream["binding_sha256"] = canonical_hash(
            {key: value for key, value in upstream.items() if key != "binding_sha256"}
        )
        packet["unresolved"] = [*limitations, "Superseded transient issue."]
        current = self.convert(packet, ["New current issue."])["packet"]
        self.assertEqual(current["unresolved"], ["New current issue.", *limitations])
        self.assertEqual(current["upstream"], upstream)
        self.assertEqual(current["sources"], packet["sources"])
        self.assertEqual(current["evidence"], packet["evidence"])

    def test_tampered_acceptance_is_rejected_before_replacement(self):
        packet = self.packet_for_version("2.2.0")
        packet["upstream"]["acceptance"]["limitations"] = ["Tampered limitation"]
        packet["upstream"]["acceptance_sha256"] = canonical_hash(
            packet["upstream"]["acceptance"]
        )
        packet["upstream"]["binding_sha256"] = canonical_hash(
            {
                key: value
                for key, value in packet["upstream"].items()
                if key != "binding_sha256"
            }
        )
        with self.assertRaisesRegex(Stage2Error, "limitations-not-preserved"):
            self.convert(packet, ["A current issue."])

    def test_append_and_nonexploratory_replace_remain_unchanged(self):
        exploratory = self.packet_for_version("2.1.0")
        original = copy.deepcopy(exploratory["unresolved"])
        appended = self.convert(
            exploratory, ["New appended issue."], update_mode="append"
        )["packet"]
        self.assertEqual(appended["unresolved"], [*original, "New appended issue."])

        nonexploratory = copy.deepcopy(exploratory)
        nonexploratory["schema_version"] = "2.0.0"
        upstream = nonexploratory["upstream"]
        for field in (
            "acceptance",
            "acceptance_sha256",
            "acceptance_file_sha256",
            "intake_mode",
        ):
            upstream.pop(field)
        upstream["schema_version"] = "1.0.0"
        upstream["eligible_for_stage2"] = True
        upstream["stage1_handoff_sha256"] = "b" * 64
        upstream["binding_sha256"] = canonical_hash(
            {key: value for key, value in upstream.items() if key != "binding_sha256"}
        )
        replacement = self.convert(nonexploratory, ["Only current issue."])["packet"]
        self.assertEqual(replacement["unresolved"], ["Only current issue."])
        repeated = ["Current issue.", "Current issue."]
        self.assertEqual(
            self.convert(nonexploratory, repeated)["packet"]["unresolved"], repeated
        )


if __name__ == "__main__":
    unittest.main()
