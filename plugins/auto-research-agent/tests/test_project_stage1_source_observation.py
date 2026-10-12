"""Local source completion on real Core and SDK parsing of authored HTTP bytes."""

from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

import test_project_stage1_records as records_fixture
import test_stage1_deliverable as package_fixture
from research_workspace_native.project_stage1_source_observation import (
    complete_saved_source,
)
from research_workspace_native.session_api import SessionApiError
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import read_json, sha, write_json
from stage1_ledger.validation import validate_run


class SourceObservationTests(unittest.TestCase):
    setUpClass = classmethod(
        records_fixture.SavedStage1RecordsTests.setUpClass.__func__
    )
    setUp = records_fixture.SavedStage1RecordsTests.setUp
    reopen = records_fixture.SavedStage1RecordsTests.reopen
    saved = records_fixture.SavedStage1RecordsTests.saved

    def observation(
        self, *, status=200, raw=package_fixture.HTML, title=package_fixture.TITLE
    ):
        fixture = self.saved()
        ledger = fixture["ledger"]
        paper = fixture["records"]["papers"][0]
        self.inputs = self.fixture_root / "next"
        self.inputs.mkdir()
        output = (self.inputs / "source").resolve()
        request = dict(
            operation="source fetch",
            doi="",
            url="https://example.org/study",
            title=title,
            output_dir=str(output),
            public_only=True,
        )
        source = ledger.start_source(
            work_id=paper["work_id"],
            version_id=paper["version_id"],
            source_uri=request["url"],
            tool="research_hub.source_fetch",
            request=request,
            actor="fixture",
            reason="Authored SDK response only.",
        )
        start = ledger.event(source, "SourceReadStarted")
        package_fixture.ResearchDeliverableTests.make_records(
            self, raw=raw, status=status, title=title
        )
        path = output / "source-fetch-result.json"
        kwargs = dict(
            materials_root=self.fixture_root,
            source_id=source,
            expected_start=start,
            result_path=path,
            expected_result_sha256=sha(path.read_bytes()),
            runtime_sha256="1" * 64,
            reason="Saved SDK observation from authored HTTP; no acquisition attestation.",
        )
        return fixture, kwargs

    def complete(self, fixture, kwargs):
        return complete_saved_source(fixture["ledger"], **kwargs)

    def assert_refused_without_write(self, fixture, kwargs):
        ledger = fixture["ledger"]
        before = ledger.events()
        with self.assertRaises((ValueError, OSError, SessionApiError)):
            self.complete(fixture, kwargs)
        self.assertEqual(ledger.events(), before)
        self.runner.assert_not_called()

    def test_real_sdk_available_completion_registry_and_reopen_refuses_repeat(self):
        fixture, kwargs = self.observation()
        result = self.complete(fixture, kwargs)
        receipt = read_json(kwargs["result_path"])
        finish = result["finish"]
        self.assertEqual(finish["outcome"], "available")
        self.assertEqual(
            sha(fixture["ledger"].read_ref(finish["text_ref"])),
            receipt["extracted_text_sha256"],
        )
        self.assertEqual(
            result["source_description"]["result_sha256"],
            kwargs["expected_result_sha256"],
        )
        self.assertIn("not execution attestation", result["evidence_scope"])
        self.assertEqual(
            result["source_description"]["artifacts"],
            {
                rel: sha((kwargs["result_path"].parent / rel).read_bytes())
                for rel in result["source_description"]["artifacts"]
            },
        )
        fixture["ledger"].checkpoint()
        registered = self.producer.register_source(
            fixture["ref"],
            source_id=result["source_id"],
            result_path=kwargs["result_path"],
            expected_result_sha256=kwargs["expected_result_sha256"],
            access_note=kwargs["reason"],
            expected_ledger_state_sha256=fixture["ledger"].state_hash(),
        )
        self.assertEqual(registered["payload"], result["source_description"])
        self.assertTrue(validate_run(fixture["ledger"].root)["valid"])
        fixture["ledger"] = CoverageLedger(fixture["ledger"].root)
        self.assert_refused_without_write(fixture, kwargs)

    def test_http_failure_preserves_receipt_attempt_bytes_without_text(self):
        fixture, kwargs = self.observation(status=503)
        result = self.complete(fixture, kwargs)
        receipt = read_json(kwargs["result_path"])
        finish = result["finish"]
        self.assertEqual(
            (
                finish["outcome"],
                finish["http_status"],
                finish["text_ref"],
                finish["extraction"],
            ),
            ("http_error", 503, None, None),
        )
        raw = Path(receipt["attempts"][-1]["raw_path"]).read_bytes()
        self.assertEqual(fixture["ledger"].read_ref(finish["raw_ref"]), raw)
        self.assertEqual(
            result["source_description"]["artifacts"],
            {
                rel: sha((kwargs["result_path"].parent / rel).read_bytes())
                for rel in result["source_description"]["artifacts"]
            },
        )

    def test_network_failure_records_exact_original_receipt_not_fabricated_response(
        self,
    ):
        fixture, kwargs = self.observation(
            raw=package_fixture.Timeout("authored timeout")
        )
        result = self.complete(fixture, kwargs)
        finish = result["finish"]
        self.assertEqual(
            (finish["outcome"], finish["http_status"], finish["text_ref"]),
            ("network_error", None, None),
        )
        self.assertEqual(
            fixture["ledger"].read_ref(finish["raw_ref"]),
            kwargs["result_path"].read_bytes(),
        )

    def test_changed_owner_start_url_version_or_request_refuses_before_write(self):
        fixture, original = self.observation()
        for field, value in (
            ("source_uri", "https://example.org/other"),
            ("version_id", "foreign"),
            ("tool", "foreign-reader"),
            ("request", {"public_only": True}),
        ):
            with self.subTest(field=field):
                kwargs = deepcopy(original)
                kwargs["expected_start"][field] = value
                self.assert_refused_without_write(fixture, kwargs)

    def test_rehashed_receipt_request_or_prestart_time_refuses_before_write(self):
        fixture, original = self.observation()
        path = original["result_path"]
        receipt = read_json(path)
        for field in ("url", "title", "output_dir", "time"):
            with self.subTest(field=field):
                changed = deepcopy(receipt)
                if field == "time":
                    changed["retrieved_at"] = "2000-01-01T00:00:00Z"
                else:
                    changed["request"][field] = {
                        "url": "https://example.org/foreign",
                        "title": "Foreign title",
                        "output_dir": str(path.parent.parent),
                    }[field]
                changed["receipt_sha256"] = package_fixture.sources.receipt_digest(
                    changed
                )
                write_json(path, changed)
                kwargs = dict(original, expected_result_sha256=sha(path.read_bytes()))
                self.assert_refused_without_write(fixture, kwargs)

    def test_partial_receipt_and_artifact_hash_tamper_refuse_before_write(self):
        fixture, kwargs = self.observation()
        path = kwargs["result_path"]
        raw = path.read_bytes()
        path.write_bytes(raw[: len(raw) // 2])
        self.assert_refused_without_write(
            fixture, dict(kwargs, expected_result_sha256=sha(path.read_bytes()))
        )
        path.write_bytes(raw)
        self.assert_refused_without_write(
            fixture, dict(kwargs, expected_result_sha256="0" * 64)
        )
        receipt = read_json(path)
        Path(receipt["extracted_text_path"]).write_bytes(b"tampered text")
        self.assert_refused_without_write(fixture, kwargs)

    def test_guard_refusal_before_write_and_after_raw_preserves_pending_history(self):
        fixture, kwargs = self.observation()
        ledger = fixture["ledger"]
        before = ledger.events()
        calls = [0]

        def check():
            calls[0] += 1
            raise OSError("authored owner loss")

        self.assert_refused_without_write(fixture, dict(kwargs, check_current=check))
        calls[0] = 0

        def after_raw():
            calls[0] += 1
            if calls[0] == 2:
                raise OSError("authored owner lost after raw save")

        with self.assertRaises(OSError):
            self.complete(fixture, dict(kwargs, check_current=after_raw))
        after = ledger.events()
        self.assertEqual(after[: len(before)], before)
        self.assertEqual(
            [row["payload"]["kind"] for row in after[len(before) :]], ["ArtifactStored"]
        )
        self.assertFalse(
            any(
                row["payload"]["kind"] == "SourceReadFinished"
                and row["payload"]["attempt_id"] == kwargs["source_id"]
                for row in after
            )
        )
        self.runner.assert_not_called()

    def test_receipt_outside_fixed_materials_root_refuses_before_write(self):
        fixture, kwargs = self.observation()
        self.assert_refused_without_write(
            fixture, dict(kwargs, materials_root=fixture["path"].parent)
        )


if __name__ == "__main__":
    unittest.main()
