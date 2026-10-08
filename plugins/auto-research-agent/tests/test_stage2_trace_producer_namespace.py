import copy
import hashlib
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

TESTS = Path(__file__).resolve().parent
CLI = TESTS.parent / "cli"
sys.path[:0] = [str(CLI), str(TESTS)]

from stage2_common import Stage2Error  # noqa: E402
from stage2_live import trace_producer  # noqa: E402
import test_stage2_trace_producer as fixture  # noqa: E402


class TraceProducerNamespaceTests(unittest.TestCase):
    def fixture(self):
        case = fixture.TraceProducerTests(methodName="runTest")
        case.setUp()
        self.addCleanup(case.doCleanups)
        return case

    @staticmethod
    def binding(case):
        scope_file = case.home / "native-namespace.json"
        scope_file.write_bytes(b'{"synthetic":true}\n')
        return {
            "path": str(scope_file),
            "sha256": hashlib.sha256(scope_file.read_bytes()).hexdigest(),
            "scope": {
                "codex": str(case.codex),
                "home": str(case.home),
                "workspace": str(case.workspace),
                "capture_root": str(case.root),
            },
            "dispatcher_sha256": "d" * 64,
        }

    @staticmethod
    def wrap(command, binding):
        return command if binding is None else ["bwrap", "--"] + command

    @staticmethod
    def inventory(request):
        profile = request["codex_profile_config"]
        return {
            "kind": "Stage2RuntimeObservation",
            "schema_version": "2.0.0",
            "status": "observed",
            "binding": {
                "runtime_sha256": request["codex_runtime_sha256"],
                "profile_config_sha256": profile["sha256"] if profile else None,
                "workspace": request["workspace"],
                "codex_home": request["codex_home"],
                "thread_id": None,
                "native_namespace": copy.deepcopy(request["native_namespace"]),
            },
            "record_sha256_receipt": "a" * 64,
            "evidence_class": "synthetic-test-only",
            "formal_ready": False,
        }

    def test_legacy_request_and_observation_keep_omitted_shape(self):
        case = self.fixture()
        request = trace_producer._request(case._args())
        self.assertNotIn("timeout_seconds", request)
        self.assertNotIn("native_namespace", request)
        profile = request["codex_profile_config"]
        binding = {
            "runtime_sha256": request["codex_runtime_sha256"],
            "profile_config_sha256": profile["sha256"],
            "workspace": request["workspace"],
            "codex_home": request["codex_home"],
            "thread_id": None,
        }
        trace_producer._observation_binding({"binding": binding}, request)
        with self.assertRaisesRegex(Stage2Error, "observation-binding-mismatch"):
            trace_producer._observation_binding(
                {"binding": {**binding, "codex": request["codex"]}}, request
            )

    def test_namespace_deadline_capture_verify_and_resume_without_reexecution(self):
        case = self.fixture()
        namespace = self.binding(case)
        observed = {"collect": 0, "verify": 0}

        with (
            patch.object(
                trace_producer.native, "bind_namespace", return_value=namespace
            ) as current_namespace,
            patch.object(
                trace_producer.native, "wrap_namespace", side_effect=self.wrap
            ),
        ):
            request = trace_producer._request(case._args(timeout_seconds=30))
            inventory = self.inventory(request)

            def collect(**_kwargs):
                observed["collect"] += 1
                return copy.deepcopy(inventory)

            def verify(*_args, **_kwargs):
                observed["verify"] += 1
                return copy.deepcopy(inventory)

            with (
                patch.object(
                    trace_producer.observation,
                    "collect_runtime_observation",
                    side_effect=collect,
                ),
                patch.object(
                    trace_producer.observation,
                    "verify_runtime_observation",
                    side_effect=verify,
                ),
            ):
                produced = case._produce(timeout_seconds=30)
                self.assertEqual(produced["status"], "complete")
                self.assertEqual(produced["evidence_class"], "synthetic-test-only")
                self.assertFalse(produced["formal_ready"])
                saved = produced["capture"]["stable_request_binding"]
                self.assertEqual(saved["timeout_seconds"], 30)
                self.assertEqual(saved["native_namespace"], namespace)
                with self.assertRaisesRegex(Stage2Error, "synthetic-mode-mismatch"):
                    trace_producer._verify(
                        case._args(timeout_seconds=30),
                        case.telemetry,
                        produced["producer_receipt"],
                        allow_synthetic=False,
                    )
                resumed = case._produce(
                    timeout_seconds=30,
                    resume=True,
                    producer_receipt=produced["producer_receipt"],
                )
                self.assertEqual(
                    resumed["resume_action"], "verified-replay-no-execution"
                )
                self.assertEqual(
                    (case.calls, observed["collect"], observed["verify"]), (1, 1, 1)
                )

                with self.assertRaisesRegex(Stage2Error, "current-binding-changed"):
                    case._produce(
                        timeout_seconds=31,
                        resume=True,
                        producer_receipt=produced["producer_receipt"],
                    )
                original_runtime = case.codex.read_bytes()
                case.codex.write_bytes(b"changed-runtime")
                with self.assertRaisesRegex(
                    Stage2Error, "observation-binding-mismatch"
                ):
                    case._produce(
                        timeout_seconds=30,
                        resume=True,
                        producer_receipt=produced["producer_receipt"],
                    )
                case.codex.write_bytes(original_runtime)
                changed = copy.deepcopy(namespace)
                changed["dispatcher_sha256"] = "e" * 64
                current_namespace.return_value = changed
                with self.assertRaisesRegex(
                    Stage2Error, "observation-binding-mismatch"
                ):
                    case._produce(
                        timeout_seconds=30,
                        resume=True,
                        producer_receipt=produced["producer_receipt"],
                    )
                self.assertEqual(case.calls, 1)

    def test_namespace_observation_rejects_executable_metadata_change(self):
        case = self.fixture()
        namespace = self.binding(case)
        with patch.object(
            trace_producer.native, "bind_namespace", return_value=namespace
        ):
            request = trace_producer._request(case._args(timeout_seconds=45))
        inventory = self.inventory(request)
        inventory["binding"]["native_namespace"]["scope"]["codex"] = str(
            case.root / "foreign-codex"
        )
        with self.assertRaisesRegex(Stage2Error, "observation-binding-mismatch"):
            trace_producer._observation_binding(inventory, request)
        with self.assertRaisesRegex(Stage2Error, "producer-timeout-invalid"):
            trace_producer._request(case._args(timeout_seconds=float("nan")))


if __name__ == "__main__":
    unittest.main()
