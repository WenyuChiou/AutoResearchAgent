"""Real workflow objects; synthetic content grants no execution authority."""

import copy
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage2_common import Stage2Error, canonical_hash  # noqa: E402
from stage2_live import controller  # noqa: E402
from stage2_workflow import registered_history as history, store  # noqa: E402
from stage2_fixture_helpers import write_stage2_fixture  # noqa: E402
import test_stage2_windows_atomic_io as atomic_fixture  # noqa: E402
import test_stage2_interaction as interaction_fixture  # noqa: E402
import test_project_stage2_controller as driver_fixture  # noqa: E402


class WorkflowConsumerTests(unittest.TestCase):
    setUp = atomic_fixture.AtomicPublicationTests.setUp
    cleanup_long_tree = atomic_fixture.AtomicPublicationTests.cleanup_long_tree

    def workflow(self):
        packet = write_stage2_fixture(self.root / "sources", candidate_count=1)
        packet_path = self.root / "packet.json"
        packet_path.write_text(json.dumps(packet), encoding="utf-8")
        root = self.root / ("w" * (185 - len(str(self.root)) - 1))
        store.initialize_workflow(
            packet_path,
            self.root / "sources",
            root,
            {"model": "test-model", "reasoning": "medium"},
            {"path": "policy.json", "sha256": "a" * 64},
        )
        if os.name == "nt":
            self.addCleanup(self.cleanup_long_tree, root)
        return root

    def ui_action(self):
        root = self.workflow()
        state = store.inspect_workflow(root)
        action_id = "ui-choice-" + "a" * 64
        started = store.start_action(
            root, action_id, "synthetic", {}, {}, state["head_sha256"]
        )
        artifacts = {}
        for name in (
            "interaction.json",
            "delivery_manifest.json",
            "projecthost-user-submission.json",
        ):
            path = self.root / name
            path.write_bytes(b'{"synthetic":true}')
            artifacts[name] = {
                "path": str(path),
                "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
            }
        finished = store.finish_action(
            root,
            action_id,
            "complete",
            artifacts,
            None,
            None,
            started["event"]["event_sha256"],
        )
        return root, action_id, store.inspect_workflow(root, finished["event_sha256"])

    def test_controller_two_real_reads_long_summary_short_equivalence_and_hash_order(
        self,
    ):
        root = self.workflow()
        name = "actions/" + "r" * 53 + "/summary.json"
        path = root / name
        self.assertEqual(len(str(path)), 260)
        store._io(path.parent).mkdir(parents=True)
        raw = b'{"value":"synthetic","lines":[1,null]}\r\n'
        store._write_new(path, raw)
        result = {
            "artifacts": {
                "summary.json": {
                    "stored_path": name,
                    "sha256": hashlib.sha256(raw).hexdigest(),
                }
            }
        }
        with patch.object(
            controller, "_workflow_bytes", wraps=store._workflow_bytes
        ) as reads:
            value = controller._artifact_value({"root": root}, result)
        self.assertEqual(reads.call_count, 2)
        short = self.root / "summary.json"
        short.write_bytes(raw)
        result["artifacts"]["summary.json"]["stored_path"] = short.name
        self.assertEqual(controller._artifact_value({"root": self.root}, result), value)
        result["artifacts"]["summary.json"]["stored_path"] = name
        store._io(path).write_bytes(b"invalid JSON with different hash")
        with patch.object(
            controller, "_workflow_bytes", wraps=store._workflow_bytes
        ) as reads:
            with self.assertRaisesRegex(Stage2Error, "summary-hash-mismatch"):
                controller._artifact_value({"root": root}, result)
        self.assertEqual(reads.call_count, 1)

    def test_full_hash_ui_action_sizes_and_complete_recovery(self):
        original = os.link
        with patch.object(store.os, "link", wraps=original) as links:
            root, action_id, state = self.ui_action()
        action = root / "actions" / action_id
        self.assertEqual(len(str(action)), 268)
        self.assertEqual(len(str(action / "request.json")), 281)
        self.assertEqual(
            sorted(
                len(str(root / row["stored_path"]))
                for row in state["actions"][action_id]["result"]["artifacts"].values()
            ),
            [295, 301, 311],
        )
        self.assertTrue(
            any(
                len(os.fspath(call.args[0]).removeprefix("\\\\?\\"))
                >= 311 + len(str(os.getpid())) + 6
                for call in links.call_args_list
            )
        )
        reused = store.start_action(
            root, action_id, "synthetic", {}, {}, state["head_sha256"]
        )
        self.assertTrue(reused["reuse"])
        self.assertEqual(store.inspect_workflow(root)["events"], state["events"])

    def test_explicit_core_interaction_replay_reads_295_chars_without_append(self):
        fixture = interaction_fixture.Stage2InteractionTests(
            "test_selected_version_and_native_text_bound_without_execution_grant"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        f = fixture.fixture
        root = f.root / ("w" * (185 - len(str(f.root)) - 1))
        f.workflow.rename(root)
        f.workflow = root
        if os.name == "nt":
            self.addCleanup(
                atomic_fixture.AtomicPublicationTests.cleanup_long_tree, f, root
            )
        action_id = "ui-choice-" + "b" * 64
        first = fixture.invoke(action_id=action_id)
        before = store.inspect_workflow(root)
        stored = before["actions"][action_id]["result"]["artifacts"][
            "interaction.json"
        ]["stored_path"]
        self.assertEqual(len(str(root / stored)), 295)
        reused = fixture.invoke(action_id=action_id, head=first["head_sha256"])
        self.assertTrue(reused["reuse"])
        self.assertEqual(reused["record"], first["record"])
        self.assertEqual(store.inspect_workflow(root)["events"], before["events"])
        self.assertEqual(reused["head_sha256"], before["head_sha256"])

    def test_long_registered_history_capture_replay_and_inventory_rejections(self):
        root, _, state = self.ui_action()
        provenance, files = history.capture_registered_history(state)
        output = self.root / (
            "h" * (185 - len(str(self.root)) - len(history.ARCHIVE) - 2)
        )
        for name, raw in files.items():
            path = output / name
            store._io(path.parent).mkdir(parents=True, exist_ok=True)
            store._io(path).write_bytes(raw)
        if os.name == "nt":
            self.addCleanup(self.cleanup_long_tree, output)
        self.assertTrue(
            all(
                "\\" not in row["path"]
                and row["size_bytes"] == len(files[row["path"]])
                and row["sha256"] == hashlib.sha256(files[row["path"]]).hexdigest()
                for row in provenance["files"]
            )
        )
        payload = state["latest_snapshot"]["event"]["payload"]
        manifest = {key: state["manifest"][key] for key in ("manifest_sha256",)}
        manifest = {
            "workflow_manifest_sha256": manifest["manifest_sha256"],
            "workflow_head_sha256": state["head_sha256"],
            "snapshot_sequence": payload["snapshot_sequence"],
            "snapshot_sha256": payload["snapshot_sha256"],
            "snapshot_checker_manifest_sha256": payload["checker_manifest_sha256"],
            "revision_provenance_scope": history.SCOPE,
            "revision_provenance_sha256": canonical_hash(provenance),
        }
        packet = state["latest_snapshot"]["packet"]
        self.assertEqual(
            history.inspect_registered_history(output, provenance, packet, manifest), []
        )
        extra = output / history.ARCHIVE / "extra.txt"
        store._io(extra).write_bytes(b"unlisted")
        with self.assertRaisesRegex(Stage2Error, "file-set-mismatch"):
            history.inspect_registered_history(output, provenance, packet, manifest)
        store._io(extra).unlink()
        bad = copy.deepcopy(provenance)
        bad["files"][0]["path"] = history.ARCHIVE + "/../escape"
        manifest["revision_provenance_sha256"] = canonical_hash(bad)
        with self.assertRaisesRegex(Stage2Error, "unsafe-registered-history-path"):
            history.inspect_registered_history(output, bad, packet, manifest)
        artifact = next(
            name for name in files if name.endswith("/artifacts/interaction.json")
        )
        store._io(output / artifact).write_bytes(b"tampered")
        manifest["revision_provenance_sha256"] = canonical_hash(provenance)
        with self.assertRaisesRegex(Stage2Error, "file-hash-mismatch"):
            history.inspect_registered_history(output, provenance, packet, manifest)

    def test_guard_relative_missing_and_nonmissing_observation_errors(self):
        workflow = self.workflow()
        target = self.root / "record.json"
        target.write_bytes(b"actual bytes")
        previous = Path.cwd()
        try:
            os.chdir(self.root)
            self.assertEqual(
                store.inspect_workflow(Path(workflow.name))["root"], workflow
            )
            self.assertEqual(
                store._workflow_bytes(Path("."), "record.json", "test"), b"actual bytes"
            )
            for name in (
                "../record.json",
                "./record.json",
                "x//file",
                "x\\file",
                "file:stream",
                "/record.json",
            ):
                with self.subTest(name=name), self.assertRaises(Stage2Error):
                    store._workflow_bytes(Path("."), name, "test")
        finally:
            os.chdir(previous)
        self.assertFalse(store._workflow_status(self.root, "missing", "exists", "test"))
        for operation, invoke in (
            (
                "read_bytes",
                lambda: store._workflow_bytes(self.root, "record.json", "test"),
            ),
            (
                "stat",
                lambda: store._workflow_status(
                    self.root, "record.json", "file", "test"
                ),
            ),
            (
                "lstat",
                lambda: store._workflow_status(
                    self.root, "record.json", "symlink", "test"
                ),
            ),
            (
                "iterdir",
                lambda: list(store._workflow_entries(self.root, "folder", "test")),
            ),
        ):
            with (
                self.subTest(operation=operation),
                patch.object(
                    Path, operation, side_effect=PermissionError("synthetic denied")
                ),
                self.assertRaises(PermissionError),
            ):
                invoke()
        with (
            patch.object(
                Path, "iterdir", side_effect=PermissionError("synthetic denied")
            ),
            self.assertRaises(PermissionError),
        ):
            list(store._entries(self.root, "*.json"))

    @unittest.skipUnless(os.name == "nt", "Real Windows long junction observation")
    def test_real_long_junction_escape_is_observed_and_rejected(self):
        parent = self.root / ("p" * (236 - len(str(self.root)) - 1))
        parent.mkdir()
        target = self.root / "outside-workflow"
        target.mkdir()
        (target / "record.json").write_bytes(b"outside bytes")
        link = parent / ("j" * 40)
        completed = subprocess.run(
            ["cmd", "/c", "mklink", "/J", str(store._io(link)), str(target)],
            capture_output=True,
            check=False,
        )
        self.assertEqual(completed.returncode, 0, completed.stderr)
        self.addCleanup(os.rmdir, store._io(link))
        self.assertTrue(store._io(link).lstat().st_reparse_tag)
        with self.assertRaisesRegex(Stage2Error, "escaping-test-path"):
            store._workflow_bytes(parent, link.name + "/record.json", "test")

    def test_postverification_failure_keeps_sealed_result_and_never_redispatches(self):
        cls = driver_fixture.ProjectStage2ControllerTests
        cls.setUpClass()
        self.addCleanup(cls.doClassCleanups)
        fixture = cls(
            "test_sealed_core_result_restores_after_host_result_write_interruption"
        )
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        module = driver_fixture.driver_module
        with patch.object(
            module.ProjectStage2ControllerDriver,
            "_verify_result",
            side_effect=Stage2Error("synthetic postverify refusal"),
        ):
            with self.assertRaisesRegex(Stage2Error, "postverify refusal"):
                fixture.run_driver()
        self.assertEqual(fixture.calls, 1)
        self.assertTrue(
            (fixture.output / "project_stage2_driver/intent.json").is_file()
        )
        self.assertFalse(
            (fixture.output / "project_stage2_driver/result.json").exists()
        )
        self.assertEqual(
            len(list((fixture.output / "controller_results").glob("*.json"))), 1
        )
        with patch.object(
            module, "run_controller", side_effect=AssertionError("redispatch forbidden")
        ) as dispatch:
            restored = fixture.driver().run("own", fixture.ref, key="controller-1")
        dispatch.assert_not_called()
        self.assertTrue(restored["replayed"])
