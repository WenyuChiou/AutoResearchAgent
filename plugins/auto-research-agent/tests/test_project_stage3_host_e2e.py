"""Real authenticated Host chain with authored provider responses only.

No HTTP, source admission, selection frontier or job persistence is mocked.
Scientific quality and real human candidate approval are outside this test.
"""

import json
import os
from pathlib import Path
import threading
import time
import unittest
import urllib.error
import urllib.request

from project_stage3_host_e2e_fixture import Stage3HostE2ESeed
from research_workspace_native.project_host import ProjectHost
from stage3_plan.jobs import POLICY


class HostConnection:
    def __init__(self, case, seed, *, recovery_pins=None):
        self.seed = seed
        self.host = ProjectHost(
            projects=seed.intake,
            credential=seed.credential,
            stage2=seed.stage2,
            stage2_selection=seed.selection,
            stage3_planning=seed.planning,
            stage3_recovery_pins=recovery_pins,
            files={},
            views=[],
            port=0,
            timeout=30,
        )
        self.thread = threading.Thread(
            target=self.host.serve_forever, kwargs={"poll_interval": 0.05}
        )
        self.thread.start()
        self.closed = False
        self.timings = []
        case.addCleanup(self.close)

    def close(self):
        if not self.closed:
            self.host.shutdown()
            self.host.server_close()
            self.thread.join(timeout=5)
            self.closed = True
            if self.thread.is_alive():
                raise AssertionError("Host request listener did not stop")

    def request(self, path, body=None, *, credential=True, origin=None, headers=None):
        supplied = {"Origin": origin or self.host.expected_origin}
        if credential:
            supplied["Authorization"] = "Bearer " + self.seed.credential
        if headers:
            supplied.update(headers)
        raw = None if body is None else json.dumps(body).encode("utf-8")
        if raw is not None:
            supplied["Content-Type"] = "application/json"
        request = urllib.request.Request(
            self.host.expected_origin + path, data=raw, headers=supplied
        )
        started = time.monotonic()
        try:
            with urllib.request.urlopen(request, timeout=32) as response:
                status, value = response.status, json.loads(response.read())
        except urllib.error.HTTPError as error:
            status, value = error.code, json.loads(error.read())
        row = dict(
            method="GET" if body is None else "POST",
            path=path,
            status=status,
            seconds=round(time.monotonic() - started, 3),
        )
        self.timings.append(row)
        print(json.dumps(row), flush=True)
        return status, value


def select_current(connection, seed):
    path = "/api/projects/" + seed.ref
    status, view = connection.request(path + "/stage2/selection")
    seed.case.assertEqual(status, 200, view)
    body = {
        name: view[name]
        for name in (
            "revision",
            "input_version",
            "brief_sha256",
            "delivery_manifest_sha256",
            "workflow_head_sha256",
            "snapshot_sha256",
        )
    }
    body.update(
        key="authored-http-e2e-choice",
        confirmed=True,
        decision=dict(
            actor="synthetic-e2e-actor",
            kind="select",
            selected=view["eligible"],
            user_text="Authored engineering choice; no real human approval.",
            conditions=["Keep limitations"],
            unresolved=["Access unknown"],
            rationale="Exercise the actual selection receipt route.",
            scope_or_resource_change=False,
        ),
    )
    status, selected = connection.request(path + "/stage2/select", body)
    seed.case.assertEqual(status, 200, selected)
    seed.case.assertEqual(selected["status"], "saved")
    seed.case.assertFalse(seed.intake.db.in_transaction)
    return selected


class ProjectStage3HostE2ETests(unittest.TestCase):
    def assert_policy(self, result):
        for name in POLICY:
            self.assertIs(result[name], False)

    def test_current_selection_to_plan_replay_and_host_restart(self):
        seed = Stage3HostE2ESeed(
            self, evidence_root=os.environ.get("STAGE3_E2E_EVIDENCE_ROOT")
        )
        connection = HostConnection(self, seed)
        route = "/api/projects/" + seed.ref + "/stage3/planning"
        with self.subTest("authentication-and-origin"):
            self.assertEqual(connection.request(route, credential=False)[0], 401)
            self.assertEqual(
                connection.request(route, origin="http://127.0.0.1:9")[0], 403
            )
            self.assertEqual(
                connection.request(route, headers={"Sec-Fetch-Site": "cross-site"})[0],
                403,
            )
        status, pending = connection.request(route)
        self.assertEqual(status, 200, pending)
        self.assertIsNone(pending["default_request"])
        self.assertIsNone(pending["job"])
        self.assertIsNone(pending["plan"])
        self.assert_policy(pending)
        self.assertEqual(seed.callback.calls, [])
        selected = select_current(connection, seed)
        status, ready = connection.request(route)
        self.assertEqual(status, 200, ready)
        body = ready["default_request"]
        self.assertEqual(body["selection_request_sha256"], selected["request_sha256"])
        self.assertIs(type(body["input_version"]), str)
        with self.subTest("browser-cannot-change-configuration"):
            self.assertEqual(
                connection.request(route + "/prepare", dict(body, model="injected"))[0],
                400,
            )
            self.assertEqual(
                connection.request(route + "/prepare", dict(body, input_version=1))[0],
                409,
            )
            self.assertEqual(seed.callback.calls, [])
        status, prepared = connection.request(route + "/prepare", body)
        self.assertEqual(status, 200, prepared)
        self.assertEqual(prepared["status"], "intent-recorded")
        pinned = dict(body, request_sha256=prepared["request_sha256"])
        self.assertEqual(connection.request(route + "/prepare", body), (200, prepared))
        self.assertEqual(connection.request(route + "/inspect", pinned)[0], 200)
        self.assertEqual(seed.callback.calls, [])
        self.assertEqual(
            connection.request(route + "/run", dict(pinned, confirmed=False))[0], 400
        )
        self.assertEqual(
            connection.request(route + "/recover", pinned),
            (409, {"error": "trusted-stage3-recovery-pin-required"}),
        )
        status, submitted = connection.request(
            route + "/run", dict(pinned, confirmed=True)
        )
        self.assertEqual(status, 202, submitted)
        self.assertEqual(submitted["submission_status"], "accepted")
        self.assertIs(submitted["dispatch_observed"], False)
        self.assert_policy(submitted)
        self.assertTrue(seed.callback.entered.wait(timeout=30))
        deadline = time.monotonic() + 60
        for _ in range(3):
            status, saved = connection.request(route)
            self.assertEqual(status, 200, saved)
            if saved["job"]["outcome"] == "saved":
                break
            self.assertLess(time.monotonic(), deadline)
            threading.Event().wait(0.05)
        else:
            self.fail("Saved plan did not become readable within bounded observations")
        result, plan = saved["job"], saved["plan"]
        self.assertEqual(result["planning_status"], "needs-information")
        actual = seed.callback.calls[0]["intake"]
        self.assertEqual(plan["selected_candidates"], actual["selected_candidates"])
        self.assertEqual(plan["questions"], actual["questions"])
        resources = {row["resource_id"] for row in plan["resources"]}
        for question in actual["questions"]:
            ref = question["question_ref"]
            question_plan = next(
                row for row in plan["question_plans"] if row["question_ref"] == ref
            )
            self.assertTrue(question_plan["resource_uses"])
            self.assertTrue(
                all(
                    row["resource_id"] in resources
                    for row in question_plan["resource_uses"]
                )
            )
            for group, id_field, refs_field in (
                ("designs", "design_id", "design_ids"),
                ("analyses", "analysis_id", "analysis_ids"),
                ("results", "result_id", "result_ids"),
            ):
                targets = {row[id_field]: row for row in plan[group]}
                for identity in question_plan[refs_field]:
                    self.assertIn(ref, targets[identity]["question_refs"])
        for row in plan["results"]:
            self.assertEqual(row["status"], "not-run")
            self.assertIsNone(row["observed_value"])
            self.assertEqual(
                set(row["interpretation"]), {"supports", "contradicts", "inconclusive"}
            )
        self.assertTrue(plan["condition_dispositions"])
        self.assertTrue(
            any(
                row["blocking"] and row["resolve_before"] == "material-design"
                for row in plan["unknowns"]
            )
        )
        self.assertEqual(
            connection.request(route + "/run", dict(pinned, confirmed=True)),
            (200, result),
        )
        self.assertEqual(connection.request(route + "/inspect", pinned), (200, result))
        connection.close()
        resumed = HostConnection(
            self,
            seed,
            recovery_pins={
                (seed.ref, body["key"], pinned["request_sha256"]): result[
                    "plan_manifest_sha256"
                ]
            },
        )
        self.assertEqual(resumed.request(route + "/recover", pinned), (200, result))
        self.assertEqual(len(seed.callback.calls), 1)
        self.assertEqual(seed.native_guard.call_count, 0)
        self.assert_policy(result)
        if os.environ.get("STAGE3_E2E_EVIDENCE_ROOT"):
            target = Path(seed.root) / "http-e2e-summary.json"
            seed.write_summary(target)


if __name__ == "__main__":
    unittest.main(verbosity=2)
