"""Real saved-source imports with explicitly synthetic Core/HTML test authority.

The authored fixtures exercise production validators and source projection. Their
review/HTML receipts are synthetic binding specimens, never genuine acceptance.
"""

from contextlib import redirect_stdout
from copy import deepcopy
import io
import json
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace import host_replay, saved_admission
from stage1_deliverable import sources
from stage1_deliverable.common import canonical, inventory, read_json, sha, write_json
from stage2_common import Stage2Error, validate_packet
from stage2_workflow import build_stage2_seed
from stage2_workflow.__main__ import main
import test_saved_source_admission as acceptance_fixtures
import test_saved_source_admission_integration as admission_fixtures


class Stage1ImportHostReplayTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        admission_fixtures.SavedAdmissionIntegrationTests.setUpClass()
        fixture = admission_fixtures.SavedAdmissionIntegrationTests()
        fixture.setUp()
        cls.addClassCleanup(fixture.doCleanups)
        cls.template = fixture.root
        cls.template_snapshot_ref = fixture.snapshot_ref
        authority = cls()
        cls.addClassCleanup(authority.doCleanups)
        authority.root = fixture.root
        authority.snapshot_ref = fixture.snapshot_ref
        authority.snapshot = read_json(fixture.root / fixture.snapshot_ref["path"])
        cls.template_acceptance_ref = authority.synthetic_acceptance()
        handoff = saved_admission.inspect_saved_admission(
            authority.root,
            authority.snapshot_ref,
            acceptance_ref=cls.template_acceptance_ref,
            trusted_acceptance_sha256=cls.template_acceptance_ref["sha256"],
        )
        write_json(authority.root / "handoff.json", handoff)
        cls.runtime = sources.runtime_binding()

    def setUp(self):
        temporary = tempfile.TemporaryDirectory(prefix="stage1-host-import-")
        self.addCleanup(temporary.cleanup)
        self.root = Path(temporary.name).resolve() / "evidence"
        shutil.copytree(self.template, self.root)
        self.snapshot_ref = deepcopy(self.template_snapshot_ref)
        self.snapshot = read_json(self.root / self.snapshot_ref["path"])
        self.package = self.root / "package"
        self.manifest = read_json(self.package / "provenance_manifest.json")
        self.manifest_sha256 = self.snapshot["bindings"]["deliverable"]["sha256"]
        self.output = self.root / "seed"
        self.brief = self.root / self.snapshot["bindings"]["brief"]["path"]
        self.resources = self.root / "resource-envelope.txt"
        self.resources.write_text(
            "Use retained sources and the existing resource limits."
        )
        self.acceptance_ref = deepcopy(self.template_acceptance_ref)
        self.handoff = read_json(self.root / "handoff.json")
        self.handoff_path = self.root / "handoff.json"
        runtime = deepcopy(self.runtime)
        exporter_root = Path(sources.__file__).parent
        source = self.manifest["canonical_records"]["sources"][0]
        archive = self.package / "sources" / source["source_id"]
        observation = read_json(archive / "validation.json")
        checked_at = json.loads(observation["stdout"])["checked_at"]
        self.replay_receipt = {
            "kind": "HostReplayReceipt",
            "schema_version": "1.0.0",
            "project_id": self.snapshot["project_id"],
            "input_version": self.snapshot["input_version"],
            "snapshot_ref": self.snapshot_ref,
            "canonical_manifest_sha256": self.manifest_sha256,
            "historical_producer": {
                "runtime": runtime,
                "executable": sys.executable,
                "exporter_files": host_replay.exporter_files(exporter_root),
            },
            "replayer": {
                "runtime": runtime,
                "executable": sys.executable,
                "exporter_files": host_replay.exporter_files(exporter_root),
            },
            "validator": {"runtime": runtime, "files": host_replay.validator_files()},
            "sources": [
                {
                    "source_id": source["source_id"],
                    "work_id": source["work_id"],
                    "version_id": source["version_id"],
                    "files": inventory(archive),
                    "historical_observation_sha256": sha(
                        (archive / "validation.json").read_bytes()
                    ),
                    "observation": observation,
                    "started_at": checked_at,
                    "ended_at": checked_at,
                }
            ],
        }
        self.replay_path = self.root / "host-replay.json"
        self.save_replay()
        self.host_args = {
            "host_replay_receipt": self.replay_path,
            "trusted_host_replay_sha256": sha(self.replay_path.read_bytes()),
            "historical_exporter_root": exporter_root,
            "replayer_exporter_root": exporter_root,
        }

    def ref(self, path):
        raw = path.read_bytes()
        return {
            "path": path.relative_to(self.root).as_posix(),
            "sha256": sha(raw),
            "bytes": len(raw),
        }

    def save(self, name, value):
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(value if isinstance(value, bytes) else canonical(value))
        return self.ref(path)

    def synthetic_acceptance(self):
        fixture = acceptance_fixtures.ExternalAcceptanceBindingTests()
        fixture.setUp()
        self.addCleanup(fixture.doCleanups)
        proof = self.save("synthetic-proof.bin", b"Synthetic binding evidence only.")
        acceptance = deepcopy(fixture.acceptance)
        binding = {
            "snapshot_sha256": self.snapshot_ref["sha256"],
            "project_id": self.snapshot["project_id"],
            "input_version": self.snapshot["input_version"],
        }
        acceptance.update(binding)
        for category, ref in fixture.acceptance["checks"].items():
            review = read_json(fixture.root / ref["path"])
            review.update(binding, validator=proof, rubric=proof, evidence=[proof])
            acceptance["checks"][category] = self.save(category + ".json", review)
        html = deepcopy(fixture.html)
        html.update(
            snapshot_sha256=self.snapshot_ref["sha256"],
            html_sha256=sha((self.root / "view/index.html").read_bytes()),
            expected_bibtex=self.ref(self.root / "view/literature/included.bib"),
            bibtex_download=self.save(
                "synthetic-download.bib",
                (self.root / "view/literature/included.bib").read_bytes(),
            ),
        )
        for operation in html["operations"]:
            operation["evidence"] = [proof]
        acceptance["html"] = self.save("synthetic-html-receipt.json", html)
        return self.save("synthetic-acceptance.json", acceptance)

    def save_replay(self):
        write_json(self.replay_path, self.replay_receipt)

    def build(self, **kwargs):
        return build_stage2_seed(
            self.package,
            self.manifest_sha256,
            self.handoff_path,
            sha(self.handoff_path.read_bytes()),
            self.brief,
            self.resources,
            self.output,
            saved_source_root=self.root,
            saved_source_acceptance_sha256=self.acceptance_ref["sha256"],
            **kwargs,
        )

    def test_host_context_is_used_for_real_package_source_and_final_validation(self):
        before = inventory(self.package)
        with patch.object(
            sources,
            "validate_archive",
            side_effect=AssertionError("saved replay must be reused"),
        ):
            receipt = self.build(**self.host_args)
        packet = read_json(self.output / "packet.json")
        self.assertEqual(receipt["schema_version"], "2.1.0")
        self.assertEqual(receipt["source_canonical_records_version"], "1.0.0")
        self.assertFalse(receipt["host_replay"]["core_acceptance"])
        self.assertFalse(receipt["stage2_execution_authorized"])
        self.assertEqual(
            packet["upstream"]["stage2"],
            {"status": "not-started", "execution_authorized": False},
        )
        self.assertEqual(packet["candidates"], [])
        self.assertEqual(
            packet["evidence"][0]["relation"],
            self.manifest["canonical_records"]["claims"][0]["relation"],
        )
        self.assertEqual(inventory(self.package), before)
        self.assertEqual(
            (self.output / packet["sources"][0]["path"]).read_bytes(),
            (
                self.root / self.snapshot["rows"][0]["extracted_text"]["path"]
            ).read_bytes(),
        )
        validate_packet(packet, self.output)

    def test_verified_context_is_reused_by_saved_admission(self):
        context = host_replay.resolve_host_replay(
            self.root, self.snapshot_ref, **self.host_args
        )
        with (
            patch.object(
                sources,
                "validate_archive",
                side_effect=AssertionError("unexpected replay"),
            ),
            patch.object(
                saved_admission,
                "inspect_saved_admission",
                wraps=saved_admission.inspect_saved_admission,
            ) as inspect,
        ):
            receipt = self.build(verified_host_replay=context)
        self.assertIs(inspect.call_args.kwargs["verified_host_replay"], context)
        self.assertEqual(receipt["host_replay"], context.evidence())

    def test_explicit_trust_identity_runtime_and_source_fail_closed(self):
        original = deepcopy(self.replay_receipt)
        mutations = {
            "wrong-project": lambda value: value.update(project_id="other-project"),
            "wrong-version": lambda value: value["sources"][0].update(
                version_id="other"
            ),
            "missing-source": lambda value: value.update(sources=[]),
            "runtime-drift": lambda value: value["replayer"]["runtime"].update(
                exporter_sha256="0" * 64
            ),
        }
        for label, mutate in mutations.items():
            with self.subTest(label=label):
                self.replay_receipt = deepcopy(original)
                mutate(self.replay_receipt)
                self.save_replay()
                args = {
                    **self.host_args,
                    "trusted_host_replay_sha256": sha(self.replay_path.read_bytes()),
                }
                with self.assertRaises(Stage2Error):
                    self.build(**args)
                self.assertFalse(self.output.exists())
        self.replay_receipt = original
        self.save_replay()
        with self.assertRaises(Stage2Error):
            self.build(**{**self.host_args, "trusted_host_replay_sha256": "0" * 64})
        partial = {"host_replay_receipt": self.replay_path}
        with self.assertRaisesRegex(Stage2Error, "all host replay inputs required"):
            self.build(**partial)
        with self.assertRaises(Stage2Error):
            self.build(**self.host_args, verified_host_replay=object())
        self.assertFalse(self.output.exists())

    def test_context_does_not_replace_Core_and_html_external_acceptance(self):
        with self.assertRaisesRegex(Stage2Error, "independent external hash"):
            build_stage2_seed(
                self.package,
                self.manifest_sha256,
                self.handoff_path,
                sha(self.handoff_path.read_bytes()),
                self.brief,
                self.resources,
                self.output,
                saved_source_root=self.root,
                saved_source_acceptance_sha256="0" * 64,
                **self.host_args,
            )
        acceptance = read_json(self.root / self.acceptance_ref["path"])
        html = read_json(self.root / acceptance["html"]["path"])
        html["operations"].pop()
        acceptance["html"] = self.save("synthetic-html-receipt.json", html)
        self.acceptance_ref = self.save("synthetic-acceptance.json", acceptance)
        self.handoff["acceptance_ref"] = self.acceptance_ref
        write_json(self.handoff_path, self.handoff)
        with self.assertRaisesRegex(Stage2Error, "HTML operations incomplete"):
            self.build(**self.host_args)
        self.assertFalse(self.output.exists())

    def test_saved_source_import_without_context_keeps_version_2_0_receipt(self):
        receipt = self.build()
        self.assertEqual(receipt["schema_version"], "2.0.0")
        self.assertNotIn("host_replay", receipt)
        self.assertNotIn("source_canonical_records_version", receipt)
        self.assertFalse(receipt["stage2_execution_authorized"])

    def test_actual_cli_forwards_all_four_explicit_host_inputs(self):
        args = ["import-stage1"]
        options = {
            "deliverable": self.package,
            "deliverable-manifest-sha256": self.manifest_sha256,
            "handoff": self.handoff_path,
            "handoff-sha256": sha(self.handoff_path.read_bytes()),
            "brief": self.brief,
            "resources": self.resources,
            "output": self.output,
            "saved-source-root": self.root,
            "saved-source-acceptance-sha256": self.acceptance_ref["sha256"],
            **{name.replace("_", "-"): value for name, value in self.host_args.items()},
        }
        for name, value in options.items():
            args.extend(["--" + name, str(value)])
        output = io.StringIO()
        with redirect_stdout(output):
            result = main(args)
        self.assertEqual(result, 0)
        receipt = json.loads(output.getvalue())
        self.assertEqual(receipt["schema_version"], "2.1.0")
        self.assertEqual(
            receipt["host_replay"]["sha256"],
            self.host_args["trusted_host_replay_sha256"],
        )
        self.assertFalse(receipt["stage2_execution_authorized"])


if __name__ == "__main__":
    unittest.main()
