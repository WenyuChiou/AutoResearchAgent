"""New excerpts retain the real versioned packet evidence contract."""

import copy
import json
from pathlib import Path
import sys
import unittest

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage2_common import Stage2Error, validate_packet  # noqa: E402
from stage2_live.content_revision import prepare_content_revision_input  # noqa: E402
import test_stage1_stage2_handoff as handoff_fixtures  # noqa: E402
import test_stage2_exploratory_contract as exploratory_fixtures  # noqa: E402


class VersionedContentRevisionTests(unittest.TestCase):
    def fixture(self, version):
        if version == "2.0.0":
            holder = handoff_fixtures.Stage1Stage2HandoffTests(methodName="runTest")
            holder.setUp()
            self.addCleanup(holder.doCleanups)
            holder.build()
            packet, root = holder.packet(), holder.output
        else:
            holder = exploratory_fixtures.ExploratoryContractTests(methodName="runTest")
            holder.setUp()
            self.addCleanup(holder.doCleanups)
            packet, root = copy.deepcopy(holder.packet), holder.fixture.output
            if version == "2.2.0":
                packet["schema_version"] = version
                packet["research_tables"] = None
        validate_packet(packet, root)
        source = packet["sources"][0]
        quote = (root / source["path"]).read_bytes().decode("utf-8").splitlines()[0]
        addition = {
            "origin": "stage2",
            "evidence_id": "ev-new-context",
            "source_id": source["source_id"],
            "work_id": source["work_id"],
            "version_id": source["version_id"],
            "claim_text": "Synthetic source context for a fresh assessment.",
            "relation": "constrains",
            "evidence_level": source["evidence_level"],
            "locator": "lines 1-1",
            "quote": quote,
        }
        return packet, root, addition

    def test_valid_versioned_excerpts_pass_real_packet_validation(self):
        for version in ("2.0.0", "2.1.0", "2.2.0"):
            with self.subTest(version=version):
                packet, root, addition = self.fixture(version)
                output = root.parent / "new-context"
                receipt = prepare_content_revision_input(
                    packet, root, [addition], output
                )
                updated = json.loads(
                    (output / "packet.json").read_text(encoding="utf-8")
                )
                validate_packet(updated, root)
                self.assertEqual(updated["evidence"][:-1], packet["evidence"])
                self.assertEqual(updated["evidence"][-1], addition)
                self.assertEqual(updated["upstream"], packet["upstream"])
                self.assertEqual(updated["sources"], packet["sources"])
                self.assertTrue(receipt["review_required"])
                self.assertFalse(receipt["sources_changed"])

    def test_missing_claim_fields_and_wrong_origin_fail_before_output(self):
        for mutation in (
            lambda row: row.pop("claim_text"),
            lambda row: row.update(origin="stage1"),
            lambda row: row.update(claim_text=" "),
            lambda row: row.update(relation=" "),
            lambda row: row.update(evidence_level={"level": "full-text"}),
        ):
            packet, root, addition = self.fixture("2.2.0")
            mutation(addition)
            output = root.parent / "invalid-context"
            with self.assertRaises(Stage2Error):
                prepare_content_revision_input(packet, root, [addition], output)
            self.assertFalse(output.exists())

    def test_wrong_version_or_changed_quote_fail_before_output(self):
        for mutation in (
            lambda row: row.update(version_id="foreign-version"),
            lambda row: row.update(quote=row["quote"] + " invented"),
        ):
            packet, root, addition = self.fixture("2.2.0")
            mutation(addition)
            output = root.parent / "foreign-context"
            with self.assertRaises(Stage2Error):
                prepare_content_revision_input(packet, root, [addition], output)
            self.assertFalse(output.exists())

    def test_excerpt_cannot_promote_abstract_to_full_text(self):
        packet, root, addition = self.fixture("2.2.0")
        source = copy.deepcopy(packet["sources"][0])
        raw = (root / source["path"]).read_bytes()
        source.update(
            origin="stage2",
            source_id="src-abstract",
            evidence_level="abstract",
            path="abstract-context.txt",
        )
        (root / source["path"]).write_bytes(raw)
        packet["sources"].append(source)
        validate_packet(packet, root)
        addition.update(source_id=source["source_id"], evidence_level="full-text")
        output = root.parent / "promoted-context"
        with self.assertRaisesRegex(Stage2Error, "level-promotion"):
            prepare_content_revision_input(packet, root, [addition], output)
        self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
