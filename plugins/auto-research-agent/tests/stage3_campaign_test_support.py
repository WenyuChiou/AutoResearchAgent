"""Private synthetic campaign fixtures; no providers are initialized."""

import sys
import tempfile
import unittest
from pathlib import Path

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]

from stage3_plan.campaign import SELECTION_FIELDS, binding, prepare_campaign  # noqa: E402
from stage3_plan.contracts import canonical_bytes, digest  # noqa: E402
from stage3_plan.evaluation import CRITERIA, prepare_evaluation  # noqa: E402
from stage3_plan.planner import draft_synthetic_plan  # noqa: E402
from stage3_plan.storage import read_json  # noqa: E402
from stage3_plan_fixtures import make_intake, make_plan  # noqa: E402


class CampaignFixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.plan = make_plan("theory", question_count=3, shared_path=True)
        package = self.root / "plan"
        saved = draft_synthetic_plan(
            make_intake(self.plan),
            package,
            lambda **_: {
                "raw_response": canonical_bytes(self.plan),
                "provenance": {"kind": "synthetic"},
            },
            configuration={"model": "stub", "reasoning": "medium"},
            plan_id=self.plan["plan_id"],
        )
        self.request_path = self.root / "request.json"
        self.request = prepare_evaluation(
            package,
            expected_manifest_sha256=saved["manifest"]["manifest_sha256"],
            output=self.request_path,
        )
        self.definition = {
            "kind": "Stage3CampaignDefinition",
            "schema_version": "1.0.0",
            "campaign_id": "synthetic-campaign",
            "seed": 19,
            "repetitions": 1,
            "arms": {
                arm: {"build_sha256": digest(arm), "protocol": "declared-" + arm}
                for arm in ("A", "B")
            },
            "runtime": {
                "model": "configured-model",
                "reasoning": "medium",
                "tool_policy": "none",
                "timeout_seconds": 90,
            },
            "roles": {
                role: {"model": "configured-" + role, "reasoning": "medium"}
                for role in ("R1", "R2", "ADJ")
            },
            "subject_order": "AB",
            "display_order": "BA",
            "limits": {"max_units": 12, "max_view_bytes": 2_000_000},
            "analysis": {
                "version": "1.0.0",
                "case_rule": "pareto-over-planned-pairs",
                "audit_triggers": ["disagreement", "grader_error", "unverifiable"],
            },
            "cases": [
                {
                    "case_id": "case-" + str(i),
                    "base_case_id": "one-base",
                    "variant": str(i),
                    "research_type": "theory" if i == 0 else "qualitative",
                    "split": "calibration",
                    "selection": {
                        k: self.request["bindings"][k] for k in SELECTION_FIELDS
                    },
                    "subjects": [
                        {
                            "repeat": 1,
                            "arm": arm,
                            "request": binding(self.request_path),
                            "failure": None,
                        }
                        for arm in ("A", "B")
                    ],
                }
                for i in range(2)
            ],
        }
        self.definition_path = self.save("definition.json", self.definition)
        self.campaign = self.root / "campaign"

    def save(self, name, value):
        path = self.root / name
        path.write_bytes(canonical_bytes(value))
        return path

    def prepare(self):
        self.definition_path.write_bytes(canonical_bytes(self.definition))
        result = prepare_campaign(
            self.definition_path,
            expected_sha256=binding(self.definition_path)["sha256"],
            output=self.campaign,
        )
        self.campaign_sha = result["campaign_sha256"]
        self.manifest = result["manifest"]
        return result

    def judgment(self, unit, score=2, status="scored"):
        view = read_json(self.campaign / (unit["subject_id"] + ".json"))
        rows = []
        for dimension, criterion in CRITERIA.items():
            row = {
                "criterion_id": criterion,
                "status": status,
                "score": score if status == "scored" else None,
            }
            if status == "grader_error":
                row["error"] = {
                    "kind": "429",
                    "message": "Injected external failure; no API call.",
                }
            else:
                row["question_assessments"] = [
                    {
                        "question_ref": q["question_ref"],
                        "applicability_basis": "Synthetic condition applies.",
                        "rationale": "Synthetic engineering fixture only.",
                        "plan_locations": ["/question_plans/0"],
                    }
                    for q in view["plan"]["questions"]
                ]
                if status == "unverifiable":
                    row["missing_evidence_reason"] = "Independent evidence unavailable."
            rows.append(row)
        return {
            "kind": "Stage3EvaluationJudgment",
            "schema_version": "1.0.0",
            "request_sha256": unit["request"]["sha256"],
            "reviewer": {
                "actor": "declared-" + unit["role"],
                "kind": "synthetic",
                "relationship_to_author": "unknown",
                "identity_authenticated": False,
                "evidence_ref": "synthetic",
            },
            "criteria": rows,
        }

    def record(self, unit, score=2, status="scored"):
        from stage3_plan.campaign_records import record_campaign

        path = self.save(
            unit["unit_id"] + "-input.json", self.judgment(unit, score, status)
        )
        return record_campaign(
            self.campaign,
            expected_sha256=self.campaign_sha,
            unit_id=unit["unit_id"],
            judgment=path,
            expected_judgment_sha256=binding(path)["sha256"],
            output=self.root / unit["unit_id"],
        )

    def summary(self, refs):
        from stage3_plan.campaign_summary import summarize_campaign

        path = self.save(
            "index.json",
            {
                "kind": "Stage3CampaignIndex",
                "schema_version": "1.0.0",
                "campaign_sha256": self.campaign_sha,
                "receipts": refs,
                "human_interventions": None,
            },
        )
        return summarize_campaign(
            self.campaign,
            expected_sha256=self.campaign_sha,
            index=path,
            expected_index_sha256=binding(path)["sha256"],
        )
