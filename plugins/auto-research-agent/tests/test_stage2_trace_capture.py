"""Tests for receipt-bound post-execution trace capture sealing."""

import hashlib
import json
import os
from pathlib import Path
import sys
import unittest
from unittest.mock import patch


CLI = Path(__file__).resolve().parents[1] / "cli"
sys.path.insert(0, str(CLI))

from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live import native, trace_capture  # noqa: E402
from native_trace_fixture import NativeTraceFixture  # noqa: E402
import test_stage2_live_native as native_fixture  # noqa: E402


class TraceCaptureTests(unittest.TestCase):
    def setUp(self):
        self.native_case = native_fixture.NativeCaptureTests(methodName="runTest")
        self.native_case.setUp()
        self.addCleanup(self.native_case.tearDown)
        self.root = self.native_case.root.resolve()
        self.output = self.native_case.output.resolve()
        self.workspace = self.native_case.workspace.resolve()
        self.seal = self.root / "seal"
        self.capture = self._capture(self.output)
        self.trace, self.inventory, self.trace_receipt = self._trace()

    def _runner(self, thread):
        def run(command, **kwargs):
            result = self.native_case.successful_runner(command, **kwargs)
            return native_fixture.Result(
                result.stdout.replace(b"thread-1", thread.encode()),
                result.stderr,
                result.returncode,
            )

        return run

    def _capture(self, output, *, model="model", thread="root-thread"):
        return native.capture_native(
            **self.native_case.args(output_dir=output, model=model),
            process_runner=self._runner(thread),
        )

    def _trace(self, state="complete"):
        case = NativeTraceFixture(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        case._inference("i1", "r1")
        if state != "complete":
            case.events[-1]["payload"]["type"] = "inference_failed"
            case._inference("i2", "r2")
            case.events.pop()
            for number, row in enumerate(case.events, 1):
                row["seq"] = number
        case._finish()
        receipt, digest = case._write()
        return case.root, receipt, digest

    def _args(self, **updates):
        values = {
            "capture_dir": self.output,
            "capture_receipt": self.capture["record_sha256_receipt"],
            "trace_root": self.trace,
            "inventory_receipt": self.inventory,
            "trace_receipt_sha256": self.trace_receipt,
            "output_dir": self.seal,
        }
        values.update(updates)
        return values

    def _seal(self, **updates):
        return trace_capture._seal_trace_capture(
            **self._args(**updates), allow_injected_test_capture=True
        )

    def _rewrite_manifest(self, mutate):
        path = self.seal / "seal.json"
        value = json.loads(path.read_text(encoding="utf-8"))
        mutate(value)
        encoded = trace_capture._manifest_bytes(value)
        path.write_bytes(encoded)
        return hashlib.sha256(encoded).hexdigest()

    def _verify(self, receipt):
        return trace_capture.verify_trace_capture(
            self.seal, receipt, self.output, self.capture["record_sha256_receipt"]
        )

    def test_success_verification_and_resume_never_copy_or_promote(self):
        with self.assertRaisesRegex(native.CaptureError, "cannot be verified"):
            trace_capture.seal_trace_capture(**self._args())

        sealed = self._seal()
        self.assertFalse(sealed["formal_ready"])
        self.assertEqual(sealed["evidence_class"], "receipt-bound-content-link")
        self.assertTrue(sealed["capture"]["injected_test_capture"])
        verified = self._verify(sealed["seal_receipt"])
        self.assertEqual(verified["observation"], sealed["observation"])
        before = (self.seal / "seal.json").read_bytes()
        with patch.object(trace_capture, "_write_trace", side_effect=AssertionError):
            resumed = self._seal(resume=True, seal_receipt=sealed["seal_receipt"])
        self.assertEqual(resumed["seal_receipt"], sealed["seal_receipt"])
        self.assertEqual((self.seal / "seal.json").read_bytes(), before)

    def test_cross_capture_wrong_root_and_model_are_rejected(self):
        sealed = self._seal()
        other_dir = self.root / "capture-other"
        other = self._capture(other_dir)
        with self.assertRaisesRegex(Stage2Error, "capture-receipt-mismatch"):
            trace_capture.verify_trace_capture(
                self.seal,
                sealed["seal_receipt"],
                other_dir,
                other["record_sha256_receipt"],
            )

        for label, model, thread, error in (
            ("root", "model", "other-root", "root-mismatch"),
            ("model", "other-model", "root-thread", "model-mismatch"),
        ):
            with self.subTest(label=label):
                capture_dir = self.root / f"capture-{label}"
                capture = self._capture(capture_dir, model=model, thread=thread)
                with self.assertRaisesRegex(Stage2Error, error):
                    self._seal(
                        capture_dir=capture_dir,
                        capture_receipt=capture["record_sha256_receipt"],
                        output_dir=self.root / f"seal-{label}",
                    )

    def test_failed_and_incomplete_inferences_remain_unknown(self):
        trace, receipt, digest = self._trace("unknown")
        sealed = self._seal(
            trace_root=trace,
            inventory_receipt=receipt,
            trace_receipt_sha256=digest,
            output_dir=self.root / "seal-unknown",
        )
        observation = sealed["observation"]
        self.assertIsNone(observation["token_usage_totals"])
        self.assertEqual(observation["counts"]["incomplete_inferences"], 1)
        self.assertEqual(observation["counts"]["failures"], 1)
        self.assertIn("token-usage-unknown:i1", observation["blockers"])
        self.assertIn("inference-terminal-missing:i2", observation["blockers"])

    def test_tampering_extra_files_and_credential_names_reject(self):
        sealed = self._seal()
        payload = next((self.seal / "trace/payloads").iterdir())
        payload.write_bytes(payload.read_bytes() + b" ")
        with self.assertRaisesRegex(Stage2Error, "file-hash-mismatch"):
            self._verify(sealed["seal_receipt"])

        tampered = dict(self.inventory)
        source = next(name for name in tampered if name.startswith("payloads/"))
        (self.trace / source).write_bytes((self.trace / source).read_bytes() + b" ")
        tampered[source] = hashlib.sha256(
            (self.trace / source).read_bytes()
        ).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "receipt-hash-mismatch"):
            self._seal(
                inventory_receipt=tampered,
                output_dir=self.root / "seal-rehashed",
            )

        trace, receipt, _ = self._trace()
        credential = trace / "payloads/auth.json"
        credential.write_bytes(b"{}")
        receipt["payloads/auth.json"] = hashlib.sha256(b"{}").hexdigest()
        with self.assertRaisesRegex(Stage2Error, "credential-like-trace-file"):
            self._seal(
                trace_root=trace,
                inventory_receipt=receipt,
                trace_receipt_sha256=canonical_hash(receipt),
                output_dir=self.root / "seal-credential",
            )

    def test_output_isolated_and_extra_or_omitted_files_reject(self):
        for output in (
            self.output / "nested",
            self.trace / "nested",
            self.workspace / "nested",
        ):
            with (
                self.subTest(output=output),
                self.assertRaisesRegex(Stage2Error, "seal-output-overlap"),
            ):
                self._seal(output_dir=output)

        sealed = self._seal()
        (self.seal / "extra.json").write_text("{}", encoding="utf-8")
        with self.assertRaisesRegex(Stage2Error, "seal-inventory-mismatch"):
            self._verify(sealed["seal_receipt"])
        (self.seal / "extra.json").unlink()
        next((self.seal / "trace/payloads").iterdir()).unlink()
        with self.assertRaisesRegex(Stage2Error, "inventory-mismatch"):
            self._verify(sealed["seal_receipt"])

    def test_control_file_and_malformed_bindings_fail_closed(self):
        for receipt in (None, [], {}, {1: "0" * 64}):
            with self.subTest(receipt=receipt), self.assertRaises(Stage2Error):
                self._seal(
                    inventory_receipt=receipt,
                    output_dir=self.root / f"bad-receipt-{type(receipt).__name__}",
                )

        self._seal()
        changed_receipt = self._rewrite_manifest(
            lambda value: value["capture"].update(injected_test_capture=False)
        )
        with self.assertRaisesRegex(Stage2Error, "injected-capture-flag-mismatch"):
            self._verify(changed_receipt)

        (self.seal / "seal.json").write_bytes(b"x" * (trace_capture.MAX_FILE_BYTES + 1))
        oversized = hashlib.sha256((self.seal / "seal.json").read_bytes()).hexdigest()
        with self.assertRaisesRegex(Stage2Error, "seal-file-size-limit"):
            self._verify(oversized)

    def test_large_valid_control_is_buffered_and_fully_replayed(self):
        self._seal()
        marker = "large-control-" + "x" * (128 * 1024)
        receipt = self._rewrite_manifest(
            lambda value: value["limitations"].append(marker)
        )
        verified = self._verify(receipt)
        self.assertEqual(verified["limitations"][-1], marker)
        self.assertGreater((self.seal / "seal.json").stat().st_size, 64 * 1024)

    def test_extra_directory_and_changed_control_identity_reject_before_replay(self):
        sealed = self._seal()
        (self.seal / "unexpected/deep").mkdir(parents=True)
        with (
            patch.object(
                Path, "read_bytes", side_effect=AssertionError("no recursion")
            ),
            self.assertRaisesRegex(Stage2Error, "seal-inventory-mismatch"),
        ):
            self._verify(sealed["seal_receipt"])
        (self.seal / "unexpected/deep").rmdir()
        (self.seal / "unexpected").rmdir()

        real_fstat = os.fstat
        calls = 0

        def changed(descriptor):
            nonlocal calls
            calls += 1
            status = real_fstat(descriptor)
            if (
                calls == 3
            ):  # opened-kind check, before-read identity, after-read identity
                fields = list(status)
                fields[6] += 1
                return os.stat_result(fields)
            return status

        with (
            patch.object(trace_capture.os, "fstat", side_effect=changed),
            self.assertRaisesRegex(Stage2Error, "seal-control-file-changed"),
        ):
            self._verify(sealed["seal_receipt"])

    def test_boolean_integer_observation_aliases_fail_rehashed_seal(self):
        self._seal()
        original = (self.seal / "seal.json").read_bytes()
        for field in ("formal_ready", "inferences"):
            (self.seal / "seal.json").write_bytes(original)

            def mutate(value):
                if field == "formal_ready":
                    value["observation"][field] = 0
                else:
                    value["observation"]["counts"][field] = True

            receipt = self._rewrite_manifest(mutate)
            with (
                self.subTest(field=field),
                self.assertRaisesRegex(Stage2Error, "observation-mismatch"),
            ):
                self._verify(receipt)

    def test_retained_output_handles_prevent_workspace_write_redirection(self):
        directory = trace_capture.SealDirectory
        original_write = directory.write
        before = sorted(p.name for p in self.workspace.iterdir())
        attacked = False

        def write(bound, name, value):
            nonlocal attacked
            if bound.path.name == "payloads" and not attacked:
                attacked = True
                if os.name == "nt":
                    with self.assertRaises(OSError):
                        (self.seal / "trace").rename(self.seal / "held-trace")
                else:
                    (self.seal / "trace").rename(self.seal / "held-trace")
                    (self.seal / "trace").symlink_to(
                        self.workspace, target_is_directory=True
                    )
            return original_write(bound, name, value)

        with patch.object(directory, "write", write):
            if os.name == "nt":
                self._seal()
            else:
                with self.assertRaises(Stage2Error):
                    self._seal()
        self.assertTrue(attacked)
        self.assertEqual(sorted(p.name for p in self.workspace.iterdir()), before)


if __name__ == "__main__":
    unittest.main()
