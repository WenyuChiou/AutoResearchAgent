# Research Studio deployment

Research Studio has a public static interface and a private, single-owner execution service. GitHub Pages can host the interface; it cannot run Python, Codex, or store research outputs. The owner still needs a Linux machine with persistent storage for execution. This change provisions no server, account, domain, credentials, or live deployment.

The interface supports Simplified Chinese, English, and Traditional Chinese. Stage 1 is the only execution adapter in this version. Stages 2–6 remain visible but disabled. A finished process, saved manifest, or green test is not scientific acceptance or a P1–P9 improvement.

The visual baseline is the original Research Studio proposal from PR #72: dark
sidebar, topic and language controls, stage input/output summary, a central
results-and-evidence canvas, artifact links, and a secondary run/review panel.
Keep this arrangement when adding features. Scope and timeout controls expand
inside the run panel; they must not replace the results canvas. The coverage
matrix remains visible with unknown-value placeholders until a structured
coverage adapter exists. File-type counts use actual artifacts and must never
be labeled as literature coverage or scientific quality. Do not restore the
proposal's sample papers, counts, or simulated execution as real output.

Review order is #73 (withdraw the unreviewed merge), #74 (execution core), #75
(authenticated API), then #76 (this interface and deployment). Withdrawing
the merge does not discard the original visual design. Contributors do not
merge this stack; the core team reviews each slice. The separate hosted preview
is for interface inspection and does not establish a live Harness deployment.

```text
Browser → GitHub Pages: HTML / CSS / JavaScript only
        → HTTPS API: owner token → Python service → native Codex
                                               → private persistent disk
```

## 1. Prepare the private Linux service

Use a dedicated, single-owner Linux host first. Containers require a separate on-host sandbox acceptance check; this PR does not supply or claim a tested container image. Do not use privileged containers, expose a Docker socket, or disable Codex sandboxing to make deployment pass.

Provision Python 3.11, Git, CA certificates, and the distribution's `bubblewrap` package. Linux sandbox operation depends on working user namespaces; resolve host policy using the [official sandbox prerequisites](https://developers.openai.com/codex/concepts/sandboxing), then test as the service account. A successful version command does not test sandbox execution.

Keep code, private files, and credentials separate:

```text
/opt/research-studio/harness/     clean dedicated clone, reviewed commit, read-only to service
/opt/research-studio/venv/        Python 3.11 environment, read-only to service
/opt/research-studio/codex/       native Linux Codex installation, read-only to service
/srv/research-studio/data/       private persistent run data and execution database
/srv/research-studio/codex-home/ dedicated authenticated Codex profile; private and writable
/srv/research-studio/tmp/        writable temporary files outside every Git checkout
/etc/research-studio/server.env root-owned service configuration, mode 0600
```

Clone `https://github.com/WenyuChiou/AutoResearchAgent.git` into the code directory and check out the exact reviewed, merged 40-character commit. Use a dedicated clone with its own `.git` directory. Do not deploy this unmerged working tree. Install the repository's pinned Python dependencies:

```sh
python3.11 -m venv /opt/research-studio/venv
/opt/research-studio/venv/bin/python -m pip install -r /opt/research-studio/harness/plugins/auto-research-agent/requirements-test.txt
```

These dependencies include the pinned research-hub revision; install them during provisioning, not during a run. Preserve the installed environment for each release. The service itself uses Python's standard HTTP server behind a reverse proxy.

Install the native Linux Codex executable from an [official release or standalone installation](https://github.com/openai/codex#installing-and-running-codex-cli). Select the host architecture, retain release metadata and the executable SHA-256, and preserve any companion resources. Use the real native executable at `/opt/research-studio/codex/codex`, not an npm JavaScript launcher or shell wrapper. No release version or image digest is guessed by this guide. Record and test the chosen version before accepting a deployment.

Create an unprivileged `research-studio` service account. Give it ownership of the three `/srv/research-studio/` subdirectories above with mode 0700; keep `/opt/research-studio/` administrator-owned. Authenticate only the dedicated profile, for example:

```sh
sudo -u research-studio env CODEX_HOME=/srv/research-studio/codex-home /opt/research-studio/codex/codex login --device-auth
sudo -u research-studio env CODEX_HOME=/srv/research-studio/codex-home /opt/research-studio/codex/codex login status
```

Device login depends on account/workspace availability. For automation, the [official authentication guide](https://developers.openai.com/codex/auth) recommends API-key login through stdin. Choose and provision one supported method yourself. A headless profile can use `cli_auth_credentials_store = "file"`; its `auth.json` is a secret and must stay outside Git, Pages, logs, and downloads. Codex credentials are separate from the Studio connection token.

Copy [server.env.example](deploy/server.env.example) to `/etc/research-studio/server.env`, fill the exact commit and origin, and create an independent random `ARA_STUDIO_TOKEN` of at least 32 characters. For example, generate it privately with Python `secrets.token_urlsafe(32)`. Protect the file with root ownership and mode 0600. Never put either token in a URL, frontend file, repository secret used by Pages, or an image layer.

Copy [research-studio.service](deploy/research-studio.service) into `/etc/systemd/system/`, inspect its paths, then use `systemctl daemon-reload` and `systemctl start research-studio`. Execution requires this dedicated systemd service with cgroup v2 supervision; an unavailable or unsafe scope must block execution. `ProtectControlGroups=true` and `Delegate=no` prevent the service from changing its cgroup boundary. The unit stops its entire control group and deliberately does not restart automatically. One data root must have only one service instance.

The CLI syntax used inside that supervised service is below. Starting it in an ordinary terminal does not establish the required execution scope:

```sh
PYTHONPATH=/opt/research-studio/harness/plugins/auto-research-agent/cli \
  /opt/research-studio/venv/bin/python -m research_studio \
  --data-root /srv/research-studio/data \
  --codex /opt/research-studio/codex/codex \
  --codex-home /srv/research-studio/codex-home \
  --expected-harness-sha "$ARA_HARNESS_SHA" --origin "$ARA_ORIGIN" \
  --host 127.0.0.1 --port 8765
```

Supply `ARA_STUDIO_TOKEN`, `TEMP`, `TMP`, and `TMPDIR` as in the unit; workers use the private `data/temp/` directory. Optional `--model` and `--reasoning` are administrator settings, not browser-supplied commands. The runner ignores personal Codex configuration; operator rule files remain active and their bytes are bound to each run. Authenticated `GET /api/status` checks readiness without a model call; submission repeats that check. Runtime checks bind the reviewed Harness and native executable bytes. Failed preflight blocks execution; do not turn that into a demo success state.

## 2. Connect HTTPS and Pages

Configure an administrator-managed HTTPS reverse proxy on a hostname such as `api.example.org`, forwarding to `127.0.0.1:8765`. Keep port 8765 private. Forward the `Authorization` and `Origin` headers; allow `OPTIONS` requests through; disable caching for `/api/`; never log authorization headers or response bodies. The API uses bearer authentication and exact-origin CORS. The proxy must not add a wildcard CORS policy. TLS, DNS, proxy limits, and external reachability require verification on the selected host.

For `https://wenyuchiou.github.io/AutoResearchAgent/`, the allowed origin is exactly `https://wenyuchiou.github.io`, with no repository path or trailing slash. Use the actual origin if a custom domain is configured. `--origin` may be repeated. Local development can use an explicit loopback HTTP origin; a public HTTPS page should connect to an HTTPS API.

The browser's connection panel takes the API base URL and the separate Studio token. The token stays in page memory and must be entered again after refresh. Public `static/config.js` may contain only the API URL. It must never contain authentication, research content, local paths, or generated outputs. Language selection changes interface labels, not original evidence bytes or filenames.

The optional [Pages workflow](../../../../.github/workflows/research-studio-pages.yml) is manual only. Before the first dispatch, a maintainer must:

1. Review and merge the PR, protect `main` with required review/checks, and select **GitHub Actions** as the Pages publishing source.
2. Configure the `github-pages` environment with required reviewers, prevent self-review, restrict deployment to `main`, and disallow administrator bypass. Required-reviewer availability depends on repository visibility and plan.
3. Dispatch **Research Studio Pages** on `main`, enter the public HTTPS API origin, inspect the artifact, and approve the environment deployment separately.

The YAML references that environment; it does not create its approval rules or prove that a commit was reviewed. Maintainers must verify those settings. The workflow copies only `index.html`, `studio.css`, `studio.js`, and a generated `config.js` from the static interface. It rejects links, missing/extra files, and invalid API URLs. It never uploads the checkout, database, run files, credentials, or paper sources. See [GitHub's Pages workflow guidance](https://docs.github.com/en/pages/getting-started-with-github-pages/using-custom-workflows-with-github-pages) and [environment protection rules](https://docs.github.com/en/actions/reference/workflows-and-actions/deployments-and-environments).

Publishing to this repository's Pages site replaces that site's existing deployment. Check for an existing site before dispatch; this workflow does not modify a separate personal website repository. There is no automatic deployment on push, PR, or merge.

## 3. Preserve research and verify deployment

The data directory holds `studio.sqlite3`, `server.lock`, private temporary files, and `runs/<uuid>/{request.json,prompt.txt,stdout.jsonl,stderr.txt,workspace/}`. Run requests, raw output, events, manifests, hashes, and artifacts remain tied to their run IDs. Raw logs are private execution evidence, not downloadable scientific artifacts. The execution database is not the canonical scientific ledger. Do not hand-edit files to change past outcomes, overwrite a run for a retry, or infer that arbitrary model files satisfy the researcher-deliverable contract. Keep failed and interrupted runs.

Use a persistent host disk, not an ephemeral container layer. Before backups, stop the service and confirm all worker processes exited; copy the entire data root together so database and files agree. Encrypt backups, keep dated versions on separate private storage, and test a restore into an isolated data root. Back up the Codex profile and server configuration separately with restricted access. Preserve the reviewed code commit, dependency lock, native binary hash, and deployment configuration alongside the backup inventory. Never publish this inventory if it contains private paths or secrets.

After an unexpected restart, inspect partial output and terminate surviving workers. Only then may an administrator start once with `--acknowledge-interrupted` to clear `reconciliation-required`; remove that flag for normal starts. Interrupted history remains. Never mark an interrupted run completed just to resume the interface. Roll back code only after preserving data; do not restore an old database over newer evidence.

Acceptance on the actual host must verify: unauthenticated API rejection; authenticated `/api/status`; allowed and rejected origins; native sandbox operation; one explicitly authorized Stage 1 run and its saved output hashes; stopping all native/tool descendants, including detached sessions; restart reconciliation; and backup/restore. A failed cgroup check or surviving worker must block further execution. Check the browser from its real Pages origin. The adapter rejects artifacts above 64 MiB and stops runs when monitored logs exceed 8 MiB. Provision disk monitoring and a quota for the entire private data root; these per-file checks do not bound total disk usage.

At PR preparation time no server, service credentials, TLS endpoint, Pages publication, container execution, or live research run has been established by this deployment guide. Local code checks do not replace those acceptance steps. Stages 2–6 and multi-user authorization remain outside this release.


## Stage conversation and owner decisions

The original results/evidence layout now includes **Stage conversation** and **Your actions**. Fill the topic at the top, ask a question, and answer Codex in the same text box. A structured `question` appears as an explicit waiting-for-answer callout. Select a saved conversation to restore it. Every send creates an immutable, independently supervised turn; retries reuse its request ID. The model receives the latest six turns, up to three explicitly selected UTF-8 artifacts (12,000 bytes each via API), and the latest five owner decisions, with a 96,000-byte context limit. Full history remains stored, with at most 100 turns per conversation. Start a new thread when the bound is reached.

The browser can attach the selected settled run's scope and manifest identity, plus one explicitly selected text artifact up to 12,000 bytes. File bytes are verified against their recorded hash; nothing is attached implicitly. Dialogue uses the configured native Codex executable, `read-only` sandbox, disabled web search and a strict output schema. It cannot authorize or automatically launch research. Stages 2–6 have discussion only. A model-generated question is a conversational request, not a suspended research worker: answering starts a separate discussion turn. Revised execution is an explicit new Stage 1 run.

**Confirm this scope** records the exact text independently of execution. The browser copies a Stage 1 confirmation into run settings; the owner still checks execution authorization and presses Run. A linked confirmation must match stage, topic and scope exactly. Existing API clients retain the prior explicit `scope_confirmed` contract. **Record review acceptance** and **Request changes** bind the selected run and manifest SHA-256. Requesting changes requires a note. These decisions do not alter the canonical scientific ledger, mark research complete, restart a run or advance a stage. Inspect files before accepting; hashes are byte identity, not scientific validation.

Authenticated endpoints added: `POST /api/dialogue/turns`, `GET /api/dialogue/threads?stage=N`, `GET /api/dialogue/threads/<uuid>`, `POST /api/decisions`, and `POST /api/decisions/query` (stage and topic in the body). `/api/runs` lists research runs separately. The existing private database and run directories preserve dialogue requests, prompts, events, output schema results and owner decisions. Backup the entire data root. Credential and exact-origin protections apply to every endpoint. No real model conversation or Linux deployment acceptance is claimed by synthetic tests.
