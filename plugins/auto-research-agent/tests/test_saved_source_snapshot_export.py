"""Real offline exporter/consumer checks; SDK source bytes are authored fixtures."""

import copy
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace.source_rerun import attach_rerun
from research_workspace.view import write_workspace
from stage1_brief.formal_target import prepare_formal_intake, submit_formal_target
from stage1_deliverable.common import canonical, sha
from test_research_brief import brief
from test_research_brief_formal_target import answer
from test_research_workspace_literature_selection import complete_document
import test_research_workspace_source_rerun_exports as rerun
from test_saved_source_admission import snapshot_fixture
import test_stage1_deliverable as deliverable_fixture


from stage1_ledger.store import Ledger
from test_stage1_ledger import add_query, SYNTHETIC
from research_workspace.saved_source_snapshot import export_snapshot, _inventory
import subprocess
import os
import tempfile


class SavedSnapshotExportTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        deliverable_fixture.ResearchDeliverableTests.setUpClass()

    def setUp(self):
        fixture = deliverable_fixture.ResearchDeliverableTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        self.root = fixture.root
        ledger = Ledger.create(
            self.root / "native",
            run_id="synthetic-export-run",
            objective="Authored fixture only",
            clock=lambda: "2026-01-01T00:00:00Z",
        )
        add_query(ledger, [SYNTHETIC])
        ledger.extract()
        candidate = next(
            e["payload"]
            for e in ledger.events()
            if e["payload"]["kind"] == "CandidateRevision"
        )
        self.work, self.version = candidate["work_id"], candidate["version_ids"][0]
        records = fixture.make_records()
        replacements = {
            "work1": self.work,
            "v1": self.version,
            "src1": "source-0",
        }

        def rename(value):
            if isinstance(value, dict):
                return {key: rename(item) for key, item in value.items()}
            if isinstance(value, list):
                return [rename(item) for item in value]
            return replacements.get(value, value) if isinstance(value, str) else value

        records = rename(records)
        fixture.build(records)
        package_ref = self.ref(fixture.output / "provenance_manifest.json")
        original = fixture.inputs / "source/source-fetch-result.json"
        receipt = json.loads(original.read_bytes())
        raw = Path(receipt["raw_path"]).read_bytes()
        text = Path(receipt["extracted_text_path"]).read_bytes()
        source = ledger.start_source(
            work_id=self.work,
            version_id=self.version,
            source_uri=receipt["final_url"],
            tool="authored-fixture",
            request={"fixture": "saved authored bytes; no external call"},
            actor="synthetic-agent",
            reason="Offline fixture only",
        )
        ledger.finish_source(
            attempt_id=source,
            outcome="available",
            observed_at=ledger.clock(),
            http_status=None,
            resolved_uri=receipt["final_url"],
            raw_ref=ledger.save_bytes(raw, producer=source),
            text_ref=ledger.save_bytes(text, producer=source),
            extraction={"method": "authored-fixture", "version": "1"},
            reason="Synthetic input",
        )
        checkpoint = ledger.checkpoint()
        note = self.save("note.json", {"fixture": "A complete authored source note."})
        companion = self.save("companion.json", {"notes": [note]})
        provenance = self.ref(original)
        with (
            patch.dict(rerun.RAW, {"source-0": raw}),
            patch.dict(rerun.TEXT, {"source-0": text}),
        ):
            replacements.update({"fixture-0": self.work, "version-0": self.version})
            index = rename(rerun.fixture_index())
            index["provenance"]["deliverable_manifest_sha256"] = package_ref["sha256"]
            paper = copy.deepcopy(records["papers"][0])
            paper.update(
                input_version="fresh-1",
                fresh_note={
                    "paper_note_status": "complete",
                    "companion_binding": {
                        **note,
                        "companion_manifest_sha256": companion["sha256"],
                    },
                    "source_qualification": {
                        "status": "qualified",
                        "work_id": paper["work_id"],
                        "version_id": paper["version_id"],
                        "source_id": "source-0",
                        "raw_sha256": sha(raw),
                        "text_sha256": sha(text),
                        "identity_checked": True,
                        "body_checked": True,
                        "reading_order_checked": True,
                        "relevance_checked": True,
                        "evidence_refs": ["synthetic-review:1"],
                    },
                },
            )
            index["papers"][0] = paper
            index["sources"][0].update(
                receipt=receipt,
                result_sha256=provenance["sha256"],
                attempts=[
                    json.loads(line)
                    for line in (fixture.output / "paper_manifest.jsonl")
                    .read_bytes()
                    .splitlines()
                ],
            )
            manifest = rerun.fixture_manifest(index)
            index["papers"] = index["papers"][:1]
            index["sources"] = index["sources"][:1]
            index["coverage"] = [
                {
                    "need_id": "synthetic-need",
                    "status": "qualified",
                    "work_ids": [self.work],
                    "evidence_refs": ["synthetic-need:1"],
                }
            ]
            rerun.refresh_bibliography(index)
            manifest["data"]["rows"] = manifest["data"]["rows"][:1]
            manifest["data"]["rows"][0]["final_url"] = receipt["final_url"]
            manifest["data"]["rows"][0]["metadata"]["journal"] = paper["venue"]
            manifest["data"]["rows"][0]["metadata_provenance"]["journal"]["value"] = (
                paper["venue"]
            )
            manifest["data"]["base_index_sha256"] = sha(canonical(index))
            manifest["data"]["rows"][0]["attempt_id"] = sha(
                canonical(
                    {
                        "base": manifest["data"]["base_index_sha256"],
                        "parser": manifest["data"]["parser_runtime"]["parser_sha256"],
                        "work": self.work,
                        "version": self.version,
                        "raw": sha(raw),
                    }
                )
            )
            complete_document(manifest["data"]["rows"][0])
            manifest["files"] = {
                name: row
                for name, row in manifest["files"].items()
                if name.startswith("sources/source-0/")
            }
            rerun_root = self.root / "rerun"
            rerun_root.mkdir()
            digest = rerun.write_manifest(rerun_root, manifest)
            self.base_index = copy.deepcopy(index)
            self.rerun_manifest = copy.deepcopy(manifest)
            index = attach_rerun(index, rerun_root, digest)
        view = self.root / "view"
        write_workspace(
            index,
            Path(__file__).parents[1] / "references/research-workspace",
            view,
            source_rerun_root=rerun_root,
        )
        intake = prepare_formal_intake(
            brief("unrestricted"),
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        submission = answer(1)
        submission.update(
            project_id=index["project_id"],
            input_version="fresh-1",
            request_id="count-1",
        )
        intake = submit_formal_target(intake, submission)
        intake["needs"] = [{"need_id": "synthetic-need", "question": "Synthetic need?"}]
        snapshot = snapshot_fixture(count=1)
        snapshot.update(project_id=index["project_id"], input_version="fresh-1")
        snapshot["bindings"] = {
            "original_request": self.save(
                "request.txt", b"Synthetic saved source request"
            ),
            "brief": self.save("brief.json", intake),
            "resources": self.save(
                "resources.json",
                {
                    "project_id": index["project_id"],
                    "input_version": "fresh-1",
                    "no_resource_reset": True,
                    "current_round_used": {
                        "queries": 1,
                        "full_source_acquisition_attempts": 1,
                    },
                    "previous_cumulative_used": {
                        "queries": 2,
                        "full_source_acquisition_attempts": 2,
                    },
                    "total_authorized_limits": {
                        "queries": 3,
                        "full_source_acquisition_attempts": 3,
                    },
                },
            ),
            "deliverable": package_ref,
            "view": self.ref(view / "view-manifest.json"),
            "companion": companion,
        }
        row = manifest["data"]["rows"][0]
        snapshot["rows"] = [
            {
                "work_id": self.work,
                "version_id": self.version,
                "source_id": "source-0",
                "raw_source": self.ref(rerun_root / row["raw_path"]),
                "extracted_text": self.ref(rerun_root / row["extracted_path"]),
                "full_note": note,
                "acquisition_provenance": provenance,
                "original_acquired_at": None,
            }
        ]
        self.snapshot_ref = self.save("snapshot.json", snapshot)
        self.view = view
        self.package = fixture.output
        self.fixture = fixture
        self.records = records
        self.index = index
        self.rerun_root = rerun_root

        self.ledger = ledger
        self.request = {
            k: snapshot[k]
            for k in (
                "project_id",
                "input_version",
                "admission_id",
                "recorded_at",
                "bindings",
            )
        }
        row = snapshot["rows"][0]
        self.request["materials"] = [
            {
                k: v
                for k, v in row.items()
                if k not in ("work_id", "version_id", "original_acquired_at")
            }
        ]
        self.request["ledger_path"] = "native"
        self.request["checkpoint_event_id"] = checkpoint["event_id"]
        self.request["project_state"] = self.save(
            "project-state.json",
            {
                "project_ref": snapshot["project_id"],
                "input_version": snapshot["input_version"],
                "stage1_active": "synthetic-run",
                "stage1_runs": {
                    "synthetic-run": {
                        "last_checkpoint": checkpoint["event_id"],
                        "manifest_sha256": sha(
                            (ledger.root / "run_manifest.json").read_bytes()
                        ),
                        "binding": {
                            "project_id": snapshot["project_id"],
                            "input_version": snapshot["input_version"],
                            "brief_sha256": snapshot["bindings"]["brief"]["sha256"],
                        },
                    }
                },
            },
        )
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.output = Path(temp.name) / "export"

    def ref(self, path):
        raw = path.read_bytes()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": sha(raw),
            "bytes": len(raw),
        }

    def save(self, name, value):
        path = self.root / name
        path.write_bytes(value if isinstance(value, bytes) else canonical(value))
        return self.ref(path)

    def export(self):
        return export_snapshot(
            self.root, self.save("export-request.json", self.request), self.output
        )

    def test_cli_export_reopen_consumer_and_idempotency(self):
        ref = self.save("export-request.json", self.request)
        ref_file = self.root / "request-ref.json"
        ref_file.write_bytes(canonical(ref))
        before = _inventory(self.root)
        env = dict(
            os.environ,
            PYTHONPATH=str(Path(__file__).parents[1] / "cli"),
            PYTHONDONTWRITEBYTECODE="1",
        )
        command = [
            sys.executable,
            "-B",
            "-m",
            "research_workspace.saved_admission",
            "export-snapshot",
            str(self.root),
            "--request-ref",
            str(ref_file),
            "--output",
            str(self.output),
        ]
        first = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(first.returncode, 0, first.stderr)
        result = json.loads(first.stdout)
        pinned = _inventory(self.output)
        second = subprocess.run(command, env=env, capture_output=True, text=True)
        self.assertEqual(second.returncode, 0, second.stderr)
        self.assertEqual(json.loads(second.stdout), result)
        consumer = subprocess.run(
            [
                sys.executable,
                "-B",
                "-m",
                "research_workspace.saved_admission",
                str(self.output),
                "--snapshot-ref",
                str(self.output / "snapshot-ref.json"),
            ],
            env=env,
            capture_output=True,
            text=True,
        )
        self.assertEqual(consumer.returncode, 0, consumer.stderr)
        self.assertEqual(json.loads(consumer.stdout), result["handoff"])
        self.assertFalse(result["eligible_for_stage2"])
        self.assertEqual(pinned, _inventory(self.output))
        self.assertEqual(before, _inventory(self.root))

    def test_wrong_project_and_typed_version_reject(self):
        for key, value in (
            ("project_id", "other"),
            ("input_version", 1),
            ("input_version", True),
        ):
            with self.subTest(key=key, value=value):
                old = self.request[key]
                self.request[key] = value
                try:
                    with self.assertRaises(ValueError):
                        self.export()
                    self.assertFalse(self.output.exists())
                finally:
                    self.request[key] = old

    def test_missing_note_reports_missing_without_snapshot_or_ledger_write(self):
        self.request["materials"][0]["full_note"] = None
        before = _inventory(self.ledger.root)
        result = self.export()
        self.assertEqual(
            result["missing"],
            [{"field": "materials[0].full_note", "reason": "not supplied"}],
        )
        self.assertIsNone(result["snapshot_ref"])
        self.assertFalse(self.output.exists())
        self.assertEqual(before, _inventory(self.ledger.root))

    def test_tampered_material_and_old_export_rejected_without_overwrite(self):
        self.export()
        before = _inventory(self.output)
        ref = self.request["materials"][0]["raw_source"]
        path = self.root / ref["path"]
        old = path.read_bytes()
        path.write_bytes(old + b"tampered")
        with self.assertRaisesRegex(ValueError, "binding differs"):
            self.export()
        self.assertEqual(before, _inventory(self.output))
        path.write_bytes(old)
        (self.output / "snapshot.json").write_bytes(b"altered")
        altered = _inventory(self.output)
        with self.assertRaisesRegex(ValueError, "existing export differs"):
            self.export()
        self.assertEqual(altered, _inventory(self.output))

    def test_wrong_missing_stale_checkpoint(self):
        original = self.request["checkpoint_event_id"]
        self.request["checkpoint_event_id"] = "e999999"
        with self.assertRaisesRegex(ValueError, "checkpoint mismatch"):
            self.export()
        self.request["checkpoint_event_id"] = original
        self.ledger.start("search", {"query": "unexecuted synthetic intent"})
        with self.assertRaisesRegex(ValueError, "stale"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_integer_and_string_version_remain_distinct(self):
        project = json.loads((self.root / "project-state.json").read_bytes())
        project["input_version"] = 1
        project["stage1_runs"]["synthetic-run"]["binding"]["input_version"] = 1
        self.request["project_state"] = self.save("project-state.json", project)
        self.request["input_version"] = "1"
        with self.assertRaisesRegex(ValueError, "typed identity mismatch"):
            self.export()

    def test_wrong_checkpoint_work_or_material_id_reject(self):
        self.request["materials"][0]["source_id"] = "other"
        with self.assertRaisesRegex(ValueError, "absent from validated view"):
            self.export()
        self.assertFalse(self.output.exists())

    def test_rehashed_material_must_exist_in_checkpoint_source_history(self):
        self.request["materials"][0]["raw_source"] = self.save(
            "different-source.html", b"Other bytes, same metadata"
        )
        before = _inventory(self.ledger.root)
        with self.assertRaisesRegex(ValueError, "bytes absent from checkpoint"):
            self.export()
        self.assertFalse(self.output.exists())
        self.assertEqual(before, _inventory(self.ledger.root))

    def test_resource_boolean_and_float_are_not_integer_version(self):
        self.request["input_version"] = 1
        brief = json.loads((self.root / "brief.json").read_bytes())
        brief["input_version"] = 1
        self.request["bindings"]["brief"] = self.save("brief.json", brief)
        for value in (True, 1.0):
            with self.subTest(value=value):
                resources = json.loads((self.root / "resources.json").read_bytes())
                resources["input_version"] = value
                self.request["bindings"]["resources"] = self.save(
                    "resources.json", resources
                )
                with self.assertRaisesRegex(ValueError, "resources typed identity"):
                    self.export()
                self.assertFalse(self.output.exists())

    def test_windows_case_aliases_cannot_overwrite_frozen_request(self):
        for name in ("Snapshot.json", "SNAPSHOT-REF.JSON", "Export-Receipt.json"):
            with self.subTest(name=name):
                ref = self.save(name, self.request)
                before = (self.root / name).read_bytes()
                with self.assertRaisesRegex(ValueError, "reserved export filename"):
                    export_snapshot(self.root, ref, self.output)
                self.assertEqual((self.root / name).read_bytes(), before)
                self.assertFalse(self.output.exists())


if __name__ == "__main__":
    unittest.main()
