"""Bind existing saved Stage1 readers to exact, verified imported projects."""

from copy import deepcopy

from .session_api import _check


def bind_saved_stage1_references(projects, credential, references):
    """Trusted host bootstrap; browsers cannot nominate a view, project or path."""
    from .project_stage2 import _verified_inputs

    result = deepcopy(list(references))
    by_ref = {row["ref"]: row for row in result}
    for current in projects.list(credential):
        if current.get("stage1_status") != "imported-verified-delivery":
            continue
        binding = projects.binding(current["project_ref"])
        view_pin = binding.get("saved_view")
        if view_pin is None:
            continue
        view = by_ref.get(view_pin["ref"])
        _check(view is not None, "stage1-saved-view-unavailable")
        _check(
            view["index_sha256"] == view_pin["index_sha256"]
            and view["manifest_sha256"] == view_pin["manifest_sha256"]
            and view.get("stage1_manifest_sha256")
            == binding["imported_stage1_inputs"]["manifest_sha256"]
            and view["project_id"] == binding["project_id"]
            and type(view["input_version"]) is type(binding["input_version"])
            and view["input_version"] == binding["input_version"],
            "stage1-saved-view-import-binding-differs",
        )
        _check(
            "project_ref" not in view or view["project_ref"] == current["project_ref"],
            "stage1-saved-view-project-binding-ambiguous",
        )
        # Reopen admission, handoff and HostReplay after cheap identity checks.
        # A matching title or project identifier alone cannot establish a link.
        handoff, _, _ = _verified_inputs(binding, binding["imported_stage1_inputs"])
        _check(
            view.get("snapshot_sha256") == handoff.get("snapshot_ref", {}).get("sha256")
            and isinstance(view.get("snapshot_sha256"), str),
            "stage1-saved-view-snapshot-differs",
        )
        view.update(
            project_ref=current["project_ref"],
            project_input_sha256=binding["imported_input_sha256"],
            binding_origin="trusted-host-stage1-view-binding",
        )
    return result
