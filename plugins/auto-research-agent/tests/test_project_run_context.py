"""Actual intake/ledger/package companion flow; authored offline sources only."""

from copy import deepcopy
import json
import os
from pathlib import Path
import shutil
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent))
sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))

import test_project_stage1_delivery as delivery_fixture
import test_stage1_deliverable as source_fixture
from research_workspace_native import project_run_context as context
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import (
    DeliverableError,
    read_json,
    sha,
    write_json,
)


class ProjectRunContextTests(unittest.TestCase):
    setUpClass = classmethod(
        delivery_fixture.ProjectStage1DeliveryTests.setUpClass.__func__
    )
    setUp = delivery_fixture.ProjectStage1DeliveryTests.setUp
    reopen = delivery_fixture.ProjectStage1DeliveryTests.reopen
    saved = delivery_fixture.ProjectStage1DeliveryTests.saved
    register = delivery_fixture.ProjectStage1DeliveryTests.register
    body = delivery_fixture.ProjectStage1DeliveryTests.body

    def authored(
        self, key="aircraft", topic="Aircraft diagnosis with sensor drift", budget=2
    ):
        title = "Authored " + topic
        content = (
            "<html><head><title>"
            + title
            + "</title></head><body><article><h1>"
            + title
            + "</h1><h2>Introduction</h2><p>"
            + (topic + ": measured signals and independent validation. ") * 14
            + "</p><h2>Results</h2><p>"
            + (
                topic
                + ": this authored local example cannot prove scientific adequacy. "
            )
            * 8
            + "</p></article></body></html>"
        ).encode()
        original_make = source_fixture.ResearchDeliverableTests.make_records
        original_submit = delivery_fixture.submit_body

        def make_records(owner):
            return original_make(owner, raw=content, title=title)

        def submit(view):
            body = original_submit(view)
            body["budgets"].update(seconds=budget * 10, search_calls=budget, rounds=1)
            return body

        with (
            patch.object(source_fixture, "TITLE", title),
            patch.object(
                source_fixture.ResearchDeliverableTests, "make_records", make_records
            ),
            patch.object(delivery_fixture, "submit_body", submit),
        ):
            fixture = self.saved(key=key, topic=topic)
        offer = self.register(fixture)
        fixture["body"] = self.body(fixture, offer)
        return fixture

    def produce(self, fixture):
        result = self.delivery.deliver("alice-token", fixture["ref"], fixture["body"])
        self.assertEqual(result["status"], "saved")
        binding = self.delivery.binding(fixture["ref"])
        canonical_root = Path(binding["deliverable_dir"])
        root = canonical_root.with_name(canonical_root.name + "-context")
        return result, root

    def test_two_distinct_inputs_follow_real_controller_package_context_and_relocation(
        self,
    ):
        reports, source_hashes, resources, plans, needs = [], [], [], [], []
        for key, topic, budget in (
            ("aircraft", "Aircraft diagnosis with sensor drift", 2),
            ("music", "Polyphonic music transcription from sparse annotations", 3),
        ):
            with self.subTest(topic=topic):
                fixture = self.authored(key, topic, budget)
                result, root = self.produce(fixture)
                digest = result["run_context"]["manifest_sha256"]
                report = context.validate_run_context(root, digest)
                reports.append(report)
                archive = read_json(root / "resource-history.json")
                resources.append(archive["view"]["declared"])
                plans.append((root / "plan/query_plan.jsonl").read_bytes())
                needs.append(read_json(root / "brief.json")["needs"])
                source_hashes.append(fixture["receipt"]["raw_sha256"])
                self.assertEqual(report["counts"]["works"], 1)
                self.assertFalse(report["runtime_attested"])
                self.assertIsNone(archive["view"]["actual_seconds"])
                self.assertTrue(
                    any(
                        row["kind"] == "stage1-deliver-intent"
                        for row in archive["events"]
                    )
                )
                self.assertFalse(
                    any(
                        row["kind"] == "stage1-deliver-saved"
                        for row in archive["events"]
                    )
                )
                self.assertFalse(result["stage1_complete"])
                self.assertEqual(
                    self.delivery.read("alice-token", fixture["ref"])[
                        "run_context_status"
                    ],
                    "bound-context",
                )
                relocated = delivery_fixture._io_root(
                    self.root / ("Receiving 空白 " + key)
                )
                shutil.copytree(root, relocated)
                source_project = self.intake._path(fixture["ref"], "marker").parent
                archived = source_project.with_name(
                    source_project.name + "-unavailable"
                )
                source_project.rename(archived)
                try:
                    self.assertEqual(
                        context.validate_run_context(relocated, digest), report
                    )
                    if os.name == "nt":
                        ordinary = Path(str(relocated).removeprefix("\\\\?\\"))
                        self.assertEqual(
                            context.validate_run_context(ordinary, digest), report
                        )
                finally:
                    archived.rename(source_project)
        self.assertNotEqual(reports[0]["binding"], reports[1]["binding"])
        self.assertNotEqual(source_hashes[0], source_hashes[1])
        self.assertNotEqual(resources[0], resources[1])
        self.assertNotEqual(plans[0], plans[1])
        self.assertNotEqual(needs[0], needs[1])
        self.runner.assert_not_called()

    def test_same_key_reopen_replays_exact_context_without_current_capture(self):
        fixture = self.authored()
        result, root = self.produce(fixture)
        before = context._tree(root)
        self.reopen()
        with patch.object(
            context, "build_run_context", side_effect=AssertionError("recaptured")
        ):
            replay = self.delivery.deliver(
                "alice-token", fixture["ref"], fixture["body"]
            )
        self.assertTrue(replay["replayed"])
        self.assertEqual(replay["run_context"], result["run_context"])
        self.assertEqual(context._tree(root), before)
        changed = deepcopy(fixture["body"])
        changed["offer_sha256"] = "0" * 64
        with self.assertRaises(SessionApiError):
            self.delivery.deliver("alice-token", fixture["ref"], changed)

    def test_companion_failure_preserves_unknown_partial_package_and_no_retry(self):
        fixture = self.authored()
        published = []

        def files(root):
            return {
                path.relative_to(root).as_posix(): sha(path.read_bytes())
                for path in root.rglob("*")
                if path.is_file()
            }

        def fail_companion(_, project_ref, artifact, output, source_context):
            published.append((Path(output), files(Path(output))))
            raise ValueError("context source absent")

        with patch.object(context, "build_run_context", side_effect=fail_companion):
            with self.assertRaises(SessionApiError) as raised:
                self.delivery.deliver("alice-token", fixture["ref"], fixture["body"])
        failure = raised.exception.receipt
        self.assertEqual(failure["status"], "execution-unknown")
        self.assertEqual(failure["failure_phase"], "publication-outcome-unobserved")
        self.assertEqual(failure["error"], "context source absent")
        self.assertEqual(len(published), 1)
        root, original_files = published[0]
        self.assertIn("provenance_manifest.json", original_files)
        self.assertIn("records.original.json", original_files)
        self.assertIsNone(
            self.intake._load("alice", fixture["ref"]).get("stage1_canonical_package")
        )
        before_paths = sorted(path.name for path in root.parent.iterdir())
        self.reopen()
        history = self.intake.history("alice-token", fixture["ref"])
        with (
            patch.object(
                context, "build_run_context", side_effect=AssertionError("recaptured")
            ) as companion,
            patch(
                "research_workspace_native.project_stage1_delivery.package.build",
                side_effect=AssertionError("rebuilt"),
            ) as builder,
        ):
            replay = self.delivery.deliver(
                "alice-token", fixture["ref"], fixture["body"]
            )
            self.assertEqual(replay, dict(failure, replayed=True))
            changed = dict(
                fixture["body"],
                key=fixture["body"]["key"] + "-new",
                revision=self.intake.read("alice-token", fixture["ref"])["revision"],
            )
            with self.assertRaisesRegex(
                SessionApiError, "stage1-coverage-write-outcome-unobserved"
            ):
                self.delivery.deliver("alice-token", fixture["ref"], changed)
            companion.assert_not_called()
            builder.assert_not_called()
        self.assertEqual(self.intake.history("alice-token", fixture["ref"]), history)
        self.assertEqual(files(root), original_files)
        self.assertEqual(
            sorted(path.name for path in root.parent.iterdir()), before_paths
        )
        self.assertIsNone(
            self.intake._load("alice", fixture["ref"]).get("stage1_canonical_package")
        )
        self.runner.assert_not_called()

    def test_cas_rejects_source_drift_after_copy(self):
        fixture = self.authored()
        original = context.validate_run_context

        def drift(root, digest):
            report = original(root, digest)
            path = fixture["ledger"].root / "coverage_and_stop.md"
            path.write_bytes(path.read_bytes() + b"\nchanged during capture\n")
            return report

        with patch.object(context, "validate_run_context", drift):
            with self.assertRaises(SessionApiError):
                self.delivery.deliver("alice-token", fixture["ref"], fixture["body"])
        state = self.intake._load("alice", fixture["ref"])
        self.assertIsNone(state.get("stage1_canonical_package"))
        self.assertTrue(
            any(
                path.name.endswith("-context")
                for path in self.intake._path(fixture["ref"], "marker").parent.iterdir()
            )
        )

    def test_external_hash_extra_files_and_cross_project_context_reject(self):
        first = self.authored()
        result, root = self.produce(first)
        digest = result["run_context"]["manifest_sha256"]
        with self.assertRaises(DeliverableError):
            context.validate_run_context(root, "0" * 64)
        (root / "unrecognized.txt").write_bytes(b"unexpected")
        with self.assertRaises(DeliverableError):
            context.validate_run_context(root, digest)
        view = self.delivery.read("alice-token", first["ref"])
        self.assertEqual(view["canonical_package"]["status"], "source-binding-failed")
        self.assertEqual(view["run_context_status"], "unavailable-or-stale")
        (root / "unrecognized.txt").unlink()
        second = self.authored("music", "Polyphonic music transcription", 3)
        result2, root2 = self.produce(second)
        binding = self.delivery.binding(first["ref"])
        changed = deepcopy(binding)
        changed["run_context"] = result2["run_context"]
        with self.assertRaises(DeliverableError):
            context.check_saved_context(Path(binding["deliverable_dir"]), changed)
        original = (root / "brief.json").read_bytes()
        (root / "brief.json").write_bytes((root2 / "brief.json").read_bytes())
        manifest = read_json(root / context.MANIFEST)
        manifest["files"]["brief.json"] = dict(
            bytes=(root / "brief.json").stat().st_size,
            sha256=sha((root / "brief.json").read_bytes()),
        )
        write_json(root / context.MANIFEST, manifest)
        with self.assertRaises(DeliverableError):
            context.validate_run_context(
                root, sha((root / context.MANIFEST).read_bytes())
            )
        self.assertNotEqual(original, (root / "brief.json").read_bytes())

    def test_hardlinked_and_linked_artifacts_reject_before_read(self):
        source = self.root / "linked"
        source.mkdir()
        (source / "one").write_bytes(b"original")
        os.link(source / "one", source / "two")
        with self.assertRaisesRegex(DeliverableError, "unlinked"):
            context._tree(source)

    def test_legacy_artifact_is_explicit_and_never_silently_upgraded(self):
        self.assertEqual(
            context.check_saved_context(self.root / "old", {}), "legacy-no-run-context"
        )
        with self.assertRaises(DeliverableError):
            context.check_saved_context(self.root / "new", {"run_context": None})

    def test_hashed_snapshot_is_not_reopened_as_a_different_manifest(self):
        fixture = self.authored()
        result, root = self.produce(fixture)
        path = root / context.MANIFEST
        original = path.read_bytes()
        replacements = []

        def swapped_read(target):
            if Path(target) == path:
                forged = json.loads(original)
                forged["binding"]["artifact_ref"] = "stage1-canonical-forged"
                target.write_bytes(context.canonical(forged) + b"\n")
                replacements.append(True)
                try:
                    return read_json(target)
                finally:
                    target.write_bytes(original)
            return read_json(target)

        # The old reader re-opened this file after hashing it. Inject an actual
        # file replacement at that exact boundary, not a fake returned object.
        with patch.object(context, "read_json", swapped_read, create=True):
            report = context.validate_run_context(
                root, result["run_context"]["manifest_sha256"]
            )
        self.assertEqual(report["binding"]["artifact_ref"], result["artifact_ref"])
        self.assertEqual(replacements, [])
        self.assertEqual(path.read_bytes(), original)


if __name__ == "__main__":
    unittest.main()
