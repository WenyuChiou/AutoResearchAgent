# Own-account project workspace

Each teammate runs this local portal on their own computer with their own Codex
installation, login and model access. No shared account, saved bearer, fixed
paper topic or private case path is included. The server listens on loopback;
this entry point does not publish an internet or LAN service.

## Start with models disabled

Use Python 3.11 or newer and the plugin's pinned
[test/runtime requirements](../../../requirements-test.txt) in your own
environment. Download the complete reviewed candidate. From its repository root,
create an environment once; these installation steps download dependencies,
but do not run research or Codex:

```powershell
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r plugins/auto-research-agent/requirements-test.txt
```

Use `.venv/Scripts/python.exe` in place of `python` in the launch commands below.
On macOS/Linux the same environment uses `.venv/bin/python` for installation
and launch. Keep the repository's dependency pins; do not substitute an
unreviewed research-hub version.

Choose a short
private project folder outside the Git checkout; its parent must already exist.
On Windows, for example, use `D:/rp/projects`.

The raw helper's SHA256 is an external input. Verify it against your reviewed
download/version; calculating it alone does not prove who published that version.
From the repository root, PowerShell can print the raw-file digest:

```powershell
(Get-FileHash plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py -Algorithm SHA256).Hash.ToLower()
```

Then run this command with that digest in place of `<helper-sha256>`:

```powershell
python plugins/auto-research-agent/references/research-workspace/examples/run-project-workspace.py --projects-root D:/rp/projects --source-helper-sha256 <helper-sha256> --open
```

`--check-only` validates paths, bytes and the fresh raw loader without opening the
project database or starting HTTP. `--prepare-only` constructs the real local
services without starting HTTP or Codex. Normal launch prints the local URL.
Do not import this entry into a process that has already imported the plugin.

## Optional own-account content planning

First install and log into Codex independently. Select a model your own account
can use. Supply the actual native `codex`/`codex.exe`, rather than a `.cmd`, `.ps1`
or shell wrapper, and your own Codex home containing `config.toml`. An absolute
executable path is recommended; a command name is resolved only if it identifies
the actual native executable. The entry point does not install Codex or probe
your login. Startup does not consume a model call.

```powershell
python plugins/auto-research-agent/references/research-workspace/examples/run-project-workspace.py --projects-root D:/rp/projects --source-helper-sha256 <helper-sha256> --enable-content-model --model <own-model> --codex <absolute-native-codex-path> --codex-home <own-codex-home> --open
```

Create a project with your own topic, review its scope/formal questions, and save
the answers. Declaring resource limits does not grant execution. The content
panel requires a separate explicit authorization for one version-bound call,
then a separate execute action. Topic suggestions remain researcher-reviewed
prose. A search-plan proposal is passed through the real confirmed-brief compiler
and retained as `plan-validated-not-executed`, or as a saved validation failure.
Neither action executes searches or acquires papers. Tool approvals permit only
decline/cancel. Failed/unknown calls and old input versions remain in history;
refresh or reconnect reads history instead of silently sending another call.

## Saved views and actual stage boundaries

Add `--views-config <absolute-json-path> --views-sha256 <raw-sha256>` to retain
existing pinned v6 Atlas views. Their saved data/identities stay separate from
new projects; a displayed saved case does not automatically become that project's
canonical Stage1 input.

The portal connects actual offline ResearchBrief/compiler and Stage1 ledger,
query-intent, checkpoint and export operations. External query execution remains
unconnected until a separate applicable execution adapter/permit exists. Stage2
can activate a trusted, separately registered canonical Stage1 package, preserving
its raw manifest/handoff/source hashes and researcher eligibility gate. Registration
is currently a trusted Python service interface, not a browser import or a CLI
path supplied by the browser. The default launcher registers no such package.

Content planning is not full Stage1/Stage2 native research. This entry does not
claim production create/resume, complete generation/extraction/independent judges,
scientific improvement, or an authenticated account before an actual authorized
run. Stage3–6 stay planned/unconnected. Private source inputs, Unknown evidence,
partial results, frozen subjects and paused evaluations retain their boundaries.
The older two-source pilot's separate 8-call/900-second cap is unchanged.

Windows model mode checks the actual shortened server-owned runtime path before
creating services: `projects-root/m/<24-hex>/n/<unit-64-hex>/` plus the original
SQLite owner/sidecar filename. The worst suffix adds 196 UTF-16 characters; the
complete path must stay under 240. Use a projects-root of at most 43 UTF-16
characters (for example `D:/rp/projects`). Full project, input, request, key and
source identities remain in the immutable runtime binding; the shortened folder
does not replace those hashes. Existing historical outputs keep their old paths.
A short-path preflight passes filesystem checks only, not actual Codex execution.
