"""Public source metadata must never persist named credentials, including on replay."""

from copy import deepcopy
import json
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest
from urllib.parse import quote

from test_stage1_ledger import Ledger, SYNTHETIC, add_query, rewrite_for_tamper_test
from stage1_ledger.journal import LedgerError, canonical
from stage1_ledger.validation import validate_run
from stage1_ledger.readiness import readiness
from stage1_export.bundle import export_run


SECRET = "synthetic-credential-value"
PUBLIC = "https://example.invalid/paper?q=households&year=2026#page=2"
ERROR = "source-credentials-forbidden"
FIELD_PATHS = (
    "headers[Authorization]",
    "request.headers.Authorization",
    "cookie_header",
    "auth.jwt",
    "X-Auth",
    "headers%5BAuthorization%5D",
    "request%2Eheaders%2EAuthorization",
    "request\uff0eheaders\uff0e\uff21uthorization",
    "request/headers/Authorization",
    "request\\headers\\Authorization",
    "request[headers][0][Authorization]",
    "cookie-header",
    "X_Auth",
    "params[auth][jwt]",
    "request.headers.%EF%BC%A1uthorization",
    "request.headers.X-Auth",
    "request.cookies.session",
    "cookieHeader",
    "authJwt",
    "api_key_header",
    "access_token_header",
    "client_secret_header",
    "private_key_path",
    "request.headers.apiKeyHeader",
    "request%2Eparams%2Eaccess_token_header",
    "request.headers.accessTokenHeader",
)
FIELD_REQUESTS = [{name: SECRET} for name in FIELD_PATHS] + [
    {"request.headers": [["Authorization", SECRET]]},
    {"request[headers]": ["Authorization", SECRET]},
    {"request.headers[0]": ["X-Auth", SECRET]},
    {"reader.argv": ["--headers[Authorization]", SECRET]},
    {"request.headers[0]": "Authorization", "request.headers[1]": SECRET},
    {
        "request.headers[0].name": "Authorization",
        "request.headers[0].value": SECRET,
    },
    {"request.argv[0]": "--api-key", "request.argv[1]": SECRET},
    {"request": {"headers[0].name": "X-Auth", "headers[0].value": SECRET}},
    {"request": {"argv[0]": "--auth.jwt", "argv[1]": SECRET}},
    {"request%2Eheaders%5B0%5D": "Authorization", "request.headers[1]": SECRET},
    {"request.headers": ["Accept: text/plain", "Authorization: Bearer " + SECRET]},
]


class SourceCredentialTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.root = Path(self.directory.name)
        self.ledger = Ledger.create(
            self.root / "run", run_id="synthetic", objective="Synthetic scope"
        )
        add_query(self.ledger, [SYNTHETIC])
        self.ledger.extract()
        work = next(iter(self.ledger.candidates().values()))
        self.base = dict(
            work_id=work["work_id"],
            version_id=work["version_ids"][0],
            source_uri=PUBLIC,
            actor="synthetic-agent",
            reason="Read a synthetic public source",
        )
        self.request = dict(self.base, tool="synthetic-reader", request={"url": PUBLIC})

    def snapshot(self):
        return {
            p.relative_to(self.ledger.root): p.read_bytes()
            for p in self.ledger.root.rglob("*")
            if p.is_file()
        }

    def rejected(self, action):
        before = self.snapshot()
        with self.assertRaises(LedgerError) as caught:
            action()
        self.assertEqual(str(caught.exception), ERROR)
        self.assertEqual(self.snapshot(), before)
        self.assertNotIn(SECRET.encode(), b"".join(before.values()))

    def completion(self):
        attempt = self.ledger.start_source(**self.request)
        raw = self.ledger.save_bytes(b"Synthetic public text", producer=attempt)
        return dict(
            attempt_id=attempt,
            outcome="available",
            observed_at=self.ledger.clock(),
            http_status=200,
            resolved_uri=PUBLIC,
            raw_ref=raw,
            text_ref=raw,
            extraction={"method": "identity", "version": "1"},
            reason="Synthetic public capture",
        )

    def test_public_arguments_round_trip_without_sanitizing_or_upgrading(self):
        public = {
            "url": PUBLIC,
            "headers": {"Accept": "text/plain", "User-Agent": "synthetic-reader"},
            "params": {
                "doi": "10.5555/stage1-synthetic",
                "query": "人口 消費",
                "code": "KOR",
            },
            "max_tokens": 200,
            "keywords": ["token", "household"],
            "terms": ["key", "finding"],
            "country": {"code": "KOR"},
            "page_token": "public-pagination-position",
            "request.params.page_token": "public-pagination-position",
            "params[code]": "KOR",
            "params.code": "KOR",
            "request.params.max_tokens": 200,
            "request.headers": ["Accept: text/plain", "User-Agent: token"],
            "request.args": ["--page-token", "public-pagination-position"],
            "request%2Eparams%2Epage_token": "public-pagination-position",
            "params\uff0ecode": "KOR",
            "pageToken": "public-pagination-position",
            "reader.headers[0].name": "User-Agent",
            "reader.headers[0].value": "token",
            "reader.headers[1]": "User-Agent: token",
            "reader.argv[0]": "--page-token",
            "reader.argv[1]": "public-pagination-position",
            "pairs.headers": [["User-Agent", "token"]],
            "flat.headers[0]": "User-Agent",
            "flat.headers[1]": "token",
            "sort_key": "year",
            "request.params.sort_key": "year",
            "sortKey": "year",
            "options": [True, None, 2, {"page": 3}],
        }
        self.request["request"] = deepcopy(public)
        self.ledger.finish_source(**self.completion())
        started = next(
            r["payload"]
            for r in self.ledger.events()
            if r["payload"]["kind"] == "SourceReadStarted"
        )
        self.assertEqual(started["request"], public)
        self.assertEqual(self.request["request"], public)
        self.assertTrue(validate_run(self.ledger.root)["valid"])
        self.assertNotEqual(
            readiness(validate_run(self.ledger.root))[1], "stop-sufficient"
        )
        self.ledger.checkpoint()
        output = self.root / "export"
        self.assertTrue(export_run(self.ledger.root, output)["valid"])
        self.assertEqual(
            (output / "source/stage_events.jsonl").read_bytes(),
            (self.ledger.root / "stage_events.jsonl").read_bytes(),
        )

    def test_sensitive_fields_and_header_forms_rejected_before_persistence(self):
        keys = [
            "Authorization",
            "Proxy-Authorization",
            "Cookie",
            "Set-Cookie",
            "api_key",
            "X-API-Key",
            "apiKey",
            "access_token",
            "refresh-token",
            "client_secret",
            "password",
            "credential",
            "X-Amz-Security-Token",
            "Ocp-Apim-Subscription-Key",
            "private_key",
            "api_token",
            "auth_token",
            "X-Auth-Token",
            "session_token",
            "api_secret",
            "csrf_token",
            "oauth",
            "cookies",
            "http_auth",
            "passphrase",
            "client_assertion",
            "code_verifier",
            "session_id",
        ]
        requests = [{"options": [{"headers": {key: SECRET}}]} for key in keys]
        requests += [
            {"cookies": {"sessionid": SECRET}},
            {"http_auth": ["synthetic-user", SECRET]},
            {"headers": [["Authorization", "Bearer " + SECRET]]},
            {"headers": [{"name": "Authorization", "value": "Bearer " + SECRET}]},
            {"headers": ["Authorization: Bearer " + SECRET]},
            {"headers": "Accept: text/plain\nAuthorization: Bearer " + SECRET},
            {"headers": "Accept: text/plain\r\nX-Auth-Token: " + SECRET},
            {"headers": [{"Name": "Authorization", "Value": SECRET}]},
            {"headers": ["Accept", "text/plain", "Authorization", SECRET]},
            {"argv": ["--url", PUBLIC, "--api-key", SECRET]},
            {"url": "/paper?api_token=" + SECRET},
            {"url": "https://example.invalid/?api_key=" + SECRET},
            {"url": "https://user:" + SECRET + "@example.invalid/"},
        ]
        for index, request in enumerate(requests):
            with self.subTest(case=index):
                self.rejected(
                    lambda: self.ledger.start_source(
                        **dict(self.request, request=request)
                    )
                )

    def test_flattened_credential_fields_rejected_by_write_and_direct_append(self):
        payload = dict(
            self.request,
            kind="SourceReadStarted",
            scope="caller-attested-source-acquisition",
            previous_attempt_id=None,
        )
        for index, request in enumerate(FIELD_REQUESTS):
            with self.subTest(case=index):
                self.rejected(
                    lambda: self.ledger.start_source(
                        **dict(self.request, request=request)
                    )
                )
                self.rejected(
                    lambda: self.ledger.append(dict(payload, request=request))
                )

    def test_source_import_start_and_redirect_uris_reject_credentials(self):
        uris = [
            "https://user:" + SECRET + "@example.invalid/",
            "https://" + SECRET + "@example.invalid/",
            "https://example.invalid/?api_key=" + SECRET,
            "https://example.invalid/?%61ccess%5ftoken=" + SECRET,
            "https://example.invalid/#access_token=" + SECRET,
            "https://example.invalid/?X-Amz-Signature=" + SECRET,
            "https://example.invalid/callback?code=" + SECRET,
            "https://example.invalid/#/callback?access_token=" + SECRET,
            "https://example.invalid/#access_token=" + SECRET + "?ordinary=value",
            "https://example.invalid/#code=" + SECRET + "?ordinary=value",
            "https://example.invalid/?q=public;api_token=" + SECRET,
            "https://example.invalid/?redirect=https%3A%2F%2Fexample.invalid%2F%3Ftoken%3D"
            + SECRET,
        ]
        uris += [
            "https://example.invalid/?" + quote(name, safe="") + "=" + SECRET
            for name in FIELD_PATHS
        ]
        for index, uri in enumerate(uris):
            with self.subTest(case=index):
                self.rejected(
                    lambda: self.ledger.start_source(
                        **dict(self.request, source_uri=uri)
                    )
                )
                self.rejected(
                    lambda: self.ledger.start_source_import(
                        **dict(self.base, source_uri=uri)
                    )
                )
        completion = self.completion()
        for index, uri in enumerate(uris):
            with self.subTest(redirect=index):
                self.rejected(
                    lambda: self.ledger.finish_source(
                        **dict(completion, resolved_uri=uri)
                    )
                )

    def test_import_opaque_http_uri_and_malformed_uri_diagnostics(self):
        self.rejected(
            lambda: self.ledger.start_source_import(
                **dict(
                    self.base,
                    source_uri="https:example.invalid/paper?api_key=" + SECRET,
                )
            )
        )
        with self.assertRaisesRegex(LedgerError, "^source-public-uri-invalid$"):
            self.ledger.start_source(
                **dict(self.request, source_uri="https://[" + SECRET)
            )
        self.assertNotIn(SECRET.encode(), b"".join(self.snapshot().values()))

    def test_direct_append_and_schema_errors_cannot_echo_credentials(self):
        payload = dict(
            self.request,
            kind="SourceReadStarted",
            scope="caller-attested-source-acquisition",
            previous_attempt_id=None,
        )
        for request in [{"api_key": SECRET}, "Authorization: Bearer " + SECRET]:
            with self.subTest(shape=type(request).__name__):
                self.rejected(
                    lambda: self.ledger.append(dict(payload, request=request))
                )

    def test_rehashed_credentials_fail_independent_replay_recovery_gate_and_export(
        self,
    ):
        self.ledger.start_source_import(**self.base)
        self.ledger.finish_source(**self.completion())
        self.ledger.checkpoint()
        original = self.snapshot()
        changes = [
            ("SourceReadStarted", "request", {"cookies": {"sessionid": SECRET}}),
            ("SourceReadStarted", "request", {"http_auth": ["synthetic-user", SECRET]}),
            ("SourceReadStarted", "request", {"passphrase": SECRET}),
            ("SourceReadStarted", "request", {"client_assertion": SECRET}),
            (
                "SourceReadFinished",
                "resolved_uri",
                "https://example.invalid/#access_token=" + SECRET + "?ordinary=value",
            ),
            (
                "SourceReadStarted",
                "request",
                {"argv": ["--url", PUBLIC, "--api-key", SECRET]},
            ),
            (
                "SourceReadStarted",
                "request",
                {"headers": "Accept: text/plain\nAuthorization: Bearer " + SECRET},
            ),
            (
                "SourceImportStarted",
                "source_uri",
                "https:example.invalid/paper?api_token=" + SECRET,
            ),
            (
                "SourceReadStarted",
                "request",
                {"headers": {"Authorization": "Bearer " + SECRET}},
            ),
            ("SourceReadStarted", "request", {"api_key": SECRET}),
            (
                "SourceReadStarted",
                "source_uri",
                "https://user:" + SECRET + "@example.invalid/",
            ),
            (
                "SourceReadFinished",
                "resolved_uri",
                "https://example.invalid/?token=" + SECRET,
            ),
            (
                "SourceImportStarted",
                "source_uri",
                "https://example.invalid/#access_token=" + SECRET,
            ),
        ]
        changes += [
            ("SourceReadStarted", "request", request) for request in FIELD_REQUESTS
        ]
        for index, (kind, key, value) in enumerate(changes):
            with self.subTest(case=index):

                def mutate(rows):
                    next(r["payload"] for r in rows if r["payload"]["kind"] == kind)[
                        key
                    ] = value

                rewrite_for_tamper_test(self.ledger, mutate)
                report = validate_run(self.ledger.root)
                self.assertFalse(report["valid"])
                self.assertIn(ERROR, " ".join(report["errors"]))
                self.assertNotIn(SECRET, json.dumps(report))
                self.assertNotEqual(readiness(report)[1], "stop-sufficient")
                with self.assertRaisesRegex(LedgerError, ERROR):
                    self.ledger.recover()
                target = self.root / ("export-" + str(index))
                with self.assertRaisesRegex(LedgerError, ERROR):
                    export_run(self.ledger.root, target)
                self.assertFalse(target.exists())
                for path, raw in original.items():
                    (self.ledger.root / path).write_bytes(raw)

    def test_public_cli_error_never_echoes_or_persists_credentials(self):
        request_path = self.root / "caller-input.json"
        request_path.write_bytes(
            canonical(dict(self.request, request={"api_key": SECRET}))
        )
        before = self.snapshot()
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "stage1_ledger",
                "--run",
                str(self.ledger.root),
                "start-source",
                "--request",
                str(request_path),
            ],
            cwd=Path(__file__).resolve().parents[1] / "cli",
            capture_output=True,
            check=False,
        )
        self.assertEqual(result.returncode, 1)
        self.assertEqual(json.loads(result.stdout)["error"], ERROR)
        self.assertNotIn(SECRET.encode(), result.stdout + result.stderr)
        self.assertEqual(self.snapshot(), before)


if __name__ == "__main__":
    unittest.main()
