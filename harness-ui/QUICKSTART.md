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

Each line says "passed", or "not passed: reason; how to fix". While any required check fails, follow its fix and run the check again until the last line says all required checks passed. The check installs nothing and changes no system setting. Items marked frontend-test-only, real-run-only or advisory do not stop the Wiki from starting.

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

- Zero-quota mode only. A real-run mode (connecting Codex) is not provided yet; `-Real` stops with an error. The script passes none of the Stage 2 or Stage 3 run configuration, so those stay off by default.
- All project data lives in the data directory, outside the Git checkout. The path must stay short: `<data directory>/projects` may not exceed 60 characters, and the self-check tells you when it does.
- `Start-Wiki.ps1` uses `.venv` automatically when it exists; `-Python <path>` or the environment variable `ARA_PYTHON` selects another Python.
- Tested only on an existing Windows account, not on a clean new Windows account.
