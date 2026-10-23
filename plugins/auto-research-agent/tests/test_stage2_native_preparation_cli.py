"""Real config loaders and CLI wiring; synthetic transport never executes models."""

# ruff: noqa: E402
from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parent / "cli")]
import test_stage2_native_prerequisites as fixture
from research_workspace_native.project_stage2_controller_config import (
    load_stage2_controllers,
)
from research_workspace_native.session_api import SessionApiError
from stage2_live.__main__ import main
from stage2_live.native_prerequisites import NativePrerequisiteHandler


class NativePreparationCliTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        fixture.NativePrerequisiteTests.setUpClass.__func__(cls)

    def setUp(self):
        fixture.NativePrerequisiteTests.setUp(self)
        self.spec_path = self.root / "spec.json"
        self.spec_path.write_text(json.dumps(self.spec), encoding="utf-8")
        self.preparation = self.root / "preparation.json"
        self.preparation.write_text(json.dumps(self.config), encoding="utf-8")
        self.digest = hashlib.sha256(self.preparation.read_bytes()).hexdigest()

    def args(self):
        return [
            "controller",
            "--workflow",
            str(self.workflow),
            "--controller-root",
            str(self.root / "controller"),
            "--delivery",
            str(self.root / "delivery"),
            "--spec",
            str(self.spec_path),
            "--expected-head",
            self.state["head_sha256"],
            "--output",
            str(self.root / "cli-result.json"),
            "--preparation-config",
            str(self.preparation),
            "--expected-preparation-sha256",
            self.digest,
        ]

    def test_public_controller_loads_pinned_handler_and_preserves_readable_gate_exit(
        self,
    ):
        with patch(
            "stage2_live.controller.run_controller",
            return_value={"status": "needs-prior-work"},
        ) as run:
            self.assertEqual(main(self.args()), 2)
        handler = run.call_args.kwargs["prerequisite_handler"]
        self.assertIsInstance(handler, NativePrerequisiteHandler)
        self.assertEqual(handler.spec, self.spec)
        self.assertFalse(Path(self.config["output_root"]).exists())

    def test_bad_hash_never_enters_controller(self):
        args = self.args()
        args[-1] = "0" * 64
        with patch("stage2_live.controller.run_controller") as run:
            self.assertEqual(main(args), 2)
        run.assert_not_called()

    def test_host_loader_authenticates_and_constructs_existing_driver_without_dispatch(
        self,
    ):
        refs = []

        def read(token, ref):
            if token != "own":
                raise SessionApiError("credential-refused", 401)
            refs.append(ref)
            return {"project_ref": ref}

        service = SimpleNamespace(
            intake=SimpleNamespace(read=read),
            binding=lambda ref: {"workflow_root": str(self.workflow)},
        )
        row = dict(
            project_ref="current-project",
            spec_path=str(self.spec_path),
            spec_sha256=hashlib.sha256(self.spec_path.read_bytes()).hexdigest(),
            controller_root=str(self.root / "controller"),
            delivery_root=str(self.root / "delivery"),
            preparation_path=str(self.preparation),
            preparation_sha256=self.digest,
        )
        config = self.root / "controllers.json"

        def save(rows):
            config.write_text(
                json.dumps(
                    dict(
                        kind="ProjectStage2ControllerConfiguration",
                        schema_version="1.0.0",
                        bindings=rows,
                    )
                ),
                encoding="utf-8",
            )
            return hashlib.sha256(config.read_bytes()).hexdigest()

        digest = save([row])
        with patch(
            "research_workspace_native.project_stage2_controller.run_controller"
        ) as run:
            loaded = load_stage2_controllers(service, "own", config, digest)
            self.assertEqual(set(loaded), {"current-project"})
            with self.assertRaises(SessionApiError):
                load_stage2_controllers(service, "wrong", config, digest)
            with self.assertRaisesRegex(SessionApiError, "configuration-duplicate"):
                load_stage2_controllers(
                    service, "own", config, save([row, deepcopy(row)])
                )
        run.assert_not_called()
        self.assertFalse((self.root / "controller").exists())
        self.assertEqual(refs, ["current-project", "current-project"])
