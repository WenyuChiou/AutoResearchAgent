"""Temporary installed-browser citation fixture with authored offline outputs.

Require --temp-root outside the checkout. The first stdout line contains only
url/project_ref. Append inspect or stop to a private control file; a 180-second lease stops
the host. Native, model, network and source-acquisition calls remain absent.
"""

import argparse
from contextlib import ExitStack
from copy import deepcopy
import json
from pathlib import Path
import shutil
import sys
import tempfile
import threading
import traceback
from types import ModuleType
from unittest.mock import patch


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--temp-root", type=Path, required=True)
    parser.add_argument("--control-file", type=Path, required=True)
    args = parser.parse_args()
    tests = Path(__file__).resolve().parent
    repo, original_plugin = tests.parents[2], tests.parent
    if not args.temp_root.is_absolute() or not args.temp_root.is_dir():
        raise ValueError("existing absolute private temp root required")
    temp_root = args.temp_root.resolve(strict=True)
    if temp_root.is_relative_to(repo) or repo.is_relative_to(temp_root):
        raise ValueError("temp root must be separate from the checkout")
    control = args.control_file
    if (
        not control.is_absolute()
        or not control.is_relative_to(temp_root)
        or control.resolve(strict=True) != control
        or not control.is_file()
        or control.stat().st_size != 0
    ):
        raise ValueError("empty private regular control file required")

    with tempfile.TemporaryDirectory(prefix="pex-ui-", dir=temp_root) as directory:
        private = Path(directory).resolve()
        snapshot = private / "source"
        plugin = snapshot / "plugins/auto-research-agent"
        plugin.parent.mkdir(parents=True)
        shutil.copytree(
            original_plugin,
            plugin,
            ignore=shutil.ignore_patterns(
                "__pycache__", "*.pyc", ".ruff_cache", ".pytest_cache"
            ),
        )
        runtime = private / "runtime"
        runtime.mkdir()
        sys.dont_write_bytecode = True
        helper = ModuleType("research_workspace_native.atlas_local_source")
        helper.__file__ = str(
            plugin / "cli/research_workspace_native/atlas_local_source.py"
        )
        exec(
            compile(Path(helper.__file__).read_bytes(), helper.__file__, "exec"),
            helper.__dict__,
        )
        files = helper.inventory(plugin)
        loader = helper.PinnedLoader(snapshot, files)
        helper.__spec__ = loader.find_spec(helper.__name__)
        helper.__loader__ = loader
        helper.__package__ = helper.__name__.rpartition(".")[0]
        sys.meta_path.insert(0, loader)
        sys.modules[helper.__name__] = helper
        sys.path[:0] = [str(plugin / "cli"), str(plugin / "tests")]
        import planned_query_fixture

        planned_query_fixture.RAW_SOURCE_PROOF = {"repo": str(snapshot), "files": files}
        (private / "source-proof.json").write_text(
            json.dumps(planned_query_fixture.RAW_SOURCE_PROOF, sort_keys=True) + "\n",
            encoding="utf8",
        )
        from project_stage1_query_http_cases import ProjectStage1QueryHttpTests
        from research_workspace_native.project_expansions import (
            ProjectStage1ExpansionService,
        )
        from test_project_expansions import ExpansionCases
        from test_stage1_ledger import SYNTHETIC
        from test_workspace_project_intake import bound_body

        http, scenario = ProjectStage1QueryHttpTests(), ExpansionCases()
        output_lock, stop = threading.Lock(), threading.Event()
        errors = []

        def emit(value):
            with output_lock:
                print(
                    json.dumps(value, ensure_ascii=False, allow_nan=False), flush=True
                )

        def inspect():
            worker = scenario.owner._workers.get(http.ref)
            observation = dict(
                present=worker is not None,
                same_owner=http.bridge.services[http.ref] is scenario.owner,
            )
            if worker is not None and worker.ident is not None:
                worker.join(30)
            observation["alive"] = worker is not None and worker.is_alive()
            if observation["alive"]:
                frame = sys._current_frames().get(worker.ident)
                observation["stack"] = traceback.format_stack(frame) if frame else []
            with http.intake._lock:
                state = http.intake._load("local-viewer", http.ref)
                rows = scenario.owner.view(http.token, http.ref)["history"]
                actions = {
                    row["request_sha256"]: row
                    for raw in http.intake.db.execute(
                        "SELECT receipt FROM intake_actions WHERE principal=? AND project=?",
                        ("local-viewer", http.ref),
                    )
                    if (row := json.loads(raw[0]))["kind"] == "stage1-expansion-execute"
                }
                emit(
                    dict(
                        children=len(http.children),
                        query_worker=observation,
                        budget=deepcopy(state["stage1_query_budget"]),
                        grants=[
                            dict(
                                operation=record["permit"]["document"]["operation"],
                                status="consumed"
                                if digest in state.get("stage1_expansion_uses", {})
                                else "permission-saved",
                            )
                            for digest, record in state.get(
                                "stage1_expansion_grants", {}
                            ).items()
                        ],
                        intents=[
                            dict(
                                operation=row["offer"]["operation"],
                                status=row["status"],
                                outcome=(row.get("result") or {}).get(
                                    "backend_outcome"
                                ),
                                outer_status=actions.get(row["client_key"][8:], {}).get(
                                    "status"
                                ),
                            )
                            for row in rows
                            if row["method"] == "stage1/expansion"
                        ],
                    )
                )

        def controls():
            try:
                position = 0
                while not stop.wait(0.05):
                    if control.stat().st_size > 16 * 1024:
                        raise ValueError("bounded controls required")
                    with control.open("rb") as stream:
                        stream.seek(position)
                        for line in stream:
                            if not line.endswith(b"\n"):
                                break
                            position += len(line)
                            command = line.strip()
                            if command == b"stop":
                                return
                            if command != b"inspect":
                                raise ValueError("inspect or stop control required")
                            inspect()
            except Exception as error:
                errors.append(error)
            finally:
                stop.set()

        with ExitStack() as stack:
            stack.enter_context(patch.object(tempfile, "tempdir", str(runtime)))
            try:
                # The surrounding finally guarantees cleanup even if setup fails.
                http.setUp()
                original_offered = http.offered

                def offered(field, key):
                    body = original_offered(field, key)
                    if field == "authorization_offer":
                        body["user_input"] = (
                            "Authorize six total offline search/citation attempts within "
                            "300 reserved seconds; no source or model calls."
                        )
                    return body

                http.offered, http.body, http.queries = offered, offered, http.bridge
                http.bridge.config["caps"].update(
                    max_attempts=6, max_reserved_seconds=300
                )
                settings = http.intake._load("local-viewer", http.ref)["settings"]
                http.post(
                    http.base + "/configure",
                    dict(
                        bound_body(http.get(http.base), "browser-offline-budget"),
                        resource_envelope="Authored offline browser fixture: six shared attempts, no source or model calls.",
                        budgets=dict(settings["budgets"], search_calls=6, seconds=300),
                        consent=deepcopy(settings["consent"]),
                        user_input="Confirm six total synthetic search/citation attempts within 300 reserved seconds.",
                        confirmed=True,
                    ),
                )
                scenario.case, scenario.ref = http, http.ref
                scenario.credential, scenario.principal = http.token, "local-viewer"
                scenario.serial, scenario.seed_record = 0, deepcopy(SYNTHETIC)
                scenario.expansions = ProjectStage1ExpansionService(http.bridge)
                stack.enter_context(scenario.fake_backend())
                stack.enter_context(http.no_probe())
                http.bootstrap()
                scenario.owner = http.bridge.services[http.ref]
                scenario.seed(bootstrapped=True)
                offers = scenario.expansions.read(http.token, http.ref)[
                    "authorization_offers"
                ]
                if {row["document"]["operation"] for row in offers} != {
                    "references",
                    "cited-by",
                }:
                    raise RuntimeError(
                        "both exact citation directions must be available"
                    )
                emit(
                    dict(
                        url=http.host.expected_origin + "/projects.html",
                        project_ref=http.ref,
                    )
                )
                control_worker = threading.Thread(target=controls, daemon=True)
                control_worker.start()
                stop.wait(180)
                stop.set()
                control_worker.join(6)
                if control_worker.is_alive():
                    raise RuntimeError("control worker cleanup incomplete")
                if errors:
                    raise errors[0]
            finally:
                stop.set()
                cleaned = http.doCleanups()
                cleaned = scenario.doCleanups() and cleaned
                if not cleaned:
                    raise RuntimeError("browser fixture cleanup failed")


if __name__ == "__main__":
    main()
