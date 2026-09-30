"""One outside controller owns ordered admission and verifies guest transfers."""

import json
from pathlib import Path
import secrets

from . import runner, sequence
from .vm_common import (
    VERSION,
    authenticated,
    binding,
    digest,
    receive_capture,
    require,
    secret,
    sign,
)
from .vm_guest import verify_capture_binding


def _load(plan_path):
    plan = runner.read_json(plan_path)
    require(
        set(plan) == {"kind", "lock", "slots", "registry_root"}
        and plan["kind"] == "Stage1GuestControllerPlan.v2",
        "controller plan fields differ",
    )
    lock = runner.read_json(plan["lock"])
    require(
        lock.get("guest_adapter") == binding(),
        "controller adapter differs from frozen bytes",
    )
    runs = sequence.expected_runs(lock)
    require(len(plan["slots"]) == len(runs), "missing guest slots")
    for slot, run in zip(plan["slots"], runs):
        require(
            set(slot) == {"identity", "secret_file", "transport"}, "slot fields differ"
        )
        identity = slot["identity"]
        require(
            set(identity)
            == {
                "guest_id",
                "protected_runtime",
                "config_sha256",
                "instance_sha256",
                "machine_id_sha256",
                "lock_sha256",
                "repeat",
                "condition",
                "run_id",
                "subject_id",
            },
            "guest identity fields differ",
        )
        require(
            all(identity[k] == v for k, v in run.items())
            and identity["lock_sha256"] == runner.sha(Path(plan["lock"]).read_bytes()),
            "guest slot order/lock differs",
        )
    for key in ("guest_id", "instance_sha256", "config_sha256"):
        require(
            len({s["identity"][key] for s in plan["slots"]}) == len(runs),
            "fresh guests require unique " + key,
        )
    require(
        len({runner.sha(secret(s["secret_file"])) for s in plan["slots"]}) == len(runs),
        "each guest requires a separate admission key",
    )
    root = Path(plan["registry_root"]).resolve()
    require(
        not (root / ".git").exists()
        and not any((p / ".git").exists() for p in root.parents),
        "controller registry must be outside Git",
    )
    return plan, lock, root


def _request(slot, action, series_id, probe_sha):
    return {
        "version": VERSION,
        "action": action,
        "identity": slot["identity"],
        "nonce": secrets.token_hex(32),
        "series_id": series_id,
        "preflight_sha256": probe_sha,
    }


def _exchange(slot, request, transport, evidence):
    key = secret(slot["secret_file"])
    envelope = sign(request, key)
    runner.write_json(Path(str(evidence) + ".request.json"), envelope)
    try:
        response = transport(slot["transport"], envelope)
    except Exception as error:
        runner.write_json(
            Path(str(evidence) + ".failure.json"),
            {
                "error_type": type(error).__name__,
                "error": str(error),
                "transport": getattr(error, "diagnostic", None),
                "reservation_retained": True,
            },
        )
        raise
    runner.write_json(Path(str(evidence) + ".response.json"), response)
    body = authenticated(response, key)
    require(
        set(body)
        == {
            "version",
            "request_sha256",
            "identity",
            "preflight",
            "preflight_sha256",
            "preflight_utf8",
            "files",
        },
        "unexpected guest response fields",
    )
    require(
        body["version"] == VERSION
        and body["request_sha256"] == digest(request)
        and body["identity"] == slot["identity"],
        "stale response or wrong guest",
    )
    raw = body["preflight_utf8"].encode("utf-8")
    require(
        body["preflight_sha256"] == runner.sha(raw)
        and json.loads(raw) == body["preflight"],
        "guest preflight bytes differ",
    )
    require(
        body["preflight"]["guest_binding"] == slot["identity"],
        "guest preflight identity differs",
    )
    return body


def prepare(plan_path, transport):
    plan, lock, root = _load(plan_path)
    # Lock bytes key the registry: changing the plan filename cannot create another series.
    root.mkdir(parents=True, exist_ok=True)
    state_path = root / (runner.sha(Path(plan["lock"]).read_bytes()) + ".json")
    anchor = sequence.REGISTRY_HOME / (state_path.stem + ".guest-controller.json")
    anchor.parent.mkdir(parents=True, exist_ok=True)
    try:
        with anchor.open("x", encoding="utf-8") as stream:
            json.dump(
                {
                    "registry": str(state_path),
                    "plan_sha256": runner.sha(Path(plan_path).read_bytes()),
                },
                stream,
            )
    except FileExistsError as error:
        raise runner.ExecutionBlocked("controller series already exists") from error
    with sequence.exclusive(state_path):
        require(not state_path.exists(), "controller series already exists")
        state = {
            "kind": "Stage1GuestControllerRegistry.v2",
            "plan_sha256": runner.sha(Path(plan_path).read_bytes()),
            "series_id": secrets.token_hex(32),
            "next_index": 0,
            "active": None,
            "probes": [],
            "completed": [],
            "exchanges": 0,
            "status": "preparing",
        }
        runner.write_json(state_path, state)
        reference = None
        for index, slot in enumerate(plan["slots"]):
            request = _request(slot, "probe", state["series_id"], None)
            body = _exchange(
                slot, request, transport, root / (state_path.stem + f".probe-{index}")
            )
            require(
                body["files"] is None, "probe response must not contain capture files"
            )
            preflight = body["preflight"]
            verify_capture_binding(
                {**slot["identity"], "guest_binding": slot["identity"]}, lock, preflight
            )
            probe = preflight["binding"]["probes"][slot["identity"]["condition"]]
            common = {
                k: probe[k]
                for k in (
                    "codex_version",
                    "model",
                    "reasoning",
                    "native_web_search",
                    "native_capabilities",
                    "native_config_sha256",
                )
            }
            require(
                reference is None or common == reference,
                "native parity differs across guests",
            )
            reference = common
            require(
                probe["codex_version"] == lock["runtime"]["app_version"]
                and probe["model"] == lock["runtime"]["model_id"]
                and probe["reasoning"] == lock["runtime"]["reasoning"]
                and probe["native_capabilities_sha256"]
                == lock["runtime"]["tool_profile_sha256"],
                "guest runtime differs from lock",
            )
            require(
                preflight["plugin_tree_sha256"] == lock["plugin_tree_sha256"]
                and preflight["binding"]["treatment_runtime_pin"]["sha256"]
                == runner._repeat_pin_sha(lock, slot["identity"]["repeat"]),
                "guest plugin/runtime pin differs",
            )
            if slot["identity"]["condition"] == "baseline":
                require(not probe["plugin_names"], "baseline contains plugin")
            else:
                require(
                    probe["plugin_names"] == ["auto-research-agent"]
                    and probe["installed_plugin_sha256"] == lock["plugin_tree_sha256"],
                    "treatment inventory differs",
                )
            state["probes"].append(
                {"sha256": body["preflight_sha256"], "preflight": preflight}
            )
            sequence.save(state_path, state)
        state["status"] = "ready"
        sequence.save(state_path, state)
    return state_path


def advance(plan_path, transport, *, action="capture"):
    require(action in {"capture", "resume", "fetch"}, "invalid controller action")
    plan, lock, root = _load(plan_path)
    state_path = root / (runner.sha(Path(plan["lock"]).read_bytes()) + ".json")
    anchor = runner.read_json(
        sequence.REGISTRY_HOME / (state_path.stem + ".guest-controller.json")
    )
    require(
        anchor
        == {
            "registry": str(state_path),
            "plan_sha256": runner.sha(Path(plan_path).read_bytes()),
        },
        "controller anchor differs",
    )
    with sequence.exclusive(state_path):
        state = runner.read_json(state_path)
        require(
            state["plan_sha256"] == runner.sha(Path(plan_path).read_bytes())
            and state["status"] == "ready",
            "controller plan changed or preparation incomplete",
        )
        require(
            len(state["completed"]) == state["next_index"], "controller index differs"
        )
        for index, prior in enumerate(state["completed"]):
            record = runner.verify_capture(prior["output"], verify_runtime=False)
            require(
                runner.sha((Path(prior["output"]) / "run.json").read_bytes())
                == prior["run_sha256"]
                and record["status"] == "complete"
                and record["series_id"] == state["series_id"]
                and record["guest_binding"] == plan["slots"][index]["identity"],
                "prior guest capture changed",
            )
        index = state["next_index"]
        require(index < len(plan["slots"]), "all guest slots already completed")
        slot = plan["slots"][index]
        if action == "capture":
            require(
                state["active"] is None,
                "active guest requires explicit fetch or inspected resume",
            )
            state["active"] = {"index": index, "identity": slot["identity"]}
        else:
            require(
                state["active"] == {"index": index, "identity": slot["identity"]},
                "no matching active guest",
            )
        ordinal = state["exchanges"]
        state["exchanges"] += 1
        sequence.save(
            state_path, state
        )  # Reservation survives subprocess failure/lost response.
        request = _request(
            slot, action, state["series_id"], state["probes"][index]["sha256"]
        )
        body = _exchange(
            slot, request, transport, root / (state_path.stem + f".exchange-{ordinal}")
        )
        require(
            body["preflight_sha256"] == state["probes"][index]["sha256"],
            "capture used stale probe",
        )
        output = root / (state_path.stem + f".capture-{index}-{ordinal}")
        record = receive_capture(body["files"], output)
        require(
            record["guest_binding"] == slot["identity"]
            and record["series_id"] == state["series_id"],
            "capture belongs to another guest/series",
        )
        if record["status"] == "complete":
            state["completed"].append(
                {
                    "output": str(output),
                    "run_sha256": runner.sha((output / "run.json").read_bytes()),
                }
            )
            state["next_index"] += 1
            state["active"] = None
        sequence.save(state_path, state)
        return record
