"""Pinned batch evidence is additive; it never supplies per-work discoveries."""

from copy import deepcopy
import csv
import io
import json
from pathlib import Path
import tempfile
import unittest

from openpyxl import load_workbook

from test_saved_source_reassessment import review_case
from research_workspace.delivery_review import delivery_review_files
from research_workspace.original_record_recovery import attach_original_records
from research_workspace.projection import validate_index
from research_workspace.retrieval_trace import work_trace
from research_workspace.saved_search_ledger import CONTRACT, project_saved_search_ledger
from stage1_deliverable.common import DeliverableError, canonical, sha


def ref(path, pointer=""):
    return dict(path=path, pointer=pointer)


def save(root, docs):
    for name, content in docs.items():
        (root / name).write_bytes(content)
    raw = canonical(
        dict(
            kind="Stage1OriginalRecordRecovery",
            schema_version="1.0.0",
            files={name: sha(raw) for name, raw in docs.items()},
        )
    )
    (root / "manifest.json").write_bytes(raw)
    return sha(raw)


def ledger_case(root):
    index, _ = review_case(root)
    index["sources"][0]["receipt"]["url"] = "https://example.org/evidence"
    input_sha = sha(canonical(index))
    docs = {p.name: p.read_bytes() for p in root.iterdir() if p.name != "manifest.json"}
    spec = json.loads(docs["recovery.json"])
    spec["input_canonical_sha256"] = input_sha
    reviews = json.loads(docs["new.json"])
    for row in reviews.values():
        row["input_canonical_sha256"] = input_sha
    docs["new.json"] = canonical(reviews)
    text = "Synthetic evidence (https://example.org/evidence)\nSaved result text.\n"
    docs["capture-1.json"] = canonical(
        dict(
            query=[
                dict(q="synthetic parameter one"),
                dict(q="synthetic parameter two"),
            ],
            started_at="2026-10-09T01:00:00Z",
            actual_native_result=text,
            screening_and_reading_not_implied=True,
        )
    )
    docs["capture-2.json"] = canonical(text)
    observations, rows, reservations = [], [], []
    for n in (1, 2):
        batch = f"native-search00{n}"
        raw = docs[f"capture-{n}.json"]
        observation = dict(
            observation_ref=f"{batch}:header-001",
            batch_ref=batch,
            batch_started_at="2026-10-09T01:00:00Z" if n == 1 else None,
            raw_header_line=1,
            title_observed="Synthetic evidence",
            url_observed="https://example.org/evidence",
            saved_receipt_ref=dict(
                path=f"saved-native/{batch}.json", bytes=len(raw), sha256=sha(raw)
            ),
        )
        observations.append(observation)
        rows.append(
            dict(
                **{
                    k: observation[k]
                    for k in ("observation_ref", "title_observed", "url_observed")
                },
                original_observation_sha256=sha(canonical(observation)),
                decision="include",
                linked_work_id="fixture-0",
                linked_version_id="version-0",
                rationale="The exact saved URL identifies the work in the supplied source inventory.",
                reason_code="same-source",
                mapping_basis="saved work URL",
                saved_evidence=dict(
                    batch_ref=batch,
                    source_sha256=sha(raw),
                    start=0,
                    end=len(text),
                    quote=text,
                ),
            )
        )
        reservations.append(
            dict(
                id=batch,
                queries=2,
                status="actual-native-search-completed",
                receipt=f"search/{batch}.json",
                receipt_sha256=sha(raw),
                receipt_persisted_at=f"2026-10-09T0{n}:01:00Z",
                tool_completion_time="not-separately-captured",
            )
        )
    reservations[0]["reserved_at"] = "2026-10-09T01:00:00Z"
    reservations[1].update(
        started_at="2026-10-09T02:00:00Z",
        query_texts=[
            dict(q="synthetic body follow-up", need="source"),
            dict(q="synthetic boundary follow-up", need="boundary"),
        ],
    )
    docs["observations.json"] = canonical(observations)
    docs["candidate.json"] = canonical(
        dict(
            kind="NewSavedCandidateScreening",
            scope="saved-observations-only",
            not_historical=True,
            input_canonical_sha256=input_sha,
            reviewed_at="2026-10-21T03:00:00Z",
            reviewer=dict(
                type="ai", identity="synthetic reviewer", authenticated=False
            ),
            observations_ref=ref("observations.json"),
            rows=rows,
            captures={
                "native-search001": ref("capture-1.json", "/actual_native_result"),
                "native-search002": ref("capture-2.json"),
            },
        )
    )
    ledger = dict(
        kind="Stage1RehearsalOwnerSubmittedScope",
        project_id=index["project_id"],
        input_version="synthetic-input",
        search_reservations=reservations,
    )
    docs["run-control.json"] = canonical(ledger)
    snapshot = dict(
        kind="SavedSourceCandidateSnapshot",
        schema_version="1.0.0",
        project_id=index["project_id"],
        input_version="synthetic-input",
        bindings=dict(
            resources=dict(
                path="run-control.json",
                bytes=len(docs["run-control.json"]),
                sha256=sha(docs["run-control.json"]),
            ),
            deliverable=dict(sha256=index["provenance"]["deliverable_manifest_sha256"]),
        ),
    )
    docs["snapshot.json"] = canonical(snapshot)
    spec["new_candidate_screening"] = ref("candidate.json")
    spec["saved_search_ledger"] = dict(
        contract_version=CONTRACT,
        input_version="synthetic-input",
        ledger=ref("run-control.json"),
        snapshot=ref("snapshot.json"),
        receipts={
            "native-search001": dict(
                receipt=ref("capture-1.json"),
                query_parameters=ref("capture-1.json", "/query"),
            ),
            "native-search002": dict(
                receipt=ref("capture-2.json"),
                query_parameters=ref(
                    "run-control.json", "/search_reservations/1/query_texts"
                ),
            ),
        },
    )
    docs["recovery.json"] = canonical(spec)
    return index, docs


def project(index, docs):
    """Exercise semantic guards after the containing recovery pinned the bytes."""

    def resolve(reference):
        value = json.loads(docs[reference["path"]])
        for part in reference["pointer"].split("/")[1:]:
            value = value[int(part)] if isinstance(value, list) else value[part]
        return dict(
            **reference, value=value, source_sha256=sha(docs[reference["path"]])
        )

    spec = json.loads(docs["recovery.json"])["saved_search_ledger"]
    return project_saved_search_ledger(
        spec, resolve, index, docs, json.loads(docs["observations.json"])
    )


def change_ledger(docs, mutation):
    ledger = json.loads(docs["run-control.json"])
    mutation(ledger)
    docs["run-control.json"] = canonical(ledger)
    snapshot = json.loads(docs["snapshot.json"])
    snapshot["bindings"]["resources"].update(
        bytes=len(docs["run-control.json"]), sha256=sha(docs["run-control.json"])
    )
    docs["snapshot.json"] = canonical(snapshot)


class SavedSearchLedgerTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(
            dir=Path(tempfile.gettempdir()).resolve()
        )
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.index, self.docs = ledger_case(self.root)

    def test_two_batches_preserve_original_observations_reviews_and_timestamp_meanings(
        self,
    ):
        pin = save(self.root, self.docs)
        attached = attach_original_records(self.index, self.root, pin)
        validate_index(json.loads(canonical(attached)))
        payload = attached["original_record_recovery"]["payload"]
        self.assertEqual(
            payload["new_candidate_screening"]["observations"],
            json.loads(self.docs["observations.json"]),
        )
        self.assertEqual(
            payload["new_candidate_screening"]["value"],
            json.loads(self.docs["candidate.json"]),
        )
        trace = work_trace(attached, "fixture-0")
        self.assertIsNone(trace["first_discovery"])
        self.assertIsNone(trace["counts"])
        self.assertIsNone(trace["search_attempts_until_first_discovery"])
        self.assertEqual(trace["query_history_scope"], "not-recorded")
        self.assertEqual(trace["saved_observation_count"], 2)
        first, second = (row["batch_context"] for row in trace["observations"])
        self.assertIsNone(first["started_at"])
        self.assertEqual(first["receipt_started_at"], "2026-10-09T01:00:00Z")
        self.assertEqual(first["reserved_at"], first["receipt_started_at"])
        self.assertEqual(second["started_at"], "2026-10-09T02:00:00Z")
        self.assertEqual(second["tool_completion_time"], "not-separately-captured")
        self.assertEqual(len(first["query_parameters"]), 2)
        self.assertEqual(second["query_parameters"][0]["need"], "source")
        self.assertIsNone(trace["observations"][1]["observation"]["batch_started_at"])
        self.assertFalse(
            payload["saved_search_ledger"]["historical_discovery_events_reconstructed"]
        )

    def test_wrong_project_input_and_snapshot_pins_fail_closed(self):
        for source, key, value in (
            ("run-control.json", "project_id", "other"),
            ("run-control.json", "input_version", "other"),
            ("snapshot.json", "project_id", "other"),
            ("snapshot.json", "input_version", "other"),
        ):
            with self.subTest(source=source, key=key):
                docs = deepcopy(self.docs)
                row = json.loads(docs[source])
                row[key] = value
                docs[source] = canonical(row)
                with self.assertRaisesRegex(DeliverableError, "project/input"):
                    project(self.index, docs)
        for binding, field, value in (
            ("resources", "sha256", "f" * 64),
            ("resources", "bytes", 1),
            ("deliverable", "sha256", "f" * 64),
        ):
            with self.subTest(binding=binding, field=field):
                docs = deepcopy(self.docs)
                snapshot = json.loads(docs["snapshot.json"])
                snapshot["bindings"][binding][field] = value
                docs["snapshot.json"] = canonical(snapshot)
                with self.assertRaisesRegex(DeliverableError, "snapshot"):
                    project(self.index, docs)

    def test_only_new_payload_key_changes_and_missing_query_parameters_stay_unknown(
        self,
    ):
        attached = attach_original_records(
            self.index, self.root, save(self.root, self.docs)
        )
        expected = deepcopy(attached["original_record_recovery"]["payload"])
        expected.pop("saved_search_ledger")
        spec = json.loads(self.docs["recovery.json"])
        without = deepcopy(spec)
        without.pop("saved_search_ledger")
        docs = {**self.docs, "recovery.json": canonical(without)}
        legacy = attach_original_records(self.index, self.root, save(self.root, docs))
        self.assertEqual(
            canonical(legacy["original_record_recovery"]["payload"]),
            canonical(expected),
        )
        for entry in spec["saved_search_ledger"]["receipts"].values():
            entry.pop("query_parameters")
        docs = {**self.docs, "recovery.json": canonical(spec)}
        context = project(self.index, docs)
        self.assertTrue(
            all(row["query_parameters"] is None for row in context["batches"])
        )
        self.assertTrue(
            all(row["query_parameters_source"] is None for row in context["batches"])
        )

    def test_unknown_attachment_fields_and_extra_receipt_reject(self):
        for mutation in (
            lambda spec: spec.update(unknown=True),
            lambda spec: spec.update(contract_version="unsupported"),
            lambda spec: spec["receipts"].update(
                extra=dict(receipt=ref("capture-1.json"))
            ),
        ):
            spec = json.loads(self.docs["recovery.json"])
            mutation(spec["saved_search_ledger"])
            docs = {**self.docs, "recovery.json": canonical(spec)}
            with self.assertRaises(DeliverableError):
                project(self.index, docs)

    def test_duplicate_batch_wrong_receipt_and_unmapped_receipt_reject(self):
        for mutation in (
            lambda x: x["search_reservations"][1].update(id="native-search001"),
            lambda x: x["search_reservations"][0].update(receipt_sha256="f" * 64),
            lambda x: x["search_reservations"][1].update(
                receipt="search/native-search001.json"
            ),
        ):
            docs = deepcopy(self.docs)
            change_ledger(docs, mutation)
            with self.assertRaises(DeliverableError):
                project(self.index, docs)
        spec = json.loads(self.docs["recovery.json"])
        del spec["saved_search_ledger"]["receipts"]["native-search002"]
        self.docs["recovery.json"] = canonical(spec)
        with self.assertRaisesRegex(DeliverableError, "unmapped receipt"):
            project(self.index, self.docs)

    def test_observation_hash_and_length_must_match_mapped_receipt(self):
        for field, value in (("sha256", "f" * 64), ("bytes", 1)):
            docs = deepcopy(self.docs)
            observations = json.loads(docs["observations.json"])
            observations[0]["saved_receipt_ref"][field] = value
            docs["observations.json"] = canonical(observations)
            with self.assertRaisesRegex(DeliverableError, "observation receipt"):
                project(self.index, docs)

    def test_cross_batch_query_source_and_bad_query_shapes_reject(self):
        spec = json.loads(self.docs["recovery.json"])
        spec["saved_search_ledger"]["receipts"]["native-search001"][
            "query_parameters"
        ] = ref("run-control.json", "/search_reservations/1/query_texts")
        docs = {**self.docs, "recovery.json": canonical(spec)}
        with self.assertRaisesRegex(DeliverableError, "outside this batch"):
            project(self.index, docs)
        for queries in ([], ["only one"], [dict(need="missing query"), "second"]):
            docs = deepcopy(self.docs)
            change_ledger(
                docs, lambda x: x["search_reservations"][1].update(query_texts=queries)
            )
            with self.assertRaisesRegex(DeliverableError, "query parameter"):
                project(self.index, docs)

    def test_invalid_or_reversed_times_reject_without_inventing_completion(self):
        for field, value in (
            ("started_at", "2026-10-09T02:00:00"),
            ("started_at", "not-recorded"),
            ("receipt_persisted_at", "2026-10-08T00:00:00Z"),
            ("tool_completion_time", "2026-10-10T00:00:00Z"),
        ):
            docs = deepcopy(self.docs)
            change_ledger(
                docs, lambda x: x["search_reservations"][1].update({field: value})
            )
            with self.assertRaisesRegex(DeliverableError, "timestamp"):
                project(self.index, docs)

    def test_rehash_tamper_rejected_and_source_edits_do_not_pass_snapshot_replay(self):
        attached = attach_original_records(
            self.index, self.root, save(self.root, self.docs)
        )
        attachment = attached["original_record_recovery"]
        attachment["payload"]["saved_search_ledger"]["batches"][0]["started_at"] = (
            "2026-10-09T01:00:00Z"
        )
        attachment["payload_sha256"] = sha(canonical(attachment["payload"]))
        with self.assertRaisesRegex(DeliverableError, "projection differs"):
            validate_index(attached)
        self.docs["run-control.json"] += b" "
        with self.assertRaisesRegex(DeliverableError, "snapshot resource"):
            attach_original_records(self.index, self.root, save(self.root, self.docs))

    def test_exports_and_new_view_include_bound_batch_context(self):
        attached = attach_original_records(
            self.index, self.root, save(self.root, self.docs)
        )
        before = canonical(attached)
        files = delivery_review_files(attached)
        trace = json.loads(files["literature/academic_screening.json"])["rows"][0][
            "retrieval_trace"
        ]
        rows = list(
            csv.DictReader(
                io.StringIO(
                    files["literature/academic_screening.csv"].decode("utf-8-sig")
                )
            )
        )
        self.assertEqual(json.loads(rows[0]["retrieval_trace"]), trace)
        book = load_workbook(
            io.BytesIO(files["literature/academic_screening.xlsx"]), read_only=True
        )
        values = list(book["AcademicScreening"].values)
        self.assertEqual(
            json.loads(values[1][values[0].index("retrieval_trace")]), trace
        )
        book.close()
        self.assertIn(
            b"synthetic body follow-up", files["literature/academic_screening.md"]
        )
        self.assertEqual(canonical(attached), before)
        from research_workspace.view import write_workspace
        from research_workspace.final_delivery import _view

        output = self.root / "new-view"
        manifest = write_workspace(
            attached,
            Path(__file__).parents[1] / "references/research-workspace",
            output,
        )
        for name in ("saved_search_ledger.py", "SavedSearchLedger.v1.schema.json"):
            self.assertEqual(
                manifest["adapter_sources"][name],
                sha(
                    (
                        Path(__file__).parents[1] / "cli/research_workspace" / name
                    ).read_bytes()
                ),
            )
        _view(output, sha((output / "view-manifest.json").read_bytes()))


if __name__ == "__main__":
    unittest.main()
