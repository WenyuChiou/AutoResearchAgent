"""Synthetic capture-time tests; no model or tool is dispatched."""

import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error  # noqa: E402
from stage2_live.no_tool_trace_capture import (  # noqa: E402
    NoToolTraceCaptureFailure,
    begin_no_tool_trace_capture,
    finish_no_tool_trace_capture,
)
from stage2_live.no_tool_trace_evidence import (  # noqa: E402
    verify_no_tool_trace_evidence as real_verify,
)


def _write(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(json.dumps(value, sort_keys=True).encode() + b"\n")


class NoToolTraceCaptureTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.base = Path(temporary.name).resolve()
        self.telemetry = self.base / "telemetry"
        self.telemetry.mkdir()
        self.output = self.base / "output"
        self.expected = {
            "model": "synthetic-model",
            "reasoning": "medium",
            "sandbox_mode": "read-only",
            "approval_policy": "never",
        }
        self.roots = {}

    def archive(self, unit, roots):
        archive = self.base / f"{unit}.model-call"
        archive.mkdir()
        config, fingerprint = (
            {"model": "synthetic-model", "reasoning": "medium"},
            unit[0] * 64,
        )
        _write(
            archive / "request.json",
            {
                "archive_version": "3.1.0",
                "label": unit,
                "config": config,
                "request_fingerprint_sha256": fingerprint,
            },
        )
        records, stdouts = [], []
        for number, root in enumerate(roots, 1):
            stdout = (
                json.dumps({"type": "thread.started", "thread_id": root}) + "\n"
            ).encode()
            stdout_path = archive / f"attempt-{number:02d}.stdout.jsonl"
            stdout_path.write_bytes(stdout)
            record_path = archive / f"attempt-{number:02d}.record.json"
            completed = number == len(roots)
            _write(
                record_path,
                {
                    "archive_version": "3.1.0",
                    "attempt": number,
                    "request_fingerprint_sha256": fingerprint,
                    "config": config,
                    "generation_status": "completed" if completed else "failed",
                    "failure_class": None if completed else "transient-transport",
                    "files": {
                        "stdout": {
                            "path": stdout_path.name,
                            "sha256": hashlib.sha256(stdout).hexdigest(),
                        }
                    },
                },
            )
            records.append(record_path)
            stdouts.append(stdout_path)
        return {
            "execution_status": "native-replayed",
            "call_archive": str(archive),
            "request_fingerprint_sha256": fingerprint,
            "config": config,
            "attempt": len(roots),
            "attempt_record_sha256": hashlib.sha256(
                records[-1].read_bytes()
            ).hexdigest(),
            "stdout_sha256": hashlib.sha256(stdouts[-1].read_bytes()).hexdigest(),
        }

    def trace(self, name, root, *, complete=True):
        trace = self.telemetry / name
        _write(
            trace / "payloads/config.json",
            {
                "thread_id": root,
                "model": "synthetic-model",
                "reasoning_effort": "medium",
                "sandbox_policy": {"type": "read-only"},
                "approval_policy": "never",
            },
        )
        _write(
            trace / "trace.jsonl",
            {
                "payload": {
                    "type": "protocol_event_observed",
                    "event_type": "session_configured",
                    "event_payload": {
                        "path": "payloads/config.json",
                        "raw_payload_id": "x",
                        "kind": {"type": "test"},
                    },
                }
            },
        )
        (trace / "manifest.json").write_bytes(b"{}\n")
        _write(
            trace / "payloads/request.json",
            {"model": "synthetic-model", "input": [], "tools": []},
        )
        self.roots[name] = (root, complete)
        return trace

    def observation(self, trace, *_args):
        root, complete = self.roots[trace.name]
        usage = {
            "input_tokens": 8,
            "cached_input_tokens": 3,
            "cache_write_input_tokens": 0,
            "output_tokens": 2,
            "reasoning_output_tokens": 1,
            "total_tokens": 10,
        }
        return {
            "root_thread_id": root,
            "inferences": [
                {
                    "status": "inference_completed",
                    "token_usage": usage,
                    "request_ref": "payloads/request.json",
                    "tools_inherited": False,
                }
            ]
            if complete
            else [],
            "threads": [
                {
                    "thread_id": root,
                    "terminal_status": "completed" if complete else "failed",
                    "offered_tools": {"definitions": []},
                }
            ],
            "counts": {"tool_calls": 0},
            "blockers": [] if complete else ["rollout-not-completed"],
        }

    def finish(self, token, provenances, observer=None, verifier=None):
        with (
            patch(
                "stage2_live.no_tool_trace_capture.inspect_native_trace",
                side_effect=observer or self.observation,
            ),
            patch(
                "stage2_live.no_tool_trace_evidence.inspect_native_trace",
                side_effect=observer or self.observation,
            ),
            patch(
                "stage2_live.no_tool_trace_capture.verify_no_tool_trace_evidence",
                side_effect=verifier or real_verify,
            ),
        ):
            return finish_no_tool_trace_capture(
                token, provenances, expected_config=self.expected
            )

    def test_completed_and_multi_attempt_units_are_copied_sealed_and_reverified(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenances = {
            "initial": self.archive("initial", ("retry-root", "initial-root")),
            "correction": self.archive("correction", ("correction-root",)),
        }
        self.trace("trace-a", "retry-root", complete=False)
        self.trace("trace-b", "initial-root")
        self.trace("trace-c", "correction-root")
        result = self.finish(token, provenances)
        self.assertEqual(set(result["units"]), {"initial", "correction"})
        self.assertEqual((result["new_model_calls"], result["new_tool_calls"]), (0, 0))
        self.assertEqual(len(result["units"]["initial"]["proof"]["attempts"]), 2)
        for unit in result["units"].values():
            self.assertTrue(Path(unit["seal_path"]).is_file())

    def test_existing_output_and_preexisting_trace_cannot_be_resealed(self):
        self.output.mkdir()
        with self.assertRaisesRegex(Stage2Error, "output-already-exists"):
            begin_no_tool_trace_capture(self.output, self.telemetry)
        self.output.rmdir()
        self.trace("trace-old", "old-root")
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenance = self.archive("initial", ("old-root",))
        self.trace("trace-new", "foreign-root")
        with self.assertRaisesRegex(Stage2Error, "foreign-or-duplicate-new-root"):
            self.finish(token, {"initial": provenance})
        self.assertFalse(self.output.exists())

    def test_missing_extra_duplicate_and_foreign_new_roots_reject_before_output(self):
        for roots, emitted, error in (
            (("wanted",), (), "new-trace-missing"),
            (
                ("wanted",),
                (("trace-a", "wanted"), ("trace-b", "extra")),
                "foreign-or-duplicate-new-root",
            ),
            (
                ("one", "two"),
                (("trace-a", "one"), ("trace-b", "one")),
                "foreign-or-duplicate-new-root",
            ),
        ):
            case = NoToolTraceCaptureTests(methodName="runTest")
            case.setUp()
            self.addCleanup(case.doCleanups)
            token = begin_no_tool_trace_capture(case.output, case.telemetry)
            provenance = case.archive("initial", roots)
            for name, root in emitted:
                case.trace(name, root, complete=root == roots[-1])
            with self.subTest(error=error), self.assertRaisesRegex(Stage2Error, error):
                case.finish(token, {"initial": provenance})
            self.assertFalse(case.output.exists())

    def test_original_change_and_copied_change_are_refused(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenance = self.archive("initial", ("wanted",))
        trace = self.trace("trace-a", "wanted")
        original = self.observation

        def mutate_original(path, *args):
            value = original(path, *args)
            (trace / "manifest.json").write_bytes(b"changed\n")
            return value

        with self.assertRaisesRegex(Stage2Error, "original-trace-changed"):
            self.finish(token, {"initial": provenance}, observer=mutate_original)
        self.assertTrue(self.output.exists())

        case = NoToolTraceCaptureTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        token = begin_no_tool_trace_capture(case.output, case.telemetry)
        provenance = case.archive("initial", ("wanted",))
        case.trace("trace-a", "wanted")

        def mutate_copy(prov, root, seal, digest, **kwargs):
            (Path(root) / "trace-a/manifest.json").write_bytes(b"changed\n")
            return real_verify(prov, root, seal, digest, **kwargs)

        with self.assertRaisesRegex(Stage2Error, "hash-mismatch"):
            case.finish(token, {"initial": provenance}, verifier=mutate_copy)

    def test_special_unit_components_reject_before_output(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenance = self.archive("initial", ("wanted",))
        for unit in (
            ".",
            "..",
            "../outside",
            "/absolute",
            "a/b",
            "first.",
            "CON",
            "con.txt",
            "LPT1",
            "COM0",
        ):
            with (
                self.subTest(unit=unit),
                self.assertRaisesRegex(Stage2Error, "unit-name-invalid"),
            ):
                self.finish(token, {unit: provenance})
        self.assertFalse(self.output.exists())

    def test_case_aliases_reject_before_output_on_every_platform(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        one = self.archive("one", ("one-root",))
        two = self.archive("two", ("two-root",))
        with self.assertRaisesRegex(Stage2Error, "unit-directory-alias"):
            self.finish(token, {"First": one, "first": two})
        self.assertFalse(self.output.exists())

    def test_size_limit_is_checked_before_read_and_reads_are_bounded(self):
        from stage2_live import no_tool_trace_capture as capture

        path = self.base / "large"
        path.write_bytes(b"x" * 1024)
        with (
            patch.object(capture, "MAX_FILE_BYTES", 8),
            patch.object(Path, "open") as opened,
        ):
            with self.assertRaisesRegex(Stage2Error, "trace-size-limit"):
                capture._bounded_bytes(path)
            opened.assert_not_called()
        path.write_bytes(b"small")
        real_open = Path.open
        requests = []

        class Reader:
            def __enter__(self):
                self.stream = real_open(path, "rb")
                return self

            def __exit__(self, *args):
                self.stream.close()

            def read(self, size):
                requests.append(size)
                return self.stream.read(size)

        with (
            patch.object(capture, "MAX_FILE_BYTES", 8),
            patch.object(Path, "open", return_value=Reader()),
        ):
            self.assertEqual(capture._bounded_bytes(path), b"small")
        self.assertEqual(requests, [9])

    def test_seal_failure_retains_original_hash_and_prior_completed_results(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenances = {
            "first": self.archive("first", ("one",)),
            "second": self.archive("second", ("two",)),
        }
        self.trace("trace-a", "one")
        self.trace("trace-b", "two")
        calls = []

        def fail_second(*args, **kwargs):
            calls.append(args[0])
            if len(calls) == 2:
                raise Stage2Error("verification failed")
            return real_verify(*args, **kwargs)

        with self.assertRaises(NoToolTraceCaptureFailure) as raised:
            self.finish(token, provenances, verifier=fail_second)
        error = raised.exception
        self.assertIsInstance(error.__cause__, Stage2Error)
        self.assertEqual(set(error.retained_seal_receipts), {"first", "second"})
        self.assertEqual(set(error.completed_units), {"first"})
        for receipt in error.retained_seal_receipts.values():
            raw = Path(receipt["seal_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt["seal_sha256"])

    def test_first_verification_failure_retains_later_correction_seal(self):
        token = begin_no_tool_trace_capture(self.output, self.telemetry)
        provenances = {
            "first": self.archive("first", ("one",)),
            "second": self.archive("second", ("two",)),
        }
        self.trace("trace-a", "one")
        self.trace("trace-b", "two")

        def fail_first(*args, **kwargs):
            raise Stage2Error("first unit verification failed")

        with self.assertRaises(NoToolTraceCaptureFailure) as raised:
            self.finish(token, provenances, verifier=fail_first)
        self.assertEqual(
            set(raised.exception.retained_seal_receipts), {"first", "second"}
        )
        self.assertEqual(raised.exception.completed_units, {})
        for receipt in raised.exception.retained_seal_receipts.values():
            raw = Path(receipt["seal_path"]).read_bytes()
            self.assertEqual(hashlib.sha256(raw).hexdigest(), receipt["seal_sha256"])


if __name__ == "__main__":
    unittest.main()
