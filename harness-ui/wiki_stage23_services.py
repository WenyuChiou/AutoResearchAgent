"""Compose the existing pinned Stage 2 and Stage 3 services into Wiki Host."""


def validate_args(args):
    for stem in ("stage2_controller_profile", "stage3_planning_profile"):
        if bool(getattr(args, stem, None)) != bool(
            getattr(args, stem + "_sha256", None)
        ):
            raise ValueError(stem + " requires its external SHA256")
    for stem in (
        "stage2_direct_import",
        "stage2_controller",
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
        stage2_controllers=None,
        stage2_controller_profile=None,
        stage2_selection=None,
        stage3_planning=None,
        stage3_planning_profile=None,
        stage3_recovery_pins=None,
        stage2_readings=None,
        planning_resources=None,
    )
    if getattr(args, "stage2_controller_profile", None):
        from research_workspace_native.project_stage2_controller_config import (
            Stage2ControllerProfile,
        )

        services["stage2_controller_profile"] = Stage2ControllerProfile(
            args.stage2_controller_profile, args.stage2_controller_profile_sha256
        )
    if getattr(args, "stage2_controller_config", None):
        from research_workspace_native.project_stage2_controller_config import (
            load_stage2_controllers,
        )

        services["stage2_controllers"] = load_stage2_controllers(
            stage2,
            token,
            args.stage2_controller_config,
            args.stage2_controller_sha256,
            allow_readback_without_admission=True,
        )
    bindings = {}
    if getattr(args, "stage2_direct_import_config", None):
        from research_workspace_native.project_stage2_direct_config import (
            load_direct_request_imports,
        )

        reuse = (
            {"existing_only": True}
            if getattr(args, "existing_stage23_store", False)
            else {}
        )
        bindings = load_direct_request_imports(
            stage2,
            token,
            args.stage2_direct_import_config,
            args.stage2_direct_import_sha256,
            **reuse,
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
    from research_workspace_native.project_stage_connections import (
        ConnectionStore,
        BindingTable,
    )
    from research_workspace_native.project_stage2_selection import (
        ProjectStage2SelectionService,
    )

    services["stage2_selection"] = ProjectStage2SelectionService(
        projects,
        BindingTable(
            bindings, ConnectionStore(projects, token), services["stage2_controllers"]
        ),
    )
    stage2.receive_current = True
    if getattr(args, "stage2_reading_config", None):
        from research_workspace_native.project_stage2_reading import (
            Stage2ReadingRegistry,
        )

        services["stage2_readings"] = Stage2ReadingRegistry(
            args.stage2_reading_config, args.stage2_reading_sha256
        )
    if getattr(args, "stage3_planning_profile", None):
        from research_workspace_native.project_stage3_planning_config import (
            Stage3PlanningProfile,
        )

        services["stage3_planning_profile"] = Stage3PlanningProfile(
            args.stage3_planning_profile, args.stage3_planning_profile_sha256
        )
    profile = services["stage3_planning_profile"]
    if getattr(args, "stage3_planning_config", None) or profile is not None:
        from research_workspace_native.project_stage3_planning_config import (
            Stage3PlanningHostResources,
            load_stage3_planning_configuration,
            validate_profile_journal,
        )

        config = (
            load_stage3_planning_configuration(
                projects,
                token,
                args.stage3_planning_config,
                args.stage3_planning_sha256,
            )
            if getattr(args, "stage3_planning_config", None)
            else None
        )
        validate_profile_journal(profile, config)
        resources = Stage3PlanningHostResources(
            projects,
            token,
            services["stage2_selection"],
            config,
            **({"profile": profile} if profile is not None else {}),
        )
        services.update(
            planning_resources=resources,
            stage3_planning=resources.service,
            stage3_recovery_pins=resources.recovery_pins,
        )
