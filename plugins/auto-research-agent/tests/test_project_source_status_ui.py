"""Actual public job serializer to actual UI; authored observations, no worker."""

from copy import deepcopy
import json
from pathlib import Path
import shutil
import subprocess
import unittest

from research_workspace_native.project_stage1_source_service import (
    ProjectStage1SourceService,
)


def public_jobs():
    job = dict(
        key="authored-source-job",
        grant_ref="authored-source-grant",
        job_binding_sha256="a" * 64,
        binding=dict(
            input_version=1,
            brief_sha256="b" * 64,
            scope=dict(selected=dict(work_id="authored-work")),
        ),
        status="source-observation-saved",
        runner_invoked=True,
        invocation_claimed=True,
        invocation_observation=None,
        result=dict(status="saved-transport-observation"),
        failure=None,
    )
    records = []
    for status in (
        None,
        "processing-intent",
        "parser-observation-saved",
        "source-core-registered",
        "execution-unknown",
        "execution-unknown-no-code",
    ):
        sample = deepcopy(job)
        if status is not None:
            sample["followup"] = dict(
                status=status, reading_complete=False, stage1_complete=False
            )
        if status in {"execution-unknown", "execution-unknown-no-code"}:
            sample["followup"]["status"] = "execution-unknown"
            sample["followup"]["failure"] = dict(
                code="source-pipeline-failed-or-unobserved",
                error_code="<authored-parser-refusal>"
                if status == "execution-unknown"
                else None,
                error_type="TimeoutError",
            )
            sample["failure"] = dict(code="authored-transport-observation")
        records.append(ProjectStage1SourceService._public_job(sample))
    return records


class ProjectSourceStatusUiTests(unittest.TestCase):
    def test_public_followup_reaches_trilingual_ui_without_dispatch_or_html(self):
        node = shutil.which("node")
        self.assertIsNotNone(node)
        result = subprocess.run(
            [
                node,
                str(Path(__file__).parent / "browser/project-source-status-test.cjs"),
            ],
            input=json.dumps(public_jobs()),
            encoding="utf8",
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=20,
        )
        self.assertEqual(result.returncode, 0, result.stdout)
        self.assertIn("PASS 36 historical source status renders", result.stdout)


if __name__ == "__main__":
    unittest.main()
