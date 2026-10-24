"""Synthetic offline campaign checks; not a scientific evaluation."""

import copy
import io
import json
from contextlib import redirect_stderr, redirect_stdout
from unittest.mock import patch

from stage3_campaign_test_support import CampaignFixture
from stage3_plan.__main__ import main
from stage3_plan.campaign import POLICY, binding, inspect_campaign
from stage3_plan.contracts import Stage3Error, canonical_bytes
from stage3_plan.storage import read_json


class CampaignPreparationTests(CampaignFixture):
    def test_prepare_replay_orders_views_source_scope_and_no_dispatch(self):
        with (
            patch(
                "subprocess.Popen", side_effect=AssertionError("no process dispatch")
            ),
            patch(
                "stage3_plan.native.NativePlanner.__call__",
                side_effect=AssertionError("no model dispatch"),
            ),
        ):
            result = self.prepare()
            before = {p.name: p.read_bytes() for p in self.campaign.iterdir()}
            self.assertEqual(
                result,
                inspect_campaign(self.campaign, expected_sha256=self.campaign_sha),
            )
            self.assertEqual(result, self.prepare())
            self.assertEqual(
                before, {p.name: p.read_bytes() for p in self.campaign.iterdir()}
            )
            for row in result["manifest"]["schedule"]:
                self.assertEqual(row["subject_order"], ["A", "B"])
                self.assertEqual(row["display_order"], ["B", "A"])
            unit = self.manifest["units"][0]
            view = read_json(self.campaign / (unit["subject_id"] + ".json"))
            self.assertNotIn(self.plan["plan_id"], json.dumps(view))
            self.assertNotIn("aliases", view)
            self.assertNotIn("arm", view)
            self.assertNotIn(str(self.root), json.dumps(view))
            self.assertEqual(len(view["plan"]["questions"]), 3)
            self.assertIn("synthetic", unit["source_scope"])
            self.assertEqual(result["manifest"]["policy"], POLICY)

    def test_source_and_view_tampering_reject_even_after_rehash(self):
        self.prepare()
        path = self.campaign / "manifest.json"
        changed = read_json(path)
        changed["units"][0]["source_scope"] = "strict-selected"
        path.write_bytes(canonical_bytes(changed))
        with self.assertRaisesRegex(Stage3Error, "replay"):
            inspect_campaign(self.campaign, expected_sha256=binding(path)["sha256"])

    def test_bounds_splits_identity_and_request_source_mismatch(self):
        mutations = [
            lambda d: d["limits"].update(max_units=1),
            lambda d: d["limits"].update(max_view_bytes=1),
            lambda d: d["cases"][1].update(split="held-out"),
            lambda d: d["cases"][1].update(case_id="case-0"),
            lambda d: d["cases"][0]["selection"].update(
                source_manifest_sha256="0" * 64
            ),
            lambda d: d.update(seed=True),
        ]
        original = copy.deepcopy(self.definition)
        for mutate in mutations:
            with self.subTest(mutate=mutate):
                self.definition = copy.deepcopy(original)
                mutate(self.definition)
                with self.assertRaises((Stage3Error, ValueError)):
                    self.prepare()
                self.assertFalse(self.campaign.exists())

    def test_cli_prepare_and_inspect_are_offline(self):
        stdout, stderr = io.StringIO(), io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            code = main(
                [
                    "campaign-prepare",
                    "--definition",
                    str(self.definition_path),
                    "--expected-sha256",
                    binding(self.definition_path)["sha256"],
                    "--output",
                    str(self.campaign),
                ]
            )
        self.assertEqual(code, 0, stderr.getvalue())
        self.campaign_sha = json.loads(stdout.getvalue())["campaign_sha256"]
        stdout = io.StringIO()
        with redirect_stdout(stdout), redirect_stderr(stderr):
            self.assertEqual(
                main(
                    [
                        "campaign-inspect",
                        "--campaign",
                        str(self.campaign),
                        "--expected-sha256",
                        self.campaign_sha,
                    ]
                ),
                0,
            )
        self.assertEqual(json.loads(stdout.getvalue())["manifest"]["policy"], POLICY)

    def test_raw_definition_bytes_and_boolean_policy_are_bound(self):
        self.prepare()
        self.definition_path.write_text(
            json.dumps(self.definition, indent=2), encoding="utf-8"
        )
        from stage3_plan.campaign import prepare_campaign

        with self.assertRaises(Stage3Error):
            prepare_campaign(
                self.definition_path,
                expected_sha256=binding(self.definition_path)["sha256"],
                output=self.campaign,
            )
        path = self.campaign / "manifest.json"
        value = read_json(path)
        value["policy"]["execution_authorized"] = 0
        path.write_bytes(canonical_bytes(value))
        with self.assertRaises(Stage3Error):
            inspect_campaign(self.campaign, expected_sha256=binding(path)["sha256"])

    def test_seeded_schedule_is_rebuilt_and_private_output_is_required(self):
        self.definition["subject_order"] = self.definition["display_order"] = "seeded"
        self.prepare()
        self.assertEqual(
            inspect_campaign(self.campaign, expected_sha256=self.campaign_sha)[
                "manifest"
            ]["schedule"],
            self.manifest["schedule"],
        )
        invalid = copy.deepcopy(self.definition)
        invalid["analysis"]["audit_triggers"] = [[]]
        self.definition = invalid
        with self.assertRaises(Stage3Error):
            self.prepare()
