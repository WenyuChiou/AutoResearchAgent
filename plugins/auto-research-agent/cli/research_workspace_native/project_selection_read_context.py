"""Reuse strict selection verification only inside one locked planning GET.

No caller credential, failed verification or result survives the read. Writes
and dispatch do not enter this scope and keep their fresh admission checks.
"""

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from threading import get_ident

from stage2_common import Stage2Error, canonical_hash


_READ = ContextVar("project_selection_read", default=None)


@contextmanager
def verified_selection_read(intake):
    """The caller holds intake._lock through this synchronous read scope."""
    scope = dict(intake=intake, thread=get_ident(), active=True, key=None, result=None)
    token = _READ.set(scope)
    try:
        yield
    finally:
        scope.update(active=False, result=None)
        _READ.reset(token)


def _copy_result(result):
    verified, context = result
    # The activation service owns SQLite/locks; only its JSON and path are copied.
    return deepcopy(verified), (
        (context[0], *deepcopy(context[1:])) if context is not None else None
    )


def current_selection_context(view, credential, project_ref, *, validate_frontier):
    scope = _READ.get()
    verify = view._verify_current_context
    if (
        scope is None
        or not scope["active"]
        or scope["intake"] is not view.intake
        or scope["thread"] != get_ident()
        or validate_frontier is not True
    ):
        return verify(credential, project_ref, validate_frontier=validate_frontier)
    # Reauthenticate even a matching lookup. Different identities, bindings or
    # custom verifier implementations cannot share the original result.
    try:
        binding_hash = canonical_hash(view.bindings.get(project_ref))
    except Stage2Error:
        # Programmatic callers may supply Path roots. Keep the original strict
        # verifier rather than narrowing accepted inputs for an optimization.
        return verify(credential, project_ref, validate_frontier=True)
    key = (
        view.intake._principal(credential),
        project_ref,
        binding_hash,
        tuple(
            getattr(method, "__func__", method)
            for method in (verify, view._project_context, view._verified_frontier)
        ),
    )
    if scope["key"] == key:
        return _copy_result(scope["result"])
    result = verify(credential, project_ref, validate_frontier=True)
    if scope["key"] is None:
        scope.update(key=key, result=_copy_result(result))
    return result
