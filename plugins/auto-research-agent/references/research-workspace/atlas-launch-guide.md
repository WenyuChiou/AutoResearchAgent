# Launch the Atlas for review

Run the repository example to inspect Stage 1 and Stage 2 in a browser. It builds
new private outputs from existing public synthetic fixtures, verifies manifests,
and hosts them on `127.0.0.1`. No real paper payload, Codex process, model call,
search, source import or session resume is required.

Use the complete final review branch, including every preceding review slice. Downloading a single HTML file omits required JavaScript and bundled assets.
A (#262) and B (#271) are merged. B adds saved-input Harness operations and
retains A's Wiki/Atlas, privacy and saved-source guards. Use a complete reviewed
main checkout and retain its exact commit. This fixture launcher is the
saved-view review host. The already merged ProjectHost root can also serve
explicitly registered views, as documented below; this does not claim acceptance
of Draft #295's native session or final Settings integration.

```powershell
git -c core.longpaths=true clone --config core.autocrlf=false --config core.longpaths=true --branch main https://github.com/WenyuChiou/AutoResearchAgent.git ara-review
Set-Location ara-review
```

From the repository root, use Python with the plugin test requirements installed:

```powershell
python -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/ara-review-data/attempt-1 --serve --harness-operations --open
```

Choose a new output directory outside every Git checkout. On Windows, use a short,
writable `TEMP`/`TMP` directory outside Git if the local environment requires it.
The command prints its actual loopback URL and `fixture-receipt.json`; keep the
terminal running and open that URL. The default chooses an available port, so a
previous `127.0.0.1:8770` address is not necessarily this process. Stop with
Ctrl+C. A previous output is never overwritten. Clone settings preserve physical
Git bytes for source binding and do not change global Git preferences.

The saved-view navigation is: printed `/` case chooser → `/views/stage1/atlas.html`
or `/views/stage2/atlas.html` → **Original workspace** (the same saved view's
`index.html`) → its Atlas link. The brand and current Settings label also link
to that legacy saved workspace; they are not the final project portal or an
editable settings page. Browser Back follows the pages already visited; after a
Wiki/Atlas round-trip it may return to the Wiki. Reopen the printed root URL to
return directly to the case chooser. The original index remains the pinned
saved package/reference view. The unique full-system
ProjectHost `/` is a separate merged portal entry; the final Settings/native
session integration remains separate acceptance work.

## Read an evaluated Stage 2 package in a canonical Wiki

For an already saved canonical WorkspaceIndex 1.1 or 1.2, use the existing Python
API from `plugins/auto-research-agent/cli`. Verify the externally retained index
bytes/hash first. `prepare_stage2_bridge(index, delivery_dir,
expected_manifest_sha256=...)` verifies the evaluated delivery and creates an
explicit reading association. Retain the canonical bridge bytes and their
external SHA-256 separately. Then call:

```python
from research_workspace.view import write_workspace

receipt = write_workspace(
    verified_index,
    reference_root,
    new_private_output,
    stage2_delivery=verified_delivery_root,
    stage2_bridge=verified_bridge,
    expected_stage2_bridge_sha256=external_bridge_sha256,
    atlas=True,
)
```

`reference_root` is `references/research-workspace` in the complete reviewed
checkout; its four frozen assets must match the renderer's `REFERENCE_HASHES`.
The output must be a new directory outside Git. The existing importer binds the
project, canonical index/version, external evaluated manifest and bridge, then
copies the verified artifacts and original evaluation comments without modifying
the index or either source package. Unknown, pending audit and technical failure
remain visible. A 3.0 index also retains its required source-rerun root binding.

The Stage 2 manifest receipt hashes canonical content excluding its own
`manifest_sha256` field; it is not the physical JSON file SHA-256. The bridge uses
canonical bytes. Host configuration and view manifest pins below use physical
file bytes. Do not interchange these values or downgrade an index version.

Register the resulting `view-manifest.json` in the existing views config:

```json
{
  "views": [{
    "ref": "saved-stage2",
    "label": "Saved Stage 2 results",
    "manifest": "C:/private-wiki/new-view/view-manifest.json",
    "sha256": "<external SHA-256 of that view-manifest file>",
    "fixture": false
  }]
}
```

Keep the config outside Git and retain its external physical SHA-256. From the
plugin CLI directory, start the already merged portal:

```powershell
python -B -X utf8 -m research_workspace_native.project_host --projects-root <PRIVATE_PROJECT_ROOT> --views-config <ABSOLUTE_CONFIG_PATH> --views-sha256 <EXTERNAL_CONFIG_SHA256> --port 0
```

Use the actual `url` printed by that process: root `/` serves `projects.html`.
Saved Results opens `/views/saved-stage2/atlas.html`, with the six stages at the
left. Stage 2 exposes comparison, directions, original comments and artifacts;
Stage 3–6 remain planned/unconnected. Original workspace returns to the same
frozen saved `index.html`, whose Atlas link returns to the Atlas. Browser Back
returns through the visited pages to the portal; this is not a new portal-back
button or a final Settings acceptance claim.

This reading association does not attest that Stage 2 originally used that
Stage 1 package. It keeps native canonical seed admission unconnected, human
selection pending and execution disabled. It does not start a research stage,
authorize Stage 3, rerun Stage 1, score research or require Draft #295. Supply the
latest real evaluated package and actual project/view bindings for real-package
acceptance; synthetic test success is implementation evidence only.

The retained historical r3 overlay was made by adding Atlas files to an older
Wiki. That old `index.html` has no forward Atlas link; use browser Back after
opening it. Its original package and hashes are preserved. Fresh outputs from
the launcher above include both navigation links. Public review evidence uses
repository synthetic fixtures and keeps private saved research notes out of the
published screenshots. See the [separate fixed-head A acceptance evidence](https://github.com/WenyuChiou/AutoResearchAgent/blob/1332583933dfdea2fd4377c570e7beb18a78fe04/review-evidence/wiki-A-acceptance-20261011/README.md)
for A commands, original bindings, screenshots and explicit remaining limits.
That A evidence is now retained in this candidate for review; it does not
establish a B runtime test result.

With `--harness-operations`, each case has three real repository operations:
validate the saved workspace, derive its conservative literature selection, and
export its literature files. The outputs and operation history are retained in
`attempt-1/harness-operations`; source snapshots remain unchanged. These are
saved-input functions, not searches, Stage 2 generation, scientific evaluation
or a native Codex session. The fixture launcher registers no native runtime.
It also registers a separate saved-stage action panel. The reopening command
below restores only the three Harness operations and their history; it does
not attach that separate stage-action service or launch a stage runtime.

The graph initially shows no relationships. Select a paper, direction or method
to reveal its direct connections; select it again to clear. Hover reads names
without expanding connections. The textual relationship basis follows the same
selection and hides again on clear. The 2D/3D views use the same rule.

The Stage 1 case contains two recorded versions and explicit metadata/Unknown
states. Stage 2 adds the existing structured-literature fixture, comparison
matrix, resource conditions, nine synthetic assessment rows and
retained Unknowns. These cases exercise presentation and bindings. Their scores
are synthetic, and the Stage 1–Stage 2 bridge is an explicit reading association,
not an attestation that this Stage 2 originally used that Stage 1 package.

To reopen saved outputs without rebuilding, read the `config` and
`config_sha256` printed in `fixture-receipt.json`, then run from the plugin CLI:

```powershell
Set-Location plugins/auto-research-agent/cli
python -B -X utf8 -m research_workspace_native.atlas_host --config C:/ara-review-data/attempt-1/host.json --config-sha256 <CONFIG_SHA256> --harness-operations-root C:/ara-review-data/attempt-1/harness-operations --harness-operations-reuse --open
```

The host snapshots only files listed by each pinned manifest. It has no arbitrary
filesystem route. Research records remain immutable; `host-binding.json` identifies
the served overlay separately. An unavailable Codex panel is the expected fixture
state. A static `file:///` page cannot own a server-side Codex session.

Reuse is explicit and requires the existing private directory and regular
`operations.sqlite3`. Every saved project/ref/input hash/output root must match
the pinned views; changed, dropped or added registrations are rejected. A new
server credential and process-held owner replace the closed owner. Existing
attempts and failures stay saved; unfinished attempts become `execution-unknown`.
Reading history does not recompute anything. A saved key never automatically
resubmits. Without `--harness-operations-reuse`, an existing root is rejected.

## Opt-in rendered navigation regression

The permanent `test_workspace_atlas_rendered.py` selector builds a fresh synthetic
Atlas export and checks keyboard navigation, phone navigation scrolling and page
containment at 1440, 768 and 390 pixels. Run it with the test requirements, Node.js,
an installed Playwright module and an installed Chromium browser available:

```powershell
$env:ATLAS_RENDERED_CHECK = '1'
# Set NODE_PATH if Playwright is installed outside the checkout's module tree.
# Set ATLAS_BROWSER_EXECUTABLE to an installed Chromium executable if needed.
python -B -X utf8 -m unittest discover -s plugins/auto-research-agent/tests -p test_workspace_atlas_rendered.py -v
Remove-Item Env:ATLAS_RENDERED_CHECK
```

Use `TEMP`/`TMP` outside Git as described above. This command does not install a
browser or dependencies. An explicitly selected check fails when a prerequisite
is missing. Ordinary CI reports a transparent skip and supplies no browser PASS.
Core owns the opt-in rendered acceptance and rechecks it when navigation or the
rendered selector changes. The earlier screenshot evidence remains applicable
only to unchanged page/style bytes and its recorded browser/viewports; it does
not attest to other browsers, physical touch devices or native execution.

# Attach an already admitted server session

Native conversation requires trusted application code to supply an existing ready
server-owned runtime. The plain host command and fixture launcher supply none.
An account/read connection check is separate and is not a persistent session.
Use the [existing host guide](codex-host.md) for that separately authorized check.

The embedding application must retain and verify the exact project ID, index hash,
input version, source root, controller/owner/epoch and owned process channel. It
must have applicable spawn/lifecycle/attach/message admission and resource bounds;
hashes and a permissive callback do not create authorization. The existing
`SessionOwners` registry adopts ready objects and starts one passive pump only on
an explicit call. It does not create or resume a thread by itself.

For the accepted current-main configuration path, trusted embedding code uses
`host_config.load_config`, `HostRegistry(runtimes={runtime_ref: runtime})` and
`create_host(config, registry=registry, credential=credential)`. A semantic
configuration must pin its external interface contract and schema and request
the same registered runtime reference. The views-only example is deliberately
disabled for native execution. Configuration
references resolve existing objects; they must not load arbitrary factories or
turn file paths into execution authority. The supplied runtime must match the
registered Atlas project/index. Successful host creation transfers shutdown
ownership; inspect its cleanup receipt. Real native/model acceptance remains a
separate evidence requirement.

The stage review choices prepare a conversation draft. They do not approve a
stage, grant a permit, select a research direction or start the next stage.
The generic session API exposes opaque `project_ref` and index/input bindings;
it keeps the controller's project identity private. Only the trusted Atlas host,
after matching its saved source to the registered runtime, supplies the public
`source_project_id` in its Atlas bootstrap. The bridge correlates that identity
with the current opaque session view and the saved Atlas index. An ordinary
session page without that explicit Atlas binding cannot accept a stage draft.
The bridge accepts only Stage 1–6, that matching source/index/input binding,
and nonblank valid UTF-8 text up to 16 KiB. Busy or unsettled actions block it.
After the draft appears, explicitly prepare the message and send it to the
admitted session. Refresh and reconnect read history without automatic resend.

The local `atlas-stage-review-draft` event has exactly `project_id`,
`index_sha256`, `stage`, `text` and `request_ref`. The last value is a process-local
`review-1`, `review-2`, etc., matching `^review-[1-9][0-9]*$`. The result event
echoes the project/index/request reference and stage with `accepted` and `reason`.
The review UI accepts only an acknowledgement matching its current request and
source binding; the acknowledgement is UI preparation, not a durable intent or
permission to run anything. Preparing this draft makes no HTTP or storage write.

Changing research content requires a new source version and appropriate recheck.
UI review, nine-row synthetic scoring, native message delivery, completed research
and scientific improvement are separate outcomes. Unknown, partial, audit-required
and evaluator failure remain visible.
