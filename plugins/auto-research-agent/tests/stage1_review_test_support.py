"""Failure diagnostics for authored tests only; never wraps a production host."""

import time
import traceback
from unittest.mock import patch

from research_workspace_native.project_stage1_auto import ProjectStage1AutoDriver


def continue_with_diagnostics(host, credential, ref, **kwargs):
    """Keep the original dispatch, exception and deadline; observe failures only."""
    original = ProjectStage1AutoDriver.dispatch
    failures = []

    def dispatch(driver, action, key, deadline):
        started = time.monotonic()
        try:
            return original(driver, action, key, deadline)
        except Exception as error:
            failures.append(
                dict(
                    kind=action.kind,
                    exception_type=type(error).__name__,
                    exception_code=getattr(error, "code", None),
                    exception_chain=traceback.format_exc(),
                    elapsed_seconds=time.monotonic() - started,
                    deadline_remaining_seconds=deadline - time.monotonic(),
                )
            )
            raise

    with patch.object(ProjectStage1AutoDriver, "dispatch", dispatch):
        result = host.continue_stage1(credential, ref, **kwargs)
    return result, failures
