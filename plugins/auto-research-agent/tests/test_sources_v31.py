import subprocess
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import EvaluationError, canonical, read_json, sha, write_json  # noqa: E402
from stage1_eval.extraction_v31 import _aggregate_works, work_id_for  # noqa: E402
from stage1_eval.sources_v31 import (  # noqa: E402
    _fetch,
    attach_public_sources,
    collect_sources_v31,
)


def work(title="A Study", identifier="10.1234/example"):
    identity = {"identifier": identifier, "title": title}
    return {
        "work_id": work_id_for(identity),
        **identity,
        "exact_reference": title,
        "evidence_id": "answer",
        "nominated_core": True,
    }


def metadata_source(item, *, date_status="within-year-cutoff"):
    return {
        "source_id": "src-metadata",
        "subject_work_id": item["work_id"],
        "work_key": "doi:10.1234/example",
        "version_id": "version-meta",
        "title": item["title"],
        "doi": "10.1234/example",
        "authors": ["Researcher"],
        "year": 2024,
        "url": "https://example.test/article",
        "abstract": "abstract",
        "source_level": "abstract",
        "date_status": date_status,
        "receipt_id": item["work_id"],
        "raw_sha256": "a" * 64,
    }


class PublicSourceFetchArchiveTests(unittest.TestCase):
    def test_merged_extractor_doi_rows_pass_source_admission(self):
        entries = [
            {
                **work("Visible Study.", "https://doi.org/10.1234/study"),
                "span_ids": ["a"],
            },
            {**work("Visible Study", "10.1234/study"), "span_ids": ["b"]},
        ]
        works, _ = _aggregate_works([{"works": entries}])
        self.assertEqual(len(works), 1)
        with (
            mock.patch(
                "stage1_eval.sources_v31._metadata",
                return_value={"sources": [], "receipts": []},
            ),
            mock.patch(
                "stage1_eval.sources_v31._fetch",
                return_value=(None, {"status": "timeout"}),
            ) as fetch,
        ):
            result = collect_sources_v31(
                {"works": works}, {}, self.root / "collector", ["hub"]
            )
        self.assertEqual(fetch.call_count, 1)
        self.assertEqual(result["public_fetches"][0]["work_id"], works[0]["work_id"])

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.directory = self.root / "public-fetch"
        self.source = self.directory / "source"
        self.args = [
            "source",
            "fetch",
            "--title",
            "A Study",
            "--output-dir",
            str(self.source),
            "--json",
            "--doi",
            "10.1234/example",
        ]
        self.request = {
            "operation": "source fetch",
            "doi": "10.1234/example",
            "url": "",
            "title": "A Study",
            "output_dir": str(self.source),
            "public_only": True,
        }
        self.byte_replay = mock.patch(
            "stage1_eval.sources_v31._replay_source_bytes",
            return_value={"schema_version": "1.0.0", "valid": True, "errors": []},
        ).start()
        self.addCleanup(mock.patch.stopall)

    def tearDown(self):
        self.temp.cleanup()

    def result(self, *, status="available"):
        self.source.mkdir(parents=True, exist_ok=True)
        raw = self.source / "raw.bin"
        text = self.source / "text.txt"
        raw.write_bytes(b"raw source bytes")
        text.write_text("A Study full text", encoding="utf-8")
        value = {
            "schema_version": "1.0.0",
            "request": self.request,
            "receipt_sha256": "b" * 64,
            "status": status,
            "evidence_level": "full-text",
            "source_url": "https://example.test/article",
            "final_url": "https://example.test/article",
            "retrieved_at": "2026-09-26T00:00:00+00:00",
            "expected_identity": {"doi": "10.1234/example", "title": "A Study"},
            "observed_identity": {"doi": "10.1234/example", "title": "A Study"},
            "identity_status": "verified",
            "source_version": "sha256:" + sha(raw.read_bytes()),
            "attempts": [],
            "raw_path": str(raw),
            "raw_sha256": sha(raw.read_bytes()),
            "extracted_text_path": str(text),
            "extracted_text_sha256": sha(text.read_bytes()),
            "locators": [
                {"kind": "html-section", "section": "Results", "start": 0, "end": 17}
            ],
            "errors": [],
            "output_dir": str(self.source),
        }
        write_json(self.source / "source-fetch-result.json", value)
        return value

    def runner(self, command, **_kwargs):
        if command[1:3] == ["source", "fetch"]:
            value = self.result()
            return SimpleNamespace(returncode=0, stdout=canonical(value), stderr=b"")
        self.assertEqual(command[1:3], ["source", "validate"])
        report = {"schema_version": "1.0.0", "valid": True, "errors": []}
        return SimpleNamespace(returncode=0, stdout=canonical(report), stderr=b"")

    def invoke(self, *, replay_only=False, request=None):
        with (
            mock.patch(
                "stage1_eval.sources_v31.executable_sha256", return_value="e" * 64
            ),
            mock.patch(
                "stage1_eval.sources_v31.installed_package_sha256",
                return_value="p" * 64,
            ),
        ):
            return _fetch(
                ["hub"],
                self.args,
                self.directory,
                request or self.request,
                replay_only,
            )

    def test_success_binds_fetch_validation_runtime_stdout_and_replays_offline(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ) as run:
            result, receipt = self.invoke()
        self.assertEqual(run.call_count, 2)
        self.assertEqual(receipt["request"], self.request)
        self.assertEqual(result["status"], "available")
        self.assertEqual(
            read_json(self.directory / "request.json")["command"], ["hub", *self.args]
        )
        validation = read_json(self.directory / "validation/receipt.json")
        self.assertEqual(
            validation["result_sha256"],
            sha((self.source / "source-fetch-result.json").read_bytes()),
        )
        with mock.patch("stage1_eval.sources_v31.subprocess.run") as replay:
            self.invoke(replay_only=True)
        replay.assert_not_called()

    def test_rehashed_wrong_request_is_rejected(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ):
            self.invoke()
        request_path = self.directory / "request.json"
        receipt_path = self.directory / "fetch-receipt.json"
        for path in (request_path, receipt_path):
            value = read_json(path)
            value["request"]["title"] = "Different Study"
            path.write_bytes(canonical(value) + b"\n")
        with self.assertRaisesRegex(EvaluationError, "request/runtime changed"):
            self.invoke(replay_only=True)

    def test_replay_rechecks_source_bytes_not_only_the_saved_validator_report(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ):
            self.invoke()
        self.byte_replay.side_effect = EvaluationError(
            "public source bytes fail offline extraction replay"
        )
        with mock.patch("stage1_eval.sources_v31.subprocess.run") as external:
            with self.assertRaisesRegex(EvaluationError, "source bytes fail"):
                self.invoke(replay_only=True)
        external.assert_not_called()

    def test_offline_validation_clock_is_not_a_source_version_change(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ):
            self.invoke()
        self.byte_replay.return_value["checked_at"] = "2026-09-27T00:00:00Z"
        self.invoke(replay_only=True)

    def test_rehashed_result_with_wrong_request_is_rejected(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ):
            self.invoke()
        result_path = self.source / "source-fetch-result.json"
        changed = read_json(result_path)
        changed["request"]["title"] = "Different Study"
        result_path.write_bytes(canonical(changed) + b"\n")
        stdout = canonical(changed)
        (self.directory / "stdout.json").write_bytes(stdout)
        receipt = read_json(self.directory / "fetch-receipt.json")
        receipt["stdout_sha256"] = sha(stdout)
        (self.directory / "fetch-receipt.json").write_bytes(canonical(receipt) + b"\n")
        with self.assertRaisesRegex(EvaluationError, "differs from executed request"):
            self.invoke(replay_only=True)

    def test_completed_fetch_cannot_silently_lose_result(self):
        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=self.runner
        ):
            self.invoke()
        (self.source / "source-fetch-result.json").unlink()
        with self.assertRaisesRegex(EvaluationError, "lost its structured result"):
            self.invoke(replay_only=True)

    def test_structured_cli_failure_is_validated_and_preserved_as_unknown(self):
        def structured_failure(command, **_kwargs):
            if command[1:3] == ["source", "fetch"]:
                value = self.result(status="identity-mismatch")
                return SimpleNamespace(
                    returncode=1, stdout=canonical(value), stderr=b""
                )
            report = {"schema_version": "1.0.0", "valid": True, "errors": []}
            return SimpleNamespace(returncode=0, stdout=canonical(report), stderr=b"")

        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=structured_failure
        ) as run:
            result, receipt = self.invoke()

        self.assertEqual(run.call_count, 2)
        self.assertEqual(receipt["returncode"], 1)
        self.assertEqual(result["status"], "identity-mismatch")
        packet = {
            "extraction": {"works": [work()]},
            "sources": {},
            "source_origins": {},
            "content_evidence": {},
        }
        attach_public_sources(
            packet,
            {
                "sources": [metadata_source(work())],
                "receipts": [],
                "public_fetches": [
                    {"work_id": work()["work_id"], "receipt": receipt, "result": result}
                ],
            },
        )
        self.assertEqual(packet["sources"], {})
        self.assertEqual(packet["content_evidence"], {})

    def test_rehashed_status_cannot_disagree_with_cli_exit(self):
        def structured_failure(command, **_kwargs):
            if command[1:3] == ["source", "fetch"]:
                value = self.result(status="identity-mismatch")
                return SimpleNamespace(
                    returncode=1, stdout=canonical(value), stderr=b""
                )
            report = {"schema_version": "1.0.0", "valid": True, "errors": []}
            return SimpleNamespace(returncode=0, stdout=canonical(report), stderr=b"")

        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=structured_failure
        ):
            self.invoke()
        result_path = self.source / "source-fetch-result.json"
        changed = read_json(result_path)
        changed["status"] = "available"
        result_path.write_bytes(canonical(changed) + b"\n")
        stdout = canonical(changed)
        (self.directory / "stdout.json").write_bytes(stdout)
        receipt = read_json(self.directory / "fetch-receipt.json")
        receipt["stdout_sha256"] = sha(stdout)
        (self.directory / "fetch-receipt.json").write_bytes(canonical(receipt) + b"\n")

        with self.assertRaisesRegex(EvaluationError, "exit code disagrees"):
            self.invoke(replay_only=True)

    def test_timeout_preserves_partial_logs_without_result_or_reexecution(self):
        timeout = subprocess.TimeoutExpired(
            cmd=["hub", *self.args],
            timeout=600,
            output=b"partial stdout",
            stderr=b"partial stderr",
        )
        with mock.patch("stage1_eval.sources_v31.subprocess.run", side_effect=timeout):
            result, receipt = self.invoke()

        self.assertIsNone(result)
        self.assertEqual(receipt["status"], "timeout")
        self.assertEqual(
            (self.directory / "stdout.json").read_bytes(), b"partial stdout"
        )
        self.assertEqual(
            (self.directory / "stderr.txt").read_bytes(), b"partial stderr"
        )
        with mock.patch("stage1_eval.sources_v31.subprocess.run") as rerun:
            replayed, _ = self.invoke(replay_only=True)
        self.assertIsNone(replayed)
        rerun.assert_not_called()

    def test_failed_call_preserves_logs_and_remains_unknown(self):
        failure = SimpleNamespace(returncode=7, stdout=b"partial", stderr=b"failed")
        with mock.patch("stage1_eval.sources_v31.subprocess.run", return_value=failure):
            result, receipt = self.invoke()
        self.assertIsNone(result)
        self.assertEqual(receipt["status"], "completed")
        self.assertEqual((self.directory / "stdout.json").read_bytes(), b"partial")
        self.assertEqual((self.directory / "stderr.txt").read_bytes(), b"failed")
        self.assertFalse((self.directory / "validation").exists())

    def test_partial_saved_call_is_not_reexecuted(self):
        self.directory.mkdir()
        write_json(self.directory / "request.json", {"partial": True})
        with (
            mock.patch("stage1_eval.sources_v31.subprocess.run") as run,
            self.assertRaisesRegex(EvaluationError, "partial source fetch"),
        ):
            self.invoke()
        run.assert_not_called()

    def test_partial_saved_validation_is_not_reexecuted(self):
        calls = []

        def stop_after_fetch(command, **kwargs):
            calls.append(command)
            if command[1:3] == ["source", "fetch"]:
                value = self.result()
                return SimpleNamespace(
                    returncode=0, stdout=canonical(value), stderr=b""
                )
            raise OSError("validation interrupted")

        with mock.patch(
            "stage1_eval.sources_v31.subprocess.run", side_effect=stop_after_fetch
        ):
            with self.assertRaisesRegex(EvaluationError, "did not complete"):
                self.invoke()
        (self.directory / "validation/receipt.json").unlink()
        with (
            mock.patch("stage1_eval.sources_v31.subprocess.run") as run,
            self.assertRaisesRegex(EvaluationError, "partial source validation"),
        ):
            self.invoke()
        run.assert_not_called()


class PublicSourceAdapterTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name)
        self.work = work()

    def tearDown(self):
        self.temp.cleanup()

    def public_result(self, *, status="available"):
        source_dir = self.root / "source"
        source_dir.mkdir(exist_ok=True)
        raw = source_dir / "raw.bin"
        text = source_dir / "text.txt"
        raw.write_bytes(b"raw")
        text.write_text("A Study evidence passage", encoding="utf-8")
        return {
            "status": status,
            "evidence_level": "full-text",
            "expected_identity": {"doi": "10.1234/example", "title": "A Study"},
            "observed_identity": {"doi": "10.1234/example", "title": "A Study"},
            "identity_status": "verified",
            "source_version": "sha256:" + sha(raw.read_bytes()),
            "raw_sha256": sha(raw.read_bytes()),
            "extracted_text_path": str(text),
            "extracted_text_sha256": sha(text.read_bytes()),
            "output_dir": str(source_dir),
            "final_url": "https://example.test/article",
            "locators": [
                {
                    "kind": "html-section",
                    "section": "Results",
                    "start": 0,
                    "end": len(text.read_text()),
                }
            ],
        }

    def packet(self):
        return {
            "extraction": {"works": [self.work]},
            "sources": {},
            "source_origins": {},
            "content_evidence": {},
        }

    def test_attachment_uses_metadata_cutoff_and_marks_non_search_origin(self):
        result = self.public_result()
        collected = {
            "sources": [metadata_source(self.work)],
            "receipts": [{"status": "results"}],
            "public_fetches": [
                {"work_id": self.work["work_id"], "receipt": {}, "result": result}
            ],
        }
        packet = attach_public_sources(self.packet(), collected)
        source = next(iter(packet["sources"].values()))
        evidence = next(iter(packet["content_evidence"].values()))
        self.assertEqual(source["date_status"], "within-year-cutoff")
        self.assertFalse(source["counts_as_subject_search"])
        self.assertEqual(evidence["locator"], result["locators"])
        self.assertEqual(
            packet["source_origins"][source["source_id"]], ["evaluator-reference-check"]
        )

    def test_failed_fetch_and_after_cutoff_metadata_add_no_source_text(self):
        for result, date_status in (
            (self.public_result(status="inaccessible"), "within-year-cutoff"),
            (self.public_result(), "after-cutoff"),
        ):
            packet = self.packet()
            collected = {
                "sources": [metadata_source(self.work, date_status=date_status)],
                "receipts": [],
                "public_fetches": [
                    {"work_id": self.work["work_id"], "receipt": {}, "result": result}
                ],
            }
            attach_public_sources(packet, collected)
            self.assertEqual(packet["sources"], {})
            self.assertEqual(packet["content_evidence"], {})

    def test_work_id_must_be_nonempty_and_match_deterministic_identity(self):
        for invalid in ("work-", "work-" + "0" * 16):
            changed = {**self.work, "work_id": invalid}
            with self.assertRaisesRegex(EvaluationError, "unsafe extracted work ID"):
                collect_sources_v31(
                    {"works": [changed]}, {}, self.root / invalid, ["hub"]
                )

    def test_collection_keeps_metadata_and_public_fetch_distinct(self):
        metadata = {
            "sources": [metadata_source(self.work)],
            "receipts": [{"status": "results", "work_id": self.work["work_id"]}],
        }
        fetched = self.public_result()
        with (
            mock.patch("stage1_eval.sources_v31._metadata", return_value=metadata),
            mock.patch(
                "stage1_eval.sources_v31._fetch",
                return_value=(fetched, {"status": "completed"}),
            ) as fetch,
        ):
            result = collect_sources_v31(
                {"works": [self.work]},
                {},
                self.root / "collected",
                ["hub"],
            )
        self.assertEqual(result["sources"], metadata["sources"])
        self.assertEqual(result["receipts"], metadata["receipts"])
        self.assertEqual(len(result["public_fetches"]), 1)
        request = fetch.call_args.args[3]
        self.assertEqual(
            request,
            {
                "operation": "source fetch",
                "doi": "10.1234/example",
                "url": "https://example.test/article",
                "title": "A Study",
                "output_dir": str(
                    (
                        self.root
                        / "collected"
                        / self.work["work_id"]
                        / "public-fetch/source"
                    ).resolve()
                ),
                "public_only": True,
            },
        )


if __name__ == "__main__":
    unittest.main()
