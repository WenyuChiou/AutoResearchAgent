# ruff: noqa: E402 -- test the repository CLI without installing it.
"""Synthetic archive regression tests, never live or scientific acceptance."""

import copy
import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
import test_stage2_controller as fixtures
import test_stage2_native_namespace_integration as namespaces
from stage1_eval import model_calls
from stage1_eval.common import EvaluationError
from stage2_common import Stage2Error, canonical_hash
from stage2_live import historical_verifier as host
from stage2_live.controller import _replay_model_config, verify_controller
from stage2_live.replay import verify_extraction


class ControllerNamespaceReplayTests(unittest.TestCase):
    def setUp(self):
        self.fixture = namespaces.NamespaceIntegrationTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.scope = self.enterContext(
            patch.object(
                model_calls, "bind_namespace", return_value=self.fixture.binding
            )
        )
        self.enterContext(
            patch.object(model_calls, "wrap_namespace", side_effect=self.fixture.wrap)
        )
        self.dispatch = self.enterContext(
            patch.object(
                model_calls,
                "call_model_v31",
                side_effect=AssertionError("dispatch forbidden"),
            )
        )
        self.config = model_calls._request_config(
            self.fixture.codex, self.fixture.home, "test-model", "high"
        )
        self.request = {
            key: self.config[key]
            for key in ("codex", "evaluator_home", "model", "reasoning")
        }
        self.request["codex_runtime_sha256"] = hashlib.sha256(
            self.fixture.codex.read_bytes()
        ).hexdigest()
        self.output = self.fixture.capture_root / "archive"
        self.output.mkdir()
        self.schema = {
            "type": "object",
            "properties": {"ok": {"type": "boolean"}},
            "required": ["ok"],
            "additionalProperties": False,
        }
        fixtures.write_json(self.output / "test.schema.json", self.schema)
        fixtures._write_faithful_model_archive(
            self.output,
            "test",
            "exact prompt",
            self.schema,
            {"ok": True},
            self.config,
            fixtures.POLICY,
        )

    def replay(self, config):
        return model_calls.replay_native_model_call_archive(
            self.output / "test.model-call",
            expected_prompt="exact prompt",
            expected_schema=self.output / "test.schema.json",
            expected_config=config,
            expected_policy=fixtures.POLICY,
        )

    def test_faithful_namespaced_archive_keeps_exact_cwd_and_never_dispatches(self):
        reconstructed = _replay_model_config(self.request)
        self.assertEqual(reconstructed, self.config)
        self.assertEqual(reconstructed["effective_cwd"], str(self.fixture.work))
        self.assertEqual(self.replay(reconstructed)[0], {"ok": True})
        self.dispatch.assert_not_called()

    def test_namespace_cwd_dispatcher_and_scope_drift_rejects(self):
        for change in ("cwd", "dispatcher", "scope", "file"):
            with self.subTest(change=change):
                binding = copy.deepcopy(self.fixture.binding)
                if change == "cwd":
                    binding["scope"]["workspace"] += "-changed"
                elif change == "dispatcher":
                    binding["dispatcher_sha256"] = "e" * 64
                elif change == "scope":
                    binding["scope"]["capture_root"] += "-changed"
                else:
                    binding["sha256"] = "f" * 64
                self.scope.return_value = binding
                with self.assertRaisesRegex(EvaluationError, "fingerprint"):
                    self.replay(_replay_model_config(self.request))
        self.dispatch.assert_not_called()

    def test_binary_digest_and_missing_runtime_pin_reject_before_replay(self):
        for request in (
            {**self.request, "codex_runtime_sha256": "a" * 64},
            {k: v for k, v in self.request.items() if k != "codex_runtime_sha256"},
        ):
            with self.subTest(request=request), self.assertRaises(Stage2Error):
                _replay_model_config(request)
        self.dispatch.assert_not_called()


class HistoricalHostVerificationTests(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve()
        self.producer = self.root / "old-cli"
        for name, raw in {
            "stage2_live/controller.py": b"old controller data\n",
            "stage2_live/extraction.py": b"old extraction data\n",
            "stage2_ideation/prompts.py": b"old prompt data\n",
        }.items():
            path = self.producer / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
        rows = host._source_inventory(self.producer)
        self.producer_sha = canonical_hash(rows)
        self.adapter_sha = canonical_hash(
            {k: v for k, v in rows.items() if k != "stage2_live/controller.py"}
        )
        self.windows_adapter_sha = canonical_hash(
            {
                k.replace("/", "\\"): v
                for k, v in rows.items()
                if k != "stage2_live/controller.py"
            }
        )
        self.registry = self.root / "compatibility.json"
        fixtures.write_json(
            self.registry,
            {
                "supported_producers": {
                    self.producer_sha: {
                        "controller_sha256": rows["stage2_live/controller.py"],
                        "extraction_adapter_sha256": {
                            "posix": self.adapter_sha,
                            "windows": self.windows_adapter_sha,
                        },
                        "merge_sha": "a" * 40,
                    }
                }
            },
        )
        self.enterContext(patch.object(host, "_REGISTRY", self.registry))
        self.binding = {
            "kind": "Stage2HistoricalVerifierBinding",
            "schema_version": "1.0.0",
            "producer_cli_root": str(self.producer),
            "producer_cli_sha256": self.producer_sha,
            "producer_path_convention": "posix",
            **host.inspect_verifier_build(),
        }

    def test_pins_are_external_and_old_source_is_never_executed(self):
        with patch(
            "builtins.exec", side_effect=AssertionError("old code must not execute")
        ):
            result = host.resolve_historical_binding(self.binding)
        self.assertEqual(result.extraction_adapter_sha256, self.adapter_sha)
        self.assertTrue(result.receipt["read_only"])
        self.assertFalse(result.receipt["formal_ready"])
        self.assertFalse(result.receipt["subject_upgraded"])

    def test_explicit_windows_convention_preserves_original_adapter_hash(self):
        binding = {**self.binding, "producer_path_convention": "windows"}
        original_request = {"adapter_code_sha256": self.windows_adapter_sha}
        before = copy.deepcopy(original_request)
        verified = host.resolve_historical_binding(binding)
        self.assertEqual(
            verified.extraction_adapter_sha256, original_request["adapter_code_sha256"]
        )
        self.assertEqual(original_request, before)
        self.assertNotEqual(verified.extraction_adapter_sha256, self.adapter_sha)
        with self.assertRaisesRegex(Stage2Error, "path-convention"):
            host.resolve_historical_binding(
                {**binding, "producer_path_convention": "guess"}
            )

    def test_mixed_dependency_import_is_rejected(self):
        import jsonschema

        with patch.object(
            jsonschema, "__file__", str(self.root / "shadow-jsonschema.py")
        ):
            with self.assertRaisesRegex(Stage2Error, "mixed-dependency-import"):
                host.inspect_verifier_build()

    def test_resource_bytes_and_format_dependency_closure_are_pinned(self):
        from types import SimpleNamespace

        names, _ = host._dependency_distributions()
        self.assertTrue(
            {"jsonschema-specifications", "idna", "rfc3339-validator", "six"} <= names
        )
        resource = self.root / "schema-package/schemas/vocabularies/validation"
        resource.parent.mkdir(parents=True)
        resource.write_bytes(b'{"type":"object"}')
        distribution = SimpleNamespace(
            files=[Path("schemas/vocabularies/validation")],
            locate_file=lambda entry: self.root / "schema-package" / entry,
        )
        first, _ = host._distribution_inventory(distribution)
        resource.write_bytes(b'{"type":"array"}')
        second, _ = host._distribution_inventory(distribution)
        self.assertNotEqual(canonical_hash(first), canonical_hash(second))

    def test_schema_resource_change_rejects_retained_runtime_pin(self):
        runtime = host._runtime_binding()
        rows = runtime["dependencies"]["jsonschema-specifications"]["files"]
        resource_name = next(
            name for name in rows if name.endswith("vocabularies/validation")
        )
        distribution = host.metadata.distribution("jsonschema-specifications")
        resource = Path(distribution.locate_file(resource_name)).resolve()
        original_sha = host._sha

        def changed_resource(path):
            return "a" * 64 if Path(path).resolve() == resource else original_sha(path)

        # Model a changed resource read without modifying the installed venv.
        with patch.object(host, "_sha", side_effect=changed_resource):
            with self.assertRaisesRegex(Stage2Error, "host-build-changed"):
                host.resolve_historical_binding(self.binding)

    def test_missing_embedded_unknown_and_wrong_pins_reject(self):
        for change in (
            "missing",
            "embedded",
            "producer",
            "host",
            "runtime",
            "unsupported",
        ):
            with self.subTest(change=change):
                binding = copy.deepcopy(self.binding)
                if change == "missing":
                    binding.pop("verifier_runtime_sha256")
                elif change == "embedded":
                    binding["manifest_sha256"] = "b" * 64
                elif change == "unsupported":
                    fixtures.write_json(self.registry, {"supported_producers": {}})
                    binding.update(host.inspect_verifier_build())
                else:
                    key = {
                        "producer": "producer_cli_sha256",
                        "host": "verifier_build_sha256",
                        "runtime": "verifier_runtime_sha256",
                    }[change]
                    binding[key] = "c" * 64
                with self.assertRaises(Stage2Error):
                    host.resolve_historical_binding(binding)

    def test_producer_mutation_and_rehashed_unregistered_tree_reject(self):
        (self.producer / "stage2_ideation/prompts.py").write_bytes(b"changed data")
        with self.assertRaisesRegex(Stage2Error, "producer-build-changed"):
            host.resolve_historical_binding(self.binding)
        updated = {
            **self.binding,
            "producer_cli_sha256": canonical_hash(
                host._source_inventory(self.producer)
            ),
        }
        with self.assertRaisesRegex(Stage2Error, "unsupported-producer"):
            host.resolve_historical_binding(updated)

    def test_host_registry_mutation_and_noncanonical_or_missing_producer_reject(self):
        for root in ("relative-cli", str(self.root / "missing-cli")):
            with self.subTest(root=root), self.assertRaises(Stage2Error):
                host.resolve_historical_binding(
                    {**self.binding, "producer_cli_root": root}
                )
        self.registry.write_bytes(self.registry.read_bytes() + b"\n")
        with self.assertRaisesRegex(Stage2Error, "host-build-changed"):
            host.resolve_historical_binding(self.binding)

    def test_environment_rechecks_host_pins_after_operation(self):
        def mutate(*args):
            self.registry.write_bytes(self.registry.read_bytes() + b"\n")
            return {"inventory_status": "not-captured"}

        with patch(
            "stage2_live.environment.verify_environment_capture", side_effect=mutate
        ):
            with self.assertRaisesRegex(Stage2Error, "host-build-changed"):
                host.verify_historical_environment_capture(
                    "capture",
                    "r",
                    {"receipt": "p"},
                    None,
                    historical_binding=self.binding,
                )

    def test_controller_default_stays_strict_and_bound_history_stays_synthetic(self):
        case = fixtures.Stage2ControllerTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        result = case.run_controller(fixtures.SyntheticAdapter())
        path = case.controller / "controller_manifest.json"
        manifest = json.loads(path.read_text(encoding="utf-8"))
        manifest["controller_code_sha256"] = host.resolve_historical_binding(
            self.binding
        ).controller_sha256
        manifest["manifest_sha256"] = canonical_hash(
            {k: v for k, v in manifest.items() if k != "manifest_sha256"}
        )
        fixtures.write_json(path, manifest)
        # Avoid the original receipt-addressed manifest; use this explicitly
        # externally retained synthetic fixture receipt for both paths.
        receipt = manifest["manifest_sha256"]
        with self.assertRaisesRegex(Stage2Error, "manifest-invalid"):
            verify_controller(case.controller, receipt)
        with patch.object(
            model_calls,
            "call_model_v31",
            side_effect=AssertionError("dispatch forbidden"),
        ) as dispatch:
            verified = verify_controller(
                case.controller, receipt, historical_binding=self.binding
            )
        self.assertTrue(verified["synthetic_test_only"])
        self.assertFalse(verified["pilot_executable"])
        self.assertFalse(verified["formal_ready"])
        self.assertEqual(
            verified["historical_verification"]["producer_cli_sha256"],
            self.producer_sha,
        )
        self.assertEqual(result["human_selection"], "pending")
        dispatch.assert_not_called()
        with self.assertRaisesRegex(Stage2Error, "manifest-invalid"):
            verify_controller(
                case.controller, "f" * 64, historical_binding=self.binding
            )

    def test_environment_uses_existing_guards_and_cannot_promote_inventory(self):
        expected = {
            "status": "verified",
            "inventory_status": "not-captured",
            "inventory_sha256": None,
        }
        with patch(
            "stage2_live.environment.verify_environment_capture", return_value=expected
        ) as verifier:
            result = host.verify_historical_environment_capture(
                "capture", "r", {"receipt": "p"}, None, historical_binding=self.binding
            )
        verifier.assert_called_once_with("capture", "r", {"receipt": "p"}, None)
        self.assertEqual(result["environment"], expected)
        self.assertFalse(result["historical_verification"]["formal_ready"])
        with patch(
            "stage2_live.environment.verify_environment_capture",
            side_effect=Stage2Error("source or permission changed"),
        ):
            with self.assertRaisesRegex(Stage2Error, "source or permission"):
                host.verify_historical_environment_capture(
                    "capture",
                    "r",
                    {"receipt": "p"},
                    None,
                    historical_binding=self.binding,
                )

    def test_extraction_retains_original_receipt_sources_and_default_code_guard(self):
        case = fixtures.Stage2ControllerTests()
        case.setUp()
        self.addCleanup(case.doCleanups)
        case.test_reconstructed_config_authenticates_faithful_extraction_archive()
        output = case.root / "faithful-extraction"
        request = json.loads((output / "request.json").read_text(encoding="utf-8"))
        request["adapter_code_sha256"] = self.adapter_sha
        fixtures.write_json(output / "request.json", request)
        result = json.loads((output / "result.json").read_text(encoding="utf-8"))
        result["request_sha256"] = canonical_hash(request)
        fixtures.write_json(output / "result.json", result)
        receipt = {
            "result_sha256": fixtures.digest(output / "result.json"),
            "unit_receipts": result["unit_receipts"],
        }
        packet = json.loads((output / "input-packet.json").read_text(encoding="utf-8"))
        args = {
            "raw_proposal": (output / "raw-proposal.bin").read_text(encoding="utf-8"),
            "packet": packet,
            "source_root": case.root / "archive-sources",
            "snapshot_sha256": fixtures.SNAPSHOT,
            "expected_config": _replay_model_config(request),
            "expected_policy": fixtures.POLICY,
        }
        with self.assertRaisesRegex(Stage2Error, "extraction-request-mismatch"):
            verify_extraction(output, receipt, **args)
        before = {
            p.relative_to(output).as_posix(): fixtures.digest(p)
            for p in output.rglob("*")
            if p.is_file()
        }
        with patch.object(
            model_calls,
            "call_model_v31",
            side_effect=AssertionError("dispatch forbidden"),
        ) as dispatch:
            verified = verify_extraction(
                output, receipt, historical_binding=self.binding, **args
            )
        dispatch.assert_not_called()
        self.assertEqual(verified["result"], result)
        self.assertFalse(verified["scientific_approval"])
        self.assertEqual(
            before,
            {
                p.relative_to(output).as_posix(): fixtures.digest(p)
                for p in output.rglob("*")
                if p.is_file()
            },
        )
        with self.assertRaisesRegex(Stage2Error, "receipt"):
            verify_extraction(
                output,
                {**receipt, "result_sha256": "f" * 64},
                historical_binding=self.binding,
                **args,
            )
        source = args["source_root"] / packet["sources"][0]["path"]
        source.write_bytes(source.read_bytes() + b"changed source")
        with self.assertRaises((Stage2Error, ValueError)):
            verify_extraction(output, receipt, historical_binding=self.binding, **args)


if __name__ == "__main__":
    unittest.main()
