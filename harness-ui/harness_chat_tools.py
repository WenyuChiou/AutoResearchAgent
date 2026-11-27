"""Read-only Codex tool adapter over the Wiki's project store and registered materials.

Wiki V1 chat only reads. There is no tool here that registers a delivery, saves a
review, prepares a workflow, selects a candidate or starts research; a message can
therefore never stand in for those human decisions. Project identity comes from the
trusted project store (ref, project ID, integer input version, brief hash), never
from the browser.
"""

import hashlib
import json
from pathlib import Path

from harness_chat_stages import attach_stage_availability


TEXT_MATERIAL_LIMIT = 64 * 1024
TEXT_MATERIAL_EXTENSIONS = {".txt", ".md", ".json", ".jsonl", ".csv", ".tsv", ".bib"}
READ_ACTIONS = ("state", "materials", "read_material")
# What the page lists as "materials this stage will read once connected" (8.4).
EXPECTED_MATERIALS = {
    1: ("来源包", "原文定位"),
    2: ("候选", "已保存的真人选择"),
    3: ("所选方向的计划", "流程图", "对应评审"),
}
READABLE_TEXT = {
    None: "能读",
    "not-plain-text": "不能读：只能读登记过的纯文本",
    "too-large": "不能读：超过 64 KiB",
    "changed-since-registration": "不能读：文件变了，和登记时不一样",
    "file-missing": "不能读：文件找不到",
    "not-screened-or-verified": "不能读：还没有筛选或核验过",
    "stage-material-reader-unavailable": "不能读：这一段的材料还没接通",
}


def encoded(value):
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        allow_nan=False,
        separators=(",", ":"),
    ).encode()


def require(ok, reason):
    if not ok:
        raise ValueError(reason)


def project_binding(value):
    """The exact four-field identity a grant and a conversation are bound to."""
    require(
        isinstance(value, dict)
        and type(value.get("project_id")) is str
        and value["project_id"]
        and type(value.get("input_version")) is int
        and value["input_version"] > 0
        and isinstance(value.get("brief_sha256"), str)
        and len(value["brief_sha256"]) == 64,
        "chat-project-binding-unavailable",
    )
    return dict(
        project_ref=value["project_ref"],
        project_id=value["project_id"],
        input_version=value["input_version"],
        brief_sha256=value["brief_sha256"],
    )


class HarnessChatTools:
    def __init__(self, host, materials, stage_registry=None):
        self.host, self.materials = host, materials
        self.stage_registry = stage_registry

    def _readable(self, item, stage_connected):
        """Can the chat read this registered row? Answer with a stable reason code."""
        if item.get("status") != "registered":
            return "not-screened-or-verified"
        if item.get("kind") == "manual-stage2-packet":
            return None
        if (
            Path(str(item.get("name", ""))).suffix.lower()
            not in TEXT_MATERIAL_EXTENSIONS
            or item.get("kind") != "manual-file"
        ):
            return "not-plain-text"
        if type(item.get("bytes")) is not int or item["bytes"] > TEXT_MATERIAL_LIMIT:
            return "too-large"
        if item.get("stage", 0) >= 3 and not stage_connected:
            return "stage-material-reader-unavailable"
        path = Path(self.materials.root) / "files" / (str(item["id"]) + ".bin")
        try:
            data = path.read_bytes()
        except OSError:
            return "file-missing"
        if len(data) != item["bytes"] or hashlib.sha256(data).hexdigest() != item.get(
            "sha256"
        ):
            return "changed-since-registration"
        return None

    def context(self, project, stage):
        require(type(stage) is int and 1 <= stage <= 6, "chat-stage-not-supported")
        require(
            isinstance(project, str) and not project.startswith("view:"),
            "chat-project-unknown",
        )
        value = self.host.projects.read(self.host.credential, project)
        binding = project_binding(dict(value, project_ref=project))
        pin = hashlib.sha256(encoded(binding)).hexdigest()
        brief = value.get("brief")
        topic = brief.get("original_description") if isinstance(brief, dict) else None
        catalog = self.materials.catalog()
        items = [
            m
            for m in catalog["materials"]
            if m["project_ref"] == project and m["stage"] == stage
        ]
        context = dict(
            project_ref=project,
            stage=stage,
            mode="active-project",
            project_pin=pin,
            binding=binding,
            topic_summary=topic[:200] if isinstance(topic, str) else None,
            materials=[],
            expected_materials=[
                dict(category=name, status="reader-not-connected")
                for name in EXPECTED_MATERIALS.get(stage, ())
            ],
            supported_actions=list(READ_ACTIONS),
            unavailable=[
                "new-formal-human-record",
                "live-research-loop",
                "stage-research-execution",
                "register-delivery",
                "save-review",
                "prepare-workflow",
                "select-candidate",
            ],
            capabilities=dict(
                material_registration=False,
                local_review_notes=False,
                material_reading="registered-utf8-text-only"
                if stage != 2
                else "validated-stage2-packet",
                material_text_max_bytes=TEXT_MATERIAL_LIMIT,
                saved_stage_reading=False,
                offline_workflow_preparation=False,
                formal_selection=False,
                research_execution=False,
                stage_execution="planned-unconnected"
                if stage >= 3
                else "not-authorized",
            ),
        )
        attached = attach_stage_availability(context, self.stage_registry)
        connected = (
            attached["stage_availability"]["context_available"] if stage >= 3 else True
        )
        for item in items:
            code = self._readable(item, connected)
            attached["materials"].append(
                dict(
                    {
                        k: item.get(k)
                        for k in (
                            "id",
                            "name",
                            "sha256",
                            "packet_file_sha256",
                            "status",
                            "stage",
                            "kind",
                            "bytes",
                        )
                    },
                    version=item.get("sha256"),
                    origin="registered-file",
                    readable=dict(
                        ok=code is None, reason=code, text=READABLE_TEXT[code]
                    ),
                )
            )
        return attached

    @staticmethod
    def specs():
        return [
            dict(
                type="function",
                name="harness",
                description=(
                    "Read the current project and stage. state and materials list what is registered and whether each item is "
                    "readable; read_material returns one bounded registered UTF-8 text file or one validated Stage 2 packet. "
                    "Everything is read-only: nothing here selects a direction, approves a plan, registers or saves a record, or "
                    "starts research. Never invent IDs or evidence. Use state first to see the supported actions."
                ),
                inputSchema={
                    "type": "object",
                    "properties": {
                        "action": {"type": "string", "enum": list(READ_ACTIONS)},
                        "id": {
                            "type": "string",
                            "description": "Exact registered material ID returned by materials; empty if not needed.",
                        },
                        "note": {
                            "type": "string",
                            "description": "Always empty; this tool is read-only.",
                        },
                    },
                    "required": ["action", "id", "note"],
                    "additionalProperties": False,
                },
            )
        ]

    def validate(self, session, args):
        require(
            isinstance(args, dict) and set(args) == {"action", "id", "note"},
            "chat-tool-arguments-invalid",
        )
        require(
            all(isinstance(v, str) for v in args.values()), "chat-tool-strings-required"
        )
        require(
            not args["note"] and len(args["id"]) <= 200, "chat-tool-input-too-large"
        )
        require(args["action"] in READ_ACTIONS, "chat-tool-unknown")
        context = self.context(session["project_ref"], session["stage"])
        require(
            context["project_pin"] == session["project_pin"],
            "chat-input-version-differs",
        )
        require(
            args["action"] in context["supported_actions"],
            "chat-action-not-supported-for-stage",
        )
        return context

    @staticmethod
    def writes(_args):
        return False

    def proposal_pin(self, session, args):
        raise ValueError("chat-write-actions-not-offered")

    def call(self, session, args):
        context = self.validate(session, args)
        action, identity = args["action"], args["id"]
        if action in {"state", "materials"}:
            return dict(context, research_execution=False)
        material = next((m for m in context["materials"] if m["id"] == identity), None)
        require(material is not None, "chat-material-binding-differs")
        require(
            material["readable"]["ok"],
            "chat-material-not-readable:" + str(material["readable"]["reason"]),
        )
        if material.get("kind") == "manual-stage2-packet":
            require(session["stage"] == 2, "chat-action-not-supported-for-stage")
            view = self.materials.packet_view(identity)
            packet = json.loads(view["packet_text"])
            # Only bounded metadata and candidates go into the model; source originals stay on disk.
            return dict(
                material_id=identity,
                packet_sha256=view["packet_file_sha256"],
                brief=packet["brief"],
                candidates=packet["candidates"],
                evidence=packet["evidence"],
                sources=packet["sources"],
                formal_selection=view["formal_selection"],
                research_generated=False,
                stage1_lineage=view["stage1_lineage"],
            )
        if session["stage"] >= 3:
            require(
                self.stage_registry is not None,
                "chat-stage-material-reader-unavailable",
            )
            return self.stage_registry.read_material(
                session["project_ref"],
                session["stage"],
                session["project_pin"],
                identity,
            )
        from harness_chat_stage_materials import read_registered_text

        return read_registered_text(
            self.materials, identity, session["project_ref"], session["stage"]
        )
