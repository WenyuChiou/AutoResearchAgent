"""Compose the existing pinned Stage 2 and Stage 3 services into Wiki Host."""


def validate_args(args):
    for stem in (
        "stage2_direct_import",
        "selection",
        "stage3_planning",
        "stage2_reading",
    ):
        if bool(getattr(args, stem + "_config", None)) != bool(
            getattr(args, stem + "_sha256", None)
        ):
            raise ValueError(stem + " requires its external configuration SHA256")
    if getattr(args, "stage3_planning_config", None) and not (
        getattr(args, "stage2_direct_import_config", None)
        or getattr(args, "selection_config", None)
    ):
        raise ValueError("Stage3 planning requires configured Stage2 selection")


def configure_services(services, args):
    validate_args(args)
    projects, token, stage2 = (
        services["projects"],
        services["credential"],
        services["stage2"],
    )
    services.update(
        stage2_selection=None,
        stage3_planning=None,
        stage3_recovery_pins=None,
        stage2_readings=None,
        planning_resources=None,
    )
    bindings = {}
    if getattr(args, "stage2_direct_import_config", None):
        from research_workspace_native.project_stage2_direct_config import (
            load_direct_request_imports,
        )

        bindings = load_direct_request_imports(
            stage2,
            token,
            args.stage2_direct_import_config,
            args.stage2_direct_import_sha256,
        )
    if getattr(args, "selection_config", None):
        from research_workspace_native.project_host import _decode, sha

        path = args.selection_config
        raw = path.read_bytes()
        if path.is_symlink() or sha(raw) != args.selection_sha256:
            raise ValueError("selection configuration receipt differs")
        config = _decode(raw.decode("utf-8"))
        if (
            not isinstance(config, dict)
            or set(config) != {"schema_version", "bindings"}
            or config["schema_version"] != "1.0.0"
        ):
            raise ValueError("selection configuration shape differs")
        if not isinstance(config["bindings"], dict) or set(bindings) & set(
            config["bindings"]
        ):
            raise ValueError("selection bindings overlap or have invalid shape")
        bindings.update(config["bindings"])
    if getattr(args, "selection_config", None) or getattr(
        args, "stage2_direct_import_config", None
    ):
        from research_workspace_native.project_stage2_selection import (
            ProjectStage2SelectionService,
        )

        services["stage2_selection"] = ProjectStage2SelectionService(projects, bindings)
    if getattr(args, "stage2_reading_config", None):
        from research_workspace_native.project_stage2_reading import (
            Stage2ReadingRegistry,
        )

        services["stage2_readings"] = Stage2ReadingRegistry(
            args.stage2_reading_config, args.stage2_reading_sha256
        )
    if getattr(args, "stage3_planning_config", None):
        from research_workspace_native.project_stage3_planning_config import (
            Stage3PlanningHostResources,
            load_stage3_planning_configuration,
        )

        config = load_stage3_planning_configuration(
            projects, token, args.stage3_planning_config, args.stage3_planning_sha256
        )
        resources = Stage3PlanningHostResources(
            projects, token, services["stage2_selection"], config
        )
        services.update(
            planning_resources=resources,
            stage3_planning=resources.service,
            stage3_recovery_pins=resources.recovery_pins,
        )
