"""Replay an accepted evaluator archive while denying processes and networking."""

import json
import sys

blocked = []


def guard(event, args):
    if event in {
        "subprocess.Popen",
        "os.system",
        "os.posix_spawn",
        "socket.connect",
        "socket.getaddrinfo",
        "socket.sendto",
    }:
        blocked.append(event)
        raise RuntimeError("Offline replay forbids external action: " + event)


sys.addaudithook(guard)
from stage1_eval.__main__ import main  # noqa: E402

code = main(sys.argv[1:])
print(
    json.dumps(
        {
            "offline_guard": True,
            "blocked_actions": blocked,
            "new_model_calls": 0,
            "exit_code": code,
        }
    )
)
raise SystemExit(code if not blocked else 2)
