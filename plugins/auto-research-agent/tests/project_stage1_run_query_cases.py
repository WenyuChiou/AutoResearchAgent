"""Original query owner/compiler/Core; fixture backend/probe, no external search."""

import time
import json
from types import SimpleNamespace, MethodType
import unittest
from unittest.mock import patch

from project_query_run_cases import setup_case
from stage1_retrieval.runtime_identity import verify_identity
from research_workspace_native.project_host import ProjectHost
from research_workspace_native.project_model import ProjectModelService
from research_workspace_native.project_records_prepare import (
    ProjectRecordsPrepareService,
)
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)


class RunQueryDispatchTests(unittest.TestCase):
    def test_original_host_authorizes_bootstraps_and_executes_one_planned_query(self):
        with setup_case() as (case, issuer, grant, now, consent, derived):
            materials = case.root / "whole-run-materials"
            materials.mkdir()
            delivery = ProjectStage1DeliveryService(case.stage1)
            records = case.queries.create_records_service(
                delivery, materials_root=materials
            )
            models = ProjectModelService(
                case.intake, reading_records=records, run_grants=issuer
            )
            try:
                host = SimpleNamespace(
                    projects=case.intake,
                    project_stage1=case.stage1,
                    project_models=models,
                    project_stage2=None,
                    project_stage1_delivery=delivery,
                    project_stage1_records=records,
                    project_records_prepare=ProjectRecordsPrepareService(records),
                    project_stage1_sources=None,
                    project_stage1_source_dispatcher=None,
                    project_expansions=None,
                )
                for name in ("overview", "stage1_view", "continue_stage1"):
                    setattr(host, name, MethodType(getattr(ProjectHost, name), host))
                with (
                    patch(
                        "stage1_retrieval.runtime_identity.verify_identity",
                        side_effect=lambda pin, **kw: verify_identity(pin),
                    ),
                    case.fake_runner(),
                    case.no_probe(),
                ):
                    result = host.continue_stage1(
                        "alice-token",
                        case.ref,
                        run_id="whole-query",
                        deadline=time.monotonic() + 90,
                        max_actions=3,
                        run_grants=issuer,
                        grant_ref=grant["grant_ref"],
                        grant_sha256=grant["grant_sha256"],
                    )
                if result["action_count"] != 3:
                    overview = host.overview("alice-token", case.ref)
                    from research_workspace_native.project_stage1_progress import (
                        project_progress,
                    )

                    print(
                        json.dumps(
                            dict(
                                diagnostic=project_progress(overview),
                                stage=overview["stage1"],
                                models=overview["models"],
                            ),
                            default=str,
                        ),
                        flush=True,
                    )
                self.assertEqual(result["action_count"], 3, result)
                self.assertEqual(
                    host.stage1_view("alice-token", case.ref)["reading_registration"][
                        "status"
                    ],
                    "ready",
                )
                kinds = [
                    case.intake.action("alice-token", a["key"], project_ref=case.ref)[
                        "kind"
                    ]
                    for a in result["actions"]
                ]
                self.assertEqual(
                    kinds,
                    [
                        "stage1-query-authorize",
                        "stage1-query-bootstrap",
                        "stage1-query-execute",
                    ],
                )
                view = case.queries.read("alice-token", case.ref)
                self.assertEqual(view["budget"]["attempts"], 1)
                self.assertFalse(result["stage1_complete"])
                self.assertFalse(result["stage2_started"])
            finally:
                models.close()


if __name__ == "__main__":
    unittest.main()
