"""Authored source fixture for real Host/browser Stage2→Stage3 acceptance.

Only model-facing responses are authored. Project, receipt, frontier, source,
admission, workflow and job implementations remain real. Nothing runs on import.
"""

# ruff: noqa: E402 -- exercise the CLI with existing authored source builders.
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import tempfile
import threading
from unittest.mock import patch

import test_project_stage123_controller_e2e as current
from test_project_stage3_planning import authored_plan
from research_workspace_native.journal import Journal
from research_workspace_native.project_stage2_controller import (
    ProjectStage2ControllerDriver,
)
from research_workspace_native.project_stage2_selection import (
    ProjectStage2SelectionService,
)
from research_workspace_native.project_stage3_planning import (
    ProjectStage3PlanningService,
)
from stage1_deliverable import sources
from stage3_plan.contracts import canonical_bytes, digest
from stage3_plan.jobs import POLICY, PlanningJobs
from stage3_plan.storage import private_output, read_json


class EvidenceDirectory:
    """Retain authored test artifacts when an explicit private evidence root is set."""

    def __init__(self, *args, evidence_root, **kwargs):
        kwargs.pop("ignore_cleanup_errors", None)
        kwargs.pop("delete", None)
        kwargs["dir"] = evidence_root
        self.name = tempfile.mkdtemp(*args, **kwargs)

    def cleanup(self):
        pass  # Evidence is kept outside Git, including original failed attempts.

    def __enter__(self):
        return self.name

    def __exit__(self, *exc):
        self.cleanup()


class FixedPlanningCallback:
    """Return a generic, source-bound plan over the actual saved planner request."""

    def __init__(self):
        self.request_context = {"kind": "authored-host-e2e", "timeout_seconds": 5}
        self.calls = []
        self.entered = threading.Event()
        self.failure = None

    def __call__(self, *, output_dir, **request):
        saved = read_json(Path(output_dir) / "request.json")
        self.calls.append(deepcopy(saved))
        self.entered.set()
        if self.failure is not None:
            raise self.failure
        intake = saved["intake"]
        plan = authored_plan(intake, intake["source_manifest_sha256"], saved["plan_id"])
        return dict(
            raw_response=canonical_bytes(plan),
            provenance={
                "kind": "authored-engineering-fixture",
                "research_or_model_call": False,
            },
        )


class Stage3HostE2ESeed:
    """Build one isolated unselected project; the browser must record its choice.

    The existing upstream builder uses authored research/extraction/review bytes.
    Its expensive exporter attestation is computed once during construction only;
    actual Host requests afterwards use the original runtime/source validators.
    This object creates the one existing PlanningJobs journal supplied to the
    Host, never a second job store or process owner. The caller owns Host cleanup.
    """

    def __init__(self, case, *, evidence_root=None):
        self.case = case
        fixture_type = current.ImportedRichControllerChoiceE2ETests
        with ExitStack() as construction:
            if evidence_root is not None:
                evidence_root = private_output(Path(evidence_root)).resolve()
                evidence_root.mkdir(parents=True, exist_ok=True)
                construction.enter_context(
                    patch.object(
                        tempfile,
                        "TemporaryDirectory",
                        side_effect=lambda *a, **k: EvidenceDirectory(
                            *a, evidence_root=evidence_root, **k
                        ),
                    )
                )
            runtime = sources.runtime_binding()
            construction.enter_context(
                patch.object(sources, "runtime_binding", return_value=runtime)
            )
            fixture_type.setUpClass()
            case.addCleanup(fixture_type.doClassCleanups)
            self.original = fixture_type()
            self.original.setUp()
            case.addCleanup(self.original.doCleanups)
            f = self.original
            driver = ProjectStage2ControllerDriver(
                f.service,
                spec=f.spec,
                controller_dir=f.output,
                delivery_dir=f.delivery,
                prerequisite_handler=f.handler,
            )
            adapter = current.RichSyntheticAdapter()
            with patch(
                "stage2_live.controller._ProductionAdapter", return_value=adapter
            ):
                recorded = driver.run("own", f.ref, key="authored-stage3-e2e-source")
            case.assertEqual(recorded["status"], "saved", recorded)
            project = f.intake.read("own", f.ref)
            manifest = read_json(f.delivery / "delivery_manifest.json")
            self.selection = ProjectStage2SelectionService(
                f.intake,
                {
                    f.ref: dict(
                        input_version=project["input_version"],
                        brief_sha256=project["brief_sha256"],
                        workflow_root=str(f.workflow),
                        delivery_root=str(f.delivery),
                        delivery_manifest_sha256=manifest["manifest_sha256"],
                    ),
                },
            )
            view = self.selection.read("own", f.ref)
            case.assertEqual(view["selection_status"], "pending")
            case.assertEqual(len(view["eligible"]), 1)
            self.initial_view = deepcopy(view)

        # No admission/frontier/project-current overrides remain for HTTP/UI.
        self.root, self.intake, self.ref = f.root, f.intake, f.ref
        self.stage2, self.credential = f.service, f.token
        self.journal = Journal(self.root / "stage3-host-jobs.sqlite")
        case.addCleanup(self.journal.close)
        self.journal.bind_project(
            project["project_id"], digest({"authored-host": self.ref})
        )
        owner = self.journal.acquire_owner(project["project_id"], "authored-host-e2e")
        self.jobs = PlanningJobs(
            self.journal,
            project["project_id"],
            owner,
            self.root / "stage3-host-jobs",
            project_ref=self.ref,
        )
        self.callback = FixedPlanningCallback()
        self.planning = ProjectStage3PlanningService(
            self.intake,
            self.selection,
            bindings={
                self.ref: dict(
                    jobs=self.jobs,
                    callback=self.callback,
                    configuration={"model": "authored-fixture", "reasoning": "medium"},
                ),
            },
        )
        self.native_guard = case.enterContext(
            patch(
                "stage3_plan.native.NativePlanner.__call__",
                side_effect=AssertionError(
                    "Native model dispatch forbidden in engineering E2E"
                ),
            )
        )
        case.addCleanup(self.native_guard.assert_not_called)

    def source_body(self, *, key):
        view = self.planning.read("own", self.ref)
        return {
            name: (key if name == "key" else view[name])
            for name in (
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "selection_request_sha256",
            )
        }

    def job_item(self, key):
        return self.journal.snapshot(self.jobs.project_id)["intents"][
            self.jobs._key(key)
        ]

    def summary(self):
        return dict(
            project_ref=self.ref,
            input_version=self.initial_view["input_version"],
            original_selection_pending=True,
            fixed_callback_calls=len(self.callback.calls),
            native_calls=self.native_guard.call_count,
            policy=dict(POLICY),
            real_human_selection=False,
            scientific_evaluation="not-run",
        )

    def write_summary(self, path):
        with Path(path).open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(self.summary(), stream, ensure_ascii=False, indent=2)
