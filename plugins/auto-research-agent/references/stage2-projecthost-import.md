# Import an accepted Stage 1 project into ProjectHost

The trusted local host can preserve a saved Stage 1 project ID, input-version type,
and confirmed ResearchBrief bytes. It does not create a new researcher decision,
a compiled Stage 1 search plan, or a research execution permit.

Use ProjectStage2Service.import_stage1_project(credential, **trusted_inputs), or
start the existing ProjectHost with --stage1-import-config PATH and
--stage1-import-sha256 SHA256. Both flags are required together. The host checks
configuration bytes and saved-source admission before allocating its listener.
Browser requests cannot choose these paths or import a package.

The private configuration is JSON with kind ProjectStage1ImportConfiguration,
schema_version 1.0.0, and a nonempty entries array. Each entry contains:

- brief_path and expected_brief_sha256 (the original confirmed file bytes).
- settings, including resource_envelope matching resources_path exactly after trim.
- deliverable_dir and expected_manifest_sha256 (the external canonical manifest hash).
- handoff_path and expected_handoff_sha256 (the external raw file hash).
- resources_path and expected_resources_sha256 (the external raw file hash).
- policy_ref with route stage2-general-v3/daily_v3.
- saved_source_root and saved_source_acceptance_sha256.
- When needed, host_replay_receipt, trusted_host_replay_sha256,
  historical_exporter_root, and replayer_exporter_root together.

Keep this configuration and source material outside Git. Paths are trusted host
configuration; hashes must come from accepted external receipts, not be guessed.
The saved-source consumer still checks its supported canonical-records version,
work/version identities, original source evidence, eligibility and replay pins.
It refuses missing or changed admission; it never promotes metadata into findings.

The catalog project_ref is an opaque local identifier. project_id and input_version
remain the original Stage 1 values, including a string version. Repeating the same
trusted import preserves the project and offer. A partial private file is reusable
only when its bytes are identical. Source drift and changed partial files fail.

Imported brief revisions are read-only. Use the source owner to produce a new
accepted version, then import its new binding. Stage 2 activation remains explicit
in the existing project UI; activation creates the original empty seed and workflow,
not a completed study. Direction selection and Stage 3 intake retain their separate
current-version, external-hash and actual-user-submission checks. Zero recommendations
remain readable but cannot become an eligible selection. execution_authorized stays
false. These engineering checks do not rerun or score any research.

The project UI keeps imported Stage1 confirmation/revision forms read-only. Missing
Stage1 budget and consent fields are left blank or ungranted, while the verified
Stage2 activation offer remains available in all three interface languages.
