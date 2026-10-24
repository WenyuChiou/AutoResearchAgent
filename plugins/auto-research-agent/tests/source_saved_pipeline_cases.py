"""Authored transport child plus unchanged actual SDK/Core/query SQLite.

The source launcher replacement below authors raw HTML and public peer fields.
It is not actual HTTP/DNS/acquisition evidence. The parser launcher is ORIGINAL,
so SDK import-saved and its Windows Job run with real runtime/source guards.
Query fixture probes/backend remain explicitly authored, with real reservations.
Only the new exact method is selected; inherited query scenarios are not run.
Source materials remain retained outside Git; this case never removes them.
"""

from copy import deepcopy
from contextlib import ExitStack
from datetime import datetime
import json
from pathlib import Path
import tempfile
from unittest.mock import patch

from research_hub import source_fetch_saved

import test_retrieval_execution as query_inputs
from project_stage1_query_cases import ProjectQueryCases
from planned_query_fixture import get_source_proof
from research_workspace_native.portable_source_worker_profile import (
    prepare_source_worker_profile,
    register_source_worker,
)
from research_workspace_native.project_resource_budget import resource_view
from research_workspace_native.project_source_saved_pipeline import SourceSavedPipeline
from research_workspace_native.project_stage1_delivery import (
    ProjectStage1DeliveryService,
)
from research_workspace_native.project_stage1_records import ProjectStage1RecordsService
from research_workspace_native.saved_source_parser_factory import (
    ContainedSavedSourceParserFactory,
    prepare_saved_parser_runtime,
)
from research_workspace_native.source_worker_process import WindowsJobProcess
from stage1_ledger.validation import validate_run
from research_workspace_native.project_stage1_run_grant import (
    ProjectStage1RunGrantService,
    SCOPE,
)
from research_workspace_native.project_run_authority import action_identity
from test_workspace_project_intake import bound_body, compile_body, submit_body


AUTHORED_CHILD = r"""
import hashlib, json, sys
from datetime import datetime, timezone
from pathlib import Path
def canonical(value):
    return json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':')).encode()
def sha(raw): return hashlib.sha256(raw).hexdigest()
launch=json.loads(Path(sys.argv[1]).read_text(encoding='utf8'))
request=launch['request']
def frame(sequence,kind,**values):
    row=dict(sequence=sequence,kind=kind,request_sha256=launch['request_sha256'],config_sha256=launch['config_sha256'],**values)
    sys.stdout.buffer.write(canonical(row)+b'\n');sys.stdout.buffer.flush()
for number,phase in enumerate(('before-transport','before-dns','after-dns')):
    frame(number,'gate',phase=phase)
    admitted=json.loads(sys.stdin.buffer.readline())
    assert admitted==dict(kind='admit',sequence=number,request_sha256=launch['request_sha256'],config_sha256=launch['config_sha256'])
root=Path(launch['output_dir']);(root/'raw').mkdir(parents=True)
began=datetime.now(timezone.utc).isoformat()
raw=(b'<html><head><title>Authored pipeline fixture</title></head><body><article><h1>Authored pipeline fixture</h1><h2>Introduction</h2><p>'
    + b'An authored local pipeline fixture describes synthetic observations. '*60
    + b'</p><h2>Results</h2><p>'+b'Synthetic results are for an offline engineering case. '*60+b'</p></article></body></html>')
(root/'raw/001-response.html').write_bytes(raw)
ended=datetime.now(timezone.utc).isoformat()
attempt=dict(sequence=1,url=request['source_uri'],started_at=began,finished_at=ended,
    resolved_addresses=['93.184.216.34'],selected_address='93.184.216.34',peer_address='93.184.216.34',http_request_attempted=True,
    http_status=200,content_type='text/html',outcome='http-body-complete',raw_path='raw/001-response.html',raw_sha256=sha(raw),
    body_bytes=len(raw),body_complete=True,error_code=None)
receipt=dict(kind='PublicSourceAcquisitionReceipt',schema_version='1.0.0',request=request,request_sha256=sha(canonical(request)),
    output_dir=str(root),started_at=began,finished_at=ended,status='completed',outcome='http-body-complete',final_url=request['source_uri'],
    http_attempts=1,http_requests_attempted=1,aggregate_bytes=len(raw),attempts=[attempt],selected_attempt_sequence=1,
    **{name:attempt[name] for name in ('raw_path','raw_sha256','content_type','body_bytes','body_complete')})
target=root/'public-source-acquisition.json';target.write_bytes(canonical(receipt)+b'\n')
frame(3,'terminal',status='receipt-observed',receipt_path=target.name,receipt_sha256=sha(target.read_bytes()))
"""


class SourceSavedPipelineCases(ProjectQueryCases):
    def _pipeline_fixture(self, *, derived=False, revoke_after=None):
        # New explicit fixture submission, before any query permit/job. Original
        # fixture brief and all later original receipts remain untouched.
        body = submit_body(self.intake.read("alice-token", self.ref))
        body["key"] = "source-pipeline-submit"
        body["budgets"].update(seconds=600, source_reads=3, search_calls=2, rounds=1)
        body["consent"]["external_search"] = True
        body["consent"]["public_source_read"] = True
        body["resource_envelope"] = (
            "Authored offline pipeline: fake transport/query, actual local SDK/Core only."
        )
        self.intake.submit("alice-token", self.ref, body)
        plan = compile_body(self.intake.read("alice-token", self.ref))
        plan["key"] = "source-pipeline-compile"
        self.intake.compile("alice-token", self.ref, plan)
        self.authorize()
        self.bootstrap()
        row = deepcopy(query_inputs.SYNTHETIC)
        row.update(
            doi="10.5555/source-pipeline-authored", title="Authored pipeline fixture"
        )
        with (
            patch.object(query_inputs, "SYNTHETIC", row),
            self.fake_runner(),
            self.no_probe(),
        ):
            queued = self.queries.execute(
                "alice-token", self.ref, self.body("query_offer", "authored-query")
            )
            self.queries.services[self.ref]._workers[self.ref].join(30)
        self.assertEqual(
            self.queries.services[self.ref].get_action(
                "alice-token", self.ref, queued["query_action_key"]
            )["status"],
            "completed",
        )
        state = self.intake._load("alice", self.ref)
        _, ledger, _ = self.stage1._ledger(state, self.intake.binding(self.ref))
        candidate = next(iter(ledger.candidates().values()))
        self.stage1.screen(
            "alice-token",
            self.ref,
            dict(
                bound_body(
                    self.intake.read("alice-token", self.ref), "authored-screen"
                ),
                ledger_state_sha256=ledger.state_hash(),
                confirmed=True,
                work_ref=candidate["work_id"],
                decision="pending",
                rationale="Authored fixture; no scientific review.",
            ),
        )
        materials = Path(tempfile.mkdtemp(prefix="ssp-")).resolve()
        self.assertTrue(materials.is_dir())
        profile = prepare_source_worker_profile(
            repo=get_source_proof()["repo"],
            materials_root=materials,
            runtime_sha256="1" * 64,
            # The complete raw-pinned SDK/Core/registry path is measured under
            # the unchanged Harness maximum, within this fixture's 600 budget.
            # Earlier 60/120-second reservations remain separate failed runs.
            timeout_seconds=300,
        )
        worker, source_config = register_source_worker(profile)
        runtime = prepare_saved_parser_runtime(
            sdk_root=Path(source_fetch_saved.__file__).parent
        )
        factory = ContainedSavedSourceParserFactory(worker=worker, runtime=runtime)
        delivery = ProjectStage1DeliveryService(self.stage1)
        records = ProjectStage1RecordsService(
            delivery,
            materials_root=materials,
            mutation_guard=self.queries.saved_records_guard,
        )
        pipeline = SourceSavedPipeline(
            self.stage1, records, factory, phase_admission=True
        )
        source_config["pipeline_sha256"] = pipeline.binding_sha256
        sources = worker.create_service(
            self.intake, self.stage1, config=source_config, pipeline=pipeline
        )
        self.addCleanup(sources.close)
        offer = sources.offers("alice-token", self.ref, candidate["work_id"])
        self.assertEqual(offer["document"]["pipeline_sha256"], pipeline.binding_sha256)
        issuer = original_grant = None
        if derived:
            issuer = ProjectStage1RunGrantService(self.intake, runtime_sha256="a" * 64)
            sources.run_grants = issuer
            original_grant = issuer.authorize(
                "alice-token",
                self.ref,
                {
                    **bound_body(
                        self.intake.read("alice-token", self.ref), "pipeline-whole-run"
                    ),
                    "confirmed": True,
                    "user_input": "Authored acquisition; original SDK/Core within saved limits.",
                    "scope": SCOPE,
                    "operations": ["source"],
                    "max_seconds": 540,
                    "max_actions": 8,
                },
            )

        def request(kind, fields, key):
            body = dict(
                bound_body(self.intake.read("alice-token", self.ref), key),
                confirmed=not derived,
                **fields,
            )
            token = None
            if derived:
                token = issuer.derive(
                    "alice-token",
                    self.ref,
                    grant_ref=original_grant["grant_ref"],
                    grant_sha256=original_grant["grant_sha256"],
                    operation="source",
                    identity=action_identity(kind, body),
                )
                body.update(
                    key=token.key + "-work",
                    revision=self.intake.read("alice-token", self.ref)["revision"],
                )
            return body, token

        authorize_body, authorize_token = request(
            "source-authorize",
            dict(
                work_ref=candidate["work_id"],
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
            ),
            "authored-source-grant",
        )
        grant = sources.authorize(
            "alice-token", self.ref, authorize_body, run_authorization=authorize_token
        )
        action, action_token = request(
            "source-execute",
            dict(grant_ref=grant["grant_ref"], grant_sha256=grant["grant_sha256"]),
            "authored-source-run",
        )
        sources.execute("alice-token", self.ref, action, run_authorization=action_token)
        if derived:
            current = sources._row(self.intake._load("alice", self.ref))
            self.assertEqual(
                current["grants"][grant["grant_ref"]]["document"]["schema_version"],
                "1.1.0",
            )
            self.assertFalse(
                current["jobs"][action["key"]]["action_request"]["confirmed"]
            )
            self.assertLessEqual(
                current["jobs"][action["key"]]["binding"]["deadline_at"],
                original_grant["expires_at"],
            )
        revoked = []

        def revoke():
            self.assertTrue(derived)
            self.assertEqual(revoked, [])
            issuer.revoke(
                "alice-token",
                self.ref,
                {
                    **bound_body(
                        self.intake.read("alice-token", self.ref), "pipeline-revoke"
                    ),
                    "grant_ref": original_grant["grant_ref"],
                    "grant_sha256": original_grant["grant_sha256"],
                },
            )
            revoked.append(revoke_after)

        reservation = resource_view(
            self.intake, self.intake._load("alice", self.ref), "alice"
        )["reserved"]
        child = self.root / "authored_source_child.py"
        child.write_text(AUTHORED_CHILD, encoding="utf8", newline="\n")
        original_launch = WindowsJobProcess.launch
        launches = []

        def launch(executable, argv, cwd, env, *, absolute_end, cleanup_end=None):
            control = json.loads(Path(argv[-2]).read_text(encoding="utf8"))
            actual = list(argv)
            synthetic = "parse_saved_manifest" not in control
            if synthetic:
                actual[-3] = str(child)
            launches.append(
                dict(
                    synthetic_transport=synthetic,
                    requested=list(argv),
                    actual=actual,
                    original_end=absolute_end,
                    cleanup_end=cleanup_end,
                )
            )
            return original_launch(
                executable,
                actual,
                cwd,
                env,
                absolute_end=absolute_end,
                cleanup_end=cleanup_end,
            )

        import research_workspace_native.project_source_saved_pipeline as pipeline_module

        actual_parse = pipeline_module.parse_acquired_source
        actual_mutate = self.stage1._mutate
        actual_register = records.register_source
        registered = []

        def parse(*args, **kwargs):
            result = actual_parse(*args, **kwargs)
            if revoke_after == "sdk":
                revoke()
            return result

        def mutate(*args, **kwargs):
            result = actual_mutate(*args, **kwargs)
            if revoke_after == "core" and args[3] == "stage1-import-saved":
                revoke()
            return result

        def register(*args, **kwargs):
            result = actual_register(*args, **kwargs)
            registered.append(deepcopy(result))
            if revoke_after == "registry":
                revoke()
            return result

        before_sources = [
            row
            for row in ledger.events()
            if row["payload"]["kind"] == "SourceReadStarted"
        ]
        with ExitStack() as stack:
            stack.enter_context(
                patch.object(WindowsJobProcess, "launch", side_effect=launch)
            )
            if revoke_after:
                stack.enter_context(
                    patch.object(
                        pipeline_module, "parse_acquired_source", side_effect=parse
                    )
                )
                stack.enter_context(
                    patch.object(self.stage1, "_mutate", side_effect=mutate)
                )
                stack.enter_context(
                    patch.object(records, "register_source", side_effect=register)
                )
            saved = sources.dispatch_pending("alice-token", self.ref, action["key"])
        if revoke_after:
            self.assertEqual(revoked, [revoke_after])
            self.assertEqual(saved["status"], "source-observation-saved", saved)
            followup = saved["followup"]
            self.assertEqual(followup["status"], "execution-unknown", saved)
            self.assertEqual(
                followup["failure"]["error_code"], "stage1-run-grant-revoked", saved
            )
            self.assertFalse(followup["automatic_retry"])
            self.assertEqual(
                [item["synthetic_transport"] for item in launches], [True, False]
            )
            self.assertTrue(worker.observations[-1]["sdk_parse_observed"])
            current_sources = [
                row
                for row in ledger.events()
                if row["payload"]["kind"] == "SourceReadStarted"
            ]
            self.assertEqual(
                len(current_sources) - len(before_sources),
                0 if revoke_after == "sdk" else 1,
            )
            self.assertTrue(validate_run(ledger.root)["valid"])
            registry = self.intake._load("alice", self.ref).get(
                "stage1_saved_registries", {}
            )
            if revoke_after == "registry":
                self.assertEqual(len(registered), 1)
                entry = registered[0]
                self.assertTrue(entry["ref"].startswith("stage1-source-registry-"))
                self.assertEqual(registry[entry["ref"]], entry)
                self.assertEqual(entry["payload"]["work_id"], candidate["work_id"])
            else:
                self.assertEqual(registered, [])
                self.assertFalse(
                    any(k.startswith("stage1-source-registry-") for k in registry)
                )
            before = ledger.events()
            sources.dispatch_pending("alice-token", self.ref, action["key"])
            self.assertEqual(ledger.events(), before)
            self.assertEqual(len(launches), 2)
            self.assertEqual(
                resource_view(
                    self.intake, self.intake._load("alice", self.ref), "alice"
                )["reserved"],
                reservation,
            )
            # The completed parser/Core/registry prefix remains; no retry or refund.
            return
        self.assertEqual(saved["status"], "source-observation-saved", saved)
        self.assertEqual(saved["followup"]["status"], "source-core-registered", saved)
        self.assertEqual(
            [item["synthetic_transport"] for item in launches], [True, False]
        )
        self.assertEqual(len(worker.observations), 2)
        self.assertTrue(worker.observations[-1]["sdk_parse_observed"])
        self.assertFalse(saved["followup"]["original_http_acquisition_verified"])
        self.assertFalse(saved["followup"]["reading_complete"])
        self.assertFalse(saved["followup"]["stage1_complete"])
        self.assertTrue(validate_run(ledger.root)["valid"])
        self.assertEqual(
            resource_view(self.intake, self.intake._load("alice", self.ref), "alice")[
                "reserved"
            ],
            reservation,
        )
        job = sources._row(self.intake._load("alice", self.ref))["jobs"][action["key"]]
        acquisition = json.loads(
            (
                Path(job["binding"]["output_dir"]) / "public-source-acquisition.json"
            ).read_text(encoding="utf8")
        )
        sdk_bundle = json.loads(
            Path(saved["followup"]["bundle_path"]).read_text(encoding="utf8")
        )
        sdk = json.loads(
            (materials / sdk_bundle["parser"]["receipt_path"]).read_text(
                encoding="utf8"
            )
        )
        self.assertEqual(sdk["request"]["operation"], "source import-saved")
        self.assertTrue(all(a["http_status"] is None for a in sdk["attempts"]))
        self.assertEqual(
            sdk["diagnostics"]["saved_import"]["original_acquired_at"],
            acquisition["finished_at"],
        )
        source_id = saved["followup"]["owned_frontier"]["own_source_id"]
        start = ledger.event(source_id, "SourceReadStarted")
        self.assertGreaterEqual(
            datetime.fromisoformat(start["created_at"].replace("Z", "+00:00")),
            datetime.fromisoformat(sdk["retrieved_at"].replace("Z", "+00:00")),
        )
        before = ledger.events()
        self.assertTrue(
            sources.execute(
                "alice-token", self.ref, action, run_authorization=action_token
            )["replayed"]
        )
        sources.dispatch_pending("alice-token", self.ref, action["key"])
        self.assertEqual(ledger.events(), before)
        self.assertEqual(len(worker.observations), 2)
        self.assertEqual(len(launches), 2)
        self.assertEqual(
            resource_view(self.intake, self.intake._load("alice", self.ref), "alice")[
                "reserved"
            ],
            reservation,
        )

    def test_authored_transport_actual_sdk_core_registry_and_same_key_no_repeat(self):
        self._pipeline_fixture()

    def test_run_grant_actual_sdk_core_registry_and_same_key_no_repeat(self):
        self._pipeline_fixture(derived=True)

    def test_run_grant_revoked_after_actual_sdk_preserves_receipt_without_core(self):
        self._pipeline_fixture(derived=True, revoke_after="sdk")

    def test_run_grant_revoked_after_core_preserves_source_without_final_success(self):
        self._pipeline_fixture(derived=True, revoke_after="core")

    def test_run_grant_revoked_after_registry_preserves_prefix_without_final_success(
        self,
    ):
        self._pipeline_fixture(derived=True, revoke_after="registry")
