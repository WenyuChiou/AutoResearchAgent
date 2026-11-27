"""Synthetic-only checks: no native process, network, files or real budgets."""

from copy import deepcopy
import json
import unittest

from harness_chat_stages import (
    CONTRACT_KIND,
    EVIDENCE_KIND,
    EVIDENCE_VERSION,
    StageContextRegistry,
    attach_stage_availability,
    require_context_available,
    require_stage,
    stage_availability,
)


PIN = "a" * 64
IMPLEMENTATION = "b" * 64
MANIFEST = "c" * 64


def context(stage=1):
    return dict(
        project_ref="view:synthetic-project",
        stage=stage,
        project_pin=PIN,
        materials=[],
        registered_delivery_ids=[],
        supported_actions=[
            "state",
            "materials",
            "read_material",
            "read_saved_stage",
            "register_delivery",
            "save_review",
        ],
        capabilities=dict(
            material_registration=True,
            local_review_notes=True,
            research_execution=False,
            formal_selection=False,
        ),
    )


def evidence(project, stage, pin):
    return dict(
        kind=EVIDENCE_KIND,
        version=EVIDENCE_VERSION,
        project_ref=project,
        stage=stage,
        project_pin=pin,
        binding=dict(manifest_sha256=MANIFEST),
        missing=[],
        context=dict(saved_status="synthetic-observed-not-executed"),
    )


def registry(provider=evidence, stage=3):
    value = StageContextRegistry()
    value.register(
        stage,
        provider,
        provider_id="synthetic-v1",
        implementation_sha256=IMPLEMENTATION,
    )
    return value


class StageAvailabilityTests(unittest.TestCase):
    def test_exact_stage_numbers(self):
        self.assertEqual(
            [require_stage(value) for value in range(1, 7)], list(range(1, 7))
        )

    def test_invalid_stage_types_and_range(self):
        for value in (True, False, 0, 7, -1, 1.0, "1", None, [], {}):
            with (
                self.subTest(value=value),
                self.assertRaisesRegex(ValueError, "chat-stage-not-supported"),
            ):
                stage_availability(context(value))

    def test_stage1_and_stage2_rules_preserved(self):
        for stage in (1, 2):
            original = context(stage)
            before = deepcopy(original)
            result = attach_stage_availability(original)
            self.assertEqual(original, before)
            self.assertEqual(
                {
                    key: val
                    for key, val in result.items()
                    if key != "stage_availability"
                },
                original,
            )
            self.assertTrue(result["stage_availability"]["context_available"])
            self.assertIsNot(result["materials"], original["materials"])

    def test_future_stages_default_unconnected(self):
        for stage in range(3, 7):
            result = attach_stage_availability(context(stage))
            self.assertFalse(result["stage_availability"]["context_available"])
            self.assertEqual(
                result["stage_availability"]["blocked_reason"],
                "chat-stage-context-provider-unregistered",
            )
            self.assertEqual(result["supported_actions"], ["state", "materials"])
            self.assertFalse(
                any(
                    result["capabilities"][key]
                    for key in (
                        "material_registration",
                        "local_review_notes",
                        "research_execution",
                    )
                )
            )
            with self.assertRaisesRegex(ValueError, "provider-unregistered"):
                require_context_available(result)

    def test_provider_is_stage_specific(self):
        value = registry()
        self.assertTrue(stage_availability(context(3), value)["context_available"])
        self.assertFalse(stage_availability(context(4), value)["context_available"])

    def test_explicit_future_readonly_context(self):
        result = attach_stage_availability(context(3), registry())
        status = require_context_available(result)
        self.assertEqual(status["context_source"], "explicit-read-only-stage-adapter")
        self.assertEqual(status["provider"]["implementation_sha256"], IMPLEMENTATION)
        self.assertEqual(status["evidence_binding"]["manifest_sha256"], MANIFEST)
        self.assertEqual(
            result["supported_actions"], ["state", "materials", "read_material"]
        )
        self.assertFalse(status["model_messages_allowed"])
        self.assertFalse(status["research_execution"])
        self.assertFalse(status["formal_selection"])
        self.assertEqual(
            status["message_blocked_reason"],
            "chat-separate-message-authorization-required",
        )
        self.assertEqual(len(status["observed_context_sha256"]), 64)

    def test_never_escalates_authorization_from_provider_metadata(self):
        def claimed(project, stage, pin):
            result = evidence(project, stage, pin)
            result["context"].update(
                model_messages_allowed=True, research_execution=True
            )
            return result

        status = stage_availability(context(3), registry(claimed))
        self.assertFalse(status["model_messages_allowed"])
        self.assertFalse(status["research_execution"])
        self.assertFalse(status["formal_selection"])

    def test_no_default_registry_calls_for_established_stages(self):
        def fail(*args):
            self.fail("existing stage context must not call future adapter")

        value = registry(fail)
        self.assertTrue(stage_availability(context(1), value)["context_available"])
        self.assertTrue(stage_availability(context(2), value)["context_available"])

    def test_stage1_and_stage2_adapters_cannot_be_replaced(self):
        for stage in (1, 2):
            with self.assertRaisesRegex(
                ValueError, "established-adapter-cannot-be-replaced"
            ):
                registry(stage=stage)

    def test_duplicate_registration_rejected(self):
        value = registry()
        with self.assertRaisesRegex(ValueError, "provider-already-registered"):
            value.register(
                3, evidence, provider_id="other", implementation_sha256=IMPLEMENTATION
            )

    def test_registration_requires_identifier_callable_and_implementation_pin(self):
        for provider, identity, pin in (
            (None, "id", IMPLEMENTATION),
            (evidence, "file:/private path", IMPLEMENTATION),
            (evidence, "id", ""),
            (evidence, "id", "D" * 64),
        ):
            with (
                self.subTest(identity=identity, pin=pin),
                self.assertRaises(ValueError),
            ):
                StageContextRegistry().register(
                    3, provider, provider_id=identity, implementation_sha256=pin
                )

    def test_project_binding_required(self):
        for field, val, reason in (
            ("project_ref", "", "project-invalid"),
            ("project_ref", "project\x00secret", "project-invalid"),
            ("project_pin", "", "project-pin-invalid"),
            ("project_pin", "F" * 64, "project-pin-invalid"),
        ):
            original = context(3)
            original[field] = val
            with self.subTest(field=field), self.assertRaisesRegex(ValueError, reason):
                stage_availability(original)

    def test_registry_object_must_be_explicit_type(self):
        with self.assertRaisesRegex(ValueError, "provider-registry-invalid"):
            stage_availability(context(3), {})

    def test_provider_identity_mismatch_fails_closed(self):
        for field, val in (
            ("project_ref", "view:another-project"),
            ("stage", 4),
            ("project_pin", "e" * 64),
        ):

            def changed(project, stage, pin):
                result = evidence(project, stage, pin)
                result[field] = val
                return result

            status = stage_availability(context(3), registry(changed))
            self.assertFalse(status["context_available"])
            self.assertEqual(
                status["blocked_reason"], "chat-stage-provider-binding-differs"
            )
            self.assertIsNone(status["observed_context"])

    def test_invalid_provider_schema_rejected(self):
        for value in (None, [], {}, {"kind": EVIDENCE_KIND}):
            status = stage_availability(context(3), registry(lambda *args: value))
            self.assertEqual(
                status["blocked_reason"], "chat-stage-provider-output-invalid"
            )

    def test_provider_version_rejected(self):
        def changed(project, stage, pin):
            result = evidence(project, stage, pin)
            result["version"] = "future-unknown"
            return result

        self.assertEqual(
            stage_availability(context(3), registry(changed))["blocked_reason"],
            "chat-stage-provider-version-unsupported",
        )

    def test_provider_binding_must_include_manifest(self):
        for binding in (
            {},
            {"head_sha256": MANIFEST},
            {"manifest_sha256": "Unknown"},
            {"manifest_sha256": MANIFEST, "unsafe key": MANIFEST},
        ):

            def changed(project, stage, pin):
                result = evidence(project, stage, pin)
                result["binding"] = binding
                return result

            status = stage_availability(context(3), registry(changed))
            self.assertEqual(
                status["blocked_reason"],
                "chat-stage-provider-evidence-binding-required",
            )

    def test_missing_evidence_gives_precise_block(self):
        def waiting(project, stage, pin):
            result = evidence(project, stage, pin)
            result["missing"] = ["trusted-human-source", "current-delivery-binding"]
            return result

        status = stage_availability(context(3), registry(waiting))
        self.assertFalse(status["context_available"])
        self.assertEqual(
            status["blocked_reason"], "chat-stage-required-evidence-missing"
        )
        self.assertEqual(
            status["missing"], ["trusted-human-source", "current-delivery-binding"]
        )

    def test_invalid_missing_codes_rejected(self):
        for missing in (
            None,
            "missing",
            ["raw private path /x"],
            ["same", "same"],
            [True],
        ):

            def changed(project, stage, pin):
                result = evidence(project, stage, pin)
                result["missing"] = missing
                return result

            self.assertEqual(
                stage_availability(context(3), registry(changed))["blocked_reason"],
                "chat-stage-provider-missing-codes-invalid",
            )

    def test_provider_failure_does_not_leak_exception(self):
        def broken(*args):
            raise RuntimeError("private credential and private path must not escape")

        status = stage_availability(context(3), registry(broken))
        self.assertEqual(status["blocked_reason"], "chat-stage-context-provider-failed")
        self.assertNotIn("private", json.dumps(status))

    def test_oversized_provider_context_rejected(self):
        def large(project, stage, pin):
            result = evidence(project, stage, pin)
            result["context"]["large"] = "x" * (33 * 1024)
            return result

        self.assertEqual(
            stage_availability(context(3), registry(large))["blocked_reason"],
            "chat-stage-provider-context-too-large",
        )

    def test_non_json_provider_context_rejected(self):
        for val in ([], {"notfinite": float("nan")}, {"value": object()}):

            def changed(project, stage, pin):
                result = evidence(project, stage, pin)
                result["context"] = val
                return result

            self.assertEqual(
                stage_availability(context(3), registry(changed))["blocked_reason"],
                "chat-stage-provider-context-invalid",
            )

    def test_returned_context_detached_from_provider(self):
        shared = evidence("view:synthetic-project", 3, PIN)
        status = stage_availability(context(3), registry(lambda *args: shared))
        shared["context"]["saved_status"] = "mutated"
        shared["binding"]["manifest_sha256"] = "d" * 64
        self.assertEqual(
            status["observed_context"]["saved_status"],
            "synthetic-observed-not-executed",
        )
        self.assertEqual(status["evidence_binding"]["manifest_sha256"], MANIFEST)

    def test_require_availability_bound_to_actual_context(self):
        result = attach_stage_availability(context(1))
        result["project_pin"] = "d" * 64
        with self.assertRaisesRegex(ValueError, "availability-binding-required"):
            require_context_available(result)
        with self.assertRaisesRegex(ValueError, "availability-binding-required"):
            require_context_available(context(1))

    def test_complete_envelope_serializable_for_all_stages(self):
        for stage in range(1, 7):
            status = stage_availability(context(stage))
            self.assertEqual(json.loads(json.dumps(status))["kind"], CONTRACT_KIND)
            self.assertFalse(status["model_messages_allowed"])
            self.assertFalse(status["research_execution"])


if __name__ == "__main__":
    unittest.main()
