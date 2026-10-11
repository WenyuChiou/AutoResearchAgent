"""Actual SDK saved-public parsing of authored transport observations only.

The injected synchronous runner is not a production process/deadline proof.
No source, DNS, native process, model, protected input or Core mutation runs.
"""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
from datetime import datetime, timedelta, timezone
import os
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from research_hub.source_fetch_saved import import_saved_public_source

from research_workspace_native.acquired_source_parser import parse_acquired_source
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable import sources
from stage1_deliverable.common import canonical, preflight, read_json, sha
from test_stage1_deliverable import HTML, TITLE


class FixtureDeadline:
    """Deterministic boundary checker; cannot stop the synchronous SDK runner."""

    def __init__(self):
        self.expired = False

    def check(self):
        if self.expired:
            raise TimeoutError("authored deadline expired")


class AcquiredSourceParserTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.private_root = Path(tempfile.gettempdir()).resolve()
        preflight(cls.private_root)

    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            prefix="acquired-parser-", dir=self.private_root
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.serial = 0
        self.parser_calls = 0
        network = patch(
            "requests.Session.get", side_effect=AssertionError("unexpected network")
        )
        dns = patch("socket.getaddrinfo", side_effect=AssertionError("unexpected DNS"))
        self.network, self.dns = network.start(), dns.start()
        self.addCleanup(network.stop)
        self.addCleanup(dns.stop)

    def fixture(self, raw=HTML, *, title=TITLE):
        self.serial += 1
        acquisition = self.root / f"acquisition-{self.serial}"
        (acquisition / "raw").mkdir(parents=True)
        raw_path = acquisition / "raw/001-response.html"
        raw_path.write_bytes(raw)
        now = datetime.now(timezone.utc)
        began, ended = (
            (now - timedelta(seconds=2)).isoformat(),
            (now - timedelta(seconds=1)).isoformat(),
        )
        job = sha(
            canonical(
                dict(
                    project="authored-project",
                    input_version="version-one",
                    work_id="work-one",
                    source_attempt="source-one",
                )
            )
        )
        request = dict(
            kind="BoundedPublicSourceRequest",
            schema_version="1.0.0",
            request_id="request-one",
            job_binding_sha256=job,
            source_uri="https://example.org/authored-paper",
            runtime_sha256="1" * 64,
            resolver_sha256="2" * 64,
            deadline_utc=(now + timedelta(seconds=30)).isoformat(),
            total_timeout_seconds=30,
            io_timeout_seconds=5,
            max_http_attempts=4,
            max_response_bytes=65536,
            max_aggregate_bytes=131072,
        )
        attempt = dict(
            sequence=1,
            url=request["source_uri"],
            started_at=began,
            finished_at=ended,
            resolved_addresses=["93.184.216.34"],
            selected_address="93.184.216.34",
            peer_address="93.184.216.34",
            http_request_attempted=True,
            http_status=200,
            content_type="text/html",
            outcome="http-body-complete",
            raw_path="raw/001-response.html",
            raw_sha256=sha(raw),
            body_bytes=len(raw),
            body_complete=True,
            error_code=None,
        )
        receipt = dict(
            kind="PublicSourceAcquisitionReceipt",
            schema_version="1.0.0",
            request=request,
            request_sha256=sha(canonical(request)),
            output_dir=str(acquisition),
            started_at=began,
            finished_at=ended,
            status="completed",
            outcome="http-body-complete",
            final_url=request["source_uri"],
            http_attempts=1,
            http_requests_attempted=1,
            aggregate_bytes=len(raw),
            attempts=[attempt],
            selected_attempt_sequence=1,
            raw_path=attempt["raw_path"],
            raw_sha256=attempt["raw_sha256"],
            content_type=attempt["content_type"],
            body_bytes=len(raw),
            body_complete=True,
        )
        path = acquisition / "public-source-acquisition.json"
        path.write_bytes(canonical(receipt) + b"\n")
        return dict(
            materials_root=self.root,
            acquisition_receipt_path=path,
            expected_acquisition_sha256=sha(path.read_bytes()),
            expected_request=deepcopy(request),
            expected_job_binding_sha256=job,
            runtime_sha256="1" * 64,
            expected_identity=dict(doi="", title=title),
            parser_output_dir=self.root / f"parser-{self.serial}",
            parse_admission=True,
            deadline=FixtureDeadline(),
            parser_runner=self.runner,
        ), receipt

    def rehash(self, arguments, receipt):
        path = arguments["acquisition_receipt_path"]
        path.write_bytes(canonical(receipt) + b"\n")
        arguments["expected_acquisition_sha256"] = sha(path.read_bytes())

    def runner(self, *, input_manifest, expected_manifest_sha256, output_dir, deadline):
        self.parser_calls += 1
        deadline.check()
        self.assertTrue((input_manifest.parent / "source-parse-intent.json").is_file())
        self.assertEqual(sha(input_manifest.read_bytes()), expected_manifest_sha256)
        return import_saved_public_source(
            input_manifest=input_manifest,
            expected_manifest_sha256=expected_manifest_sha256,
            output_dir=output_dir,
        )

    def inventory(self):
        return {
            path.relative_to(self.root).as_posix(): sha(path.read_bytes())
            for path in self.root.rglob("*")
            if path.is_file()
        }

    def test_actual_sdk_import_preserves_dual_receipts_original_bytes_and_no_http_claim(
        self,
    ):
        arguments, acquired = self.fixture()
        path = arguments["acquisition_receipt_path"]
        original_receipt, original_body = (
            path.read_bytes(),
            (path.parent / acquired["raw_path"]).read_bytes(),
        )
        result = parse_acquired_source(**arguments)
        bundle = result["bundle"]
        self.assertEqual(read_json(result["bundle_path"]), bundle)
        self.assertEqual(
            sha(Path(result["bundle_path"]).read_bytes()), result["bundle_sha256"]
        )
        self.assertEqual(bundle["kind"], "SourceAcquisitionParseBundle")
        self.assertEqual(bundle["acquisition"]["http_status"], 200)
        sdk = read_json(self.root / bundle["parser"]["receipt_path"])
        self.assertEqual(sdk["request"]["operation"], "source import-saved")
        self.assertEqual(sdk["status"], "available")
        self.assertEqual(
            [item["http_status"] for item in sdk["attempts"]], [None, None]
        )
        self.assertIs(
            sdk["diagnostics"]["saved_import"]["original_http_acquisition_verified"],
            False,
        )
        self.assertEqual(sdk["source_version"], "sha256:" + acquired["raw_sha256"])
        self.assertEqual(path.read_bytes(), original_receipt)
        self.assertEqual(
            (path.parent / acquired["raw_path"]).read_bytes(), original_body
        )
        self.assertEqual(self.parser_calls, 1)
        self.network.assert_not_called()
        self.dns.assert_not_called()
        with self.assertRaisesRegex(
            SessionApiError, "fresh-output|required|existing-intent"
        ):
            parse_acquired_source(**arguments)
        self.assertEqual(self.parser_calls, 1)

    def test_literal_admission_unavailable_runner_and_expired_owner_refuse_without_writes(
        self,
    ):
        for admission in (False, None, 1, "approved"):
            arguments, _ = self.fixture()
            arguments["parse_admission"] = admission
            before = self.inventory()
            with self.assertRaisesRegex(SessionApiError, "admission-required"):
                parse_acquired_source(**arguments)
            self.assertEqual(before, self.inventory())
        for failure in ("runner", "deadline", "owner"):
            arguments, _ = self.fixture()
            if failure == "runner":
                arguments["parser_runner"] = None
            elif failure == "deadline":
                arguments["deadline"].expired = True
            else:
                arguments["check_current"] = Mock(side_effect=ValueError("owner lost"))
            before = self.inventory()
            with self.assertRaises((SessionApiError, TimeoutError, ValueError)):
                parse_acquired_source(**arguments)
            self.assertEqual(before, self.inventory())
        self.assertEqual(self.parser_calls, 0)

    def test_failed_partial_and_interrupted_acquisition_never_invokes_parser(self):
        for status, outcome, http in (
            ("completed", "http-error", 503),
            ("completed", "rate-limited", 429),
            ("completed", "not-found", 404),
            ("interrupted", "timeout", None),
            ("completed", "body-bound-reached", 200),
        ):
            with self.subTest(outcome=outcome):
                arguments, receipt = self.fixture(
                    raw=b"authored saved failure or partial prefix"
                )
                receipt.update(
                    status=status,
                    outcome=outcome,
                    raw_path=None,
                    raw_sha256=None,
                    body_bytes=0,
                    body_complete=False,
                    selected_attempt_sequence=None,
                )
                receipt["attempts"][0].update(
                    outcome=outcome, http_status=http, body_complete=False
                )
                self.rehash(arguments, receipt)
                before = self.inventory()
                with self.assertRaisesRegex(
                    SessionApiError, "complete-acquisition-required"
                ):
                    parse_acquired_source(**arguments)
                self.assertEqual(before, self.inventory())
        self.assertEqual(self.parser_calls, 0)

    def test_job_request_runtime_and_original_raw_hash_mismatch_refuse_before_parser(
        self,
    ):
        for changed in ("receipt-sha", "job", "runtime", "request", "raw"):
            arguments, receipt = self.fixture()
            if changed == "receipt-sha":
                arguments["expected_acquisition_sha256"] = "3" * 64
            elif changed == "job":
                arguments["expected_job_binding_sha256"] = "3" * 64
            elif changed == "runtime":
                arguments["runtime_sha256"] = "3" * 64
            elif changed == "request":
                arguments["expected_request"]["request_id"] = "other-request"
            else:
                (
                    arguments["acquisition_receipt_path"].parent / receipt["raw_path"]
                ).write_bytes(b"changed authored bytes")
            before = self.inventory()
            with self.assertRaises((SessionApiError, ValueError)):
                parse_acquired_source(**arguments)
            self.assertEqual(before, self.inventory())
        self.assertEqual(self.parser_calls, 0)

    def test_failure_sidecar_and_overlong_acquisition_refuse_before_parser(self):
        arguments, receipt = self.fixture()
        acquisition = arguments["acquisition_receipt_path"].parent
        (acquisition / "public-source-acquisition-failure.json").write_bytes(
            b'{"phase":"post-receipt-publication"}\n'
        )
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "acquisition-failure-observed"):
            parse_acquired_source(**arguments)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.parser_calls, 0)

        arguments, receipt = self.fixture()
        began = datetime.fromisoformat(receipt["started_at"])
        receipt["started_at"] = (began - timedelta(seconds=31)).isoformat()
        receipt["attempts"][0]["started_at"] = receipt["started_at"]
        self.rehash(arguments, receipt)
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "time-order"):
            parse_acquired_source(**arguments)
        self.assertEqual(self.inventory(), before)
        self.assertEqual(self.parser_calls, 0)

        arguments, receipt = self.fixture()
        original = arguments["acquisition_receipt_path"].read_bytes()

        def late_failure(**kwargs):
            result = self.runner(**kwargs)
            failure = arguments["acquisition_receipt_path"].parent
            (failure / "public-source-acquisition-failure.json").write_bytes(b"{}\n")
            return result

        arguments["parser_runner"] = late_failure
        with self.assertRaisesRegex(SessionApiError, "acquisition-failure-observed"):
            parse_acquired_source(**arguments)
        self.assertEqual(arguments["acquisition_receipt_path"].read_bytes(), original)
        self.assertEqual(self.parser_calls, 1)

    def test_rehashed_count_size_peer_and_selected_hop_tamper_refuse(self):
        for changed in ("count", "size", "bound", "peer", "status", "sequence", "uri"):
            arguments, receipt = self.fixture()
            if changed == "count":
                receipt["http_requests_attempted"] = 2
            elif changed == "size":
                receipt["attempts"][0]["body_bytes"] += 1
            elif changed == "bound":
                receipt["request"]["max_response_bytes"] = 32
                receipt["request_sha256"] = sha(canonical(receipt["request"]))
                arguments["expected_request"] = deepcopy(receipt["request"])
            elif changed == "peer":
                receipt["attempts"][0]["peer_address"] = "127.0.0.1"
            elif changed == "status":
                receipt["attempts"][0]["http_status"] = 503
            elif changed == "sequence":
                receipt["selected_attempt_sequence"] = 2
            else:
                receipt["attempts"][0]["url"] = "https://example.org/other"
            self.rehash(arguments, receipt)
            before = self.inventory()
            with self.assertRaises((SessionApiError, ValueError)):
                parse_acquired_source(**arguments)
            self.assertEqual(before, self.inventory())
        self.assertEqual(self.parser_calls, 0)

    def test_hardlink_private_output_and_existing_manifest_are_not_adopted(self):
        arguments, receipt = self.fixture()
        raw = arguments["acquisition_receipt_path"].parent / receipt["raw_path"]
        os.link(raw, raw.with_name("authored-alias.html"))
        with self.assertRaisesRegex(SessionApiError, "file-invalid"):
            parse_acquired_source(**arguments)
        arguments, _ = self.fixture()
        arguments["parser_output_dir"] = (
            arguments["acquisition_receipt_path"].parent / "parser"
        )
        with self.assertRaisesRegex(SessionApiError, "fresh-output-required"):
            parse_acquired_source(**arguments)
        arguments, _ = self.fixture()
        manifest = (
            arguments["acquisition_receipt_path"].parent / "source-parse-input.json"
        )
        manifest.write_bytes(b"previous failed attempt remains")
        before = self.inventory()
        with self.assertRaisesRegex(SessionApiError, "existing-intent-refused"):
            parse_acquired_source(**arguments)
        self.assertEqual(before, self.inventory())
        self.assertEqual(self.parser_calls, 0)

    def test_late_parser_and_owner_loss_preserve_intent_without_success_or_replay(self):
        for loss in ("deadline", "owner"):
            arguments, _ = self.fixture()
            lost = []

            def current():
                if lost:
                    raise ValueError("owner lost")

            if loss == "owner":
                arguments["check_current"] = current

            def late(**kwargs):
                result = self.runner(**kwargs)
                if loss == "deadline":
                    arguments["deadline"].expired = True
                else:
                    lost.append(True)
                return result

            arguments["parser_runner"] = late
            with self.assertRaises((TimeoutError, ValueError)):
                parse_acquired_source(**arguments)
            self.assertTrue(
                (
                    arguments["acquisition_receipt_path"].parent
                    / "source-parse-intent.json"
                ).is_file()
            )
            self.assertTrue(
                (arguments["parser_output_dir"] / "source-fetch-result.json").is_file()
            )
            self.assertFalse(
                (
                    arguments["parser_output_dir"]
                    / "source-acquisition-parse-bundle.json"
                ).exists()
            )
            count = self.parser_calls
            arguments.update(
                deadline=FixtureDeadline(),
                check_current=None,
                parser_output_dir=self.root / f"fresh-{loss}",
            )
            with self.assertRaisesRegex(SessionApiError, "existing-intent-refused"):
                parse_acquired_source(**arguments)
            self.assertEqual(self.parser_calls, count)

    def test_sdk_http_attestation_request_or_bytes_cannot_be_forged_by_rehash(self):
        for changed in ("http-verified", "operation", "doi", "returned", "artifact"):
            arguments, _ = self.fixture()

            def forged(**kwargs):
                actual = self.runner(**kwargs).to_dict()
                path = kwargs["output_dir"] / "source-fetch-result.json"
                if changed == "http-verified":
                    actual["diagnostics"]["saved_import"][
                        "original_http_acquisition_verified"
                    ] = True
                elif changed == "operation":
                    actual["request"]["operation"] = "source fetch"
                elif changed == "doi":
                    actual["request"]["doi"] = "10.1234/other"
                elif changed == "returned":
                    actual["status"] = "parse-error"
                    return actual
                else:
                    Path(actual["raw_path"]).write_bytes(b"changed SDK raw")
                actual["receipt_sha256"] = sources.receipt_digest(actual)
                path.write_bytes(canonical(actual) + b"\n")
                return actual

            arguments["parser_runner"] = forged
            with self.assertRaises((SessionApiError, ValueError)):
                parse_acquired_source(**arguments)
            self.assertFalse(
                (
                    arguments["parser_output_dir"]
                    / "source-acquisition-parse-bundle.json"
                ).exists()
            )

    def test_parser_identity_failure_and_original_acquisition_drift_remain_visible(
        self,
    ):
        arguments, _ = self.fixture(title="Different authored work and identity")
        result = parse_acquired_source(**arguments)
        self.assertEqual(result["bundle"]["parser"]["status"], "identity-mismatch")
        self.assertFalse(
            result["bundle"]["parser"]["original_http_acquisition_verified"]
        )
        arguments, receipt = self.fixture()

        def drift(**kwargs):
            result = self.runner(**kwargs)
            (
                arguments["acquisition_receipt_path"].parent / receipt["raw_path"]
            ).write_bytes(b"changed after parser")
            return result

        arguments["parser_runner"] = drift
        with self.assertRaisesRegex(SessionApiError, "file-hash-differs"):
            parse_acquired_source(**arguments)
        self.assertFalse(
            (
                arguments["parser_output_dir"] / "source-acquisition-parse-bundle.json"
            ).exists()
        )


if __name__ == "__main__":
    unittest.main()
