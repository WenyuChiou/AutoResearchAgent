"""The Harness record summary is read-only and never invents a number."""

# ruff: noqa: E402 -- exercise the plugin and ordinary Wiki composition together.
from contextlib import ExitStack
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

sys.path[:0] = [
    str(Path(__file__).resolve().parents[1] / "cli"),
    str(Path(__file__).resolve().parents[3] / "harness-ui"),
]
from current_core_stage12_fixtures import current_core_stage1_case
from test_project_stage2_current_evidence import authenticate, request, VIEWER
from test_project_stage_connections import counts, wiki
from research_workspace_native.project_harness_record import CATEGORIES, _classify


class HarnessRecordTests(unittest.TestCase):
    def test_summary_is_read_only_and_every_missing_value_says_so(self):
        with (
            patch("test_project_stage1_delivery.authenticate", authenticate),
            ExitStack() as fixture,
        ):
            data = fixture.enter_context(current_core_stage1_case(screened=True))
            case, ref = data["case"], data["project_ref"]
            route = f"/api/projects/{ref}/harness-record"

            def snapshot():
                root = case.intake.root / ref
                state = case.intake._load(case.intake._principal(VIEWER), ref)
                return (
                    counts(case.intake),
                    state["revision"],
                    data["ledger"].state_hash(),
                    {
                        str(file.relative_to(case.intake.root)): file.read_bytes()
                        for file in case.intake.root.rglob("*")
                        if file.is_file()
                        and not file.name.startswith("project-intake.sqlite")
                    },
                    root.exists(),
                )

            with wiki(case, connections=True) as origin:
                before = snapshot()
                status, first = request(origin, route)
                self.assertEqual(status, 200, first)
                status, second = request(origin, route)
                self.assertEqual((status, second), (200, first))
                self.assertEqual(snapshot(), before)
                self.assertEqual(first["kind"], "HarnessRecordSummary")
                self.assertTrue(first["read_only"])
                self.assertFalse(first["execution_authorized"])
                self.assertEqual(first["project_ref"], ref)
                self.assertEqual(set(first["stages"]), {"1", "2", "3"})
                one = first["stages"]["1"]
                self.assertEqual(one["status"], "recorded", one)
                keys = [row["key"] for row in one["rows"]]
                self.assertEqual(
                    keys,
                    [
                        "search",
                        "screening",
                        "evidence",
                        "source-check",
                        "source-acquisition",
                        "coverage-stop",
                        "checkpoint",
                    ],
                )
                for row in one["rows"]:
                    self.assertIn(row["source"]["view"], {"stage1"})
                    self.assertTrue(row["source"]["path"])
                    # a value is either a saved count or an explicit "missing"
                    self.assertTrue(row["value"] is not None or row["missing"])
                self.assertGreater(one["summary"]["records"], 0)
                for stage in first["stages"].values():
                    self.assertEqual(
                        [cell["category"] for cell in stage["blocked"]],
                        [name for name, _ in CATEGORIES],
                    )
                    self.assertFalse(stage["reopen"]["available"])
                    self.assertFalse(stage["timeline"]["available"])
                    self.assertTrue(stage["blocked_scope"])
                # Stage 2 and 3 were never run for this project: no numbers.
                for stage in ("2", "3"):
                    self.assertEqual(first["stages"][stage]["rows"], [])
                    self.assertIn(
                        first["stages"][stage]["status"], {"not-run", "unavailable"}
                    )
                # Wrong method, extra path and unknown project are refused.
                self.assertGreaterEqual(
                    request(origin, route, body={"key": "x"})[0], 400
                )
                self.assertEqual(snapshot(), before)
                status, _ = request(
                    origin,
                    "/api/projects/project-00000000000000000000000000000000/harness-record",
                )
                self.assertEqual(status, 404)

    def test_new_route_checks_credentials_origin_and_creates_only_the_temporary_lock(
        self,
    ):
        import json as _json
        from urllib.error import HTTPError
        from urllib.request import Request, urlopen
        import pathlib

        with (
            patch("test_project_stage1_delivery.authenticate", authenticate),
            ExitStack() as fixture,
        ):
            data = fixture.enter_context(current_core_stage1_case(screened=True))
            case, ref = data["case"], data["project_ref"]
            route = f"/api/projects/{ref}/harness-record"
            with wiki(case, connections=True) as origin:
                self.assertEqual(request(origin, route, token=None)[0], 401)
                for headers in (
                    {"Sec-Fetch-Site": "cross-site"},
                    {"Origin": "http://evil.example"},
                ):
                    req = Request(
                        origin + route,
                        headers={"Authorization": "Bearer " + VIEWER, **headers},
                    )
                    try:
                        status = urlopen(req, timeout=60).status
                    except HTTPError as error:
                        status = error.code
                    self.assertGreaterEqual(status, 400, headers)
                created = []
                real_open = pathlib.Path.open

                def watching(self, mode="r", *args, **kwargs):
                    if any(flag in mode for flag in "xwa"):
                        created.append(self.name)
                    return real_open(self, mode, *args, **kwargs)

                with patch.object(pathlib.Path, "open", watching):
                    status, one = request(origin, route + "/stage-1")
                self.assertEqual(status, 200, one)
                self.assertEqual(set(one["stages"]), {"1"})
                self.assertTrue(one["temporary_files"])
                self.assertTrue(
                    all(name == ".writer-lock" for name in created), created
                )
                self.assertFalse(
                    list((case.intake.root).rglob(".writer-lock")),
                    "the temporary lock must be gone after the read",
                )
                status, _ = request(origin, route + "/stage-9")
                self.assertGreaterEqual(status, 400)
                _ = _json

    def test_failure_classes_and_scope(self):
        self.assertEqual(_classify("project-unavailable"), "wrong-project")
        self.assertEqual(_classify("stage2-selection-view-stale"), "stale-version")
        self.assertEqual(_classify("idempotency-payload-differs"), "duplicate-click")
        self.assertEqual(_classify("intake-action-bound-exceeded"), "over-limit")
        self.assertEqual(_classify("anything-else"), "failed-check")


if __name__ == "__main__":
    unittest.main()
