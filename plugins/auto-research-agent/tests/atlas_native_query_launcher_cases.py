"""Real journals/HTTP and fake channels; no native, Hub or model execution."""

from copy import deepcopy
import http.client
import json
import os
from pathlib import Path
import sys
import threading
import time
from types import SimpleNamespace
from types import ModuleType
from unittest.mock import patch

from planned_query_fixture import QueryCase, get_source_proof
from research_workspace_native import atlas_local_launcher as launcher
from research_workspace_native.atlas_query_launcher import QueryRegistration
from research_workspace_native.atlas_host import AtlasHost
from research_workspace_native.controller import InjectedSessionController
from research_workspace_native.frame_journal import FrameJournal
from research_workspace_native.session_api import SessionApi
from research_workspace_native.stage_actions import StageActions
from research_workspace_native.stage_inputs import snapshot_inputs, source_digest
from stage1_deliverable.common import canonical, sha
from native_session_fixtures import Channel


class LocalNativeQueryTests(QueryCase):
    def setUp(self):
        super().setUp()
        self.raw = b'{"project_id":"project-a"}\n'
        self.item["index_sha256"] = sha(self.raw)
        self.item["principals"] = ["local-viewer"]
        self.permit["principals"] = ["local-viewer"]
        self.permit["binding"]["index_sha256"] = self.item["index_sha256"]
        self.write_permit()
        self.source = sys.modules["research_workspace_native.atlas_local_source"]
        source_root = self.root / "immutable-view"
        source_root.mkdir()
        self.inputs = {1: {"ledger_root": str(self.parent_ledger)}, 2: None}
        protected = {}
        for name in ("host_config", "user_config", "source_manifest"):
            p = self.root / ("native-" + name)
            p.write_bytes(b"synthetic native input; never executable\n")
            protected[name] = dict(path=str(p), sha256=sha(p.read_bytes()))
        manifest = source_root / "view-manifest.json"
        manifest.write_bytes(b'{"kind":"synthetic-view"}')
        self.host = dict(
            views=[dict(manifest=str(manifest), sha256=sha(manifest.read_bytes()))]
        )
        Path(protected["host_config"]["path"]).write_bytes(canonical(self.host))
        protected["host_config"]["sha256"] = sha(canonical(self.host))
        spec = dict(
            project_ref="case",
            project_id="project-a",
            index_sha256=self.item["index_sha256"],
            input_version=self.item["input_version"],
            source_root=source_root.as_posix(),
            principals=["local-viewer"],
            executable=str(self.pin["argv_prefix"][0]),
            limits=dict(timeout_seconds=15),
        )
        self.authority = SimpleNamespace(
            spec=spec,
            sha="a" * 64,
            repo=Path(get_source_proof()["repo"]),
            manifest={"plugin_files": get_source_proof()["files"]},
            permit=dict(
                stage_inputs=deepcopy(self.inputs),
                attempt_root=str(self.root / "native-attempt"),
                **protected,
            ),
            path=self.root / "native-spec.json",
            permit_path=self.root / "native-permit.json",
            starts=0,
            valid=True,
            checks=0,
            callbacks=lambda: {},
        )

        def verify(event, *, full=False):
            self.assertEqual(event, dict(spec_sha256="a" * 64, spec=spec))
            self.assertTrue(full)
            self.authority.checks += 1
            if not self.authority.valid:
                raise ValueError("synthetic native binding invalid")
            return True

        self.authority.verify = verify
        self.registration = self.root / "query-registration.json"
        self.save_registration()

    def save_registration(self, **changes):
        value = dict(
            kind="LocalAtlasQueryRegistration",
            schema_version="1.0.0",
            project_ref="case",
            registration=deepcopy(self.item),
            **changes,
        )
        self.registration.write_bytes(canonical(value))
        return sha(self.registration.read_bytes())

    def guard(self, path=None, expected=None):
        return QueryRegistration(
            self.source,
            self.authority,
            path or self.registration,
            expected or sha(self.registration.read_bytes()),
        )

    def create(self):
        guard = self.guard()
        service = guard.create_service(
            lambda t: "local-viewer" if t in {"secret", "t" * 48} else None
        )
        self.services.append(service)
        return guard, service

    def test_text_profile_alone_and_invalid_registration_never_create_store(self):
        with patch.object(
            launcher, "preflight", side_effect=AssertionError("no native bootstrap")
        ):
            self.assertEqual(
                launcher.launch(SimpleNamespace(enable_native=False))["status"],
                "disabled",
            )
            for options in (
                {"query_registration": self.registration},
                {"query_registration_sha256": "a" * 64},
            ):
                with self.assertRaisesRegex(ValueError, "explicit native"):
                    launcher.launch(SimpleNamespace(enable_native=False, **options))
        for item in (
            dict(self.item, principals=["another-user"]),
            dict(self.item, input_version="f" * 64),
            dict(self.item, execution_source_root=str(self.root)),
        ):
            self.registration.write_bytes(
                canonical(
                    dict(
                        kind="LocalAtlasQueryRegistration",
                        schema_version="1.0.0",
                        project_ref="case",
                        registration=item,
                    )
                )
            )
            with self.assertRaises(ValueError):
                self.guard()
        with self.assertRaises(ValueError):
            self.guard(path=Path("relative.json"))
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_query_brief_is_protected_from_budget_marker_collision(self):
        marker = Path(self.item["control_store_path"] + ".created")
        raw = self.brief.read_bytes()
        marker.write_bytes(raw)
        self.item["brief_path"] = str(marker)
        self.save_registration()
        with self.assertRaisesRegex(ValueError, "storage overlap"):
            self.guard().create_service(lambda _: "local-viewer")
        self.assertEqual(marker.read_bytes(), raw)
        self.assertFalse(Path(self.item["control_store_path"]).exists())

    def test_expiry_parent_and_native_storage_fail_before_composition(self):
        self.permit["expires_at_unix"] = int(time.time()) - 1
        self.write_permit()
        self.save_registration()
        with self.assertRaises(ValueError):
            self.guard()
        self.permit["expires_at_unix"] = int(time.time()) + 600
        self.write_permit()
        self.save_registration()
        for change in (
            lambda: setattr(self.authority, "valid", False),
            lambda: self.authority.permit["stage_inputs"].update({1: None}),
            lambda: self.authority.permit.update(attempt_root=str(self.ledger_root)),
        ):
            change()
            with self.assertRaises(ValueError):
                self.guard()
            self.authority.valid = True
            self.authority.permit["stage_inputs"] = deepcopy(self.inputs)
        self.assertFalse((self.root / "query.sqlite3").exists())

    def test_opt_in_alias_preserves_default_and_refuses_distinct_loader_class(self):
        launcher.SOURCE = self.source
        alias = self.source.__name__
        self.assertEqual(launcher.query_source_alias(SimpleNamespace()), (None, None))
        self.assertIs(sys.modules[alias], self.source)
        args = SimpleNamespace(
            query_registration=self.registration, query_registration_sha256="a" * 64
        )
        with self.assertRaisesRegex(ValueError, "preloaded"):
            launcher.query_source_alias(args)
        sys.modules.pop(alias)
        try:
            self.assertEqual(
                launcher.query_source_alias(args), (self.registration, "a" * 64)
            )
            self.assertIs(sys.modules[alias].PinnedLoader, self.source.PinnedLoader)
        finally:
            sys.modules[alias] = self.source
        import stage1_retrieval.runner as runner

        foreign = ModuleType("synthetic_foreign_source")
        foreign.__file__ = self.source.__file__
        exec(
            compile(Path(foreign.__file__).read_bytes(), foreign.__file__, "exec"),
            foreign.__dict__,
        )
        foreign_loader = foreign.PinnedLoader.__new__(foreign.PinnedLoader)
        foreign_loader.__dict__.update(runner.__loader__.__dict__)
        with patch.object(runner, "__loader__", foreign_loader):
            with self.assertRaisesRegex(ValueError, "raw-loader"):
                self.create()
        self.assertFalse((self.root / "query.sqlite3").exists())

    def test_other_stage_and_other_view_inputs_refuse_before_writer(self):
        for name in ("delivery_root", "evaluation_root"):
            stage = dict(
                delivery_root=str(self.root / "delivery"),
                delivery_manifest_sha256="a" * 64,
                evaluation_root=None,
                evaluation_manifest_sha256=None,
            )
            stage[name] = str(self.ledger_root)
            self.authority.permit["stage_inputs"][2] = stage
            with self.assertRaisesRegex(ValueError, "storage overlap"):
                self.guard()
            self.authority.permit["stage_inputs"] = deepcopy(self.inputs)
        path = self.ledger_root / "unrelated-view.json"
        path.write_bytes(b"{}")
        host = dict(
            views=[*self.host["views"], dict(manifest=str(path), sha256=sha(b"{}"))]
        )
        protected = self.authority.permit["host_config"]
        Path(protected["path"]).write_bytes(canonical(host))
        protected["sha256"] = sha(canonical(host))
        with self.assertRaisesRegex(ValueError, "storage overlap"):
            self.guard()
        self.assertFalse((self.root / "query.sqlite3").exists())
        self.assertEqual(self.children, [])

    def test_registration_drift_after_intent_preserves_known_unsent_history(self):
        _, service = self.create()
        body = self.request(service)
        self.registration.write_bytes(b"{}")
        with self.no_probe(), self.fake_runner():
            service.execute("secret", "case", body, deadline=time.monotonic() + 30)
            row = self.wait(service)
        self.assertEqual(row["outcome"], "refused-known-unsent")
        self.assertEqual(self.children, [])
        self.assertEqual(service.view("secret", "case")["budget"]["attempts"], 1)
        self.assertEqual(
            service.execute("secret", "case", body, deadline=time.monotonic() + 30), row
        )

    def test_final_source_recheck_survives_mutating_admission(self):
        guard, service = self.create()
        original = guard.admit
        target = (
            Path(get_source_proof()["repo"])
            / "plugins/auto-research-agent/cli/stage1_retrieval/runner.py"
        )
        raw = target.read_bytes()

        def mutated(event):
            result = original(event)
            target.write_bytes(raw + b"\n# synthetic mutation after admission\n")
            return result

        service._admit = mutated
        try:
            with self.no_probe(), self.fake_runner():
                service.execute(
                    "secret",
                    "case",
                    self.request(service),
                    deadline=time.monotonic() + 30,
                )
                row = self.wait(service)
            self.assertEqual(row["outcome"], "refused-known-unsent")
            self.assertEqual(self.children, [])
        finally:
            target.write_bytes(raw)

    def test_derived_budget_and_owner_paths_cannot_touch_protected_inputs(self):
        database = Path(self.item["control_store_path"])
        owner = self.ledger_root.parent / (
            ".planned-query-owner-"
            + sha(os.path.normcase(str(self.ledger_root)).encode())
            + ".sqlite3"
        )
        paths = [
            Path(str(database) + s)
            for s in ("", "-wal", "-shm", "-journal", ".created")
        ]
        paths.extend(Path(str(owner) + s) for s in ("", "-wal", "-shm", "-journal"))
        pid = "planned-query-" + sha(b"case")[:32]
        project_owner = database.with_name(
            database.name + ".owner-" + sha(pid.encode()) + ".sqlite3"
        )
        paths.extend(
            Path(str(project_owner) + s) for s in ("", "-wal", "-shm", "-journal")
        )
        original = self.authority.path
        for protected in paths:
            with self.subTest(path=protected.name):
                protected.write_bytes(b'{"synthetic-native-spec":"preserve"}')
                self.authority.path = protected
                try:
                    with self.assertRaisesRegex(ValueError, "storage overlap"):
                        self.guard().create_service(lambda _: "local-viewer")
                    self.assertEqual(
                        protected.read_bytes(), b'{"synthetic-native-spec":"preserve"}'
                    )
                    self.assertTrue(
                        all(p == protected or not p.exists() for p in paths)
                    )
                finally:
                    protected.unlink()
                    self.authority.path = original
        self.assertEqual(self.children, [])

    def test_same_host_serves_native_and_query_without_cross_authority(self):
        guard, service = self.create()
        store = FrameJournal(self.root / "fake-native.sqlite3")
        self.addCleanup(store.close)
        store.bind_project("project-a", self.item["index_sha256"])
        owner = store.acquire_owner("project-a", "synthetic")
        store.bind_thread(
            "project-a", owner, "thread-a", store.snapshot("project-a")["revision"]
        )
        channel = Channel()
        controller = InjectedSessionController(
            store=store,
            project_id="project-a",
            owner=owner,
            connection_id="epoch-a",
            index_sha256=self.item["index_sha256"],
            thread_id="thread-a",
            channel=channel,
            verify_binding=lambda: True,
            admit_action=lambda action: True,
        )
        self.addCleanup(controller.close)

        def authenticate(token):
            return "local-viewer" if token == "t" * 48 else None

        api = SessionApi(authenticate=authenticate)
        binding = dict(
            project_id="project-a",
            index_sha256=self.item["index_sha256"],
            input_version=self.item["input_version"],
        )
        api.register(
            "case",
            controller=controller,
            principals=["local-viewer"],
            source_root=self.authority.spec["source_root"],
            index_sha256=binding["index_sha256"],
            input_version=binding["input_version"],
            verify_source=lambda _: True,
            start_offer=lambda _: dict(
                **binding,
                source_root=self.authority.spec["source_root"],
                model="synthetic-model",
                permit_sha256="a" * 64,
                limits=dict(max_text_bytes=128, max_starts=2, timeout_seconds=15),
            ),
        )
        runtime = SimpleNamespace(
            api=api,
            bindings=lambda: {"case": binding},
            shutdown=lambda timeout: {"synthetic": True},
        )
        stages = StageActions(
            self.root / "stage.sqlite3",
            authenticate=authenticate,
            planned_queries=service,
            registrations={
                "case": dict(
                    **binding,
                    principals=["local-viewer"],
                    inputs=self.inputs,
                    source_sha256=source_digest(snapshot_inputs(self.inputs)),
                    output_root=str(self.root / "checks"),
                )
            },
        )
        self.addCleanup(stages.close)
        host = AtlasHost(
            files={
                "/views/case/atlas.html": b'<html lang="en"><meta content="connect-src \'none\'"><body><main id="atlas-content"><section id="atlas-stage-review"></section></main></body>',
                "/views/case/workspace-index.json": self.raw,
            },
            views=[
                dict(
                    ref="case",
                    label="Synthetic case",
                    url="/views/case/atlas.html",
                    manifest_sha256="a" * 64,
                    fixture=True,
                    project_id=binding["project_id"],
                    index_sha256=binding["index_sha256"],
                )
            ],
            native_runtime=runtime,
            stage_actions=stages,
            credential="t" * 48,
            timeout=15,
        )
        worker = threading.Thread(target=host.serve_forever, daemon=True)
        worker.start()

        def stop():
            host.shutdown()
            host.server_close()
            worker.join(3)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)

        def call(path, body=None):
            client = http.client.HTTPConnection(*host.server_address, timeout=15)
            headers = {"Authorization": "Bearer " + "t" * 48}
            if body is not None:
                headers.update(
                    Origin=host.expected_origin, **{"Content-Type": "application/json"}
                )
            try:
                client.request(
                    "GET" if body is None else "POST",
                    path,
                    json.dumps(body) if body is not None else None,
                    headers,
                )
                response = client.getresponse()
                return response.status, json.loads(response.read())
            finally:
                client.close()

        self.assertEqual(call("/api/native/projects/case")[0], 200)
        route = "/api/stages/projects/case/queries"
        status, offer = call(route + "/offer")
        self.assertEqual(status, 200)
        body = dict(
            key="host-query",
            confirmed=True,
            index_sha256=binding["index_sha256"],
            input_version=binding["input_version"],
            **{k: offer[k] for k in ("revision", "offer_ref", "offer_sha256")},
        )
        with self.no_probe(), self.fake_runner():
            self.assertEqual(call(route + "/actions", body)[0], 200)
            row = self.wait(service, "host-query")
        self.assertEqual((row["status"], len(self.children)), ("completed", 1))
        self.assertEqual(channel.calls, [])
        self.assertEqual(self.authority.starts, 0)
        self.assertFalse(row["result"]["stage_complete"])
        for _ in range(2):
            self.assertEqual(call(route + "/actions/host-query")[0], 200)
        self.assertEqual(len(self.children), 1)
        self.assertGreater(self.authority.checks, 2)

    def test_failed_native_composition_closes_query_ownership(self):
        guard = self.guard()
        self.authority.query_registration = guard
        self.authority.deadline = time.monotonic() + 30
        args = SimpleNamespace(
            enable_native=True,
            spec="synthetic",
            spec_sha256="a" * 64,
            permit_sha256="b" * 64,
            port=0,
            open=False,
        )
        created = []
        original = guard.create_service

        def create(authenticate):
            value = original(authenticate)
            created.append(value)
            return value

        launcher.SOURCE = self.source
        with (
            patch.object(
                launcher,
                "preflight",
                return_value=(self.authority, {}, self.root / "native-attempt"),
            ),
            patch.object(guard, "create_service", side_effect=create),
            patch("research_workspace_native.runtime_spec._load"),
            patch(
                "research_workspace_native.runtime_factory.compose_runtime",
                side_effect=RuntimeError("synthetic compose failure"),
            ),
        ):
            with self.assertRaisesRegex(RuntimeError, "synthetic compose"):
                launcher.launch(args)
        self.assertEqual(len(created), 1)
        self.assertTrue(created[0]._closed)
        receipt = json.loads(
            (self.root / "native-attempt/cleanup-receipt.json").read_bytes()
        )
        self.assertTrue(receipt["planned_queries_registered"])
        self.assertEqual(
            receipt["query_execution_authority"], "separate-research-permit"
        )
        replacement = guard.create_service(lambda _: "local-viewer")
        self.services.append(replacement)
        self.assertEqual(replacement.view("secret", "case")["budget"]["attempts"], 0)
