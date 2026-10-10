# Run the repository-content pilot in Atlas

This opt-in example connects real Codex app-server replies to the existing
Harness extraction, source checks, workflow snapshots, independent review roles
and partial delivery. It uses the two synthetic source texts already in the
repository tests. It does not establish a canonical Stage1 handoff, live search,
daily_v3 scientific assessment, Stage3 readiness or scientific improvement.

Use your own Codex installation and sign in with your own account. Do not share
another person's configuration, authentication files or local browser credential.
Install the Python dependencies described in the plugin README. Start this from a
complete checkout containing this PR stack; a standalone HTML file has no backend.

Example PowerShell setup (choose new private directories outside the checkout):

```powershell
$pilotRepo = (Get-Location).Path
$pilotCase = 'D:/rp/case1'
$pilotOutput = 'D:/rp/run1'
$pilotExample = Join-Path $pilotRepo 'plugins/auto-research-agent/references/research-workspace/examples'
python -X utf8 (Join-Path $pilotExample 'build-stage-run-case.py') --output $pilotCase
$pilotCaseFile = Join-Path $pilotCase 'case.json'
$pilotCaseSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $pilotCaseFile).Hash.ToLower()
$pilotCodex = 'C:/YOUR_PHYSICAL_INSTALL_PATH/codex.exe'
$pilotScope = 'I allow real Codex model calls on this bound repository case only, at most 8 turns and 900 seconds; no external search, trading, frozen inputs, command/file approval, private import or resume.'
python -X utf8 (Join-Path $pilotExample 'run-stage-pilot.py') --repo $pilotRepo --case $pilotCaseFile --case-sha256 $pilotCaseSha --model YOUR_OWN_AVAILABLE_MODEL --max-calls 8 --max-seconds 900 --permission-id YOUR_EXPLICIT_PERMISSION_REFERENCE --accept-scope $pilotScope --codex-executable $pilotCodex --output $pilotOutput --port 8770
```

Replace the model and permission reference with your actual accepted values;
the example does not infer authority from login, a role, a copied receipt or CI.
`--user-config` can explicitly select your own config. Otherwise it uses your own
`CODEX_HOME/config.toml`. `--prepare-only` verifies and records registration
without starting HTTP, a native process or a model. Ports are loopback only. A
port conflict is a failure, not permission to stop another service.

On Windows, create the short private parent (`D:/rp` in this example) first,
and choose a new output name for each separately authorized registration.
SQLite also creates a hashed owner database and journal below each model unit;
the launcher rejects an output whose longest physical owner/sidecar path reaches
240 Windows characters, before preparation, writes or model reservation.
Keep failed attempts and their budget reservations; shortening the path does not
reset the approved aggregate call/time budget or grant a retry.

Use the actual installed `codex.exe` binary's physical absolute path. A command
lookup can return a `.cmd`/`.ps1` wrapper, Windows alias, or path through a junction.
Those are not executable attestations for this launcher. Inspect the installation
and select its physical target; the existing linked-path refusal remains in force.
The pilot host uses a bounded 30-second HTTP deadline for source verification;
its connection cap and absolute deadline checks remain active.

On another operating system use the same Python scripts and arguments with that
computer's absolute checkout, private input/output, configuration and executable
paths. The example does not bypass the existing Linux Engine guards or assert
that all machines, accounts, model names or containment mechanisms are verified.

Open the printed local URL, choose Stage1 or Stage2 and scroll to
**Codex × Harness · run one step**. The original graph and source details remain.

1. Inspect the offered next step and click **Run this step**. A saved intent and
   aggregate reservation precede native execution. Only one unit is active.
2. Read its status and completed original reply. **validated** means that unit's
   native final/terminal evidence and applicable Harness checks passed. It does
   not mean the entire stage, research or scoring succeeded.
3. If Codex asks a native question, answer in the panel. Content-only authority
   permits declining/cancelling commands or file changes; it does not enable
   accepting them. Stop uses the active turn's server-bound interrupt reference.
4. Choose the next offered step explicitly. Refresh, another tab and a lost
   response only read saved progress; they never automatically resend work.
5. **Save current delivery** exports validated candidates and retained reviews
   through the actual Harness delivery builder. Download its current HTML;
   unresolved reviews, partial output and independent scoring remain pending.

This pilot retains nine semantic units: source review, ideation, extraction, two
independent reviewer replies and their extraction, synthesis and its extraction.
An eight-call budget cannot silently cover nine required units. A repair also
uses a separately reserved call. At the cap, keep the outputs and report the
remaining step; do not remove review or invent an assessment to declare success.
Time starts at the first reservation and includes native startup and model work.
Failed or interrupted attempts count conservatively as reservations; actual
usage/cost is recorded only when returned by the provider, otherwise Unknown.

**validation-failed** retains the original output and may offer one separate
repair within the same budget. **failed-or-unknown** or recovered unknown blocks
automatic continuation. **budget-pending** requires a separately authorized next
scope. Reopening the budget service preserves counts and unknown history; this
example intentionally requires a fresh output for registration, and cannot grant
resume/import authority or automatically recover an old native conversation.

All implementation changes are reviewed through PRs. The example never merges,
approves, resolves reviews, changes frozen rules or replaces the UI in production.
