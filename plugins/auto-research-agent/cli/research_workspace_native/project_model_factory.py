"""Pinned own-account content-unit preparation; no automatic native start.

Production imports must already come from the existing fresh-process
``atlas_local_source.PinnedLoader``. Its bootstrap recipe is: raw-compile the
externally pinned helper, inventory the plugin, install PinnedLoader(repo,
files) in sys.meta_path, then import this module and the project host. Normal,
preloaded and mixed owned imports are refused. This freezes a project input
snapshot, not a canonical WorkspaceIndex or research-stage completion.
"""

from contextlib import contextmanager
from copy import deepcopy
import os
from pathlib import Path
import re
import sys
import tomllib

from stage1_brief.brief import validate_brief
from stage1_deliverable.common import private_output
from . import atlas_local_source as source
from .runtime_spec import DENIED_THREAD_CONFIG, _thread_config
from .stage_inputs import snapshot_inputs, source_digest
from .stage_model import StageModel
from .project_model_reading import READ_OPERATION, reading_prompt
from .project_stage1_review_units import (
    OPERATION as AUTO_REVIEW,
    prompt as automatic_review_prompt,
)

MAX_CONTEXT = 65536
HASH = re.compile(r"[0-9a-f]{64}")


def _save(path, raw):
    with path.open("xb") as stream:
        stream.write(raw)
        stream.flush()
        os.fsync(stream.fileno())
    return source.digest(raw)


class _CheckedSource:
    """Keep origin checks inside the StageModel's own per-I/O source checks."""

    def __init__(self, verify):
        self.verify = verify

    @contextmanager
    def verification_pass(self):
        """One bounded source check; no verification result survives this pass."""
        self.verify()
        try:
            yield source
        finally:
            self.verify()

    def __getattr__(self, name):
        callback = getattr(source, name)
        if not callable(callback):
            return callback

        def checked(*args, **kwargs):
            self.verify()
            return callback(*args, **kwargs)

        return checked


class _GuardedStageModel:
    def __init__(self, model, verify):
        self.model, self.verify = model, verify

    def run(self, key, prompt, deadline):
        self.verify()
        return self.model.run(key, prompt, deadline)

    def verify_receipt(self, receipt, **expected):
        self.verify()
        return self.model.verify_receipt(receipt, **expected)

    def status(self):
        self.verify()
        return self.model.status()

    def answer(self, body, *, pre_admission=None):
        self.verify()
        source.require(callable(pre_admission), "trusted answer admission required")
        return self.model.answer(body, pre_admission=pre_admission)

    def interrupt(self, body, *, pre_admission=None):
        self.verify()
        source.require(callable(pre_admission), "trusted interrupt admission required")
        return self.model.interrupt(body, pre_admission=pre_admission)

    def close(self):
        # Cleanup must still be attempted if a source/config pin changed.
        error = None
        try:
            self.verify()
        except Exception as failure:
            error = failure
        result = self.model.close()
        if error is not None:
            raise error
        return result


class OwnAccountProjectModelFactory:
    """Trusted broker callable; constructing this object launches no process.

    ``stage_model_factory`` is an explicit synthetic-test seam. Production uses
    StageModel plus raw PinnedLoader imports. Neither constructor authenticates
    a Codex account, reserves calls, grants source/search access, or probes it.
    """

    def __init__(
        self,
        repo,
        executable,
        user_config,
        account_config_root,
        authenticate,
        credential,
        *,
        stage_model_factory=None,
    ):
        source.require(callable(authenticate), "trusted authentication required")
        source.require(
            authenticate(credential) == "local-viewer", "same local principal required"
        )
        source.require(
            stage_model_factory is None or callable(stage_model_factory),
            "trusted StageModel factory required",
        )
        self.factory = (
            StageModel if stage_model_factory is None else stage_model_factory
        )
        self.test_seam = stage_model_factory is not None
        self.authenticate, self.credential = authenticate, credential
        self.repo = source.unlinked(repo).resolve()
        self.plugin = self.repo / "plugins/auto-research-agent"
        self.cli = self.plugin / "cli"
        source.require(self.cli.is_dir(), "complete plugin checkout required")
        self.executable = source.unlinked(executable).resolve()
        source.require(
            self.executable.name.casefold() in {"codex", "codex.exe"},
            "explicit installed Codex executable required",
        )
        self.home = source.unlinked(account_config_root).resolve()
        self.user_path = source.unlinked(user_config).resolve()
        source.require(
            self.home.is_dir() and self.user_path == self.home / "config.toml",
            "explicit own-account config.toml required",
        )
        self.user_sha256 = source.digest(source.read(self.user_path))
        names = tomllib.loads(source.read(self.user_path).decode("utf8")).get(
            "mcp_servers", {}
        )
        source.require(
            type(names) is dict and len(names) <= 64, "bounded MCP names required"
        )
        self.thread_config = _thread_config(
            {
                **DENIED_THREAD_CONFIG,
                **{f"mcp_servers.{name}.enabled": False for name in names},
            }
        )
        self.executable_sha256 = source.digest(
            source.read(self.executable, 512 * 1024 * 1024)
        )
        self.plugin_files = source.inventory(self.plugin)
        self.names = {
            path.name
            for path in self.cli.iterdir()
            if path.is_dir() and (path / "__init__.py").is_file()
        } | {path.stem for path in self.cli.glob("*.py")}
        self.loader = getattr(sys.modules[__name__], "__loader__", None)
        if not self.test_seam:
            source.require(
                isinstance(self.loader, source.PinnedLoader)
                or (
                    type(self.loader).__name__ == "PinnedLoader"
                    and Path(getattr(self.loader, "root", "")) == self.cli
                    and getattr(self.loader, "files", None) == self.plugin_files
                ),
                "fresh raw PinnedLoader process required",
            )
            source.require(
                self.loader in sys.meta_path
                and self.loader.root == self.cli
                and self.loader.files == self.plugin_files,
                "raw loader inventory differs",
            )
        self._guard()

    def _owned_origins(self):
        owned = [
            (name, module)
            for name, module in tuple(sys.modules.items())
            if name.split(".")[0] in self.names
        ]
        source.require(len(owned) <= 1024, "owned module bound exceeded")
        for name, module in owned:
            path = self.cli.joinpath(*name.split("."))
            package = path.is_dir()
            path = path / "__init__.py" if package else path.with_suffix(".py")
            spec = getattr(module, "__spec__", None)
            source.require(
                module is not None
                and spec is not None
                and getattr(module, "__file__", None) == str(path)
                and spec.origin == str(path),
                "owned module origin differs",
            )
            relative = "cli/" + path.relative_to(self.cli).as_posix()
            source.require(
                relative in self.plugin_files, "owned module is not inventoried"
            )
            source.pinned(path, self.plugin_files[relative], 32 * 1024 * 1024)
            if package:
                source.require(
                    list(getattr(module, "__path__", ())) == [str(path.parent)]
                    and list(spec.submodule_search_locations or ())
                    == [str(path.parent)],
                    "owned package paths differ",
                )
            if not self.test_seam:
                source.require(
                    module.__loader__ is self.loader and spec.loader is self.loader,
                    "normal mixed or cached owned import refused",
                )

    def _guard(self):
        effective = source.unlinked(
            os.environ.get("CODEX_HOME") or Path.home() / ".codex"
        ).resolve()
        source.require(effective == self.home, "inherited account config root changed")
        source.require(
            self.authenticate(self.credential) == "local-viewer",
            "local principal changed",
        )
        source.pinned(self.user_path, self.user_sha256)
        source.pinned(self.executable, self.executable_sha256, 512 * 1024 * 1024)
        source.require(
            source.inventory(self.plugin) == self.plugin_files,
            "project model plugin inventory changed",
        )
        if not self.test_seam:
            source.require(
                self.loader in sys.meta_path and self.loader.files == self.plugin_files,
                "raw loader no longer installed",
            )
        self._owned_origins()

    def __call__(self, *, context, admit, output_root):
        self._guard()
        source.require(
            callable(admit) and type(context) is dict, "trusted broker context required"
        )
        context = deepcopy(context)
        source.require(
            len(source.canonical(context)) <= MAX_CONTEXT,
            "model context bound exceeded",
        )
        for name in ("brief_sha256", "source_sha256", "permit_sha256"):
            source.require(
                type(context.get(name)) is str and HASH.fullmatch(context[name]),
                "project input hashes required",
            )
        source.require(
            source.digest(
                source.canonical(
                    {k: v for k, v in context.items() if k != "source_sha256"}
                )
            )
            == context["source_sha256"],
            "project context source hash differs",
        )
        source.require(
            type(context.get("input_version")) is int
            and context["input_version"] > 0
            and type(context.get("project_id")) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", context["project_id"])
            and type(context.get("project_ref")) is str
            and re.fullmatch(r"[A-Za-z0-9_-]{1,64}", context["project_ref"])
            and type(context.get("model")) is str
            and re.fullmatch(r"[A-Za-z0-9_.:-]{1,128}", context["model"]),
            "explicit project version and model required",
        )
        source.require(
            context.get("deny_only") is True
            and context.get("trusted_stage_unit") is True,
            "deny-only trusted content unit required",
        )
        source.require(
            context.get("operation")
            in {"suggest-topic", "plan-search", READ_OPERATION, AUTO_REVIEW},
            "bounded project content operation required",
        )
        validate_brief(
            context["brief"],
            require_confirmed=context.get("operation") != "suggest-topic",
        )
        if context["brief"]["schema_version"] == "1.1.0":
            source.require(
                context["brief"].get("project_id") == context["project_id"]
                and type(context["brief"].get("input_version")) is int
                and context["brief"]["input_version"] == context["input_version"],
                "formal brief project version differs",
            )
        raw_brief = source.canonical(context["brief"]) + b"\n"
        source.require(
            source.digest(raw_brief) == context["brief_sha256"],
            "raw brief bytes differ",
        )
        source.require(
            type(context.get("settings")) is dict
            and context["settings"].get("brief_sha256") == context["brief_sha256"],
            "settings brief version differs",
        )
        if context["operation"] == READ_OPERATION:
            snapshot = context.get("saved_reading")
            source.require(
                type(snapshot) is dict
                and snapshot.get("kind") == "Stage1SavedTextReadingInput"
                and snapshot.get("schema_version") == "1.0.0"
                and snapshot.get("model_creates_core_claims") is False
                and snapshot.get("scientific_acceptance") is False
                and snapshot.get("work_id") == context.get("work_ref")
                and all(
                    snapshot.get(name) == context[name]
                    for name in (
                        "project_ref",
                        "project_id",
                        "input_version",
                        "brief_sha256",
                    )
                )
                and source.digest(source.canonical(snapshot))
                == context.get("snapshot_sha256")
                and source.digest(reading_prompt(snapshot).encode("utf8"))
                == context.get("prompt_sha256"),
                "saved reading source or prompt binding differs",
            )
        elif context["operation"] == AUTO_REVIEW:
            snapshot = context.get("saved_reading")
            source.require(
                type(snapshot) is dict
                and snapshot.get("kind") == "Stage1AutomaticReviewInput"
                and snapshot.get("schema_version") == "1.0.0"
                and snapshot.get("scientific_acceptance") is False
                and snapshot.get("human_acceptance") is False
                and snapshot.get("task_ref") == context.get("task_ref")
                and snapshot.get("work_id") == context.get("work_ref")
                and all(
                    snapshot.get(name) == context[name]
                    for name in (
                        "project_ref",
                        "project_id",
                        "input_version",
                        "brief_sha256",
                    )
                )
                and source.digest(source.canonical(snapshot))
                == context.get("snapshot_sha256")
                and source.digest(automatic_review_prompt(snapshot).encode("utf8"))
                == context.get("prompt_sha256"),
                "automatic reading source or prompt binding differs",
            )
        output = private_output(source.unlinked(output_root).resolve())
        source.require(
            not output.exists() and output.parent.is_dir(),
            "fresh output parent required",
        )
        input_root = private_output(output.parent / "project-model-input")
        source.require(
            not input_root.exists()
            and not output.is_relative_to(self.repo)
            and not self.repo.is_relative_to(output)
            and not input_root.is_relative_to(output)
            and not output.is_relative_to(input_root),
            "source output overlap or reuse refused",
        )
        for ancestor in (input_root, *input_root.parents):
            layer = ancestor / ".codex/config.toml"
            source.require(
                not layer.exists()
                or source.unlinked(layer).resolve() == self.user_path,
                "additional project config layer refused",
            )
        input_root.mkdir()
        brief_path, index_path, config_path = (
            input_root / name
            for name in ("brief.json", "input-snapshot.json", "model-context.json")
        )
        _save(brief_path, raw_brief)
        if context["operation"] == READ_OPERATION:
            _save(
                input_root / "saved-reading.json",
                source.canonical(context["saved_reading"]) + b"\n",
            )
        index_sha = _save(
            index_path,
            source.canonical(
                dict(
                    kind="ProjectModelInputSnapshot",
                    schema_version="1.0.0",
                    project_id=context["project_id"],
                    project_ref=context["project_ref"],
                    input_version=context["input_version"],
                    brief_sha256=context["brief_sha256"],
                    settings_sha256=source.digest(
                        source.canonical(context["settings"])
                    ),
                    source_sha256=context["source_sha256"],
                    permit_sha256=context["permit_sha256"],
                    model=context["model"],
                    canonical_workspace_index=False,
                    canonical_stage1_handoff=False,
                    execution_authorized=False,
                )
            )
            + b"\n",
        )
        config_sha = _save(config_path, source.canonical(context) + b"\n")
        stage_inputs = {1: None, 2: None}
        manifest = dict(
            kind="LocalProjectModelByteInventory",
            repo_root=self.repo.as_posix(),
            source_root=input_root.as_posix(),
            plugin_files=deepcopy(self.plugin_files),
            source_files=source.inventory(input_root),
        )
        checked = dict(
            source=_CheckedSource(self._owned_origins),
            repo=self.repo,
            manifest=manifest,
            source_root=input_root,
            project_id=context["project_id"],
            index_path=index_path,
            index_sha256=index_sha,
            input_path=brief_path,
            input_version=context["brief_sha256"],
            thread_config=deepcopy(self.thread_config),
            stage_inputs=stage_inputs,
            stage_source_sha256=source_digest(snapshot_inputs(stage_inputs)),
            config_path=config_path,
            user_path=self.user_path,
            executable=self.executable,
        )

        def verify():
            self._guard()
            source.require(
                source.inventory(input_root) == manifest["source_files"],
                "frozen model input changed",
            )

        def guarded_admit(event):
            verify()
            return admit(event) is True

        verify()
        model = self.factory(
            checked,
            model=context["model"],
            permit_sha256=context["permit_sha256"],
            source_sha256=context["source_sha256"],
            executable_sha256=self.executable_sha256,
            user_config_sha256=self.user_sha256,
            config_sha256=config_sha,
            authenticate=self.authenticate,
            credential=self.credential,
            admit=guarded_admit,
            output_root=output,
            project_ref=context["project_ref"],
            trusted_stage_unit=True,
        )
        return _GuardedStageModel(model, verify)
