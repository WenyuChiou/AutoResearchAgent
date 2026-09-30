"""Trusted helper executed as the subject UID before touching subject-controlled bytes."""

import base64
import json
import os
from pathlib import Path
import subprocess
import sys


def call(username, operation, **arguments):
    from .vm_guest import native_options

    options, environment = native_options(username)
    if operation == "workspace_env":
        import inspect
        from . import runner

        arguments["function_source"] = inspect.getsource(
            runner._research_hub_workspace_env
        )
    result = subprocess.run(
        [sys.executable, "-I", "-B", "-c", Path(__file__).read_text(encoding="utf-8")],
        input=json.dumps({"operation": operation, **arguments}),
        text=True,
        capture_output=True,
        check=True,
        env=dict(os.environ, **environment),
        **options,
    )
    return json.loads(result.stdout)


def collect(workspace):
    root = Path(workspace)
    files, errors = {}, []
    for path in sorted(root.rglob("*")):
        name = path.relative_to(root).as_posix()
        try:
            if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
                raise OSError("symlink or escaped path")
            if path.is_file():
                before = path.stat()
                raw = path.read_bytes()
                after = path.stat()
                if (before.st_size, before.st_mtime_ns) != (
                    after.st_size,
                    after.st_mtime_ns,
                ):
                    raise OSError("file changed during observation")
                files[name] = base64.b64encode(raw).decode("ascii")
        except OSError as error:
            errors.append({"path": name, "error": str(error)})
    return {"files": files, "errors": errors}


def dispatch(request):
    operation = request.pop("operation")
    if operation == "snapshot":
        return collect(request["workspace"])
    if operation == "empty_directory":
        path = Path(request["path"])
        if path.is_symlink() or (path.exists() and not path.is_dir()):
            raise ValueError("skill probe workspace is not a normal directory")
        path.mkdir(exist_ok=True)
        if any(path.iterdir()):
            raise ValueError("skill probe workspace is not empty")
        return str(path)
    if operation == "read":
        path = Path(request["path"])
        if not path.exists():
            return None
        if path.is_symlink() or not path.is_file():
            raise ValueError("subject source is not a regular file")
        return base64.b64encode(path.read_bytes()).decode("ascii")
    if operation == "workspace_env":
        scope = {"Path": Path, "json": json, "ExecutionBlocked": ValueError}
        exec(request["function_source"], scope)
        return scope["_research_hub_workspace_env"](
            Path(request["workspace"]), request["resume"]
        )
    raise ValueError("unsupported subject helper operation")


if __name__ == "__main__":
    print(json.dumps(dispatch(json.load(sys.stdin))))
