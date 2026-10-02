"""Run an experimental authenticated API, without automatically starting research."""

import argparse
import os
import re
import signal

from .runtime import Engine
from .server import make_server
from .store import Store, StudioError, safe_path


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ("data-root", "codex", "codex-home", "expected-harness-sha"):
        parser.add_argument("--" + name, required=True)
    parser.add_argument("--origin", action="append", required=True)
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--model")
    parser.add_argument("--reasoning", default="high")
    parser.add_argument(
        "--acknowledge-interrupted",
        action="store_true",
        help="attest all previous worker processes are dead; retain interrupted history",
    )
    args = parser.parse_args()
    if not re.fullmatch("[0-9a-f]{40}", args.expected_harness_sha):
        parser.error("expected-harness-sha must be a full immutable Git revision")
    store = Store(args.data_root)
    token = os.environ.pop("ARA_STUDIO_TOKEN", "")
    if args.acknowledge_interrupted:
        safe_path(store.root, "reconciliation-required").unlink(missing_ok=True)
        store.event(
            "operator", "reconciliation", "operator attested previous workers are dead"
        )
    engine = Engine(
        store,
        args.codex,
        args.codex_home,
        args.expected_harness_sha,
        token,
        model=args.model,
        reasoning=args.reasoning,
    )
    server = make_server(engine, token, set(args.origin), (args.host, args.port))

    def terminate(_signum, _frame):
        raise KeyboardInterrupt()

    signal.signal(signal.SIGTERM, terminate)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        if engine.active:
            engine.stop(engine.active)
            engine.thread.join(timeout=20)
        server.server_close()
        store.close()


if __name__ == "__main__":
    try:
        main()
    except (StudioError, OSError) as error:
        raise SystemExit(str(error)) from error
