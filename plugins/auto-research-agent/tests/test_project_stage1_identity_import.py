"""Trusted Stage1 identity import; authored sources, not scientific acceptance."""

import json
import shutil
import subprocess
from pathlib import Path
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import sha
import test_saved_source_stage2_intake as saved


class ImportedStage1ProjectTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        saved.SavedReplayImportIntegrationTests.setUpClass()
        cls.shared = saved.SavedReplayImportIntegrationTests()
        cls.shared.setUp()
        cls.addClassCleanup(cls.shared.doCleanups)

    def setUp(self):
        fixture = self.shared
        self.f = fixture
        temporary = tempfile.TemporaryDirectory(prefix="stage1-project-import-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name)
        self.auth = lambda token: "alice" if token == "own" else "bob"
        self.intake = ProjectIntakeService(self.root, authenticate=self.auth)
        self.addCleanup(lambda: self.intake.close())
        self.service = ProjectStage2Service(self.intake)
        self.settings = dict(
            resource_envelope=fixture.resources.read_text(encoding="utf-8")
        )
        self.args = dict(
            brief_path=fixture.brief,
            expected_brief_sha256=sha(fixture.brief.read_bytes()),
            settings=self.settings,
            deliverable_dir=fixture.f.package,
            expected_manifest_sha256=fixture.manifest["sha256"],
            handoff_path=fixture.handoff_path,
            expected_handoff_sha256=sha(fixture.handoff_path.read_bytes()),
            resources_path=fixture.resources,
            expected_resources_sha256=sha(fixture.resources.read_bytes()),
            policy_ref=dict(
                route="stage2-general-v3/daily_v3", execution_authorized=False
            ),
            saved_source_root=fixture.root,
            saved_source_acceptance_sha256=fixture.acceptance_ref["sha256"],
            **fixture.replay_args,
        )

    def test_legacy_identity_reaches_activation_and_reopens_without_research(self):
        before = self.f.brief.read_bytes()
        result = self.service.import_stage1_project("own", **self.args)
        ref = result["project_ref"]
        view = self.intake.read("own", ref)
        brief = json.loads(before)
        self.assertEqual(view["project_id"], brief["project_id"])
        self.assertEqual(view["input_version"], brief["input_version"])
        self.assertIs(type(view["input_version"]), str)
        self.assertEqual(view["brief_sha256"], sha(before))
        self.assertIsNone(view["plan"])
        self.assertEqual(view["stage1_status"], "imported-verified-delivery")
        offer = result["offer"]
        body = dict(
            key="activate-original-version",
            revision=view["revision"],
            input_version=view["input_version"],
            brief_sha256=view["brief_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        activated = self.service.activate("own", ref, body)
        self.assertEqual(activated["status"], "saved")
        binding = self.service.binding(ref)
        packet = json.loads(binding["packet_path"].read_bytes())
        self.assertEqual(packet["brief"], brief)
        self.assertEqual(packet["candidates"], [])
        self.assertFalse(activated["execution_authorized"])
        self.intake.close()
        self.intake = ProjectIntakeService(self.root, authenticate=self.auth)
        self.service = ProjectStage2Service(self.intake)
        with patch(
            "research_workspace_native.project_stage2.build_stage2_seed"
        ) as build:
            replayed = self.service.activate("own", ref, body)
            self.assertTrue(replayed["replayed"])
            build.assert_not_called()
        self.assertEqual(
            self.service.binding(ref)["packet_sha256"], binding["packet_sha256"]
        )
        self.assertEqual(self.f.brief.read_bytes(), before)

    def test_imported_overview_opens_html_activation_without_invented_consent(self):
        from research_workspace_native.project_host import ProjectHost

        imported = self.service.import_stage1_project("own", **self.args)
        host = object.__new__(ProjectHost)
        host.projects = self.intake
        host.project_models = None
        host.project_stage1 = None
        host.project_stage2 = self.service
        overview = host.overview("own", imported["project_ref"])
        self.assertEqual(overview["project"]["settings"], self.settings)
        self.assertEqual(len(overview["stage2"]["offers"]), 1)
        executable = shutil.which("node")
        self.assertIsNotNone(
            executable, "Node is required for the registered UI regression"
        )
        result = subprocess.run(
            [
                executable,
                str(
                    Path(__file__).parent / "browser/project-imported-overview-test.cjs"
                ),
            ],
            input=json.dumps(overview),
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertIn("PASS: imported actual overview", result.stdout)

    def test_hash_pinned_host_configuration_uses_the_same_import(self):
        from research_workspace_native.project_stage1_import import load_stage1_imports
        from stage1_ledger.journal import canonical

        entry = {
            key: str(value) if isinstance(value, Path) else value
            for key, value in self.args.items()
        }
        path = self.root / "imports.json"
        path.write_bytes(
            canonical(
                dict(
                    kind="ProjectStage1ImportConfiguration",
                    schema_version="1.0.0",
                    entries=[entry],
                )
            )
        )
        with self.assertRaises((ValueError, SessionApiError)):
            load_stage1_imports(self.service, "own", path, "0" * 64)
        self.assertEqual(self.intake.list("own"), [])
        result = load_stage1_imports(self.service, "own", path, sha(path.read_bytes()))
        self.assertEqual(
            result, [self.service.import_stage1_project("own", **self.args)]
        )

    def test_partial_import_recovers_only_identical_private_bytes(self):
        before = self.f.brief.read_bytes()
        with patch.object(
            self.intake,
            "_save",
            side_effect=RuntimeError("authored interruption before SQL commit"),
        ):
            with self.assertRaisesRegex(RuntimeError, "before SQL commit"):
                self.service.import_stage1_project("own", **self.args)
        self.assertEqual(self.intake.list("own"), [])
        retained = {
            str(path.relative_to(self.root)): path.read_bytes()
            for path in self.root.glob("project-*/import/*.json")
        }
        self.assertEqual(len(retained), 2)
        result = self.service.import_stage1_project("own", **self.args)
        for relative, raw in retained.items():
            self.assertEqual((self.root / relative).read_bytes(), raw)
        self.assertFalse(result["execution_authorized"])
        self.assertEqual(self.f.brief.read_bytes(), before)

    def test_changed_partial_import_is_retained_and_refused(self):
        with patch.object(
            self.intake, "_save", side_effect=RuntimeError("authored interruption")
        ):
            with self.assertRaises(RuntimeError):
                self.service.import_stage1_project("own", **self.args)
        path = next(self.root.glob("project-*/import/brief.json"))
        path.write_bytes(b"changed partial")
        with self.assertRaisesRegex(
            SessionApiError, "stage2-import-partial-bytes-differ"
        ):
            self.service.import_stage1_project("own", **self.args)
        self.assertEqual(path.read_bytes(), b"changed partial")
        self.assertEqual(self.intake.list("own"), [])

    def test_bootstrap_is_idempotent_and_principal_scoped(self):
        first = self.service.import_stage1_project("own", **self.args)
        history = self.intake.history("own", first["project_ref"])
        second = self.service.import_stage1_project("own", **self.args)
        self.assertEqual(first, second)
        self.assertEqual(self.intake.history("own", first["project_ref"]), history)
        with self.assertRaises(SessionApiError):
            self.service.read("foreign", first["project_ref"])
        other = self.service.import_stage1_project("foreign", **self.args)
        self.assertNotEqual(first["project_ref"], other["project_ref"])

    def test_bad_external_pins_never_create_a_project(self):
        for field in (
            "expected_brief_sha256",
            "expected_manifest_sha256",
            "expected_handoff_sha256",
            "expected_resources_sha256",
            "trusted_host_replay_sha256",
        ):
            with (
                self.subTest(field=field),
                self.assertRaises((ValueError, SessionApiError)),
            ):
                self.service.import_stage1_project(
                    "own", **dict(self.args, **{field: "0" * 64})
                )
            self.assertEqual(self.intake.list("own"), [])

    def test_imported_version_is_typed_read_only_and_tamper_checked(self):
        imported = self.service.import_stage1_project("own", **self.args)
        ref, offer = imported["project_ref"], imported["offer"]
        view = self.intake.read("own", ref)
        body = dict(
            key="wrong-type",
            revision=view["revision"],
            input_version=1,
            brief_sha256=view["brief_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )
        history = self.intake.history("own", ref)
        with self.assertRaisesRegex(SessionApiError, "intake-source-version-differs"):
            self.service.activate("own", ref, body)
        self.assertEqual(self.intake.history("own", ref), history)
        with self.assertRaisesRegex(SessionApiError, "imported-intake-is-read-only"):
            self.intake.revise(
                "own",
                ref,
                dict(
                    key="do-not-rewrite",
                    revision=view["revision"],
                    input_version=view["input_version"],
                    brief_sha256=view["brief_sha256"],
                    topic="Changed",
                ),
            )
        state = self.intake._load("alice", ref)
        self.intake._path(ref, state["briefs"][-1]["path"]).write_bytes(b"changed")
        with self.assertRaises((ValueError, SessionApiError)):
            self.intake.read("own", ref)


class ImportedVersionEnvelopeTests(unittest.TestCase):
    def test_wrong_host_import_config_hash_refuses_before_listener(self):
        from research_workspace_native.project_host import main
        from stage1_ledger.journal import canonical

        with tempfile.TemporaryDirectory(prefix="import-host-config-") as folder:
            path = Path(folder) / "imports.json"
            path.write_bytes(
                canonical(
                    dict(
                        kind="ProjectStage1ImportConfiguration",
                        schema_version="1.0.0",
                        entries=[],
                    )
                )
            )
            with patch("research_workspace_native.project_host.ProjectHost") as host:
                with self.assertRaises((ValueError, SessionApiError)):
                    main(
                        [
                            "--projects-root",
                            str(Path(folder) / "projects"),
                            "--stage1-import-config",
                            str(path),
                            "--stage1-import-sha256",
                            "0" * 64,
                        ]
                    )
                host.assert_not_called()

    def test_only_stage2_and_stage3_envelopes_allow_preserved_string_versions(self):
        from research_workspace_native.project_intake_contract import refusal_shape

        body = dict(
            key="request",
            revision=0,
            input_version="20261009-A03",
            brief_sha256="a" * 64,
            offer_ref="stage2-offer",
            offer_sha256="b" * 64,
            confirmed=True,
        )
        self.assertTrue(
            refusal_shape("stage2-activate", body, "request", "project-test")
        )
        self.assertFalse(
            refusal_shape("stage1-initialize", body, "request", "project-test")
        )
        for invalid in (True, 1.0, "", " " * 3, "x" * 129):
            self.assertFalse(
                refusal_shape(
                    "stage2-activate",
                    dict(body, input_version=invalid),
                    "request",
                    "project-test",
                )
            )


if __name__ == "__main__":
    unittest.main()
