# Launch the Atlas for review

Run the repository example to inspect Stage 1 and Stage 2 in a browser. It builds
new private outputs from existing public synthetic fixtures, verifies manifests,
and hosts them on `127.0.0.1`. No real paper payload, Codex process, model call,
search, source import or session resume is required.

Use the complete final review branch, including every preceding review slice. Downloading a single HTML file omits required JavaScript and bundled assets.
Candidate A (#262) retains accepted main `347ae67a` and the reviewed Wiki/Atlas
assets. It is not yet merged or accepted by the core team. This candidate's
launcher is the saved-view review host below; the later ProjectHost/settings/
research-execution integration belongs to candidates B/C (#271/#295).

```powershell
git -c core.longpaths=true clone --config core.autocrlf=false --config core.longpaths=true --branch codex/atlas-selected-relation-basis-20261009 https://github.com/WenyuChiou/AutoResearchAgent.git ara-review
Set-Location ara-review
```

From the repository root, use Python with the plugin test requirements installed:

```powershell
python -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/ara-review-data/attempt-1 --serve --open
```

Choose a new output directory outside every Git checkout. On Windows, use a short,
writable `TEMP`/`TMP` directory outside Git if the local environment requires it.
The command prints its actual loopback URL and `fixture-receipt.json`; keep the
terminal running and open that URL. The default chooses an available port, so a
previous `127.0.0.1:8770` address is not necessarily this process. Stop with
Ctrl+C. A previous output is never overwritten. Clone settings preserve physical
Git bytes for source binding and do not change global Git preferences.

The A navigation is: printed `/` case chooser → `/views/stage1/atlas.html`
or `/views/stage2/atlas.html` → **Original workspace** (the same saved view's
`index.html`) → its Atlas link. The brand and current Settings label also link
to that legacy saved workspace; they are not the final project portal or an
editable settings page. Browser Back returns to the case chooser. A's index
remains the pinned saved package/reference view. The unique full-system
ProjectHost `/` and real settings entry are deferred to C, without adding C
functions to this candidate.

The retained historical r3 overlay was made by adding Atlas files to an older
Wiki. That old `index.html` has no forward Atlas link; use browser Back after
opening it. Its original package and hashes are preserved. Fresh outputs from
the launcher above include both navigation links. Public review evidence uses
repository synthetic fixtures and keeps private saved research notes out of the
published screenshots. See the [A acceptance evidence](../../../../review-evidence/wiki-A-acceptance-20261011/README.md)
for commands, original bindings, screenshots and explicit remaining limits.

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
python -B -X utf8 -m research_workspace_native.atlas_host --config C:/ara-review-data/attempt-1/host.json --config-sha256 <CONFIG_SHA256> --open
```

The host snapshots only files listed by each pinned manifest. It has no arbitrary
filesystem route. Research records remain immutable; `host-binding.json` identifies
the served overlay separately. An unavailable Codex panel is the expected fixture
state. A static `file:///` page cannot own a server-side Codex session.

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
The bridge accepts only Stage 1–6, a matching current server-read project/index,
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
