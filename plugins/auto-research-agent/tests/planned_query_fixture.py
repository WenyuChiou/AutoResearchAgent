"""Neutral saved-intake fixture; fake executable is never launched."""

from copy import deepcopy
from pathlib import Path
import tempfile
import shutil
import time
from types import SimpleNamespace
import unittest
from unittest.mock import patch

import stage1_retrieval.runner as runner

from stage1_brief.brief import create_brief, compile_confirmed
from stage1_brief.formal_target import prepare_formal_intake, submit_formal_target
from stage1_coverage.run import CoverageLedger
from stage1_deliverable.common import canonical, sha
from stage1_ledger.store import Ledger
from stage1_retrieval.runtime_identity import verify_identity
from research_workspace_native.planned_query_contract import tree_sha
from test_research_brief import brief, search_request
from test_research_brief_formal_target import answer
from test_retrieval_execution import PLUGIN, synthetic_audit


RAW_SOURCE_PROOF = None


def get_source_proof():
    if RAW_SOURCE_PROOF is None:
        raise RuntimeError("fresh raw-loader child required")
    return deepcopy(RAW_SOURCE_PROOF)


def saved_pin(root):
    code = root / "code"
    code.mkdir()
    executable, script = code / "fake-python.exe", code / "cli.py"
    executable.write_bytes(b"not-an-executable: test-only")
    script.write_bytes(b"raise RuntimeError('never execute fixture')\n")
    prefix = [str(executable), "-I", "-B", str(script)]
    files = {str(p): sha(p.read_bytes()) for p in (executable, script)}
    config = root / "config.json"
    config.write_bytes(b"{}")
    identity = dict(
        scope="isolated-python-import-paths-and-entry-tree",
        mode="script",
        argv_prefix=prefix,
        entry=str(script),
        roots={str(code): True},
        files=files,
        absent_paths=[],
        files_sha256=sha(canonical(files)),
    )
    return dict(
        code_identity=identity,
        schema_version="1.0.0",
        revision="a" * 40,
        status="merged",
        version="synthetic-label-only",
        wheel_sha256="b" * 64,
        audit_schema_sha256=sha(
            (PLUGIN / "schemas/research-hub-audit.v1.schema.json").read_bytes()
        ),
        executable_sha256=files[str(executable)],
        argv_prefix=prefix,
        config=dict(path=str(config), sha256=sha(b"{}")),
        cwd=str(root),
        timeout_seconds=2,
    )


class QueryCase(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="pq-")
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name).resolve()
        self.pin = saved_pin(self.root)
        pending = prepare_formal_intake(
            brief("unrestricted"),
            project_id="project-a",
            input_version="1" * 64,
            request_id="request-1",
        )
        submitted = answer(37)
        submitted.update(input_version="1" * 64, user_input="Use 37 distinct works.")
        self.brief = self.root / "brief.json"
        create_brief(submit_formal_target(pending, submitted), self.brief)
        self.plan = self.root / "plan"
        compile_confirmed(
            self.brief, search_request(), self.plan, as_of="2026-09-26", actor="test"
        )
        self.ledger_root = self.root / "ledger"
        # Replace the readonly Python probe only; preserve all runtime byte guards.
        with patch(
            "stage1_retrieval.runtime_identity.verify_identity",
            side_effect=lambda pin, **kw: verify_identity(pin),
        ):
            Ledger.create(
                self.ledger_root,
                run_id="synthetic",
                objective=search_request()["proposal"]["topic"],
                research_hub_pin=self.pin,
            )
        self.ledger = CoverageLedger(self.ledger_root)
        self.ledger.bind_plan(self.plan, backends=["openalex"], limit=3)
        self.ledger.open_round()
        self.parent_ledger = self.root / "parent-ledger"
        shutil.copytree(self.ledger_root, self.parent_ledger)
        self.source_proof = self.root / "query-execution-source-proof"
        self.source_proof.write_bytes(
            b"synthetic-source-owner-proof; not production attestation"
        )
        self.item = dict(
            project_id="project-a",
            index_sha256="2" * 64,
            input_version="1" * 64,
            brief_path=str(self.brief),
            brief_sha256=sha(self.brief.read_bytes()),
            plan_root=str(self.plan),
            plan_sha256=tree_sha(self.plan),
            ledger_root=str(self.ledger_root),
            ledger_manifest_sha256=sha(
                (self.ledger_root / "run_manifest.json").read_bytes()
            ),
            runtime_sha256=sha(canonical(self.pin)),
            execution_source_sha256=sha(canonical(get_source_proof()["files"])),
            execution_source_root=Path(get_source_proof()["repo"]).as_posix(),
            permit_path=str(self.root / "permit.json"),
            permit_sha256=None,
            principals=["researcher"],
            control_store_path=(self.root / "query.sqlite3").as_posix(),
            parent_ledger_root=str(self.parent_ledger),
            parent_ledger_sha256=tree_sha(self.parent_ledger),
        )
        self.permit = dict(
            kind="Stage1PlannedQueryPermit",
            schema_version="1.0.0",
            project_ref="case",
            binding={
                k: self.item[k]
                for k in (
                    "project_id",
                    "index_sha256",
                    "input_version",
                    "brief_sha256",
                    "plan_sha256",
                    "ledger_manifest_sha256",
                    "runtime_sha256",
                    "execution_source_sha256",
                    "execution_source_root",
                    "control_store_path",
                    "parent_ledger_sha256",
                )
            },
            principals=["researcher"],
            planned_ids=list(self.ledger.coverage_state().queries)[:2],
            backends=["openalex"],
            max_attempts=2,
            max_reserved_seconds=64,
            max_results=3,
            timeout_seconds=2,
            expires_at_unix=int(time.time()) + 600,
            allow_search=True,
        )
        self.write_permit()
        self.children, self.services = [], []
        self.addCleanup(self.close_services)

    def write_permit(self):
        Path(self.item["permit_path"]).write_bytes(canonical(self.permit))
        self.item["permit_sha256"] = sha(canonical(self.permit))

    def close_services(self):
        for service in reversed(self.services):
            service.close()

    def service(
        self, *, admit=lambda event: True, executor=runner.execute, verify_source=None
    ):
        from research_workspace_native.planned_queries import PlannedQueryService

        service = PlannedQueryService(
            self.root / "query.sqlite3",
            registrations={"case": deepcopy(self.item)},
            authenticate=lambda token: "researcher" if token == "secret" else None,
            admit=admit,
            verify_source=verify_source
            or (
                lambda claim: (
                    get_source_proof()
                    if self.source_proof.read_bytes()
                    == b"synthetic-source-owner-proof; not production attestation"
                    else None
                )
            ),
            executor=executor,
        )
        self.services.append(service)
        return service

    def request(self, service, key="action-1"):
        offer = service.offer("secret", "case")
        return dict(
            key=key,
            revision=offer["revision"],
            index_sha256=self.item["index_sha256"],
            input_version=self.item["input_version"],
            offer_ref=offer["offer_ref"],
            offer_sha256=offer["offer_sha256"],
            confirmed=True,
        )

    def wait(self, service, key="action-1"):
        service._workers["case"].join(30)
        self.assertFalse(service._workers["case"].is_alive(), "bounded offline worker")
        return service.get_action("secret", "case", key)

    def fake_runner(self, mode="rows"):
        original = runner.subprocess
        test = self

        class Child:
            def __init__(self, argv, **options):
                test.assertFalse(options["shell"])
                test.assertEqual(options["stdin"], original.DEVNULL)
                test.children.append(list(argv))
                synthetic_audit(
                    Path(argv[argv.index("--audit-output") + 1]),
                    "openalex",
                    mode,
                    argv[4:],
                )

            def wait(self, timeout=None):
                return 0

        # Local module namespace, avoiding interception of private_output's Git check.
        return patch.object(
            runner,
            "subprocess",
            SimpleNamespace(
                Popen=Child,
                DEVNULL=original.DEVNULL,
                TimeoutExpired=original.TimeoutExpired,
            ),
        )

    def no_probe(self):
        return patch.object(
            runner,
            "verify_identity",
            side_effect=lambda pin, **kw: verify_identity(pin),
        )
