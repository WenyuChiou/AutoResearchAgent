"""Host relocation is opt-in evidence, never runtime or acceptance bypass."""

from copy import deepcopy
from datetime import datetime, timezone
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

import test_stage1_deliverable as fixtures

from research_workspace import host_replay
from research_workspace.saved_admission import inspect_saved_admission
from stage1_deliverable import package, sources
from stage1_deliverable.common import (
    DeliverableError,
    canonical,
    inventory,
    read_json,
    sha,
    write_json,
)


class HostReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixtures.ResearchDeliverableTests.setUpClass()
        fixture = fixtures.ResearchDeliverableTests()
        fixture.setUp()
        cls.addClassCleanup(fixture.doCleanups)
        fixture.make_records()
        cls.runtime = sources.runtime_binding()
        with patch.object(sources, "runtime_binding", return_value=cls.runtime):
            fixture.build()
        cls.template = fixture.output

    def setUp(self):
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name).resolve()
        self.output = self.root / "package"
        shutil.copytree(self.template, self.output)
        self.archive = self.output / "sources/src1"
        self.old_root = self.root / "historical-exporter"
        self.old_root.mkdir()
        (self.old_root / "__init__.py").write_text("# historical fixture only\n")
        self.replayer_root = Path(sources.__file__).parent
        self.old_exe = str(self.root / "old-host/python")
        fresh = read_json(self.archive / "validation.json")
        old = deepcopy(fresh)
        old["command"][0] = self.old_exe
        write_json(self.archive / "validation.json", old)
        historical = deepcopy(self.runtime)
        historical["exporter_sha256"] = sha(
            canonical(host_replay.exporter_files(self.old_root))
        )
        manifest = read_json(self.output / "provenance_manifest.json")
        manifest["runtime"] = historical
        manifest["files"] = inventory(self.output)
        write_json(self.output / "provenance_manifest.json", manifest)
        self.manifest_ref = self.ref("package/provenance_manifest.json")
        self.snapshot = {
            "project_id": "synthetic",
            "input_version": "input1",
            "bindings": {"deliverable": self.manifest_ref},
        }
        write_json(self.root / "snapshot.json", self.snapshot)
        self.snapshot_ref = self.ref("snapshot.json")
        checked = json.loads(fresh["stdout"])["checked_at"]
        self.receipt = {
            "kind": "HostReplayReceipt",
            "schema_version": "1.0.0",
            "project_id": "synthetic",
            "input_version": "input1",
            "snapshot_ref": self.snapshot_ref,
            "canonical_manifest_sha256": self.manifest_ref["sha256"],
            "historical_producer": {
                "runtime": historical,
                "executable": self.old_exe,
                "exporter_files": host_replay.exporter_files(self.old_root),
            },
            "replayer": {
                "runtime": self.runtime,
                "executable": sys.executable,
                "exporter_files": host_replay.exporter_files(self.replayer_root),
            },
            "validator": {
                "runtime": self.runtime,
                "files": host_replay.validator_files(),
            },
            "sources": [
                {
                    "source_id": "src1",
                    "work_id": "work1",
                    "version_id": "v1",
                    "files": inventory(self.archive),
                    "historical_observation_sha256": sha(
                        (self.archive / "validation.json").read_bytes()
                    ),
                    "observation": fresh,
                    "started_at": checked,
                    "ended_at": checked,
                }
            ],
        }

    def ref(self, name):
        raw = (self.root / name).read_bytes()
        return {"path": name, "sha256": sha(raw), "bytes": len(raw)}

    def load(self, *, snapshot_ref=None, trusted=None):
        path = self.root / "host-replay.json"
        write_json(path, self.receipt)
        with patch.object(sources, "runtime_binding", return_value=self.runtime):
            return host_replay.load_host_replay(
                path,
                trusted or sha(path.read_bytes()),
                self.root,
                snapshot_ref or self.snapshot_ref,
                historical_exporter_root=self.old_root,
                replayer_exporter_root=self.replayer_root,
            )

    def test_real_saved_source_and_all_views_replay_without_source_reexecution(self):
        before = inventory(self.output)
        with patch.object(
            sources,
            "validate_archive",
            side_effect=AssertionError("must reuse saved replay"),
        ):
            context = self.load()
            with patch.object(sources, "runtime_binding", return_value=self.runtime):
                result = package.validate(
                    self.output, self.manifest_ref["sha256"], host_replay=context
                )
        self.assertEqual(result["status"], "passed")
        self.assertFalse(result["scientific_quality_scored"])
        self.assertFalse(context.evidence()["core_acceptance"])
        self.assertEqual(inventory(self.output), before)

    def test_default_package_and_observation_still_reject_relocation(self):
        with patch.object(sources, "runtime_binding", return_value=self.runtime):
            with self.assertRaisesRegex(DeliverableError, "runtime bytes changed"):
                package.validate(self.output, self.manifest_ref["sha256"])
        result = read_json(self.archive / "original.json")
        with self.assertRaisesRegex(DeliverableError, "observation differs"):
            sources.validate_observation(
                self.archive,
                result,
                sources.artifact_map(result),
                self.receipt["sources"][0]["observation"],
            )

    def test_rehashed_receipt_identity_coverage_and_runtime_tampering_rejects(self):
        original = deepcopy(self.receipt)
        mutations = {
            "project": lambda r: r.update(project_id="other"),
            "input": lambda r: r.update(input_version="other"),
            "snapshot": lambda r: r["snapshot_ref"].update(sha256="0" * 64),
            "canonical": lambda r: r.update(canonical_manifest_sha256="0" * 64),
            "missing": lambda r: r.update(sources=[]),
            "duplicate": lambda r: r["sources"].append(deepcopy(r["sources"][0])),
            "work": lambda r: r["sources"][0].update(work_id="other"),
            "version": lambda r: r["sources"][0].update(version_id="other"),
            "source": lambda r: r["sources"][0].update(source_id="other"),
            "dependency": lambda r: r["replayer"]["runtime"].update(
                python_sha256="0" * 64
            ),
            "validator": lambda r: r["validator"]["files"].update(
                {"forged.py": "0" * 64}
            ),
            "exporter": lambda r: r["historical_producer"]["exporter_files"].update(
                {"extra.py": "0" * 64}
            ),
            "old-observation": lambda r: r["sources"][0].update(
                historical_observation_sha256="0" * 64
            ),
            "inventory": lambda r: r["sources"][0]["files"].pop("original.json"),
            "new-interpreter": lambda r: r["replayer"].update(executable="other"),
            "old-interpreter": lambda r: r["historical_producer"].update(
                executable="other"
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.receipt = deepcopy(original)
                mutate(self.receipt)
                with self.assertRaises((DeliverableError, ValueError)):
                    self.load()

    def test_fresh_observation_command_report_and_process_tampering_rejects(self):
        original = deepcopy(self.receipt)
        for field, value in (
            ("returncode", 1),
            ("returncode", False),
            ("network_acquisition", True),
            ("stderr", "changed"),
            ("original_sha256", "0" * 64),
            ("relocated_sha256", "0" * 64),
            ("stdout", "not JSON"),
        ):
            with self.subTest(field=field):
                self.receipt = deepcopy(original)
                self.receipt["sources"][0]["observation"][field] = value
                with self.assertRaises(ValueError):
                    self.load()
        for offset in range(9):
            with self.subTest(command_offset=offset):
                self.receipt = deepcopy(original)
                self.receipt["sources"][0]["observation"]["command"][offset] = "changed"
                with self.assertRaises(ValueError):
                    self.load()
        for field, value in (
            ("valid", False),
            ("errors", ["failure"]),
            ("source_version", "wrong"),
            ("result_path", "wrong"),
            ("output_dir", "wrong"),
            ("receipt_sha256", "0" * 64),
            ("checked_at", "2001-01-01T00:00:00Z"),
        ):
            with self.subTest(report=field):
                self.receipt = deepcopy(original)
                observation = self.receipt["sources"][0]["observation"]
                report = json.loads(observation["stdout"])
                report[field] = value
                observation["stdout"] = json.dumps(report)
                with self.assertRaises(ValueError):
                    self.load()

    def test_changed_body_hash_and_stale_external_receipt_fail(self):
        with self.assertRaisesRegex(DeliverableError, "external SHA"):
            self.load(trusted="0" * 64)
        original = read_json(self.archive / "original.json")
        relative = sources.artifact_map(original)[original["raw_path"]]
        (self.archive / relative).write_bytes(b"different body")
        # Even rehashing the external raw inventory cannot change the original receipt.
        self.receipt["sources"][0]["files"] = inventory(self.archive)
        with self.assertRaisesRegex(DeliverableError, "source hash changed"):
            self.load()

    def test_historical_code_is_read_only_never_executed(self):
        path = self.old_root / "__init__.py"
        path.write_text(
            "raise RuntimeError('untrusted attachment must never execute')\n"
        )
        with self.assertRaisesRegex(DeliverableError, "source code inventory changed"):
            self.load()

    def test_context_rechecks_after_loading(self):
        context = self.load()
        (self.output / "papers.jsonl").write_bytes(b"changed")
        with patch.object(sources, "runtime_binding", return_value=self.runtime):
            with self.assertRaisesRegex(DeliverableError, "inventory or bytes"):
                package.validate(
                    self.output, self.manifest_ref["sha256"], host_replay=context
                )

    def test_partial_host_arguments_do_not_change_legacy_admission(self):
        with (
            patch(
                "research_workspace.saved_admission.read_bound_json",
                return_value=self.snapshot,
            ),
            patch("research_workspace.saved_admission.check_snapshot"),
        ):
            with self.assertRaisesRegex(ValueError, "all host replay inputs"):
                inspect_saved_admission(
                    self.root, self.snapshot_ref, host_replay_receipt="only-one"
                )

    def test_external_receipt_parses_the_same_single_verified_snapshot(self):
        target = self.root / "host-replay.json"
        trusted = canonical(self.receipt) + b"\n"
        replacement = canonical({**self.receipt, "project_id": "replacement"})
        original_read = Path.read_bytes
        reads = []

        def changing_read(path):
            if path == target:
                reads.append(path)
                return trusted if len(reads) == 1 else replacement
            return original_read(path)

        with patch.object(Path, "read_bytes", changing_read):
            context = self.load(trusted=sha(trusted))
        self.assertEqual(reads, [target])
        self.assertEqual(context._receipt, self.receipt)
        self.assertEqual(context.evidence()["sha256"], sha(trusted))

    def test_source_json_replacement_after_inventory_hash_is_rejected(self):
        original_read = Path.read_bytes
        for name in ("original.json", "validation.json"):
            target = self.archive / name
            trusted = target.read_bytes()
            replacement = canonical({"replacement": True})
            reads = []

            def changing_read(path):
                if path == target:
                    reads.append(path)
                    return trusted if len(reads) == 1 else replacement
                return original_read(path)

            with (
                self.subTest(name=name),
                patch.object(Path, "read_bytes", changing_read),
            ):
                with self.assertRaisesRegex(DeliverableError, "trusted external SHA"):
                    self.load()
            self.assertEqual(len(reads), 2)

    def test_trusted_receipt_rejects_duplicate_nonfinite_and_non_utf8_json(self):
        target = self.root / "host-replay.json"
        original_read = Path.read_bytes
        for raw in (
            b'{"kind":"first","kind":"second"}',
            b'{"invalid":NaN}',
            b'{"invalid":Infinity}',
            b'{"invalid":1e999}',
            b'{"invalid":"\xff"}',
        ):
            with (
                self.subTest(raw=raw),
                patch.object(
                    Path,
                    "read_bytes",
                    lambda path: raw if path == target else original_read(path),
                ),
            ):
                with self.assertRaises(ValueError):
                    self.load(trusted=sha(raw))

    def test_other_synthetic_topic_migrates_to_unicode_space_root_with_stale_pin_rejected(
        self,
    ):
        producer = self.root / "Producer 原始 space"
        receiver = self.root / "Different receiver 接收 space"
        producer.mkdir()
        receiver.mkdir()
        fixture = fixtures.ResearchDeliverableTests()
        fixture.root = producer
        fixture.inputs = producer / "input"
        fixture.inputs.mkdir()
        fixture.output = producer / "package"
        title = "Synthetic coastal sensor battery calibration"
        records = fixture.make_records(
            raw=fixtures.HTML.replace(fixtures.TITLE.encode(), title.encode()),
            title=title,
        )
        records["topic"] = "Authored coastal sensor fixture, not a research subject."
        with patch.object(sources, "runtime_binding", return_value=self.runtime):
            built = fixture.build(records)
        shutil.copytree(fixture.output, receiver / "package")
        old_manifest = read_json(fixture.output / "provenance_manifest.json")
        old_observation = (fixture.output / "sources/src1/validation.json").read_bytes()
        producer.rename(self.root / "Archived producer 封存 space")
        self.assertFalse(producer.exists())
        archive = receiver / "package/sources/src1"
        before = inventory(receiver / "package")
        started = datetime.now(timezone.utc).isoformat()
        _, _, fresh = sources.validate_archive(archive)
        ended = datetime.now(timezone.utc).isoformat()
        snapshot = {
            "project_id": "synthetic-sensor-portability",
            "input_version": "sensor-fixture-1",
            "bindings": {
                "deliverable": {
                    "path": "package/provenance_manifest.json",
                    "bytes": (receiver / "package/provenance_manifest.json")
                    .stat()
                    .st_size,
                    "sha256": built["manifest_sha256"],
                }
            },
        }
        write_json(receiver / "snapshot.json", snapshot)
        snapshot_ref = {
            "path": "snapshot.json",
            "bytes": (receiver / "snapshot.json").stat().st_size,
            "sha256": sha((receiver / "snapshot.json").read_bytes()),
        }
        code_root = Path(sources.__file__).parent
        producer_binding = {
            "runtime": old_manifest["runtime"],
            "executable": sys.executable,
            "exporter_files": host_replay.exporter_files(code_root),
        }
        receipt = {
            "kind": "HostReplayReceipt",
            "schema_version": "1.0.0",
            "project_id": snapshot["project_id"],
            "input_version": snapshot["input_version"],
            "snapshot_ref": snapshot_ref,
            "canonical_manifest_sha256": built["manifest_sha256"],
            "historical_producer": producer_binding,
            "replayer": deepcopy(producer_binding),
            "validator": {
                "runtime": self.runtime,
                "files": host_replay.validator_files(),
            },
            "sources": [
                {
                    "source_id": "src1",
                    "work_id": "work1",
                    "version_id": "v1",
                    "files": inventory(archive),
                    "historical_observation_sha256": sha(old_observation),
                    "observation": fresh,
                    "started_at": started,
                    "ended_at": ended,
                }
            ],
        }
        path = receiver / "host-replay.json"
        write_json(path, receipt)
        with (
            patch.object(sources, "runtime_binding", return_value=self.runtime),
            patch.object(
                sources, "validate_archive", side_effect=AssertionError("no repeat")
            ),
        ):
            with self.assertRaisesRegex(DeliverableError, "trusted external SHA"):
                host_replay.load_host_replay(
                    path,
                    "0" * 64,
                    receiver,
                    snapshot_ref,
                    historical_exporter_root=code_root,
                    replayer_exporter_root=code_root,
                )
            context = host_replay.load_host_replay(
                path,
                sha(path.read_bytes()),
                receiver,
                snapshot_ref,
                historical_exporter_root=code_root,
                replayer_exporter_root=code_root,
            )
            checked = package.validate(
                receiver / "package", built["manifest_sha256"], host_replay=context
            )
        self.assertEqual(checked["status"], "passed")
        self.assertFalse(checked["scientific_quality_scored"])
        self.assertEqual(before, inventory(receiver / "package"))
        self.assertEqual((archive / "validation.json").read_bytes(), old_observation)
        self.assertEqual(
            read_json(receiver / "package/provenance_manifest.json"), old_manifest
        )


if __name__ == "__main__":
    unittest.main()
