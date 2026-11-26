"""Reopen runtime controller connections through the saved native evidence."""

from collections.abc import Mapping
import json

from stage1_deliverable.common import private_output, safe_path, sha
from stage2_common import canonical_hash
from .project_stage2_controller_config import _document, load_stage2_controller
from .project_stage2_current_evidence import current_evidence
from .project_stage_connections import CONTROLLER_STAGE, ConnectionStore
from .session_api import SessionApiError, _check


class Stage2ControllerConnections(Mapping):
    def __init__(self, host, profile):
        self.host, self.profile = host, profile
        self.static = host.project_stage2_controllers
        self.store = ConnectionStore(host.projects, host.credential)

    def _resolve(self, ref):
        saved = self.store.resolve(ref, CONTROLLER_STAGE)
        _check(
            ref not in self.static or saved is None,
            "stage2-controller-bindings-overlap",
        )
        return saved

    def _source(self, credential, ref, deadline):
        host = self.host
        project = host.projects.read(credential, ref)
        _check(
            type(project["input_version"]) is int,
            "stage2-controller-integer-version-required",
        )
        source = self.store.resolve(ref, "stage2-input")
        delivery = host.project_stage1_delivery
        _check(
            source is not None and delivery is not None,
            "stage2-controller-current-input-required",
        )
        digest = canonical_hash(source["derived_from"])
        root = host.projects._path(ref, "s2r-" + digest[:32])
        _check(
            safe_path(root, "receipt.json").is_file(),
            "stage2-controller-current-input-differs",
        )
        evidence = current_evidence(
            delivery,
            credential,
            host.project_stage1.read(credential, ref),
            project,
            check_deadline=deadline,
            on_received=lambda result, _, bound: dict(result, source_binding=bound),
        )
        _check(
            evidence["status"] == "received"
            and canonical_hash(evidence["source"]) == digest
            and all(
                evidence[key] == source["row"][key]
                for key in ("packet_id", "packet_sha256", "receipt_sha256")
            ),
            "stage2-controller-current-input-differs",
        )
        return source, evidence, safe_path(root, "resources.txt")

    def _profile_inputs(self, credential, ref, deadline):
        _check(self.profile is not None, "stage2-controller-profile-unavailable")
        try:
            row, policy, maximum = self.profile.resolve(ref)
            return row, policy, maximum, *self._source(credential, ref, deadline)
        except SessionApiError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            raise SessionApiError(
                "stage2-controller-profile-verification-required", 409
            ) from error

    def _verified(self, credential, ref, deadline, *, inputs=None):
        try:
            row, policy, maximum, source, evidence, _ = (
                self._profile_inputs(credential, ref, deadline)
                if inputs is None
                else inputs
            )
            stage2 = self.host.project_stage2
            principal = self.store.intake._principal(credential)
            state = self.store.intake._load(principal, ref)
            activation = state.get("stage2_activation")
            _check(activation is not None, "stage2-continuation-activation-required")
            binding = stage2.binding(ref)
            offer = state["stage2_offers"][activation["offer_ref"]]
            _check(
                offer["policy_ref"] == policy
                and activation["packet_sha256"] == evidence["packet_sha256"]
                and binding["activation_sha256"] == canonical_hash(activation)
                and all(
                    type(binding[key]) is type(source["identity"][key])
                    and binding[key] == source["identity"][key]
                    for key in ("project_id", "input_version", "brief_sha256")
                ),
                "stage2-controller-native-input-differs",
            )
            driver = load_stage2_controller(
                stage2,
                binding,
                row,
                allow_readback_without_admission=True,
                profile_paths=True,
            )
            records = private_output(driver.records)
            _check(
                all(
                    records != other
                    and records not in other.parents
                    and other not in records.parents
                    for other in (
                        private_output(item.records) for item in self.static.values()
                    )
                ),
                "stage2-controller-records-overlap",
            )
        except SessionApiError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            raise SessionApiError(
                "stage2-controller-profile-verification-required", 409
            ) from error
        return (
            driver,
            row,
            maximum,
            source["identity"],
            {
                "profile_sha256": self.profile.sha256,
                "input_connection_id": source["connection_id"],
                "packet_sha256": evidence["packet_sha256"],
                "activation_sha256": binding["activation_sha256"],
            },
        )

    def _publish_offer(self, credential, ref, body, inputs, deadline):
        row, policy, _, _, evidence, resources = inputs
        try:
            for key in ("spec", "preparation"):
                _document(row[key + "_path"], row[key + "_sha256"])
            project = self.store.intake.binding(ref)
            native = evidence["source_binding"]
            offer = self.host.project_stage2.register(
                ref,
                deliverable_dir=native["deliverable_dir"],
                expected_manifest_sha256=native["manifest_sha256"],
                handoff_path=native["handoff_path"],
                expected_handoff_sha256=native["handoff_sha256"],
                resources_path=resources,
                expected_resources_sha256=sha(
                    project["settings"]["resource_envelope"].encode("utf-8")
                ),
                policy_ref=policy,
                expected_revision=body["revision"],
                check_deadline=deadline,
                connection_key=body["key"],
                connection_profile_sha256=body["profile_sha256"],
            )
            stage = self.host.project_stage2.read(credential, ref, registered_only=True)
            _check(
                offer in stage["offers"],
                "stage2-controller-activation-offer-unavailable",
            )
            return self._public(
                ref,
                "consent-required",
                reason="stage2-continuation-activation-required",
                activation_offer=offer,
                revision=stage["revision"],
            )
        except SessionApiError:
            raise
        except (OSError, ValueError, KeyError, TypeError, RecursionError) as error:
            raise SessionApiError(
                "stage2-controller-profile-verification-required", 409
            ) from error

    @staticmethod
    def _match(saved, row, derived):
        _check(
            saved["row"] == row and saved["derived_from"] == derived,
            "stage2-controller-connection-differs",
        )

    def __getitem__(self, ref):
        driver = self.driver(self.store.credential, ref, None)
        if driver is None:
            raise KeyError(ref)
        return driver

    def driver(self, credential, ref, deadline):
        with self.store.intake._lock:
            saved = self._resolve(ref)
            if ref in self.static:
                return self.static[ref]
            if saved is None:
                return None
            driver, row, _, _, derived = self._verified(credential, ref, deadline)
            self._match(saved, row, derived)
            return driver

    def __iter__(self):
        with self.store.intake._lock:
            principal = self.store.intake._principal(self.store.credential)
            rows = self.store.intake.db.execute(
                """SELECT ref FROM intake_projects WHERE principal=?
                AND CASE WHEN json_valid(state)
                    THEN json_type(state, '$.stage_connections."stage2-controller"') IS NOT NULL
                    ELSE 0 END""",
                (principal,),
            ).fetchall()
            return iter(sorted(self.static.keys() | {row[0] for row in rows}))

    def __len__(self):
        return sum(1 for _ in self)

    def discover(self, credential, ref, deadline):
        with self.store.intake._lock:
            self.store.intake.read(credential, ref)
            saved = None
            try:
                saved = self._resolve(ref)
                if ref in self.static:
                    return self._public(ref, "connected", profile_sha256=None)
                _, row, _, _, derived = self._verified(credential, ref, deadline)
                if saved is None:
                    return self._public(ref, "connectable")
                self._match(saved, row, derived)
                return self._public(ref, "connected", saved=saved)
            except SessionApiError as error:
                if error.status != 409:
                    raise
                status = (
                    "consent-required"
                    if saved is None
                    and error.code == "stage2-continuation-activation-required"
                    else "unavailable"
                )
                return self._public(ref, status, reason=error.code)

    def register(self, credential, ref, body, deadline):
        with self.store.intake._lock:
            project = self.store.intake.read(credential, ref)
            _check(
                type(project["input_version"]) is int
                and project["input_version"] == body["input_version"]
                and project["brief_sha256"] == body["brief_sha256"],
                "stage2-controller-project-stale",
            )
            previous = self._resolve(ref)
            _check(ref not in self.static, "stage2-controller-bindings-overlap")
            _check(
                self.profile is not None
                and self.profile.sha256 == body["profile_sha256"],
                "stage2-controller-profile-differs",
            )
            inputs = self._profile_inputs(credential, ref, deadline)
            principal = self.store.intake._principal(credential)
            key_record = self.store.intake.db.execute(
                "SELECT receipt FROM intake_actions WHERE principal=? AND project=? AND key=?",
                (principal, ref, body["key"]),
            ).fetchone()
            if (
                key_record is not None
                and json.loads(key_record[0])["kind"] == "stage2-register-offer"
            ):
                return self._publish_offer(credential, ref, body, inputs, deadline)
            try:
                _, row, maximum, identity, derived = self._verified(
                    credential, ref, deadline, inputs=inputs
                )
            except SessionApiError as error:
                if (
                    previous is None
                    and error.code == "stage2-continuation-activation-required"
                ):
                    return self._publish_offer(credential, ref, body, inputs, deadline)
                raise
            if previous is not None:
                self._match(previous, row, derived)
            deadline()
            saved = self.store.record(
                ref,
                CONTROLLER_STAGE,
                row,
                derived_from=derived,
                check_deadline=deadline,
                expected_identity=identity,
                expected_revision=body["revision"],
                request_key=body["key"],
                maximum_projects=maximum,
            )
            return self._public(ref, "connected", saved=saved)

    def _public(self, ref, status, *, reason=None, saved=None, **extra):
        connection = {
            "status": status,
            "reason": reason,
            "profile_sha256": None if self.profile is None else self.profile.sha256,
            "connection_id": None if saved is None else saved["connection_id"],
            "receipt_id": None if saved is None else saved["receipt_id"],
            **extra,
        }
        return {
            "project_ref": ref,
            "connections": {CONTROLLER_STAGE: connection},
            "execution_authorized": False,
        }
