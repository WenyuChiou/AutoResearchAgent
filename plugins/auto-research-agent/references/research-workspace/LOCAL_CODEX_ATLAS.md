# Fresh local Codex Atlas

Use a complete review checkout with Python 3.11 and the pinned plugin requirements
installed. Each person installs Codex and signs in with their own account (`codex
login`, then `codex login status`). Do not copy another person's login files,
private project data, runtime spec or permit. Official authentication guidance:
https://developers.openai.com/codex/auth.

This is a bounded text-session adapter with saved-input Harness operations, not
a full research launcher. Windows has a recorded real text roundtrip; macOS and
Linux protocol tests are separate from real account/device acceptance. The tested
CLI is 0.153.0. Other versions must pass the actual protocol/policy checks; a
version string or model catalog alone does not establish compatible execution.

Run the direct script from your complete review checkout:

For a new local installation, use the [per-user preparation guide](PORTABLE_ATLAS_SETUP.md)
to create your own pinned bundle first. Preparation does not start Codex.

```powershell
python -B -X utf8 plugins/auto-research-agent/cli/research_workspace_native/atlas_local_launcher.py --enable-native --repo ABSOLUTE_CHECKOUT --config PRIVATE/host.json --config-sha256 CONFIG_SHA --spec PRIVATE/runtime-spec.json --spec-sha256 SPEC_SHA --permit PRIVATE/permit.json --permit-sha256 PERMIT_SHA --open
```

Replace every placeholder with the reviewed pin. Default is disabled and reads
no input. Module invocation is unsupported: it preloads owned package code.
The entrypoint raw-compiles two exact manifest-pinned helpers in a fresh process;
owned plugin imports also use raw hash-checked source, never owned cached pyc.

Use an existing private host allowlist, source index and source-bound ResearchBrief.
The production NativeAtlasRuntimeSpec v1 binds project/ref/index/input/root/exe,
an explicitly selected account model, `approval_policy: on-request`,
`principals: [local-viewer]`,
and a new `store_path: <attempt>/native/session.sqlite3`. Required `thread_config`
contains all 14 production DENIED_THREAD_CONFIG values plus observed user MCP
names disabled. Inherited CODEX_HOME/config.toml bytes are pinned; additional
project config layers are refused. These denials do not attest all built-in tools
are absent. Never copy auth or permit command/file approval Accept.

The selected model is part of the canonical spec/permit identity, lifecycle
parameters and every turn payload. It is not replaced automatically. Each account
must have access to that model; an unavailable model is an error, not a successful
connection. See https://developers.openai.com/codex/app-server.

An optional server-owned `handshake_timeout_seconds` (at most 120 seconds and
never longer than the existing process lease) separates the total four-step
handshake from its per-step I/O limit of at most 30 seconds. It must be included
in the exact spec/permit identity before startup; omitted fields retain the old
single total timeout. This does not increase message limits, turns or lease.

Explicit native hosting passes the spec's pinned request timeout (at most 30
seconds) to HTTP; other hosts keep the five-second default. Absolute accept-time
and pre-admission expiry checks still apply. Each passive source check has a
30-second readonly budget clamped to the process lease, including waits behind
full admission verification. Neither deadline grants write or model authority.
The UI distinguishes a ready process/thread from an observed saved assistant
reply; partial replies and stopped sessions retain their separate status.

Permit fields are exactly: kind=LocalCodexAtlasPermit, schema_version=1.0.0,
spec_identity_sha256, host_config, user_config, source_manifest, attempt_root,
brief_path, stage_inputs, stage_source_sha256, max_turns, lease_seconds, sandbox,
network_access, allow_fresh_session, allow_user_messages, expires_at_unix.
Each config/manifest is `{path,sha256}`; allow flags are literal true, sandbox is
read-only, network_access is false. Limits permit at most 2 text turn admissions,
600 seconds, 4096 text bytes, 1048576 stream bytes and 30-second I/O timeout.
Stage inputs retain saved Stage1 ledger_root and Stage2 delivery/evaluation roots
with manifest pins. Their production snapshot digest is bound; no search is started.
Inventory is LocalAtlasByteInventory with repo_root/source_root/plugin_files/source_files.
Spec identity hashes canonical spec without permit_sha256; complete permit is then
hashed into spec, and the CLI separately pins full spec bytes. This avoids circular hashes.

The owned stdout queue remains eight chunks with the existing total byte bound.
Backpressure waits at most 30 seconds within the lease for the same captured chunk,
checking close at most every 100ms; it does not repeat reads or native requests.

The launcher creates a fresh process/thread and starts a passive event pump only.
Each message is explicitly sent in the browser; no seed, resume or automatic retry.
Credentials remain in memory. The native lease stops the entire HTTP server,
so its URL is temporary. Restart requires a new attempt/store and explicit permit.
After shutdown inspect cleanup-receipt.json and retained session journal; a views-only
host can reopen saved results without claiming the expired native connection exists.

A pinned process and accepted account/thread schemas are observations, not process
authentication or Windows tree containment. Both attestation flags remain false.
Turn admission is not inference completion or completed research. A non-research
no-tool smoke requires its explicit prompt and examination of native item records.
Unknown I/O and cleanup stay unknown; independent stores are always closed.
External dependencies are not attested by the owned-source inventory.

The localhost URL printed at launch belongs to that running computer. Another
person launches their own checkout and opens their own printed URL. A downloaded
HTML file or the old URL from someone else's computer cannot start Codex. Remote
hosting needs a separate authenticated access layer over all page, bootstrap and
API routes; changing the bind address is insufficient. No public listener is
enabled by this adapter.

In the UI, Harness validation, literature selection/export, saved Stage 1
checkpoint, saved Stage 2 inspection and stage-review history call real repository
functions. They retain source versions, failures and output references. They do
not start literature searches, generate Stage 2 research, score with judges or
execute the next stage. Those research workflows need their own stage adapter,
confirmed intake, budgets and applicable execution permission. Stage 2's optional
Linux namespace lane and Windows process lane have different isolation limits;
passing the local chat test verifies neither lane's full research acceptance.

Offline: run unittest discover with pattern test_atlas_local_*.py. Byte drift,
exact gates, expiry, lifecycle, limits and failed cleanup tests never launch children.
