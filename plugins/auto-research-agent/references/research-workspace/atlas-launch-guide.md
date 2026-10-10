# Launch the Atlas for review

Run the repository example to inspect Stage 1 and Stage 2 in a browser. It builds
new private outputs from existing public synthetic fixtures, verifies manifests,
and hosts them on `127.0.0.1`. No real paper payload, Codex process, model call,
search, protected source import, new source acquisition or session resume is required.

The optional [Stage 2 controller demo](STAGE2_REPOSITORY_DEMO.md) generates a new
synthetic workflow and delivery from an explicit UI action. Its fixed legacy
fixture is independent of the saved Stage 1 and ordinary daily_v3 scoring.

Use the complete final review branch, including every preceding review slice. Downloading a single HTML file omits required JavaScript and bundled assets.
These stacked review slices are not yet merged or accepted by the core team.
Existing native runtime guards remain enforced.

```powershell
git -c core.longpaths=true clone --config core.autocrlf=false --config core.longpaths=true --branch codex/atlas-stage2-demo-ui-20261010 https://github.com/WenyuChiou/AutoResearchAgent.git ara-review
Set-Location ara-review
```

The checkout keeps Git source bytes unchanged. Its local `core.autocrlf=false`
setting does not change your global Git preferences and also protects older
review assets without an explicit line-ending rule. A source-byte mismatch
remains a failure; do not bypass the source checks.

From the repository root, use Python with the plugin test requirements installed.
The [per-user setup guide](PORTABLE_ATLAS_SETUP.md) includes virtual-environment
installation; use that environment's Python for the following commands:

```powershell
& .venv/Scripts/python.exe -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/ara-review-data/attempt-1 --serve --harness-operations --open
```

Choose a new output directory outside every Git checkout. On Windows, use a short,
writable `TEMP`/`TMP` directory outside Git if the local environment requires it.
The command prints a loopback URL and `fixture-receipt.json`; keep the terminal
running and open that URL. Stop with Ctrl+C. A previous output is never overwritten.

With `--harness-operations`, each case has real repository operations:
validate the saved workspace, derive its conservative literature selection, and
export its literature files. It also registers saved Stage 1 checkpoint,
Stage 2 completion inspection and explicit review/hold/request-next actions.
Their outputs and history are retained in `attempt-1/harness-operations`,
`stage-results` and `stage-actions.sqlite3`; source snapshots remain unchanged. These are
saved-input functions, not searches, Stage 2 generation, scientific evaluation
or a native Codex session. The fixture launcher registers no native runtime.
`--stage-actions` serves only the stage actions without the literature operations.
The Stage 1 ledger and Stage 2 saved delivery are independent synthetic cases,
not an end-to-end research run. A successful checkpoint can still report blocked
readiness. Requesting the next stage records a request; it grants no execution
authority. Refresh/reconnect reads history without restarting operations.

To demonstrate a passing saved Stage 1 check, choose a separate new output:

```powershell
& .venv/Scripts/python.exe -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/ara-review-data/ready-case-1 --demonstrate-ready-saved-case --serve --harness-operations --open
```

This optional mode runs the existing public coverage fixture through the real
ledger and coverage gate. It preserves the reviewed work/version, claim IDs and
saved source references in the displayed paper and the checked input. It does
not substitute an unrelated paper into the view. The saved rounds have qualified
yields `1, 0, 0`; missing paper findings stay Unknown. These are synthetic saved
inputs, not retrieved literature, a complete Stage 1 delivery package or evidence
of scientific adequacy. Stage 2 remains an independent saved example; the receipt
does not claim continuous Stage 1-to-Stage 2 research lineage.

In the stage panel, choose a stage and press **Check this stage**. An attempt
marked completed means the saved-input function returned and its result was
recorded. Read **Latest stage check** separately: `pass` or `ready` means the
particular saved check passed; `blocked` or `incomplete` means the listed work
remains. A failed attempt preserves its error. An unknown outcome requires
**Read saved history**, rather than another submission. Inspect the full check
and output references, then enter a review reason and confirm its source version.
Changing stages clears that reason and confirmation. **Request next stage**
records a request only; it never starts research, authorizes a model call or
automatically feeds the independent Stage 2 fixture.

中文使用步骤：选择 Stage 1 或 Stage 2，点击「检查本阶段」。操作完成表示保存材料的
检查已结束并留下回执；还要看「本阶段最近检查」是否通过、受阻或交付未完整。
查看待处理事项、完整检查记录及产物位置后，再填写审阅理由并确认当前来源版本。
切换阶段会清空上一阶段的理由和确认，防止错用。「申请进入下一阶段」只记录申请，
不会自动开始研究、调用模型或执行下一阶段。结果未知时读取历史，不重复提交。
默认案例保留证据不足的受阻情况；新增选项展示保存的 synthetic 覆盖案例正常通过。
页面论文与该 Stage 1 ledger 使用同一作品、版本和保存来源；Stage 2 仍是独立示例。

The example writes an unconfirmed synthetic `brief.json` into each view root and
separately pins `stage-inputs.json` in `fixture-receipt.json`. These added inputs
are not attested by the original read-only view manifest and are not researcher
intake or research permission. Native preparation inventories them separately.
Use the [per-user setup guide](PORTABLE_ATLAS_SETUP.md) to prepare your own bounded
Codex text session. Keep saved-case checks and actual research execution separate.

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
$atlasReviewPython = (Resolve-Path .venv/Scripts/python.exe).Path
Set-Location plugins/auto-research-agent/cli
& $atlasReviewPython -B -X utf8 -m research_workspace_native.atlas_host --config C:/ara-review-data/attempt-1/host.json --config-sha256 <CONFIG_SHA256> --harness-operations-root C:/ara-review-data/attempt-1/harness-operations --harness-operations-reuse --open
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
This plain host reuse command reopens literature-operation history; it does not
register StageActions or a native session. The fixture's stage database is retained
separately. Rebuilding into the same output directory is refused.

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
