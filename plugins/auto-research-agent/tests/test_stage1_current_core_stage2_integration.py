"""Authored current-Core checkpoint fixtures; no Stage2 admission is inferred."""

import unittest

from current_core_stage12_fixtures import current_core_stage1_case
from stage1_deliverable.common import read_json, sha
from stage1_deliverable.package import validate as validate_package
from stage1_ledger.journal import canonical, decode
from stage1_ledger.validation import validate_run


class CurrentCoreStage2IntegrationTests(unittest.TestCase):
    def _assert_core_provenance(self, fixture):
        from copy import deepcopy
        from stage2_common import Stage2Error, canonical_hash
        from stage2_common.core_source import (
            copy_files,
            project_claim,
            retain_core_source,
            validate_core_source,
        )

        # Only the standalone Core closure is under test. This is deliberately
        # not a complete Stage2 packet, source-access proof or research acceptance.
        root = fixture["root"] / "retained-core"
        root.mkdir()
        records, handoff = fixture["records"], fixture["handoff"]
        included = {row["work_id"] for row in handoff["papers"]}
        descriptor = retain_core_source(
            fixture["deliverable_dir"], fixture["handoff_path"], root, records
        )
        packet = {
            "schema_version": "2.7.0",
            "core_source": descriptor,
            "upstream": {
                "stage1_records_sha256": fixture["records_sha256"],
                "stage1_deliverable_manifest_sha256": fixture["manifest_sha256"],
                "stage1_handoff_sha256": fixture["handoff_sha256"],
                "source_run_id": handoff["source_run_id"],
                "source_state_sha256": handoff["source_state_sha256"],
                "research_brief_sha256": canonical_hash(
                    read_json(fixture["brief_path"])
                ),
                "included_work_ids": sorted(included),
            },
            "literature": [
                {"origin": "stage1", **row}
                for row in sorted(records["papers"], key=lambda row: row["work_id"])
                if row["work_id"] in included
            ],
            "evidence": [
                project_claim(row)
                for row in records["claims"]
                if row["work_id"] in included
            ],
            "sources": [
                {
                    "origin": "stage1",
                    "source_id": row["source_id"],
                    "work_id": row["work_id"],
                    "version_id": row["version_id"],
                    "path": "not-materialized-in-provenance-only-fixture/"
                    + row["source_id"],
                }
                for row in records["sources"]
                if row["work_id"] in included
            ],
        }
        validate_core_source(packet, root)
        copied = fixture["root"] / "copied-core"
        copy_files(packet, root, copied)
        validate_core_source(packet, copied)
        self.assertEqual(
            read_json(copied / "stage1_core/records.original.json"), records
        )
        self.assertFalse(descriptor["execution_authorized"])
        changed = deepcopy(packet)
        changed["evidence"][0]["claim_text"] = "Invented replacement assertion."
        with self.assertRaisesRegex(Stage2Error, "claim-projection-mismatch"):
            validate_core_source(changed, copied)
        changed = deepcopy(packet)
        changed["core_source"]["scientific_quality_verified"] = True
        with self.assertRaisesRegex(Stage2Error, "descriptor-boundary"):
            validate_core_source(changed, copied)
        handoff_path = copied / "stage1_core/handoff.json"
        original_handoff = handoff_path.read_bytes()
        try:
            paper = handoff["papers"][0]
            for kind, selected in (
                ("title", [dict(paper, title="Different title")]),
                ("version", [dict(paper, reviewed_version_id="other-version")]),
                ("unknown", [dict(paper, work_id="unknown-work")]),
                ("duplicate", [paper, paper]),
                ("empty", []),
            ):
                with self.subTest(handoff=kind):
                    changed, body = deepcopy(packet), deepcopy(handoff)
                    body["papers"] = selected
                    if kind == "unknown":
                        (
                            changed["literature"],
                            changed["evidence"],
                            changed["sources"],
                        ) = [], [], []
                    changed["upstream"]["included_work_ids"] = sorted(
                        {row["work_id"] for row in body["papers"]}
                    )
                    raw = canonical(body)
                    handoff_path.write_bytes(raw)
                    changed["upstream"]["stage1_handoff_sha256"] = sha(raw)
                    next(
                        row
                        for row in changed["core_source"]["files"]
                        if row["path"] == "stage1_core/handoff.json"
                    )["sha256"] = sha(raw)
                    with self.assertRaises(Stage2Error):
                        validate_core_source(changed, copied)
        finally:
            handoff_path.write_bytes(original_handoff)
        ref = next(
            row
            for row in descriptor["files"]
            if "/core_claim_artifacts/" in row["path"]
        )
        original = (copied / ref["path"]).read_bytes()
        (copied / ref["path"]).write_bytes(original + b"\nTampered fixture.\n")
        changed = deepcopy(packet)
        next(
            row for row in changed["core_source"]["files"] if row["path"] == ref["path"]
        )["sha256"] = sha(original + b"\nTampered fixture.\n")
        with self.assertRaisesRegex(Stage2Error, "provenance-invalid"):
            validate_core_source(changed, copied)

    def _qualify_fixture(self, screened):
        with current_core_stage1_case(screened=screened) as fixture:
            self._assert_core_provenance(fixture)
            ledger, records = fixture["ledger"], fixture["records"]
            self.assertEqual(
                records["schema_version"], "1.2.0" if screened else "1.1.0"
            )
            history = [
                row
                for row in ledger.events()
                if row["payload"]["kind"] == "ClaimEvidence"
            ]
            self.assertEqual(records["core_claim_history"], history)
            self.assertEqual(
                history[: len(fixture["original_core_history"])],
                fixture["original_core_history"],
            )
            self.assertEqual(
                fixture["zero_callback_counts"],
                {"query_runner": 0, "source_service": 0, "model": 0},
            )
            fixture["case"].runner.assert_not_called()
            self.assertTrue(validate_run(ledger.root)["valid"])
            self.assertEqual(
                [
                    len(row["new_qualified_work_ids"])
                    for row in fixture["report"]["coverage"]["rounds"]
                ],
                [1, 0, 0],
            )
            checkpoint, handoff = fixture["checkpoint"], fixture["handoff"]
            self.assertEqual(
                checkpoint["stage_result"]["next_allowed_action"], "stop-sufficient"
            )
            self.assertEqual(
                handoff, decode(ledger.read_ref(fixture["handoff_ref"]), "handoff")
            )
            self.assertEqual(handoff, read_json(fixture["handoff_path"]))
            self.assertTrue(handoff["eligible_for_stage2"])
            self.assertFalse(handoff["stage2"]["execution_authorized"])
            self.assertEqual(
                handoff["source_run_id"], ledger.manifest["research_run"]["run_id"]
            )
            self.assertEqual(handoff["source_state_sha256"], checkpoint["state_sha256"])
            self.assertEqual(
                fixture["binding"]["checkpoint_event_id"], checkpoint["event_id"]
            )
            self.assertEqual(fixture["binding"]["project_ref"], fixture["project_ref"])
            current = fixture["case"].intake.binding(fixture["project_ref"])
            self.assertEqual(current["brief_sha256"], fixture["brief_sha256"])
            self.assertEqual(
                fixture["binding"]["binding"]["input_version"], current["input_version"]
            )
            for key in ("records", "handoff", "brief", "resources"):
                self.assertEqual(
                    sha(fixture[key + "_path"].read_bytes()), fixture[key + "_sha256"]
                )
            self.assertEqual(
                validate_package(
                    fixture["deliverable_dir"], fixture["manifest_sha256"]
                )["status"],
                "passed",
            )
            null_claims = [
                row for row in records["claims"] if row["relation"] == "pending"
            ]
            for row in null_claims:
                for name in ("locator", "start", "end", "quote"):
                    self.assertIsNone(row[name], name)
                self.assertIsNone(row["core_event"]["payload"]["locator"])
            primary = [
                row
                for row in records["claims"]
                if row["evidence_level"] == "primary_data_or_table"
            ]
            self.assertTrue(primary)
            for row in primary:
                payload = row["core_event"]["payload"]
                text = ledger.read_ref(payload["source_ref"]).decode("utf-8")
                self.assertEqual(text[row["start"] : row["end"]], row["quote"])
                self.assertEqual(row["quote"], payload["locator"]["quote"])
            self.assertEqual(
                {row["relation"] for row in records["claims"]},
                {
                    "supports",
                    "partial",
                    "pending",
                    "unclear",
                    "unverifiable",
                    "context",
                },
            )
            self.assertEqual("screening_library" in records, screened)
            if screened:
                self.assertEqual(
                    records["screening_library"]["binding"]["project_ref"],
                    fixture["project_ref"],
                )
                self.assertEqual(
                    records["screening_library"]["binding"]["journal_sha256"],
                    records["screening_journal"]["sha256"],
                )
                self.assertTrue(any("assessment" in row["payload"] for row in history))

    def test_checkpoint_generated_core11_handoff_and_package_without_dispatch(self):
        self._qualify_fixture(False)

    def test_checkpoint_generated_screened12_handoff_and_package_without_dispatch(self):
        self._qualify_fixture(True)
