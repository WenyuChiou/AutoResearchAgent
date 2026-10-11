"""Server setup for the existing contained public-source worker.

This helper is called only by portable preparation, not by an HTTP/browser
request. It derives the actual checkout inventory, interpreter and Git from
the running server. Creating a profile never grants a source/parse permission,
reserves a resource, starts a process or imports a paper. Dispatch remains the
durable source service's explicitly confirmed, budget-reserved operation.
"""

from copy import deepcopy
from pathlib import Path
import shutil
import sys

from stage1_deliverable.common import canonical, sha
from .atlas_local_source import decode, inventory, read, require, unlinked

_SERVER_PROFILE = object()


SOURCE_CAPS = {
    "max_fetches": 128,
    "max_reserved_seconds": 86400,
    "timeout_seconds": 60,
    "validity_seconds": 1800,
    "max_response_bytes": 16 * 1024 * 1024,
    "max_http_attempts": 16,
}


class PortableSourceWorkerProfile:
    """A server-prepared immutable profile, not a browser configuration body."""

    def __init__(self, document, token):
        require(token is _SERVER_PROFILE, "source-profile-server-construction-required")
        self._raw = canonical(document)

    @property
    def document(self):
        return decode(self._raw)


def prepare_source_worker_profile(*, repo, materials_root, runtime_sha256):
    """Derive one fixed server profile; no caller JSON/caps/argv/env are read.

    runtime_sha256 is the portable host's already verified runtime binding.
    It is deliberately not synthesized from a declared version string here.
    Raw hashes are physical configuration evidence, not authentication.
    """
    require(
        type(runtime_sha256) is str
        and len(runtime_sha256) == 64
        and all(c in "0123456789abcdef" for c in runtime_sha256),
        "source-profile-verified-runtime-required",
    )
    repo = unlinked(Path(repo).absolute()).resolve(strict=True)
    materials = unlinked(Path(materials_root).absolute()).resolve(strict=True)
    require(repo.is_dir() and materials.is_dir(), "source-profile-directories-required")
    require(
        not materials.is_relative_to(repo) and not repo.is_relative_to(materials),
        "source-profile-private-materials-outside-checkout",
    )
    plugin = unlinked(repo / "plugins/auto-research-agent")
    files = inventory(plugin)
    required = {
        "source_worker_process.py",
        "source_worker_bootstrap.py",
        "source_worker_transport.py",
        "source_worker_runner.py",
        "bounded_public_source.py",
        "bounded_source_resolver.py",
        "project_stage1_source_service.py",
        "acquired_source_parser.py",
    }
    require(
        all("cli/research_workspace_native/" + name in files for name in required),
        "source-profile-owned-worker-dependency-missing",
    )
    interpreter = unlinked(Path(sys.executable).absolute()).resolve(strict=True)
    git = shutil.which("git.exe")
    require(git is not None, "source-profile-fixed-git-unavailable")
    git = unlinked(Path(git).absolute()).resolve(strict=True)
    require(git.name.lower() == "git.exe", "source-profile-git-identity-differs")
    inventory_sha = sha(canonical(files))
    worker = dict(
        kind="OwnedSourceWorkerConfiguration",
        schema_version="1.0.0",
        repo=str(repo),
        files=files,
        inventory_sha256=inventory_sha,
        interpreter=str(interpreter),
        interpreter_sha256=sha(read(interpreter, 64 * 1024 * 1024)),
        git_executable=str(git),
        git_sha256=sha(read(git, 64 * 1024 * 1024)),
        execution_source_sha256=inventory_sha,
        runtime_sha256=runtime_sha256,
        resolver_sha256=files[
            "cli/research_workspace_native/bounded_source_resolver.py"
        ],
        materials_root=str(materials),
        cleanup_reserve_seconds=2,
        guard_timeout_seconds=2,
        max_stdout_bytes=1024 * 1024,
        max_stderr_bytes=1024 * 1024,
        max_frames=64,
    )
    source = dict(
        caps=deepcopy(SOURCE_CAPS),
        runtime_sha256=runtime_sha256,
        execution_source_sha256=inventory_sha,
    )
    return PortableSourceWorkerProfile(
        dict(
            kind="PortableContainedSourceProfile",
            schema_version="1.0.0",
            worker=worker,
            source=source,
            profile_sha256=sha(canonical(dict(worker=worker, source=source))),
            configured=True,
            execution_authorized=False,
            source_dispatch_requires_saved_grant=True,
            sdk_parse_connected=False,
            automatic_dispatch=False,
        ),
        _SERVER_PROFILE,
    )


def register_source_worker(profile):
    """Construct the concrete worker only; no process/service/SDK construction."""
    require(
        type(profile) is PortableSourceWorkerProfile,
        "source-profile-server-object-required",
    )
    profile = profile.document
    require(
        type(profile) is dict
        and profile.get("kind") == "PortableContainedSourceProfile"
        and profile.get("schema_version") == "1.0.0",
        "source-profile-registration-invalid",
    )
    worker, source = profile["worker"], profile["source"]
    require(
        profile["profile_sha256"] == sha(canonical(dict(worker=worker, source=source)))
        and source["runtime_sha256"] == worker["runtime_sha256"]
        and source["execution_source_sha256"] == worker["execution_source_sha256"],
        "source-profile-registration-pins-differ",
    )
    from .source_worker_runner import ContainedSourceJobRunner

    return ContainedSourceJobRunner(deepcopy(worker)), deepcopy(source)
