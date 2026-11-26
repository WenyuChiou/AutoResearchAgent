"""Host-owned, durable read bindings. A connection is never an execution grant."""

from collections.abc import Mapping
from contextlib import nullcontext
from copy import deepcopy

from stage1_deliverable.common import safe_path, sha
from stage1_ledger.journal import canonical, decode, write_new
from stage2_common import canonical_hash
from .project_stage2 import _raw
from .session_api import SessionApiError, _check


class ConnectionStore:
    """Keep project-local connection receipts in the existing intake journal."""

    def __init__(self, intake, credential):
        self.intake = intake
        self.credential = credential

    def _identity(self, ref):
        self.intake.read(self.credential, ref)
        binding = self.intake.binding(ref)
        return {
            "project_id": binding["project_id"],
            "input_version": binding["input_version"],
            "brief_sha256": binding["brief_sha256"],
            "plan_manifest_sha256": binding["plan_manifest_sha256"],
            "settings_sha256": canonical_hash(binding["settings"]),
        }

    def resolve(self, ref, stage):
        with self.intake._lock:
            principal = self.intake._principal(self.credential)
            state = self.intake._load(principal, ref)
            saved = state.get("stage_connections", {}).get(stage)
            if saved is None:
                return None
            try:
                record = decode(
                    _raw(self.intake._path(ref, saved["path"]), saved["sha256"]),
                    "project connection",
                )
                _check(
                    record["project_ref"] == ref
                    and record["stage"] == stage
                    and record["execution_authorized"] is False
                    and canonical_hash(record["identity"])
                    == canonical_hash(self._identity(ref)),
                    "stage-connection-project-stale",
                )
                return {
                    **record,
                    "connection_id": saved["sha256"],
                    "receipt_id": saved["key"],
                }
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SessionApiError("stage-connection-source-invalid", 409) from error

    def record(self, ref, stage, row, *, derived_from, check_deadline=None):
        """Trusted producer only; callers must verify the source before recording."""
        _check(stage in {"stage2-input", "stage2-selection"}, "stage-connection-kind")
        with self.intake._lock:
            identity = self._identity(ref)
            record = dict(
                kind="ProjectStageConnection",
                schema_version="1.0.0",
                project_ref=ref,
                stage=stage,
                identity=identity,
                derived_from=deepcopy(derived_from),
                row=deepcopy(row),
                execution_authorized=False,
            )
            raw = canonical(record)
            digest = sha(raw)
            previous = self.resolve(ref, stage)
            if previous is not None:
                _check(
                    previous["connection_id"] == digest,
                    "stage-connection-source-differs",
                )
                return previous
            principal = self.intake._principal(self.credential)
            state = self.intake._load(principal, ref)
            key = "connection-" + digest
            relative = "connection-" + digest[:32] + ".json"
            body = dict(
                key=key,
                revision=state["revision"],
                input_version=identity["input_version"],
                brief_sha256=identity["brief_sha256"],
                connection_sha256=digest,
            )

            def work(current, _, __):
                path = self.intake._path(ref, relative)
                if path.exists():
                    _check(_raw(path, digest) == raw, "stage-connection-bytes-differ")
                else:
                    write_new(path, raw)
                current.setdefault("stage_connections", {})[stage] = {
                    "path": relative,
                    "sha256": digest,
                    "key": key,
                }
                return {"connection_id": digest, "execution_authorized": False}

            receipt = self.intake._perform(
                principal,
                ref,
                "stage2-record-connection",
                body,
                work,
                check_deadline=check_deadline,
            )
            _check(
                receipt["status"] == "saved",
                "stage-connection-write-outcome-unobserved",
            )
            return self.resolve(ref, stage)

    def record_selection(self, ref, binding):
        """Accept only a verified existing delivery of this activated project."""
        from .project_stage2_selection_view import ProjectStage2SelectionView

        with self.intake._lock:
            view = ProjectStage2SelectionView(self.intake, {ref: binding})
            view._current(self.credential, ref)
            return self.record(
                ref,
                "stage2-selection",
                binding,
                derived_from={
                    "delivery_manifest_sha256": binding["delivery_manifest_sha256"]
                },
            )


class BindingTable(Mapping):
    """Static compatibility plus persisted bindings; overlap is an error."""

    def __init__(self, static, store):
        from .project_stage2_selection_view import validate_selection_binding

        self.static = deepcopy(static)
        self.store = store
        for ref, binding in self.static.items():
            validate_selection_binding(ref, binding)

    def __getitem__(self, ref):
        dynamic = self.store.resolve(ref, "stage2-selection")
        _check(
            not (ref in self.static and dynamic is not None),
            "selection-bindings-overlap",
        )
        if dynamic is not None:
            return deepcopy(dynamic["row"])
        if ref in self.static:
            return deepcopy(self.static[ref])
        raise KeyError(ref)

    def __iter__(self):
        with self.store.intake._lock:
            principal = self.store.intake._principal(self.store.credential)
            refs = set(self.static)
            for row in self.store.intake.db.execute(
                "SELECT ref FROM intake_projects WHERE principal=?", (principal,)
            ).fetchall():
                state = self.store.intake._load(principal, row[0])
                if "stage2-selection" in state.get("stage_connections", {}):
                    refs.add(row[0])
            return iter(sorted(refs))

    def __len__(self):
        return sum(1 for _ in self)


def register_current(
    service, ref, *, credential, delivery, stage1=None, check_deadline=None
):
    """Derive a read connection from #524's freshly verified native package."""
    from .project_stage2_current_evidence import current_evidence

    intake = service.intake
    _check(delivery.intake is intake, "stage-connection-store-differs")
    with intake._lock:
        # Public identity is re-read; callers cannot select a physical package.
        project = intake.read(credential, ref)
        if stage1 is None:
            stage1 = delivery.stage1.read(credential, ref)
        evidence = current_evidence(
            delivery, credential, stage1, project, check_deadline=check_deadline
        )
        if evidence["status"] != "received":
            return {**evidence, "connection_id": None, "receipt_id": None}
        _check(
            type(evidence["input_version"]) is int,
            "stage-connection-integer-version-required",
        )
        store = ConnectionStore(intake, credential)
        source = evidence["source"]
        # Reopen the actual marker; never persist paths or identities from HTTP.
        root = intake._path(ref, "s2r-" + evidence["source_descriptor_sha256"][:32])
        marker = decode(
            _raw(safe_path(root, "receipt.json"), evidence["receipt_sha256"]),
            "receiver",
        )
        _check(
            canonical_hash(marker["source"]) == canonical_hash(source),
            "stage-connection-source-differs",
        )
        row = {
            key: evidence[key]
            for key in ("packet_id", "packet_sha256", "receipt_sha256")
        }
        _, _, _, run, ledger, report = delivery._saved_context(ref)
        guard = nullcontext(lambda: None)
        if run.get("query_owned"):
            owner = getattr(delivery.stage1, "query_service", None)
            factory = getattr(owner, "saved_records_guard", None)
            _check(callable(factory), "stage2-current-evidence-owner-unavailable")
            guard = factory(run, ledger, report)
        with guard as check_owner, ledger.writing(repair=False):
            bound = delivery.binding(ref)
            _check(
                all(
                    bound[key] == source[key]
                    for key in (
                        "artifact_ref",
                        "run_ref",
                        "checkpoint_event_id",
                        "ledger_state_sha256",
                        "manifest_sha256",
                        "handoff_sha256",
                        "records_sha256",
                    )
                ),
                "stage-connection-source-differs",
            )
            check_owner()
            if check_deadline is not None:
                check_deadline()
            record = store.record(
                ref,
                "stage2-input",
                row,
                derived_from=source,
                check_deadline=check_deadline,
            )
        revision = intake.read(credential, ref)["revision"]
        evidence.update(
            revision=revision,
            stage1_atlas_url=(
                f"/api/projects/{ref}/stage1/atlas/{source['input_version']}/"
                f"{revision}/{source['artifact_ref']}/{source['manifest_sha256']}"
            ),
        )
        return {
            **evidence,
            "connection_id": record["connection_id"],
            "receipt_id": record["receipt_id"],
            "activation_allowed": False,
        }
