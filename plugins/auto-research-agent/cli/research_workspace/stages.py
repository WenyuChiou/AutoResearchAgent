"""Standalone presentation registry; the strict StageRun schema is unchanged."""


def stage_registry():
    definitions = [
        (
            1,
            "Literature and Evidence",
            "Find and preserve source-bound literature.",
            ["Confirmed research brief", "Search intake", "Resources"],
            ["Literature package", "Claims", "Search and coverage records"],
            "stage1_deliverable.records.validate_records",
            "research_workspace.projection.project_package",
            "read-only-adapter",
        ),
        (
            2,
            "Comparison and Gap",
            "Compare evidence and retain unresolved research opportunities.",
            ["Accepted Stage 1 input route", "Confirmed brief", "Resources"],
            [
                "Comparison",
                "Candidates",
                "Independent assessment",
                "User direction decision",
            ],
            "stage2_common.validate_packet",
            "stage2_workflow.import_stage1.build_stage2_seed",
            "core-available-not-connected",
        ),
        (
            3,
            "Design and Feasibility",
            "Turn a reviewed direction into a bounded research design.",
            ["Reviewed comparison", "Explicit direction choice"],
            ["Design", "Feasibility checks", "Experiment plan"],
            None,
            None,
            "reserved",
        ),
        (
            4,
            "Experiment Execution",
            "Execute the approved design and retain raw outcomes and failures.",
            ["Approved design", "Experiment plan", "Execution authority"],
            ["Execution records", "Raw results", "Failures"],
            None,
            None,
            "reserved",
        ),
        (
            5,
            "Analysis and Figures",
            "Analyze validated outcomes with uncertainty and provenance.",
            ["Validated execution records", "Raw results"],
            ["Analysis", "Figures", "Uncertainty records"],
            None,
            None,
            "reserved",
        ),
        (
            6,
            "Writing and Submission",
            "Write from reviewed evidence and preserve publication decisions.",
            ["Reviewed evidence", "Analysis", "Figures"],
            ["Manuscript", "Submission artifacts"],
            None,
            None,
            "reserved",
        ),
    ]
    return [
        {
            "stage": number,
            "label": label,
            "purpose": purpose,
            "required_inputs": inputs,
            "expected_deliverables": outputs,
            "validator": validator,
            "adapter": adapter,
            "support_status": support,
            "node_flow": [
                "plan",
                "execute",
                "extract",
                "validate",
                "gate",
                "checkpoint",
            ],
            "execution_enabled": False,
            "allowed_execution_actions": [],
        }
        for number, label, purpose, inputs, outputs, validator, adapter, support in definitions
    ]
