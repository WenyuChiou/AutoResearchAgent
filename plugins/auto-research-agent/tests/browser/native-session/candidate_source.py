"""Bind this synthetic fixture to one complete checkout's Python source bytes.

This is not native-process authentication or a third-party dependency attestation.
Use in a fresh fixture process, before importing any of the owned modules.
"""

import hashlib
import importlib
from importlib.abc import Loader, MetaPathFinder
from importlib.util import spec_from_file_location
from pathlib import Path
import sys

PACKAGES = frozenset(
    (
        "research_workspace_native",
        "stage1_deliverable",
        "stage1_brief",
        "stage1_coverage",
        "stage1_ledger",
    )
)
HELPERS = frozenset(
    "test_research_workspace_native_" + name
    for name in ("controller", "session_api", "scope_api")
)
BASE = (
    ("research_workspace_native", "stage1_deliverable", "stage1_deliverable.common")
    + tuple(
        "research_workspace_native." + name
        for name in (
            "controller",
            "frame_journal",
            "journal",
            "store",
            "recording",
            "transport",
            "write_observation",
            "session_api",
            "http",
            "wiki_http",
        )
    )
    + (
        "test_research_workspace_native_controller",
        "test_research_workspace_native_session_api",
    )
)
SCOPE = (
    "stage1_brief",
    "stage1_brief.brief",
    "stage1_coverage",
    "stage1_coverage.plan",
    "stage1_ledger",
    "stage1_ledger.journal",
    "research_workspace_native.scope_api",
    "research_workspace_native.scope_http",
    "test_research_workspace_native_scope_api",
)


class CandidateSources(MetaPathFinder, Loader):
    def __init__(self, repo, scope=False):
        requested = Path(repo)
        if not requested.is_absolute():
            raise ValueError("candidate repo must be absolute")
        self.repo = requested.resolve(strict=True)
        self.plugin = self.repo / "plugins/auto-research-agent"
        self.sources = {}
        self.required = BASE + (SCOPE if scope else ())
        if not (self.plugin / "cli").is_dir() or not (self.plugin / "tests").is_dir():
            raise ValueError("candidate CLI and test directories are required")
        if any(self.owns(name) for name in sys.modules):
            raise ValueError("candidate modules already loaded; use a fresh process")
        for name in self.required:
            self.capture(name)

    @staticmethod
    def owns(name):
        return name.split(".")[0] in PACKAGES or name in HELPERS

    def capture(self, name):
        if name in self.sources:
            return self.sources[name]
        base = self.plugin / ("tests" if name in HELPERS else "cli")
        relative = Path(*name.split("."))
        module, package = (
            base / relative.with_suffix(".py"),
            base / relative / "__init__.py",
        )
        paths = [path for path in (module, package) if path.is_file()]
        if len(paths) != 1:
            raise ValueError("missing or ambiguous candidate module: " + name)
        path = paths[0]
        if path.resolve(strict=True) != path or not path.is_relative_to(self.repo):
            raise ValueError("linked candidate source is not allowed: " + name)
        raw = path.read_bytes()
        self.sources[name] = (path, raw, path == package)
        return self.sources[name]

    def find_spec(self, fullname, path=None, target=None):
        if not self.owns(fullname):
            return None
        source, _, package = self.capture(fullname)
        return spec_from_file_location(
            fullname,
            source,
            loader=self,
            submodule_search_locations=[str(source.parent)] if package else None,
        )

    def create_module(self, spec):
        return None

    def exec_module(self, module):
        source, raw, _ = self.capture(module.__name__)
        exec(compile(raw, str(source), "exec", dont_inherit=True), module.__dict__)

    def verify(self):
        loaded = {name for name in sys.modules if self.owns(name)}
        if loaded != set(self.sources):
            raise ValueError("candidate module inventory differs")
        for name, (source, raw, package) in self.sources.items():
            module = sys.modules[name]
            if (
                Path(module.__file__) != source
                or module.__spec__.origin != str(source)
                or module.__spec__.loader is not self
                or (package and list(module.__path__) != [str(source.parent)])
                or source.resolve(strict=True) != source
                or source.read_bytes() != raw
            ):
                raise ValueError("candidate module origin or bytes differ: " + name)

    def receipt(self):
        self.verify()
        return dict(
            repo=str(self.repo),
            modules={
                name: dict(path=str(path), sha256=hashlib.sha256(raw).hexdigest())
                for name, (path, raw, _) in sorted(self.sources.items())
            },
        )


def load_candidate(repo, scope=False):
    """Import required source snapshots; a missing module cannot fall back elsewhere."""
    bound = CandidateSources(repo, scope)
    sys.meta_path.insert(0, bound)
    try:
        for name in bound.required:
            importlib.import_module(name)
        bound.verify()
    except BaseException:
        sys.meta_path.remove(bound)
        raise
    return bound
