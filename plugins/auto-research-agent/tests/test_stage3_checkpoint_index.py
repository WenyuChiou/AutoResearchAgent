"""Native saved jobs and workflow records through the private checkpoint index."""

from contextlib import closing
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import sqlite3
import subprocess
import sys
import unittest
from unittest.mock import patch

PLUGIN = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(PLUGIN.parents[1] / "harness-ui"), str(PLUGIN / "cli")]

from research_workspace_native.project_stage3_http import ProjectStage3Http  # noqa: E402
from research_workspace_native.session_api import SessionApiError  # noqa: E402
from stage3_checkpoint_index import Stage3CheckpointIndex  # noqa: E402
from stage3_plan.contracts import Stage3Error, canonical_bytes, digest  # noqa: E402
from stage3_plan.decision import record_plan_decision  # noqa: E402
from stage3_plan.storage import inspect_completed_package  # noqa: E402
from stage3_plan.workflow import advance_workflow  # noqa: E402
from stage3_plan_review_readback import plan_review_identity, read_plan_review  # noqa: E402
import test_project_stage3_planning as host_fixture  # noqa: E402
import test_saved_source_admission_integration as source_fixture  # noqa: E402
from test_research_brief import brief  # noqa: E402
from test_stage3_plan_decision import semantic_review  # noqa: E402


def engineering_brief(_status):
    value = brief("specified", "United States")
    value["original_description"] = (
        "How does population aging relate to the composition of household "
        "expenditure in the United States? Engineering-only BLS CE example."
    )
    value["decisions"][0].update(
        actor="engineering-fixture",
        source_ref="fixture:stage3-checkpoint-index",
    )
    return value


def ref(path):
    return {"path": str(path), "sha256": sha256(path.read_bytes()).hexdigest()}


class Stage3CheckpointIndexTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = host_fixture.ProjectStage3PlanningTests
        cls.addClassCleanup(cls.fixture.doClassCleanups)
        with patch.object(source_fixture, "brief", engineering_brief):
            cls.fixture.setUpClass()

    def setUp(self):
        ctx = self.fixture("test_save_only_prepares_real_checkpoint_without_dispatch")
        self.addCleanup(ctx.doCleanups)
        ctx.setUp()
        # The intake fixture allows only the product's own non-network Git guard.
        original = self.original_popen
        probes = []

        def git_only(argv, *args, **kwargs):
            if argv[:2] != ["git", "-C"] or argv[3:] != [
                "rev-parse",
                "--show-toplevel",
            ]:
                raise AssertionError("unexpected subprocess during planning index test")
            probes.append(True)
            return original(argv, *args, **kwargs)

        ctx.process.side_effect = git_only
        ctx._cleanups = [
            item for item in ctx._cleanups if item[0] != ctx.process.assert_not_called
        ]
        self.ctx = ctx
        self.root = ctx.f.root
        self.addCleanup(lambda: self.assertEqual(ctx.process.call_count, len(probes)))
        self.index = Stage3CheckpointIndex(
            self.root / "history.sqlite", archive_root=self.root
        )
        self.http = ProjectStage3Http(ctx.bridge)
        self.addCleanup(self.http.close)

    original_popen = staticmethod(subprocess.Popen)

    def native_receipt(self, key, saved_plan_sha):
        ctx = self.ctx
        archived = ctx.jobs.journal.snapshot(ctx.jobs.project_id)["intents"][
            ctx.jobs._key(key)
        ]["payload"]
        return ctx.jobs.inspect_saved(
            key,
            expected_request_sha256=digest(archived),
            current_checkpoint=archived["checkpoint"],
            expected_plan_manifest_sha256=saved_plan_sha,
        )

    def test_native_archives_rebuild_exact_current_and_historical_entries(self):
        ctx, project = self.ctx, self.ctx.f.ref
        initial = self.http.view("own", project)
        self.assertIsNone(self.index.lookup(plan_review_identity(initial)))
        self.assertFalse(self.index.database.exists())
        ctx.key = initial["default_request"]["key"]
        ctx.plan = host_fixture.authored_plan(
            ctx.admitted,
            ctx.selection["planning_manifest_sha256"],
            "host-plan-" + digest(ctx.key),
        )
        ctx.callback.return_value["raw_response"] = canonical_bytes(ctx.plan)
        output = ctx.bridge.run("own", project, dict(ctx.prepared(), confirmed=True))
        old_view = self.http.view("own", project)
        job1 = self.native_receipt(ctx.key, output["plan_manifest_sha256"])
        old_id = plan_review_identity(old_view)
        self.assertIsNone(self.index.lookup(old_id))
        self.assertFalse(self.index.database.exists())
        root_ref = self.index.publish(old_view, job1)["checkpoint"]
        self.assertEqual(root_ref, job1["result"]["checkpoint"])
        no_review = read_plan_review(
            old_view, trusted_binding=self.index.lookup(old_id)
        )
        self.assertEqual(no_review["readback_status"], "bound")
        self.assertIsNone(no_review["review"])
        self.assertIsNone(no_review["decision"])

        review = self.root / "fixture-review.json"
        review.write_bytes(
            canonical_bytes(
                semantic_review(
                    ctx.plan, ctx.admitted, status="unknown", kind="synthetic"
                )
            )
        )
        review_ref = ref(review)

        def reviewed_from(path):
            saved = advance_workflow(
                root_ref["path"],
                expected_checkpoint_sha256=root_ref["sha256"],
                action="attach-review",
                output=path,
                binding=review_ref,
            )
            return {"path": str(path), "sha256": saved["checkpoint_sha256"]}

        tip = reviewed_from(self.root / "review-checkpoint.json")
        # Create an independently valid sibling by attaching a different review.
        branch = self.root / "fixture-other-review.json"
        alternative = semantic_review(
            ctx.plan, ctx.admitted, status="unknown", kind="synthetic"
        )
        alternative["findings"][0]["reason"] = "Another synthetic archived review."
        branch.write_bytes(canonical_bytes(alternative))
        sibling_path = self.root / "other-checkpoint.json"
        sibling = advance_workflow(
            root_ref["path"],
            expected_checkpoint_sha256=root_ref["sha256"],
            action="attach-review",
            output=sibling_path,
            binding=ref(branch),
        )
        self.index.publish(old_view, job1, checkpoint=tip)
        review_without_decision = read_plan_review(
            old_view, trusted_binding=self.index.lookup(old_id)
        )
        self.assertEqual(
            review_without_decision["review"]["sha256"], review_ref["sha256"]
        )
        self.assertIsNone(review_without_decision["decision"])

        source = ctx.item()["payload"]["source"]
        words = "Engineering fixture defers the saved first plan version."
        native = self.root / "synthetic-message.jsonl"
        native.write_bytes(
            canonical_bytes(
                {
                    "type": "event_msg",
                    "payload": {"type": "user_message", "message": words},
                }
            )
        )
        decision_root = self.root / "fixture-decision"
        record_plan_decision(
            job1["result"]["plan"]["package"],
            expected_manifest_sha256=output["plan_manifest_sha256"],
            review_path=review,
            expected_review_sha256=review_ref["sha256"],
            native_message=native,
            message_index=0,
            user_text=words,
            decision="defer",
            output_dir=decision_root,
            planning_package=source["package"],
            delivery_dir=source["delivery"],
            expected_source_manifest_sha256=source["manifest_sha256"],
        )
        decision = ref(decision_root / "decision.json")
        old_binding = self.index.publish(
            old_view, job1, checkpoint=tip, decision=decision
        )
        self.assertEqual(
            self.index.publish(old_view, job1, checkpoint=tip), old_binding
        )
        rejects = {}
        for label, checkpoint in (
            ("rollback", root_ref),
            (
                "sibling",
                {"path": str(sibling_path), "sha256": sibling["checkpoint_sha256"]},
            ),
        ):
            with self.assertRaisesRegex(Stage3Error, "rollback or fork") as error:
                self.index.publish(old_view, job1, checkpoint=checkpoint)
            rejects[label] = str(error.exception)

        next_plan = dict(deepcopy(ctx.plan), version=2)
        key2 = "fixture-native-version-2"
        prepared = ctx.jobs.prepare(
            key2,
            checkpoint=tip,
            configuration=ctx.binding["configuration"],
            adapter_context=ctx.callback.request_context,
            plan_id=next_plan["plan_id"],
            version=2,
            schema_version=next_plan["schema_version"],
            expected_revision=ctx.journal.snapshot(ctx.jobs.project_id)["revision"],
        )
        ctx.callback.return_value["raw_response"] = canonical_bytes(next_plan)
        result2 = ctx.jobs.run(
            key2,
            expected_request_sha256=prepared["request_sha256"],
            current_checkpoint=tip,
            callback=ctx.callback,
        )
        job2 = self.native_receipt(key2, result2["result"]["plan"]["manifest_sha256"])
        plan2 = job2["result"]["plan"]
        native_plan2 = inspect_completed_package(
            plan2["package"], plan2["manifest_sha256"]
        )["artifacts"]["plan.json"]
        current_view = dict(
            ctx.bridge.read("own", project),
            job=ctx.bridge._public(project, job2),
            plan=native_plan2,
        )
        new_id = plan_review_identity(current_view)
        new_binding = self.index.publish(current_view, job2)
        self.assertEqual(current_view["plan"]["version"], 2)
        self.assertEqual(current_view["plan"]["plan_id"], old_view["plan"]["plan_id"])

        wrong = deepcopy(current_view)
        wrong["project_ref"] = wrong["job"]["project_ref"] = "project-unrelated"
        self.assertIsNone(self.index.lookup(plan_review_identity(wrong)))
        with self.assertRaisesRegex(
            Stage3Error, "archived selection does not bind"
        ) as error:
            self.index.publish(wrong, job2)
        rejects["foreign_index"] = str(error.exception)
        with self.assertRaises(SessionApiError) as error:
            self.http.view("own", wrong["project_ref"])
        rejects["foreign_http"] = dict(
            status=error.exception.status, code=str(error.exception)
        )
        self.assertEqual(rejects["foreign_http"]["status"], 404)
        stale = dict(current_view, input_version="stale-fixture")
        self.assertIsNone(self.index.lookup(plan_review_identity(stale)))
        with self.assertRaisesRegex(Stage3Error, "archived selection does not bind"):
            self.index.publish(stale, job2)
        with self.assertRaisesRegex(Stage3Error, "pinned job"):
            self.index.publish(current_view, job1)
        with self.assertRaisesRegex(Stage3Error, "requires the displayed plan"):
            self.index.publish(current_view, dict(job2, inspection_scope=None))
        with self.assertRaisesRegex(Stage3Error, "saved planning job"):
            self.index.publish(current_view, job2, checkpoint=tip)
        with self.assertRaisesRegex(Stage3Error, "outside the Host archive"):
            self.index.publish(
                current_view,
                job2,
                checkpoint={
                    "path": str(self.root.parent / "unused.json"),
                    "sha256": "0" * 64,
                },
            )

        # The older publisher observes no row, then another native attachment
        # wins the transaction. The stale write may not replace it.
        raced = Stage3CheckpointIndex(
            self.root / "raced.sqlite", archive_root=self.root
        )

        def validated_after_competitor(view, *, trusted_binding):
            with patch("stage3_checkpoint_index.read_plan_review", read_plan_review):
                raced.publish(old_view, job1, checkpoint=tip, decision=decision)
            return read_plan_review(view, trusted_binding=trusted_binding)

        with (
            patch(
                "stage3_checkpoint_index.read_plan_review", validated_after_competitor
            ),
            self.assertRaisesRegex(Stage3Error, "changed during publication") as error,
        ):
            raced.publish(old_view, job1)
        rejects["concurrent_stale_writer"] = str(error.exception)
        self.assertEqual(raced.lookup(old_id), old_binding)

        # A first writer can stop after SQLite creates its file, or while
        # its first schema is invisible to a simultaneous read-only lookup.
        rebuilt = Stage3CheckpointIndex(
            self.root / "rebuilt.sqlite", archive_root=self.root
        )
        rebuilt.database.touch()
        self.assertIsNone(rebuilt.lookup(old_id))
        with closing(sqlite3.connect(rebuilt.database)) as writer:
            writer.execute("BEGIN IMMEDIATE")
            writer.execute(
                "CREATE TABLE stage3_checkpoint_bindings_v1 ("
                "identity BLOB PRIMARY KEY, checkpoint BLOB NOT NULL, decision BLOB)"
            )
            self.assertIsNone(rebuilt.lookup(old_id))
            writer.rollback()
        self.assertIsNone(rebuilt.lookup(old_id))
        foreign_store = Stage3CheckpointIndex(
            self.root / "foreign.sqlite", archive_root=self.root
        )
        with closing(sqlite3.connect(foreign_store.database)) as writer, writer:
            writer.execute("CREATE TABLE unrelated(id INTEGER)")
        unrelated_before = ref(foreign_store.database)
        with self.assertRaisesRegex(Stage3Error, "unexpected checkpoint index schema"):
            foreign_store.publish(old_view, job1)
        self.assertEqual(ref(foreign_store.database), unrelated_before)
        # Rebuild from native receipts after the initial transaction is rolled back.
        self.assertEqual(
            rebuilt.publish(old_view, job1, checkpoint=tip, decision=decision),
            old_binding,
        )
        self.assertEqual(rebuilt.publish(current_view, job2), new_binding)
        self.assertIsNone(rebuilt.lookup(plan_review_identity(wrong)))

        originals = [
            self.index.database,
            rebuilt.database,
            raced.database,
            review,
            native,
            Path(tip["path"]),
            Path(job2["result"]["checkpoint"]["path"]),
            *decision_root.iterdir(),
            *(Path(job1["result"]["plan"]["package"]).glob("*")),
            *(Path(plan2["package"]).glob("*")),
        ]
        before = {str(p): ref(p)["sha256"] for p in originals}
        reopened = Stage3CheckpointIndex(self.index.database, archive_root=self.root)
        historical = read_plan_review(old_view, trusted_binding=reopened.lookup(old_id))
        current = read_plan_review(
            current_view, trusted_binding=reopened.lookup(new_id)
        )
        self.assertEqual(
            historical["decision"]["status"],
            "decision-recorded-pending-host-verification",
        )
        self.assertFalse(historical["decision"]["identity_authenticated"])
        self.assertIsNone(current["review"])
        self.assertIsNone(current["decision"])
        self.assertFalse(current["execution_authorized"])
        self.assertFalse(historical["execution_authorized"])
        self.assertEqual(before, {str(p): ref(p)["sha256"] for p in originals})
        self.assertEqual(ctx.callback.call_count, 2)
        ctx.native.assert_not_called()

        self.reopen_contract = {
            "archive_root": str(self.root),
            "database": str(self.index.database),
            "source_brief": ctx.admitted["brief"]["original_description"],
            "source_scope": ctx.admitted["brief"]["decisions"],
            "views": {"current": current_view, "historical": old_view},
            "result": {"current": current, "historical": historical},
            "originals": before,
            "rejects": rejects,
            "recorded_checkpoints": {
                "initial": root_ref,
                "review": tip,
                "next": job2["result"]["checkpoint"],
            },
            "initialization_recovery": {
                "empty_database": "no binding",
                "first_uncommitted_schema": "no binding",
                "first_rolled_back_schema": "rebuilt from original receipts",
                "unrelated_sqlite": "refused and unchanged",
            },
            "fixtures": {
                "fixed_plan_callbacks": ctx.callback.call_count,
                "native_planner_calls": ctx.native.call_count,
            },
        }
