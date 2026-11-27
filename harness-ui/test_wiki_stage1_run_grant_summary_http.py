"""Read-only Wiki summary of the launch consent and the Stage 1 run grant."""

# ruff: noqa: E402 -- the plugin and Wiki use repository-local imports.
from pathlib import Path
import sys
import unittest

sys.path[:0] = [str(Path(__file__).resolve().parent)]

from stage1_deliverable.common import sha
from test_wiki_stage1_run_grant_http import (
    BUDGETS,
    LIMITS,
    OPERATIONS,
    TOKEN,
    WORDS,
    ZERO,
    Fixture,
)


class RunGrantSummaryTests(Fixture, unittest.TestCase):
    def test_summary_is_read_only_and_reports_consent_grant_and_use(self):
        self.build()
        before = self.state()
        status, summary = self.call("GET", self.url())
        self.assertEqual(status, 200)
        self.assertEqual(summary["run_grant"], {"status": "none"})
        self.assertTrue(summary["consent"]["valid"])
        self.assertTrue(summary["consent"]["stages"]["stage1"]["covered"])
        self.assertEqual(summary["consent"]["stages"]["stage1"]["max_dispatches"], 1)
        self.assertFalse(summary["consent"]["stages"]["stage2"]["covered"])
        self.assertFalse(summary["consent"]["stages"]["stage3"]["covered"])
        self.assertFalse(summary["consent"]["expired"])
        self.assertTrue(summary["consent"]["expires_at"])
        self.assertEqual(summary["launch_limits"], LIMITS)
        self.assertEqual(summary["grant_creation"]["max_seconds"], 120)
        self.assertTrue(summary["grant_creation"]["available"])
        self.assertFalse(summary["execution_authorized"])
        self.assertEqual(self.state(), before)
        _, grant = self.create()
        after = self.state()
        for _ in range(3):
            status, summary = self.call("GET", self.url())
            self.assertEqual(status, 200)
        self.assertEqual(self.state(), after)
        run = summary["run_grant"]
        self.assertEqual(run["status"], "active")
        self.assertEqual(run["user_input"], WORDS)
        self.assertEqual(run["limits"], BUDGETS)
        self.assertEqual(sorted(run["operations"]), sorted(OPERATIONS))
        self.assertEqual(run["max_actions"], 4)
        self.assertEqual(run["actions_used"], 0)
        self.assertEqual(run["remaining_seconds"], 100)
        self.assertEqual(run["expires_at"], grant["expires_at"])
        self.assertEqual(run["grant_ref"], grant["grant_ref"])
        self.assertEqual(run["lease"], {"state": "open"})
        self.assertEqual(run["resources"]["status"], "available")
        self.assertEqual(run["resources"]["declared"]["seconds"], 120)
        self.assertFalse(run["resources"]["automatic_refund"])
        self.issuer.derive(
            TOKEN,
            self.ref,
            grant_ref=grant["grant_ref"],
            grant_sha256=grant["grant_sha256"],
            operation="query",
            identity="e" * 64,
        )
        _, summary = self.call("GET", self.url())
        self.assertEqual(summary["run_grant"]["actions_used"], 1)

    def test_an_existing_grant_closes_creation_in_the_summary(self):
        self.build()
        self.create()
        _, summary = self.call("GET", self.url())
        self.assertFalse(summary["grant_creation"]["available"])
        self.assertEqual(
            summary["grant_creation"]["reason"], "stage1-run-grant-renewal-refused"
        )
        self.now[0] += 101  # an expired grant still counts: the service never renews
        _, summary = self.call("GET", self.url())
        self.assertEqual(summary["run_grant"]["status"], "expired")
        self.assertFalse(summary["grant_creation"]["available"])

    def test_an_expired_grant_reads_as_expired_without_touching_the_lease(self):
        self.build()
        self.create()
        self.now[0] += 101
        before = self.state()
        status, summary = self.call("GET", self.url())
        self.assertEqual(status, 200)
        self.assertEqual(summary["run_grant"]["status"], "expired")
        self.assertEqual(summary["run_grant"]["remaining_seconds"], 0)
        self.assertEqual(summary["run_grant"]["lease"], {"state": "open"})
        self.assertEqual(self.state(), before)  # reading did not even mark the lease

    def test_an_expired_lease_written_by_a_real_use_is_reported(self):
        self.build()
        self.create()
        self.now[0] += 101
        project = self.intake.read(TOKEN, self.ref)
        status, _ = self.call(
            "POST",
            self.url(tail="progression"),
            {
                "input_version": project["input_version"],
                "brief_sha256": project["brief_sha256"],
                "confirmed": True,
            },
        )
        self.assertEqual(status, 409)
        _, summary = self.call("GET", self.url())
        self.assertEqual(summary["run_grant"]["status"], "expired")
        self.assertEqual(summary["run_grant"]["lease"], {"state": "expired"})

    def test_zero_launch_summary_says_creation_is_unavailable_and_writes_nothing(self):
        self.build(limits=ZERO, budgets=ZERO, consent=False)
        before = self.state()
        status, summary = self.call("GET", self.url())
        self.assertEqual(status, 200)
        self.assertFalse(summary["grant_creation"]["available"])
        self.assertEqual(
            summary["grant_creation"]["reason"], "stage1-run-grant-zero-limits"
        )
        self.assertEqual(summary["launch_limits"], ZERO)
        self.assertEqual(self.state(), before)

    def test_summary_without_consent_says_so(self):
        self.build(consent=False)
        _, summary = self.call("GET", self.url())
        self.assertFalse(summary["consent"]["present"])
        self.assertEqual(summary["consent"]["reason"], "consent-not-provided")

    def test_a_consent_that_no_longer_matches_the_project_is_not_valid(self):
        self.build()
        project = self.intake.read(TOKEN, self.ref)
        self.write_consent()
        raw = self.consent[self.ref][0].replace(
            project["brief_sha256"].encode(), b"f" * 64
        )
        self.consent[self.ref] = (raw, sha(raw))
        _, summary = self.call("GET", self.url())
        self.assertTrue(summary["consent"]["present"])
        self.assertFalse(summary["consent"]["valid"])
        self.assertEqual(
            summary["consent"]["reason"], "stage-progression-consent-binding-differs"
        )

    def test_a_host_without_whole_run_enabled_says_why(self):
        self.build(trusted=False)
        before = self.state()
        _, summary = self.call("GET", self.url())
        self.assertEqual(
            summary["grant_creation"]["reason"], "stage1-run-grant-not-enabled"
        )
        self.assertEqual(self.state(), before)

    def test_a_project_without_a_confirmed_scope_reads_as_not_ready(self):
        self.build()
        ref = self.intake.create(
            TOKEN,
            {"key": "bare", "topic": "Bare topic only"},
        )["project_ref"]
        before = self.state()
        status, summary = self.call("GET", self.url(ref))
        self.assertEqual(status, 200)
        self.assertEqual(
            summary["grant_creation"]["reason"], "stage1-run-grant-scope-not-ready"
        )
        self.assertEqual(summary["run_grant"], {"status": "none"})
        self.assertEqual(self.state(), before)

    def test_summary_of_an_unknown_project_is_404(self):
        self.build()
        status, body = self.call("GET", self.url("project-nope"))
        self.assertEqual((status, body["error"]), (404, "project-unavailable"))


if __name__ == "__main__":
    unittest.main()
