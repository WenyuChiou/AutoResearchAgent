"""One synthetic-planner browser journey through the real V9 Wiki Host."""

from concurrent.futures import ThreadPoolExecutor
from dataclasses import asdict, dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
import tempfile
import threading
import time
import unittest
import uuid
from unittest.mock import patch

import project_stage3_host_e2e_fixture as host_seed
from project_wiki_completion_fixture import (
    ProjectWikiCompletionFixture,
    ROOT,
    wiki_host_artifacts,
)
from research_workspace_native.project_completion import (
    CompletionIdentity,
    completion_event_adapter,
    inspect_project_completion,
)
from stage3_plan.contracts import Stage3Error
from stage3_plan.native import NativePlanner


@dataclass(frozen=True)
class RecordedEvent:
    task_id: str
    version: str
    environment: str
    operation_id: str
    phase: str
    target: str
    mechanism: str
    origin: str
    result: str


class WikiHostArtifactPathTests(unittest.TestCase):
    def test_short_workspaces_survive_interleaved_setup_failure(self):
        default_evidence_directory = host_seed.EvidenceDirectory
        default_temp_directory = tempfile.TemporaryDirectory
        default_runtime_binding = host_seed.sources.runtime_binding
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            desktop_in_setup = threading.Event()
            mobile_attempted = threading.Event()
            mobile_in_setup = threading.Event()
            let_desktop_fail = threading.Event()
            profile = threading.local()
            cleanup_order = []
            test = self

            class SetupFailure(RuntimeError):
                pass

            class FailingSource(unittest.TestCase):
                @classmethod
                def setUpClass(cls):
                    cls.addClassCleanup(cleanup_order.append, ("class", profile.name))

                def setUp(self):
                    name = profile.name
                    if name == "mobile":
                        mobile_in_setup.set()
                    project = tempfile.TemporaryDirectory(
                        prefix="rich-controller-choice-"
                    )
                    self.addCleanup(project.cleanup)
                    self.addCleanup(cleanup_order.append, ("instance", name))
                    project_root = Path(project.name).resolve()
                    (project_root / "setup-marker.txt").write_text(
                        name, encoding="utf-8"
                    )
                    if name == "desktop":
                        desktop_in_setup.set()
                        test.assertTrue(let_desktop_fail.wait(10))
                    raise SetupFailure(project_root)

            def construct(name):
                profile.name = name
                evidence = parent / name
                arguments = {}
                if name == "ordinary":
                    workspace = evidence
                else:
                    evidence.mkdir()
                    workspace, directory_factory = wiki_host_artifacts(
                        evidence, short_paths=True
                    )
                    arguments["evidence_directory"] = directory_factory
                case = unittest.TestCase()
                try:
                    if name == "mobile":
                        mobile_attempted.set()
                    with self.assertRaises(SetupFailure) as raised:
                        host_seed.Stage3HostE2ESeed(
                            case, evidence_root=workspace, **arguments
                        )
                finally:
                    self.assertTrue(case.doCleanups())
                actual = raised.exception.args[0]
                if name != "ordinary":
                    receipt = json.loads(
                        (evidence / "host-workspace.json").read_bytes()
                    )
                    self.assertEqual(actual, Path(receipt["workspace"]))
                    self.assertEqual(actual.parent, parent)
                    self.assertLess(len(actual.name), 16)
                self.assertEqual(
                    (actual / "setup-marker.txt").read_text(encoding="utf-8"), name
                )
                return actual

            with (
                patch.object(
                    host_seed.current,
                    "ImportedRichControllerChoiceE2ETests",
                    FailingSource,
                ),
                patch.object(
                    host_seed.sources, "runtime_binding", return_value={}
                ) as runtime,
                ThreadPoolExecutor(max_workers=2) as workers,
            ):
                desktop = workers.submit(construct, "desktop")
                try:
                    self.assertTrue(desktop_in_setup.wait(10))
                    mobile = workers.submit(construct, "mobile")
                    self.assertTrue(mobile_attempted.wait(10))
                    self.assertFalse(
                        mobile_in_setup.wait(1),
                        "mobile entered seed setup before desktop released its patches",
                    )
                finally:
                    let_desktop_fail.set()
                self.assertNotEqual(
                    desktop.result(timeout=15), mobile.result(timeout=15)
                )
                self.assertIs(tempfile.TemporaryDirectory, default_temp_directory)
                self.assertIs(host_seed.sources.runtime_binding, runtime)
                ordinary = construct("ordinary")
                self.assertIs(tempfile.TemporaryDirectory, default_temp_directory)
                self.assertIs(host_seed.sources.runtime_binding, runtime)

            self.assertIs(host_seed.EvidenceDirectory, default_evidence_directory)
            self.assertIs(host_seed.sources.runtime_binding, default_runtime_binding)
            self.assertEqual(ordinary.parent, parent / "ordinary")
            self.assertTrue(ordinary.name.startswith("rich-controller-choice-"))
            for name in ("desktop", "mobile", "ordinary"):
                self.assertLess(
                    cleanup_order.index(("instance", name)),
                    cleanup_order.index(("class", name)),
                )

    def test_short_workspace_rejects_git_parent(self):
        with tempfile.TemporaryDirectory() as temp:
            parent = Path(temp).resolve()
            (parent / ".git").mkdir()
            evidence = parent / "evidence"
            evidence.mkdir()
            with self.assertRaisesRegex(Stage3Error, "outside Git checkouts"):
                wiki_host_artifacts(evidence, short_paths=True)
            self.assertEqual(set(parent.iterdir()), {parent / ".git", evidence})

    def test_normal_layout_keeps_nested_artifacts(self):
        with tempfile.TemporaryDirectory() as temp:
            evidence = Path(temp) / "evidence"
            workspace, directory_factory = wiki_host_artifacts(
                evidence, short_paths=False
            )
            self.assertEqual(workspace, evidence / "host-artifacts")
            self.assertIs(directory_factory, host_seed.EvidenceDirectory)
            self.assertFalse(evidence.exists())

    def test_native_guard_stays_until_last_fixture_closes(self):
        original = NativePlanner.__call__
        desktop, mobile = unittest.TestCase(), unittest.TestCase()
        self.addCleanup(mobile.doCleanups)
        self.addCleanup(desktop.doCleanups)
        guard = desktop.enterContext(host_seed._deny_native_planning())
        self.assertIs(mobile.enterContext(host_seed._deny_native_planning()), guard)
        self.assertTrue(desktop.doCleanups())
        self.assertIs(NativePlanner.__call__, guard)
        guard.assert_not_called()
        self.assertTrue(mobile.doCleanups())
        self.assertIs(NativePlanner.__call__, original)


class ProjectWikiCompletionE2ETests(unittest.TestCase):
    def evidence_root(self):
        configured = os.environ.get("PROJECT_WIKI_COMPLETION_EVIDENCE_ROOT")
        if configured:
            base = Path(configured)
        else:
            codex_home = Path(os.environ.get("CODEX_HOME", Path.home() / ".codex"))
            base = codex_home / "tmp" / "project-wiki-completion-e2e"
        root = base.resolve() / (
            time.strftime("%Y%m%dT%H%M%S") + "-" + uuid.uuid4().hex
        )
        self.assertFalse(root.is_relative_to(ROOT.resolve()))
        return root

    def run_profile(self, profile, width, height, mobile):
        fixture = ProjectWikiCompletionFixture(self, self.evidence_root())
        renderer_receipt = fixture.write_renderer_receipt()
        script = Path(__file__).parent / "browser" / "project-wiki-completion-e2e.cjs"
        environment = dict(os.environ)
        completed = subprocess.run(
            [
                "node",
                str(script),
                fixture.origin,
                fixture.seed.ref,
                str(fixture.evidence_root),
                profile,
                str(width),
                str(height),
                str(mobile).lower(),
            ],
            cwd=ROOT,
            env=environment,
            capture_output=True,
            text=True,
            encoding="utf-8",
            timeout=180,
            check=False,
        )
        observer_path = fixture.evidence_root / "browser-observer.json"
        self.assertTrue(observer_path.is_file(), completed.stdout + completed.stderr)
        observer = json.loads(observer_path.read_text(encoding="utf-8"))
        self.assertEqual(
            completed.returncode, 0, observer.get("error", completed.stderr)
        )
        self.assertEqual(observer["outcome"], "passed", observer)
        self.assertEqual(observer["profile"], profile)
        self.assertEqual([row["width"] for row in observer["profiles"]], [width])
        self.assertEqual(len(fixture.seed.callback.calls), 1)
        self.assertEqual(fixture.seed.native_guard.call_count, 0)

        selection = fixture.seed.selection.read("own", fixture.seed.ref)
        run_requests = [
            row["payload"]
            for row in observer["requests"]
            if row["path"] == f"/api/projects/{fixture.seed.ref}/stage3/planning/run"
        ]
        self.assertEqual(len(run_requests), 1)
        job_request = dict(run_requests[0])
        self.assertIs(job_request.pop("confirmed"), True)
        job = fixture.seed.planning.inspect("own", fixture.seed.ref, job_request)
        self.assertEqual(job["outcome"], "saved")
        self.assertEqual(job["request_sha256"], observer["planning_request_sha256"])
        identity = CompletionIdentity(
            task_id="project-wiki-completion-e2e",
            version="1.0.0",
            environment="isolated-local-v9",
            operation_id=observer["operation_id"],
            project_ref=fixture.seed.ref,
            input_version=selection["input_version"],
            delivery_manifest_sha256=selection["delivery_manifest_sha256"],
            submission_request_sha256=observer["selection_receipt"]["request_sha256"],
            plan_manifest_sha256=job["plan_manifest_sha256"],
        )
        authoritative = inspect_project_completion(
            fixture.seed.selection,
            fixture.seed.planning,
            "own",
            identity,
            job_request,
        )
        contract = {
            "task_id": identity.task_id,
            "version": identity.version,
            "environment": identity.environment,
            "operation_id": identity.operation_id,
        }
        adapter = completion_event_adapter(
            fixture.seed.selection,
            fixture.seed.planning,
            "own",
            identity,
            job_request,
            event_factory=RecordedEvent,
            observed_events=observer["observed_events"],
        )
        events = []
        for phase in ("entry", "action", "outcome"):
            observed = observer["observed_events"][phase]
            requirement = {
                key: observed[key] for key in ("phase", "target", "mechanism", "origin")
            }
            events.append(asdict(adapter(authoritative, requirement, contract)))
        self.assertEqual(
            [event["phase"] for event in events], ["entry", "action", "outcome"]
        )
        self.assertTrue(all(event["result"] == "passed" for event in events))
        self.assertFalse(authoritative["identity_authenticated"])
        self.assertFalse(authoritative["human_acceptance_verified"])
        self.assertFalse(authoritative["execution_authorized"])
        self.assertEqual(len(fixture.seed.callback.calls), 1)

        service_snapshot = fixture.evidence_root / "service-inspection.json"
        with service_snapshot.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(
                {
                    "kind": "ProjectWikiCompletionServiceInspection",
                    "authoritative": authoritative,
                    "identity": asdict(identity),
                    "job_request": job_request,
                    "job": job,
                    "events": events,
                    "fixed_callback_calls": len(fixture.seed.callback.calls),
                    "native_model_calls": fixture.seed.native_guard.call_count,
                    "automation_not_actual_human": True,
                    "browser_observer_sha256": hashlib.sha256(
                        observer_path.read_bytes()
                    ).hexdigest(),
                    "renderer_receipt_sha256": hashlib.sha256(
                        renderer_receipt.read_bytes()
                    ).hexdigest(),
                },
                stream,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            stream.write("\n")
        return fixture.evidence_root

    def test_original_wiki_button_reaches_one_persisted_same_project_plan_per_viewport(
        self,
    ):
        roots = []
        for profile, width, height, mobile in (
            ("desktop-1440", 1440, 960, False),
            ("mobile-390", 390, 844, True),
        ):
            with self.subTest(profile=profile):
                roots.append(self.run_profile(profile, width, height, mobile))
        self.assertEqual(len(set(roots)), 2)


if __name__ == "__main__":
    unittest.main(verbosity=2)
