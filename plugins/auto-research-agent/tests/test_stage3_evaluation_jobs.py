"""Injected single-role evaluation jobs; no scientific scores or native calls."""

import copy
import hashlib
import importlib
from pathlib import Path
import sys
import unittest
from unittest.mock import Mock, patch
import subprocess

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN / "cli"), str(PLUGIN / "tests")]
from research_workspace_native.journal import JournalError  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes  # noqa: E402
from stage3_plan.evaluation import prepare_evaluation, record_evaluation  # noqa: E402
from stage3_plan.evaluation_jobs import EvaluationJobs, save_campaign_index  # noqa: E402
from stage3_plan.jobs import PlanningJobs, _ref  # noqa: E402
from stage3_plan.storage import read_json  # noqa: E402


class EvaluationJobTests(unittest.TestCase):
    def setUp(self):
        from test_stage3_jobs import PlanningJobTests
        from test_stage3_evaluation import Stage3EvaluationTests

        self.f = PlanningJobTests()
        self.f.setUp()
        self.addCleanup(self.f.doCleanups)
        self.addCleanup(self.f.tearDown)
        planning = self.f.execute(self.f.prepare())
        self.checkpoint = planning["result"]["checkpoint"]
        self.request_path = self.f.root / "evaluation-request.json"
        self.request = prepare_evaluation(
            planning["result"]["plan"]["package"],
            expected_manifest_sha256=planning["result"]["plan"]["manifest_sha256"],
            output=self.request_path,
        )
        self.request_ref = _ref(self.request_path)
        self.judgments = Stage3EvaluationTests()
        self.judgments.plan = self.f.plan
        self.judgments.request_path = self.request_path
        self.context = {"kind": "synthetic-role-adapter", "timeout_seconds": 5}
        self.config = {"model": "fixture-judge", "reasoning": "medium"}
        self.callback = Mock(
            side_effect=lambda **kw: {
                "raw_response": canonical_bytes(self.judgments.judgment()),
                "provenance": {"kind": "synthetic", "identity": "not-established"},
                "stdout": b"Original synthetic prose.\n",
                "stderr": b"",
                "returncode": 0,
            }
        )
        self.callback.request_context = self.context
        self.jobs = self.controller()

    def controller(self, role="R1", request=None, campaign=None):
        return EvaluationJobs(
            self.f.journal,
            "project-a",
            self.f.owner,
            self.f.root / "jobs",
            request=request or self.request_ref,
            role=role,
            campaign=campaign,
        )

    def prepare(self, jobs=None, key="grade"):
        return (jobs or self.jobs).prepare(
            key,
            checkpoint=self.checkpoint,
            configuration=self.config,
            adapter_context=self.context,
            expected_revision=self.f.journal.snapshot("project-a")["revision"],
        )

    def execute(self, prepared, jobs=None, key="grade"):
        return (jobs or self.jobs).run(
            key,
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            callback=self.callback,
        )

    def payload(self, jobs=None, key="grade"):
        jobs = jobs or self.jobs
        return self.f.journal.snapshot("project-a")["intents"][jobs._key(key)][
            "payload"
        ]

    def interrupt_after_record(self, prepared):
        transition = self.jobs._transition

        def cut(key, status, evidence):
            if status == "completed":
                raise OSError("injected post-record journal persistence failure")
            return transition(key, status, evidence)

        with patch.object(self.jobs, "_transition", side_effect=cut):
            with self.assertRaises(OSError):
                self.execute(prepared)
        return Path(self.payload()["output"])

    def campaign_job(self):
        from stage3_campaign_test_support import CampaignFixture
        from stage3_plan.campaign import SELECTION_FIELDS

        campaign = CampaignFixture()
        campaign.setUp()
        self.addCleanup(campaign.doCleanups)
        for case in campaign.definition["cases"]:
            case["selection"] = {
                key: self.request["bindings"][key] for key in SELECTION_FIELDS
            }
            for subject in case["subjects"]:
                subject["request"] = self.request_ref
        campaign.prepare()
        unit = next(u for u in campaign.manifest["units"] if u["role"] == "R1")
        sibling = next(
            u
            for u in campaign.manifest["units"]
            if u["subject_id"] == unit["subject_id"] and u["role"] == "R2"
        )
        self.jobs = self.controller(
            campaign={
                "root": str(campaign.campaign),
                "sha256": campaign.campaign_sha,
                "unit_id": unit["unit_id"],
            }
        )
        self.callback.side_effect = lambda **kw: {
            "raw_response": canonical_bytes(campaign.judgment(unit)),
            "provenance": {"kind": "synthetic"},
        }
        return unit, sibling

    def test_campaign_recovery_rejects_sibling_unit_then_recovers_correct_unit(self):
        unit, sibling = self.campaign_job()
        prepared = self.prepare()
        root = self.interrupt_after_record(prepared)
        path = root / "unit/receipt.json"
        original = path.read_bytes()
        receipt = read_json(path)
        receipt["unit_id"] = sibling["unit_id"]
        path.write_bytes(canonical_bytes(receipt))
        kwargs = dict(
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
        )
        with self.assertRaisesRegex(Stage3Error, "job unit"):
            self.jobs.recover(
                "grade", expected_record_sha256=_ref(path)["sha256"], **kwargs
            )
        path.write_bytes(original)
        recovered = self.jobs.recover(
            "grade", expected_record_sha256=_ref(path)["sha256"], **kwargs
        )
        self.assertEqual(recovered["result"]["outcome"], "saved")
        self.assertEqual(recovered["result"]["role"], "R1")
        self.assertEqual(read_json(path)["unit_id"], unit["unit_id"])
        self.assertEqual(self.execute(prepared), recovered)
        self.assertEqual(self.callback.call_count, 1)

    def test_failed_campaign_receipt_keeps_exact_job_unit_binding(self):
        _, sibling = self.campaign_job()
        self.callback.side_effect = lambda **kw: {
            "raw_response": b"{bad",
            "provenance": {"kind": "synthetic"},
        }
        failed = self.execute(self.prepare())
        failure_path = Path(failed["result"]["failure"]["path"])
        failure = read_json(failure_path)
        path = Path(failure["artifacts"]["unit/receipt.json"]["path"])
        receipt = read_json(path)
        self.assertEqual(receipt["status"], "failed")
        receipt["unit_id"] = sibling["unit_id"]
        path.write_bytes(canonical_bytes(receipt))
        failure["artifacts"]["unit/receipt.json"] = _ref(path)
        failure_path.write_bytes(canonical_bytes(failure))
        with self.assertRaisesRegex(Stage3Error, "job unit"):
            self.jobs._verify_failure(_ref(failure_path))
        self.assertEqual(self.callback.call_count, 1)

    def test_partial_record_write_preserves_readable_failed_result_without_retry(self):
        prepared = self.prepare()

        def partial_write(*args, **kwargs):
            Path(kwargs["output"]).write_bytes(b"{bad")
            raise OSError("injected partial evaluation record write")

        with patch(
            "stage3_plan.evaluation_jobs.record_evaluation", side_effect=partial_write
        ):
            failed = self.execute(prepared)
        self.assertEqual(failed["result"]["outcome"], "failed")
        failure = read_json(failed["result"]["failure"]["path"])
        self.assertEqual(failure["error_class"], "OSError")
        self.assertEqual(failure["message"], "injected partial evaluation record write")
        partial = failure["artifacts"]["unvalidated:record.json"]
        self.assertEqual(Path(partial["path"]).read_bytes(), b"{bad")
        self.assertEqual(_ref(partial["path"]), partial)
        self.assertEqual(
            self.jobs.inspect(
                "grade",
                expected_request_sha256=prepared["request_sha256"],
                current_checkpoint=self.checkpoint,
            ),
            failed,
        )
        self.assertEqual(self.execute(prepared), failed)
        self.assertEqual(self.callback.call_count, 1)

    def test_complete_failure_artifacts_reject_rehashed_record_and_capture_tampering(
        self,
    ):
        for name in ("record.json", "adapter-result.json"):
            with self.subTest(artifact=name):
                key = name
                prepared = self.prepare(key=key)
                with patch.object(
                    self.jobs, "_saved", side_effect=OSError("after complete record")
                ):
                    failed = self.execute(prepared, key=key)
                self.assertEqual(failed["result"]["outcome"], "failed")
                failure_path = Path(failed["result"]["failure"]["path"])
                failure = read_json(failure_path)
                self.assertIn(name, failure["artifacts"])
                path = Path(failure["artifacts"][name]["path"])
                value = read_json(path)
                if name == "record.json":
                    value["score_vector"]["P7"]["score"] = False
                else:
                    value["returncode"] = False
                path.write_bytes(canonical_bytes(value))
                failure["artifacts"][name] = _ref(path)
                failure_path.write_bytes(canonical_bytes(failure))
                with self.assertRaises(Stage3Error):
                    self.jobs._verify_failure(_ref(failure_path))
        self.assertEqual(self.callback.call_count, 2)

    def test_roles_keep_raw_prose_vectors_identity_unknown_and_no_reexecution(self):
        for role in ("R1", "R2", "ADJ"):
            with self.subTest(role=role):
                jobs = self.controller(role)
                prepared = self.prepare(jobs, role)
                self.assertEqual(prepared["status"], "intent-recorded")
                result = self.execute(prepared, jobs, role)
                self.assertEqual(result["result"]["role"], role)
                self.assertEqual(
                    set(result["result"]["score_vector"]), {"P7", "P8", "P9"}
                )
                self.assertEqual(result["result"]["reviewer_identity"], "unverified")
                capture = read_json(result["result"]["capture"]["path"])
                self.assertEqual(
                    Path(capture["stdout"]["path"]).read_bytes(),
                    b"Original synthetic prose.\n",
                )
                self.assertEqual(capture["returncode"], 0)
                before = self.callback.call_count
                self.assertEqual(self.execute(prepared, jobs, role), result)
                self.assertEqual(self.callback.call_count, before)
                self.assertTrue(all(v is False for v in result["policy"].values()))
        self.assertEqual(self.callback.call_count, 3)

    def test_unverifiable_and_grader_error_are_saved_without_becoming_scored(self):
        statuses = {
            "P7": ("scored", 1),
            "P8": ("unverifiable", None),
            "P9": ("grader_error", ("429", "Injected failure; no API call.")),
        }
        self.callback.side_effect = lambda **kw: {
            "raw_response": canonical_bytes(self.judgments.judgment(statuses)),
            "provenance": {"kind": "synthetic"},
        }
        result = self.execute(self.prepare())
        vector = result["result"]["score_vector"]
        self.assertEqual(vector["P8"]["status"], "unverifiable")
        self.assertIsNone(vector["P8"]["score"])
        self.assertEqual(vector["P9"]["status"], "grader_error")
        capture = read_json(result["result"]["capture"]["path"])
        self.assertIsNone(capture["stdout"])
        self.assertIsNone(capture["returncode"])

    def test_malformed_unicode_deep_and_oversized_output_are_retained_as_failures(self):
        for key, raw in (
            ("malformed", b"{bad"),
            ("unicode", b"\xff"),
            ("deep", b"[" * 2000 + b"]" * 2000),
            ("oversized", b"x" * 2_000_001),
        ):
            with self.subTest(key=key):
                self.callback.side_effect = lambda raw=raw, **kw: {
                    "raw_response": raw,
                    "provenance": {"kind": "synthetic"},
                }
                prepared = self.prepare(key=key)
                result = self.execute(prepared, key=key)
                self.assertEqual(result["status"], "completed")
                self.assertEqual(result["result"]["outcome"], "failed")
                capture = read_json(
                    Path(self.payload(key=key)["output"]) / "adapter-result.json"
                )
                self.assertEqual(capture["raw"]["size"], len(raw))
                self.assertEqual(
                    capture["raw"]["sha256"], hashlib.sha256(raw).hexdigest()
                )
                if capture["raw"]["retained"]:
                    self.assertEqual(Path(capture["raw"]["path"]).read_bytes(), raw)
                else:
                    self.assertNotIn("path", capture["raw"])
                before = self.callback.call_count
                self.assertEqual(self.execute(prepared, key=key), result)
                self.assertEqual(self.callback.call_count, before)

    def test_timeout_and_nonzero_preserve_original_streams_without_retry(self):
        self.callback.side_effect = subprocess.TimeoutExpired(
            "fixture", 5, output=b"partial", stderr=b"deadline"
        )
        prepared = self.prepare()
        failed = self.execute(prepared)
        self.assertEqual(failed["status"], "execution-unknown")
        failure = read_json(failed["result"]["failure"]["path"])
        self.assertEqual(Path(failure["stderr"]["path"]).read_bytes(), b"deadline")
        self.assertEqual(self.execute(prepared), failed)
        self.assertEqual(self.callback.call_count, 1)

    def test_nonzero_reply_and_partial_stream_capture_cannot_be_saved_success(self):
        for key, code, stream in (
            ("nonzero", 7, b"error"),
            ("partial", 0, b"x" * 2_000_001),
        ):
            with self.subTest(key=key):
                self.callback.side_effect = lambda code=code, stream=stream, **kw: {
                    "raw_response": canonical_bytes(self.judgments.judgment()),
                    "provenance": {"kind": "synthetic"},
                    "stderr": stream,
                    "returncode": code,
                }
                result = self.execute(self.prepare(key=key), key=key)
                self.assertEqual(result["result"]["outcome"], "failed")
                capture = read_json(
                    Path(self.payload(key=key)["output"]) / "adapter-result.json"
                )
                self.assertEqual(capture["returncode"], code)
                self.assertEqual(capture["stderr"]["size"], len(stream))

    def test_role_request_and_current_plan_drift_reject_before_dispatch(self):
        prepared = self.prepare()
        with self.assertRaises(JournalError):
            self.prepare(self.controller("R2"))
        changed = copy.deepcopy(self.request)
        changed["bindings"]["plan_id"] = "another-plan"
        self.request_path.write_bytes(canonical_bytes(changed))
        with self.assertRaises(Stage3Error):
            self.execute(prepared)
        self.callback.assert_not_called()

    def test_pinned_capture_and_rehashed_raw_type_tampering_are_rejected(self):
        prepared = self.prepare()
        root = self.interrupt_after_record(prepared)
        raw = read_json(root / "judgment.raw")
        raw["criteria"][0]["score"] = True
        raw_bytes = canonical_bytes(raw)
        (root / "judgment.raw").write_bytes(raw_bytes)
        capture = read_json(root / "adapter-result.json")
        capture["raw"].update(
            size=len(raw_bytes), sha256=hashlib.sha256(raw_bytes).hexdigest()
        )
        (root / "adapter-result.json").write_bytes(canonical_bytes(capture))
        with self.assertRaisesRegex(Stage3Error, "source-aware replay"):
            self.jobs.recover(
                "grade",
                expected_request_sha256=prepared["request_sha256"],
                current_checkpoint=self.checkpoint,
                expected_record_sha256=_ref(root / "record.json")["sha256"],
            )
        self.assertEqual(self.callback.call_count, 1)

    def test_saved_record_recovery_and_capture_replay_never_invoke_judge(self):
        prepared = self.prepare()
        root = self.interrupt_after_record(prepared)
        recovered = self.jobs.recover(
            "grade",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=self.checkpoint,
            expected_record_sha256=_ref(root / "record.json")["sha256"],
        )
        self.assertEqual(recovered["result"]["outcome"], "saved")
        capture = read_json(root / "adapter-result.json")
        Path(capture["stdout"]["path"]).write_bytes(b"tampered prose")
        with self.assertRaises(Stage3Error):
            self.execute(prepared)
        self.assertEqual(self.callback.call_count, 1)

    def test_missing_campaign_dependency_is_explicit_and_never_dispatches(self):
        campaign = {
            "root": str(self.f.root / "campaign"),
            "sha256": "a" * 64,
            "unit_id": "one",
        }
        jobs = self.controller(campaign=campaign)
        real_import = importlib.import_module

        def missing(name, package=None):
            if name in (".campaign", ".campaign_records"):
                raise ModuleNotFoundError(
                    "fixture dependency absent", name="stage3_plan.campaign"
                )
            return real_import(name, package)

        with patch(
            "stage3_plan.evaluation_jobs.importlib.import_module", side_effect=missing
        ):
            with self.assertRaisesRegex(Stage3Error, "dependency is not installed"):
                self.prepare(jobs)
            with self.assertRaisesRegex(Stage3Error, "dependency is not installed"):
                save_campaign_index(
                    campaign["root"],
                    expected_campaign_sha256="a" * 64,
                    receipts=[],
                    output=self.f.root / "index.json",
                )
        self.callback.assert_not_called()

    def test_recovery_rejects_partial_capture_and_rehashed_boolean_exit(self):
        self.callback.side_effect = lambda **kw: {
            "raw_response": canonical_bytes(self.judgments.judgment()),
            "provenance": {"kind": "synthetic"},
            "returncode": 0,
            "stderr": b"x" * 2_000_001,
        }
        prepared = self.prepare()
        root = self.interrupt_after_record(prepared)
        record_evaluation(
            self.request_path,
            expected_request_sha256=self.request_ref["sha256"],
            judgment=root / "judgment.raw",
            expected_judgment_sha256=_ref(root / "judgment.raw")["sha256"],
            output=root / "record.json",
        )
        capture = read_json(root / "adapter-result.json")
        for code, stderr in ((0, capture["stderr"]), (False, None)):
            capture.update(returncode=code, stderr=stderr)
            (root / "adapter-result.json").write_bytes(canonical_bytes(capture))
            with self.assertRaises(Stage3Error):
                self.jobs.recover(
                    "grade",
                    expected_request_sha256=prepared["request_sha256"],
                    current_checkpoint=self.checkpoint,
                    expected_record_sha256=_ref(root / "record.json")["sha256"],
                )
        self.assertEqual(self.callback.call_count, 1)

    def test_host_reference_journal_id_and_original_brief_id_stay_separate(self):
        self.f.intake["input_origin"] = {"project_ref": "host-alias"}
        current = self.f.workflow("aliased-source")
        jobs = PlanningJobs(
            self.f.journal,
            "project-a",
            self.f.owner,
            self.f.root / "jobs",
            project_ref="host-alias",
        )
        prepared = jobs.prepare(
            "aliased-plan",
            checkpoint=current,
            configuration=self.f.config,
            adapter_context=self.f.context,
            plan_id=self.f.plan["plan_id"],
            expected_revision=self.f.journal.snapshot("project-a")["revision"],
        )
        result = jobs.run(
            "aliased-plan",
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=current,
            callback=self.f.callback,
        )
        self.assertEqual(result["result"]["outcome"], "saved")
        payload = self.f.journal.snapshot("project-a")["intents"][
            jobs._key("aliased-plan")
        ]["payload"]
        self.assertEqual(
            (
                payload["project_ref"],
                payload["project_id"],
                payload["brief_project_id"],
            ),
            ("host-alias", "project-a", "original-brief"),
        )
        path = self.f.root / "alias-evaluation.json"
        prepare_evaluation(
            result["result"]["plan"]["package"],
            expected_manifest_sha256=result["result"]["plan"]["manifest_sha256"],
            output=path,
        )
        self.judgments.request_path = path
        evaluation = EvaluationJobs(
            self.f.journal,
            "project-a",
            self.f.owner,
            self.f.root / "jobs",
            request=_ref(path),
            role="R1",
            project_ref="host-alias",
        )
        kwargs = dict(
            checkpoint=result["result"]["checkpoint"],
            configuration=self.config,
            adapter_context=self.context,
            expected_revision=self.f.journal.snapshot("project-a")["revision"],
        )
        grade = evaluation.prepare("alias-grade", **kwargs)
        graded = evaluation.run(
            "alias-grade",
            expected_request_sha256=grade["request_sha256"],
            current_checkpoint=result["result"]["checkpoint"],
            callback=self.callback,
        )
        self.assertEqual(graded["result"]["outcome"], "saved")
