"""Offline recovery must reproduce the packet actually used by v3.1 execution."""

import copy
import sys
import tempfile
import unittest
from contextlib import ExitStack
from pathlib import Path
from unittest import mock

PLUGIN = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PLUGIN / "cli"))

from stage1_eval.common import canonical, sha  # noqa: E402
from stage1_eval.judging import make_packet, make_packet_v31  # noqa: E402
from stage1_eval.reason_recovery import reconstruct_context  # noqa: E402
from stage1_eval.source_audit_units import build_audit_plan  # noqa: E402
from stage1_eval.sources_v31 import attach_public_sources  # noqa: E402


class RecoveryPacketParityTests(unittest.TestCase):
    def setUp(self):
        self.subject = {
            "status": "complete",
            "evidence": {
                "native-attempt-one": {"origin": "subject-native-trace", "text": "one"},
                "native-attempt-two": {"origin": "subject-native-trace", "text": "two"},
                "delivery-v31": {
                    "origin": "subject-delivered-artifact",
                    "text": "file",
                },
                "trace-decoy": {"origin": "other", "text": "not a native event"},
                "artifact-decoy": {"origin": "other", "text": "not a delivery"},
            },
        }
        self.extraction = {
            "works": [],
            "central_claims": [],
            "extraction_complete": True,
        }
        self.sources = {"sources": [], "receipts": [], "public_fetches": []}

    def packet(self, constructor, subject=None):
        return constructor(
            "Synthetic research task",
            {},
            subject or self.subject,
            self.extraction,
            None,
            self.sources,
            mode="packet-only",
        )

    def test_origin_inventory_preserves_legacy_constructor_and_content(self):
        subject_before = copy.deepcopy(self.subject)
        legacy = self.packet(make_packet)
        current = self.packet(make_packet_v31)
        self.assertEqual(
            legacy["process_evidence"]["capture-integrity"]["text"],
            "Subject status: complete; native trace events: 1; delivered artifacts: 1",
        )
        self.assertEqual(
            current["process_evidence"]["capture-integrity"],
            {
                "text": "Subject status: complete; native trace events: 2; delivered artifacts: 1",
                "origin": "evaluator-mechanical-inventory",
                "sha256": sha(canonical(self.subject)),
            },
        )
        self.assertEqual(current["content_evidence"], legacy["content_evidence"])
        self.assertEqual(current["extraction"], legacy["extraction"])
        self.assertEqual(self.subject, subject_before)

    def test_empty_origin_inventory_is_zero_without_fabricated_events(self):
        subject = {"status": "partial", "evidence": {}}
        packet = self.packet(make_packet_v31, subject)
        self.assertEqual(
            packet["process_evidence"]["capture-integrity"]["text"],
            "Subject status: partial; native trace events: 0; delivered artifacts: 0",
        )

    def test_real_reconstruction_matches_historical_v31_plan_without_calls(self):
        # Independent expected record reproduces the saved pipeline override,
        # not the new shared helper. Legacy construction must give a different plan.
        expected = self.packet(make_packet)
        expected["process_evidence"]["capture-integrity"] = {
            "text": "Subject status: complete; native trace events: 2; delivered artifacts: 1",
            "origin": "evaluator-mechanical-inventory",
            "sha256": sha(canonical(self.subject)),
        }
        attach_public_sources(expected, self.sources)
        historical_plan = build_audit_plan(expected, [], self.extraction)
        legacy = self.packet(make_packet)
        attach_public_sources(legacy, self.sources)
        self.assertNotEqual(
            canonical(build_audit_plan(legacy, [], self.extraction)),
            canonical(historical_plan),
        )

        with tempfile.TemporaryDirectory() as temporary:
            root = Path(temporary).resolve()
            output, capture = root / "output", root / "capture"
            output.mkdir()
            capture.mkdir()
            (capture / "run.json").write_bytes(canonical({"kind": "synthetic"}))
            codex = root / "codex"
            codex.write_bytes(b"synthetic executable; never executed")
            config = {
                "codex": str(codex),
                "evaluator_home": str(root / "home"),
                "model": "synthetic-model",
                "reasoning": "high",
                "codex_executable_sha256": sha(codex.read_bytes()),
            }
            policy = {"synthetic": "frozen"}
            runtime = {"synthetic": "source-runtime"}
            source_plan = {
                "execution_policy": policy,
                "codex_executable": str(codex),
                "codex_executable_sha256": config["codex_executable_sha256"],
                "source_runtime": runtime,
                "evaluator_bundle_sha256": "a" * 64,
                "research_hub_package_sha256": "b" * 64,
            }
            inputs = {
                "policy": policy,
                "model_config": config,
                "source_runtime": runtime,
                "identity": {
                    "evaluator_bundle_sha256": "a" * 64,
                    "research_hub_package_sha256": "b" * 64,
                },
                "capture_run_sha256": sha((capture / "run.json").read_bytes()),
                "spec_sha256": sha(canonical({})),
                "task_sha256": sha(b"Synthetic research task"),
                "mode": "packet-only",
            }
            for name, value in {
                "evaluation-input.json": inputs,
                "subject-observation.json": self.subject,
                "subject-extraction.json": self.extraction,
                "extraction-provenance.json": {},
                "subject-original-extraction.json": self.extraction,
                "subject-sources.json": self.sources,
                "spec.json": {},
            }.items():
                (output / name).write_bytes(canonical(value))
            (output / "task.txt").write_bytes(b"Synthetic research task")

            def inventory():
                return {
                    p.relative_to(root).as_posix(): (
                        p.read_bytes(),
                        p.stat().st_mtime_ns,
                    )
                    for p in root.rglob("*")
                    if p.is_file()
                }

            before = inventory()
            patches = {
                "stage1_eval.model_calls._request_config": config,
                "stage1_eval.source_runtime.source_runtime_preflight": runtime,
                "stage1_eval.runtime.installed_package_sha256": "b" * 64,
                "stage1_eval.formal.observe_capture_v31": (self.subject, {}),
                "stage1_eval.extraction_v31.extract_subject_v31": (self.extraction, {}),
                "stage1_eval.original_fields.extract_original_fields": (
                    self.extraction,
                    {},
                ),
                "stage1_eval.sources_v31.collect_sources_v31": self.sources,
                "stage1_eval.reason_recovery.readonly_source_validator": object(),
            }
            with ExitStack() as stack:
                mocks = {
                    name: stack.enter_context(mock.patch(name, return_value=value))
                    for name, value in patches.items()
                }
                run = stack.enter_context(
                    mock.patch(
                        "subprocess.run", side_effect=AssertionError("no subprocess")
                    )
                )
                plan, returned_config = reconstruct_context(
                    output, capture, None, source_plan, [], {}
                )
            self.assertEqual(canonical(plan), canonical(historical_plan))
            self.assertEqual(returned_config, config)
            self.assertEqual(inventory(), before)
            run.assert_not_called()
            mocks["stage1_eval.extraction_v31.extract_subject_v31"].assert_called_once()
            self.assertTrue(
                mocks[
                    "stage1_eval.extraction_v31.extract_subject_v31"
                ].call_args.kwargs["replay_only"]
            )
            self.assertTrue(
                mocks["stage1_eval.sources_v31.collect_sources_v31"].call_args.kwargs[
                    "replay_only"
                ]
            )


if __name__ == "__main__":
    unittest.main()
