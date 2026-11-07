"""Native Windows root syntax and exact effective permission evidence."""

import copy
import hashlib
import os
import unittest

from stage2_live import native, native_policy
import test_stage2_plain_native_policy as fixture
from test_stage2_role_policy_controller import _runtime


class WindowsNamedPolicyTests(unittest.TestCase):
    def setUp(self):
        self.fixture = fixture.PlainNativePolicyTests()
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)

    def binding(self, args):
        return dict(
            args,
            workspace=str(self.fixture.fixture.workspace.resolve()),
            codex_home=str(self.fixture.fixture.home.resolve()),
        )

    def test_symbolic_root_capture_preserves_raw_hash_and_replay(self):
        raw, args = self.fixture.install()
        result = native.capture_native(
            **args, process_runner=self.fixture.fixture._runner
        )
        self.assertEqual(
            (self.fixture.output / "archive/profile-config.toml").read_bytes(), raw
        )
        self.assertEqual(
            result["stable_request_binding"]["policy_bindings"]["config_sha256"],
            hashlib.sha256(raw).hexdigest(),
        )
        replay = native.capture_native(
            **args,
            resume=True,
            record_sha256_receipt=result["record_sha256_receipt"],
            process_runner=lambda *a, **k: self.fail("replay dispatched"),
        )
        self.assertEqual(replay["resume_action"], "verified-replay-no-execution")

    def test_slash_config_is_accepted_only_on_posix(self):
        raw, _ = self.fixture.install()
        _, args = self.fixture.install(
            raw=raw.replace(b'":root" = "read"', b'"/" = "read"')
        )
        if os.name == "nt":
            with self.assertRaisesRegex(native.CaptureError, "restrictions differ"):
                native.capture_native(
                    **args, process_runner=self.fixture.fixture._runner
                )
            self.assertEqual(self.fixture.fixture.calls, [])
        else:
            native.capture_native(**args, process_runner=self.fixture.fixture._runner)

    def test_symbolic_config_does_not_allow_root_or_deny_drift(self):
        raw, _ = self.fixture.install()
        variants = [
            raw.replace(b'":root" = "read"', value)
            for value in (
                b'":root" = "write"',
                b'":minimal" = "read"',
                b'":unknown" = "read"',
                b'":root" = "read"\n"/" = "read"',
                b'":root" = "read"\n"C:/" = "write"',
            )
        ]
        variants.append(raw.replace(b' = "deny"', b' = "read"', 1))
        for altered in variants:
            with self.subTest(raw=altered):
                _, args = self.fixture.install(raw=altered)
                with self.assertRaises(native.CaptureError):
                    native.capture_native(
                        **args, process_runner=self.fixture.fixture._runner
                    )
                self.assertEqual(self.fixture.fixture.calls, [])
                self.assertFalse(self.fixture.output.exists())

    def test_runtime_root_is_exact_and_both_views_are_required(self):
        _, args = self.fixture.install()
        binding = self.binding(args)
        context = _runtime(binding)
        for fs in (
            context["permission_profile"]["file_system"],
            context["file_system_sandbox_policy"],
        ):
            fs["entries"][0]["path"] = {"type": "special", "value": {"kind": "root"}}
        native_policy.verify_named_runtime(binding, context)
        for view in ("permission", "sandbox"):
            for replacement in (
                {"type": "special", "value": {"kind": "minimal"}},
                {"type": "special", "value": {"kind": "root", "subpath": "x"}},
                {"type": "path", "path": ":root"},
                {"type": "special", "value": {"kind": "unknown"}},
            ):
                with self.subTest(view=view, replacement=replacement):
                    bad = copy.deepcopy(context)
                    fs = (
                        bad["permission_profile"]["file_system"]
                        if view == "permission"
                        else bad["file_system_sandbox_policy"]
                    )
                    fs["entries"][0]["path"] = replacement
                    with self.assertRaises(native_policy.NamedPolicyError):
                        native_policy.verify_named_runtime(binding, bad)
        for mutation in ("write", "duplicate", "missing-deny", "extra-write"):
            with self.subTest(mutation=mutation):
                bad = copy.deepcopy(context)
                entries = bad["permission_profile"]["file_system"]["entries"]
                if mutation == "write":
                    entries[0]["access"] = "write"
                elif mutation == "duplicate":
                    entries.append(
                        {"path": {"type": "path", "path": "/"}, "access": "read"}
                    )
                elif mutation == "missing-deny":
                    entries.pop()
                else:
                    entries.append(
                        {"path": {"type": "path", "path": "C:/"}, "access": "write"}
                    )
                with self.assertRaises(native_policy.NamedPolicyError):
                    native_policy.verify_named_runtime(binding, bad)


if __name__ == "__main__":
    unittest.main()
