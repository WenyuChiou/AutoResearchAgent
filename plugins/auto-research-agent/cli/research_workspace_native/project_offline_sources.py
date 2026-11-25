"""Explicit same-project local SDK observations; no transport or human review.

The trusted launcher pins the entire configuration. HTTP selects an offered
work, never a filesystem path, executable, grant or fabricated source receipt.
"""

from contextlib import contextmanager
import json
from pathlib import Path

from stage1_deliverable.common import (
    canonical,
    identifier,
    private_output,
    safe_path,
    sha,
)
from .planned_query_contract import raw_file
from .project_stage1_fixed_replay import FixedReplayStage1Service
from .project_stage1_delivery import ProjectStage1DeliveryService
from .project_stage1_records import ProjectStage1RecordsService
from .project_stage1_saved_import import (
    _inspect,
    prepare_saved_sdk_import,
    complete_saved_sdk_import,
)
from .session_api import _check

KIND = "stage1-offline-source"
MODE = "fixed-offline-engineering"


class OfflineSourceRecords(ProjectStage1RecordsService):
    """Keep each immutable configuration's registry separate on cold reopen."""

    def __init__(self, owner):
        self.owner = owner
        super().__init__(
            owner.delivery,
            materials_root=owner.root,
            mutation_guard=owner.records_guard,
        )

    def _basis(self, context):
        self.owner._context(context[0], context[1]["project_ref"])
        return dict(
            super()._basis(context), offline_config_sha256=self.owner.inputs.sha256
        )


class OfflineSourceInputs:
    def __init__(self, path, expected_sha256):
        self.path, self.sha256 = Path(path), expected_sha256
        self.document = self.load()

    def load(self):
        def pairs(items):
            result = {}
            for key, value in items:
                _check(key not in result, "offline-source-duplicate-field")
                result[key] = value
            return result

        value = json.loads(
            raw_file(self.path, self.sha256, 262144), object_pairs_hook=pairs
        )
        _check(
            type(value) is dict
            and set(value)
            == {
                "kind",
                "schema_version",
                "scope",
                "project_ref",
                "input_version",
                "brief_sha256",
                "plan_manifest_sha256",
                "materials_root",
                "runtime_sha256",
                "sources",
            },
            "offline-source-config-fields",
        )
        _check(
            value["kind"] == "Stage1OfflineSavedSources"
            and value["schema_version"] == "1.0.0"
            and value["scope"] == "authored-engineering-only",
            "offline-source-engineering-admission-required",
        )
        _check(
            type(value["input_version"]) is int and value["input_version"] > 0,
            "offline-source-integer-input-required",
        )
        identifier(value["project_ref"])
        for name in ("brief_sha256", "plan_manifest_sha256", "runtime_sha256"):
            _check(
                type(value[name]) is str
                and len(value[name]) == 64
                and all(c in "0123456789abcdef" for c in value[name]),
                "offline-source-config-hash",
            )
        root = Path(value["materials_root"])
        _check(root.is_absolute(), "offline-source-absolute-root-required")
        root = private_output(root)
        _check(root.is_dir(), "offline-source-materials-required")
        rows = value["sources"]
        _check(type(rows) is list and 0 < len(rows) <= 32, "offline-source-input-bound")
        seen = set()
        for row in rows:
            _check(
                type(row) is dict
                and set(row)
                == {"work_ref", "version_id", "result_path", "result_sha256"},
                "offline-source-entry-fields",
            )
            identifier(row["work_ref"])
            identifier(row["version_id"])
            _check(row["work_ref"] not in seen, "offline-source-ambiguous-work")
            seen.add(row["work_ref"])
            path = safe_path(root, row["result_path"])
            _inspect(root, path, row["result_sha256"])
        return value


class ProjectOfflineSourceService:
    """Separate local mutation owner, deliberately not a live query service."""

    def __init__(self, stage1, inputs):
        _check(
            type(stage1) is FixedReplayStage1Service
            and type(inputs) is OfflineSourceInputs,
            "offline-source-typed-owner-required",
        )
        _check(
            getattr(stage1, "query_service", None) is None
            and stage1.query_runner is None,
            "offline-source-live-owner-forbidden",
        )
        self.stage1, self.intake, self.inputs = stage1, stage1.intake, inputs
        self.root = private_output(Path(inputs.document["materials_root"]))
        _check(
            not self.root.is_relative_to(self.intake.root)
            and not self.intake.root.is_relative_to(self.root),
            "offline-source-storage-overlap",
        )
        self.delivery = ProjectStage1DeliveryService(stage1)
        self.records = OfflineSourceRecords(self)
        self.runner = None
        self.closed = False

    def _context(self, principal, ref):
        _check(not self.closed, "offline-source-owner-closed")
        config = self.inputs.load()
        _check(ref == config["project_ref"], "offline-source-project-differs")
        state = self.intake._load(principal, ref)
        binding = self.intake.binding(ref)
        _check(
            all(
                type(config[k]) is type(binding[k]) and config[k] == binding[k]
                for k in ("input_version", "brief_sha256", "plan_manifest_sha256")
            ),
            "offline-source-input-differs",
        )
        _check(
            not any(binding["settings"]["consent"].values())
            and all(
                type(v) is int and v == 0
                for v in binding["settings"]["budgets"].values()
            ),
            "offline-source-zero-research-envelope-required",
        )
        fixed = self.stage1.fixed_inputs.load()
        _check(
            all(
                fixed[k] == config[k] and type(fixed[k]) is type(config[k])
                for k in (
                    "project_ref",
                    "input_version",
                    "brief_sha256",
                    "plan_manifest_sha256",
                )
            ),
            "offline-source-query-binding-differs",
        )
        _check(
            getattr(self.stage1, "query_service", None) is None
            and self.stage1.query_runner is None,
            "offline-source-live-owner-forbidden",
        )
        run, ledger, report = self.stage1._ledger(state, binding)
        _check(
            not run.get("query_owned") and report["valid"] is True,
            "offline-source-local-ledger-required",
        )
        return state, binding, run, ledger, report, config

    def _actions(self, principal, ref, *, all_configs=False):
        rows = [
            json.loads(r[0])
            for r in self.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                (principal, ref),
            ).fetchall()
            if json.loads(r[0])["kind"] == KIND
        ]
        return [
            r
            for r in rows
            if all_configs
            or r["request"].get("offline_config_sha256") == self.inputs.sha256
        ]

    def _registered(self, ref, ledger_state, source_id):
        context = self.records._context(ref, ledger_state)
        found = [
            r
            for r in self.records._entries(context)
            if r["ref"].startswith("stage1-source-registry-")
            and r["payload"]["source_id"] == source_id
        ]
        _check(len(found) <= 1, "offline-source-registry-ambiguous")
        return found[0]["ref"] if found else None

    @contextmanager
    def records_guard(self, run, ledger, report):
        with self.intake._lock:
            ref = self.inputs.document["project_ref"]
            principal = self.intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (ref,)
            ).fetchone()
            _check(principal is not None, "offline-source-project-unavailable")

            def check():
                current = self._context(principal[0], ref)
                _check(
                    current[2] == run
                    and current[3].root == ledger.root
                    and current[4]["state_sha256"] == report["state_sha256"],
                    "offline-source-frontier-changed",
                )
                from .project_stage1_coverage import unresolved

                _check(
                    not unresolved(
                        self.stage1, ref, principal[0], current[0]["input_version"]
                    ),
                    "offline-source-outcome-unobserved",
                )

            check()
            yield check
            check()

    def read(self, credential, ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state, binding, _, ledger, _, config = self._context(principal, ref)
            actions = self._actions(principal, ref)
            rows = []
            for item in config["sources"]:
                related = [
                    r
                    for r in actions
                    if r["request"].get("work_ref") == item["work_ref"]
                ]
                saved = related[-1] if related else None
                registry = (
                    self._registered(ref, ledger.state_hash(), saved["source_id"])
                    if saved and saved["status"] == "saved"
                    else None
                )
                rows.append(
                    dict(
                        work_ref=item["work_ref"],
                        version_id=item["version_id"],
                        status="source-registered"
                        if registry
                        else (
                            "registration-unobserved"
                            if saved and saved["status"] == "saved"
                            else saved["status"]
                            if saved
                            else "ready-for-explicit-local-import"
                        ),
                        registry_ref=registry,
                        receipt=self.intake._receipt(saved) if saved else None,
                    )
                )
            return dict(
                kind="ProjectStage1OfflineSources",
                schema_version="1.0.0",
                mode=MODE,
                config_sha256=self.inputs.sha256,
                project_ref=ref,
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=binding["brief_sha256"],
                ledger_state_sha256=ledger.state_hash(),
                sources=rows,
                historical_actions=[
                    self.intake._receipt(r)
                    for r in self._actions(principal, ref, all_configs=True)
                    if r["request"].get("offline_config_sha256") != self.inputs.sha256
                ],
                execution_authorized=False,
                source_acquisition_calls=0,
                model_calls=0,
                scientific_acceptance=False,
                automatic_retry=False,
            )

    history = read

    def offers(self, credential, ref, work_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state, binding, _, ledger, _, config = self._context(principal, ref)
            row = next(
                (r for r in config["sources"] if r["work_ref"] == work_ref), None
            )
            _check(row is not None, "offline-source-work-not-admitted")
            candidate = ledger.candidates().get(work_ref)
            _check(
                candidate is not None
                and row["version_id"] in candidate["version_ids"]
                and candidate["discoveries"][-1]["version_id"] == row["version_id"],
                "offline-source-work-version-differs",
            )
            _, _, sdk, _, _, _ = _inspect(
                self.root,
                safe_path(self.root, row["result_path"]),
                row["result_sha256"],
            )
            metadata = candidate["discoveries"][-1]["record"]
            _check(
                sdk["expected_identity"]["title"] == metadata["title"]
                and (
                    not metadata.get("doi")
                    or sdk["expected_identity"].get("doi") == metadata["doi"]
                ),
                "offline-source-candidate-identity-differs",
            )
            digest = sha(
                canonical(
                    dict(
                        config_sha256=self.inputs.sha256,
                        work_ref=work_ref,
                        version_id=row["version_id"],
                        candidate_event_id=candidate["event_id"],
                        ledger_state_sha256=ledger.state_hash(),
                    )
                )
            )
            return dict(
                mode=MODE,
                config_sha256=self.inputs.sha256,
                project_ref=ref,
                revision=state["revision"],
                input_version=state["input_version"],
                brief_sha256=binding["brief_sha256"],
                ledger_state_sha256=ledger.state_hash(),
                work_ref=work_ref,
                version_id=row["version_id"],
                offer_sha256=digest,
                execution_authorized=False,
            )

    def authorize(self, *args, **kwargs):
        _check(False, "offline-source-live-authorization-forbidden")

    def execute(self, credential, ref, body, *, check_deadline=None):
        principal = self.intake._principal(credential)
        _check(
            type(body) is dict
            and set(body)
            == {
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "confirmed",
                "ledger_state_sha256",
                "work_ref",
                "offer_sha256",
            },
            "offline-source-action-fields",
            400,
        )
        identifier(body["key"])
        body = dict(body, offline_config_sha256=self.inputs.sha256)
        with self.intake._lock:
            context = self._context(principal, ref)
            prior = next(
                (
                    r
                    for r in self._actions(principal, ref, all_configs=True)
                    if r["key"] == body["key"]
                ),
                None,
            )
            if prior:
                semantic = {k: v for k, v in body.items() if k != "revision"}
                _check(prior["request"] == semantic, "idempotency-payload-differs")
                return self.intake._receipt(prior, replayed=True)
            _check(
                not any(
                    r["status"] in {"intent-recorded", "execution-unknown"}
                    for r in self._actions(principal, ref, all_configs=True)
                ),
                "offline-source-outcome-unobserved",
            )
            _check(
                not any(
                    r["request"].get("work_ref") == body["work_ref"]
                    for r in self._actions(principal, ref)
                ),
                "offline-source-existing-action-reopen-required",
            )
            offer = self.offers(credential, ref, body["work_ref"])
            _check(
                body["offer_sha256"] == offer["offer_sha256"],
                "offline-source-offer-stale",
            )
            row = next(
                r for r in context[5]["sources"] if r["work_ref"] == body["work_ref"]
            )
            result_path = safe_path(self.root, row["result_path"])

            def check():
                fresh = self._context(principal, ref)
                _check(
                    fresh[2] == context[2] and fresh[5] == context[5],
                    "offline-source-binding-changed",
                )
                if check_deadline is not None:
                    check_deadline()

            proposed = prepare_saved_sdk_import(
                materials_root=self.root,
                result_path=result_path,
                expected_result_sha256=row["result_sha256"],
                runtime_sha256=context[5]["runtime_sha256"],
                check_current=check,
            )

            def produce(_state, _run, ledger, _digest, actor):
                check()
                source = ledger.start_source(
                    work_id=row["work_ref"],
                    version_id=row["version_id"],
                    source_uri=proposed["source_uri"],
                    tool=proposed["tool"],
                    request=proposed["request"],
                    actor=actor,
                    reason="Explicit local authored-engineering SDK observation; not human source review.",
                )
                result = complete_saved_sdk_import(
                    ledger,
                    materials_root=self.root,
                    source_id=source,
                    expected_start=ledger.event(source, "SourceReadStarted"),
                    result_path=result_path,
                    expected_result_sha256=row["result_sha256"],
                    runtime_sha256=context[5]["runtime_sha256"],
                    reason="Original local SDK bytes; acquisition and scientific identity unverified.",
                    check_current=check,
                )
                return dict(
                    result,
                    mode=MODE,
                    config_sha256=self.inputs.sha256,
                    work_ref=row["work_ref"],
                    version_id=row["version_id"],
                    actor=actor,
                    actor_role="engineering-operator",
                    execution_authorized=False,
                    scientific_acceptance=False,
                    stage1_complete=False,
                )

            receipt = self.stage1._mutate(
                credential,
                ref,
                body,
                KIND,
                produce,
                fields={"work_ref", "offer_sha256", "offline_config_sha256"},
                check_deadline=check_deadline,
            )
            if receipt["status"] != "saved":
                return receipt
            # Separate existing records transaction; reads never repair a missing registration.
            self.records.register_source(
                ref,
                source_id=receipt["source_id"],
                result_path=result_path,
                expected_result_sha256=row["result_sha256"],
                access_note="Authored engineering fixture; local SDK import, no verified HTTP acquisition or scientific review.",
                expected_ledger_state_sha256=receipt["ledger_state_sha256"],
                check_current=check,
            )
            return receipt

    def close(self):
        with self.intake._lock:
            self.closed = True
