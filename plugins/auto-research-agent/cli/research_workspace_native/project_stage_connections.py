"""Host-owned, durable read bindings. A connection is never an execution grant."""

from collections.abc import Mapping
from copy import deepcopy

from stage1_deliverable.common import safe_path, sha
from stage1_ledger.journal import canonical, decode, write_new
from stage2_common import canonical_hash
from .project_stage2 import MAX_OFFERS, _public, _raw
from .project_intake import MAX_ACTIONS
from .session_api import SessionApiError, _check


CONTROLLER_STAGE = "stage2-controller"


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
        return self._resolve(ref, stage, current=True)

    def _resolve(self, ref, stage, *, current):
        with self.intake._lock:
            principal = self.intake._principal(self.credential)
            try:
                state = self.intake._load(principal, ref)
                saved = state.get("stage_connections", {}).get(stage)
            except (ValueError, KeyError, TypeError, AttributeError) as error:
                raise SessionApiError("stage-connection-source-invalid", 409) from error
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
                    and (
                        not current
                        or canonical_hash(record["identity"])
                        == canonical_hash(self._identity(ref))
                    ),
                    "stage-connection-project-stale",
                )
                action = self.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (principal, ref, saved["key"]),
                ).fetchone()
                receipt = (
                    None
                    if action is None
                    else decode(action[0].encode(), "connection action")
                )
                _check(
                    receipt is not None
                    and receipt["status"] == "saved"
                    and receipt["kind"] == "stage2-record-connection"
                    and receipt["project_ref"] == ref
                    and receipt["key"] == saved["key"]
                    and receipt["request"]["connection_sha256"] == saved["sha256"]
                    and receipt["connection_id"] == saved["sha256"],
                    "stage-connection-receipt-differs",
                )
                _check(
                    any(
                        event[0] == action[0]
                        for event in self.intake.db.execute(
                            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
                            (ref, "stage2-record-connection-saved"),
                        )
                    ),
                    "stage-connection-saved-event-missing",
                )
                return {
                    **record,
                    "connection_id": saved["sha256"],
                    "receipt_id": saved["key"],
                }
            except SessionApiError:
                raise
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SessionApiError("stage-connection-source-invalid", 409) from error

    def record(
        self,
        ref,
        stage,
        row,
        *,
        derived_from,
        check_deadline=None,
        offer=None,
        expected_identity=None,
        expected_revision=None,
        request_key=None,
        maximum_projects=None,
    ):
        """Trusted producer only; callers must verify the source before recording."""
        _check(
            stage in {"stage2-input", "stage2-selection", CONTROLLER_STAGE},
            "stage-connection-kind",
        )
        with self.intake._lock:
            identity = self._identity(ref)
            principal = self.intake._principal(self.credential)
            state = self.intake._load(principal, ref)
            _check(
                request_key is not None
                or expected_revision is None
                or state["revision"] == expected_revision,
                "stage-connection-project-stale",
            )
            _check(
                expected_identity is None
                or canonical_hash(identity) == canonical_hash(expected_identity),
                "stage-connection-project-stale",
            )
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
            previous = self._resolve(ref, stage, current=False)
            if previous is not None and canonical_hash(
                previous["identity"]
            ) == canonical_hash(identity):
                _check(
                    previous["connection_id"] == digest,
                    "stage-connection-source-differs",
                )
                if offer is not None:
                    principal = self.intake._principal(self.credential)
                    state = self.intake._load(principal, ref)
                    _check(
                        canonical_hash(
                            state.get("stage2_offers", {}).get(offer["offer_ref"])
                        )
                        == canonical_hash(offer),
                        "stage-connection-offer-differs",
                    )
                if request_key is not None and request_key != previous["receipt_id"]:
                    _check(
                        self.intake.db.execute(
                            "SELECT 1 FROM intake_actions WHERE principal=? AND project=? AND key=?",
                            (principal, ref, request_key),
                        ).fetchone()
                        is None,
                        "idempotency-payload-differs",
                    )
                return previous
            _check(
                expected_revision is None or state["revision"] == expected_revision,
                "stage-connection-project-stale",
            )
            relative = "connection-" + digest[:32] + ".json"
            # A failed local publication with no output can be attempted on a
            # new journal key. Never erase its failure or retry an unknown write.
            for attempt in range(MAX_ACTIONS + 1):
                if request_key is not None:
                    key = request_key
                    break
                key = "connection-" + digest + ("-" + str(attempt) if attempt else "")
                old = self.intake.db.execute(
                    "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                    (principal, ref, key),
                ).fetchone()
                if old is None:
                    break
                receipt = decode(old[0].encode(), "connection attempt")
                _check(
                    receipt["status"] == "failed"
                    and "failure_phase" not in receipt
                    and receipt.get("error") == "session-deadline-exceeded"
                    and receipt["request"]["connection_sha256"] == digest
                    and any(
                        event[0] == old[0]
                        for event in self.intake.db.execute(
                            "SELECT payload FROM intake_events WHERE project=? AND kind=?",
                            (ref, "stage2-record-connection-failed"),
                        )
                    )
                    and not self.intake._path(ref, relative).exists(),
                    "stage-connection-write-outcome-unobserved",
                )
            else:
                raise SessionApiError("stage-connection-recovery-bound-exceeded", 409)
            body = dict(
                key=key,
                revision=state["revision"]
                if expected_revision is None
                else expected_revision,
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
                current.setdefault("stage_connection_history", []).append(digest)
                if offer is not None:
                    offers = current.setdefault("stage2_offers", {})
                    _check(len(offers) < MAX_OFFERS, "stage2-offer-bound-exceeded")
                    offers[offer["offer_ref"]] = deepcopy(offer)
                return {"connection_id": digest, "execution_authorized": False}

            def reserve(_, __, ___):
                _check(
                    canonical_hash(self._identity(ref)) == canonical_hash(identity),
                    "stage-connection-project-stale",
                )
                if maximum_projects is not None:
                    n = self.intake.db.execute(
                        """SELECT COUNT(*) FROM intake_projects
                        WHERE principal=? AND ref<>?
                        AND json_type(state, '$.stage_connections."stage2-controller"')
                            IS NOT NULL""",
                        (principal, ref),
                    ).fetchone()[0]
                    _check(n < maximum_projects, "stage2-controller-profile-limit")

            receipt = self.intake._perform(
                principal,
                ref,
                "stage2-record-connection",
                body,
                work,
                check_deadline=check_deadline,
                reserve=reserve,
            )
            _check(
                receipt["status"] == "saved",
                "stage-connection-write-outcome-unobserved",
            )
            return self.resolve(ref, stage)

    def record_selection(self, ref, binding, *, check_deadline=None):
        """Accept only a verified existing delivery of this activated project."""
        from .project_stage2_selection_view import ProjectStage2SelectionView

        with self.intake._lock:
            view = ProjectStage2SelectionView(self.intake, {ref: binding})
            project = self.intake.read(self.credential, ref)
            _check(
                type(project["input_version"]) is type(binding["input_version"])
                and project["input_version"] == binding["input_version"]
                and project["brief_sha256"] == binding["brief_sha256"],
                "stage2-selection-project-stale",
            )
            expected_identity = self._identity(ref)
            # The normal service's direction mixin may already own a read
            # scope. Do not cache a pre-publication project revision there.
            verified, _ = view._verify_current_context(self.credential, ref)
            if check_deadline is not None:
                check_deadline()
            return self.record(
                ref,
                "stage2-selection",
                binding,
                derived_from={
                    "delivery_manifest_sha256": binding["delivery_manifest_sha256"]
                },
                check_deadline=check_deadline,
                expected_identity=expected_identity,
                expected_revision=verified[0]["revision"],
            )


class BindingTable(Mapping):
    """Static compatibility plus persisted bindings; overlap is an error."""

    def __init__(self, static, store, controllers=None):
        from .project_stage2_selection_view import validate_selection_binding

        self.static = deepcopy(static)
        self.store = store
        self.controllers = dict(controllers or {})
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

    def __contains__(self, ref):
        # Wiki membership is a discovery hint, not a verified binding. Only
        # read() may receive a completed result; direct writes still need a row.
        return ref in iter(self)

    def receive_completed(self, ref, *, check_deadline=None):
        # Finish any local registration before entering the read-only view cache.
        if check_deadline is not None:
            check_deadline()
        dynamic = self.store.resolve(ref, "stage2-selection")
        _check(
            not (ref in self.static and dynamic is not None),
            "selection-bindings-overlap",
        )
        if ref in self.static or dynamic is not None:
            return
        driver = self.controllers.get(ref)
        if driver is not None:
            try:
                binding = _completed_binding(driver, self.store.credential, ref)
            except SessionApiError:
                raise
            except (OSError, ValueError, KeyError, TypeError) as error:
                raise SessionApiError("stage2-selection-source-invalid", 409) from error
            if binding is not None:
                self.store.record_selection(ref, binding, check_deadline=check_deadline)

    def __iter__(self):
        with self.store.intake._lock:
            principal = self.store.intake._principal(self.store.credential)
            refs = set(self.static)
            for ref in self.controllers:
                try:
                    driver = self.controllers[ref]
                    if safe_path(driver.records, "result.json").is_file():
                        refs.add(ref)
                except (OSError, ValueError):
                    # Discovery cannot vouch for this row. Explicit access
                    # still performs strict verification and returns its error.
                    continue
            for row in self.store.intake.db.execute(
                "SELECT ref FROM intake_projects WHERE principal=?", (principal,)
            ).fetchall():
                try:
                    state = self.store.intake._load(principal, row[0])
                    if "stage2-selection" in state.get("stage_connections", {}):
                        refs.add(row[0])
                except (
                    SessionApiError,
                    OSError,
                    ValueError,
                    KeyError,
                    TypeError,
                    AttributeError,
                ):
                    continue
            return iter(sorted(refs))

    def __len__(self):
        return sum(1 for _ in self)


def register_current(
    service, ref, *, credential, delivery, stage1=None, check_deadline=None
):
    """Consume #524's verification while its source locks are still held."""
    from .project_stage2_current_evidence import current_evidence

    intake = service.intake
    _check(delivery.intake is intake, "stage-connection-store-differs")
    with intake._lock:
        project = intake.read(credential, ref)
        if stage1 is None:
            stage1 = delivery.stage1.read(credential, ref)

        def receive(evidence, binding, bound):
            _check(
                type(evidence["input_version"]) is int,
                "stage-connection-integer-version-required",
            )
            source = evidence["source"]
            root = intake._path(ref, "s2r-" + evidence["source_descriptor_sha256"][:32])
            row = {
                key: evidence[key]
                for key in ("packet_id", "packet_sha256", "receipt_sha256")
            }
            offer = _current_offer(binding, bound, evidence, root)
            row["offer_ref"] = offer["offer_ref"]
            expected = {
                key: binding[key]
                for key in (
                    "project_id",
                    "input_version",
                    "brief_sha256",
                    "plan_manifest_sha256",
                )
            }
            expected["settings_sha256"] = canonical_hash(binding["settings"])
            record = ConnectionStore(intake, credential).record(
                ref,
                "stage2-input",
                row,
                derived_from=source,
                check_deadline=check_deadline,
                offer=offer,
                expected_identity=expected,
                expected_revision=evidence["revision"],
            )
            revision = intake.read(credential, ref)["revision"]
            return dict(
                evidence,
                revision=revision,
                stage1_atlas_url=(
                    f"/api/projects/{ref}/stage1/atlas/{source['input_version']}/"
                    f"{revision}/{source['artifact_ref']}/{source['manifest_sha256']}"
                ),
                connection_id=record["connection_id"],
                receipt_id=record["receipt_id"],
                activation_allowed=False,
                offer=_public(offer),
            )

        result = current_evidence(
            delivery,
            credential,
            stage1,
            project,
            check_deadline=check_deadline,
            on_received=receive,
        )
        if result["status"] != "received":
            return dict(result, connection_id=None, receipt_id=None)
        return result


def _current_offer(binding, bound, evidence, root):
    """An already verified native input is visible, but cannot activate research."""
    resources = safe_path(root, "resources.txt")
    resources_sha256 = sha(binding["settings"]["resource_envelope"].encode("utf-8"))
    _raw(resources, resources_sha256, maximum=65536)
    inputs = dict(
        deliverable_dir=str(bound["deliverable_dir"]),
        manifest_sha256=bound["manifest_sha256"],
        handoff_path=str(bound["handoff_path"]),
        handoff_sha256=bound["handoff_sha256"],
        resources_path=str(resources),
        resources_sha256=resources_sha256,
    )
    basis = {
        key: binding[key]
        for key in (
            "project_id",
            "input_version",
            "brief_sha256",
            "plan_manifest_sha256",
        )
    }
    basis.update(
        stage1_manifest_sha256=bound["manifest_sha256"],
        stage1_handoff_sha256=bound["handoff_sha256"],
        resources_sha256=inputs["resources_sha256"],
        settings_sha256=canonical_hash(binding["settings"]),
        policy_ref={
            "route": "stage2-current-project/read-only",
            "packet_profile": "scientific-v3",
            "execution_authorized": False,
        },
    )
    digest = canonical_hash(basis)
    return dict(
        basis,
        offer_ref="stage2-" + digest[:32],
        offer_sha256=digest,
        inputs=inputs,
        work_count=evidence["source_count"],
        status="receiving-only",
    )


def _completed_binding(driver, credential, ref):
    """Read an existing controller result; never execute or restore a job."""
    from .project_stage2_controller import _read

    result_path = safe_path(driver.records, "result.json")
    if not result_path.is_file():
        return None
    intent = _read(safe_path(driver.records, "intent.json"))
    driver._same(intent, credential, ref, intent["key"])
    verified = driver._verify_result(_read(result_path), intent)
    delivery = verified["delivery"]
    if delivery is None:
        return None
    current = driver.service.binding(ref)
    return dict(
        input_version=current["input_version"],
        brief_sha256=current["brief_sha256"],
        workflow_root=str(current["workflow_root"]),
        delivery_root=str(delivery["root"]),
        delivery_manifest_sha256=delivery["manifest"]["manifest_sha256"],
    )
