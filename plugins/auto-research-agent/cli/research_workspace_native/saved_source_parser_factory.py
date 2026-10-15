"""Explicit typed parser registration; never create a source grant or deadline.

The bound callable is only useful inside the original acquired-source operation.
Default parser_runner=None remains unavailable. No host auto-registration occurs.
"""

from copy import deepcopy
import math
from pathlib import Path
import sys

from .atlas_local_source import canonical, decode, digest, read, require, unlinked
from .bounded_public_source import request_binding
from .saved_source_parser_runtime import (
    SDK_COMMIT,
    configuration,
    tree_inventory,
    verify_sdk,
)
from .source_worker_runner import ContainedSourceJobRunner


def prepare_saved_parser_runtime(*, sdk_root):
    """Read current installation bytes; no SDK import, parse, network or child."""
    sdk = unlinked(Path(sdk_root).absolute()).resolve(strict=True)
    site = sdk.parent
    require(sdk.name == "research_hub", "saved-parser-sdk-package-required")
    metadata = list(site.glob("research_hub_pipeline-*.dist-info/direct_url.json"))
    require(len(metadata) == 1, "saved-parser-sdk-provenance-required")
    provenance = decode(read(metadata[0], 64 * 1024))
    require(
        provenance
        == {
            "url": "https://github.com/WenyuChiou/research-hub",
            "vcs_info": {
                "vcs": "git",
                "commit_id": SDK_COMMIT,
                "requested_revision": SDK_COMMIT,
            },
        },
        "saved-parser-sdk-commit-differs",
    )
    base = unlinked(Path(sys.base_prefix).absolute()).resolve(strict=True)
    roots = [
        dict(path=str(base / "Lib"), exclude=["site-packages"]),
        dict(path=str(base / "DLLs"), exclude=[]),
        dict(path=str(site), exclude=[]),
    ]
    for root in roots:
        root["files"] = tree_inventory(root["path"], exclude=root["exclude"])
    sdk_files = {
        name.removeprefix("research_hub/"): sha
        for name, sha in roots[2]["files"].items()
        if name.startswith("research_hub/")
    }
    document = dict(
        kind="SavedSourceParserRuntime",
        schema_version="1.0.0",
        sdk_commit=SDK_COMMIT,
        sdk_root=str(sdk),
        sdk_tree_sha256=digest(canonical(sdk_files)),
        runtime_roots=roots,
        module_paths=[root["path"] for root in roots],
        runtime_support={
            str(path): digest(read(path, 128 * 1024 * 1024))
            for path in sorted(base.glob("*.dll"))
        },
    )
    document["inventory_sha256"] = digest(canonical(document))
    configuration(document)
    verify_sdk(document)
    return document


def original_deadline_end(deadline):
    require(
        callable(getattr(deadline, "check", None)),
        "saved-parser-original-deadline-required",
    )
    ends = [getattr(deadline, name, None) for name in ("until", "end")]
    ends = [
        value for value in ends if type(value) in (int, float) and math.isfinite(value)
    ]
    require(bool(ends), "saved-parser-absolute-original-deadline-required")
    deadline.check()
    return min(ends)


class ContainedSavedSourceParserFactory:
    def __init__(self, *, worker, runtime):
        require(
            type(worker) is ContainedSourceJobRunner,
            "saved-parser-typed-owned-worker-required",
        )
        self.worker, self.runtime = worker, deepcopy(configuration(runtime))
        self.binding_sha256 = digest(canonical(self.runtime))

    def bind(self, *, request, deadline, check_current):
        require(
            type(self) is ContainedSavedSourceParserFactory and callable(check_current),
            "saved-parser-current-check-required",
        )
        request = request_binding(request)
        require(
            request["runtime_sha256"] == self.worker.config["runtime_sha256"]
            and request["resolver_sha256"] == self.worker.resolver_sha256,
            "saved-parser-original-request-differs",
        )
        original_deadline_end(deadline)
        return BoundSavedSourceParser(self, request, deadline, check_current)


class BoundSavedSourceParser:
    def __init__(self, factory, request, deadline, check_current):
        self.factory, self.request = factory, deepcopy(request)
        self.deadline, self.check_current = deadline, check_current
        self.original_end = original_deadline_end(deadline)

    def __call__(
        self, *, input_manifest, expected_manifest_sha256, output_dir, deadline
    ):
        require(
            type(self) is BoundSavedSourceParser and deadline is self.deadline,
            "saved-parser-original-deadline-differs",
        )
        require(
            original_deadline_end(deadline) == self.original_end,
            "saved-parser-original-deadline-changed",
        )
        factory = self.factory
        require(
            digest(canonical(configuration(factory.runtime))) == factory.binding_sha256,
            "saved-parser-runtime-registration-changed",
        )
        manifest_path = unlinked(Path(input_manifest).absolute())
        manifest_raw = read(manifest_path, 256 * 1024)
        require(
            digest(manifest_raw) == expected_manifest_sha256,
            "saved-parser-manifest-pin-differs",
        )
        manifest = decode(manifest_raw)
        intent = decode(
            read(manifest_path.parent / "source-parse-intent.json", 256 * 1024)
        )
        require(
            manifest_path.name == "source-parse-input.json"
            and manifest["url"] == self.request["source_uri"]
            and intent["kind"] == "SourceAcquisitionParseIntent"
            and intent["status"] == "dispatch-unobserved"
            and intent["request_sha256"] == digest(canonical(self.request))
            and intent["job_binding_sha256"] == self.request["job_binding_sha256"]
            and intent["runtime_sha256"] == self.request["runtime_sha256"]
            and intent["manifest_sha256"] == expected_manifest_sha256
            and Path(intent["parser_output_dir"]) == Path(output_dir)
            and intent["expected_identity"]
            == {"doi": manifest["doi"], "title": manifest["title"]},
            "saved-parser-original-intent-differs",
        )
        phase = dict(
            kind="SavedSourceParserOperation",
            schema_version="1.0.0",
            operation="parse_saved_manifest",
            runtime=deepcopy(factory.runtime),
            input_manifest=str(manifest_path),
            manifest_sha256=expected_manifest_sha256,
            original_deadline_end=self.original_end,
        )
        result = factory.worker.run_sdk(
            self.request,
            output_dir,
            parse_saved_manifest=phase,
            deadline=deadline,
            check_current=self.check_current,
        )
        deadline.check()
        raw = read(Path(output_dir) / result["receipt_path"], 256 * 1024)
        require(
            digest(raw) == result["receipt_sha256"],
            "saved-parser-result-readback-differs",
        )
        deadline.check()
        return decode(raw)
