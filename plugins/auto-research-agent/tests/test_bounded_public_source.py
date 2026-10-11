"""Authored transport fixtures only; no DNS, external HTTP, native or models."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
import json
import http.client
import os
from pathlib import Path
import socket
import ssl
import sys
import tempfile
import unittest
from unittest.mock import Mock, patch
from urllib.parse import urlsplit

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "cli"))

from research_workspace_native.bounded_public_source import (
    TypedBoundedResolver,
    SourceTransportError,
    _Deadline,
    _DeadlineChannel,
    _Engine,
    _PinnedConnection,
    acquire_public_source,
    request_binding,
)
from research_workspace_native.session_api import SessionApiError
from stage1_deliverable.common import canonical, sha


NOW = datetime(2026, 10, 11, tzinfo=timezone.utc)
ADDRESS = "93.184.216.34"


def request():
    return dict(
        kind="BoundedPublicSourceRequest",
        schema_version="1.0.0",
        request_id="source-job-1",
        job_binding_sha256="1" * 64,
        source_uri="https://example.org/paper.pdf",
        runtime_sha256="2" * 64,
        resolver_sha256="3" * 64,
        deadline_utc=(NOW + timedelta(seconds=20)).isoformat(),
        total_timeout_seconds=15,
        io_timeout_seconds=3,
        max_http_attempts=3,
        max_response_bytes=4096,
        max_aggregate_bytes=8192,
    )


class Resolver(TypedBoundedResolver):
    def __init__(self, addresses=(ADDRESS,), callback=None):
        self.addresses, self.callback = addresses, callback
        self.calls = []

    @property
    def binding_sha256(self):
        return "3" * 64

    def resolve(self, host, port, deadline):
        self.calls.append((host, port, deadline))
        if self.callback:
            self.callback()
        return self.addresses


class Response:
    def __init__(
        self,
        body=b"%PDF-authored-bytes",
        status=200,
        headers=None,
        failure=None,
        on_read=None,
        close_error=False,
        on_close=None,
    ):
        self.body, self.status = body, status
        self.headers = headers or {"Content-Type": "application/pdf"}
        self.failure, self.on_read = failure, on_read
        self.close_error = close_error
        self.on_close = on_close
        self.offset, self.closed, self.reads = 0, False, []

    def getheader(self, name, default=None):
        return self.headers.get(name, default)

    def read1(self, amount):
        self.reads.append(amount)
        if self.on_read:
            self.on_read()
        if self.failure is not None and self.offset:
            raise self.failure
        size = min(amount, 5 if self.failure is not None else amount)
        data = self.body[self.offset : self.offset + size]
        self.offset += len(data)
        self.closed = self.offset == len(self.body)
        return data

    def isclosed(self):
        return self.closed

    def close(self):
        if self.on_close:
            self.on_close()
        if self.close_error:
            raise OSError("authored cleanup failure")


class Connection:
    def __init__(self, response, peer=ADDRESS):
        self.response, self.peer_address = response, peer
        self.requests, self.connects, self.closes = [], 0, 0

    def connect(self):
        self.connects += 1

    def request(self, method, target, headers):
        self.requests.append((method, target, deepcopy(headers)))

    def getresponse(self):
        return self.response

    def close(self):
        self.closes += 1


class BoundedPublicSourceTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(prefix="bounded-public-source-")
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.connections = []
        self.tick = 10.0

    def engine(self, responses, *, value=None, resolver=None, peer=ADDRESS):
        queue = iter(responses)

        def connection(parsed, address, deadline):
            self.assertEqual(address, ADDRESS)
            self.assertLessEqual(deadline.end, 25)
            self.assertEqual(parsed.hostname, "example.org")
            result = Connection(next(queue), peer)
            self.connections.append(result)
            return result

        return _Engine(
            value or request(),
            self.root / "capture",
            resolver or Resolver(),
            lambda: NOW,
            lambda: self.tick,
            connection,
        )

    def assert_receipt(self, receipt):
        self.assertEqual(receipt["request_sha256"], sha(canonical(receipt["request"])))
        self.assertEqual(receipt["http_attempts"], len(receipt["attempts"]))
        self.assertEqual(
            receipt["http_requests_attempted"],
            sum(row["http_request_attempted"] for row in receipt["attempts"]),
        )
        self.assertEqual(
            receipt["aggregate_bytes"],
            sum(row["body_bytes"] for row in receipt["attempts"]),
        )
        for row in receipt["attempts"]:
            if row["raw_path"] is not None:
                raw = (self.root / "capture" / row["raw_path"]).read_bytes()
                self.assertEqual(
                    (len(raw), sha(raw)), (row["body_bytes"], row["raw_sha256"])
                )
        original = (self.root / "capture/public-source-acquisition.json").read_bytes()
        self.assertEqual(json.loads(original), receipt)

    def test_unconfigured_or_wrong_binding_refuses_before_output_or_network(self):
        with (
            patch("socket.socket", side_effect=AssertionError("network forbidden")),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
        ):
            with self.assertRaisesRegex(SessionApiError, "bounded-resolver-required"):
                acquire_public_source(
                    request(), self.root / "missing", clock_utc=lambda: NOW
                )
            value = request()
            value["resolver_sha256"] = "4" * 64
            with self.assertRaisesRegex(SessionApiError, "resolver-binding-differs"):
                self.engine([], value=value)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_complete_response_has_real_body_hash_and_no_sdk_or_reading_claim(self):
        receipt = self.engine([Response()]).run()
        self.assert_receipt(receipt)
        self.assertEqual(receipt["kind"], "PublicSourceAcquisitionReceipt")
        self.assertEqual(
            (receipt["status"], receipt["outcome"], receipt["body_complete"]),
            ("completed", "http-body-complete", True),
        )
        self.assertNotIn("evidence_level", receipt)
        headers = self.connections[0].requests[0][2]
        self.assertEqual(headers["Host"], "example.org")
        self.assertFalse(
            {"Cookie", "Authorization", "Proxy-Authorization"} & set(headers)
        )
        self.assertEqual(self.connections[0].closes, 1)

    def test_private_address_mixed_dns_and_changed_peer_send_no_http(self):
        for addresses, peer in (
            ((ADDRESS, "127.0.0.1"), ADDRESS),
            ((ADDRESS,), "8.8.8.8"),
        ):
            with self.subTest(addresses=addresses, peer=peer):
                engine = self.engine(
                    [Response()], resolver=Resolver(addresses), peer=peer
                )
                receipt = engine.run()
                self.assertEqual(receipt["http_requests_attempted"], 0)
                self.assertFalse(receipt["body_complete"])
                self.assert_receipt(receipt)
                # Use a fresh immutable output for the next authored case.
                self.root = self.root / "next"
                self.root.mkdir()

    def test_initial_secret_and_redirect_secret_refuse_without_next_dns(self):
        value = request()
        value["source_uri"] = "https://example.org/paper?code=secret-value"
        with self.assertRaises(SessionApiError):
            request_binding(value)
        resolver = Resolver()
        response = Response(
            b"redirect body",
            302,
            {"Location": "https://example.org/?token=secret-value"},
        )
        receipt = self.engine([response], resolver=resolver).run()
        self.assertEqual(len(resolver.calls), 1)
        self.assertEqual(receipt["outcome"], "unsafe-url")
        self.assertFalse(receipt["body_complete"])
        self.assertNotIn("secret-value", canonical(receipt).decode())
        self.assert_receipt(receipt)

    def test_redirect_cap_and_aggregate_bound_preserve_each_original_body(self):
        value = request()
        value.update(max_http_attempts=2, max_aggregate_bytes=8)

        def redirect():
            return Response(b"1234", 302, {"Location": "https://example.org/next"})

        receipt = self.engine([redirect(), redirect()], value=value).run()
        self.assertEqual(
            (receipt["outcome"], receipt["http_attempts"]), ("attempt-limit", 2)
        )
        self.assertEqual(receipt["aggregate_bytes"], 8)
        self.assert_receipt(receipt)

    def test_declared_oversize_and_unknown_length_bound_do_not_read_cap_plus_one(self):
        response = Response(b"x" * 100, headers={"Content-Length": "100"})
        value = request()
        value["max_response_bytes"] = 8
        receipt = self.engine([response], value=value).run()
        self.assertEqual(receipt["outcome"], "response-too-large")
        self.assertEqual(response.reads, [])
        self.assert_receipt(receipt)
        self.root = self.root / "next"
        self.root.mkdir()
        response = Response(b"x" * 9)
        receipt = self.engine([response], value=value).run()
        self.assertEqual(receipt["outcome"], "body-bound-reached")
        self.assertEqual(response.offset, 8)
        self.assertFalse(receipt["body_complete"])
        self.assert_receipt(receipt)

    def test_http_failure_and_timeout_keep_response_and_partial_prefix(self):
        receipt = self.engine([Response(b"not found", 404)]).run()
        self.assertEqual(receipt["outcome"], "not-found")
        self.assertFalse(receipt["body_complete"])
        self.assertTrue(receipt["attempts"][0]["body_complete"])
        self.assert_receipt(receipt)
        self.root = self.root / "next"
        self.root.mkdir()
        receipt = self.engine(
            [Response(b"saved-prefix-more", failure=TimeoutError())]
        ).run()
        self.assertEqual(receipt["outcome"], "network-timeout")
        self.assertEqual(receipt["attempts"][0]["body_bytes"], 5)
        self.assertFalse(receipt["attempts"][0]["body_complete"])
        self.assert_receipt(receipt)

    def test_declared_short_body_and_incomplete_read_partial_remain_unusable(self):
        response = Response(b"short", headers={"Content-Length": "20"})
        receipt = self.engine([response]).run()
        self.assertEqual(receipt["outcome"], "incomplete-body")
        self.assertFalse(receipt["body_complete"])
        self.assert_receipt(receipt)
        self.root = self.root / "next"
        self.root.mkdir()
        response = Response(
            b"first-more", failure=http.client.IncompleteRead(b"partial", 20)
        )
        receipt = self.engine([response]).run()
        self.assertEqual(receipt["outcome"], "incomplete-body")
        self.assertEqual(receipt["aggregate_bytes"], len(b"firstpartial"))
        self.assertFalse(receipt["attempts"][0]["body_complete"])
        self.assert_receipt(receipt)

    def test_deadline_after_resolver_and_after_body_retains_unknown_without_retry(self):
        def expired():
            self.tick = 26

        receipt = self.engine([], resolver=Resolver(callback=expired)).run()
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "deadline-exceeded"),
        )
        self.assertEqual(self.connections, [])
        self.assert_receipt(receipt)
        self.root = self.root / "next"
        self.root.mkdir()
        self.tick = 10
        receipt = self.engine([Response(b"observed", on_read=expired)]).run()
        self.assertEqual(receipt["status"], "interrupted")
        self.assertEqual(receipt["aggregate_bytes"], len(b"observed"))
        self.assertFalse(receipt["body_complete"])
        self.assert_receipt(receipt)

    def test_interrupt_and_cleanup_failure_save_unknown_original_receipt(self):
        engine = self.engine(
            [Response(b"prefix-remainder", failure=KeyboardInterrupt())]
        )
        with self.assertRaises(KeyboardInterrupt):
            engine.run()
        receipt = json.loads(
            (self.root / "capture/public-source-acquisition.json").read_bytes()
        )
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "execution-unknown"),
        )
        self.assertEqual(receipt["aggregate_bytes"], 5)
        self.assert_receipt(receipt)
        self.root = self.root / "next"
        self.root.mkdir()
        receipt = self.engine([Response(close_error=True)]).run()
        self.assertEqual(receipt["status"], "interrupted")
        self.assertEqual(
            receipt["attempts"][0]["error_code"], "connection-cleanup-unobserved"
        )
        self.assert_receipt(receipt)

    def test_close_deadline_rejects_success_and_preserves_saved_body(self):
        response = Response(b"observed", on_close=lambda: setattr(self, "tick", 26))
        receipt = self.engine([response]).run()
        self.assertEqual(
            (receipt["status"], receipt["outcome"], receipt["body_complete"]),
            ("interrupted", "deadline-exceeded", False),
        )
        self.assertFalse(receipt["attempts"][0]["body_complete"])
        self.assertEqual(receipt["aggregate_bytes"], len(b"observed"))
        self.assertEqual(len(self.connections), 1)
        self.assert_receipt(receipt)

    def test_raw_fsync_deadline_rejects_success_and_preserves_saved_body(self):
        original = os.fsync
        calls = []

        def delayed(fd):
            result = original(fd)
            calls.append(fd)
            if len(calls) == 1:
                self.tick = 26
            return result

        with patch("os.fsync", side_effect=delayed):
            receipt = self.engine([Response(b"observed")]).run()
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "deadline-exceeded"),
        )
        self.assertFalse(receipt["body_complete"])
        self.assertEqual(receipt["attempts"][0]["raw_sha256"], sha(b"observed"))
        self.assertEqual(len(self.connections), 1)
        self.assert_receipt(receipt)

    def test_raw_hash_deadline_rejects_success_and_preserves_saved_body(self):
        original = os.fdopen
        case = self

        class Reader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, maximum):
                result = self.stream.read(maximum)
                case.tick = 26
                return result

        with patch("os.fdopen", side_effect=lambda *args: Reader(original(*args))):
            receipt = self.engine([Response(b"observed")]).run()
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "deadline-exceeded"),
        )
        self.assertFalse(receipt["body_complete"])
        self.assertEqual(receipt["aggregate_bytes"], len(b"observed"))
        self.assert_receipt(receipt)

    def test_expanded_raw_uses_bounded_read_and_never_claims_a_prefix_as_file_hash(
        self,
    ):
        original = os.fdopen
        reads = []

        class Reader:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def fileno(self):
                return self.stream.fileno()

            def read(self, maximum):
                reads.append(maximum)
                return self.stream.read(maximum)

        value = request()
        value["max_response_bytes"] = 8
        raw_path = self.root / "capture/raw/001.response"
        expanded = b"authored-expanded-file" * 10
        response = Response(
            b"observed", on_close=lambda: raw_path.write_bytes(expanded)
        )
        with patch("os.fdopen", side_effect=lambda *args: Reader(original(*args))):
            with self.assertRaisesRegex(SourceTransportError, "artifact-read-bound"):
                self.engine([response], value=value).run()
        self.assertEqual(reads, [9])
        self.assertEqual(raw_path.read_bytes(), expanded)
        receipt_bytes = (
            self.root / "capture/public-source-acquisition.json"
        ).read_bytes()
        receipt = json.loads(receipt_bytes)
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "execution-unknown"),
        )
        self.assertFalse(receipt["body_complete"])
        self.assertIsNone(receipt["raw_path"])
        self.assertIsNone(receipt["raw_sha256"])
        attempt = receipt["attempts"][0]
        self.assertEqual(attempt["error_code"], "artifact-read-unobserved")
        self.assertEqual(attempt["raw_path"], "raw/001.response")
        self.assertIsNone(attempt["raw_sha256"])
        self.assertFalse(attempt["body_complete"])
        self.assertEqual(receipt["http_requests_attempted"], 1)
        self.assertEqual(len(self.connections), 1)
        with self.assertRaisesRegex(SessionApiError, "output-exists"):
            self.engine([Response()], value=value)
        self.assertEqual(len(self.connections), 1)
        self.assertEqual(raw_path.read_bytes(), expanded)
        self.assertEqual(
            (self.root / "capture/public-source-acquisition.json").read_bytes(),
            receipt_bytes,
        )

    def test_raw_directory_or_hardlink_is_refused_without_a_complete_file_hash(self):
        for change in ("directory", "hardlink"):
            with self.subTest(change=change):
                raw_path = self.root / "capture/raw/001.response"

                def replace():
                    if change == "directory":
                        raw_path.unlink()
                        raw_path.mkdir()
                    else:
                        os.link(raw_path, self.root / "other-raw-link")

                response = Response(b"observed", on_close=replace)
                with self.assertRaisesRegex(
                    SourceTransportError, "artifact-file-invalid"
                ):
                    self.engine([response]).run()
                receipt = json.loads(
                    (self.root / "capture/public-source-acquisition.json").read_bytes()
                )
                self.assertEqual(
                    (receipt["status"], receipt["outcome"]),
                    ("interrupted", "execution-unknown"),
                )
                self.assertFalse(receipt["body_complete"])
                self.assertIsNone(receipt["attempts"][0]["raw_sha256"])
                self.assertEqual(
                    len(self.connections), 1 if change == "directory" else 2
                )
                self.root = self.root / "next"
                self.root.mkdir()

    def test_receipt_fsync_deadline_keeps_immutable_receipt_and_separate_failure(self):
        original = os.fsync
        calls = []

        def delayed(fd):
            result = original(fd)
            calls.append(fd)
            if len(calls) == 2:
                self.tick = 26
            return result

        with patch("os.fsync", side_effect=delayed):
            with self.assertRaisesRegex(SourceTransportError, "deadline-exceeded"):
                self.engine([Response(b"observed")]).run()
        receipt_path = self.root / "capture/public-source-acquisition.json"
        original_bytes = receipt_path.read_bytes()
        receipt = json.loads(original_bytes)
        self.assertEqual(
            (receipt["status"], receipt["outcome"]), ("completed", "http-body-complete")
        )
        self.assert_receipt(receipt)
        failure_path = self.root / "capture/public-source-acquisition-failure.json"
        failure = json.loads(failure_path.read_bytes())
        self.assertEqual(failure["kind"], "PublicSourceAcquisitionFailureObservation")
        self.assertEqual(failure["phase"], "post-receipt-publication")
        self.assertEqual(
            (failure["status"], failure["outcome"]),
            ("execution-unknown", "deadline-exceeded"),
        )
        self.assertEqual(failure["request_sha256"], receipt["request_sha256"])
        self.assertEqual(failure["acquisition_receipt_path"], receipt_path.name)
        self.assertEqual(failure["acquisition_receipt_sha256"], sha(original_bytes))
        failure_bytes = failure_path.read_bytes()
        with self.assertRaisesRegex(SessionApiError, "output-exists"):
            self.engine([Response()])
        self.assertEqual(len(self.connections), 1)
        self.assertEqual(receipt_path.read_bytes(), original_bytes)
        self.assertEqual(failure_path.read_bytes(), failure_bytes)

    def test_post_publication_failure_collision_is_not_overwritten_or_success(self):
        original = os.fsync
        calls = []
        failure_path = self.root / "capture/public-source-acquisition-failure.json"

        def delayed(fd):
            result = original(fd)
            calls.append(fd)
            if len(calls) == 2:
                failure_path.write_bytes(b"earlier unknown observation")
                self.tick = 26
            return result

        with patch("os.fsync", side_effect=delayed):
            with self.assertRaises(FileExistsError):
                self.engine([Response(b"observed")]).run()
        self.assertEqual(failure_path.read_bytes(), b"earlier unknown observation")
        receipt = json.loads(
            (self.root / "capture/public-source-acquisition.json").read_bytes()
        )
        self.assert_receipt(receipt)
        self.assertEqual(len(self.connections), 1)

    def test_raw_drift_rejects_success_with_actual_physical_length_and_hash(self):
        for changed in (b"short", b"modified", b"longer-than-observed"):
            with self.subTest(changed=changed):
                raw_path = self.root / "capture/raw/001.response"
                response = Response(
                    b"observed", on_close=lambda: raw_path.write_bytes(changed)
                )
                receipt = self.engine([response]).run()
                self.assertEqual(
                    (receipt["status"], receipt["outcome"]),
                    ("interrupted", "execution-unknown"),
                )
                self.assertFalse(receipt["body_complete"])
                attempt = receipt["attempts"][0]
                self.assertEqual(attempt["error_code"], "raw-body-differs")
                self.assertFalse(attempt["body_complete"])
                self.assertEqual(
                    (attempt["body_bytes"], attempt["raw_sha256"]),
                    (len(changed), sha(changed)),
                )
                self.assertEqual(receipt["aggregate_bytes"], len(changed))
                self.assert_receipt(receipt)
                self.root = self.root / "next"
                self.root.mkdir()

    def test_short_write_retains_actual_prefix_without_promoting_complete_body(self):
        original = Path.open

        class ShortWriter:
            def __init__(self, stream):
                self.stream = stream

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return self.stream.__exit__(*args)

            def write(self, value):
                return self.stream.write(value[:-1])

            def flush(self):
                return self.stream.flush()

            def fileno(self):
                return self.stream.fileno()

        def partial(path, mode="r", *args, **kwargs):
            stream = original(path, mode, *args, **kwargs)
            return (
                ShortWriter(stream)
                if mode == "xb" and path.name == "001.response"
                else stream
            )

        with patch.object(Path, "open", partial):
            receipt = self.engine([Response(b"observed")]).run()
        self.assertEqual(
            (receipt["status"], receipt["outcome"]),
            ("interrupted", "artifact-write-unobserved"),
        )
        self.assertFalse(receipt["body_complete"])
        self.assertEqual(receipt["aggregate_bytes"], len(b"observe"))
        self.assertEqual(receipt["attempts"][0]["raw_sha256"], sha(b"observe"))
        self.assert_receipt(receipt)

    def test_gzip_response_refuses_before_reading_or_saving_body(self):
        response = Response(b"compressed", headers={"Content-Encoding": "gzip"})
        receipt = self.engine([response]).run()
        self.assertEqual(receipt["outcome"], "content-encoding-not-supported")
        self.assertFalse(receipt["body_complete"])
        self.assertIsNone(receipt["attempts"][0]["raw_path"])
        self.assertEqual(response.reads, [])
        self.assert_receipt(receipt)

    def test_disabled_tls_verification_refuses_before_wrap_or_http(self):
        for check_hostname, verify_mode in (
            (False, ssl.CERT_REQUIRED),
            (True, ssl.CERT_NONE),
        ):
            with self.subTest(check_hostname=check_hostname, verify_mode=verify_mode):
                sock = Mock()
                sock.getpeername.return_value = (ADDRESS, 443)
                context = Mock(check_hostname=check_hostname, verify_mode=verify_mode)
                deadline = _Deadline(request(), lambda: NOW, lambda: self.tick)
                with (
                    patch("socket.socket", return_value=sock),
                    patch("ssl.create_default_context", return_value=context),
                    patch(
                        "socket.getaddrinfo",
                        side_effect=AssertionError("DNS forbidden"),
                    ),
                ):
                    connection = _PinnedConnection(
                        urlsplit(request()["source_uri"]), ADDRESS, deadline
                    )
                    with self.assertRaisesRegex(
                        SourceTransportError, "tls-verification-required"
                    ):
                        connection.connect()
                context.wrap_socket.assert_not_called()
                sock.sendall.assert_not_called()
                sock.close.assert_called_once()

    def test_same_output_never_reexecutes_and_request_limits_reject_invalid_values(
        self,
    ):
        original = self.engine([Response()]).run()
        with self.assertRaisesRegex(SessionApiError, "output-exists"):
            self.engine([Response()])
        self.assertEqual(len(self.connections), 1)
        self.assert_receipt(original)
        for key, value in (
            ("max_http_attempts", True),
            ("max_response_bytes", 2**30),
            ("total_timeout_seconds", float("nan")),
            ("io_timeout_seconds", float("inf")),
        ):
            altered = request()
            altered[key] = value
            with self.subTest(key=key), self.assertRaises(SessionApiError):
                request_binding(altered)

    def test_direct_socket_uses_numeric_peer_and_tls_origin_and_per_read_deadline(self):
        class Sock:
            def __init__(self):
                self.targets, self.timeouts, self.closed = [], [], False

            def settimeout(self, value):
                self.timeouts.append(value)

            def connect(self, target):
                self.targets.append(target)

            def getpeername(self):
                return ADDRESS, 443

            def recv_into(self, buffer):
                buffer[:1] = b"x"
                return 1

            def sendall(self, value):
                pass

            def close(self):
                self.closed = True

        sock = Sock()
        context = type(
            "Context", (), dict(check_hostname=True, verify_mode=ssl.CERT_REQUIRED)
        )()
        names = []
        context.wrap_socket = lambda value, server_hostname: (
            names.append(server_hostname) or value
        )
        deadline = _Deadline(request(), lambda: NOW, lambda: self.tick)
        with (
            patch("socket.socket", return_value=sock) as create,
            patch("ssl.create_default_context", return_value=context),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
        ):
            connection = _PinnedConnection(
                urlsplit(request()["source_uri"]), ADDRESS, deadline
            )
            connection.connect()
            self.assertEqual(
                create.call_args.args, (socket.AF_INET, socket.SOCK_STREAM)
            )
            self.assertEqual(sock.targets, [(ADDRESS, 443)])
            self.assertEqual(names, ["example.org"])
            channel = _DeadlineChannel(sock, deadline)
            reader = channel.makefile("rb")
            self.assertEqual(reader.read1(1), b"x")
            self.tick = 26
            with self.assertRaisesRegex(Exception, "deadline-exceeded"):
                reader.read1(1)
            reader.close()
            connection.close()
        self.assertTrue(sock.closed)

    def test_stdlib_http_connection_close_keeps_body_stream_alive_and_no_dns(self):
        class Sock:
            def __init__(self):
                self.response = (
                    b"HTTP/1.1 200 OK\r\nConnection: close\r\n"
                    b"Content-Type: text/plain\r\nContent-Length: 8\r\n\r\n"
                    b"observed"
                )
                self.sent, self.closed = [], False

            def settimeout(self, value):
                pass

            def connect(self, target):
                self.target = target

            def getpeername(self):
                return ADDRESS, 443

            def recv_into(self, buffer):
                self.assert_open()
                data, self.response = (
                    self.response[: len(buffer)],
                    self.response[len(buffer) :],
                )
                buffer[: len(data)] = data
                return len(data)

            def sendall(self, value):
                self.assert_open()
                self.sent.append(value)

            def assert_open(self):
                if self.closed:
                    raise OSError("authored closed socket")

            def close(self):
                self.closed = True

        sock = Sock()
        context = type(
            "Context", (), dict(check_hostname=True, verify_mode=ssl.CERT_REQUIRED)
        )()
        context.wrap_socket = lambda value, server_hostname: value
        with (
            patch("socket.socket", return_value=sock),
            patch("ssl.create_default_context", return_value=context),
            patch("socket.getaddrinfo", side_effect=AssertionError("DNS forbidden")),
        ):
            receipt = _Engine(
                request(),
                self.root / "capture",
                Resolver(),
                lambda: NOW,
                lambda: self.tick,
            ).run()
        self.assertEqual(receipt["outcome"], "http-body-complete")
        self.assertEqual(receipt["body_bytes"], 8)
        self.assertTrue(sock.closed)
        self.assertEqual(sock.target, (ADDRESS, 443))
        sent = b"".join(sock.sent)
        self.assertIn(b"Host: example.org\r\n", sent)
        self.assertNotIn(b"Cookie:", sent)
        self.assert_receipt(receipt)


if __name__ == "__main__":
    unittest.main()
