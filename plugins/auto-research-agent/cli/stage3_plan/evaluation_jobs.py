"""Single-role Stage3 evaluation jobs; the host supplies the evaluator adapter."""

import copy
import hashlib
import importlib
from pathlib import Path
import subprocess

from .contracts import Stage3Error, digest
from .evaluation import (
    inspect_evaluation_record,
    inspect_evaluation_request,
    record_evaluation,
)
from .jobs import POLICY, PlanningJobs, _ref
from .preparation import closed, file_binding
from .storage import MAX_ARTIFACT_BYTES, read_bytes, write_new


def _campaign_api():
    try:
        campaign = importlib.import_module(".campaign", __package__)
        records = importlib.import_module(".campaign_records", __package__)
    except ModuleNotFoundError as error:
        if error.name not in {
            __package__ + ".campaign",
            __package__ + ".campaign_records",
        }:
            raise
        raise Stage3Error(
            "pinned campaign dependency is not installed; no dispatch"
        ) from error
    return campaign.inspect_campaign, records.inspect_receipt, records.record_campaign


class EvaluationJobs(PlanningJobs):
    """Reuse the planning job's journal lifecycle, with existing P7-P9 record APIs."""

    method = "stage3/evaluation"
    kind = "Stage3EvaluationJob"
    namespace = "stage3-evaluation-"

    def __init__(self, *args, request, role, campaign=None):
        super().__init__(*args)
        closed(request, {"path", "sha256"}, "evaluation request binding")
        if role not in {"R1", "R2", "ADJ"}:
            raise Stage3Error("explicit existing evaluator role required")
        self.request, self.role = copy.deepcopy(request), role
        self.campaign = copy.deepcopy(campaign)
        if campaign is not None:
            closed(campaign, {"root", "sha256", "unit_id"}, "campaign job binding")

    def _campaign(self, payload):
        inspect_campaign, inspect_receipt, record_campaign = _campaign_api()
        ref = payload["campaign"]
        manifest = inspect_campaign(ref["root"], expected_sha256=ref["sha256"])[
            "manifest"
        ]
        units = [u for u in manifest["units"] if u["unit_id"] == ref["unit_id"]]
        if (
            len(units) != 1
            or units[0]["role"] != payload["role"]
            or (digest(units[0]["request"]) != digest(payload["evaluation_request"]))
        ):
            raise Stage3Error("campaign unit/role/request differs from the job")
        return manifest, units[0], inspect_receipt, record_campaign

    def _payload(self, *args, **kwargs):
        value = super()._payload(*args, **kwargs)
        request = inspect_evaluation_request(
            self.request["path"], expected_sha256=self.request["sha256"]
        )
        checkpoint = file_binding(
            value["checkpoint"]["path"], value["checkpoint"]["sha256"]
        )
        plan_ref = {
            "package": request["source"]["package"],
            "manifest_sha256": request["source"]["manifest_sha256"],
        }
        if (
            digest(checkpoint["bindings"]["plan"]) != digest(plan_ref)
            or request["bindings"]["intake_sha256"] != value["intake_sha256"]
        ):
            raise Stage3Error(
                "evaluation request is not the current workflow saved plan"
            )
        value.update(
            evaluation_request=self.request, role=self.role, campaign=self.campaign
        )
        if self.campaign is not None:
            self._campaign(value)
        return copy.deepcopy(value)

    def prepare(
        self, key, *, checkpoint, configuration, adapter_context, expected_revision
    ):
        request = inspect_evaluation_request(
            self.request["path"], expected_sha256=self.request["sha256"]
        )
        binding = request["bindings"]
        return super().prepare(
            key,
            checkpoint=checkpoint,
            configuration=configuration,
            adapter_context=adapter_context,
            expected_revision=expected_revision,
            plan_id=binding["plan_id"],
            version=binding["plan_version"],
            schema_version=binding["plan_schema_version"],
        )

    def _blob(self, root, name, raw):
        if isinstance(raw, str):
            raw = raw.encode("utf-8")
        if not isinstance(raw, bytes):
            raise Stage3Error(
                "adapter capture must provide bytes/text or explicit null"
            )
        ref = {
            "size": len(raw),
            "sha256": hashlib.sha256(raw).hexdigest(),
            "retained": len(raw) <= MAX_ARTIFACT_BYTES,
        }
        if ref["retained"]:
            path = root / name
            write_new(path, raw, raw=True)
            ref["path"] = str(path)
        return ref

    def _capture(self, payload, response):
        if not isinstance(response, dict) or not {"raw_response", "provenance"} <= set(
            response
        ):
            raise Stage3Error(
                "evaluator adapter must return raw_response and provenance"
            )
        if set(response) - {
            "raw_response",
            "provenance",
            "stdout",
            "stderr",
            "returncode",
        }:
            raise Stage3Error("unsupported evaluator adapter output fields")
        code = response.get("returncode")
        if code is not None and type(code) is not int:
            raise Stage3Error("actual exit code must be an exact integer or null")
        root = Path(payload["output"])
        capture = {
            "raw": self._blob(root, "judgment.raw", response["raw_response"]),
            "provenance": response["provenance"],
            "returncode": code,
        }
        for name in ("stdout", "stderr"):
            capture[name] = (
                self._blob(root, name + ".raw", response[name])
                if (response.get(name) is not None)
                else None
            )
        write_new(root / "adapter-result.json", capture)
        if any(
            blob is not None and not blob["retained"]
            for blob in (capture["raw"], capture["stdout"], capture["stderr"])
        ):
            raise Stage3Error(
                "oversized evaluator capture: size/hash retained, bytes unavailable"
            )
        if code is not None and code != 0:
            raise subprocess.CalledProcessError(code, "host-evaluator-adapter")
        return capture

    def _capture_value(self, payload):
        root = Path(payload["output"])
        ref = _ref(root / "adapter-result.json")
        value = file_binding(ref["path"], ref["sha256"])
        for field in ("raw", "stdout", "stderr"):
            blob = value[field]
            if blob and blob["retained"]:
                name = "judgment.raw" if field == "raw" else field + ".raw"
                if Path(blob["path"]) != root / name:
                    raise Stage3Error("evaluator capture escapes its job")
                raw = read_bytes(blob["path"])
                if (
                    len(raw) != blob["size"]
                    or hashlib.sha256(raw).hexdigest() != blob["sha256"]
                ):
                    raise Stage3Error("evaluator capture bytes changed")
        return ref, value

    def _perform(self, payload, callback):
        request = inspect_evaluation_request(
            self.request["path"], expected_sha256=self.request["sha256"]
        )
        view = request["assessor_view"]
        if payload["campaign"] is not None:
            _, unit, _, _ = self._campaign(payload)
            from .storage import read_json

            view = read_json(
                Path(payload["campaign"]["root"]) / (unit["subject_id"] + ".json")
            )
        response = callback(
            view=copy.deepcopy(view),
            role=payload["role"],
            configuration=copy.deepcopy(payload["configuration"]),
            timeout_seconds=payload["adapter_context"]["timeout_seconds"],
            output_dir=Path(payload["output"]),
        )
        capture = self._capture(payload, response)
        raw_ref = {"path": capture["raw"]["path"], "sha256": capture["raw"]["sha256"]}
        root = Path(payload["output"])
        if payload["campaign"] is not None:
            _, _, _, record_campaign = self._campaign(payload)
            result = record_campaign(
                payload["campaign"]["root"],
                expected_sha256=payload["campaign"]["sha256"],
                unit_id=payload["campaign"]["unit_id"],
                judgment=raw_ref["path"],
                expected_judgment_sha256=raw_ref["sha256"],
                output=root / "unit",
            )
            pin = result["receipt_binding"]["sha256"]
        else:
            record_evaluation(
                self.request["path"],
                expected_request_sha256=self.request["sha256"],
                judgment=raw_ref["path"],
                expected_judgment_sha256=raw_ref["sha256"],
                output=root / "record.json",
            )
            pin = _ref(root / "record.json")["sha256"]
        return self._saved(payload, pin)

    def _saved(self, payload, pin, *, attach=False):
        capture_ref, capture = self._capture_value(payload)
        if capture["returncode"] not in (None, 0) or not capture["raw"]["retained"]:
            raise Stage3Error(
                "failed or partial capture cannot complete an evaluation job"
            )
        root = Path(payload["output"])
        raw_ref = {"path": capture["raw"]["path"], "sha256": capture["raw"]["sha256"]}
        receipt_ref = None
        if payload["campaign"] is not None:
            manifest, _, inspect_receipt, _ = self._campaign(payload)
            receipt_ref = {"path": str(root / "unit/receipt.json"), "sha256": pin}
            receipt, record = inspect_receipt(
                receipt_ref, manifest, payload["campaign"]["sha256"]
            )
            if receipt["status"] != "recorded" or digest(
                receipt["raw"]["sha256"]
            ) != digest(raw_ref["sha256"]):
                raise Stage3Error(
                    "campaign receipt is failed or differs from job capture"
                )
            record_ref = receipt["record"]
        else:
            record_ref = {"path": str(root / "record.json"), "sha256": pin}
            record = inspect_evaluation_record(
                record_ref["path"],
                expected_sha256=pin,
                request=payload["evaluation_request"],
                judgment=raw_ref,
            )
        if record["record_status"] != "recorded":
            raise Stage3Error("failed evaluation record cannot complete a saved job")
        return {
            "outcome": "saved",
            "record": record_ref,
            "campaign_receipt": receipt_ref,
            "capture": capture_ref,
            "role": payload["role"],
            "score_vector": record["score_vector"],
            "reviewer_identity": "unverified",
            "policy": dict(POLICY),
        }

    def _result_pin(self, evidence):
        return (evidence["campaign_receipt"] or evidence["record"])["sha256"]

    def _known_failure(self, payload):
        return (Path(payload["output"]) / "adapter-result.json").is_file()

    def _failure_artifacts(self, payload):
        root = Path(payload["output"])
        return {
            name: _ref(root / name)
            for name in (
                "adapter-result.json",
                "judgment.raw",
                "record.json",
                "unit/receipt.json",
            )
            if (root / name).is_file()
        }

    def _verify_failure(self, ref):
        super()._verify_failure(ref)
        value = file_binding(ref["path"], ref["sha256"])
        capture = value.get("artifacts", {}).get("adapter-result.json")
        if capture:
            self._capture_value({"output": str(Path(ref["path"]).parent)})
        artifacts = value.get("artifacts", {})
        if "record.json" in artifacts:
            record = artifacts["record.json"]
            inspect_evaluation_record(
                record["path"],
                expected_sha256=record["sha256"],
                request=self.request,
                judgment=artifacts["judgment.raw"],
            )
        if "unit/receipt.json" in artifacts:
            manifest, _, inspect_receipt, _ = self._campaign(
                {
                    "campaign": self.campaign,
                    "role": self.role,
                    "evaluation_request": self.request,
                }
            )
            inspect_receipt(
                artifacts["unit/receipt.json"], manifest, self.campaign["sha256"]
            )

    def recover(
        self,
        key,
        *,
        expected_request_sha256,
        current_checkpoint,
        expected_record_sha256,
    ):
        return super().recover(
            key,
            expected_request_sha256=expected_request_sha256,
            current_checkpoint=current_checkpoint,
            expected_plan_manifest_sha256=expected_record_sha256,
        )


def save_campaign_index(
    root, *, expected_campaign_sha256, receipts, output, human_interventions=None
):
    """Bind actual saved receipts to the existing index; never invent scores or audit."""
    _campaign_api()
    try:
        summarize = importlib.import_module(
            ".campaign_summary", __package__
        ).summarize_campaign
    except ModuleNotFoundError as error:
        raise Stage3Error(
            "pinned campaign summary dependency is not installed"
        ) from error
    from .storage import private_output

    target = private_output(output)
    write_new(
        target,
        {
            "kind": "Stage3CampaignIndex",
            "schema_version": "1.0.0",
            "campaign_sha256": expected_campaign_sha256,
            "receipts": receipts,
            "human_interventions": human_interventions,
        },
    )
    ref = _ref(target)
    summarize(
        root,
        expected_sha256=expected_campaign_sha256,
        index=target,
        expected_index_sha256=ref["sha256"],
    )
    return ref
