# Research Wiki quick start (Windows, zero quota)

中文：[QUICKSTART.zh-CN.md](QUICKSTART.zh-CN.md)

Three steps from nothing to an open Wiki. **This is zero-quota mode: it connects no model and no Codex, runs no search, and never starts a research run on its own**, so it spends no quota. You need Windows PowerShell 5.1 (built in), Git and Python 3.11 or newer.

## 1. Clone and install the dependencies

```powershell
git config --global core.longpaths true
git clone https://github.com/WenyuChiou/AutoResearchAgent.git
cd AutoResearchAgent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r harness-ui\requirements.txt
.\.venv\Scripts\python.exe harness-ui\setup_vendor.py
```

The last line downloads the frontend dependency `three.core.js` and checks its pinned hash. Git ignores that file, so a fresh clone does not have it, and the Wiki cannot start without it. With no network, add `--from-file <an existing three.core.js>`.

## 2. Self-check (read-only)

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\doctor.ps1
```

Each line says "passed", or "not passed: reason; how to fix". While any required check fails, follow its fix and run the check again until the last line says all required checks passed. The check installs nothing and changes no system setting. Items marked frontend-test-only, real-run-only or advisory do not stop the Wiki from starting. The Codex item runs `codex --version` and `codex login status` (local state only: no model call, no search); add `-SkipCodex` to doctor to skip it. `Start-Wiki.ps1` already passes that switch when it calls doctor.

## 3. Start

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Open
```

The script creates the data directory (default `C:/ara`; use `-DataDir` for another short path), picks a free port, starts the Wiki and opens the browser. The first start takes roughly twenty to thirty seconds. Running it again never starts a second Wiki: if the same data directory already has one, the existing one is used.

- Dry run, starting nothing: add `-CheckOnly`.
- Stop: `powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Stop` (add the same `-DataDir` if you did not use the default).
- When the default port is busy the next free one is used and the program holding it is left alone. The script only stops the process that it started itself and can confirm is this project's Wiki.

Once it is open, type a title under "New research topic" on the home page and click "Create project".

## Limits

- The one-click script has zero-quota mode only; `-Real` stops with an error. For a real Stage 1 run, pass options straight to `harness-ui/run_v9.py` (`python harness-ui/run_v9.py --help` lists them): the query runtime and materials root, public sources, and the content model with Codex. These options only register things, they authorize nothing; every step is still authorized in the page, and automatic searching spends quota once enabled.
- At zero quota you can create a topic, write the scope and import an existing search plan, but you **cannot get literature**: without a search the ledger has no sources, and the "import a saved source package" entry does not exist yet.
- The script passes none of the Stage 2 or Stage 3 run configuration, so those stay off by default.
- The single entry point is `run_v9.py` (`Start-Wiki.ps1` is its one-click zero-quota start). The old launcher `run-project-workspace.py` is kept for compatibility only and is no longer recommended; options `run_v9.py` does not support are refused at start-up with an explanation.
- All project data lives in the data directory, outside the Git checkout. The path must stay short: `<data directory>/projects` may not exceed 60 characters, and the self-check tells you when it does.
- `Start-Wiki.ps1` uses `.venv` automatically when it exists; `-Python <path>` or the environment variable `ARA_PYTHON` selects another Python.
- Tested only on an existing Windows account, not on a clean new Windows account.
