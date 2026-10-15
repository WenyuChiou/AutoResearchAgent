"""Strict saved project-intake bindings; no runtime probe or external execution."""

import atlas_test_paths  # noqa: F401
from copy import deepcopy
import json
from pathlib import Path
import shutil
from unittest.mock import patch

from planned_query_fixture import QueryCase
from research_workspace_native import planned_query_contract as contract
from research_workspace_native.project_intake import ProjectIntakeService
from research_workspace_native.project_stage1 import _basis
from research_workspace_native.session_api import SessionApiError
from stage1_brief.brief import validate_brief
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.store import Ledger
from stage1_retrieval.runtime_identity import verify_identity
from test_workspace_project_intake import compile_body, create_body, submit_body


LEGACY_FIELDS = {
    "project_id",
    "index_sha256",
    "input_version",
    "brief_path",
    "brief_sha256",
    "plan_root",
    "plan_sha256",
    "ledger_root",
    "ledger_manifest_sha256",
    "runtime_sha256",
    "execution_source_sha256",
    "execution_source_root",
    "permit_path",
    "permit_sha256",
    "principals",
    "control_store_path",
    "parent_ledger_root",
    "parent_ledger_sha256",
}
PROJECT_BINDINGS = (
    "registration_kind",
    "project_input_version",
    "project_binding_sha256",
    "bootstrap_permit_sha256",
    "bootstrap_receipt_sha256",
)


class ProjectPlannedQueryContractTests(QueryCase):
    def project_registration(self):
        """Compile an actual integer-version intake, then bind a pinned ledger."""
        self.intake = ProjectIntakeService(
            self.root / "projects",
            authenticate=lambda token: "researcher" if token == "secret" else None,
        )
        self.addCleanup(self.intake.close)
        receipt = self.intake.create(
            "secret",
            create_body("Polyphonic music transcription with scarce annotations"),
        )
        ref = receipt["project_ref"]
        view = self.intake.read("secret", ref)
        self.intake.submit("secret", ref, submit_body(view))
        view = self.intake.read("secret", ref)
        self.intake.compile("secret", ref, compile_body(view))
        binding = self.intake.binding(ref)
        self.actual_binding = binding
        self.actual_project_ref = ref
        self.brief, self.plan = binding["brief_path"], binding["plan_root"]
        self.original_brief_bytes = self.brief.read_bytes()
        self.ledger_root = self.root / "project-query-ledger"
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=lambda pin, **kw: verify_identity(pin),
        ):
            Ledger.create(
                self.ledger_root,
                run_id="offline-project-contract",
                objective=json.loads(self.original_brief_bytes)["original_description"],
                research_hub_pin=self.pin,
            )
        self.ledger = CoverageLedger(self.ledger_root)
        self.ledger.bind_plan(self.plan, backends=["openalex"], limit=3)
        self.ledger.open_round()
        self.parent_ledger = self.root / "project-query-parent"
        shutil.copytree(self.ledger_root, self.parent_ledger)
        basis = _basis(binding)
        # These saved test-only records attest no external execution authority.
        bootstrap = canonical({"kind": "OfflineBootstrapFixture", "binding": basis})
        bootstrap_receipt = canonical(
            {"kind": "OfflineBootstrapReceiptFixture", "permit_sha256": sha(bootstrap)}
        )
        (self.root / "bootstrap-fixture.json").write_bytes(bootstrap)
        (self.root / "bootstrap-receipt-fixture.json").write_bytes(bootstrap_receipt)
        self.item.update(
            registration_kind="project-intake",
            schema_version="1.1.0",
            project_id=binding["project_id"],
            input_version=sha(self.original_brief_bytes),
            project_input_version=binding["input_version"],
            project_binding_sha256=sha(canonical(basis)),
            bootstrap_permit_sha256=sha(bootstrap),
            bootstrap_receipt_sha256=sha(bootstrap_receipt),
            brief_path=str(self.brief),
            brief_sha256=binding["brief_sha256"],
            plan_root=str(self.plan),
            plan_sha256=contract.tree_sha(self.plan),
            ledger_root=str(self.ledger_root),
            ledger_manifest_sha256=sha(
                (self.ledger_root / "run_manifest.json").read_bytes()
            ),
            parent_ledger_root=str(self.parent_ledger),
            parent_ledger_sha256=contract.tree_sha(self.parent_ledger),
        )
        self.permit["schema_version"] = "1.1.0"
        for name in self.permit["binding"]:
            self.permit["binding"][name] = self.item[name]
        self.permit["binding"].update(
            {name: self.item[name] for name in PROJECT_BINDINGS}
        )
        self.permit["planned_ids"] = list(self.ledger.coverage_state().queries)[:2]
        self.write_permit()

    def inspect(self, *, ready=True):
        return contract.inspect_registration("case", self.item, require_ready=ready)

    def test_legacy_exact_fields_and_saved_v10_permit_remain_valid(self):
        self.assertEqual(contract.FIELDS, LEGACY_FIELDS)
        item, permit, state, _ = self.inspect()
        self.assertEqual(set(item), LEGACY_FIELDS)
        self.assertEqual(item["input_version"], "1" * 64)
        self.assertEqual(permit["schema_version"], "1.0.0")
        self.assertTrue(set(permit["planned_ids"]).issubset(state.queries))

    def test_legacy_partial_project_extensions_and_extras_stay_rejected(self):
        original = deepcopy(self.item)
        for name, value in (
            ("schema_version", "1.1.0"),
            ("registration_kind", "project-intake"),
            ("project_input_version", 1),
            ("project_binding_sha256", "a" * 64),
            ("bootstrap_permit_sha256", "b" * 64),
            ("bootstrap_receipt_sha256", "c" * 64),
            ("atlas_spec", {}),
        ):
            with self.subTest(name=name):
                self.item = {**original, name: value}
                with self.assertRaisesRegex(
                    SessionApiError, "query-registration-fields"
                ):
                    self.inspect()
        self.item = original
        del self.item["input_version"]
        with self.assertRaisesRegex(SessionApiError, "query-registration-fields"):
            self.inspect()

    def test_legacy_registration_cannot_use_v11_permit(self):
        self.permit["schema_version"] = "1.1.0"
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-research-permit-differs"):
            self.inspect()

    def test_project_v11_binds_actual_integer_and_unchanged_brief_bytes(self):
        self.project_registration()
        item, permit, state, pin = self.inspect()
        self.assertEqual(self.brief.read_bytes(), self.original_brief_bytes)
        self.assertEqual(item["input_version"], sha(self.original_brief_bytes))
        self.assertEqual(item["input_version"], item["brief_sha256"])
        self.assertIs(type(item["project_input_version"]), int)
        self.assertEqual(
            item["project_input_version"], self.actual_binding["input_version"]
        )
        self.assertEqual(permit["schema_version"], "1.1.0")
        for name in PROJECT_BINDINGS:
            self.assertEqual(permit["binding"][name], item[name])
        self.assertEqual(
            set(item), LEGACY_FIELDS | {"schema_version", *PROJECT_BINDINGS}
        )
        self.assertNotIn("atlas_spec", item)
        self.assertEqual(state.binding["limit"], 3)
        self.assertEqual(pin["timeout_seconds"], 2)
        self.assertFalse(self.actual_binding["execution_authorized"])

    def test_project_integer_rejects_bool_string_float_null_nonpositive(self):
        self.project_registration()
        for value in (True, False, "1", 1.0, None, 0, -1, [], {}):
            with self.subTest(value=value):
                self.item["project_input_version"] = value
                with self.assertRaisesRegex(
                    SessionApiError, "query-project-registration-differs"
                ):
                    self.inspect()

    def test_project_positive_version_must_match_actual_brief(self):
        self.project_registration()
        self.item["project_input_version"] = 2
        self.permit["binding"]["project_input_version"] = 2
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-intake-project-differs"):
            self.inspect()
        self.assertEqual(self.brief.read_bytes(), self.original_brief_bytes)

    def test_project_hash_input_version_is_not_coerced_from_integer(self):
        self.project_registration()
        original = self.item["input_version"]
        for value in (1, True, "1", "a" * 64):
            with self.subTest(value=value):
                self.item["input_version"] = value
                with self.assertRaises(SessionApiError):
                    self.inspect()
        self.item["input_version"] = original
        self.inspect()
        self.assertEqual(self.brief.read_bytes(), self.original_brief_bytes)

    def test_actual_brief_version_rehashed_as_string_cannot_pass_int_binding(self):
        self.project_registration()
        value = json.loads(self.original_brief_bytes)
        value["input_version"] = "1"
        for answer in value["formal_final_count"]["decisions"]:
            answer["input_version"] = "1"
        validate_brief(value, require_confirmed=True)
        mutated = canonical(value)
        self.brief.write_bytes(mutated)
        self.item["input_version"] = self.item["brief_sha256"] = sha(mutated)
        self.permit["binding"].update(
            input_version=sha(mutated), brief_sha256=sha(mutated)
        )
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-intake-project-differs"):
            self.inspect()

    def test_project_hash_fields_reject_wrong_types_and_noncanonical_sha(self):
        self.project_registration()
        original = deepcopy(self.item)
        for name in PROJECT_BINDINGS[2:]:
            for value in (None, 7, True, "a" * 63, "A" * 64, "g" * 64):
                with self.subTest(name=name, value=value):
                    self.item = {**original, name: value}
                    with self.assertRaisesRegex(SessionApiError, "query-pin-required"):
                        self.inspect()

    def test_rehashed_permit_binding_drift_does_not_rebind_registration(self):
        self.project_registration()
        original = deepcopy(self.permit)
        for name, value in (
            ("registration_kind", "atlas"),
            ("project_input_version", 2),
            ("project_input_version", True),
            ("project_input_version", 1.0),
            ("project_binding_sha256", "d" * 64),
            ("bootstrap_permit_sha256", "e" * 64),
            ("bootstrap_receipt_sha256", "f" * 64),
            ("input_version", "0" * 64),
        ):
            with self.subTest(name=name, value=value):
                self.permit = deepcopy(original)
                self.permit["binding"][name] = value
                self.write_permit()
                with self.assertRaisesRegex(
                    SessionApiError, "query-research-permit-differs"
                ):
                    self.inspect()

    def test_project_registration_schema_kind_exact_fields_and_permit_schema(self):
        self.project_registration()
        original = deepcopy(self.item)
        for mutation in (
            {"schema_version": "1.0.0"},
            {"schema_version": "1.1"},
            {"registration_kind": "atlas"},
            {"registration_kind": None},
        ):
            with self.subTest(mutation=mutation):
                self.item = {**original, **mutation}
                with self.assertRaisesRegex(
                    SessionApiError, "query-project-registration-differs"
                ):
                    self.inspect()
        self.item = original
        self.permit["schema_version"] = "1.0.0"
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-research-permit-differs"):
            self.inspect()
        self.item = {**original, "atlas_spec": {}}
        with self.assertRaisesRegex(SessionApiError, "query-registration-fields"):
            self.inspect()
        self.item = deepcopy(original)
        del self.item["bootstrap_receipt_sha256"]
        with self.assertRaisesRegex(SessionApiError, "query-registration-fields"):
            self.inspect()

    def test_project_and_target_id_must_match_real_intake_and_ledger_queries(self):
        self.project_registration()
        self.item["project_id"] = "foreign-project"
        self.permit["binding"]["project_id"] = "foreign-project"
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-intake-project-differs"):
            self.inspect()
        self.item["project_id"] = self.actual_binding["project_id"]
        self.permit["binding"]["project_id"] = self.item["project_id"]
        self.permit["planned_ids"] = ["unplanned-query"]
        self.write_permit()
        with self.assertRaisesRegex(SessionApiError, "query-permit-targets-differ"):
            self.inspect()

    def test_inspection_never_probes_or_creates_query_budget(self):
        self.project_registration()
        calls = []

        def saved_bytes_only(pin, **options):
            self.assertFalse(options.get("probe", False))
            calls.append(options)
            return verify_identity(pin, **options)

        with (
            patch.object(contract, "verify_identity", side_effect=saved_bytes_only),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("backend started"),
            ),
            patch(
                "stage1_retrieval.runtime_identity.inspect_python",
                side_effect=AssertionError("runtime probe"),
            ),
        ):
            self.inspect(ready=False)
            self.inspect()
        self.assertEqual(calls, [{}, {}])
        self.assertEqual(self.children, [])
        self.assertFalse(Path(self.item["control_store_path"]).exists())
        self.assertFalse(Path(self.item["control_store_path"] + ".created").exists())

    def test_saved_project_get_reads_only_and_does_not_check_or_spawn_runtime(self):
        self.project_registration()
        service = self.service()
        before = self.brief.read_bytes()
        with (
            patch(
                "research_workspace_native.planned_queries.inspect_registration",
                side_effect=AssertionError("GET reinspected"),
            ),
            patch.object(
                contract,
                "verify_identity",
                side_effect=AssertionError("GET runtime check"),
            ),
            patch(
                "stage1_retrieval.runner.execute",
                side_effect=AssertionError("GET backend started"),
            ),
            patch(
                "stage1_retrieval.runtime_identity.inspect_python",
                side_effect=AssertionError("GET runtime probe"),
            ),
        ):
            view = service.view("secret", "case")
            with self.assertRaisesRegex(SessionApiError, "query-action-not-found"):
                service.get_action("secret", "case", "unsent")
        self.assertEqual(view["budget"], {"attempts": 0, "seconds": 0})
        self.assertEqual(view["history"], [])
        self.assertEqual(view["input_version"], sha(before))
        self.assertEqual(self.children, [])
        self.assertEqual(self.brief.read_bytes(), before)
