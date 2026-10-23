"""Saved package reviews extend the real SQLite inbox without research I/O."""

from concurrent.futures import ThreadPoolExecutor
from contextlib import redirect_stdout
from copy import deepcopy
from io import StringIO
import json
from pathlib import Path
import sqlite3
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parents[1] / "cli"))
from stage1_deliverable.common import canonical, sha
from research_workspace_native.maintenance_inbox import (
    MaintenanceInbox,
    MaintenanceInboxError,
)
from research_workspace_native.saved_review import SavedReviewService, SCHEMA, main


class SavedPackageReviewTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.root = Path(self.temp.name).resolve()
        self.package = self.root / "Saved package with spaces"
        self.package.mkdir()
        self.original_text = "原始来源\n同一句。\n同一句。\n" + "完整正文。" * 1000
        files = {
            "index": b'{"schema":"fixture-index"}',
            "manifest": b'{"schema_version":"1.0.0","project_id":"project-a"}',
            "view": b'{"works":["paper-a","paper-b"]}',
            "source-a": self.original_text.encode(),
            "source-b": b"Different work and original version.",
        }
        artifacts = {}
        for name, raw in files.items():
            path = self.package / (name + ".txt")
            path.write_bytes(raw)
            artifacts[name] = dict(
                path=path.name, sha256=sha(raw), bytes=len(raw), kind="utf8-text"
            )
        self.registration = dict(
            schema_version=SCHEMA,
            case_ref="case-a",
            project_id="project-a",
            input_version=None,
            run_id=None,
            artifacts=artifacts,
            pins=dict(
                index="index",
                manifest="manifest",
                view="view",
                brief=None,
                ledger=None,
                run_manifest=None,
            ),
            works=[
                dict(work_ref="paper-a", version_id="v1", source_refs=["source-a"]),
                dict(work_ref="paper-b", version_id="v2", source_refs=["source-b"]),
            ],
            unknowns={
                name: "Original evidence not located in this bounded fixture."
                for name in (
                    "input_version",
                    "run_id",
                    "brief",
                    "ledger",
                    "run_manifest",
                )
            },
        )
        self.registration_path = self.root / "registration.json"
        self.registration_path.write_bytes(canonical(self.registration))
        self.registration_sha = sha(self.registration_path.read_bytes())
        self.bindings = {
            "case-a": dict(
                project_id="project-a",
                index_sha256=sha(files["index"]),
                manifest_sha256=sha(files["manifest"]),
            )
        }
        self.db = self.root / "maintenance.sqlite3"
        self.inbox = MaintenanceInbox(self.db, self.bindings)
        self.service = self.build(self.inbox)
        self.target = dict(work_ref="paper-a", version_id="v1", source_ref="source-a")

    def build(self, inbox):
        return SavedReviewService(
            inbox,
            package_root=self.package,
            registration_path=self.registration_path,
            registration_sha256=self.registration_sha,
        )

    def tearDown(self):
        self.inbox.close()
        self.temp.cleanup()

    def input_registration(self, value, label):
        registration = deepcopy(self.registration)
        registration["input_version"] = value
        del registration["unknowns"]["input_version"]
        path = self.root / (label + ".json")
        path.write_bytes(canonical(registration))
        inbox = MaintenanceInbox(self.root / (label + ".sqlite3"), self.bindings)
        try:
            service = SavedReviewService(
                inbox,
                package_root=self.package,
                registration_path=path,
                registration_sha256=sha(path.read_bytes()),
            )
        except BaseException:
            inbox.close()
            raise
        return inbox, service

    def test_original_string_and_integer_input_versions_round_trip_without_coercion(
        self,
    ):
        for number, version in enumerate(("20261009-A03", 1, 0, "1", "  A03  ")):
            with self.subTest(version=version):
                inbox, service = self.input_registration(version, f"known-{number}")
                try:
                    body = dict(
                        key="review",
                        offer=service.offer(
                            "reviewer-a", service.ref, "submit-review", self.target
                        ),
                        decision="pending",
                        message="Original input version retained.",
                        confirmed=True,
                    )
                    offered = body["offer"]["context"]["input_version"]
                    self.assertEqual(offered, version)
                    self.assertIs(type(offered), type(version))
                    wrong = deepcopy(body)
                    wrong["offer"]["context"]["input_version"] = (
                        str(version) if type(version) is int else 1
                    )
                    with self.assertRaises(MaintenanceInboxError):
                        service.submit_review("reviewer-a", service.ref, wrong)
                    receipt = service.submit_review("reviewer-a", service.ref, body)
                    inbox.close()
                    inbox = MaintenanceInbox(
                        self.root / f"known-{number}.sqlite3", self.bindings
                    )
                    service = SavedReviewService(
                        inbox,
                        package_root=self.package,
                        registration_path=self.root / f"known-{number}.json",
                        registration_sha256=service.registration_sha256,
                        allow_register=False,
                    )
                    self.assertEqual(service.history(service.ref), [receipt])
                    saved = service.action(service.ref, "review")["context"][
                        "input_version"
                    ]
                    self.assertEqual(saved, version)
                    self.assertIs(type(saved), type(version))
                finally:
                    inbox.close()

    def test_invalid_original_input_versions_refuse_registration(self):
        for number, version in enumerate(
            ("", " \n", True, False, -1, 1.0, "x" * 257, "版" * 86)
        ):
            with (
                self.subTest(version=version),
                self.assertRaisesRegex(
                    MaintenanceInboxError, "invalid-original-input-version"
                ),
            ):
                self.input_registration(version, f"invalid-{number}")

    def request(self, operation="submit-review", *, key="one", target=True):
        return dict(
            key=key,
            offer=self.service.offer(
                "reviewer-a",
                self.service.ref,
                operation,
                self.target if target else None,
            ),
            decision="pending" if operation == "submit-review" else None,
            message="  保留原始意见。\n请补充这篇的来源。  ",
            confirmed=True,
        )

    def test_review_fix_handoff_are_durable_original_text_without_active_project(self):
        before = {p.name: p.read_bytes() for p in self.package.iterdir()}
        with (
            patch("subprocess.Popen", side_effect=AssertionError("no process")),
            patch("subprocess.run", side_effect=AssertionError("no process")),
            patch("socket.create_connection", side_effect=AssertionError("no network")),
        ):
            body = self.request()
            review = self.service.submit_review("reviewer-a", self.service.ref, body)
            fix = self.service.request_fix(
                "reviewer-a", self.service.ref, self.request("request-fix", key="fix")
            )
            handoff = self.service.request_handoff(
                "reviewer-a",
                self.service.ref,
                self.request("request-handoff", key="handoff", target=False),
            )
            self.assertEqual(
                [row["review_revision"] for row in (review, fix, handoff)], [1, 2, 3]
            )
            self.assertEqual(review["message"], body["message"])
            self.assertEqual(
                review["target"]["source_sha256"], sha(self.original_text.encode())
            )
            self.assertIsNone(handoff["context"]["active_project_ref"])
            self.assertIsNone(handoff["context"]["original_run_id"])
            self.assertFalse(handoff["context"]["core_acceptance"])
            self.assertFalse(handoff["context"]["execution_authorized"])
            self.assertFalse(handoff["context"]["stage1_complete"])
            self.assertEqual(handoff["status"], "recorded-not-dispatched")
            self.inbox.close()
            self.inbox = MaintenanceInbox(self.db, self.bindings)
            self.service = self.build(self.inbox)
            changes = self.inbox.db.total_changes
            self.assertEqual(
                self.service.history(self.service.ref), [review, fix, handoff]
            )
            self.assertEqual(self.service.action(self.service.ref, "handoff"), handoff)
            self.assertEqual(self.inbox.db.total_changes, changes)
        self.assertEqual(
            {p.name: p.read_bytes() for p in self.package.iterdir()}, before
        )
        self.assertNotIn(str(self.root), json.dumps(handoff))
        # Actions really use the existing feedback journal, not a parallel store.
        self.assertEqual(
            self.inbox.db.execute(
                "SELECT COUNT(*) FROM maintenance_feedback"
            ).fetchone()[0],
            3,
        )
        self.assertEqual(self.inbox.history("case-a")[0]["message"], body["message"])

    def test_source_pages_keep_exact_text_and_version(self):
        page = self.service.source(self.service.ref, self.target, offset=4, limit=4096)
        self.assertEqual(page["text"], self.original_text[4:4100])
        self.assertEqual(page["next_offset"], 4100)
        self.assertEqual(page["target"]["version_id"], "v1")
        for target in (
            dict(self.target, version_id="v2"),
            dict(self.target, source_ref="source-b"),
            dict(self.target, work_ref="paper-b"),
        ):
            with self.assertRaisesRegex(MaintenanceInboxError, "review-target-differs"):
                self.service.source(self.service.ref, target)

    def test_wrong_project_source_hash_principal_revision_and_unknown_fields_refuse(
        self,
    ):
        body = self.request()
        bad = []
        for field, value in (("project_id", "project-b"), ("input_version", 2)):
            changed = deepcopy(body)
            changed["offer"]["context"][field] = value
            bad.append(changed)
        for field, value in (
            ("source_sha256", "a" * 64),
            ("version_id", "v2"),
            ("work_ref", "paper-b"),
        ):
            changed = deepcopy(body)
            changed["offer"]["target"][field] = value
            bad.append(changed)
        changed = deepcopy(body)
        changed["offer"]["revision"] = 1
        bad.append(changed)
        changed = deepcopy(body)
        changed["offer"]["context"]["core_acceptance"] = 0
        bad.append(changed)
        bad.extend(
            (
                dict(body, path=str(self.package)),
                dict(body, confirmed=False),
                dict(body, decision="approved"),
            )
        )
        for item in bad:
            with self.subTest(item=item), self.assertRaises(MaintenanceInboxError):
                self.service.submit("reviewer-a", self.service.ref, item)
        with self.assertRaises(MaintenanceInboxError):
            self.service.submit("reviewer-b", self.service.ref, body)
        with self.assertRaises(MaintenanceInboxError):
            self.service.submit("reviewer-a", "wrong-review-ref", body)
        self.assertEqual(self.service.history(self.service.ref), [])

    def test_same_key_reopen_after_source_drift_is_passive_but_new_action_refuses(self):
        body = self.request()
        receipt = self.service.submit("reviewer-a", self.service.ref, body)
        fresh = self.request(key="two")
        (self.package / "source-a.txt").write_text(
            "Changed original bytes", encoding="utf8"
        )
        self.inbox.close()
        self.inbox = MaintenanceInbox(self.db, self.bindings)
        self.service = self.build(self.inbox)
        self.assertEqual(self.service.action(self.service.ref, "one"), receipt)
        self.assertEqual(
            self.service.submit("reviewer-a", self.service.ref, body),
            dict(receipt, replayed=True),
        )
        with self.assertRaisesRegex(MaintenanceInboxError, "source-changed"):
            self.service.offer(
                "reviewer-a", self.service.ref, "submit-review", self.target
            )
        with self.assertRaisesRegex(MaintenanceInboxError, "source-changed"):
            self.service.submit("reviewer-a", self.service.ref, fresh)
        with self.assertRaisesRegex(
            MaintenanceInboxError, "idempotency-payload-differs"
        ):
            self.service.submit(
                "reviewer-a", self.service.ref, dict(body, message="Changed opinion")
            )
        self.assertEqual(len(self.service.history(self.service.ref)), 1)

    def test_two_handles_same_key_deduplicate_and_distinct_keys_use_revision_cas(self):
        other = MaintenanceInbox(self.db, self.bindings)
        try:
            second = self.build(other)
            body = self.request()
            with ThreadPoolExecutor(max_workers=2) as pool:
                results = list(
                    pool.map(
                        lambda service: service.submit("reviewer-a", service.ref, body),
                        (self.service, second),
                    )
                )
            self.assertEqual(sum(not row["replayed"] for row in results), 1)
            body = self.request(key="cas-a")
            stale = dict(body, key="cas-b")
            with ThreadPoolExecutor(max_workers=2) as pool:
                futures = [
                    pool.submit(service.submit, "reviewer-a", service.ref, data)
                    for service, data in ((self.service, body), (second, stale))
                ]
                outcomes = []
                for future in futures:
                    try:
                        outcomes.append(future.result())
                    except MaintenanceInboxError as error:
                        outcomes.append(str(error))
            self.assertEqual(sum(isinstance(row, dict) for row in outcomes), 1)
            self.assertIn("stale-review-revision", outcomes)
            self.assertEqual(len(self.service.history(self.service.ref)), 2)
        finally:
            other.close()

    def test_stale_form_and_deadline_or_post_insert_drift_roll_back(self):
        first = self.request()
        stale = self.request(key="stale")
        self.service.submit("reviewer-a", self.service.ref, first)
        with self.assertRaisesRegex(MaintenanceInboxError, "stale-review-revision"):
            self.service.submit("reviewer-a", self.service.ref, stale)
        body = self.request(key="new")

        def expired():
            raise TimeoutError("deadline expired")

        with self.assertRaises(TimeoutError):
            self.service.submit(
                "reviewer-a", self.service.ref, body, before_commit=expired
            )
        original = self.inbox._public

        def mutate_after_insert(row, **kwargs):
            result = original(row, **kwargs)
            if row["client_key"] == "new":
                (self.package / "source-b.txt").write_bytes(
                    b"Changed during transaction"
                )
            return result

        with patch.object(self.inbox, "_public", side_effect=mutate_after_insert):
            with self.assertRaisesRegex(MaintenanceInboxError, "source-changed"):
                self.service.submit("reviewer-a", self.service.ref, body)
        self.assertFalse(self.inbox.db.in_transaction)
        self.assertEqual(len(self.service.history(self.service.ref)), 1)

    def test_independent_registration_pin_and_private_binding_are_required(self):
        self.service.submit("reviewer-a", self.service.ref, self.request())
        with self.assertRaisesRegex(MaintenanceInboxError, "registration-pin-differs"):
            SavedReviewService(
                self.inbox,
                package_root=self.package,
                registration_path=self.registration_path,
                registration_sha256="a" * 64,
            )
        changed = deepcopy(self.registration)
        changed["project_id"] = "other-project"
        self.registration_path.write_bytes(canonical(changed))
        with self.assertRaisesRegex(MaintenanceInboxError, "case-binding-differs"):
            SavedReviewService(
                self.inbox,
                package_root=self.package,
                registration_path=self.registration_path,
                registration_sha256=sha(canonical(changed)),
            )
        for table in ("maintenance_review_bindings", "maintenance_feedback"):
            for verb in ("UPDATE", "DELETE"):
                statement = (
                    f"DELETE FROM {table}"
                    if verb == "DELETE"
                    else f"UPDATE {table} SET case_ref='x'"
                )
                with self.assertRaises(sqlite3.IntegrityError):
                    self.inbox.db.execute(statement)

    def test_history_pagination_and_cli_receipt_readback(self):
        body = self.request()
        first = self.service.submit("reviewer-a", self.service.ref, body)
        self.service.submit("reviewer-a", self.service.ref, self.request(key="two"))
        self.assertEqual(
            len(self.service.history(self.service.ref, after_revision=1, limit=1)), 1
        )
        argv = [
            "--database",
            str(self.db),
            "--package-root",
            str(self.package),
            "--registration",
            str(self.registration_path),
            "--expected-registration-sha256",
            self.registration_sha,
            "action",
            "--key",
            "one",
        ]
        stream = StringIO()
        with redirect_stdout(stream):
            self.assertEqual(main(argv), 0)
        self.assertEqual(json.loads(stream.getvalue()), first)

    def test_mutated_registration_cache_cannot_replace_an_independent_pin(self):
        changed = b"Untrusted replacement"
        (self.package / "source-a.txt").write_bytes(changed)
        self.service.registration["artifacts"]["source-a"].update(
            sha256=sha(changed), bytes=len(changed)
        )
        with self.assertRaisesRegex(MaintenanceInboxError, "registration-differs"):
            self.service.offer(
                "reviewer-a", self.service.ref, "submit-review", self.target
            )


if __name__ == "__main__":
    unittest.main()
