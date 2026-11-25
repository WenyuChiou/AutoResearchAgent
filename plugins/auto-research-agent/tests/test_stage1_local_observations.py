"""Local cell notes retain agent identity and never become human evidence."""

from copy import deepcopy
from contextlib import contextmanager
import unittest

from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import ProjectStage1Service
from research_workspace_native.project_stage1_local_observations import (
    ProjectStage1LocalObservationService,
)
from research_workspace_native.session_api import SessionApiError
from stage1_ledger.journal import LedgerError
from stage1_deliverable.common import sha
import test_stage1_provided_candidate as provided_fixture
from test_workspace_project_intake import authenticate


class LocalObservationTests(unittest.TestCase):
    @contextmanager
    def sample(self, raw, checkpoint="after"):
        c = provided_fixture.ProvidedCandidateTests()
        c.setUp()
        try:
            if checkpoint == "before":
                c.service.checkpoint("alice-token", c.ref, c.action_body(c.ref, "cp"))
            c.data = raw
            (c.material / "table.csv").write_bytes(raw)
            c.admit()
            if checkpoint == "after":
                c.service.checkpoint("alice-token", c.ref, c.action_body(c.ref, "cp"))
            yield c
            c.runner.assert_not_called()
        finally:
            c.tearDown()

    def sample_body(self, c, unit="mg", *, row=2, column=2, quote="42", start=17):
        view = c.intake.read("alice-token", c.ref)
        stage = c.service.read("alice-token", c.ref)
        source = c.private_ledger(c.ref).candidates()[c.work]["discoveries"][0][
            "provided"
        ]["material_ref"]
        return dict(
            key="sample-cell",
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            ledger_state_sha256=stage["ledger"]["state_sha256"],
            checkpoint_event_id=stage["checkpoint"]["event_id"]
            if stage["checkpoint"]
            else None,
            work_id=c.work,
            version_id=c.version,
            source_ref=source,
            material_sha256=sha(c.data),
            row=row,
            column=column,
            start_byte=start,
            end_byte=start + len(quote.encode("utf8")),
            quote=quote,
            unit=unit,
            note="Agent local cell only.",
        )

    def counts(self, c):
        return [
            c.intake.db.execute("SELECT count(*) FROM " + table).fetchone()[0]
            for table in ("intake_actions", "intake_events")
        ]

    def journal_rows(self, c):
        return {
            table: [
                tuple(row)
                for row in c.intake.db.execute(
                    "SELECT * FROM " + table + " ORDER BY rowid"
                )
            ]
            for table in ("intake_projects", "intake_actions", "intake_events")
        }

    def test_column_declaration_precedence_uses_source_not_request(self):
        cases = (
            ("%", "mg/L", False),
            ("mg/L", "mg/L", True),
            ("mg/L", "mg", False),
            ("Mean (mg/L)", "mg/L", True),
            ("Mean (estimated)", "mg/L", True),
            ("Mean (estimated)", "mg", False),
            ("Mean", "mg/L", True),
            ("A", "mg/L", True),
            ("(A)", "mg/L", False),
            ("L", "mg/L", False),
            ("mg/L (estimated)", "mg/L", True),
            ("% (estimated)", "mg/L", False),
            ("Mean (unknown)", "mg/L", False),
            ("Mean (mg/L) (%)", "mg/L", False),
            ("mg/L (g)", "mg/L", False),
            ("mg/L extra", "mg/L", False),
            ("Mean (mg/L", "mg/L", False),
        )
        for label, unit, valid in cases:
            raw = f"Item,{label}\nConcentration (mg/L),42\n".encode()
            with self.subTest(label=label, unit=unit), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                body = self.sample_body(c, unit, start=raw.index(b"42"))
                before = self.journal_rows(c)
                if not valid:
                    with self.assertRaises(SessionApiError):
                        service.record("alice-token", c.ref, body)
                    self.assertEqual(self.journal_rows(c), before)
                    continue
                first = service.record("alice-token", c.ref, body)
                c.intake.close()
                c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
                c.service = ProjectStage1Service(c.intake)
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.journal_rows(c)
                read = service.read("alice-token", c.ref, body["key"])
                repeat = service.record("alice-token", c.ref, body)
                self.assertEqual(first["observation"], read["observation"])
                self.assertEqual(first["observation"], repeat["observation"])
                self.assertTrue(repeat["replayed"])
                self.assertEqual(self.journal_rows(c), before)

    def test_column_annotation_cannot_replace_required_row_unit(self):
        for row_label in ("Concentration", "Concentration (estimated)"):
            raw = f"Item,mg/L\n{row_label},42\n".encode()
            with self.subTest(row=row_label), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.journal_rows(c)
                with self.assertRaises(SessionApiError):
                    service.record(
                        "alice-token",
                        c.ref,
                        self.sample_body(c, "mg/L", start=raw.index(b"42")),
                    )
                self.assertEqual(self.journal_rows(c), before)

    def test_age_group_column_grammar_keeps_row_unit_on_reopen(self):
        for column in (
            "All consumer units",
            "Under 25 years",
            "25–34 years",
            "35–44 years",
            "45–54 years",
            "55–64 years",
            "65 years and older",
            "65–74 years",
            "75 years and older",
            "18 years or older",
            "12 years and younger",
            "Over 18 years",
            "18 to 24 years",
            "30-39 years",
        ):
            raw = f"Item,{column}\nIncome (in dollars),42\n".encode()
            with self.subTest(column=column), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                body = self.sample_body(c, "dollars", start=raw.index(b"42"))
                saved = service.record("alice-token", c.ref, body)
                self.assertEqual(saved["observation"]["cell"]["unit"], "dollars")
                self.assertEqual(saved["observation"]["cell"]["column_label"], column)
                c.intake.close()
                c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
                service = ProjectStage1LocalObservationService(
                    ProjectStage1Service(c.intake), agent_id="test-agent"
                )
                before = self.journal_rows(c)
                self.assertEqual(
                    service.read("alice-token", c.ref, body["key"])["observation"],
                    saved["observation"],
                )
                again = service.record("alice-token", c.ref, body)
                self.assertTrue(again["replayed"])
                self.assertEqual(again["observation"], saved["observation"])
                self.assertEqual(self.journal_rows(c), before)

    def test_age_category_cannot_hide_unit_options_or_supply_requested_unit(self):
        for column, row, unit in (
            ("65 years and older or ft", "Income (dollars)", "dollars"),
            ("65 mg and older", "Mass (mg)", "mg"),
            ("65 years and older (A)", "Income (dollars)", "dollars"),
            ("65 years and unknown", "Income (dollars)", "dollars"),
            ("65 years and older", "Income", "dollars"),
            ("65 years and older", "Income (dollars)", "cents"),
        ):
            raw = f"Item,{column}\n{row},42\n".encode()
            with self.subTest(column=column, row=row, unit=unit), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.journal_rows(c)
                with self.assertRaises(SessionApiError):
                    service.record(
                        "alice-token",
                        c.ref,
                        self.sample_body(c, unit, start=raw.index(b"42")),
                    )
                self.assertEqual(self.journal_rows(c), before)

    def test_alternative_unit_declarations_cannot_borrow_row_or_request_unit(self):
        import csv
        import io

        declarations = (
            "m or ft",
            "m OR ft",
            "m versus ft",
            "m vs. ft",
            "m and ft",
            "m and/or ft",
            "m | ft",
            "m; ft",
            "m, ft",
            "m & ft",
            "m + ft",
            "m to ft",
            "m-ft",
            "m = ft",
            "m → ft",
            "m or unknown",
            "meters or feet",
            "Mean or median",
            "Length in m or ft",
            "m or ft (estimated)",
        )
        for declaration in declarations:
            text = io.StringIO(newline="")
            csv.writer(text, lineterminator="\n").writerows(
                [["Item", declaration], ["Length (cm)", "42"]]
            )
            raw = text.getvalue().encode()
            with self.subTest(declaration=declaration), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.journal_rows(c)
                for unit in ("cm", "m", "ft"):
                    body = self.sample_body(c, unit, start=raw.index(b"42"))
                    with self.assertRaisesRegex(
                        SessionApiError, "local-observation-unit-evidence-ambiguous"
                    ):
                        service.record("alice-token", c.ref, body)
                    self.assertEqual(self.journal_rows(c), before)

    def test_row_prefix_alternatives_are_not_hidden_by_one_parenthesized_unit(self):
        raw = b"Item,Mean\nLength m or ft (cm),42\n"
        with self.sample(raw) as c:
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            before = self.journal_rows(c)
            with self.assertRaisesRegex(
                SessionApiError, "local-observation-unit-evidence-ambiguous"
            ):
                service.record(
                    "alice-token",
                    c.ref,
                    self.sample_body(c, "cm", start=raw.index(b"42")),
                )
            self.assertEqual(self.journal_rows(c), before)

    def test_whole_unit_expressions_and_non_unit_categories_still_reopen(self):
        for column, row, unit in (
            ("m/ft", "Ratio (m/ft)", "m/ft"),
            ("Median", "Length (cm)", "cm"),
        ):
            raw = f"Item,{column}\n{row},42\n".encode()
            with self.subTest(column=column), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                body = self.sample_body(c, unit, start=raw.index(b"42"))
                saved = service.record("alice-token", c.ref, body)
                c.intake.close()
                c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
                service = ProjectStage1LocalObservationService(
                    ProjectStage1Service(c.intake), agent_id="test-agent"
                )
                before = self.journal_rows(c)
                self.assertEqual(
                    service.read("alice-token", c.ref, body["key"])["observation"],
                    saved["observation"],
                )
                retry = service.record("alice-token", c.ref, body)
                self.assertEqual(retry["observation"], saved["observation"])
                self.assertTrue(retry["replayed"])
                self.assertEqual(self.journal_rows(c), before)

    def test_row_and_selected_column_units_must_agree_before_save(self):
        raw = (
            b"Analyte,Mean (mg/L),Coefficient of variation (%)\n"
            b"Concentration (mg/L),42,8\n"
        )
        with self.sample(raw) as c:
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            for unit in ("mg/L", "%"):
                before = self.journal_rows(c)
                with (
                    self.subTest(unit=unit),
                    self.assertRaisesRegex(
                        SessionApiError, "local-observation-row-column-unit-conflict"
                    ),
                ):
                    service.record(
                        "alice-token",
                        c.ref,
                        self.sample_body(c, unit, column=3, quote="8", start=73),
                    )
                self.assertEqual(self.journal_rows(c), before)
            body = self.sample_body(c, "mg/L", start=70)
            first = service.record("alice-token", c.ref, body)
            c.intake.close()
            c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
            c.service = ProjectStage1Service(c.intake)
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            before = self.journal_rows(c)
            self.assertEqual(
                service.read("alice-token", c.ref, body["key"])["observation"],
                first["observation"],
            )
            again = service.record("alice-token", c.ref, body)
            self.assertTrue(again["replayed"])
            self.assertEqual(again["observation"], first["observation"])
            self.assertEqual(self.journal_rows(c), before)

    def test_complete_compound_unit_refuses_both_components_without_writes(self):
        with self.sample(b"Item,A\nConcentration (mg/L),42\n") as c:
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            for unit in ("mg", "L"):
                before = self.journal_rows(c)
                with self.subTest(unit=unit), self.assertRaises(SessionApiError):
                    service.record(
                        "alice-token", c.ref, self.sample_body(c, unit, start=28)
                    )
                self.assertEqual(self.journal_rows(c), before)
            body = self.sample_body(c, "mg/L", start=28)
            first = service.record("alice-token", c.ref, body)
            c.intake.close()
            c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
            c.service = ProjectStage1Service(c.intake)
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            before = self.journal_rows(c)
            self.assertEqual(
                service.read("alice-token", c.ref, body["key"])["observation"],
                first["observation"],
            )
            again = service.record("alice-token", c.ref, body)
            self.assertTrue(again["replayed"])
            self.assertEqual(again["observation"], first["observation"])
            self.assertEqual(self.journal_rows(c), before)

    def test_explicit_compound_declarations_match_whole_original_spelling(self):
        for unit, truncated in (
            ("mg / L", "mg"),
            ("mg·kg^-1", "kg"),
            ("kg m^-2 s^-1", "m"),
            ("m²/s", "s"),
        ):
            raw = f"Item,A\nMeasure ({unit}),42\n".encode("utf8")
            with self.subTest(unit=unit), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                start = raw.index(b"42")
                before = self.journal_rows(c)
                with self.assertRaises(SessionApiError):
                    service.record(
                        "alice-token",
                        c.ref,
                        self.sample_body(c, truncated, start=start),
                    )
                self.assertEqual(self.journal_rows(c), before)
                got = service.record(
                    "alice-token", c.ref, self.sample_body(c, unit, start=start)
                )
                self.assertEqual(got["observation"]["cell"]["unit"], unit)

    def test_unit_evidence_distinguishes_symbols_annotations_and_footnotes(self):
        examples = (
            ("Pressure (in Hg)", "in Hg", ("Hg", "in")),
            ("Concentration (mg/L) (estimated)", "mg/L", ("estimated", "mg", "L")),
            ("Number of consumer units (in thousands)[1]", "thousands", ("units", "1")),
            ("Income (in dollars)[1][2]", "dollars", ("in",)),
            ("Mass (estimated) (mg)", "mg", ("estimated",)),
        )
        for label, valid, invalid in examples:
            raw = f"Item,A\n{label},42\n".encode("utf8")
            with self.subTest(label=label), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                start = raw.index(b"42")
                before = self.journal_rows(c)
                for unit in invalid:
                    with self.subTest(unit=unit), self.assertRaises(SessionApiError):
                        service.record(
                            "alice-token", c.ref, self.sample_body(c, unit, start=start)
                        )
                    self.assertEqual(self.journal_rows(c), before)
                body = self.sample_body(c, valid, start=start)
                first = service.record("alice-token", c.ref, body)
                c.intake.close()
                c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
                service = ProjectStage1LocalObservationService(
                    ProjectStage1Service(c.intake), agent_id="test-agent"
                )
                stored = self.journal_rows(c)
                self.assertEqual(
                    service.read("alice-token", c.ref, body["key"])["observation"],
                    first["observation"],
                )
                self.assertTrue(service.record("alice-token", c.ref, body)["replayed"])
                self.assertEqual(self.journal_rows(c), stored)

    def test_ambiguous_or_unknown_unit_evidence_refuses_without_rewriting(self):
        for label, unit in (
            ("Mass (mg) (g)", "mg"),
            ("Mass (estimated)", "estimated"),
            ("Mass (mg) (per day)", "mg"),
            ("Mass (mg)/(L)", "mg"),
            ("Mass ((mg))", "mg"),
            ("Mass (mg)[unresolved]", "mg"),
            ("Mass (unknown-unit)", "unknown-unit"),
        ):
            raw = f"Item,A\n{label},42\n".encode("utf8")
            with self.subTest(label=label), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.journal_rows(c)
                with self.assertRaises(SessionApiError):
                    service.record(
                        "alice-token",
                        c.ref,
                        self.sample_body(c, unit, start=raw.index(b"42")),
                    )
                self.assertEqual(self.journal_rows(c), before)

    def test_checkpoint_must_exist_and_cover_source_before_any_action(self):
        for timing, reason in (
            ("none", "local-observation-checkpoint-required"),
            ("before", "local-observation-checkpoint-state-differs"),
        ):
            with (
                self.subTest(timing=timing),
                self.sample(b"Item,A\nMass (mg),42\n", timing) as c,
            ):
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                before = self.counts(c)
                with self.assertRaisesRegex(SessionApiError, reason):
                    service.record("alice-token", c.ref, self.sample_body(c))
                self.assertEqual(self.counts(c), before)
                c.service.checkpoint(
                    "alice-token", c.ref, c.action_body(c.ref, "current-cp")
                )
                self.assertEqual(
                    service.record("alice-token", c.ref, self.sample_body(c))["status"],
                    "saved",
                )

    def test_unit_is_complete_case_sensitive_token_and_rejections_do_not_write(self):
        with self.sample(b"Item,A\nMass (mg),42\n") as c:
            service = ProjectStage1LocalObservationService(
                c.service, agent_id="test-agent"
            )
            before = self.counts(c)
            for unit in ("g", "Mg"):
                with (
                    self.subTest(unit=unit),
                    self.assertRaisesRegex(
                        SessionApiError, "local-observation-cell-bytes-or-unit-differs"
                    ),
                ):
                    service.record("alice-token", c.ref, self.sample_body(c, unit))
                self.assertEqual(self.counts(c), before)
            saved = service.record("alice-token", c.ref, self.sample_body(c))
            self.assertEqual(saved["observation"]["cell"]["unit"], "mg")

    def test_csv_lf_crlf_cr_keep_quoted_utf8_duplicate_cell_offsets(self):
        token = '"é, ""x"""'
        for newline in ("\n", "\r\n", "\r"):
            raw = (f"Données,A,B{newline}Masse (mg),{token},{token}{newline}").encode(
                "utf8"
            )
            with self.subTest(newline=repr(newline)), self.sample(raw) as c:
                service = ProjectStage1LocalObservationService(
                    c.service, agent_id="test-agent"
                )
                body = self.sample_body(
                    c, column=3, quote=token, start=raw.rindex(token.encode("utf8"))
                )
                wrong = dict(body, start_byte=raw.index(token.encode("utf8")))
                wrong["end_byte"] = wrong["start_byte"] + len(token.encode("utf8"))
                before = self.counts(c)
                with self.assertRaises(SessionApiError):
                    service.record("alice-token", c.ref, wrong)
                self.assertEqual(self.counts(c), before)
                saved = service.record("alice-token", c.ref, body)
                self.assertEqual(saved["observation"]["cell"]["cell_text"], 'é, "x"')
                self.assertEqual(
                    service.read("alice-token", c.ref, body["key"])["observation"],
                    saved["observation"],
                )

    def setUp(self):
        c = self.case = provided_fixture.ProvidedCandidateTests()
        c.setUp()
        self.addCleanup(c.tearDown)
        c.data = b'Item,Under 25 years\nIncome before taxes (in dollars),"56,107"\n'
        (c.material / "table.csv").write_bytes(c.data)
        c.admit()
        c.service.checkpoint("alice-token", c.ref, c.action_body(c.ref, "cp"))
        self.service = ProjectStage1LocalObservationService(
            c.service, agent_id="test-agent"
        )

    def body(self, key="read-cell"):
        c = self.case
        view = c.intake.read("alice-token", c.ref)
        stage = c.service.read("alice-token", c.ref)
        ledger = c.private_ledger(c.ref)
        source = ledger.candidates()[c.work]["discoveries"][0]["provided"][
            "material_ref"
        ]
        start = c.data.index(b'"56,107"')
        return dict(
            key=key,
            **{k: view[k] for k in ("revision", "input_version", "brief_sha256")},
            ledger_state_sha256=stage["ledger"]["state_sha256"],
            checkpoint_event_id=stage["checkpoint"]["event_id"],
            work_id=c.work,
            version_id=c.version,
            source_ref=source,
            material_sha256=sha(c.data),
            start_byte=start,
            end_byte=start + 8,
            quote='"56,107"',
            row=2,
            column=2,
            unit="dollars",
            note="Agent read one saved cell. No screening or scientific effect inferred.",
        )

    def test_record_reopen_same_key_has_one_receipt_and_no_core_write(self):
        c = self.case
        before = c.service.read("alice-token", c.ref)
        body = self.body()
        first = self.service.record("alice-token", c.ref, body)
        self.assertEqual(first["status"], "saved")
        obs = first["observation"]
        self.assertEqual(
            obs["operator"],
            dict(principal="alice", actor_type="agent", agent_id="test-agent"),
        )
        self.assertEqual(obs["cell"]["cell_text"], "56,107")
        self.assertEqual(obs["source"]["identity_status"], "unverified")
        self.assertFalse(
            obs["human_verification"]
            or obs["claim_evidence_created"]
            or obs["grants_stage2_admission"]
        )
        c.intake.close()
        c.intake = ProjectIntakeService(c.root, authenticate=authenticate)
        c.service = ProjectStage1Service(c.intake)
        self.service = ProjectStage1LocalObservationService(
            c.service, agent_id="test-agent"
        )
        read = self.service.read("alice-token", c.ref, body["key"])
        self.assertEqual(read["observation"], obs)
        again = self.service.record("alice-token", c.ref, body)
        self.assertTrue(again["replayed"])
        self.assertEqual(again["observation"], obs)
        import json

        rows = c.intake.db.execute(
            "SELECT receipt FROM intake_actions WHERE project=?", (c.ref,)
        ).fetchall()
        count = sum(json.loads(row[0])["kind"] == first["kind"] for row in rows)
        self.assertEqual(count, 1)
        after = c.service.read("alice-token", c.ref)
        for field in ("ledger", "checkpoint", "stage1_complete", "later_stages"):
            self.assertEqual(before[field], after[field])

    def test_wrong_project_version_hash_span_and_locator_are_refused(self):
        c = self.case
        for field, value in (
            ("input_version", 99),
            ("brief_sha256", "0" * 64),
            ("version_id", "wrong-version"),
            ("material_sha256", "0" * 64),
            ("quote", "56,108"),
            ("start_byte", 0),
            ("row", 1),
            ("column", 1),
            ("unit", "euros"),
            ("checkpoint_event_id", "e999999"),
        ):
            bad = deepcopy(self.body())
            bad[field] = value
            before = c.intake.read("alice-token", c.ref)["revision"]
            with (
                self.subTest(field=field),
                self.assertRaises((SessionApiError, LedgerError)),
            ):
                self.service.record("alice-token", c.ref, bad)
            self.assertEqual(c.intake.read("alice-token", c.ref)["revision"], before)
        other = c.new(key="second-project")
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", other, self.body())
        with self.assertRaises(SessionApiError):
            self.service.read("bob-token", c.ref, "read-cell")

    def test_request_cannot_claim_human_verification_or_reuse_key_for_other_note(self):
        c = self.case
        bad = self.body()
        bad["actor_type"] = "human"
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", c.ref, bad)
        body = self.body()
        self.service.record("alice-token", c.ref, body)
        changed = deepcopy(body)
        changed["note"] = "A different observation."
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            self.service.record("alice-token", c.ref, changed)

    def test_actual_material_drift_refuses_readback_and_replay(self):
        c = self.case
        body = self.body()
        self.service.record("alice-token", c.ref, body)
        ledger = c.private_ledger(c.ref)
        path = ledger.root / body["source_ref"]["path"]
        path.write_bytes(b"different bytes")
        with self.assertRaises((SessionApiError, LedgerError)):
            self.service.read("alice-token", c.ref, body["key"])
        with self.assertRaises((SessionApiError, LedgerError)):
            self.service.record("alice-token", c.ref, body)

    def test_other_agent_reads_original_author_but_cannot_reuse_write_key(self):
        c = self.case
        body = self.body()
        first = self.service.record("alice-token", c.ref, body)
        other = ProjectStage1LocalObservationService(
            c.service, agent_id="another-agent"
        )
        read = other.read("alice-token", c.ref, body["key"])
        self.assertEqual(read["observation"]["operator"]["agent_id"], "test-agent")
        self.assertEqual(read["observation"], first["observation"])
        with self.assertRaisesRegex(SessionApiError, "idempotency-payload-differs"):
            other.record("alice-token", c.ref, body)
        body["observer_agent_id"] = "forged-agent"
        with self.assertRaises(SessionApiError):
            self.service.record("alice-token", c.ref, body)
