"""Saved-v2 admission reaches the existing importer and project workflow.

All papers, reviews, browser receipts and identities here are authored fixtures.
The CLI integration uses real package/admission/replay/import/workflow validators;
only the fixture source producer is simulated. Native adapter tests separately
stub admission to isolate journal/CAS/reopen behavior, never real Core authority.
"""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace import host_replay
from research_workspace.saved_admission import inspect_saved_admission, producer_files
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable import sources
from stage1_deliverable.common import DeliverableError, canonical, inventory, sha
from stage2_common import Stage2Error
from stage2_workflow import initialize_workflow, inspect_workflow
from stage2_workflow.import_stage1 import build_stage2_seed
import test_project_stage2 as native_fixture
import test_saved_source_admission as acceptance_fixture
import test_saved_source_admission_integration as integration_fixture
import test_saved_source_import as import_fixture


class SavedReplayImportIntegrationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        integration_fixture.SavedAdmissionIntegrationTests.setUpClass()

    def setUp(self):
        f = integration_fixture.SavedAdmissionIntegrationTests()
        f.setUp()
        self.addCleanup(f.doCleanups)
        self.f = f
        self.root = f.root
        self.snapshot = json.loads((self.root / "snapshot.json").read_bytes())
        native = getattr(self, "native_binding", None)
        original_project = self.snapshot["project_id"]
        original_version = self.snapshot["input_version"]
        if native is not None:
            # Authored integration evidence is produced for this actual native
            # intake. No existing receipt is accepted under a substituted ID.
            brief = json.loads(Path(native["brief_path"]).read_bytes())
            self.snapshot.update(
                project_id=native["project_id"], input_version=native["input_version"]
            )
            self.snapshot["bindings"]["brief"] = f.save(
                "native-brief.json", Path(native["brief_path"]).read_bytes()
            )
            self.snapshot["bindings"]["original_request"] = f.save(
                "native-request.txt", brief["original_description"].encode("utf-8")
            )
            resources = json.loads(
                (
                    self.root / self.snapshot["bindings"]["resources"]["path"]
                ).read_bytes()
            )
            resources.update(
                project_id=native["project_id"], input_version=native["input_version"]
            )
            self.snapshot["bindings"]["resources"] = f.save(
                "native-resources.json", resources
            )
        self.manifest = self.snapshot["bindings"]["deliverable"]
        self.brief = self.root / self.snapshot["bindings"]["brief"]["path"]
        self.resources = self.root / "resource-envelope.txt"
        self.resources.write_text(
            "Authored fixture only; no research execution."
            if native is None
            else native["settings"]["resource_envelope"],
            encoding="utf-8",
        )
        self.runtime = sources.runtime_binding()

        # A different historical exporter exercises the opt-in path. Every saved
        # observation remains actual output from the fixture's offline SDK CLI.
        self.old_exporter = self.root / "historical-exporter"
        self.old_exporter.mkdir()
        (self.old_exporter / "__init__.py").write_text("# fixture only\n")
        historical = deepcopy(self.runtime)
        historical["exporter_sha256"] = sha(
            canonical(host_replay.exporter_files(self.old_exporter))
        )
        manifest = json.loads((f.package / "provenance_manifest.json").read_bytes())
        manifest["runtime"] = historical
        (f.package / "provenance_manifest.json").write_bytes(canonical(manifest))
        self.manifest = f.ref(f.package / "provenance_manifest.json")
        self.snapshot["bindings"]["deliverable"] = self.manifest
        # Rebind the authored view through the original renderer, preserving its
        # real source-rerun and qualification checks, instead of mocking admission.
        from research_workspace.source_rerun import attach_rerun
        from research_workspace.view import write_workspace
        import test_research_workspace_source_rerun_exports as rerun

        index = deepcopy(f.base_index)
        rerun_manifest = deepcopy(f.rerun_manifest)
        if native is not None:

            def authored_identity(value):
                if isinstance(value, dict):
                    return {key: authored_identity(item) for key, item in value.items()}
                if isinstance(value, list):
                    return [authored_identity(item) for item in value]
                if type(value) is str and value == original_project:
                    return native["project_id"]
                if type(value) is str and value == original_version:
                    return native["input_version"]
                return value

            index = authored_identity(index)
            rerun_manifest = authored_identity(rerun_manifest)
            index["coverage"] = [
                {
                    "need_id": need["need_id"],
                    "status": "qualified",
                    "work_ids": [index["papers"][0]["work_id"]],
                    "evidence_refs": ["authored-native-need-review:1"],
                }
                for need in brief["needs"]
            ]
        index["provenance"]["deliverable_manifest_sha256"] = self.manifest["sha256"]
        rerun_manifest["data"]["base_index_sha256"] = sha(canonical(index))
        row = rerun_manifest["data"]["rows"][0]
        row["attempt_id"] = sha(
            canonical(
                dict(
                    base=rerun_manifest["data"]["base_index_sha256"],
                    parser=rerun_manifest["data"]["parser_runtime"]["parser_sha256"],
                    work=row["work_id"],
                    version=row["version_id"],
                    raw=row["raw_sha256"],
                )
            )
        )
        rebound = self.root / "rebound-rerun"
        rebound.mkdir()
        with (
            patch.dict(
                rerun.RAW, {"source-0": (f.rerun_root / row["raw_path"]).read_bytes()}
            ),
            patch.dict(
                rerun.TEXT,
                {"source-0": (f.rerun_root / row["extracted_path"]).read_bytes()},
            ),
        ):
            digest = rerun.write_manifest(rebound, rerun_manifest)
            index = attach_rerun(index, rebound, digest)
        view = self.root / "rebound-view"
        write_workspace(
            index,
            Path(__file__).parents[1] / "references/research-workspace",
            view,
            source_rerun_root=rebound,
        )
        self.snapshot["bindings"]["view"] = f.ref(view / "view-manifest.json")
        self.snapshot_ref = f.save("snapshot.json", self.snapshot)
        self.replay_path = self.root / "host-replay.json"
        source = manifest["canonical_records"]["sources"][0]
        archive = f.package / "sources" / source["source_id"]
        observation = json.loads((archive / "validation.json").read_bytes())
        checked = json.loads(observation["stdout"])["checked_at"]
        self.replay = dict(
            kind="HostReplayReceipt",
            schema_version="1.0.0",
            project_id=self.snapshot["project_id"],
            input_version=self.snapshot["input_version"],
            snapshot_ref=self.snapshot_ref,
            canonical_manifest_sha256=self.manifest["sha256"],
            historical_producer=dict(
                runtime=historical,
                executable=sys.executable,
                exporter_files=host_replay.exporter_files(self.old_exporter),
            ),
            replayer=dict(
                runtime=self.runtime,
                executable=sys.executable,
                exporter_files=host_replay.exporter_files(
                    Path(sources.__file__).parent
                ),
            ),
            validator=dict(runtime=self.runtime, files=host_replay.validator_files()),
            sources=[
                dict(
                    source_id=source["source_id"],
                    work_id=source["work_id"],
                    version_id=source["version_id"],
                    files=inventory(archive),
                    historical_observation_sha256=sha(
                        (archive / "validation.json").read_bytes()
                    ),
                    observation=observation,
                    started_at=checked,
                    ended_at=checked,
                )
            ],
        )
        self.replay_path.write_bytes(canonical(self.replay))
        self.replay_args = dict(
            host_replay_receipt=self.replay_path,
            trusted_host_replay_sha256=sha(self.replay_path.read_bytes()),
            historical_exporter_root=self.old_exporter,
            replayer_exporter_root=Path(sources.__file__).parent,
        )
        # Reuse the controlled receipt contract fixture, with exact current byte
        # inventories and this fixture's actual rendered HTML/BibTeX. These are
        # declared synthetic checks, not a real independent reviewer or browser.
        a = acceptance_fixture.ExternalAcceptanceBindingTests()
        a.setUp()
        self.addCleanup(a.doCleanups)
        self.acceptance_builder = a
        a.root = self.root
        a.snapshot = self.snapshot
        acceptance = deepcopy(a.acceptance)
        acceptance.update(
            snapshot_sha256=self.snapshot_ref["sha256"],
            project_id=self.snapshot["project_id"],
            input_version=self.snapshot["input_version"],
        )
        acceptance["producer"]["sources"] = {
            name: sha((Path(__file__).parents[1] / name).read_bytes())
            for name in producer_files()
        }
        proof = a.save("proof.bin", b"Authored fixture evidence, no real acceptance.")
        for category in acceptance["checks"]:
            review = dict(
                kind="SavedSourceAdmissionReview",
                category=category,
                snapshot_sha256=self.snapshot_ref["sha256"],
                project_id=self.snapshot["project_id"],
                input_version=self.snapshot["input_version"],
                scope="saved-source-current-admission",
                validator=proof,
                rubric=proof,
                results=[
                    dict(
                        check_id="authored",
                        status="passed",
                        locator="fixture:1",
                        reason="Authored fixture only.",
                    )
                ],
                outcome="accepted",
                observations="Authored fixture only, no real Core verdict.",
                evidence=[proof],
            )
            acceptance["checks"][category] = a.save(category + ".json", review)
        html = deepcopy(a.html)
        html.update(
            snapshot_sha256=self.snapshot_ref["sha256"],
            html_sha256=sha((view / "index.html").read_bytes()),
            expected_bibtex=f.ref(view / "literature/included.bib"),
            bibtex_download=a.save(
                "download.bib", (view / "literature/included.bib").read_bytes()
            ),
        )
        for operation in html["operations"]:
            operation["evidence"] = [proof]
        acceptance["html"] = a.save("html-receipt.json", html)
        self.acceptance_ref = a.save("accepted.json", acceptance)
        self.handoff = inspect_saved_admission(
            self.root,
            self.snapshot_ref,
            acceptance_ref=self.acceptance_ref,
            trusted_acceptance_sha256=self.acceptance_ref["sha256"],
            **self.replay_args,
        )
        self.handoff_path = self.root / "handoff.json"
        self.handoff_path.write_bytes(canonical(self.handoff))
        self.output = self.root / "seed"

    def build(self, **changes):
        kwargs = dict(self.replay_args)
        kwargs.update(changes)
        return build_stage2_seed(
            self.f.package,
            self.manifest["sha256"],
            self.handoff_path,
            sha(self.handoff_path.read_bytes()),
            self.brief,
            self.resources,
            self.output,
            saved_source_root=self.root,
            saved_source_acceptance_sha256=self.acceptance_ref["sha256"],
            **kwargs,
        )

    def test_real_import_and_cli_initialize_readback_reuse_one_context(self):
        package_before = inventory(self.f.package)
        contexts = []
        original = host_replay.HostReplay.package

        def checked(context, *args):
            contexts.append(context)
            return original(context, *args)

        with (
            patch.object(host_replay.HostReplay, "package", checked),
            patch.object(
                sources, "validate_archive", side_effect=AssertionError("no new replay")
            ),
        ):
            receipt = self.build()
        self.assertTrue(contexts)
        self.assertTrue(all(context is contexts[0] for context in contexts))
        self.assertEqual(
            receipt["host_replay"]["sha256"],
            self.replay_args["trusted_host_replay_sha256"],
        )
        self.assertFalse(receipt["host_replay"]["core_acceptance"])
        self.assertEqual(
            receipt["note_inventory"]["fixture-0"]["sha256"],
            self.snapshot["rows"][0]["full_note"]["sha256"],
        )
        packet = json.loads((self.output / "packet.json").read_bytes())
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(
            packet["evidence"][0]["relation"], self.f.records["claims"][0]["relation"]
        )
        initialize_workflow(
            self.output / "packet.json",
            self.output,
            self.root / "workflow",
            {"model": "authored-no-call", "reasoning": "medium"},
            {"route": "stage2-general-v3/daily_v3", "execution_authorized": False},
            receipt["packet_sha256"],
        )
        reopened = inspect_workflow(self.root / "workflow")
        self.assertEqual(
            reopened["manifest"]["initial_packet_sha256"], receipt["packet_sha256"]
        )
        self.assertEqual(inventory(self.f.package), package_before)
        command = [
            sys.executable,
            "-B",
            "-X",
            "utf8",
            "-m",
            "stage2_workflow",
            "import-stage1",
            "--deliverable",
            str(self.f.package),
            "--deliverable-manifest-sha256",
            self.manifest["sha256"],
            "--handoff",
            str(self.handoff_path),
            "--handoff-sha256",
            sha(self.handoff_path.read_bytes()),
            "--brief",
            str(self.brief),
            "--resources",
            str(self.resources),
            "--output",
            str(self.root / "cli-seed"),
            "--saved-source-root",
            str(self.root),
            "--saved-source-acceptance-sha256",
            self.acceptance_ref["sha256"],
        ]
        for name, value in self.replay_args.items():
            command.extend(["--" + name.replace("_", "-"), str(value)])
        child = subprocess.run(
            command,
            cwd=Path(__file__).parents[1] / "cli",
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=60,
        )
        self.assertEqual(child.returncode, 0, child.stderr)
        self.assertEqual(
            json.loads(child.stdout)["packet_sha256"], receipt["packet_sha256"]
        )

    def test_stale_trust_partial_inputs_and_core_rejection_leave_no_seed(self):
        for changes, message in (
            ({"trusted_host_replay_sha256": "0" * 64}, "trusted external"),
            ({"historical_exporter_root": None}, "all.host.replay.inputs"),
        ):
            with (
                self.subTest(changes=changes),
                self.assertRaisesRegex(Stage2Error, message),
            ):
                self.build(**changes)
            self.assertFalse(self.output.exists())
        original = self.acceptance_builder
        acceptance = json.loads((self.root / self.acceptance_ref["path"]).read_bytes())
        ref = acceptance["checks"]["coverage-and-claim-review"]
        review = json.loads((self.root / ref["path"]).read_bytes())
        review["outcome"] = "rejected"
        acceptance["checks"]["coverage-and-claim-review"] = original.save(
            ref["path"], review
        )
        self.acceptance_ref = original.save("accepted.json", acceptance)
        self.handoff["acceptance_ref"] = self.acceptance_ref
        self.handoff_path.write_bytes(canonical(self.handoff))
        with self.assertRaisesRegex(Stage2Error, "Core review missing"):
            self.build()
        self.assertFalse(self.output.exists())

    def test_context_does_not_cover_another_snapshot_and_final_recheck_rejects_change(
        self,
    ):
        context = host_replay.load_host_replay(
            self.replay_path,
            self.replay_args["trusted_host_replay_sha256"],
            self.root,
            self.snapshot_ref,
            historical_exporter_root=self.old_exporter,
            replayer_exporter_root=Path(sources.__file__).parent,
        )
        changed = deepcopy(self.snapshot)
        changed["admission_id"] = "another-authored-snapshot"
        ref = self.f.save("other-snapshot.json", changed)
        with self.assertRaisesRegex(DeliverableError, "snapshot reference"):
            inspect_saved_admission(self.root, ref, verified_host_replay=context)
        from stage2_workflow import import_stage1

        project = import_stage1._project_stage1

        def mutate(*args, **kwargs):
            result = project(*args, **kwargs)
            archive = self.f.package / "sources/source-0/original.json"
            archive.write_bytes(archive.read_bytes() + b" ")
            return result

        with patch.object(import_stage1, "_project_stage1", side_effect=mutate):
            with self.assertRaises(Stage2Error):
                self.build()
        self.assertFalse(self.output.exists())


class NativeSavedStage2Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        native_fixture.ProjectStage2Tests.setUpClass()
        cls.addClassCleanup(native_fixture.ProjectStage2Tests.doClassCleanups)

    def setUp(self):
        # Reuse the existing real project/journal/package fixture without
        # inheriting its tests or pretending its admission is independently reviewed.
        p = native_fixture.ProjectStage2Tests()
        p.setUp()
        self.addCleanup(p.doCleanups)
        self.p = p
        saved = import_fixture.SavedSourceImportTests()
        saved.setUp()
        self.addCleanup(saved.doCleanups)
        self.handoff = deepcopy(saved.handoff)
        binding = p.intake.binding(p.ref)
        self.handoff.update(
            project_id=binding["project_id"],
            input_version=binding["input_version"],
            brief_sha256=binding["brief_sha256"],
            deliverable_manifest_sha256=p.package_report["manifest_sha256"],
        )
        source_text = Path(
            json.loads((p.deliverable / "sources/src1/original.json").read_bytes())[
                "extracted_text_path"
            ]
        ).read_bytes()
        text_ref = saved.save("saved-text.txt", source_text)
        snapshot = json.loads((saved.fixture.root / "snapshot.json").read_bytes())
        snapshot["rows"][0]["extracted_text"] = text_ref
        self.handoff["snapshot_ref"] = saved.save("snapshot.json", snapshot)
        self.handoff["source_state_sha256"] = self.handoff["snapshot_ref"]["sha256"]
        p.handoff_path.write_bytes(canonical(self.handoff))
        p.registration.update(
            expected_handoff_sha256=sha(p.handoff_path.read_bytes()),
            saved_source_root=saved.fixture.root,
            saved_source_acceptance_sha256=self.handoff["acceptance_ref"]["sha256"],
        )
        self.admission = patch(
            "research_workspace.saved_admission.inspect_saved_admission",
            side_effect=lambda *a, **kw: deepcopy(self.handoff),
        )
        self.admission.start()
        self.addCleanup(self.admission.stop)
        p.offer = p.service.register(p.ref, **p.registration)

    def test_actual_native_import_initialize_reopen_and_same_key_do_not_dispatch(self):
        p = self.p
        body = p.body()
        first = p.service.activate("own", p.ref, body)
        self.assertEqual(first["status"], "saved")
        self.assertFalse(first["execution_authorized"])
        self.assertEqual(first["daily_v3"], "not-started")
        self.assertEqual(first["import_receipt"]["schema_version"], "2.0.0")
        p.intake.close()
        p.intake = ProjectIntakeService(p.store_root, authenticate=p.authenticate)
        p.service = ProjectStage2Service(p.intake)
        reopened = p.service.binding(p.ref)
        same = p.service.activate("own", p.ref, body)
        self.assertTrue(same["replayed"])
        self.assertEqual(same["packet_sha256"], reopened["packet_sha256"])
        self.assertEqual(
            p.service.action("own", p.ref, body["key"])["import_receipt"],
            first["import_receipt"],
        )
        self.assertEqual(
            len(list(p.store_root.rglob("packet.json"))), 2
        )  # seed + workflow snapshot
        self.assertNotIn(str(p.root), json.dumps(p.service.read("own", p.ref)))

    def test_reopened_note_tampering_and_changed_external_pin_fail_closed(self):
        p = self.p
        result = p.service.activate("own", p.ref, p.body())
        binding = p.service.binding(p.ref)
        note = result["import_receipt"]["note_inventory"]["work1"]
        path = binding["source_root"] / note["path"]
        original = path.read_bytes()
        path.write_bytes(b"changed projected note")
        with self.assertRaisesRegex(SessionApiError, "bytes-differ"):
            p.service.binding(p.ref)
        path.write_bytes(original)
        state = p.intake._load("researcher", p.ref)
        state["stage2_offers"][p.offer["offer_ref"]]["inputs"][
            "saved_source_acceptance_sha256"
        ] = "0" * 64
        p.intake._save(state, "authored-corruption-only", {})
        p.intake.db.commit()
        with self.assertRaisesRegex(SessionApiError, "admission-pins-differ"):
            p.service.binding(p.ref)

    def test_cross_project_snapshot_and_browser_trust_paths_are_rejected(self):
        p = self.p
        self.handoff["project_id"] = "different-authored-project"
        p.handoff_path.write_bytes(canonical(self.handoff))
        registration = dict(
            p.registration, expected_handoff_sha256=sha(p.handoff_path.read_bytes())
        )
        history = p.intake.history("own", p.ref)
        with self.assertRaisesRegex(SessionApiError, "project-input-differs"):
            p.service.register(p.ref, **registration)
        self.assertEqual(p.intake.history("own", p.ref), history)
        binding = p.intake.binding(p.ref)
        self.handoff.update(
            project_id=binding["project_id"],
            input_version=str(binding["input_version"]),
        )
        p.handoff_path.write_bytes(canonical(self.handoff))
        registration["expected_handoff_sha256"] = sha(p.handoff_path.read_bytes())
        with self.assertRaisesRegex(SessionApiError, "project-input-differs"):
            p.service.register(p.ref, **registration)
        self.assertEqual(p.intake.history("own", p.ref), history)
        body = dict(p.body(), saved_source_root="browser-supplied-path")
        with self.assertRaises(SessionApiError):
            p.service.activate("own", p.ref, body)


if __name__ == "__main__":
    unittest.main()
