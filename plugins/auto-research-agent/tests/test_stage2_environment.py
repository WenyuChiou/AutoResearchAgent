"""Execution-specific admission failures; no model or provider execution."""

from pathlib import Path
import copy
import tempfile
import json
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
# ruff: noqa: E402
from stage2_common import Stage2Error
from stage2_live.environment import preflight_for_environment, verify_environment_start
from stage2_live.environment import verify_environment_capture
from stage2_live.native import _path_binding
from stage2_live.preflight import PreflightError


class EnvironmentBindingTests(unittest.TestCase):
    def test_missing_execution_preflight_is_not_inherited(self):
        with self.assertRaisesRegex(Stage2Error, "execution-specific-preflight"):
            preflight_for_environment({"preflight": {"status": "passed"}}, "h", "w")

    def test_effective_runtime_and_missing_inventory_block_replay(self):
        from stage2_live.preflight import _actual_runtime

        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            sessions = root / "archive/native-sessions"
            sessions.mkdir(parents=True)
            context = {
                "model": "m",
                "effort": "high",
                "sandbox_policy": {"type": "workspace-write", "network_access": True},
            }
            session = sessions / "s.jsonl"
            session.write_text(
                json.dumps({"type": "session_meta", "payload": {"id": "s"}})
                + "\n"
                + json.dumps({"type": "turn_context", "payload": context})
                + "\n",
                encoding="utf-8",
            )
            stable = {
                "codex_home": "same-home",
                "workspace": "same-workspace",
                "config_bindings": {},
            }
            actual = {
                "stable_request_binding": stable,
                "started_at": "2026-09-29T01:00:00+00:00",
                "event_summary": {"thread_id": "s"},
                "archived_files": {},
            }
            prior = {
                "stable_request_binding": stable,
                "ended_at": "2026-09-29T00:00:00+00:00",
            }
            preflight = {
                "report": {},
                "capture_dir": "prior",
                "receipt": "b" * 64,
                "probe_spec": {
                    "kind": "Stage2RuntimeProbeSpec",
                    "schema_version": "1.0.0",
                },
                "inventory_receipt": {},
            }
            expected = {
                "kind": "Stage2RuntimePreflight",
                "runtime_gate": True,
                "formal_ready": False,
                "actual_runtime": _actual_runtime(context, "same-workspace"),
            }
            with (
                patch(
                    "stage2_live.environment.verify_preflight", return_value=expected
                ),
                patch(
                    "stage2_live.environment.verify_capture",
                    side_effect=[(actual, ""), (prior, "")],
                ),
            ):
                with self.assertRaisesRegex(Stage2Error, "inventory-not-captured"):
                    verify_environment_capture(root, "a" * 64, preflight, None)
            production = copy.deepcopy(preflight)
            production["probe_spec"]["kind"] = "Stage2ProductionRuntimeProbeSpec"
            production_report = copy.deepcopy(expected)
            production_report.update(
                {
                    "kind": "Stage2ProductionRuntimePreflight",
                    "validation_scope": "production-single",
                    "filesystem_read_isolation": "not-assessed",
                    "quality_improvement": "not-established",
                }
            )
            with (
                patch(
                    "stage2_live.environment.verify_preflight",
                    return_value=production_report,
                ),
                patch(
                    "stage2_live.environment.verify_capture",
                    side_effect=[(actual, ""), (prior, "")],
                ),
            ):
                result = verify_environment_capture(root, "a" * 64, production, None)
            self.assertEqual(result["inventory_status"], "not-captured")
            instruction_path = root / "archive/thread-start.json"
            instruction_path.write_text(
                json.dumps({"result": {"thread": {"id": "foreign-session"}}}),
                encoding="utf-8",
            )
            actual["archived_files"]["archive/thread-start.json"] = "c" * 64
            with (
                patch(
                    "stage2_live.environment.verify_preflight",
                    return_value=production_report,
                ),
                patch(
                    "stage2_live.environment.verify_capture",
                    side_effect=[(actual, ""), (prior, "")],
                ),
                patch(
                    "stage2_live.environment._inventory",
                    return_value=({"instructions": {"status": "present"}}, None),
                ),
            ):
                with self.assertRaisesRegex(Stage2Error, "inventory-thread-mismatch"):
                    verify_environment_capture(
                        root,
                        "a" * 64,
                        production,
                        {
                            "entries": {
                                "instructions": {
                                    "path": "archive/thread-start.json",
                                    "sha256": "c" * 64,
                                }
                            }
                        },
                    )
            expected["actual_runtime"]["model"] = "different-model"
            with (
                patch(
                    "stage2_live.environment.verify_preflight", return_value=expected
                ),
                patch(
                    "stage2_live.environment.verify_capture",
                    side_effect=[(actual, ""), (prior, "")],
                ),
            ):
                with self.assertRaisesRegex(Stage2Error, "effective-policy-differs"):
                    verify_environment_capture(root, "a" * 64, preflight, None)

    def test_different_home_or_changed_profile_blocks_before_execution(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            home = root / "home"
            home.mkdir()
            workspace = root / "workspace"
            workspace.mkdir()
            (home / "config.toml").write_text(
                'sandbox_mode="workspace-write"', encoding="utf-8"
            )
            native = {
                "codex": str(root / "codex"),
                "model": "model",
                "reasoning": "high",
                "policy_bindings": {"sandbox": "workspace-write"},
                "config_bindings": {},
            }
            stable = {
                "codex_home": str(home.resolve()),
                "workspace": str(workspace.resolve()),
                "codex_runtime_sha256": "a" * 64,
                "codex_profile_config": _path_binding(home / "config.toml"),
                "model": "model",
                "reasoning": "high",
                "policy_bindings": native["policy_bindings"],
                "config_bindings": {},
            }
            preflight = {
                "report": {},
                "capture_dir": str(root / "probe"),
                "receipt": "b" * 64,
                "probe_spec": {
                    "kind": "Stage2RuntimeProbeSpec",
                    "schema_version": "1.0.0",
                },
                "inventory_receipt": {},
            }
            report = {
                "kind": "Stage2RuntimePreflight",
                "runtime_gate": True,
                "status": "passed",
                "formal_ready": False,
            }
            with (
                patch("stage2_live.environment.verify_preflight", return_value=report),
                patch(
                    "stage2_live.environment.verify_capture",
                    return_value=({"stable_request_binding": stable}, ""),
                ),
                patch(
                    "stage2_live.environment.codex_runtime_sha", return_value="a" * 64
                ),
            ):
                verify_environment_start(preflight, native, home, workspace)
                with self.assertRaisesRegex(Stage2Error, "codex_home-mismatch"):
                    verify_environment_start(
                        preflight, native, root / "other", workspace
                    )
                (home / "config.toml").write_text(
                    'sandbox_mode="read-only"', encoding="utf-8"
                )
                with self.assertRaisesRegex(Stage2Error, "profile-changed"):
                    verify_environment_start(preflight, native, home, workspace)

    def test_production_selects_typed_child_lineage_but_formal_stays_strict(self):
        from stage2_live.preflight import _actual_runtime

        context = {
            "model": "m",
            "effort": "high",
            "sandbox_policy": {"type": "workspace-write", "network_access": True},
        }

        def verify(events, *, production=True, duplicate=False):
            with tempfile.TemporaryDirectory() as temp:
                root = Path(temp)
                sessions = root / "archive/native-sessions"
                sessions.mkdir(parents=True)
                raw = "\n".join(json.dumps(row) for row in events) + "\n"
                (sessions / "child.jsonl").write_text(raw, encoding="utf-8")
                if duplicate:
                    (sessions / "duplicate.jsonl").write_text(raw, encoding="utf-8")
                stable = {
                    "codex_home": "same-home",
                    "workspace": "same-workspace",
                    "config_bindings": {},
                }
                actual = {
                    "stable_request_binding": stable,
                    "started_at": "2026-10-03T01:00:00+00:00",
                    "event_summary": {"thread_id": "child-thread"},
                    "archived_files": {},
                }
                prior = {
                    "stable_request_binding": stable,
                    "ended_at": "2026-10-03T00:00:00+00:00",
                }
                preflight = {
                    "report": {},
                    "capture_dir": "prior",
                    "receipt": "b" * 64,
                    "probe_spec": {
                        "kind": "Stage2ProductionRuntimeProbeSpec"
                        if production
                        else "Stage2RuntimeProbeSpec",
                        "schema_version": "1.0.0",
                    },
                    "inventory_receipt": {},
                }
                report = {
                    "kind": "Stage2ProductionRuntimePreflight"
                    if production
                    else "Stage2RuntimePreflight",
                    "runtime_gate": True,
                    "formal_ready": False,
                    "actual_runtime": _actual_runtime(context, "same-workspace"),
                }
                if production:
                    report.update(
                        validation_scope="production-single",
                        filesystem_read_isolation="not-assessed",
                        quality_improvement="not-established",
                    )
                with (
                    patch(
                        "stage2_live.environment.verify_preflight",
                        return_value=report,
                    ),
                    patch(
                        "stage2_live.environment.verify_capture",
                        side_effect=[(actual, ""), (prior, "")],
                    ),
                ):
                    return verify_environment_capture(root, "a" * 64, preflight, None)

        authentic_child = [
            {"type": "session_meta", "payload": {"id": "parent-thread"}},
            {
                "type": "session_meta",
                "payload": {
                    "id": "child-thread",
                    "source": {
                        "subagent": {
                            "thread_spawn": {"parent_thread_id": "parent-thread"}
                        }
                    },
                },
            },
            {"type": "turn_context", "payload": context},
        ]
        result = verify(authentic_child)
        self.assertEqual(result["thread_id"], "child-thread")
        self.assertEqual(result["inventory_status"], "not-captured")
        with self.assertRaisesRegex(PreflightError, "conflicting identities"):
            verify(authentic_child, production=False)
        with self.assertRaisesRegex(Stage2Error, "primary-session-not-unique"):
            verify(authentic_child, duplicate=True)

        conflicting_children = copy.deepcopy(authentic_child)
        conflicting_children.insert(
            2,
            {
                "type": "session_meta",
                "payload": {
                    "id": "other-child",
                    "source": {
                        "subagent": {
                            "thread_spawn": {"parent_thread_id": "parent-thread"}
                        }
                    },
                },
            },
        )
        with self.assertRaisesRegex(PreflightError, "child session.*conflicting"):
            verify(conflicting_children)


if __name__ == "__main__":
    unittest.main()
