"""Stage 2 controller registration over the normal ProjectHost HTTP routes."""

# ruff: noqa: E402 -- exercise the existing Wiki extension on ProjectHost.
from contextlib import contextmanager
from hashlib import sha256
import json
from pathlib import Path
import sys
import threading
import time
import traceback
from types import SimpleNamespace
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "harness-ui"))

from current_core_stage12_fixtures import current_core_stage1_case
from research_workspace_native import project_stage2_controller as driver_module
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_stage2 import ProjectStage2Service
from research_workspace_native.project_stage_connections import ConnectionStore
from stage2_common import canonical_hash
from stage2_live import controller
from test_project_stage2_current_evidence import authenticate, request, VIEWER
from test_stage1_current_core_stage123_e2e import (
    CurrentCorePreparation,
    CurrentCoreSyntheticAdapter,
)
import test_stage2_controller as synthetic
from wiki_stage2_continuation import install_stage2_continuation
from wiki_stage23_services import configure_services
from run_v7 import configure_host_lifecycle


POLICY = {"route": "stage2-general-v3/daily_v3", "packet_profile": "scientific-v3"}


@contextmanager
def wiki(case, path, digest):
    stage2 = ProjectStage2Service(case.intake)
    services = {"projects": case.intake, "credential": VIEWER, "stage2": stage2}
    configure_services(
        services,
        SimpleNamespace(
            stage2_controller_profile=path, stage2_controller_profile_sha256=digest
        ),
    )
    with ProjectHost(
        projects=case.intake,
        credential=VIEWER,
        stage1=case.stage1,
        stage2=stage2,
        stage2_selection=services["stage2_selection"],
        files={},
        views=[],
        port=0,
    ) as host:
        configure_host_lifecycle(host, services)
        install_stage2_continuation(host, services["stage2_controller_profile"])
        thread = threading.Thread(target=host.serve_forever)
        thread.start()
        try:
            yield host.expected_origin, host
        finally:
            host.shutdown()
            thread.join(5)
            if thread.is_alive():
                raise RuntimeError("Host did not shut down")


def write(path, value):
    raw = json.dumps(value).encode("utf-8")
    path.write_bytes(raw)
    return sha256(raw).hexdigest()


def counts(intake, ref):
    return {
        "actions": intake.db.execute(
            "SELECT COUNT(*) FROM intake_actions WHERE project=?", (ref,)
        ).fetchone()[0],
        "events": intake.db.execute(
            "SELECT COUNT(*) FROM intake_events WHERE project=?", (ref,)
        ).fetchone()[0],
    }


class Stage2ControllerRegistrationHttpTests(unittest.TestCase):
    def test_current_native_connection_retains_one_candidate_under_expired_readback(
        self,
    ):
        with (
            patch("test_project_stage1_delivery.authenticate", authenticate),
            current_core_stage1_case(screened=True) as fixture,
        ):
            self._journey(fixture)

    def _journey(self, fixture):
        case, ref = fixture["case"], fixture["project_ref"]
        route = f"/api/projects/{ref}"
        connections = route + "/connections"
        continuation = route + "/stage2/continuation"
        project = case.intake.read(VIEWER, ref)
        parent = Path(fixture["root"]) / "c"
        root = parent / ref
        root.mkdir(parents=True)
        spec = synthetic.Stage2ControllerTests._spec(
            SimpleNamespace(
                root=root,
                packet={"brief": project["brief"]},
                base=None,
            )
        )
        spec["confirmed_brief_sha256"] = None
        deadline = time.time() + 1800
        spec_path, prep_path = root / "spec.json", root / "prep.json"
        prep = {
            "kind": "Stage2NativePrerequisiteConfiguration",
            "schema_version": "1.0.0",
            "native_sha256": canonical_hash(spec["native"]),
            "output_root": "prep",
            "workspace_templates": {},
            "admission_context": {
                **{
                    key: project[key]
                    for key in ("project_id", "input_version", "brief_sha256")
                },
                "project_ref": ref,
                "status": "admitted",
                "mode": "fixed-engineering",
                "execution_policy_sha256": canonical_hash(spec["native"]),
                "runtime_sha256": "e" * 64,
                "deadline_unix": deadline,
                "remaining_budget": {"model_calls": 0, "search_calls": 0},
            },
        }
        path = parent / "profile.json"
        digest = write(
            path,
            {
                "kind": "ProjectStage2ControllerProfile",
                "schema_version": "1.0.0",
                "project_parent": str(parent),
                "max_projects": 1,
                "policy_ref": POLICY,
                "spec_path": spec_path.name,
                "spec_sha256": write(spec_path, spec),
                "preparation_path": prep_path.name,
                "preparation_sha256": write(prep_path, prep),
                "controller_root": "ctl",
                "delivery_root": "del",
            },
        )
        calls = []

        def run(workflow, output, delivery, head, value, *, prerequisite_handler):
            self.assertEqual(
                prerequisite_handler.admission_context["remaining_budget"],
                {
                    "model_calls": 0,
                    "search_calls": 0,
                },
            )
            adapter = CurrentCoreSyntheticAdapter()
            preparation = CurrentCorePreparation(
                SimpleNamespace(root=root, workflow=workflow, spec=value)
            )
            preparation.admission_context = prerequisite_handler.admission_context
            try:
                with patch.object(
                    controller, "_ProductionAdapter", return_value=adapter
                ):
                    return controller.run_controller(
                        workflow,
                        output,
                        delivery,
                        head,
                        value,
                        prerequisite_handler=preparation,
                    )
            finally:
                calls.append(adapter.calls)

        def observed(origin, label, path, **kwargs):
            status, body = request(origin, path, **kwargs)
            print(
                json.dumps({"fixture": label, "http_status": status, "body": body}),
                flush=True,
            )
            return status, body

        with patch.object(driver_module, "run_controller", side_effect=run):
            with wiki(case, path, digest) as (origin, host):
                code, data = request(origin, route + "/stage2")
                self.assertEqual(code, 200, data)
                evidence = data["current_evidence"]
                self.assertEqual(evidence["status"], "received", evidence)
                self.assertIs(type(evidence["input_version"]), int)
                print(
                    json.dumps(
                        {
                            "fixture": "native-input",
                            **{
                                key: evidence[key]
                                for key in (
                                    "project_ref",
                                    "input_version",
                                    "packet_id",
                                    "packet_sha256",
                                    "receipt_sha256",
                                    "connection_id",
                                    "receipt_id",
                                    "revision",
                                )
                            },
                            "project_id": project["project_id"],
                        }
                    ),
                    flush=True,
                )
                _, project = request(origin, route)
                body = {
                    **{
                        key: project[key]
                        for key in ("revision", "input_version", "brief_sha256")
                    },
                    "key": "publish-stage2-activation-offer",
                    "stage": "stage2-controller",
                    "confirmed": True,
                    "profile_sha256": digest,
                }
                status, response = observed(origin, "before-registration", continuation)
                self.assertEqual(
                    (status, response),
                    (409, {"error": "stage2-controller-not-connected"}),
                )
                before_offer = counts(case.intake, ref)
                status, offered = observed(origin, "offer", connections, body=body)
                self.assertEqual(status, 200, offered)
                consent = offered["connections"]["stage2-controller"]
                self.assertEqual(consent["status"], "consent-required")
                self.assertEqual(consent["revision"], body["revision"] + 2)
                self.assertFalse(offered["execution_authorized"])
                self.assertEqual(
                    request(origin, connections, body=body), (200, offered)
                )
                after_offer = counts(case.intake, ref)
                self.assertEqual(
                    after_offer,
                    {
                        "actions": before_offer["actions"] + 1,
                        "events": before_offer["events"] + 2,
                    },
                )
                offer = consent["activation_offer"]
                status, activated = observed(
                    origin,
                    "explicit-activation",
                    route + "/stage2/actions",
                    body={
                        **{
                            key: body[key]
                            for key in ("input_version", "brief_sha256", "confirmed")
                        },
                        "revision": consent["revision"],
                        "key": "activate-stage2",
                        **{key: offer[key] for key in ("offer_ref", "offer_sha256")},
                    },
                )
                self.assertEqual(status, 200, activated)
                self.assertEqual(activated["packet_sha256"], evidence["packet_sha256"])
                _, latest = request(origin, route)
                self.assertEqual(latest["revision"], consent["revision"] + 2)
                self.assertEqual(
                    request(origin, connections, body=body)[1]["connections"][
                        "stage2-controller"
                    ]["status"],
                    "consent-required",
                )
                body = {
                    **body,
                    "key": "connect-stage2",
                    "revision": latest["revision"],
                }
                status, response = observed(origin, "connectable", connections)
                self.assertEqual(status, 200, response)
                self.assertEqual(
                    response["connections"]["stage2-controller"]["status"],
                    "connectable",
                )
                before_registration = counts(case.intake, ref)
                for label, change, refusal_status in (
                    (
                        "typed-version",
                        {"input_version": str(body["input_version"])},
                        400,
                    ),
                    ("brief", {"brief_sha256": "0" * 64}, 409),
                    ("profile-pin", {"profile_sha256": "0" * 64}, 409),
                    ("browser-path", {"controller_root": str(root)}, 400),
                    ("old-revision", {"revision": body["revision"] - 1}, 409),
                ):
                    with self.subTest(refusal=label):
                        self.assertEqual(
                            request(origin, connections, body={**body, **change})[0],
                            refusal_status,
                        )
                code, other = request(
                    origin,
                    "/api/projects",
                    body={
                        "key": "other-project",
                        "topic": "Other authored engineering fixture",
                    },
                )
                self.assertEqual(code, 200, other)
                self.assertEqual(
                    request(
                        origin,
                        f"/api/projects/{other['project_ref']}/connections",
                        body=body,
                    )[0],
                    409,
                )
                self.assertEqual(counts(case.intake, ref), before_registration)
                status, saved = observed(origin, "register", connections, body=body)
                self.assertEqual(status, 200, saved)
                self.assertFalse(saved["execution_authorized"])
                self.assertEqual(request(origin, connections, body=body), (200, saved))
                attached = ConnectionStore(case.intake, VIEWER).resolve(
                    ref, "stage2-controller"
                )
                self.assertEqual(
                    attached["derived_from"]["input_connection_id"],
                    evidence["connection_id"],
                )
                self.assertEqual(
                    attached["derived_from"]["packet_sha256"], evidence["packet_sha256"]
                )
                self.assertEqual(
                    attached["connection_id"],
                    saved["connections"]["stage2-controller"]["connection_id"],
                )
                self.assertEqual(attached["receipt_id"], body["key"])
                self.assertEqual(
                    counts(case.intake, ref),
                    {
                        "actions": before_registration["actions"] + 1,
                        "events": before_registration["events"] + 2,
                    },
                )
                status, response = observed(origin, "ready", continuation)
                self.assertEqual(status, 200, response)
                self.assertEqual(response["status"], "ready")
                self.assertEqual(calls, [])
                for label, artifact in (
                    ("profile", path),
                    ("spec", spec_path),
                    ("preparation", prep_path),
                ):
                    with self.subTest(artifact=label):
                        original = artifact.read_bytes()
                        try:
                            artifact.write_bytes(original + b" ")
                            self.assertEqual(request(origin, continuation)[0], 409)
                        finally:
                            artifact.write_bytes(original)
                intent = {
                    key: body[key]
                    for key in ("input_version", "brief_sha256", "confirmed")
                }
                intent["key"] = "explicit-stage2-continuation"
                with patch("time.time", return_value=deadline + 1):
                    status, response = observed(
                        origin, "expired-before-start", continuation, body=intent
                    )
                    self.assertEqual(
                        (status, response),
                        (
                            409,
                            {
                                "error": "stage2-continuation-original-admission-unavailable"
                            },
                        ),
                    )
                status, submitted = observed(
                    origin, "submit", continuation, body=intent
                )
                self.assertEqual(status, 202, submitted)
                wait_until = time.monotonic() + 360
                while time.monotonic() < wait_until:
                    status, result = request(origin, continuation)
                    if status != 200 or result["status"] != "running":
                        break
                    time.sleep(0.2)
                if status != 200 or result["status"] != "candidate-ready":
                    for name in ("failure.json", "wiki-outcome.json"):
                        failure = root / "ctl/project_stage2_driver" / name
                        if failure.is_file():
                            print(name, failure.read_text(encoding="utf-8"), flush=True)
                    try:
                        host.project_stage2_controllers[ref]
                    except (OSError, ValueError):
                        traceback.print_exc()
                self.assertEqual(status, 200, result)
                self.assertEqual(result["status"], "candidate-ready", result)
                self.assertTrue(result["synthetic_test_only"])
                self.assertFalse(result["execution_authorized"])
                self.assertEqual(len(result["cards"]), 1)
                after_candidate = counts(case.intake, ref)
            with (
                patch("time.time", return_value=deadline + 1),
                wiki(case, path, digest) as (origin, _),
            ):
                self.assertEqual(
                    observed(origin, "candidate-after-reopen-and-expiry", continuation),
                    (200, result),
                )
                self.assertEqual(
                    request(origin, continuation, body=intent), (200, result)
                )
                self.assertEqual(request(origin, connections, body=body), (200, saved))
        self.assertEqual(counts(case.intake, ref), after_candidate)
        self.assertEqual(len(calls), 1)
        self.assertEqual(calls[0].count("research"), 1)
        print(
            json.dumps(
                {
                    "fixture": "counts",
                    "before_offer": before_offer,
                    "after_offer": after_offer,
                    "before_registration": before_registration,
                    "after_candidate": after_candidate,
                    "after_reopen": counts(case.intake, ref),
                    "fixed_controller_invocations": len(calls),
                    "adapter_calls": calls[0],
                    "model_calls": 0,
                    "search_calls": 0,
                }
            ),
            flush=True,
        )
        case.runner.assert_not_called()
