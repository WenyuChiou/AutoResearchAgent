"""Universal project intake over the existing authenticated, bounded Atlas host.

Topic entry, confirmation and compilation are real Harness operations. Optional
model/Stage2 services are trusted objects; browser JSON cannot construct them.
This module alone supplies no native, search or source-import authority.
"""

import argparse
import json
from pathlib import Path
import re
import secrets
import webbrowser

from .atlas_host import AtlasHandler, AtlasHost, load_views
from .http import token_authenticator
from .project_intake import ProjectIntakeService
from .project_contract import project_view
from .project_stage1_delivery import ProjectStage1DeliveryService
from .project_stage1_progress import project_progress
from .project_stage1_records import reading_registration_view
from .project_stage1_atlas import ProjectStage1AtlasService
from .project_stage2_context import ProjectStage2InputReviewService
from .project_stage2_selection import ProjectStage2SelectionService
from .project_stage3_planning import ProjectStage3PlanningService
from .project_stage3_http import (
    ProjectStage3Http,
    ROUTE as PLANNING_ROUTE,
    handle_planning,
)
from .project_stage2_reading import Stage2ReadingRegistry
from .project_atlas_shell import shell_assets
from .project_ui_overlay import (
    PANEL,
    PANEL_CSP,
    PARENT_CSP,
    SOURCE_HTML_CSP,
    install_project_overlay,
    saved_stage1_views,
    stage2_example_views,
)
from .project_stage1_library import ProjectStage1LibraryService
from .project_stage1_source_service import ProjectStage1SourceService
from .project_source_dispatcher import ProjectSourceDispatcher
from .project_stage1_source_http import ROUTE as SOURCE_ROUTE, handle_sources
from .project_stage1_library_http import (
    DETAIL_ROUTE,
    PAGE_ROUTE,
    descriptor,
    read_page,
)
from .session_api import SessionApiError
from .transport import _decode
from stage1_deliverable.common import canonical, sha

ROUTE = re.compile(
    r"/api/projects(?:/([A-Za-z0-9_-]{1,64})"
    r"(?:/(history|overview|contract|confirm|configure|revise|compile|models|stage1|stage2)(?:/(offers|actions|authorize|retire|native|initialize|plan-query|execute-query|screen|coverage|claim|source-claim|reading-review|review-stage2-input|prepare-delivery|recover-delivery|checkpoint|export|deliver|query-authorize|query-bootstrap|query-execute|query-restore-owner|expansion-authorize|expansion-execute|selection|select|direction-intent)(?:/(answer|interrupt))?)?)?)?"
)
READING_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/reading/([0-9a-f]{64})"
)
ATLAS_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/atlas/([0-9]{1,7})/([0-9]{1,10})/([A-Za-z0-9_-]{1,128})/([0-9a-f]{64})(?:/files/([0-9a-f]{64})/([0-9a-f]{64}))?"
)
ACTION_ROUTE = re.compile(r"/api/projects/actions/([A-Za-z0-9_-]{1,128})")
OUTPUT_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/models/outputs/([A-Za-z0-9_-]{1,128})/([0-9]{1,7})"
)
HISTORY_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/models/actions/([0-9]{1,4})"
)
ASSETS = Path(__file__).parent / "web"
SAVED_CLAIM_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/source-claims/([A-Za-z0-9_-]{1,256})"
    r"(?:/([0-9a-f]{64})/([0-9]{1,7}))?"
)
SOURCE_READING_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/source-reading/([A-Za-z0-9_-]{1,256})"
)
AUTOMATIC_NOTE_ROUTE = re.compile(
    r"/api/projects/([A-Za-z0-9_-]{1,64})/stage1/automatic-notes/([0-9a-f]{64})"
)


class ProjectHost(AtlasHost):
    """One local user's projects; each service still owns its admission checks."""

    def __init__(
        self,
        *,
        projects,
        credential,
        models=None,
        stage1=None,
        stage2=None,
        stage2_selection=None,
        stage3_planning=None,
        stage3_recovery_pins=None,
        stage3_close_owner=None,
        stage2_readings=None,
        stage2_controllers=None,
        stage1_materials_root=None,
        stage1_sources=None,
        stage1_source_dispatcher=None,
        **options,
    ):
        if not isinstance(projects, ProjectIntakeService):
            raise ValueError("trusted project intake service required")
        if projects.authenticate(credential) != "local-viewer":
            raise ValueError("same local principal required")
        if stage2_selection is not None and (
            type(stage2_selection) is not ProjectStage2SelectionService
            or stage2_selection.intake is not projects
        ):
            raise ValueError("same trusted Stage2 selection service required")
        if stage3_planning is not None and (
            type(stage3_planning) is not ProjectStage3PlanningService
            or stage3_planning.intake is not projects
            or stage3_planning.selection_view is not stage2_selection
        ):
            raise ValueError("same trusted Stage3 planning service required")
        if stage3_planning is None and (
            stage3_recovery_pins is not None or stage3_close_owner is not None
        ):
            raise ValueError("Stage3 lifecycle requires its planning service")
        planning_http = (
            None
            if stage3_planning is None
            else ProjectStage3Http(
                stage3_planning,
                recovery_pins=stage3_recovery_pins,
                close_owner=stage3_close_owner,
            )
        )
        if (
            stage2_readings is not None
            and type(stage2_readings) is not Stage2ReadingRegistry
        ):
            raise ValueError("trusted Stage2 reading registry required")
        reading_assets, self.stage2_readings = (
            ({}, []) if stage2_readings is None else stage2_readings.snapshot()
        )
        if set(reading_assets) & set(options["files"]):
            raise ValueError("Stage2 reading routes collide with saved view assets")
        controllers = {} if stage2_controllers is None else dict(stage2_controllers)
        if controllers:
            from .project_stage2_controller import ProjectStage2ControllerDriver

            if any(
                not isinstance(ref, str)
                or type(driver) is not ProjectStage2ControllerDriver
                or driver.service is not stage2
                or driver.service.intake is not projects
                for ref, driver in controllers.items()
            ):
                raise ValueError("same trusted Stage2 controller owner required")
            for ref in controllers:
                projects.read(credential, ref)
        if stage1_sources is not None and (
            not isinstance(stage1_sources, ProjectStage1SourceService)
            or stage1_sources.stage1 is not stage1
        ):
            raise ValueError("same trusted Stage1 source service required")
        if stage1_source_dispatcher is not None and (
            type(stage1_source_dispatcher) is not ProjectSourceDispatcher
            or stage1_source_dispatcher.service is not stage1_sources
        ):
            raise ValueError("same trusted Stage1 source dispatcher required")
        for service in (
            models,
            stage1,
            stage2,
            stage1_sources,
            stage1_source_dispatcher,
        ):
            if service is not None and getattr(service, "intake", None) is not projects:
                raise ValueError("same project intake binding required")
        # Load the complete project asset snapshot before allocating a listener
        # or attaching service owners, including the expanded Stage1 assets.
        project_assets = {
            "/" + filename: (ASSETS / filename).read_bytes()
            for filename in (
                "projects.html",
                "projects.js",
                "projects.css",
                "projects-library.js",
                "projects-coverage.js",
                "projects-expansions.js",
                "projects-reading.js",
                "projects-saved-claims.js",
                "projects-atlas.js",
                "projects-progress.js",
                "projects-stages.js",
                "projects-stages.css",
                "projects-stage2-preview.js",
                "projects-stage2-readings.js",
                "project-operations.js",
                "project-operations.css",
                "project-saved-views.js",
                "project-stage2-selection.html",
                "project-stage2-selection.js",
                "project-stage2-selection.css",
                "project-stage3-planning.html",
                "project-stage3-planning.js",
                "project-stage3-planning.css",
            )
        }
        atlas_shell = shell_assets(ASSETS)
        example_assets, self.stage2_examples, self.stage2_example_routes = (
            stage2_example_views(options["files"], options["views"])
        )
        saved_assets, self.saved_stage1_references, self.saved_stage1_routes = (
            saved_stage1_views(options["files"], options["views"])
        )
        from .project_stage1_view_binding import bind_saved_stage1_references

        self.saved_stage1_references = bind_saved_stage1_references(
            projects, credential, self.saved_stage1_references
        )
        self.saved_stage1_source_html_routes = frozenset(
            path
            for path in saved_assets
            if path.endswith(".html") and path not in self.saved_stage1_routes
        )
        self.projects, self.project_models, self.project_stage2 = (
            projects,
            models,
            stage2,
        )
        self.project_stage1 = stage1
        self.project_stage2_selection = stage2_selection
        self.project_stage3_http = planning_http
        self.project_stage2_controllers = controllers
        self.project_expansions = None
        queries = getattr(stage1, "query_service", None)
        if queries is not None:
            from .project_expansions import ProjectStage1ExpansionService

            self.project_expansions = ProjectStage1ExpansionService(queries)
        self.project_stage1_sources = stage1_sources
        self.project_stage1_source_dispatcher = stage1_source_dispatcher
        self.project_stage1_library = (
            None if stage1 is None else ProjectStage1LibraryService(stage1)
        )
        self.project_stage1_delivery = (
            None if stage1 is None else ProjectStage1DeliveryService(stage1)
        )
        self.project_stage1_atlas = (
            None
            if stage1 is None
            else ProjectStage1AtlasService(self.project_stage1_delivery)
        )
        self.project_stage2_input = (
            None
            if stage1 is None
            else ProjectStage2InputReviewService(self.project_stage1_atlas)
        )
        self.project_stage1_records = None
        self.project_stage1_claims = None
        self.project_saved_claims = None
        self.project_reading_review = None
        self.project_records_prepare = None
        if stage1_materials_root is not None:
            from .project_stage1_queries import ProjectStage1QueryService

            queries = getattr(stage1, "query_service", None)
            if (
                not isinstance(queries, ProjectStage1QueryService)
                or queries.stage1 is not stage1
                or queries.intake is not projects
            ):
                raise ValueError(
                    "saved records require the attached trusted query owner"
                )
            self.project_stage1_records = queries.create_records_service(
                self.project_stage1_delivery, materials_root=stage1_materials_root
            )
            from .project_records_prepare import ProjectRecordsPrepareService

            self.project_records_prepare = ProjectRecordsPrepareService(
                self.project_stage1_records
            )
            from .project_saved_claims import ProjectSavedClaimService

            self.project_saved_claims = ProjectSavedClaimService(
                stage1, self.project_stage1_records, models
            )
            if models is not None:
                from .project_model import ProjectModelService

                if isinstance(models, ProjectModelService):
                    models.attach_reading_records(self.project_stage1_records)
                    from .project_stage1_claims import ProjectStage1ClaimService

                    self.project_stage1_claims = ProjectStage1ClaimService(
                        stage1, models, self.project_stage1_records
                    )
            from .project_reading_review import ProjectReadingReviewService

            self.project_reading_review = ProjectReadingReviewService(
                self.project_stage1_claims, saved_claims=self.project_saved_claims
            )
        # Saved package build/replay is bounded filesystem work. The generic
        # 5-second socket default can expire after work but before commit; use
        # the existing hard 30-second HTTP cap, still checked before admission
        # and before commit. This grants no native/model execution time.
        options.setdefault("timeout", 30)
        renderer = {
            path.removeprefix("/project-atlas-static/"): sha(raw)
            for path, raw in atlas_shell.items()
            if path.startswith("/project-atlas-static/")
        }
        if self.project_stage1_atlas is not None and (
            renderer != self.project_stage1_atlas.renderer_sha256
        ):
            raise ValueError("project atlas renderer snapshot differs")
        super().__init__(credential=credential, **options)
        self.RequestHandlerClass = ProjectHandler
        self._assets.update(project_assets)
        self._assets.update(atlas_shell)
        self._assets.update(example_assets)
        self._assets.update(saved_assets)
        self._assets.update(reading_assets)
        self.project_panel_parents = install_project_overlay(
            self._assets, self.views, ASSETS, self.saved_stage1_references
        )
        # No package is invented for a new project. Existing saved views keep
        # their original entry and renderer, with operations in a lazy drawer.
        self._assets["/"] = self._assets["/projects.html"]
        if self.views:
            self._assets.pop("/")  # A redirect has no served HTML byte hash.
        self.host_binding.update(
            project_operations="versioned-intake-and-explicit-registered-actions",
            project_model_provider=models is not None,
            project_stage1_ledger=stage1 is not None,
            project_stage1_saved_records=self.project_stage1_records is not None,
            project_stage1_claim_review=self.project_stage1_claims is not None,
            project_stage1_saved_claim_review=self.project_saved_claims is not None,
            project_stage1_reading_review=self.project_reading_review is not None,
            project_stage1_private_atlas=self.project_stage1_atlas is not None,
            project_stage1_source_controls=stage1_sources is not None,
            project_stage1_source_worker_connected=stage1_sources is not None
            and stage1_sources.runner is not None,
            project_stage1_source_dispatch_registered=stage1_source_dispatcher
            is not None,
            project_stage1_source_acquisition=False,
            project_stage1_automatic_reading=False,
            project_stage1_saved_text_reading=models is not None
            and getattr(models, "reading_records", None) is not None,
            project_stage2_import=stage2 is not None,
            project_stage2_reading_references=self.stage2_readings,
            project_stage2_operator_continuation=bool(controllers),
            project_stage3_planning=stage3_planning is not None,
            project_execution_authority=False,
            project_saved_stage1_references=self.saved_stage1_references,
            project_operations_presentation="additive-v6-drawer",
            project_home_route=self.views[0]["url"] if self.views else "/projects.html",
        )
        self.host_binding["served_files"] = {
            path: sha(raw)
            for path, raw in self._assets.items()
            if path != "/host-binding.json"
        }
        self._assets["/host-binding.json"] = canonical(self.host_binding)

    def server_close(self):
        try:
            if self.project_stage3_http is not None:
                self.planning_shutdown = self.project_stage3_http.close()
            if self.project_stage1_source_dispatcher is not None:
                self.source_dispatch_shutdown = (
                    self.project_stage1_source_dispatcher.close()
                )
            elif self.project_stage1_sources is not None:
                self.project_stage1_sources.close()
        finally:
            super().server_close()

    def continue_stage1(
        self,
        credential,
        ref,
        *,
        run_id,
        deadline,
        max_actions=32,
        run_grants=None,
        grant_ref=None,
        grant_sha256=None,
    ):
        """Trusted operator continuation; does not register grants or start Stage2."""
        full_source = getattr(self, "project_stage1_full_source_execution", None)
        if full_source is not None:
            return full_source.run(
                credential,
                ref,
                run_id=run_id,
                deadline=deadline,
                max_actions=max_actions,
                run_grants=run_grants,
                grant_ref=grant_ref,
                grant_sha256=grant_sha256,
            )
        from .project_stage1_auto import ProjectStage1AutoDriver

        return ProjectStage1AutoDriver(self, credential, ref).run(
            run_id=run_id,
            deadline=deadline,
            max_actions=max_actions,
            run_grants=run_grants,
            grant_ref=grant_ref,
            grant_sha256=grant_sha256,
        )

    def register_stage1_full_source(
        self, credential, ref, *, run_grants, grant_ref, grant_sha256, output_root
    ):
        """Bind only an existing trusted run; no permission or execution is created."""
        from .project_stage1_full_source import ProjectStage1FullSourceAdapter

        if getattr(self, "project_stage1_full_source_execution", None) is not None:
            raise ValueError("full-source Stage1 adapter already registered")
        adapter = ProjectStage1FullSourceAdapter(
            self,
            credential,
            ref,
            run_grants=run_grants,
            grant_ref=grant_ref,
            grant_sha256=grant_sha256,
            output_root=output_root,
        )
        self.project_stage1_full_source_execution = adapter
        self.host_binding.update(
            project_stage1_full_source_run=grant_sha256,
            project_stage1_automatic_reading=True,
            project_stage1_full_source_stage2_execution=False,
        )
        self._assets["/host-binding.json"] = canonical(self.host_binding)
        return dict(
            registered=True,
            project_ref=ref,
            run_grant_sha256=grant_sha256,
            model_or_source_started=False,
            stage2_started=False,
        )

    def register_stage1_execution(
        self, ref, *, permit_path, permit_sha256, output_root
    ):
        """Trusted bootstrap only; register a delegated producer without running it."""
        from .project_stage1_execution import ProjectStage1ExecutionService

        if getattr(self, "project_stage1_full_source_execution", None) is not None:
            raise ValueError("full-source Stage1 adapter already registered")

        if getattr(self, "project_stage1_execution", None) is not None:
            raise ValueError("automatic Stage1 producer already registered")
        producer = ProjectStage1ExecutionService(
            self.project_stage1,
            self.project_models,
            self.project_stage1_records,
            permit_path=permit_path,
            permit_sha256=permit_sha256,
            output_root=output_root,
        )
        try:
            producer._permit(ref)
        except BaseException:
            self.project_models.automatic_stage1 = None
            raise
        self.project_stage1_execution = producer
        self.host_binding.update(
            project_stage1_automatic_reading=True,
            project_stage1_automatic_parent_sha256=permit_sha256,
            project_stage1_automatic_stage2_execution=False,
        )
        self._assets["/host-binding.json"] = canonical(self.host_binding)
        return dict(
            registered=True,
            project_ref=ref,
            permit_sha256=permit_sha256,
            model_or_source_started=False,
            stage2_started=False,
        )

    def continue_stage2(self, credential, ref, *, key):
        """Trusted operator continuation under its original admitted run budget.

        Browser input cannot install a controller or change native policy, paths
        or deadlines. Research completion is distinct from selection/intake.
        """
        self.projects.read(credential, ref)
        driver = self.project_stage2_controllers.get(ref)
        if driver is None:
            raise SessionApiError("stage2-controller-not-connected", 409)
        return driver.run(credential, ref, key=key)

    def overview(self, credential, ref, *, automatic=False):
        # One store lock joins matching saved revisions. Workers cannot commit
        # another input/version between the UI brief and its action offers.
        with self.projects._lock:
            project = self.projects.read(credential, ref)
            direct_receiving = (
                project.get("input_origin") == "stage2-direct-request"
                and project.get("receiving_only") is True
            )
            result = dict(
                project=project,
                models=None
                if self.project_models is None
                else self.project_models.read(credential, ref),
                model_offers=None
                if self.project_models is None
                else self.project_models.offers(credential, ref),
                stage1=None
                if self.project_stage1 is None or direct_receiving
                else self.stage1_view(credential, ref, automatic=automatic),
                stage2=None
                if self.project_stage2 is None
                else self.project_stage2.read(credential, ref),
            )
            if result["stage1"] is not None:
                result["stage1"]["progress"] = project_progress(result)
            return result

    def stage1_view(self, credential, ref, *, automatic=False):
        """Read saved delivery offers together with the same project revision."""
        with self.projects._lock:
            result = dict(
                self.project_stage1.read(credential, ref),
                delivery=self.project_stage1_delivery.read(credential, ref),
                saved_records_connected=self.project_records_prepare is not None,
                saved_records_recovery=(
                    None
                    if self.project_records_prepare is None
                    else self.project_records_prepare.recovery.read(credential, ref)
                ),
            )
            queries = getattr(self.project_stage1, "query_service", None)
            result["query_execution"] = (
                None if queries is None else queries.read(credential, ref)
            )
            result["expansion_execution"] = (
                None
                if self.project_expansions is None
                else self.project_expansions.read(credential, ref)
            )
            # One shared overview revision, with full history in bound GET pages.
            result["screening_library"] = descriptor(result)
            result["source_execution"] = (
                None
                if self.project_stage1_sources is None
                else self.project_stage1_sources.read(credential, ref)
            )
            ledger = result["ledger"]
            state_hash = None if ledger is None else ledger["state_sha256"]
            result["reading_registration"] = (
                reading_registration_view(
                    self.projects.read(credential, ref), state_hash
                )
                if self.project_stage1_records is None
                else self.project_stage1_records.reading_readiness(
                    credential, ref, expected_ledger_state_sha256=state_hash
                )
            )
            producer = getattr(self, "project_stage1_full_source_execution", None)
            if producer is None:
                producer = getattr(self, "project_stage1_execution", None)
            result["automatic_production"] = (
                producer.project_view(credential, ref)
                if automatic and producer is not None
                else None
            )
            return result


class ProjectHandler(AtlasHandler):
    def send_header(self, keyword, value):
        if keyword.lower() == "content-security-policy":
            if self.path in self.server.saved_stage1_source_html_routes:
                value = SOURCE_HTML_CSP
            elif self.path == PANEL:
                value = PANEL_CSP
            elif self.path == "/project-atlas.html":
                value = value.replace(
                    "frame-ancestors 'none'", "frame-ancestors 'self'"
                )
            elif (
                self.path in self.server.stage2_example_routes
                or self.path in self.server.saved_stage1_routes
            ):
                value = value.replace(
                    "frame-ancestors 'none'", "frame-ancestors 'self'"
                )
            elif self.path == "/projects.html" or (
                self.path == "/" and not self.server.views
            ):
                value = PARENT_CSP
            elif self.path in self.server.project_panel_parents:
                value = PARENT_CSP
        super().send_header(keyword, value)

    def _project(self, method):
        if SOURCE_ROUTE.fullmatch(self.path) is not None:
            return handle_sources(self, method)
        if PLANNING_ROUTE.fullmatch(self.path) is not None:
            return handle_planning(self, method)
        called = None
        try:
            token, length = self._headers(method)
            if self.headers.get("Sec-Fetch-Site") not in (None, "none", "same-origin"):
                raise SessionApiError("cross-site-rejected", 403)
            if self.server.authenticate(token) is None:
                raise SessionApiError("credential-rejected", 401)
            automatic_note = AUTOMATIC_NOTE_ROUTE.fullmatch(self.path)
            if automatic_note is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                producer = getattr(
                    self.server, "project_stage1_full_source_execution", None
                )
                if producer is None:
                    producer = getattr(self.server, "project_stage1_execution", None)
                if producer is None:
                    raise SessionApiError("automatic-stage1-unconnected", 409)
                result = producer.note_by_hash(
                    token, automatic_note[1], automatic_note[2]
                )
                self._remaining()
                return self._reply(200, result)
            atlas = ATLAS_ROUTE.fullmatch(self.path)
            if atlas is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                if self.server.project_stage1_atlas is None:
                    raise SessionApiError("stage1-atlas-unconnected", 409)
                result = self.server.project_stage1_atlas.read(
                    token,
                    atlas[1],
                    input_version=int(atlas[2]),
                    revision=int(atlas[3]),
                    artifact_ref=atlas[4],
                    manifest_sha256=atlas[5],
                    file_ref=atlas[6],
                    file_sha256=atlas[7],
                    check_deadline=self._remaining,
                )
                self._remaining()
                return self._reply(200, result)
            output = OUTPUT_ROUTE.fullmatch(self.path)
            page = HISTORY_ROUTE.fullmatch(self.path)
            screening = PAGE_ROUTE.fullmatch(self.path)
            detail = DETAIL_ROUTE.fullmatch(self.path)
            reading = READING_ROUTE.fullmatch(self.path)
            saved_claim = SAVED_CLAIM_ROUTE.fullmatch(self.path)
            source_reading = SOURCE_READING_ROUTE.fullmatch(self.path)
            if source_reading is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                extension = self.server.project_reading_review
                if extension is None:
                    raise SessionApiError("stage1-reading-review-unconnected", 409)
                result = extension.view_source(
                    token,
                    source_reading[1],
                    source_reading[2],
                    check_deadline=self._remaining,
                )
                self._remaining()
                return self._reply(200, result)
            if saved_claim is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                if self.server.project_saved_claims is None:
                    raise SessionApiError("saved-claim-review-unconnected", 409)
                result = self.server.project_saved_claims.view(
                    token,
                    saved_claim[1],
                    saved_claim[2],
                    saved_claim[3],
                    int(saved_claim[4] or 0),
                    check_deadline=self._remaining,
                )
                self._remaining()
                return self._reply(200, result)
            if reading is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                extension = (
                    self.server.project_reading_review
                    or self.server.project_stage1_claims
                )
                if extension is None:
                    raise SessionApiError("stage1-claim-review-unconnected", 409)
                result = extension.view(
                    token, reading[1], reading[2], check_deadline=self._remaining
                )
                self._remaining()
                return self._reply(200, result)
            if screening is not None or detail is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                result = read_page(
                    self.server.project_stage1_library,
                    token,
                    detail if detail is not None else screening,
                    detail=detail is not None,
                )
                if detail is not None:
                    models = self.server.project_models
                    reading_offer = getattr(models, "reading_offer", None)
                    result["reading_offer"] = (
                        dict(
                            available=False,
                            snapshot_sha256=None,
                            blocked_reason="reading-model-or-records-unconnected",
                            execution_authorized=False,
                        )
                        if not callable(reading_offer)
                        else reading_offer(
                            token,
                            result["project_ref"],
                            result["row"]["work_id"],
                            expected_input_version=result["input_version"],
                            expected_ledger_state_sha256=result["binding"][
                                "ledger_state_sha256"
                            ],
                            check_deadline=self._remaining,
                        )
                    )
                self._remaining()
                return self._reply(200, result)
            if output is not None or page is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                extension = self.server.project_models
                if extension is None:
                    raise SessionApiError("project-operation-unconnected", 409)
                result = (
                    extension.outputs(token, output[1], output[2], int(output[3]))
                    if output is not None
                    else extension.history(token, page[1], offset=int(page[2]))
                )
                self._remaining()
                return self._reply(200, result)
            recovery = ACTION_ROUTE.fullmatch(self.path)
            if recovery is not None:
                if method != "GET" or length:
                    raise SessionApiError("invalid-project-read", 400)
                result = self.server.projects.action(token, recovery.group(1))
                self._remaining()
                self._reply(200, {"action": result})
                return
            match = ROUTE.fullmatch(self.path)
            if match is None:
                raise SessionApiError("unknown-project-route", 404)
            ref, operation, action, resolution = match.groups()
            service = self.server.projects
            self._remaining()
            if method == "GET":
                if length or operation in {"confirm", "configure", "revise", "compile"}:
                    raise SessionApiError("invalid-project-read", 400)
                if operation not in {"models", "stage1", "stage2"} and (
                    action or resolution
                ):
                    raise SessionApiError("invalid-project-read", 400)
                if (
                    operation == "stage2"
                    and action == "selection"
                    and resolution is None
                ):
                    extension = self.server.project_stage2_selection
                    if extension is None:
                        raise SessionApiError("stage2-selection-unconnected", 409)
                    result = extension.read(token, ref, check_deadline=self._remaining)
                elif operation in {"models", "stage1", "stage2"}:
                    extension = (
                        self.server.project_models
                        if operation == "models"
                        else self.server.project_stage1
                        if operation == "stage1"
                        else self.server.project_stage2
                    )
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    if resolution or action not in {
                        None,
                        "offers",
                        "actions",
                        "native",
                    }:
                        raise SessionApiError("invalid-project-read", 400)
                    if action == "native" and operation != "models":
                        raise SessionApiError("invalid-project-read", 400)
                    result = (
                        extension.native_view(token, ref)
                        if action == "native" and operation == "models"
                        else extension.offers(token, ref)
                        if action == "offers"
                        else extension.history(token, ref)
                        if action == "actions"
                        else extension.read(token, ref)
                    )
                    if operation == "stage1" and action in {None, "offers"}:
                        result = self.server.stage1_view(token, ref, automatic=True)
                elif operation == "overview":
                    if action or resolution:
                        raise SessionApiError("invalid-project-read", 400)
                    result = self.server.overview(token, ref, automatic=True)
                elif operation == "contract":
                    with service._lock:
                        result = project_view(
                            service,
                            token,
                            ref,
                            models=self.server.project_models,
                            stage1=self.server.project_stage1,
                            stage2=self.server.project_stage2,
                            stage1_delivery=self.server.project_stage1_delivery,
                        )
                else:
                    result = (
                        service.list(token)
                        if ref is None
                        else service.history(token, ref)
                        if operation == "history"
                        else service.read(token, ref)
                    )
            else:
                if self.headers.get("Content-Type", "").lower() != "application/json":
                    raise SessionApiError("json-content-type-required", 415)
                if not 0 < length <= 65536:
                    raise SessionApiError("project-body-bound-exceeded", 413)
                raw = self.rfile.read(length)
                if len(raw) != length:
                    raise SessionApiError("partial-body", 400)
                try:
                    body = _decode(raw.decode("utf8"))
                except (ValueError, UnicodeError, RecursionError):
                    raise SessionApiError("invalid-json", 400) from None
                self._remaining()
                if ref is None:
                    called = ("create", None, body)
                    result = service.create(token, body, check_deadline=self._remaining)
                elif operation == "confirm" and action is None:
                    called = ("submit", ref, body)
                    result = service.submit(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation in {"configure", "revise"} and action is None:
                    called = (operation, ref, body)
                    result = getattr(service, operation)(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation == "compile" and action is None:
                    called = ("compile", ref, body)
                    result = service.compile(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif (
                    operation == "stage1"
                    and action
                    in {
                        "initialize",
                        "screen",
                        "coverage",
                        "claim",
                        "source-claim",
                        "reading-review",
                        "review-stage2-input",
                        "prepare-delivery",
                        "recover-delivery",
                        "plan-query",
                        "execute-query",
                        "checkpoint",
                        "export",
                        "deliver",
                        "query-authorize",
                        "query-bootstrap",
                        "query-execute",
                        "query-restore-owner",
                        "expansion-authorize",
                        "expansion-execute",
                    }
                    and resolution is None
                ):
                    extension = self.server.project_stage1
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    called = ("stage1-" + action, ref, body)
                    if action == "deliver":
                        extension = self.server.project_stage1_delivery
                    elif action == "review-stage2-input":
                        extension = self.server.project_stage2_input
                        action = "review"
                    elif action == "claim":
                        extension = self.server.project_stage1_claims
                        if extension is None:
                            raise SessionApiError(
                                "stage1-claim-review-unconnected", 409
                            )
                    elif action == "source-claim":
                        extension = self.server.project_saved_claims
                        if extension is None:
                            raise SessionApiError("saved-claim-review-unconnected", 409)
                        called = ("stage1-claim", ref, body)
                        action = "claim"
                    elif action == "reading-review":
                        extension = self.server.project_reading_review
                        if extension is None:
                            raise SessionApiError(
                                "stage1-reading-review-unconnected", 409
                            )
                        called = ("stage1-reading-registry", ref, body)
                        action = "review"
                    elif action in {"prepare-delivery", "recover-delivery"}:
                        extension = self.server.project_records_prepare
                        if extension is None:
                            raise SessionApiError(
                                "stage1-records-prepare-unconnected", 409
                            )
                        if action == "recover-delivery":
                            extension = extension.recovery
                            called = ("stage1-recover-delivery", ref, body)
                            action = "recover"
                        else:
                            called = ("stage1-produce-records", ref, body)
                            action = "prepare"
                    elif action.startswith("expansion-"):
                        extension = self.server.project_expansions
                        if extension is None:
                            raise SessionApiError("stage1-expansion-unconnected", 409)
                        action = action.removeprefix("expansion-")
                    elif action.startswith("query-"):
                        extension = getattr(extension, "query_service", None)
                        if extension is None:
                            raise SessionApiError(
                                "stage1-query-execution-unconnected", 409
                            )
                        action = action.removeprefix("query-")
                    result = getattr(extension, action.replace("-", "_"))(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif (
                    operation == "stage2"
                    and action in {"select", "direction-intent"}
                    and resolution is None
                ):
                    extension = self.server.project_stage2_selection
                    if extension is None:
                        raise SessionApiError("stage2-selection-unconnected", 409)
                    called = ("stage2-" + action, ref, body)
                    result = getattr(extension, action.replace("-", "_"))(
                        token, ref, body, check_deadline=self._remaining
                    )
                elif operation in {"models", "stage2"} and action in {
                    "actions",
                    "authorize",
                    "native",
                    "retire",
                }:
                    extension = (
                        self.server.project_models
                        if operation == "models"
                        else self.server.project_stage2
                    )
                    if extension is None:
                        raise SessionApiError("project-operation-unconnected", 409)
                    if (
                        operation == "models"
                        and action == "native"
                        and resolution in {"answer", "interrupt"}
                    ):
                        function = getattr(extension, resolution)
                    elif (
                        operation == "models"
                        and action == "authorize"
                        and resolution is None
                    ):
                        function = extension.authorize
                        called = ("model-authorization", ref, body)
                    elif action == "actions" and resolution is None:
                        function = (
                            extension.execute
                            if operation == "models"
                            else extension.activate
                        )
                        called = (
                            "model-operation"
                            if operation == "models"
                            else "stage2-activate",
                            ref,
                            body,
                        )
                    elif (
                        operation == "models"
                        and action == "retire"
                        and resolution is None
                    ):
                        function = extension.retire
                        called = ("model-retirement", ref, body)
                    else:
                        raise SessionApiError("unknown-project-write", 404)
                    result = function(token, ref, body, check_deadline=self._remaining)
                else:
                    raise SessionApiError("unknown-project-write", 404)
            self._remaining()
            self._reply(200, result)
        except SessionApiError as error:
            response = {"error": error.code}
            if called is not None:
                kind, project_ref, body = called
                try:
                    response["receipt"] = self.server.projects.record_refusal(
                        token, body.get("key"), project_ref, kind, body, error.code
                    )
                except (SessionApiError, ValueError, OSError, KeyError, TypeError):
                    pass  # No evidence means unresolved, never inferred unsent.
            self._reply(error.status, response)
        except (TimeoutError, OSError):
            self.close_connection = True
        except (ValueError, UnicodeError, KeyError, TypeError):
            self._reply(400, {"error": "project-input-rejected"})
        except Exception:
            self._reply(500, {"error": "project-operation-failed"})

    def do_GET(self):
        if self.path == "/" and self.server.views:
            # Redirect rather than alias HTML: the reviewed view uses relative
            # assets, notes and links under its original saved-package route.
            if (
                self.headers.get("Host") != self.server.expected_host
                or self.headers.get("Origin") not in (None, self.server.expected_origin)
                or self.headers.get("Sec-Fetch-Site")
                not in (None, "none", "same-origin")
                or any(
                    len(self.headers.get_all(name, [])) > 1
                    for name in (
                        "Host",
                        "Origin",
                        "Content-Length",
                        "Transfer-Encoding",
                    )
                )
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Length", "0") != "0"
            ):
                return self._reply(403, {"error": "origin-or-host-rejected"})
            self._remaining()
            self.send_response(302)
            for name, value in (
                ("Location", self.server.views[0]["url"]),
                ("Content-Length", "0"),
                ("Cache-Control", "no-store"),
                ("Connection", "close"),
            ):
                self.send_header(name, value)
            self.close_connection = True
            self.end_headers()
            return
        if self.path.startswith("/api/projects"):
            return self._project("GET")
        if self.path == "/project-bootstrap.js":
            # Same-origin local bootstrap, matching the existing Atlas credential
            # boundary. No credential appears in URL, HTML, logs or storage.
            if (
                self.headers.get("Host") != self.server.expected_host
                or self.headers.get("Origin") not in (None, self.server.expected_origin)
                or self.headers.get("Sec-Fetch-Site")
                not in (None, "none", "same-origin")
                or any(
                    len(self.headers.get_all(name, [])) > 1
                    for name in (
                        "Host",
                        "Origin",
                        "Content-Length",
                        "Transfer-Encoding",
                    )
                )
                or self.headers.get("Transfer-Encoding") is not None
                or self.headers.get("Content-Length", "0") != "0"
            ):
                return self._reply(403, {"error": "origin-or-host-rejected"})
            self.server._assets[self.path] = (
                "window.RESEARCH_PROJECTS="
                + json.dumps(
                    dict(
                        credential=self.server.credential,
                        views=self.server.views,
                        stage2_examples=self.server.stage2_examples,
                        stage2_readings=self.server.stage2_readings,
                        models=self.server.project_models is not None,
                        stage2=self.server.project_stage2 is not None,
                        stage2_selection_projects=(
                            list(self.server.project_stage2_selection.bindings)
                            if self.server.project_stage2_selection is not None
                            else []
                        ),
                        stage3_planning_projects=(
                            list(self.server.project_stage3_http.service.bindings)
                            if self.server.project_stage3_http is not None
                            else []
                        ),
                        stage1=self.server.project_stage1 is not None,
                    ),
                    ensure_ascii=True,
                    allow_nan=False,
                ).replace("<", "\\u003c")
                + ";\n"
            ).encode("utf8")
        return super().do_GET()

    def do_POST(self):
        if self.path.startswith("/api/projects"):
            return self._project("POST")
        return super().do_POST()


def main(argv=None):
    from .project_stage1 import ProjectStage1Service
    from .project_stage2 import ProjectStage2Service

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--projects-root", required=True, type=Path)
    parser.add_argument("--views-config", type=Path)
    parser.add_argument("--views-sha256")
    parser.add_argument("--stage1-import-config", type=Path)
    parser.add_argument("--stage1-import-sha256")
    parser.add_argument("--stage2-direct-import-config", type=Path)
    parser.add_argument("--stage2-direct-import-sha256")
    parser.add_argument("--controller-config", type=Path)
    parser.add_argument("--controller-sha256")
    parser.add_argument("--continue-stage2", metavar="PROJECT_REF")
    parser.add_argument("--controller-key")
    parser.add_argument("--selection-config", type=Path)
    parser.add_argument("--selection-sha256")
    parser.add_argument("--stage2-reading-config", type=Path)
    parser.add_argument("--stage2-reading-sha256")
    parser.add_argument("--stage3-planning-config", type=Path)
    parser.add_argument("--stage3-planning-sha256")
    parser.add_argument("--port", type=int, default=0)
    parser.add_argument("--open", action="store_true")
    args = parser.parse_args(argv)
    if bool(args.views_config) != bool(args.views_sha256):
        parser.error("saved views require their external configuration SHA256")
    if bool(args.stage1_import_config) != bool(args.stage1_import_sha256):
        parser.error("Stage1 imports require their external configuration SHA256")
    if bool(args.stage2_direct_import_config) != bool(args.stage2_direct_import_sha256):
        parser.error(
            "direct Stage2 imports require their external configuration SHA256"
        )
    if bool(args.selection_config) != bool(args.selection_sha256):
        parser.error("selection bindings require their external configuration SHA256")
    if bool(args.stage2_reading_config) != bool(args.stage2_reading_sha256):
        parser.error("Stage2 readings require their external configuration SHA256")
    if bool(args.controller_config) != bool(args.controller_sha256):
        parser.error("Stage2 controllers require their external configuration SHA256")
    if bool(args.stage3_planning_config) != bool(args.stage3_planning_sha256):
        parser.error("Stage3 planning requires its external configuration SHA256")
    if args.stage3_planning_config and not (
        args.selection_config or args.stage2_direct_import_config
    ):
        parser.error("Stage3 planning requires configured Stage2 selection")
    if bool(args.continue_stage2) != bool(args.controller_key) or (
        args.continue_stage2 and not args.controller_config
    ):
        parser.error(
            "Stage2 continuation requires a configured project and original request key"
        )
    files, views = (
        load_views(args.views_config, args.views_sha256)
        if args.views_config
        else ({}, [])
    )
    readings = (
        Stage2ReadingRegistry(args.stage2_reading_config, args.stage2_reading_sha256)
        if args.stage2_reading_config
        else None
    )
    token = secrets.token_urlsafe(32)
    projects = ProjectIntakeService(
        args.projects_root, authenticate=token_authenticator({token: "local-viewer"})
    )
    host = None
    planning_resources = None
    failure = None
    try:
        stage2 = ProjectStage2Service(projects)
        if args.stage1_import_config is not None:
            from .project_stage1_import import load_stage1_imports

            load_stage1_imports(
                stage2, token, args.stage1_import_config, args.stage1_import_sha256
            )
        controllers = {}
        if args.controller_config:
            from .project_stage2_controller_config import load_stage2_controllers

            controllers = load_stage2_controllers(
                stage2, token, args.controller_config, args.controller_sha256
            )
        selection = None
        selection_bindings = {}
        if args.stage2_direct_import_config:
            from .project_stage2_direct_config import load_direct_request_imports

            selection_bindings = load_direct_request_imports(
                stage2,
                token,
                args.stage2_direct_import_config,
                args.stage2_direct_import_sha256,
            )
        if args.selection_config:
            raw = args.selection_config.read_bytes()
            if args.selection_config.is_symlink() or sha(raw) != args.selection_sha256:
                parser.error("selection configuration receipt differs")
            config = _decode(raw.decode("utf-8"))
            if (
                not isinstance(config, dict)
                or set(config) != {"schema_version", "bindings"}
                or config["schema_version"] != "1.0.0"
            ):
                parser.error("selection configuration shape differs")
            if not isinstance(config["bindings"], dict) or set(
                selection_bindings
            ) & set(config["bindings"]):
                parser.error("selection bindings overlap or have invalid shape")
            selection_bindings.update(config["bindings"])
        if args.selection_config or args.stage2_direct_import_config:
            selection = ProjectStage2SelectionService(projects, selection_bindings)
        if args.stage3_planning_config:
            from .project_stage3_planning_config import (
                Stage3PlanningHostResources,
                load_stage3_planning_configuration,
            )

            planning_config = load_stage3_planning_configuration(
                projects,
                token,
                args.stage3_planning_config,
                args.stage3_planning_sha256,
            )
            planning_resources = Stage3PlanningHostResources(
                projects, token, selection, planning_config
            )
        host = ProjectHost(
            projects=projects,
            credential=token,
            stage1=ProjectStage1Service(projects),
            stage2=stage2,
            stage2_selection=selection,
            stage3_planning=(
                planning_resources.service if planning_resources is not None else None
            ),
            stage3_recovery_pins=(
                planning_resources.recovery_pins
                if planning_resources is not None
                else None
            ),
            stage2_readings=readings,
            stage2_controllers=controllers,
            files=files,
            views=views,
            port=args.port,
        )
        if planning_resources is not None:
            # The CLI must join the original request threads before closing intake.
            # NativePlanner keeps its original finite deadline; no worker is added.
            host.daemon_threads = False
            host.block_on_close = True
        if args.continue_stage2:
            outcome = host.continue_stage2(
                token, args.continue_stage2, key=args.controller_key
            )
            print(
                json.dumps({"stage2_controller": outcome}, ensure_ascii=False),
                flush=True,
            )
        url = host.expected_origin + "/"
        print(
            json.dumps(
                dict(
                    url=url,
                    model_execution="unconnected",
                    search_execution="unconnected",
                    stage3_planning=(
                        "connected" if planning_resources is not None else "unconnected"
                    ),
                    execution_authorized=False,
                )
            ),
            flush=True,
        )
        if args.open:
            webbrowser.open(url)
        host.serve_forever()
    except KeyboardInterrupt:
        pass
    except BaseException as error:
        failure = error
        raise
    finally:
        cleanup_errors = []
        # Only a completed server_close confirms the configured handlers drained.
        # Keep their Journal and intake open if that join fails or is interrupted.
        drained = host is None or planning_resources is None
        try:
            if host is not None:
                host.server_close()
                drained = True
                if planning_resources is not None:
                    host.planning_shutdown = host.project_stage3_http.close()
        except BaseException as cleanup:
            cleanup_errors.append(cleanup)
        finally:
            if drained:
                try:
                    if planning_resources is not None:
                        planning_resources.close()
                except BaseException as cleanup:
                    cleanup_errors.append(cleanup)
                finally:
                    try:
                        projects.close()
                    except BaseException as cleanup:
                        cleanup_errors.append(cleanup)
            else:
                cleanup_errors.append(
                    RuntimeError(
                        "CLI handlers did not confirm shutdown; "
                        "Journal and intake remain open"
                    )
                )
        if cleanup_errors:
            primary = failure if failure is not None else cleanup_errors[0]
            for cleanup in cleanup_errors:
                if cleanup is not primary:
                    primary.add_note(f"ProjectHost cleanup failed: {cleanup!r}")
            if failure is None:
                raise primary


if __name__ == "__main__":
    main()
