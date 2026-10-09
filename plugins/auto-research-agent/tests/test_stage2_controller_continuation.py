# ruff: noqa: E402 -- load repository CLI and controlled test fixtures.
"""Explicit reviewed-snapshot continuation regressions for the Stage 2 controller."""

import copy
import hashlib
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]

from stage2_common import Stage2Error, canonical_hash
from stage2_live.controller import (
    _extracted_next_packet,
    _run_controller,
    _validate_spec,
    verify_controller,
)
from stage2_live.environment import environment_key
from stage2_live.source_updates import prepare_source_update
from stage2_workflow import initialize_workflow
from stage2_workflow.store import add_snapshot, inspect_workflow
from test_stage2_checker import assessment
import test_stage2_controller as controller_fixtures
from test_stage2_controller import SyntheticAdapter as _SyntheticAdapter
from test_stage2_named_policy import _config
from test_stage2_role_policy_controller import _root_policy
import test_stage2_prior_work as prior_work_fixtures


class CurrentVersionAdapter(_SyntheticAdapter):
    def review(self, context):
        role = context["role"]
        self.calls.append(f"review:{role}")
        self.review_inputs.append(copy.deepcopy(context))
        candidate = max(
            (
                row
                for row in context["packet"]["candidates"]
                if row["candidate_id"] == context["candidate_id"]
            ),
            key=lambda row: row["version"],
        )
        value = assessment(
            context["packet"],
            event_id=f"synthetic-{role}",
            version=candidate["version"],
        )
        return {
            "review": {
                "role": role,
                "view_sha256": canonical_hash(context["view"]),
                "snapshot_sha256": context["snapshot_sha256"],
                "candidate_id": context["candidate_id"],
                "candidate_version": candidate["version"],
                "assessment": value,
                "session_id": f"session-{role}",
                "native_artifact": {
                    "path": f"synthetic-{role}.jsonl",
                    "sha256": ("2" if role == "challenger" else "3") * 64,
                },
                "initial": True,
                "assumptions": ["The bounded observations are comparable."],
                "strongest_alternative": "A bounded alternative explanation.",
                "change_conditions": ["New contradictory evidence."],
            },
            "adapter_mode": "injected-test",
        }


class Stage2ControllerContinuationTests(unittest.TestCase):
    def setUp(self):
        self.fixture = controller_fixtures.Stage2ControllerTests(
            methodName="test_complete_pipeline_replays_without_new_calls_and_awaits_human"
        )
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        environment = tempfile.TemporaryDirectory()
        self.addCleanup(environment.cleanup)
        self.environment_root = Path(environment.name).resolve()
        self.spec = self._v12_spec(self.fixture.spec)

    def _v12_spec(self, source):
        spec = copy.deepcopy(source)
        spec.update(
            schema_version="1.2.0",
            execution_policies={},
            execution_preflights={},
            execution_inventories={},
        )
        codex = self.environment_root / "continuation-codex.exe"
        codex.write_bytes(b"controlled continuation runtime; never executed")
        spec["native"]["codex"] = str(codex)
        for index, name in enumerate(spec["workspaces"]):
            safe = name.replace(":", "-")
            home = self.environment_root / f"{safe}-home"
            workspace = self.environment_root / f"{safe}-workspace"
            home.mkdir(parents=True, exist_ok=True)
            workspace.mkdir(parents=True, exist_ok=True)
            spec["workspaces"][name] = {
                "home": str(home),
                "workspace": str(workspace),
            }
            telemetry = self.environment_root / f"continuation-telemetry-{index}"
            capture = self.environment_root / f"continuation-capture-{index}"
            raw = _config(
                workspace,
                home,
                telemetry,
                capture,
                model="synthetic-model",
                reasoning="medium",
            )
            (home / "config.toml").write_bytes(raw)
            key = environment_key(home, workspace)
            spec["execution_policies"][key] = _root_policy(raw, telemetry, capture)
            spec["execution_preflights"][key] = {
                "synthetic": True,
                "inventory_receipt": {"environment": name},
            }
        return spec

    def _append_packet(self, packet, source_root, reason):
        path = self.fixture.root / f"packet-{canonical_hash(packet)}.json"
        path.write_text(json.dumps(packet), encoding="utf-8")
        state = inspect_workflow(self.fixture.run)
        event = add_snapshot(
            self.fixture.run,
            path,
            source_root,
            reason,
            {
                "candidate-1": {
                    "status": "affected",
                    "reason": reason,
                }
            },
            state["head_sha256"],
        )
        return event["payload"]["snapshot_sha256"], event["event_sha256"]

    def _source_update(self):
        state = inspect_workflow(self.fixture.run)
        packet = copy.deepcopy(state["latest_snapshot"]["packet"])
        source_root = self.fixture.root / "continuation-sources"
        shutil.copytree(
            state["latest_snapshot"]["checker"]["root"] / "sources", source_root
        )
        raw = b"A later bounded source changes the recorded evidence set.\n"
        (source_root / "source-3.txt").write_bytes(raw)
        packet["sources"].append(
            {
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "path": "source-3.txt",
                "sha256": hashlib.sha256(raw).hexdigest(),
                "evidence_level": "full-text",
            }
        )
        packet["evidence"].append(
            {
                "evidence_id": "ev-3",
                "source_id": "src-3",
                "work_id": "work-3",
                "version_id": "v1",
                "locator": "line 1",
                "quote": raw.decode().strip(),
            }
        )
        return packet, source_root

    def test_old_v12_ignores_newer_source_snapshot_without_opt_in(self):
        adapter = _SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        packet, source_root = self._source_update()
        _, head = self._append_packet(packet, source_root, "New source set.")
        with self.assertRaisesRegex(
            Stage2Error, "delivery-review-batch-current-snapshot-mismatch"
        ):
            _run_controller(
                self.fixture.run,
                self.fixture.controller,
                self.fixture.root / "legacy-delivery-replay",
                head,
                self.spec,
                adapter,
            )
        self.assertEqual(adapter.calls.count("research"), 1)
        self.assertEqual(adapter.calls.count("extract"), 1)

    def test_source_only_continuation_reuses_ideation_and_rechecks_target(self):
        adapter = _SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        packet, source_root = self._source_update()
        target, head = self._append_packet(packet, source_root, "New source set.")
        continued = copy.deepcopy(self.spec)
        continued["continuation_snapshot_sha256"] = target
        result = _run_controller(
            self.fixture.run,
            self.fixture.controller,
            self.fixture.root / "continued-source-delivery",
            head,
            continued,
            adapter,
        )
        self.assertEqual(result["status"], "awaiting-human")
        self.assertEqual(result["batch"]["snapshot_sha256"], target)
        self.assertEqual(adapter.calls.count("research"), 1)
        self.assertEqual(adapter.calls.count("extract"), 1)
        self.assertTrue(all(row["replayed"] for row in result["units"][:2]))
        verified = verify_controller(
            self.fixture.controller, result["controller_manifest_sha256"]
        )
        self.assertEqual(verified["delivery"]["manifest"]["snapshot_sha256"], target)

        saved_head = verified["manifest"]["workflow_head_sha256"]
        calls = list(adapter.calls)
        state = inspect_workflow(self.fixture.run)
        later_packet = copy.deepcopy(state["latest_snapshot"]["packet"])
        later_packet["packet_id"] = "later-legitimate-continuation"
        later_target, later_head = self._append_packet(
            later_packet,
            state["latest_snapshot"]["checker"]["root"] / "sources",
            "A later legitimate snapshot follows the saved receipt.",
        )
        retained = verify_controller(
            self.fixture.controller, result["controller_manifest_sha256"]
        )
        self.assertEqual(retained["workflow"]["head_sha256"], later_head)
        self.assertEqual(retained["manifest"]["workflow_head_sha256"], saved_head)
        self.assertEqual(adapter.calls, calls)

        with self.assertRaisesRegex(Stage2Error, "continuation-snapshot-stale"):
            _run_controller(
                self.fixture.run,
                self.fixture.controller,
                self.fixture.root / "stale-current-target-delivery",
                later_head,
                continued,
                adapter,
            )
        self.assertEqual(adapter.calls, calls)

        manifest_path = (
            self.fixture.controller
            / "controller_manifests"
            / f"{result['controller_manifest_sha256']}.json"
        )
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        unknown_head = copy.deepcopy(manifest)
        unknown_head["workflow_head_sha256"] = "f" * 64
        unknown_head["manifest_sha256"] = canonical_hash(
            {
                key: value
                for key, value in unknown_head.items()
                if key != "manifest_sha256"
            }
        )
        (manifest_path.parent / f"{unknown_head['manifest_sha256']}.json").write_text(
            json.dumps(unknown_head), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "workflow-head-not-retained"):
            verify_controller(self.fixture.controller, unknown_head["manifest_sha256"])

        saved_spec = json.loads(
            (self.fixture.controller / manifest["controller_spec_path"]).read_text(
                encoding="utf-8"
            )
        )
        saved_spec["continuation_snapshot_sha256"] = later_target
        saved_spec_sha256 = canonical_hash(saved_spec)
        saved_spec_path = (
            self.fixture.controller / "controller_specs" / f"{saved_spec_sha256}.json"
        )
        saved_spec_path.write_text(json.dumps(saved_spec), encoding="utf-8")
        future_target = copy.deepcopy(manifest)
        future_target["controller_spec_path"] = (
            f"controller_specs/{saved_spec_sha256}.json"
        )
        future_target["controller_spec_sha256"] = saved_spec_sha256
        future_target["manifest_sha256"] = canonical_hash(
            {
                key: value
                for key, value in future_target.items()
                if key != "manifest_sha256"
            }
        )
        (manifest_path.parent / f"{future_target['manifest_sha256']}.json").write_text(
            json.dumps(future_target), encoding="utf-8"
        )
        with self.assertRaisesRegex(Stage2Error, "continuation-snapshot-not-found"):
            verify_controller(self.fixture.controller, future_target["manifest_sha256"])

    def test_revised_candidate_continuation_uses_new_version_and_fresh_actions(self):
        adapter = CurrentVersionAdapter()
        first = self.fixture.run_controller(adapter, spec=self.spec)
        state = inspect_workflow(self.fixture.run)
        packet = copy.deepcopy(state["latest_snapshot"]["packet"])
        revised = copy.deepcopy(packet["candidates"][0])
        revised.update(
            version=2, parent_version=1, question="A reviewed revised question?"
        )
        packet["candidates"].append(revised)
        target, head = self._append_packet(
            packet,
            state["latest_snapshot"]["checker"]["root"] / "sources",
            "Candidate content revised.",
        )
        continued = copy.deepcopy(self.spec)
        continued["continuation_snapshot_sha256"] = target
        result = _run_controller(
            self.fixture.run,
            self.fixture.controller,
            self.fixture.root / "continued-revision-delivery",
            head,
            continued,
            adapter,
        )
        self.assertEqual(result["status"], "awaiting-human")
        self.assertEqual(
            {row["candidate_version"] for row in result["batch"]["assignments"]},
            {2},
        )
        self.assertNotEqual(
            first["batch"]["batch_sha256"], result["batch"]["batch_sha256"]
        )
        self.assertEqual(adapter.calls.count("research"), 1)
        self.assertEqual(adapter.calls.count("extract"), 1)
        self.assertEqual(sum(call.startswith("review:") for call in adapter.calls), 4)
        self.assertTrue(all(not row["replayed"] for row in result["units"][2:]))

    def test_continuation_rejects_foreign_stale_and_pre_ideation_targets(self):
        adapter = _SyntheticAdapter()
        first = self.fixture.run_controller(adapter, spec=self.spec)
        ideation = first["batch"]["snapshot_sha256"]
        packet, source_root = self._source_update()
        stale, head = self._append_packet(packet, source_root, "First continuation.")
        packet2 = copy.deepcopy(packet)
        packet2["packet_id"] = "second-continuation-packet"
        latest, head = self._append_packet(packet2, source_root, "Second continuation.")
        for value, error in (
            ("f" * 64, "snapshot-not-found"),
            (stale, "snapshot-stale"),
            (ideation, "must-follow-ideation"),
            (self.fixture.base, "must-follow-ideation"),
        ):
            with self.subTest(value=value, error=error):
                changed = copy.deepcopy(self.spec)
                changed["continuation_snapshot_sha256"] = value
                with self.assertRaisesRegex(Stage2Error, error):
                    _run_controller(
                        self.fixture.run,
                        self.fixture.controller,
                        self.fixture.root / f"rejected-{value[:8]}",
                        head,
                        changed,
                        adapter,
                    )
        self.assertNotEqual(latest, stale)
        self.assertEqual(adapter.calls.count("research"), 1)
        self.assertEqual(adapter.calls.count("extract"), 1)

    def test_only_v12_accepts_continuation_field(self):
        for version in (None, "1.1.0"):
            changed = copy.deepcopy(self.spec)
            if version is None:
                for key in (
                    "schema_version",
                    "execution_policies",
                    "execution_preflights",
                    "execution_inventories",
                ):
                    changed.pop(key, None)
            else:
                changed["schema_version"] = version
            changed["continuation_snapshot_sha256"] = "a" * 64
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(Stage2Error, "spec-shape|requires-v1.2"),
            ):
                _validate_spec(
                    changed,
                    self.fixture.packet,
                    self.fixture.base,
                    synthetic=True,
                )
        _validate_spec(
            self.spec,
            self.fixture.packet,
            self.fixture.base,
            synthetic=True,
        )

        present_null = copy.deepcopy(self.spec)
        present_null["continuation_snapshot_sha256"] = None
        with self.assertRaisesRegex(Stage2Error, "continuation-snapshot-invalid"):
            _validate_spec(
                present_null,
                self.fixture.packet,
                self.fixture.base,
                synthetic=True,
            )

    def test_extraction_still_requires_the_nested_packet_envelope(self):
        with self.assertRaisesRegex(Stage2Error, "extraction-next-packet-missing"):
            _extracted_next_packet({"next_packet": copy.deepcopy(self.fixture.packet)})

    def test_target_cannot_replace_unsaved_original_ideation_units(self):
        state = inspect_workflow(self.fixture.run)
        packet = copy.deepcopy(state["latest_snapshot"]["packet"])
        packet["packet_id"] = "premature-continuation"
        target, head = self._append_packet(
            packet,
            state["latest_snapshot"]["checker"]["root"] / "sources",
            "A target exists before controller ideation.",
        )
        changed = copy.deepcopy(self.spec)
        changed["continuation_snapshot_sha256"] = target
        adapter = _SyntheticAdapter()
        with self.assertRaisesRegex(Stage2Error, "continuation-unit-missing"):
            _run_controller(
                self.fixture.run,
                self.fixture.controller,
                self.fixture.root / "premature-delivery",
                head,
                changed,
                adapter,
            )
        self.assertEqual(adapter.calls, [])

    def test_continuation_rejects_changed_saved_bindings_before_new_calls(self):
        adapter = _SyntheticAdapter()
        self.fixture.run_controller(adapter, spec=self.spec)
        packet, source_root = self._source_update()
        target, head = self._append_packet(packet, source_root, "New source set.")
        continued = copy.deepcopy(self.spec)
        continued["continuation_snapshot_sha256"] = target
        calls = list(adapter.calls)

        research = continued["workspaces"]["research"]
        profile = Path(research["home"]) / "config.toml"
        profile_before = profile.read_bytes()
        profile_after = profile_before + b"# changed continuation profile\n"
        profile.write_bytes(profile_after)
        changed_profile = copy.deepcopy(continued)
        key = environment_key(research["home"], research["workspace"])
        changed_profile["execution_policies"][key]["config_sha256"] = hashlib.sha256(
            profile_after
        ).hexdigest()
        try:
            with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
                _run_controller(
                    self.fixture.run,
                    self.fixture.controller,
                    self.fixture.root / "changed-profile-delivery",
                    head,
                    changed_profile,
                    adapter,
                )
        finally:
            profile.write_bytes(profile_before)

        changed_proof = copy.deepcopy(continued)
        changed_proof["execution_preflights"][key]["inventory_receipt"] = {
            "environment": "changed-proof"
        }
        with self.assertRaisesRegex(Stage2Error, "action-binding-changed"):
            _run_controller(
                self.fixture.run,
                self.fixture.controller,
                self.fixture.root / "changed-proof-delivery",
                head,
                changed_proof,
                adapter,
            )

        target_state = inspect_workflow(self.fixture.run)
        target_source = (
            target_state["latest_snapshot"]["checker"]["root"]
            / "sources"
            / "source-3.txt"
        )
        source_before = target_source.read_bytes()
        target_source.write_bytes(source_before + b" changed")
        try:
            with self.assertRaises(Stage2Error):
                _run_controller(
                    self.fixture.run,
                    self.fixture.controller,
                    self.fixture.root / "changed-source-delivery",
                    head,
                    continued,
                    adapter,
                )
        finally:
            target_source.write_bytes(source_before)
        self.assertEqual(adapter.calls, calls)

    def test_v24_source_update_clears_dossiers_and_returns_needs_prior_work(self):
        prior = prior_work_fixtures.Stage2PriorWorkTests(
            methodName="test_source_update_clears_stale_reviews"
        )
        prior.setUp()
        self.addCleanup(prior.doCleanups)
        base_packet = copy.deepcopy(prior.packet)
        base_packet["prior_work_reviews"] = []
        packet_path = prior.root / "continuation-base.json"
        packet_path.write_text(json.dumps(base_packet), encoding="utf-8")
        run = prior.root / "continuation-workflow"
        initialize_workflow(
            packet_path,
            prior.source_root,
            run,
            {"model": "synthetic-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
            canonical_hash(base_packet),
        )
        initial = inspect_workflow(run)
        base_hash = initial["latest_snapshot"]["event"]["payload"]["snapshot_sha256"]
        seed_spec = copy.deepcopy(self.fixture.spec)
        seed_spec.update(
            confirmed_brief_sha256=canonical_hash(base_packet["brief"]),
            base_snapshot_sha256=base_hash,
        )
        seed_spec["workspaces"] = {
            key: value
            for key, value in seed_spec["workspaces"].items()
            if key in {"research", "extractor"}
        }
        spec = self._v12_spec(seed_spec)
        controller = prior.root / "continuation-controller"
        adapter = _SyntheticAdapter()
        pending = _run_controller(
            run,
            controller,
            prior.root / "pending-delivery",
            initial["head_sha256"],
            spec,
            adapter,
        )
        self.assertEqual(pending["status"], "needs-prior-work")

        source, evidence, literature = prior.add_stage2_work()
        state = inspect_workflow(run)
        parent = copy.deepcopy(state["latest_snapshot"]["packet"])
        parent["prior_work_reviews"] = []
        raw_path = prior.source_root / source["path"]
        update = prepare_source_update(
            parent,
            state["latest_snapshot"]["checker"]["root"] / "sources",
            [
                {
                    "source": source,
                    "evidence": [evidence],
                    "literature": literature,
                    "raw_path": str(raw_path),
                    "acquisition": {
                        "status": "obtained",
                        "url": source["source_url"],
                        "retrieved_at": source["retrieved_at"],
                        "raw_sha256": source["sha256"],
                        "identity_status": "matched",
                        "evidence_level": source["evidence_level"],
                        "reason": "Captured a bounded later source.",
                        "action_ref": "native-call-synthetic",
                    },
                }
            ],
            [],
            {
                "direction-1": {
                    "status": "affected",
                    "reason": "The source set changed precedent positioning.",
                }
            },
            prior.root / "continuation-source-update",
            expected_packet_sha256=canonical_hash(parent),
        )
        updated = json.loads(Path(update["packet_path"]).read_text(encoding="utf-8"))
        self.assertEqual(updated["prior_work_reviews"], [])
        event = add_snapshot(
            run,
            update["packet_path"],
            update["source_root"],
            "A later source set requires current dossiers.",
            update["impact"],
            state["head_sha256"],
        )
        continued = copy.deepcopy(spec)
        continued["continuation_snapshot_sha256"] = event["payload"]["snapshot_sha256"]
        result = _run_controller(
            run,
            controller,
            prior.root / "continued-source-delivery",
            event["event_sha256"],
            continued,
            adapter,
        )
        self.assertEqual(result["status"], "needs-prior-work")
        self.assertEqual(
            result["prior_work_completion"]["missing_candidate_ids"], ["direction-1"]
        )
        self.assertEqual(adapter.calls, ["research", "extract"])


if __name__ == "__main__":
    unittest.main()
