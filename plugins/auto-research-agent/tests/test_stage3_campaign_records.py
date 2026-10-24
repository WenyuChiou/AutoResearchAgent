"""Synthetic offline campaign checks; not a scientific evaluation."""

from pathlib import Path
from unittest.mock import patch

from stage3_campaign_test_support import CampaignFixture
from stage3_plan.campaign import POLICY, binding
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.campaign_records import inspect_receipt, record_campaign
from stage3_plan.storage import read_json


class CampaignRecordsTests(CampaignFixture):
    def test_raw_neutral_judgment_roundtrip_and_same_key_resume(self):
        self.prepare()
        unit = self.manifest["units"][0]
        first = self.record(unit)
        before = {
            p.name: p.read_bytes() for p in (self.root / unit["unit_id"]).iterdir()
        }
        again = self.record(unit)
        self.assertTrue(again["replayed"])
        self.assertEqual(
            before,
            {p.name: p.read_bytes() for p in (self.root / unit["unit_id"]).iterdir()},
        )
        receipt, record = inspect_receipt(
            first["receipt_binding"], self.manifest, self.campaign_sha
        )
        self.assertEqual(
            record["bindings"]["question_refs"],
            self.request["bindings"]["question_refs"],
        )
        self.assertEqual(receipt["policy"], POLICY)
        with self.assertRaisesRegex(Stage3Error, "different input"):
            self.record(unit, score=1)

    def test_malformed_raw_bytes_are_retained_and_partial_is_not_reexecuted(self):
        self.prepare()
        unit = self.manifest["units"][0]
        for index, raw in enumerate(
            (b"{bad", b"\xff", ("[" * 2000 + "]" * 2000).encode())
        ):
            target = self.root / ("bad-" + str(index))
            source = self.root / ("input-" + str(index))
            source.write_bytes(raw)
            with self.assertRaises(Stage3Error):
                record_campaign(
                    self.campaign,
                    expected_sha256=self.campaign_sha,
                    unit_id=unit["unit_id"],
                    judgment=source,
                    expected_judgment_sha256=binding(source)["sha256"],
                    output=target,
                )
            self.assertEqual((target / "judgment.raw").read_bytes(), raw)
            self.assertEqual(read_json(target / "receipt.json")["status"], "failed")
        partial = self.root / "partial"
        partial.mkdir()
        with self.assertRaises((Stage3Error, OSError)):
            record_campaign(
                self.campaign,
                expected_sha256=self.campaign_sha,
                unit_id=unit["unit_id"],
                judgment=source,
                expected_judgment_sha256=binding(source)["sha256"],
                output=partial,
            )
        self.assertEqual(list(partial.iterdir()), [])

    def test_rehashed_record_tamper_is_rejected(self):
        self.prepare()
        result = self.record(self.manifest["units"][0])
        receipt_path = Path(result["receipt_binding"]["path"])
        receipt = read_json(receipt_path)
        record_path = Path(receipt["record"]["path"])
        record = read_json(record_path)
        record["score_vector"]["P7"]["score"] = 0
        record_path.write_bytes(canonical_bytes(record))
        receipt["record"] = binding(record_path)
        receipt_path.write_bytes(canonical_bytes(receipt))
        with self.assertRaisesRegex(Stage3Error, "replay"):
            inspect_receipt(binding(receipt_path), self.manifest, self.campaign_sha)

    def test_injected_io_failure_after_mapping_stays_failed_and_readable(self):
        self.prepare()
        unit = self.manifest["units"][0]
        with patch(
            "stage3_plan.campaign_records.record_evaluation",
            side_effect=OSError("injected fsync/write failure"),
        ):
            with self.assertRaises(Stage3Error):
                self.record(unit)
        target = self.root / unit["unit_id"]
        receipt, record = inspect_receipt(
            binding(target / "receipt.json"), self.manifest, self.campaign_sha
        )
        self.assertEqual(receipt["status"], "failed")
        self.assertIsNone(record)
        self.assertEqual(receipt["error"]["kind"], "OSError")
        with self.assertRaisesRegex(Stage3Error, "no automatic retry"):
            self.record(unit)

    def test_bad_grade_and_oversized_input_cannot_complete_a_unit(self):
        self.prepare()
        unit = self.manifest["units"][0]
        judgment = self.judgment(unit)
        judgment["criteria"][0]["score"] = True
        path = self.save("bad-score.json", judgment)
        with self.assertRaises(Stage3Error):
            record_campaign(
                self.campaign,
                expected_sha256=self.campaign_sha,
                unit_id=unit["unit_id"],
                judgment=path,
                expected_judgment_sha256=binding(path)["sha256"],
                output=self.root / "bad-score",
            )
        receipt, record = inspect_receipt(
            binding(self.root / "bad-score/receipt.json"),
            self.manifest,
            self.campaign_sha,
        )
        self.assertEqual(record["record_status"], "failed")
        self.assertEqual(receipt["status"], "failed")
        large = self.root / "large.raw"
        large.write_bytes(b"x" * 2_000_001)
        with self.assertRaises(Stage3Error):
            record_campaign(
                self.campaign,
                expected_sha256=self.campaign_sha,
                unit_id=unit["unit_id"],
                judgment=large,
                expected_judgment_sha256="0" * 64,
                output=self.root / "large-output",
            )
        self.assertFalse((self.root / "large-output").exists())
