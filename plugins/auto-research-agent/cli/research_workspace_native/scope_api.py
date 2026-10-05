"""Source-bound ResearchBrief overlays; no execution or input-binding activation.

Brief bytes, parent hashes and explicit operator attestations commit together in
the existing project journal. Reviews record a decision, not research approval,
human identity proof, or permission to launch. Original source bytes stay intact.
"""

from contextlib import contextmanager
from copy import deepcopy
from datetime import datetime, timezone
import stat

from stage1_brief.brief import CHOICES, validate_brief
from stage1_deliverable.common import safe_path, sha
from stage1_ledger.journal import canonical, decode
from .session_api import SessionApi, SessionApiError, _check, _hash, _pick, _text

MAX_BRIEF = 65536
MAX_VERSIONS = 64
MAX_ACTIONS = 256


def _brief(raw, expected):
    _check(0 < len(raw) <= MAX_BRIEF and sha(raw) == expected, "scope-bytes-differ")
    value = decode(raw, "bound-brief")
    canonical(value)  # Reject overflow to infinity as well as explicit NaN.
    validate_brief(value)
    return value


class ScopeApi:
    def __init__(self, session_api):
        _check(isinstance(session_api, SessionApi), "session-api-required")
        self.api, self._bindings = session_api, {}

    @staticmethod
    def _source(binding, scope_binding):
        path = safe_path(binding["source_root"], scope_binding["brief_path"])
        _check(stat.S_ISREG(path.stat().st_mode), "scope-source-not-regular")
        with path.open("rb") as stream:
            raw = stream.read(MAX_BRIEF + 1)
        _brief(raw, scope_binding["base_sha256"])
        return raw

    def register(self, project_ref, *, brief_path, expected_sha256):
        """Trusted bootstrap selects the source path; browser requests never do."""
        _check(_hash(expected_sha256), "scope-source-hash-required")
        with self.api._lock:
            registration = self.api._projects.get(project_ref)
            _check(registration is not None, "project-unavailable", 404)
            controller, _, binding, _ = registration
            with controller.store._lock:
                self.api._source(registration)
                current = controller._context()
                source = dict(brief_path=brief_path, base_sha256=expected_sha256)
                raw = self._source(binding, source)
                ref = self.api._ref(binding, "scope-version", expected_sha256)
                with controller.store._edit(
                    controller.project_id,
                    controller.owner,
                    current["revision"],
                    "scope-source-bound",
                    source,
                ) as state:
                    saved = state.get("scope_overlay")
                    if saved is None:
                        state["scope_overlay"] = dict(
                            binding=source,
                            order=[ref],
                            actions={},
                            versions={
                                ref: dict(
                                    sha256=expected_sha256,
                                    parent_ref=None,
                                    raw_utf8=raw.decode("utf-8"),
                                )
                            },
                        )
                    else:
                        _check(saved["binding"] == source, "scope-binding-differs")
                        _check(
                            saved["versions"][saved["order"][0]]["raw_utf8"].encode(
                                "utf-8"
                            )
                            == raw,
                            "scope-base-differs",
                        )
                self._bindings[project_ref] = source

    def _versions(self, binding, overlay):
        order, versions = overlay["order"], overlay["versions"]
        _check(
            0 < len(order) <= MAX_VERSIONS
            and len(set(order)) == len(order)
            and set(order) == set(versions),
            "scope-history-invalid",
        )
        parsed, previous = {}, None
        for ref in order:
            row = versions[ref]
            value = _brief(row["raw_utf8"].encode("utf-8"), row["sha256"])
            _check(
                ref == self.api._ref(binding, "scope-version", row["sha256"])
                and row["parent_ref"] == previous,
                "scope-parent-differs",
            )
            if previous is not None:
                parent = parsed[previous]
                decisions = value.get("decisions", [])
                old = parent.get("decisions", [])
                _check(
                    len(decisions) > len(old) and decisions[: len(old)] == old,
                    "scope-history-rewritten",
                )
                expected = dict(
                    parent,
                    decisions=decisions,
                    previous_sha256=versions[previous]["sha256"],
                )
                _check(value == expected, "scope-nondecision-change")
            parsed[ref], previous = value, ref
        return parsed

    @contextmanager
    def _access(self, credential, project_ref):
        with self.api._access(credential, project_ref) as access:
            controller, principal, binding, state = access
            source = self._bindings.get(project_ref)
            overlay = state.get("scope_overlay")
            _check(
                source is not None
                and overlay is not None
                and overlay["binding"] == source,
                "scope-not-bound",
            )
            raw = self._source(binding, source)
            first = overlay["versions"][overlay["order"][0]]
            _check(
                first["sha256"] == source["base_sha256"]
                and first["raw_utf8"].encode("utf-8") == raw,
                "scope-base-differs",
            )
            yield (
                controller,
                principal,
                binding,
                state,
                overlay,
                self._versions(binding, overlay),
            )

    @staticmethod
    def _summary(ref, row, value):
        report = validate_brief(value)
        return dict(
            version_ref=ref,
            sha256=row["sha256"],
            parent_ref=row["parent_ref"],
            necessary_clarification_complete=report["necessary_clarification_complete"],
            pending_fields=report["pending_fields"],
        )

    @staticmethod
    def _receipt(row, replayed=False):
        return dict(
            _pick(
                row,
                "action_ref client_key kind status version_ref version_sha256 decision recorded_at",
            ),
            note=row["request"].get("note"),
            replayed=replayed,
            execution_authorized=False,
        )

    def history(self, credential, project_ref):
        with self._access(credential, project_ref) as (
            _,
            principal,
            binding,
            state,
            overlay,
            parsed,
        ):
            return dict(
                project_ref=project_ref,
                index_sha256=binding["index_sha256"],
                input_version=binding["input_version"],
                revision=state["revision"],
                latest_version_ref=overlay["order"][-1],
                execution_authorized=False,
                versions=[
                    self._summary(ref, overlay["versions"][ref], parsed[ref])
                    for ref in overlay["order"]
                ],
                actions=[
                    self._receipt(row)
                    for row in overlay["actions"].values()
                    if row["principal"] == principal
                ],
            )

    def read(self, credential, project_ref, version_ref):
        with self._access(credential, project_ref) as (_, _, _, state, overlay, parsed):
            _check(version_ref in parsed, "scope-version-unavailable", 404)
            value = parsed[version_ref]
            return dict(
                self._summary(version_ref, overlay["versions"][version_ref], value),
                revision=state["revision"],
                original_description=value["original_description"],
                scope_fields=[
                    _pick(f, "field material reason") for f in value["scope_fields"]
                ],
                scope=validate_brief(value)["scope"],
                execution_authorized=False,
                decisions=[
                    _pick(d, "field status value reason user_input recorded_at")
                    for d in value.get("decisions", [])
                ],
            )

    def append(self, credential, project_ref, body):
        return self._change(credential, project_ref, "append", body)

    def review(self, credential, project_ref, body):
        return self._change(credential, project_ref, "review", body)

    def _change(self, credential, project_ref, kind, body):
        with self._access(credential, project_ref) as (
            controller,
            principal,
            binding,
            state,
            overlay,
            parsed,
        ):
            fields = {"key", "revision", "index_sha256", "input_version", "confirmed"}
            fields |= (
                {"parent_ref", "parent_sha256", "choices"}
                if kind == "append"
                else {"version_ref", "version_sha256", "decision", "note"}
            )
            _check(
                isinstance(body, dict) and set(body) == fields,
                "invalid-scope-fields",
                400,
            )
            _check(
                _text(body["key"])
                and type(body["revision"]) is int
                and 0 <= body["revision"] < 2**63
                and body["confirmed"] is True,
                "explicit-scope-confirmation-required",
                400,
            )
            _check(
                body["index_sha256"] == binding["index_sha256"]
                and body["input_version"] == binding["input_version"],
                "source-version-differs",
            )
            body = deepcopy(body)
            _check(len(canonical(body)) <= 32768, "scope-request-too-large", 400)
            semantic = {k: v for k, v in body.items() if k != "revision"}
            request_hash = sha(canonical(dict(kind=kind, body=semantic)))
            key = sha(canonical([binding["project_id"], principal, body["key"]]))
            saved = overlay["actions"].get(key)
            if saved is not None:
                _check(
                    saved["request_sha256"] == request_hash,
                    "idempotency-payload-differs",
                )
                return self._receipt(saved, True)
            _check(body["revision"] == state["revision"], "stale-revision")
            _check(len(overlay["actions"]) < MAX_ACTIONS, "scope-action-bound-exceeded")
            recorded_at = datetime.now(timezone.utc).isoformat()
            if kind == "append":
                ref = body["parent_ref"]
                _check(
                    ref == overlay["order"][-1]
                    and body["parent_sha256"] == overlay["versions"][ref]["sha256"],
                    "scope-parent-differs",
                )
                _check(
                    len(overlay["order"]) < MAX_VERSIONS, "scope-version-bound-exceeded"
                )
                value = deepcopy(parsed[ref])
                choices = body["choices"]
                _check(
                    isinstance(choices, list) and 0 < len(choices) <= 32,
                    "scope-choices-required",
                    400,
                )
                selected = set()
                for choice in choices:
                    _check(
                        isinstance(choice, dict)
                        and set(choice)
                        == {"field", "status", "value", "reason", "user_input"},
                        "invalid-scope-choice",
                        400,
                    )
                    _check(
                        isinstance(choice["field"], str)
                        and choice["field"] not in selected
                        and choice["status"] in CHOICES
                        and isinstance(choice["reason"], str),
                        "invalid-scope-choice",
                        400,
                    )
                    selected.add(choice["field"])
                    value.setdefault("decisions", []).append(
                        dict(
                            choice,
                            authority="user",
                            actor=principal,
                            recorded_at=recorded_at,
                            source_ref="scope-request:" + request_hash,
                            event_id=sha(canonical([key, choice["field"]])),
                        )
                    )
                value["previous_sha256"] = body["parent_sha256"]
                try:
                    validate_brief(value)
                except (ValueError, TypeError, KeyError):
                    raise SessionApiError("invalid-scope-decision", 400) from None
                raw = canonical(value) + b"\n"
                _check(len(raw) <= MAX_BRIEF, "scope-version-too-large")
                version_hash = sha(raw)
                version_ref = self.api._ref(binding, "scope-version", version_hash)
                version = dict(
                    sha256=version_hash, parent_ref=ref, raw_utf8=raw.decode("utf-8")
                )
            else:
                version_ref, version_hash = body["version_ref"], body["version_sha256"]
                _check(
                    version_ref in parsed
                    and overlay["versions"][version_ref]["sha256"] == version_hash,
                    "scope-version-differs",
                )
                _check(
                    body["decision"] in {"reviewed", "changes-requested"}
                    and isinstance(body["note"], str)
                    and bool(body["note"].strip()),
                    "scope-review-note-required",
                    400,
                )
            row = dict(
                action_ref=self.api._ref(binding, "scope-action", key),
                client_key=body["key"],
                principal=principal,
                kind=kind,
                request=semantic,
                request_sha256=request_hash,
                version_ref=version_ref,
                version_sha256=version_hash,
                recorded_at=recorded_at,
                status="version-saved" if kind == "append" else "review-recorded",
                decision=body.get("decision"),
            )
            self._source(binding, self._bindings[project_ref])
            with controller.store._edit(
                controller.project_id,
                controller.owner,
                state["revision"],
                "scope-" + kind,
                dict(key=key, action=row),
            ) as current:
                target = current["scope_overlay"]
                if kind == "append":
                    target["versions"][version_ref] = version
                    target["order"].append(version_ref)
                target["actions"][key] = row
            return self._receipt(row)
