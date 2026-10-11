"""Canonical Stage1 activation in the existing offline project journal.

Only trusted bootstrap registers physical inputs. An explicit researcher action
imports a verified eligible handoff and initializes the real Stage2 workflow.
This adapter never launches a native process, calls a model, searches, scores,
or authorizes Stage3. Persisted interrupted intents are history, never retries.
"""

from copy import deepcopy
from pathlib import Path
import stat

from stage1_brief.brief import validate_brief
from stage1_deliverable.common import (
    identifier,
    private_output,
    reject_links,
    safe_path,
    sha,
)
from stage1_ledger.contracts import check as check_contract
from stage1_ledger.journal import canonical, decode
from stage2_common import Stage2Error, canonical_hash, validate_packet
from stage2_workflow import build_stage2_seed, initialize_workflow, inspect_workflow
from .project_intake import ProjectIntakeService, _fields
from .session_api import SessionApiError, _check, _hash

MAX_OFFERS = 16
MAX_INPUT = 16 * 1024 * 1024
RECEIPT_FIELDS = {
    "project_ref",
    "key",
    "kind",
    "request_sha256",
    "request",
    "status",
    "recorded_at",
}


def _raw(path, expected, *, maximum=MAX_INPUT):
    _check(_hash(expected), "stage2-input-hash-required", 400)
    path = Path(path).absolute()
    reject_links(path)
    _check(stat.S_ISREG(path.stat().st_mode), "stage2-input-not-regular")
    with path.open("rb") as stream:
        raw = stream.read(maximum + 1)
    _check(len(raw) <= maximum and sha(raw) == expected, "stage2-input-bytes-differ")
    return raw


def _verified_inputs(binding, inputs):
    manifest = decode(
        _raw(
            Path(inputs["deliverable_dir"]) / "provenance_manifest.json",
            inputs["manifest_sha256"],
        ),
        "stage1 manifest",
    )
    _check(
        manifest.get("canonical_records", {}).get("schema_version") != "1.1.0",
        "stage2-canonical-records-1.1-consumer-unconnected",
    )
    handoff = decode(
        _raw(inputs["handoff_path"], inputs["handoff_sha256"]), "stage1 handoff"
    )
    check_contract(handoff, "Stage1Handoff")
    _check(handoff["eligible_for_stage2"] is True, "stage1-not-eligible-for-stage2")
    _check(
        handoff["stage2"] == {"status": "not-started", "execution_authorized": False},
        "stage2-handoff-boundary-differs",
    )
    brief = decode(
        _raw(binding["brief_path"], binding["brief_sha256"], maximum=65536),
        "research brief",
    )
    validate_brief(brief, require_confirmed=True)
    resources = (
        _raw(inputs["resources_path"], inputs["resources_sha256"], maximum=65536)
        .decode("utf-8")
        .strip()
    )
    _check(
        bool(resources)
        and resources == binding["settings"]["resource_envelope"].strip(),
        "stage2-resources-differ",
    )
    papers = {row["work_id"]: row for row in manifest["canonical_records"]["papers"]}
    for row in handoff["papers"]:
        paper = papers.get(row["work_id"])
        _check(
            paper is not None
            and paper["title"] == row["title"]
            and paper["version_id"]
            == (row["reviewed_version_id"] or row["listed_version_id"]),
            "stage2-work-version-differs",
        )
    return handoff, brief


def _public(offer):
    return {
        key: deepcopy(offer[key])
        for key in (
            "offer_ref",
            "offer_sha256",
            "input_version",
            "brief_sha256",
            "plan_manifest_sha256",
            "stage1_manifest_sha256",
            "stage1_handoff_sha256",
            "work_count",
            "status",
        )
    }


class ProjectStage2Service:
    """Offline extension of ProjectIntakeService; not another project store."""

    def __init__(self, intake):
        _check(
            isinstance(intake, ProjectIntakeService),
            "project-intake-service-required",
            400,
        )
        self.intake = intake

    @staticmethod
    def _matches(binding, offer):
        _check(
            all(
                binding[key] == offer[key]
                for key in (
                    "project_id",
                    "input_version",
                    "brief_sha256",
                    "plan_manifest_sha256",
                )
            ),
            "stage2-offer-source-version-differs",
        )

    def register(
        self,
        project_ref,
        *,
        deliverable_dir,
        expected_manifest_sha256,
        handoff_path,
        expected_handoff_sha256,
        resources_path,
        expected_resources_sha256,
        policy_ref,
    ):
        """Trusted bootstrap only. Browser requests cannot supply these paths."""
        _check(
            type(policy_ref) is dict
            and policy_ref.get("route") == "stage2-general-v3/daily_v3",
            "stage2-daily-v3-policy-reference-required",
            400,
        )
        inputs = dict(
            deliverable_dir=str(Path(deliverable_dir).absolute()),
            manifest_sha256=expected_manifest_sha256,
            handoff_path=str(Path(handoff_path).absolute()),
            handoff_sha256=expected_handoff_sha256,
            resources_path=str(Path(resources_path).absolute()),
            resources_sha256=expected_resources_sha256,
        )
        with self.intake._lock:
            binding = self.intake.binding(project_ref)
            handoff, _ = _verified_inputs(binding, inputs)
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
                stage1_manifest_sha256=expected_manifest_sha256,
                stage1_handoff_sha256=expected_handoff_sha256,
                resources_sha256=expected_resources_sha256,
                settings_sha256=canonical_hash(binding["settings"]),
                policy_ref=deepcopy(policy_ref),
            )
            offer_hash = sha(canonical(basis))
            offer = dict(
                basis,
                offer_ref="stage2-" + offer_hash[:32],
                offer_sha256=offer_hash,
                inputs=inputs,
                work_count=len(handoff["papers"]),
                status="ready-for-researcher-activation",
            )
            row = self.intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            principal = row[0]
            state = self.intake._load(principal, project_ref)
            body = dict(
                key="offer-" + offer_hash,
                revision=state["revision"],
                input_version=binding["input_version"],
                brief_sha256=binding["brief_sha256"],
                offer_sha256=offer_hash,
            )

            def work(current, _, __):
                saved = current.setdefault("stage2_offers", {})
                _check(len(saved) < MAX_OFFERS, "stage2-offer-bound-exceeded")
                saved[offer["offer_ref"]] = deepcopy(offer)
                return {"offer": _public(offer)}

            self.intake._perform(
                principal, project_ref, "stage2-register-offer", body, work
            )
            return _public(offer)

    def read(self, credential, project_ref):
        principal = self.intake._principal(credential)
        with self.intake._lock:
            state = self.intake._load(principal, project_ref)
            current = self.intake.read(credential, project_ref)
            offers = [_public(row) for row in state.get("stage2_offers", {}).values()]
            current_plan = current.get("plan")
            for offer in offers:
                if (
                    offer["input_version"] != current.get("input_version")
                    or offer["brief_sha256"] != current.get("brief_sha256")
                    or current_plan is None
                    or offer["plan_manifest_sha256"] != current_plan["manifest_sha256"]
                ):
                    offer["status"] = "stale-input"
            activation = deepcopy(state.get("stage2_activation"))
            if activation and any(
                offer["offer_ref"] == activation["offer_ref"]
                and offer["status"] == "stale-input"
                for offer in offers
            ):
                activation["stage2_status"] = "stale-input"
            return dict(
                project_ref=project_ref,
                revision=state["revision"],
                offers=offers,
                activation=activation,
                frontier=deepcopy(state.get("stage2_frontier")),
                execution_authorized=False,
                native_connected=False,
                daily_v3="not-started",
                stage2_complete=False,
                later_stages={
                    str(i): dict(status="planned", connected=False) for i in range(3, 7)
                },
            )

    def history(self, credential, project_ref):
        return self.intake.history(credential, project_ref)

    def offers(self, credential, project_ref):
        """Read the current public offers; no registration or import occurs."""
        return self.read(credential, project_ref)

    def action(self, credential, project_ref, key):
        """Recover an existing action by its original opaque key."""
        return self.intake.action(credential, key, project_ref=project_ref)

    def activate(self, credential, project_ref, body, *, check_deadline=None):
        _fields(
            body,
            {
                "key",
                "revision",
                "input_version",
                "brief_sha256",
                "offer_ref",
                "offer_sha256",
                "confirmed",
            },
        )
        _check(
            body["confirmed"] is True and _hash(body["offer_sha256"]),
            "explicit-stage2-activation-required",
            400,
        )
        identifier(body["offer_ref"])
        _check(
            check_deadline is None or callable(check_deadline),
            "stage2-deadline-check-invalid",
            400,
        )
        principal = self.intake._principal(credential)

        def work(state, request_hash, actor):
            binding = self.intake.binding(project_ref)
            offer = state.get("stage2_offers", {}).get(body["offer_ref"])
            _check(
                offer is not None and offer["offer_sha256"] == body["offer_sha256"],
                "stage2-offer-unavailable",
                404,
            )
            self._matches(binding, offer)
            _check(
                canonical_hash(binding["settings"]) == offer["settings_sha256"],
                "stage2-settings-differ",
            )
            _verified_inputs(binding, offer["inputs"])
            active = state.get("stage2_activation")
            _check(active is None, "stage2-already-activated")
            if check_deadline is not None:
                check_deadline()
            relative = "stage2-" + request_hash
            output = private_output(self.intake._path(project_ref, relative))
            _check(not output.exists(), "stage2-output-requires-reconciliation")
            output.mkdir()
            inputs = offer["inputs"]
            receipt = build_stage2_seed(
                inputs["deliverable_dir"],
                inputs["manifest_sha256"],
                inputs["handoff_path"],
                inputs["handoff_sha256"],
                binding["brief_path"],
                inputs["resources_path"],
                output / "seed",
            )
            if check_deadline is not None:
                check_deadline()
            manifest = initialize_workflow(
                output / "seed" / "packet.json",
                output / "seed",
                output / "workflow",
                binding["settings"],
                offer["policy_ref"],
                receipt["packet_sha256"],
            )
            verified = inspect_workflow(output / "workflow")
            _verified_inputs(binding, inputs)
            if check_deadline is not None:
                check_deadline()
            result = dict(
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                packet_sha256=receipt["packet_sha256"],
                binding_sha256=receipt["binding_sha256"],
                workflow_manifest_sha256=manifest["manifest_sha256"],
                workflow_head_sha256=verified["head_sha256"],
                artifact_ref="stage2-artifact-" + request_hash,
                stage2_status="ready-for-explicit-stage2-run",
                researcher=actor,
                input_version=binding["input_version"],
                brief_sha256=binding["brief_sha256"],
                daily_v3="not-started",
                stage2_complete=False,
                execution_authorized=False,
            )
            state["stage2_activation"] = result
            state["stage2_frontier"] = self._initial_frontier(
                project_ref, binding, offer, result
            )
            state.setdefault("stage2_artifacts", {})[result["artifact_ref"]] = dict(
                path=relative, **result
            )
            return result

        return self.intake._perform(
            principal,
            project_ref,
            "stage2-activate",
            deepcopy(body),
            work,
            check_deadline=check_deadline,
        )

    def _journal(self, project_ref, kind):
        return [
            decode(row[0].encode("utf-8"), "stage2 journal receipt")
            for row in self.intake.db.execute(
                "SELECT payload FROM intake_events WHERE project=? AND kind=? ORDER BY id",
                (project_ref, kind),
            )
        ]

    @staticmethod
    def _initial_frontier(project_ref, current, offer, activation):
        return dict(
            kind="Stage2WorkflowFrontier",
            schema_version="1.0.0",
            project_ref=project_ref,
            project_id=current["project_id"],
            input_version=current["input_version"],
            brief_sha256=current["brief_sha256"],
            plan_manifest_sha256=current["plan_manifest_sha256"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            stage1_manifest_sha256=offer["stage1_manifest_sha256"],
            stage1_handoff_sha256=offer["stage1_handoff_sha256"],
            resources_sha256=offer["resources_sha256"],
            settings_sha256=offer["settings_sha256"],
            activation_sha256=canonical_hash(activation),
            artifact_ref=activation["artifact_ref"],
            packet_sha256=activation["packet_sha256"],
            binding_sha256=activation["binding_sha256"],
            workflow_manifest_sha256=activation["workflow_manifest_sha256"],
            initial_workflow_head_sha256=activation["workflow_head_sha256"],
            workflow_head_sha256=activation["workflow_head_sha256"],
            sequence=0,
        )

    def _activation_context(self, project_ref, state):
        activation = state.get("stage2_activation")
        _check(activation is not None, "stage2-not-activated")
        saved = [
            row
            for row in self._journal(project_ref, "stage2-activate-saved")
            if row.get("artifact_ref") == activation["artifact_ref"]
        ]
        _check(
            len(saved) == 1
            and {
                key: value
                for key, value in saved[0].items()
                if key not in RECEIPT_FIELDS
            }
            == activation,
            "stage2-activation-journal-differs",
        )
        offer = state["stage2_offers"][activation["offer_ref"]]
        registered = [
            row.get("offer")
            for row in self._journal(project_ref, "stage2-register-offer-saved")
            if row.get("offer", {}).get("offer_ref") == offer["offer_ref"]
        ]
        basis = {
            key: offer[key]
            for key in (
                "project_id",
                "input_version",
                "brief_sha256",
                "plan_manifest_sha256",
                "stage1_manifest_sha256",
                "stage1_handoff_sha256",
                "resources_sha256",
                "settings_sha256",
                "policy_ref",
            )
        }
        _check(
            registered == [_public(offer)]
            and sha(canonical(basis))
            == activation["offer_sha256"]
            == offer["offer_sha256"],
            "stage2-offer-journal-differs",
        )
        current = self.intake.binding(project_ref)
        self._matches(current, offer)
        _check(
            canonical_hash(current["settings"]) == offer["settings_sha256"],
            "stage2-settings-differ",
        )
        _verified_inputs(current, offer["inputs"])
        artifact = state["stage2_artifacts"][activation["artifact_ref"]]
        relative = "stage2-" + saved[0]["request_sha256"]
        _check(
            artifact == dict(path=relative, **activation),
            "stage2-artifact-journal-differs",
        )
        root = self.intake._path(project_ref, relative)
        packet_path = safe_path(root / "seed", "packet.json")
        with packet_path.open("rb") as stream:
            packet_raw = stream.read(MAX_INPUT + 1)
        _check(len(packet_raw) <= MAX_INPUT, "stage2-packet-too-large")
        packet = decode(packet_raw, "stage2 packet")
        _check(
            canonical_hash(packet) == activation["packet_sha256"],
            "stage2-packet-bytes-differ",
        )
        for source in packet["sources"]:
            safe_path(root / "seed", source["path"])
        validate_packet(packet, root / "seed")
        return current, activation, offer, root

    def _frontier(self, project_ref, state, current, offer, activation):
        initial = self._initial_frontier(project_ref, current, offer, activation)
        frontier = deepcopy(initial)
        for receipt in self._journal(project_ref, "stage2-frontier-saved"):
            request = receipt.get("request", {})
            new_head = request.get("new_workflow_head_sha256")
            _check(
                receipt.get("status") == "saved"
                and request.get("expected_activation_sha256")
                == initial["activation_sha256"]
                and request.get("expected_previous_head_sha256")
                == frontier["workflow_head_sha256"]
                and _hash(new_head)
                and new_head != frontier["workflow_head_sha256"],
                "stage2-frontier-journal-chain-differs",
            )
            frontier.update(
                workflow_head_sha256=new_head, sequence=frontier["sequence"] + 1
            )
            _check(
                receipt.get("frontier") == frontier,
                "stage2-frontier-journal-binding-differs",
            )
        _check(
            state.get("stage2_frontier", initial) == frontier,
            "stage2-frontier-state-journal-differs",
        )
        return frontier

    @staticmethod
    def _inspect_frontier(root, activation, previous_head, new_head):
        verified = inspect_workflow(root / "workflow", new_head)
        _check(
            verified["manifest"]["manifest_sha256"]
            == activation["workflow_manifest_sha256"],
            "stage2-workflow-bytes-differ",
        )
        heads = [row["event_sha256"] for row in verified["events"]]
        initial_head = activation["workflow_head_sha256"]
        _check(
            initial_head in heads
            and previous_head in heads
            and heads.index(initial_head)
            <= heads.index(previous_head)
            <= heads.index(new_head),
            "stage2-frontier-not-descendant-of-activation",
        )
        return verified

    def advance_frontier(
        self,
        project_ref,
        *,
        key,
        expected_activation_sha256,
        expected_previous_head_sha256,
        new_workflow_head_sha256,
        check_deadline=None,
    ):
        """Trusted adapter CAS only; validates saved events and never runs an action.

        No browser route or physical-path argument is accepted. The adapter must
        retain the activation and previous-head receipts before the producer runs.
        Unknown intents remain history; replay never advances a frontier again.
        """
        identifier(key)
        _check(
            all(
                _hash(value)
                for value in (
                    expected_activation_sha256,
                    expected_previous_head_sha256,
                    new_workflow_head_sha256,
                )
            ),
            "stage2-frontier-hashes-required",
            400,
        )
        _check(
            check_deadline is None or callable(check_deadline),
            "stage2-deadline-check-invalid",
            400,
        )
        with self.intake._lock:
            row = self.intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            _check(row is not None, "project-unavailable", 404)
            state = self.intake._load(row[0], project_ref)
            current = self.intake.binding(project_ref)
            body = dict(
                key=key,
                revision=state["revision"],
                input_version=current["input_version"],
                brief_sha256=current["brief_sha256"],
                expected_activation_sha256=expected_activation_sha256,
                expected_previous_head_sha256=expected_previous_head_sha256,
                new_workflow_head_sha256=new_workflow_head_sha256,
            )

            def work(saved, _, __):
                try:
                    current, activation, offer, root = self._activation_context(
                        project_ref, saved
                    )
                    frontier = self._frontier(
                        project_ref, saved, current, offer, activation
                    )
                    _check(
                        frontier["activation_sha256"] == expected_activation_sha256,
                        "stage2-frontier-activation-differs",
                    )
                    _check(
                        frontier["workflow_head_sha256"]
                        == expected_previous_head_sha256
                        and new_workflow_head_sha256 != expected_previous_head_sha256,
                        "stage2-frontier-cas-conflict",
                    )
                    self._inspect_frontier(
                        root,
                        activation,
                        expected_previous_head_sha256,
                        new_workflow_head_sha256,
                    )
                except (OSError, Stage2Error) as error:
                    # Producer diagnostics may contain physical paths. Public
                    # action history retains a refusal code, never those paths.
                    raise SessionApiError(
                        "stage2-frontier-validation-failed"
                    ) from error
                frontier.update(
                    workflow_head_sha256=new_workflow_head_sha256,
                    sequence=frontier["sequence"] + 1,
                )
                saved["stage2_frontier"] = frontier
                return dict(frontier=deepcopy(frontier), execution_authorized=False)

            return self.intake._perform(
                row[0],
                project_ref,
                "stage2-frontier",
                body,
                work,
                check_deadline=check_deadline,
            )

    def binding(self, project_ref):
        """Trusted lookup accepts only the durably acknowledged workflow frontier."""
        with self.intake._lock:
            row = self.intake.db.execute(
                "SELECT principal FROM intake_projects WHERE ref=?", (project_ref,)
            ).fetchone()
            _check(row is not None, "project-unavailable", 404)
            state = self.intake._load(row[0], project_ref)
            current, activation, offer, root = self._activation_context(
                project_ref, state
            )
            frontier = self._frontier(project_ref, state, current, offer, activation)
            self._inspect_frontier(
                root,
                activation,
                frontier["workflow_head_sha256"],
                frontier["workflow_head_sha256"],
            )
            return dict(
                project_id=current["project_id"],
                input_version=current["input_version"],
                brief_sha256=current["brief_sha256"],
                source_root=root / "seed",
                packet_path=root / "seed" / "packet.json",
                workflow_root=root / "workflow",
                workflow_head_sha256=frontier["workflow_head_sha256"],
                initial_workflow_head_sha256=activation["workflow_head_sha256"],
                activation_sha256=frontier["activation_sha256"],
                frontier_sequence=frontier["sequence"],
                packet_sha256=activation["packet_sha256"],
                execution_authorized=False,
            )
