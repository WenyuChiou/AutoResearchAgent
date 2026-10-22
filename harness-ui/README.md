# V9 local Harness UI

This opt-in workbench keeps Stage1 and Stage2 separate. It runs on the repository's
existing `ProjectHost`; it does not replace the default Wiki or change research rules.
The result area uses saved, hash-bound artifacts. Imported inputs, local comparison
choices, formal selections, and newly generated research have different states.

## Start from a checkout

Python 3.11+ and the existing Harness schema/document dependencies (`requirements.txt`)
are required. The host imports editable-document helpers even when only reading a
workflow. Node 22+ is used only for the JavaScript syntax check. Use an existing
Python environment; install the declared dependencies with
`python -m pip install -r harness-ui/requirements.txt`.
From the repository root, in PowerShell:

```powershell
$repoPath = (Get-Location).Path
$dataPath = Join-Path (Split-Path $repoPath -Parent) 'v9-local-data'
New-Item -ItemType Directory -Force -Path (Join-Path $dataPath 'incoming') | Out-Null
python harness-ui/setup_vendor.py
$sourcePin = (Get-FileHash -Algorithm SHA256 -LiteralPath (Join-Path $repoPath 'plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py')).Hash.ToLower()
python harness-ui/run_v9.py --repo $repoPath --source-helper-sha256 $sourcePin --projects-root (Join-Path $dataPath 'projects') --ui-state-root (Join-Path $dataPath 'ui-state') --incoming-root (Join-Path $dataPath 'incoming') --run-limits harness-ui/zero-limits.json --port 62431 --open
```

`setup_vendor.py` obtains the pinned official Three.js core and checks its archive
and member hashes; it executes no package scripts. For offline setup, use
`--from-file /path/to/three.core.js` with the exact verified distribution.
The large generated vendor file is ignored by Git. The other vendors are reused
from this repository. No private delivery, database, credential or research output
is included in this source package.

The service binds only to `127.0.0.1`, uses the existing Host/Origin and bearer checks,
and has zero research limits by default. Data roots must be outside Git; incoming
materials and UI state must be separate. Opening the page does not start a model.
Old V7 filenames and contract markers remain internally for compatibility.

## Use a delivery

1. Create a project, or load an operator-configured canonical saved view through the
   original workspace launcher's `--views` configuration.
2. Open **加入文件与阶段接续** in the relevant stage. Ordinary files are registered
   as unreviewed materials, not automatically classified, screened, or approved.
3. For Stage2, place a `Stage2Packet` and all its relative source files under the
   incoming directory. Enter its path, source root and file SHA-256. The adapter
   calls Harness `stage2_common.validate_packet`; it does not extract arbitrary ZIPs.
4. Choose **读取并显示这份材料**. The current project's validated packet, sources,
   evidence and candidates populate the existing literature/route comparison UI.
   Full originals remain available behind details. Missing reviews stay Unknown.
5. Save the comparison list and continuation note. Reloading can restore the saved
   source/candidate versions. These choices are a local draft, not a formal selection.
6. **建立Harness接续快照** uses `initialize_workflow`; reading it again uses
   `inspect_workflow`. This preserves an event head but performs zero research actions.
   Old recommendations are not replayed as authority in the new workflow.

## Connected and remaining

### Optional original review reader

An operator may supply `--review-sources FILE --review-sources-sha256 SHA256`.
The pinned JSON has `schema_version: 1` and an `entries` list. Each entry contains
`project_ref`, the exact `packet_file_sha256`, an absolute `delivery_root` under
the existing incoming directory, and the canonical `delivery_manifest_sha256`.
The GET projection reuses `inspect_delivery` and rechecks the original packet and
`review_results.json`; it does not infer a review file from a nearby filename.
Changed bytes or a different project, candidate version, or manifest are refused.

The result page offers one collapsed **Original independent reviews** entry.
Original roles, reasons, checks, next steps, failed records and complete JSON stay
available on demand. These are reading records, not new scientific scores or a
formal choice. A draft remains a draft; formal selection and Stage3 stay disabled.
Packet2.6 requires the corresponding merged Harness validator/runtime. Existing
canonical delivery HTML and frozen package files are not modified by this reader.

| Area | Available here | Still required |
|---|---|---|
| Stage1 operations | Existing project/scope, progress, screening/reading views and checkpoint entry; closed operation panel stays clickable | A trusted current run is required to exercise live review. Pause/revise/resume of an unfinished loop is not implemented by this adapter |
| Manual materials | Stage-bound registration, chunked upload, SHA verification, persistent drafts | Raw uploaded files do not become reviewed evidence or continuation permission |
| Stage2 | Validated packet projection; literature, routes, gaps and saved metric plans; local selections; real offline workflow initialization | Trusted delivery registration, current head, independent review receipts and native human-message provenance for formal selection |
| New outputs | Retained native completion collector and canonical saved-view adapters | Generic import-to-new-research completion and auto-attachment have not been demonstrated |
| Codex | Existing opt-in native transport/configuration is retained | No provider or valid research admission is shipped; this release does not claim arbitrary-topic research acceptance |
| Stages3–6 | Stage-specific material storage and explicitly labeled previews | Execution adapters |

The UI has no invented `/human-record` or loop-repeat endpoint. See
[#346](https://github.com/WenyuChiou/AutoResearchAgent/issues/346) and
[#348](https://github.com/WenyuChiou/AutoResearchAgent/pull/348) for the missing
contracts. Imported packet lineage is displayed as supplied, never inferred from
the fact that the user selected a project.

## Validate without research

Interface language and research-content language are separate. Optional reading
translations can be supplied with `--display-translations <local-json-file>`.
The format is `{"schema_version":1,"packets":[{"packet_file_sha256":"<sha256>",
"fields":[{"candidate_id":"<id>","version":1,"path":"candidate.question",
"source":"<exact original>","translations":{"zh":"...","en":"...","tw":"..."}}]}]}`.
Each translation is matched to the packet file hash, candidate version, field and
exact original value. Array translations must retain every item. Route cards,
trade-offs, review rationale and next-check text use the selected language;
translated fields expose the original in a collapsed disclosure. Unknown
translations are labeled instead of substituting a different topic's text.
Titles, direct quotations, original JSON and user notes remain verbatim. This
is display translation, not a new scientific judgment or automatic model call.
Keep actual delivery text and translations outside the public checkout.

```powershell
python -m unittest discover -s harness-ui -p "test_*.py" -v
python harness-ui/check_bundle.py
node harness-ui/test_route_language.cjs
```

These checks use the repository's explicitly synthetic Stage2 fixture and real
local Harness services. They cover original-byte/hash preservation, changed-source
rejection, project isolation, durable choices, workflow heads, HTTP authentication,
and fail-closed missing formal selection. They are not scientific evaluation.
CI repeats them on Windows, Linux and macOS. Browser acceptance remains a separate
manual check: Stage1 scope disclosure, packet selection, comparison restore,
project/stage isolation, reload and raw evidence access.

## Source organization

`renderer/` retains the reviewed linked layout and existing service consumers.
`stage2_display.*` and `v9-workbench.js` render generic packet data.
`manual_materials.py`, `materials_http.py`, `v9-materials.js` and
`v9-continuation.js` implement registration, persistence and verified projection.
`run_v9.py` composes these with the existing runtime. This is the first source-only
publication of that complete local layout; it deliberately excludes the historical
case-specific delivery modules, large vendor bytes and all local audit/data archives.
