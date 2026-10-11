"""Strict bounded public request shapes for the offline project intake."""

from copy import deepcopy
import re

from stage1_deliverable.common import identifier
from stage1_ledger.journal import canonical
from .session_api import _check

MAX_REQUEST = 65536
MAX_PROJECTS = 128
MAX_VERSIONS = 64
MAX_ACTIONS = 256
BUDGETS = {"model_calls", "seconds", "search_calls", "source_reads", "rounds"}
CONSENTS = {"external_search", "public_source_read", "browser_fallback"}
BOUND_FIELDS = {"key", "revision", "input_version", "brief_sha256"}
RESOURCE_FIELDS = {"resource_envelope", "budgets", "consent", "user_input", "confirmed"}


def refusal_shape(kind, body, key, project_ref):
    """Only a trusted handler's exact valid envelope can yield an unsent receipt.

    Value validation remains the operation's responsibility. This check does not
    certify arbitrary JSON, a generic HTTP rejection, or an unbound project.
    """
    shapes = {
        "create": ({"key", "topic"}, {"needs", "scope_fields"}),
        "submit": (
            BOUND_FIELDS
            | RESOURCE_FIELDS
            | {"choices", "formal_target", "priority_reading_target"},
            set(),
        ),
        "configure": (BOUND_FIELDS | RESOURCE_FIELDS, set()),
        "revise": (BOUND_FIELDS | {"topic"}, {"needs", "scope_fields"}),
        "compile": (BOUND_FIELDS | {"request", "as_of"}, set()),
        "model-operation": (
            BOUND_FIELDS | {"offer_ref", "offer_sha256", "confirmed"},
            set(),
        ),
        "model-authorization": (
            BOUND_FIELDS | {"operation", "user_input", "confirmed"},
            set(),
        ),
        "stage1-initialize": (
            BOUND_FIELDS | {"offer_ref", "offer_sha256", "confirmed"},
            set(),
        ),
        "stage1-plan-query": (
            BOUND_FIELDS
            | {"ledger_state_sha256", "query_ref", "query_sha256", "confirmed"},
            set(),
        ),
        "stage1-execute-query": (
            BOUND_FIELDS
            | {"ledger_state_sha256", "query_ref", "query_sha256", "confirmed"},
            set(),
        ),
        "stage1-checkpoint": (
            BOUND_FIELDS | {"ledger_state_sha256", "confirmed"},
            set(),
        ),
        "stage1-export": (BOUND_FIELDS | {"ledger_state_sha256", "confirmed"}, set()),
        "stage1-deliver": (
            BOUND_FIELDS
            | {"ledger_state_sha256", "offer_ref", "offer_sha256", "confirmed"},
            set(),
        ),
        "stage2-activate": (
            BOUND_FIELDS | {"offer_ref", "offer_sha256", "confirmed"},
            set(),
        ),
    }
    for operation in ("bootstrap", "execute", "restore-owner", "authorize"):
        shapes["stage1-query-" + operation] = (
            BOUND_FIELDS
            | {"offer_ref", "offer_sha256", "confirmed"}
            | ({"user_input"} if operation == "authorize" else set()),
            set(),
        )
    if kind not in shapes or type(body) is not dict or body.get("key") != key:
        return False
    try:
        identifier(key)
        expected, optional = shapes[kind]
        _fields(body, expected, optional)
        if kind == "create":
            return project_ref is None and type(body["topic"]) is str
        identifier(project_ref)
        return (
            type(body["revision"]) is int
            and body["revision"] >= 0
            and type(body["input_version"]) is int
            and body["input_version"] > 0
            and type(body["brief_sha256"]) is str
            and re.fullmatch("[0-9a-f]{64}", body["brief_sha256"]) is not None
        )
    except (ValueError, TypeError, UnicodeError):
        return False


def _text(value, maximum=4096):
    _check(type(value) is str and bool(value.strip()), "intake-text-required", 400)
    _check(len(value.encode("utf-8")) <= maximum, "intake-text-too-large", 400)
    return value


def _fields(body, expected, optional=()):
    _check(
        type(body) is dict
        and set(body) <= set(expected) | set(optional)
        and set(expected) <= set(body),
        "intake-fields-invalid",
        400,
    )
    _check(len(canonical(body)) <= MAX_REQUEST, "intake-request-too-large", 400)
    identifier(body["key"])


def _scope(topic, body):
    needs = deepcopy(body.get("needs", [{"need_id": "main", "question": topic}]))
    fields = deepcopy(
        body.get(
            "scope_fields",
            [
                {
                    "field": "geography",
                    "material": True,
                    "reason": "Researcher must decide geography applicability or leave it unrestricted.",
                }
            ],
        )
    )
    _check(
        type(needs) is list
        and 0 < len(needs) <= 32
        and all(
            type(row) is dict and set(row) == {"need_id", "question"} for row in needs
        ),
        "intake-needs-invalid",
        400,
    )
    _check(
        type(fields) is list
        and 0 < len(fields) <= 32
        and all(
            type(row) is dict and set(row) == {"field", "material", "reason"}
            for row in fields
        )
        and not any(
            row["field"] in {"priority_reading_target", "formal_final_count"}
            for row in fields
        ),
        "intake-scope-fields-invalid",
        400,
    )
    fields.append(
        {
            "field": "priority_reading_target",
            "material": True,
            "reason": "Organization target is distinct from formal works, screening bibliography, and execution budget.",
        }
    )
    return {
        "original_description": topic,
        "needs": needs,
        "scope_fields": fields,
        "suggestions": [],
        "decisions": [],
    }


def _resources(body):
    _text(body["user_input"])
    _text(body["resource_envelope"], 8192)
    _check(
        type(body["budgets"]) is dict
        and set(body["budgets"]) == BUDGETS
        and all(type(v) is int and 0 <= v <= 1000000 for v in body["budgets"].values()),
        "intake-budget-invalid",
        400,
    )
    _check(
        type(body["consent"]) is dict
        and set(body["consent"]) == CONSENTS
        and all(type(v) is bool for v in body["consent"].values()),
        "intake-consent-invalid",
        400,
    )
