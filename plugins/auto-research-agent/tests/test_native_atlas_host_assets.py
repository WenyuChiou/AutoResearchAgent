"""Real temporary HTTP/SQLite, injected channels; no native/model invocation."""

import http.client
import json
import unittest

from research_workspace_native.atlas_host import AtlasHost
from stage1_deliverable.common import sha
import test_native_message_host as host_fixture


class NativeAtlasHostAssetsTests(unittest.TestCase):
    def setUp(self):
        self.fixture = host_fixture.MessageHostTests("runTest")
        self.fixture.setUp()
        self.addCleanup(self.fixture.doCleanups)
        # Reuse already bounded real HTTP lifecycle and synthetic runtime fixture.
        self.explicit = self.fixture.start(atlas=True)
        self.p = self.fixture.p

    def start(self, *, native=True, **options):
        import threading

        if native:
            options.update(
                native_runtime=self.fixture.runtime, credential=self.fixture.token
            )
        server = AtlasHost(
            files=self.fixture.files, views=self.fixture.views, **options
        )
        worker = threading.Thread(target=server.serve_forever, daemon=True)
        worker.start()

        def stop():
            server.shutdown()
            server.server_close()
            worker.join(2)
            self.assertFalse(worker.is_alive())

        self.addCleanup(stop)
        return server

    def get(self, server, route):
        client = http.client.HTTPConnection(*server.server_address, timeout=2)
        try:
            client.request("GET", route)
            response = client.getresponse()
            return response.status, response.read()
        finally:
            client.close()

    def test_default_bound_overlay_order_hashes_and_zero_native_io(self):
        before = self.p.store.snapshot(self.p.pid)
        server = self.start()
        status, raw = self.get(server, "/views/case/atlas.html")
        self.assertEqual(status, 200)
        routes = [
            "/host-bootstrap/case.js",
            "/host-panel.js",
            "/session-panel.js",
            "/native-atlas-chat.js",
        ]
        positions = [raw.index(route.encode()) for route in routes]
        self.assertEqual(positions, sorted(positions))
        self.assertIn(b"/session-panel.css", raw)
        for route in ("/session-panel.css", *routes[1:]):
            status, data = self.get(server, route)
            self.assertEqual(status, 200)
            self.assertEqual(sha(data), server.host_binding["served_files"][route])
        status, binding = self.get(server, "/host-binding.json")
        self.assertEqual(status, 200)
        self.assertEqual(json.loads(binding), server.host_binding)
        self.assertFalse(server.host_binding["execution_authority"])
        self.assertEqual(self.p.channel.calls, [])
        self.assertEqual(self.p.store.snapshot(self.p.pid), before)
        self.assertEqual(self.fixture.runtime.stops, [])

    def test_unbound_case_bootstrap_disables_overlay_and_cannot_access_native(self):
        server = self.start()
        _, raw = self.get(server, "/host-bootstrap/unbound.js")
        native = json.loads(raw.decode().splitlines()[1].split("=", 1)[1][:-1])
        self.assertFalse(native["enabled"])
        self.assertIsNone(native["project_ref"])
        self.assertIsNone(native["input_version"])
        self.assertEqual(self.get(server, "/api/native/projects/unbound/offer")[0], 404)
        self.assertEqual(self.p.channel.calls, [])

    def test_explicit_script_keeps_legacy_asset_choice(self):
        self.assertEqual(
            self.get(self.explicit, "/native-atlas-chat.js"),
            (200, b"/* fixture-only; no model */"),
        )
        self.assertEqual(self.get(self.explicit, "/session-panel.js")[0], 404)
        self.assertEqual(self.get(self.explicit, "/session-panel.css")[0], 404)
        self.assertEqual(self.p.channel.calls, [])

    def test_default_no_runtime_has_no_control_assets_or_native_routes(self):
        server = self.start(native=False)
        _, page = self.get(server, "/views/case/atlas.html")
        self.assertNotIn(b"/session-panel.js", page)
        self.assertNotIn(b"/native-atlas-chat.js", page)
        for route in (
            "/session-panel.js",
            "/session-panel.css",
            "/native-atlas-chat.js",
        ):
            self.assertEqual(self.get(server, route)[0], 404)
        _, raw = self.get(server, "/host-bootstrap/case.js")
        native = json.loads(raw.decode().splitlines()[1].split("=", 1)[1][:-1])
        self.assertFalse(native["enabled"])
        self.assertEqual(self.get(server, "/api/native/projects/" + self.p.ref)[0], 404)
        self.assertEqual(self.p.channel.calls, [])


if __name__ == "__main__":
    unittest.main()
