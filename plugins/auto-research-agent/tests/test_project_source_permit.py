"""Real Core offers and shared budgets; no source, DNS, native or model calls."""

from copy import deepcopy
from pathlib import Path
import socket
import subprocess
import sys
import unittest
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.project_source_permit import (
    configuration,
    configuration_sha,
    inspect,
    proposal,
    public_source_uri,
)
from research_workspace_native.project_stage1 import _basis
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha
from test_project_stage1_library import Stage1LibraryFixture
from test_workspace_project_intake import bound_body, compile_body, submit_body


def source_config():
    return dict(
        caps=dict(
            max_fetches=4,
            max_reserved_seconds=120,
            timeout_seconds=30,
            validity_seconds=600,
            max_response_bytes=16 * 1024 * 1024,
            max_http_attempts=6,
        ),
        runtime_sha256="1" * 64,
        execution_source_sha256="2" * 64,
    )


class ProjectSourcePermitTests(Stage1LibraryFixture, unittest.TestCase):
    def new(self, key, topic="Synthetic source authority and saved decisions"):
        ref = self.intake.create(self.token, {"key": key, "topic": topic})[
            "project_ref"
        ]
        body = submit_body(self.intake.read(self.token, ref))
        body["consent"]["public_source_read"] = True
        body["budgets"].update(seconds=180, source_reads=3)
        body["resource_envelope"] = "Authored source offer fixture; no actual fetch."
        self.intake.submit(self.token, ref, body)
        self.intake.compile(
            self.token, ref, compile_body(self.intake.read(self.token, ref))
        )
        offer = self.stage1.read(self.token, ref)["initialization_offer"]
        self.stage1.initialize(
            self.token,
            ref,
            dict(
                bound_body(self.intake.read(self.token, ref), "initialize"),
                offer_ref=offer["offer_ref"],
                offer_sha256=offer["offer_sha256"],
                confirmed=True,
            ),
        )
        return ref

    def offer(self, name="retained", config=None, *, principal=None):
        return proposal(
            self.intake,
            self.stage1,
            self.ref,
            principal or self.principal,
            source_config() if config is None else config,
            self.work_by_name[name],
        )

    def check(self, document, offer, *, name="retained", config=None):
        return inspect(
            self.intake,
            self.stage1,
            self.ref,
            self.principal,
            source_config() if config is None else config,
            self.work_by_name[name],
            document,
            offer["offer_sha256"],
        )

    def state_budget(self, *, query=None, source=None):
        state = self.intake._load(self.principal, self.ref)
        if query is not None:
            state["stage1_query_budget"] = query
        if source is not None:
            state["stage1_source_budget"] = source
        with self.intake.db:
            self.intake._save(state, "authored-budget-fixture", {})

    def test_offer_binds_actual_candidate_decision_version_and_is_read_only(self):
        before = self.inventory()
        expected_git = [
            "git",
            "-C",
            str(self.intake.binding(self.ref)["plan_root"].parent),
            "rev-parse",
            "--show-toplevel",
        ]
        real_popen = subprocess.Popen

        def readonly_git_only(*args, **kwargs):
            self.assertEqual(args, (expected_git,))
            self.assertEqual(
                kwargs, dict(stdout=subprocess.PIPE, stderr=subprocess.PIPE)
            )
            return real_popen(*args, **kwargs)

        with (
            patch.object(
                socket, "getaddrinfo", side_effect=AssertionError("DNS called")
            ),
            patch("subprocess.Popen", side_effect=readonly_git_only),
        ):
            binding, document, offer = self.offer()
            checked = self.check(document, offer)
        self.assertEqual(checked, document)
        self.assertEqual(self.inventory(), before)
        self.runner.assert_not_called()
        candidate = self.ledger.candidates()[self.work_by_name["retained"]]
        self.assertEqual(
            document["selected"]["candidate_event_id"], candidate["event_id"]
        )
        self.assertEqual(
            document["selected"]["candidate_sha256"], sha(canonical(candidate))
        )
        self.assertEqual(document["selected"]["current_decision"], "include")
        self.assertEqual(
            document["selected"]["source_uri"],
            "https://doi.org/10.5555/library-retained",
        )
        self.assertEqual(document["binding"]["brief_sha256"], binding["brief_sha256"])
        self.assertEqual(
            document["binding"]["manifest_sha256"],
            sha((self.ledger.root / "run_manifest.json").read_bytes()),
        )
        self.assertEqual(document["limits"]["max_fetches"], 3)
        self.assertEqual(document["limits"]["max_reserved_seconds"], 120)
        self.assertEqual(
            document["binding"]["reservation_state_sha256"],
            sha(canonical(dict(stage1_query_budget=None, stage1_source_budget=None))),
        )
        self.assertIs(document["allow_source_acquisition"], True)
        self.assertIs(document["allow_search"], False)
        self.assertIs(document["execution_authorized"], False)
        self.assertIs(document["model_execution"], False)
        self.assertNotIn(str(self.root), canonical(offer).decode())

    def test_actual_pending_allowed_but_unscreened_and_excluded_not_manufactured(self):
        before = self.inventory()
        self.assertEqual(
            self.offer("pending")[1]["selected"]["current_decision"], "pending"
        )
        for name, code in (
            ("unscreened", "project-source-current-decision-required"),
            ("excluded", "project-source-current-work-excluded"),
        ):
            with self.subTest(name=name), self.assertRaises(SessionApiError) as error:
                self.offer(name)
            self.assertEqual(error.exception.code, code)
        self.assertEqual(self.inventory(), before)

    def test_shared_seconds_and_source_fetch_reservations_are_not_double_granted(self):
        self.state_budget(
            query=dict(probes=1, attempts=1, seconds=65),
            source=dict(fetches=1, seconds=40),
        )
        document = self.offer()[1]
        self.assertEqual(document["limits"]["max_reserved_seconds"], 75)
        self.assertEqual(document["limits"]["max_fetches"], 2)
        self.state_budget(
            query=dict(probes=1, attempts=2, seconds=130),
            source=dict(fetches=1, seconds=30),
        )
        with self.assertRaises(SessionApiError) as error:
            self.offer()
        self.assertEqual(
            error.exception.code, "project-source-requested-budget-insufficient"
        )
        self.assertEqual(error.exception.status, 429)

    def test_fractional_reserved_seconds_are_preserved_and_nonfinite_values_refuse(
        self,
    ):
        self.state_budget(
            query=dict(probes=1, attempts=1, seconds=62.5),
            source=dict(fetches=1, seconds=35.25),
        )
        before = self.inventory()
        document = self.offer()[1]
        self.assertEqual(document["limits"]["max_reserved_seconds"], 82.25)
        self.assertEqual(self.inventory(), before)
        # Nonfinite values cannot be serialized into an actual intake state;
        # reject them at the pure reservation boundary before any grant.
        from research_workspace_native.project_source_permit import _budget

        for value in (float("nan"), float("inf"), float("-inf"), True, -0.25):
            for name, budget in (
                ("stage1_query_budget", dict(probes=1, attempts=1, seconds=value)),
                ("stage1_source_budget", dict(fetches=1, seconds=value)),
            ):
                with (
                    self.subTest(name=name, value=value),
                    self.assertRaises(SessionApiError) as error,
                ):
                    _budget({name: budget}, name, tuple(budget))
                self.assertEqual(
                    error.exception.code, "project-source-reservation-state-invalid"
                )
        for name, budget in (
            ("stage1_query_budget", dict(probes=1, attempts=1.5, seconds=62.5)),
            ("stage1_source_budget", dict(fetches=1.5, seconds=35.25)),
        ):
            with self.subTest(name=name), self.assertRaises(SessionApiError):
                _budget({name: budget}, name, tuple(budget))

    def test_false_or_nonliteral_source_consent_and_zero_reads_refuse(self):
        original = self.intake._load(self.principal, self.ref)
        for consent, reads in ((False, 3), (1, 3), (True, 0)):
            state = deepcopy(original)
            # This intentionally corrupts saved settings: preserve the binding
            # too so this fixture reaches the contract's literal consent check.
            state["settings"]["consent"]["public_source_read"] = consent
            state["settings"]["budgets"]["source_reads"] = reads
            state["stage1_runs"][state["stage1_active"]]["binding"] = _basis(
                dict(
                    self.intake.binding(self.ref),
                    settings=state["settings"],
                )
            )
            with self.intake.db:
                self.intake._save(state, "authored-consent-fixture", {})
            with (
                self.subTest(consent=consent, reads=reads),
                self.assertRaises(SessionApiError) as error,
            ):
                self.offer()
            self.assertEqual(
                error.exception.code,
                "project-source-requested-budget-insufficient"
                if reads == 0
                else "project-source-consent-required",
            )
            with self.intake.db:
                self.intake._save(original, "restore-authored-fixture", {})

    def test_rehashed_changed_url_or_selected_version_does_not_rebind(self):
        _, document, offer = self.offer()
        for field, value in (
            ("source_uri", "https://example.org/another-source"),
            ("version_id", "another-version"),
        ):
            changed = deepcopy(document)
            changed["selected"][field] = value
            forged = dict(offer, offer_sha256=sha(canonical(changed)))
            with self.subTest(field=field), self.assertRaises(SessionApiError) as error:
                self.check(changed, forged)
            self.assertEqual(
                error.exception.code, "project-source-current-offer-differs"
            )

    def test_decision_reversal_and_new_reservation_stale_old_offer(self):
        _, document, offer = self.offer()
        self.decision("retained", "pending")
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer)
        self.assertEqual(error.exception.code, "project-source-current-offer-differs")
        _, document, offer = self.offer()
        self.state_budget(query=dict(probes=1, attempts=0, seconds=30))
        current = self.offer()[1]
        self.assertEqual(current["limits"], document["limits"])
        self.assertNotEqual(
            current["binding"]["reservation_state_sha256"],
            document["binding"]["reservation_state_sha256"],
        )
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer)
        self.assertEqual(error.exception.code, "project-source-current-offer-differs")

    def test_foreign_principal_missing_work_and_raw_brief_drift_refuse(self):
        with self.assertRaises(SessionApiError) as error:
            self.offer(principal="other-viewer")
        self.assertEqual(error.exception.code, "project-unavailable")
        with self.assertRaises(SessionApiError) as error:
            proposal(
                self.intake,
                self.stage1,
                self.ref,
                self.principal,
                source_config(),
                "missing",
            )
        self.assertEqual(error.exception.code, "project-source-work-unavailable")
        binding, document, offer = self.offer()
        path = binding["brief_path"]
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer)
        self.assertEqual(error.exception.code, "intake-source-bytes-differ")

    def test_current_saved_version_is_used_and_old_offer_becomes_stale(self):
        _, document, offer = self.offer("pending")
        self.query(3, [dict(self.metadata[2], version="v2")])
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer, name="pending")
        self.assertEqual(error.exception.code, "project-source-current-offer-differs")
        changed = self.offer("pending")[1]
        self.assertNotEqual(
            changed["selected"]["version_id"], document["selected"]["version_id"]
        )
        self.assertEqual(changed["selected"]["metadata"]["version"], "v2")

    def test_no_saved_doi_or_disabled_policy_has_no_url_fallback(self):
        config = source_config()
        config["url_policy"] = {"allow_doi_resolution": False}
        with self.assertRaises(SessionApiError) as error:
            self.offer(config=config)
        self.assertEqual(error.exception.code, "project-source-doi-resolution-disabled")
        metadata = dict(
            title="Authored DOI-free candidate", authors=["Fixture"], year=2024
        )
        self.query(3, [metadata])
        work = next(
            value["work_id"]
            for value in self.ledger.candidates().values()
            if value["discoveries"][-1]["record"]["title"] == metadata["title"]
        )
        self.ledger.decide(
            work,
            "pending",
            reason="fixture",
            rationale="Needs source review",
            evidence_refs=[
                self.ledger.candidates()[work]["discoveries"][-1]["source_ref"]
            ],
        )
        with self.assertRaises(SessionApiError) as error:
            proposal(
                self.intake,
                self.stage1,
                self.ref,
                self.principal,
                source_config(),
                work,
            )
        self.assertEqual(error.exception.code, "project-source-url-unavailable")

    def test_pending_source_and_malformed_reservations_refuse_without_recovery(self):
        self.state_budget(source=dict(fetches=True, seconds=0))
        with self.assertRaises(SessionApiError) as error:
            self.offer()
        self.assertEqual(
            error.exception.code, "project-source-reservation-state-invalid"
        )
        self.state_budget(source=dict(fetches=0, seconds=0))
        self.source_attempt("pending")
        before = self.inventory()
        with self.assertRaises(SessionApiError) as error:
            self.offer("pending")
        self.assertEqual(error.exception.code, "project-source-attempt-pending")
        self.assertEqual(self.inventory(), before)

    def test_configuration_and_manifest_changes_stale_offer(self):
        _, document, offer = self.offer()
        changed = source_config()
        changed["execution_source_sha256"] = "4" * 64
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer, config=changed)
        self.assertEqual(error.exception.code, "project-source-current-offer-differs")
        path = self.ledger.root / "run_manifest.json"
        path.write_bytes(path.read_bytes() + b" ")
        with self.assertRaises(SessionApiError) as error:
            self.check(document, offer)
        self.assertEqual(error.exception.code, "stage1-ledger-manifest-differs")


class ProjectSourceConfigurationTests(unittest.TestCase):
    def test_caps_configuration_and_runtime_bytes_remain_separate(self):
        original = source_config()
        self.assertEqual(
            configuration(original)["url_policy"], {"allow_doi_resolution": True}
        )
        for key, value in (
            ("max_response_bytes", 16 * 1024 * 1024 + 1),
            ("max_http_attempts", True),
            ("max_fetches", 0),
            ("timeout_seconds", 301),
        ):
            changed = deepcopy(original)
            changed["caps"][key] = value
            with self.subTest(key=key), self.assertRaises(SessionApiError):
                configuration(changed)
        changed = deepcopy(original)
        changed["runtime_sha256"] = "3" * 64
        self.assertNotEqual(configuration_sha(changed), configuration_sha(original))
        changed = dict(original, allow_source_acquisition=True)
        with self.assertRaises(SessionApiError):
            configuration(changed)

    def test_structural_public_url_validation_never_resolves_dns(self):
        with patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS called")
        ):
            self.assertEqual(
                public_source_uri("https://example.org/source.pdf"),
                "https://example.org/source.pdf",
            )
            for value in (
                "http://127.0.0.1/a",
                "https://[::1]/a",
                "https://localhost/a",
                "https://name.local/a",
                "https://name.internal/a",
                "https://10.0.0.1/a",
                "https://169.254.169.254/a",
                "https://name/a",
                "https://user:pass@example.org/a",
                "https://example.org/a?token=secret",
                "file:///tmp/source",
                "https://example.org/a#b",
                "https://example.org:8888/a",
                "https://example.org/\nsource",
                "https://example.org\\a",
                "https://example.org/\ud800",
            ):
                with self.subTest(value=value), self.assertRaises(SessionApiError):
                    public_source_uri(value)

    def test_core_source_credential_guard_rejects_oauth_nested_and_cookie_urls(self):
        with patch.object(
            socket, "getaddrinfo", side_effect=AssertionError("DNS called")
        ):
            for value in (
                "https://example.org/source?code=private-oauth",
                "https://example.org/source?return_url=https%3A%2F%2Fexample.org%2Fa%3Fcode%3Dprivate-oauth",
                "https://example.org/source?cookie=private-cookie",
                "https://example.org/source?clientAssertion=private-assertion",
                "https://example.org/source?redirect=https%3A%2F%2Fexample.org%2Fa%3Fsession_id%3Dprivate-session",
            ):
                with (
                    self.subTest(value=value),
                    self.assertRaises(SessionApiError) as error,
                ):
                    public_source_uri(value)
                self.assertEqual(error.exception.code, "project-source-url-invalid")
                self.assertNotIn("private-", str(error.exception))
