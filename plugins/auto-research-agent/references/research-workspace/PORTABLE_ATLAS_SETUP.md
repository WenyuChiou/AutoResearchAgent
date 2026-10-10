# Run your own local Atlas review

Every teammate runs a complete review checkout on their own computer and uses
their own Codex account. Do not share `auth.json`, credentials, private research
payloads, configuration contents or another person's permits.

The [case launcher](atlas-launch-guide.md) opens repository synthetic Stage 1/2
examples with real saved-input Harness checks and review history. Those examples
are not a completed research run. The same UI can host a separately admitted local
Codex text session. A downloaded HTML file or another computer's localhost URL
cannot create that session.

Use Python 3.11, the pinned requirements and an installed native Codex executable:

```powershell
py -3.11 -m venv .venv
& .venv/Scripts/python.exe -m pip install -r plugins/auto-research-agent/requirements-test.txt
codex login
codex login status
```

Use a model available to your account; its explicit ID is never replaced silently.
Select the actual native `codex`/`codex.exe`, not an npm `.cmd` or JavaScript wrapper.
Installation and login follow [official CLI guidance](https://developers.openai.com/codex/cli)
and [authentication guidance](https://developers.openai.com/codex/auth).
The recorded actual Windows text roundtrip used CLI 0.153.0. Tests on other
platforms/versions do not substitute for actual account/protocol acceptance.

Build a fresh saved case outside every Git checkout. Replace the example data
path with your own existing private parent. This command builds files without
starting a server, Codex, model, search or judge:

```powershell
& .venv/Scripts/python.exe -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/ara-review-data/case-1
```

Prepare from that case. Replace the uppercase values with your own absolute paths
and deliberate model choice. If `CODEX_HOME` is set, select its `config.toml`;
otherwise select your own home `.codex/config.toml`. Missing/empty configuration
refuses without writing it. You may explicitly create a nonempty comment-only
configuration yourself when absent; never overwrite existing settings or copy auth.

```powershell
$repoRoot = (Get-Location).Path
$caseRoot = 'C:/ara-review-data/case-1'
$nativeExecutable = 'ABSOLUTE_PATH_TO_YOUR_NATIVE_CODEX_EXECUTABLE'
$ownConfig = 'ABSOLUTE_PATH_TO_YOUR_CODEX_HOME/config.toml'
$chosenModel = 'MODEL_ID_AVAILABLE_TO_YOUR_ACCOUNT'
$newBundle = 'C:/ara-review-data/text-session-1'
$pins = Get-Content -Raw "$caseRoot/fixture-receipt.json" | ConvertFrom-Json
$helper = "$repoRoot/plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py"
& .venv/Scripts/python.exe -B -X utf8 plugins/auto-research-agent/cli/research_workspace_native/atlas_local_prepare.py --repo $repoRoot --source-helper-sha256 (Get-FileHash $helper).Hash.ToLowerInvariant() --config $pins.config --config-sha256 $pins.config_sha256 --project-ref stage2 --brief brief.json --stage-inputs $pins.stage_inputs --stage-inputs-sha256 $pins.stage_inputs_sha256 --executable $nativeExecutable --executable-sha256 (Get-FileHash $nativeExecutable).Hash.ToLowerInvariant() --user-config $ownConfig --user-config-sha256 (Get-FileHash $ownConfig).Hash.ToLowerInvariant() --model $chosenModel --output $newBundle
```

Default returns `checked-only`: no output files or process. Read-only Git probes
from the original private-path checks remain enabled. All Host view roots, saved
stage roots and the repository are protected from output overlap. The bundle
folder must not exist, and its private parent must already exist.

To prepare a restricted text-session permit, repeat the same command with these
two additional arguments. They are explicit consent to this text scope only:

```powershell
--allow-text-session --accept-text-scope 'I allow a fresh local read-only Codex session with at most two text turns and a 600-second lease; no research, search, trading, or command/file approval.'
```

This writes four exclusive files: `byte-inventory.json`, `permit.json`,
`runtime-spec.json`, `launcher-argv.json`. Preparation never executes the argv,
creates a session database or sends a message. Launch explicitly within the
600-second permit expiry; a changed input, existing attempt or expired permit
refuses. Partial failed preparation remains saved and cannot be reused.

```powershell
$launchVector = @(Get-Content -Raw "$newBundle/launcher-argv.json" | ConvertFrom-Json)
$launcherArgs = $launchVector[1..($launchVector.Count - 1)]
& $launchVector[0] @launcherArgs
```

Keep that terminal running and open its printed localhost URL on the same
computer. The selected `stage2` view gets the admitted Codex session and both
saved Stage 1/2 checks. Other views remain separate; they do not inherit its
session. Send messages explicitly. Refresh and lost responses read history,
never automatically resend. The 600-second native lease stops the whole HTTP
host; inspect the retained cleanup receipt and journal after shutdown. A new
session requires a new explicit bundle and attempt.

The permit binds two text turns, 4096 text bytes, read-only/networkfalse, all
required denials and observed user MCP names. Denials are not proof that every
built-in tool is absent. Command/file approval Accept, automatic resume, research,
search, trading and scoring are not enabled. Actual native questions/approvals
were tested synthetically; the previous real smoke observed a text reply only.

Full Harness stage execution requires a separate confirmed research intake,
version-bound execution permit, tools and budget. Saved-case checks, real Codex
text, stage research completion and scientific improvement are separate states.
Remote public hosting also needs a separate authenticated access layer; this
launcher intentionally binds loopback rather than exposing credentials publicly.
