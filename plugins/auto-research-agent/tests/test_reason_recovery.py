"""Synthetic native archives; no actual model, network or process calls."""

import copy
import json
import socket
import subprocess
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))
from stage1_eval.common import EvaluationError, canonical, read_json, sha
from stage1_eval.model_calls import _request_config
from stage1_eval.reason_recovery import (
    revalidate_unit,
    require_reason_delta,
    _plan_contract,
)
from stage1_eval.source_audit_units import (
    build_audit_plan,
    normalize_audit_value,
    _prompt,
    _schema,
)
from stage1_eval.spans import model_span_aliases
from stage1_eval.units import run_unit
import test_source_audit_units as fixtures


class ReasonRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixtures.SourceAuditUnitTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        self.root = self.fixture.root
        plan = build_audit_plan(
            self.fixture.packet, [self.fixture.record], self.fixture.extraction
        )
        planned = next(row for row in plan["plan"] if row["windows"])
        self.target, self.group = planned["target"], planned["windows"][0]
        self.label = planned["expected_unit_ids"][0]
        self.directory = self.root / "audit"
        self.directory.mkdir()
        self.aliases, _ = model_span_aliases(self.group)
        self.schema = _schema(list(self.aliases))
        self.schema["properties"]["reason"]["maxLength"] = 400
        self.schema_path = self.directory / (self.label + ".schema.json")
        self.schema_path.write_bytes(canonical(self.schema) + b"\n")
        self.prompt = _prompt(self.target, self.aliases)
        self.options = self.fixture.options
        self.config = _request_config(
            **{
                k: self.options[k]
                for k in ("codex", "evaluator_home", "model", "reasoning")
            }
        )

    def generate(self, lengths=(30,), *, initial_aliases=None):
        responses = iter(lengths)
        count = [0]

        def respond(command, **kwargs):
            count[0] += 1
            value = {
                "verdict": "partially-supported",
                "reason": "x" * next(responses),
                "addressed": list(self.aliases),
                "passages": list(self.aliases),
            }
            if initial_aliases is not None and count[0] == 1:
                value["addressed"] = initial_aliases
            Path(command[command.index("-o") + 1]).write_bytes(canonical(value))
            events = [
                {
                    "type": "item.completed",
                    "item": {"type": "agent_message", "text": json.dumps(value)},
                },
                {"type": "turn.completed"},
            ]
            return SimpleNamespace(
                returncode=0,
                stdout=b"\n".join(canonical(e) for e in events),
                stderr=b"",
            )

        with mock.patch("stage1_eval.model_calls.subprocess.run", side_effect=respond):
            try:
                run_unit(
                    self.prompt,
                    self.schema_path,
                    self.directory,
                    self.label,
                    self.options,
                    lambda value: normalize_audit_value(value, self.group),
                )
            except EvaluationError:
                pass
        return count[0]

    def inventory(self):
        return {
            p.relative_to(self.directory).as_posix(): sha(p.read_bytes())
            for p in self.directory.rglob("*")
            if p.is_file()
        }

    def invoke(self, **kwargs):
        before = self.inventory()
        with (
            mock.patch.object(
                subprocess, "Popen", side_effect=AssertionError("process forbidden")
            ),
            mock.patch.object(
                socket, "socket", side_effect=AssertionError("network forbidden")
            ),
        ):
            result = revalidate_unit(
                self.directory,
                self.label,
                kwargs.get("target", self.target),
                kwargs.get("group", self.group),
                kwargs.get("config", self.config),
                kwargs.get("policy", self.options["execution_policy"]),
            )
        self.assertEqual(before, self.inventory())
        return result

    def test_unchanged_valid_reuse(self):
        self.assertEqual(self.generate(), 1)
        result = self.invoke()
        self.assertEqual(result["status"], "accepted")
        self.assertEqual(result["selected"]["generation"], "initial")
        self.assertTrue(result["historical_accepted_receipt"])
        self.assertEqual(result["new_native_calls"], 0)

    def test_471_and_411_earliest_original_and_history_preserved_zero_calls(self):
        self.assertEqual(self.generate((471, 411)), 2)
        result = self.invoke()
        self.assertEqual(result["selected"]["generation"], "initial")
        self.assertEqual(len(result["selected"]["value"]["reason"]), 471)
        self.assertEqual(
            [len(row["attempt_records"]) for row in result["original_history"]], [1, 1]
        )
        self.assertTrue(
            all(
                row["attempt_records"][0]["failure_class"] == "schema-mismatch"
                for row in result["original_history"]
            )
        )
        self.assertFalse(result["retry_budget_reset"])
        self.assertFalse(result["historical_accepted_receipt"])
        self.assertEqual(self.invoke(), result)

    def test_reason_over_1024_cannot_count_coverage(self):
        self.generate((1025, 1026))
        result = self.invoke()
        self.assertEqual(result["status"], "rejected")
        self.assertFalse(result["coverage_eligible"])
        self.assertIsNone(result["selected"])

    def test_previously_accepted_correction_now_selects_earliest_original(self):
        self.generate((471, 30))
        result = self.invoke()
        self.assertTrue(result["historical_accepted_receipt"])
        self.assertEqual(result["selected"]["generation"], "initial")
        self.assertEqual(len(result["original_history"]), 2)

    def test_changed_verdict_schema_rejected(self):
        self.generate()
        value = read_json(self.schema_path)
        value["properties"]["verdict"]["enum"].append("invented")
        self.schema_path.write_bytes(canonical(value))
        with self.assertRaises(EvaluationError):
            self.invoke()

    def test_changed_aliases_rejected(self):
        self.generate()
        group = copy.deepcopy(self.group)
        key = next(iter(group))
        group["different-span"] = group.pop(key)
        with self.assertRaises(EvaluationError):
            self.invoke(group=group)

    def test_evidence_work_version_bound_and_prompt_rejected(self):
        self.generate()
        for field in ("source_version", "version_alias", "text"):
            with self.subTest(field=field):
                group = copy.deepcopy(self.group)
                group[next(iter(group))][field] = "tampered"
                with self.assertRaises(EvaluationError):
                    self.invoke(group=group)
        target = copy.deepcopy(self.target)
        target["original_value"] = "changed original value"
        with self.assertRaises(EvaluationError):
            self.invoke(target=target)

    def test_runtime_bytes_bound_model_and_policy_mismatch_rejected(self):
        self.generate()
        for key in ("codex_executable_sha256", "model", "reasoning", "evaluator_home"):
            with self.subTest(key=key):
                config = dict(self.config, **{key: "changed"})
                with self.assertRaises(EvaluationError):
                    self.invoke(config=config)
        policy = dict(
            self.options["execution_policy"], max_transient_transport_retries=0
        )
        with self.assertRaises(EvaluationError):
            self.invoke(policy=policy)

    def test_tampered_native_artifact_rejected(self):
        self.generate()
        archive = self.directory / (self.label + ".model-call")
        (archive / "attempt-01.output.json").write_bytes(b"{}")
        with self.assertRaises(EvaluationError):
            self.invoke()

    def test_saved_acceptance_and_provenance_tamper_rejected(self):
        self.generate()
        path = self.directory / (self.label + ".unit.json")
        receipt = read_json(path)
        receipt["provenance"]["initial"]["attempt"] = 2
        path.write_bytes(canonical(receipt))
        with self.assertRaises(EvaluationError):
            self.invoke()

    def test_missing_unit_stays_unstarted(self):
        result = self.invoke()
        self.assertEqual(result["status"], "missing")
        self.assertFalse(result["coverage_eligible"])
        self.assertEqual(result["original_history"], [])

    def test_inventory_omission_and_tamper_fail_closed(self):
        from stage1_eval.reason_recovery import verify_inventory

        self.generate()
        binding = {"root": str(self.directory), "files": self.inventory()}
        verify_inventory(binding, exact=True)
        binding["files"].pop(next(iter(binding["files"])))
        with self.assertRaises(EvaluationError):
            verify_inventory(binding, exact=True)

    def test_rejected_history_and_total_attempt_accounting_preserved(self):
        from stage1_eval.reason_recovery import historical_attempts, rejected_history

        self.generate((1025, 1026))
        rows = historical_attempts(self.directory, self.inventory())
        self.assertEqual(len(rows), 2)
        self.assertTrue(
            all(row["record"]["failure_class"] == "schema-mismatch" for row in rows)
        )
        refs = rejected_history(self.directory, self.label)
        self.assertEqual(len(refs), 2)
        self.assertTrue(
            all(
                row["authentication"] == "not-established-unit-rejected" for row in refs
            )
        )

    def test_resume_no_reexecution_separate_import_and_guarded_replay_detect_tamper(
        self,
    ):
        from stage1_eval.reason_recovery import import_recovery, replay_recovery

        self.generate((471, 411))
        expected = {"kind": "Stage1ReasonRecovery.v1", "units": [self.invoke()]}
        refs = {}
        for key in ("generation", "old_code"):
            path = self.root / (key + ".json")
            path.write_bytes(canonical({"root": str(self.directory)}))
            refs[key] = {"path": str(path), "sha256": sha(path.read_bytes())}
        path = self.root / "captures.json"
        path.write_bytes(canonical({"captures": {}}))
        refs["captures"] = {"path": str(path), "sha256": sha(path.read_bytes())}
        manifest = self.root / "migration.json"
        manifest.write_bytes(canonical(refs))
        digest = sha(manifest.read_bytes())
        with mock.patch("stage1_eval.reason_recovery.dry_run", return_value=expected):
            with self.assertRaises(EvaluationError):
                import_recovery(manifest, digest, self.directory / "forbidden-child")
            destination = self.root / "recovery"
            result = import_recovery(manifest, digest, destination)
            with (
                mock.patch.object(
                    subprocess, "Popen", side_effect=AssertionError("no processes")
                ),
                mock.patch.object(
                    socket, "socket", side_effect=AssertionError("no network")
                ),
            ):
                self.assertEqual(replay_recovery(destination, digest), result)
            with self.assertRaises(EvaluationError):
                import_recovery(manifest, digest, destination)
            (destination / "recovery.json").write_bytes(b"{}")
            with self.assertRaises(EvaluationError):
                replay_recovery(destination, digest)
        with mock.patch(
            "stage1_eval.reason_recovery.dry_run",
            side_effect=EvaluationError("binding broken"),
        ):
            destination = self.root / "failure"
            with self.assertRaises(EvaluationError):
                import_recovery(manifest, digest, destination)
            failure = read_json(destination / "recovery-failure.json")
            self.assertEqual(failure["status"], "binding-failed")
            self.assertFalse(failure["coverage_eligible"])
            self.assertIsNone(failure["unit_population"])

    def test_readonly_api_guard_blocks_original_append_rename_network_and_process(self):
        from stage1_eval.reason_recovery import readonly_guard
        import os

        path = self.root / "original.jsonl"
        path.write_bytes(b"historical evidence\n")
        before = path.read_bytes()
        operations = [
            lambda: path.open("ab"),
            lambda: path.write_bytes(b"changed"),
            lambda: os.open(path, os.O_WRONLY | os.O_TRUNC),
            lambda: path.rename(self.root / "renamed"),
            lambda: (self.root / "new-dir").mkdir(),
            lambda: subprocess.run([sys.executable, "-c", "pass"]),
            lambda: socket.getaddrinfo("localhost", 80),
        ]
        for operation in operations:
            with self.subTest(operation=operation):
                with readonly_guard(), self.assertRaises(EvaluationError):
                    operation()
                self.assertEqual(path.read_bytes(), before)
        with readonly_guard():
            self.assertEqual(path.read_bytes(), before)
        (self.root / "allowed-outside-guard").write_bytes(b"new recovery result")

    def test_original_source_replay_cannot_create_journal_under_guard(self):
        from stage1_eval.reason_recovery import readonly_guard
        from stage1_eval.source_replay import replay_source_bytes

        result = self.root / "source-result.json"
        result.write_bytes(b"{}")
        journal = self.root / "replay-events.jsonl"
        with readonly_guard(), self.assertRaises(EvaluationError):
            replay_source_bytes(result, [sys.executable, "-m", "research_hub"], journal)
        self.assertFalse(journal.exists())
        self.assertEqual(result.read_bytes(), b"{}")

    def test_python_and_configuration_pins_fail_closed(self):
        from stage1_eval.reason_recovery import verify_operator_runtime
        from stage1_eval.runtime import executable_sha256

        config = self.root / "research-hub.json"
        config.write_bytes(b"{}")
        plan = {
            "python_executable_sha256": executable_sha256(sys.executable),
            "research_hub_config_sha256": sha(config.read_bytes()),
        }
        verify_operator_runtime(plan, self.root)
        for key in plan:
            with self.subTest(key=key):
                with self.assertRaises(EvaluationError):
                    verify_operator_runtime(dict(plan, **{key: "f" * 64}), self.root)

    def test_profile_exclusion_is_generation_only(self):
        from stage1_eval.reason_recovery import verify_inventory

        root = self.root / "capture"
        (root / "profile").mkdir(parents=True)
        (root / "profile/config.toml").write_bytes(b"config")
        (root / "profile/omitted.txt").write_bytes(b"must not silently disappear")
        inventory = {
            "root": str(root),
            "files": {"profile/config.toml": sha(b"config")},
        }
        with self.assertRaises(EvaluationError):
            verify_inventory(inventory, exact=True)
        verify_inventory(inventory, exact=True, exclude_profile=True)

    def test_complete_tree_unchanged_on_success_parser_failure_process_denial_exception(
        self,
    ):
        from stage1_eval.reason_recovery import readonly_guard

        root = self.root / "protected"
        (root / "nested").mkdir(parents=True)
        (root / "journal.jsonl").write_bytes(b"retained")
        (root / "nested/source.txt").write_bytes(b"source")

        def snapshot():
            return {
                p.relative_to(root).as_posix(): (
                    sha(p.read_bytes()),
                    p.stat().st_mtime_ns,
                )
                for p in root.rglob("*")
                if p.is_file()
            }

        before = snapshot()

        def parser_failure():
            raise EvaluationError("parser failure")

        def other_failure():
            raise RuntimeError("other failure")

        operations = [
            lambda: (root / "nested/source.txt").read_bytes(),
            parser_failure,
            lambda: subprocess.run([sys.executable, "-c", "pass"]),
            other_failure,
            lambda: (root / "nested/new.txt").write_bytes(b"forbidden"),
        ]
        for operation in operations:
            try:
                with readonly_guard():
                    operation()
            except (EvaluationError, RuntimeError):
                pass
            self.assertEqual(snapshot(), before)

    def test_public_dry_run_installs_guard_before_upstream_failure_paths(self):
        from stage1_eval.reason_recovery import dry_run

        original = self.root / "public-api-original.jsonl"
        original.write_bytes(b"unchanged")

        def snapshot():
            return {
                p.relative_to(self.root).as_posix(): (
                    sha(p.read_bytes()),
                    p.stat().st_mtime_ns,
                )
                for p in self.root.rglob("*")
                if p.is_file()
            }

        baseline = snapshot()

        def append():
            with original.open("ab") as stream:
                stream.write(b"must never append")

        def parser_failure():
            raise EvaluationError("parser failure")

        def unexpected():
            raise RuntimeError("unexpected parser failure")

        operations = [
            lambda: {"status": "synthetic-success"},
            append,
            parser_failure,
            lambda: subprocess.run([sys.executable, "-c", "pass"]),
            unexpected,
        ]
        for operation in operations:
            with mock.patch(
                "stage1_eval.reason_recovery._dry_run",
                side_effect=lambda *_: operation(),
            ):
                try:
                    dry_run("synthetic manifest", "external digest")
                except (EvaluationError, RuntimeError):
                    pass
            self.assertEqual(snapshot(), baseline)

    def test_readonly_seam_rejects_live_misuse_before_actions(self):
        from stage1_eval.sources_v31 import collect_sources_v31, _fetch, _validate_fetch
        from stage1_eval.reason_recovery import readonly_guard

        def callback(*args):
            return {"valid": True}

        with (
            readonly_guard(),
            mock.patch.object(
                subprocess, "run", side_effect=AssertionError("no process")
            ),
        ):
            with self.assertRaisesRegex(EvaluationError, "replay-only"):
                collect_sources_v31(
                    {}, {}, self.root / "new", [], replay_validator=callback
                )
            with self.assertRaisesRegex(EvaluationError, "replay-only"):
                _fetch([], [], self.root / "new", {}, False, callback)
            with self.assertRaisesRegex(EvaluationError, "replay-only"):
                _validate_fetch(
                    [], self.root / "new", self.root / "result", False, callback
                )
        self.assertFalse((self.root / "new").exists())

    def test_explicit_incident_prefix_append_hash_and_partial_inventory_rejections(
        self,
    ):
        from stage1_eval.reason_recovery import verify_incident, readonly_guard

        root = self.root / "generation"
        relative = (
            "evaluations/one/sources/work/public-fetch/validation/replay-events.jsonl"
        )
        path = root / relative
        path.parent.mkdir(parents=True)
        prefix = b'{"historical":"prefix"}\n'
        tail = (
            canonical({"event": "registered", "counts_as_source_acquisition": False})
            + b"\n"
        )
        path.write_bytes(prefix + tail)
        (root / "unchanged.json").write_bytes(b"{}")

        def ref(name, value=None, raw=None):
            target = self.root / name
            target.write_bytes(canonical(value) if raw is None else raw)
            return {"path": str(target), "sha256": sha(target.read_bytes())}

        before = {
            "root": str(root),
            "excluded_scope": [],
            "files": {
                relative: {"bytes": len(prefix), "sha256": sha(prefix)},
                "unchanged.json": {"bytes": 2, "sha256": sha(b"{}")},
            },
        }
        after = copy.deepcopy(before)
        after["files"][relative] = {
            "bytes": len(prefix + tail),
            "sha256": sha(prefix + tail),
        }
        incident = {
            "kind": "Stage1ReasonRecoveryIncident.v1",
            "decision_url": "https://github.com/WenyuChiou/AutoResearchAgent/pull/62#issuecomment-1",
            "pre_inventory": ref("before.json", before),
            "post_inventory": ref("after.json", after),
            "changes": [
                {
                    "path": relative,
                    "original_bytes": len(prefix),
                    "original_sha256": sha(prefix),
                    "current_bytes": len(prefix + tail),
                    "current_sha256": sha(prefix + tail),
                    "append_bytes": len(tail),
                    "append_sha256": sha(tail),
                    "derived_prefix": ref("prefix.jsonl", raw=prefix),
                }
            ],
            "diagnostics": {
                "traceback": ref("traceback.txt", raw=b"synthetic failure"),
                "diff": ref("diff.json", {"changed": [relative]}),
            },
        }
        before["root"] = str(root / ".." / root.name)
        incident["pre_inventory"] = ref("before.json", before)
        original = path.read_bytes()
        bound = ref("incident.json", incident)
        with readonly_guard():
            views, provenance = verify_incident(bound, after)
        self.assertEqual(views[str(path.resolve())]["prefix"], prefix)
        self.assertIn("derived", provenance["interpretation"])
        self.assertEqual(path.read_bytes(), original)
        for key in (
            "original_sha256",
            "append_sha256",
            "current_sha256",
            "append_bytes",
        ):
            changed = copy.deepcopy(incident)
            changed["changes"][0][key] = 1 if key.endswith("bytes") else "f" * 64
            with self.subTest(key=key), self.assertRaises(EvaluationError):
                verify_incident(ref("bad-incident.json", changed), after)
        wrong_root = copy.deepcopy(before)
        wrong_root["root"] = str(self.root / "different-generation")
        changed = copy.deepcopy(incident)
        changed["pre_inventory"] = ref("wrong-root.json", wrong_root)
        with self.assertRaises(EvaluationError):
            verify_incident(ref("wrong-root-incident.json", changed), after)
        incomplete = copy.deepcopy(after)
        incomplete["files"].pop("unchanged.json")
        with self.assertRaises(EvaluationError):
            verify_incident(bound, incomplete)

    def test_readonly_source_validator_authenticates_journal_without_append(self):
        from stage1_eval.reason_recovery import (
            readonly_guard,
            readonly_source_validator,
        )
        from stage1_eval.source_replay import EVENT_KIND

        result = self.root / "source-result.json"
        result.write_bytes(
            canonical({"receipt_sha256": "a" * 64, "source_version": "v1"})
        )
        prefix = [sys.executable, "-m", "research_hub"]
        report = {
            "schema_version": "source-fetch-validation/v1",
            "valid": True,
            "errors": [],
            "result_path": str(result.resolve()),
            "receipt_sha256": "a" * 64,
            "source_version": "v1",
            "checked_at": "old",
        }
        request = {
            "kind": EVENT_KIND,
            "attempt_id": "one",
            "event": "registered",
            "command": prefix + ["source", "validate", str(result), "--json"],
            "result_sha256": sha(result.read_bytes()),
            "counts_as_source_acquisition": False,
        }
        stdout = canonical(report)
        outcome = {
            **request,
            "event": "finished",
            "validation_passed": True,
            "status": "completed",
            "returncode": 0,
            "stdout_hex": stdout.hex(),
            "stdout_sha256": sha(stdout),
            "stderr_hex": "",
            "stderr_sha256": sha(b""),
        }
        journal = self.root / "journal.jsonl"
        original = canonical(request) + b"\n" + canonical(outcome) + b"\n"
        journal.write_bytes(original)
        plan = {
            "python_executable_sha256": "python",
            "research_hub_package_sha256": "package",
        }
        observations = []
        # Public validator is mocked here; real source parser fixtures are covered by source pipeline tests.
        with (
            mock.patch("stage1_eval.runtime.executable_sha256", return_value="python"),
            mock.patch(
                "stage1_eval.runtime.installed_package_sha256", return_value="package"
            ),
            mock.patch(
                "research_hub.source_fetch.validate_source_fetch",
                return_value={**report, "checked_at": "new"},
            ) as validator,
        ):
            callback = readonly_source_validator(plan, observations)
            with readonly_guard():
                callback(result, prefix, journal)
            validator.assert_called_once_with(result)
        self.assertEqual(journal.read_bytes(), original)
        self.assertNotIn("checked_at", observations[0]["report"])
        self.assertFalse(observations[0]["historical_journal"]["derived_prefix"])
        for bad in (
            original + canonical(request) + b"\n",
            original.replace(b'"status":"completed"', b'"status":"failed"'),
        ):
            journal.write_bytes(bad)
            with self.assertRaises(EvaluationError), readonly_guard():
                callback(result, prefix, journal)
            self.assertEqual(journal.read_bytes(), bad)

    def test_reason_only_delta_and_target_policy_fail_closed(self):
        candidate = _schema(list(self.aliases))
        require_reason_delta(self.schema, candidate)
        candidate["properties"]["verdict"]["enum"] = ["supported"]
        with self.assertRaises(EvaluationError):
            require_reason_delta(self.schema, candidate)
        policy = self.options["execution_policy"]
        source = {"targets": ["one"], "execution_policy": policy}
        target = {
            "kind": "Stage1ReasonRecoveryPlan.v1",
            "source_plan_sha256": "a" * 64,
            "source_bundle_sha256": "b" * 64,
            "target_bundle_sha256": "c" * 64,
            "targets": ["one"],
            "source_policy": policy,
            "target_policy": dict(policy, evaluator_bundle_sha256="c" * 64),
        }
        _plan_contract(source, target, "a" * 64, "b" * 64, "c" * 64)
        target["target_policy"]["timeout_seconds"] = 601
        with self.assertRaises(EvaluationError):
            _plan_contract(source, target, "a" * 64, "b" * 64, "c" * 64)


if __name__ == "__main__":
    unittest.main()
