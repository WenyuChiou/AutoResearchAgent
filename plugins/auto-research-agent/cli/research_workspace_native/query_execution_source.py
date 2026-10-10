"""Verify current raw source and fresh owned-module origins independently."""

from copy import deepcopy
from pathlib import Path
import sys
import stat
from stage1_deliverable.common import canonical, sha
from .atlas_local_source import PinnedLoader, unlinked
from .planned_query_contract import HASH, require


def check_execution_source(verifier, ref, item, phase, executor=None):
    proof = verifier(
        dict(
            project_ref=ref,
            execution_source_sha256=item["execution_source_sha256"],
            phase=deepcopy(phase),
        )
    )
    require(
        isinstance(proof, dict) and set(proof) == {"repo", "files"},
        "query-execution-source-unobserved",
        403,
    )
    files = proof["files"]
    require(
        isinstance(files, dict)
        and 1 <= len(files) <= 4096
        and all(
            isinstance(k, str) and isinstance(v, str) and HASH.fullmatch(v)
            for k, v in files.items()
        )
        and sha(canonical(files)) == item["execution_source_sha256"],
        "query-execution-source-manifest-differs",
        403,
    )
    repo = unlinked(proof["repo"]).resolve()
    require(
        repo == Path(item["execution_source_root"]),
        "query-execution-source-root-differs",
        403,
    )
    cli = repo / "plugins/auto-research-agent/cli"
    require(cli.is_dir(), "query-execution-source-root-missing", 403)
    names = {
        p.name for p in cli.iterdir() if p.is_dir() and (p / "__init__.py").is_file()
    } | {p.stem for p in cli.glob("*.py")}
    plugin = repo / "plugins/auto-research-agent"
    selected_paths = {}
    for relative in files:
        selected = Path(relative)
        target = plugin / selected
        require(
            selected.parts
            and not selected.drive
            and not selected.root
            and ".." not in selected.parts
            and target.is_relative_to(plugin),
            "query-execution-source-path-invalid",
            403,
        )
        selected_paths[relative] = target
    observed = set()
    for name, module in tuple(sys.modules.items()):
        if name.split(".")[0] not in names:
            continue
        expected = cli.joinpath(*name.split("."))
        expected = (
            expected / "__init__.py"
            if expected.is_dir()
            else expected.with_suffix(".py")
        )
        require(
            getattr(module, "__file__", None) == str(expected),
            "query-execution-module-origin-differs",
            403,
        )
        relative = "cli/" + expected.relative_to(cli).as_posix()
        require(relative in files, "query-execution-module-unpinned", 403)
        # The bootstrap helper is itself raw pinned by the trusted owner before
        # constructing this loader; all subsequently owned modules must use it.
        if name != "research_workspace_native.atlas_local_source":
            loader = getattr(module, "__loader__", None)
            require(
                isinstance(loader, PinnedLoader)
                and loader.root == cli
                and loader.files == files
                and loader.paths.get(name) == expected
                and getattr(getattr(module, "__spec__", None), "origin", None)
                == str(expected),
                "query-execution-raw-loader-required",
                403,
            )
        observed.add(name)
    require(
        {
            "research_workspace_native.planned_queries",
            "research_workspace_native.query_execution_source",
            "research_workspace_native.planned_query_contract",
            "research_workspace_native.query_storage",
            "stage1_retrieval.runner",
        }.issubset(observed),
        "query-execution-required-module-missing",
        403,
    )
    checked = set()  # Ancestors only cached within this one invocation.
    for relative, expected_sha in files.items():
        target = selected_paths[relative]
        for ancestor in (target, *target.parents):
            if ancestor not in checked:
                info = ancestor.lstat()
                require(
                    not stat.S_ISLNK(info.st_mode)
                    and not getattr(info, "st_file_attributes", 0) & 0x400,
                    "query-execution-source-link-refused",
                    403,
                )
                checked.add(ancestor)
        require(
            stat.S_ISREG(target.stat().st_mode),
            "query-execution-source-not-regular",
            403,
        )
        with target.open("rb") as stream:
            raw = stream.read(32 * 1024 * 1024 + 1)
        require(
            len(raw) <= 32 * 1024 * 1024 and sha(raw) == expected_sha,
            "query-execution-source-bytes-differ",
            403,
        )
    if executor is not None:
        require(
            getattr(executor, "__module__", None) == "stage1_retrieval.runner"
            and getattr(getattr(executor, "__code__", None), "co_filename", None)
            == str(cli / "stage1_retrieval/runner.py"),
            "query-execution-runner-origin-differs",
            403,
        )
    return True
