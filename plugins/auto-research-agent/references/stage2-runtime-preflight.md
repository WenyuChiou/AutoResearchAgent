# Stage 2 functional runtime preflight

## Ordinary use: one research harness run

Use `Stage2ProductionRuntimeProbeSpec` (schema `1.0.0`) when a researcher runs
the harness alone. It uses the same expected settings and bound executor as
the older probe, and requires actual read, write, search and child-agent
evidence. Its `probes` contains exactly those four keys. It does not need an A
run, six paired runs, judge files, or expected-answer sentinels.

The reconstructed report is `Stage2ProductionRuntimePreflight`, with
`validation_scope=production-single`. Missing inventory information stays in
`observations`; malformed or mismatched supplied evidence still fails.
Effective-policy differences and failed or missing capabilities block the run.
The controller requires the explicit matching report and probe; it never
automatically changes a failed formal probe into a production probe.

Reuse a passed probe only while its profile, workspace, model, runtime and
configuration bindings still match. A changed setting requires the matching
probe to be checked again. General researchers may retain their authorized
skills and tools; preparing a clean evaluation profile is not mandatory for
ordinary use. Record the actual configuration rather than silently disabling
working research capabilities.

This report says `filesystem_read_isolation=not-assessed` and
`formal_ready=false`. A separate profile preserves context boundaries; it
does not prevent reading other files on the computer. Keep unnecessary files
out of the workspace and preserve the host's native permissions. The report
does not certify scientific quality or independent reviewer blindness.

## Course evaluation: additional isolation proof

Formal A/B retains the older `Stage2RuntimeProbeSpec`, its three denied-read
sentinels and complete inventory requirements. The formal validator rejects a
production-only report even when its four capabilities passed. It additionally
requires frozen conditions, calibration, pilots, six runs, independent judges
and required audits. These are evaluation requirements for our course claims,
not steps every researcher must repeat when using the harness.

A successful process exit proves that a process exited. It does not prove that
the research agent could read its sources, search, use a child agent, or remain
isolated from evaluator files. This adapter extends native capture; it does not
replace Codex tools or change the Stage 2 scientific rubric.

## Preparation and evidence

1. For formal comparison, use a new profile and a separate Git-root workspace for each subject. Do not
   change the user's personal configuration. Obtain native `skills/list` evidence
   before preparing the profile. A new `CODEX_HOME` alone does not suppress skills
   under the real user's `.agents/skills` directory.
2. `python -m stage2_live prepare-profile --destination NEW_HOME
   --skills-response RESPONSE.json --skills-sha256 SHA256 --output RECEIPT.json`
   disables discovered personal skills, retains bundled capabilities and enables
   the restricted-token Windows sandbox on Windows. The response must be complete
   and byte-bound. Install the research plugin only in treatment, then record the
   actual loaded inventories again.
3. Freeze harmless read, write, search and child probes. Keep the
   expected read nonce outside the prompt. Formal comparison additionally freezes
   isolation probes: record the existence and bytes of each
   judge/peer/expected-outcomes sentinel before execution. Save the exact read
   request fingerprint. Bind generated native event IDs after capture; the event
   IDs are lookup references, not a substitute for the pre-run probe requirements.
4. Execute through the native capture adapter, retaining its external receipt.
   When available, a host inventory receipt references the actual config, instruction, skills,
   plugin, MCP and tool responses. Active and disabled config layers differ.
   Unsupported or missing inventory evidence remains unknown.
5. `python -m stage2_live preflight --capture CAPTURE --receipt SHA256
   --probe PROBE.json --inventory-receipt INVENTORY.json --output REPORT.json`
   reconstructs the report from the capture and receipts. It checks the primary
   session's effective policy rather than trusting the requested CLI flags.
   Omit `--inventory-receipt` when ordinary production has no such evidence;
   the report records unknown inventory instead of inventing it.

## Production Code Mode witnesses

Some native tools run inside `exec`. The production decoder accepts one constant
`tools.exec_command` or `tools.web__run` call followed by `text(result)` or
`text(JSON.stringify(result))`, without executing the recorded JavaScript.
Expressions, extra actions and transformed or invented output are rejected.
Yielded cells require matching wait records and a successful native terminal.
Shell commands bind the actual executable, working directory and output, not
only the shell requested in the wrapper. Child proof binds the host spawn,
parent/child identities, native lineage and an assistant result. Formal legacy
proof rules remain unchanged.

## 中文操作重點

- 一般研究只跑一個 harness，不必先完成六次 A/B 或準備 judge 答案檔。
- 先查實際設定，再以原生日誌證明讀檔、寫檔、搜尋與子 agent 可用。
- 支援的環境資訊可用 [observe-runtime](stage2-runtime-observation.md) 保存；
  metadata 不等於完整工具清單，也不等於實體隔離證明。
- 原始紀錄與外部 hash 保留；設定或執行版本變更後重新核對，不能沿用舊通過旗標。
- 通過四項能力，只證明執行入口可用。完整研究預演與研究品質改善仍分別驗收。

### 第一次使用與之後恢復

第一次使用先保存環境 snapshot，再執行四項無敏感內容的能力 probe。
以 `Stage2ProductionRuntimeProbeSpec` 保存預先決定的模型、權限、shell
bytes、工作目錄、讀檔 nonce、寫檔預期 hash，以及實際原生 event IDs。
用 `preflight` 重建報告；把 `report`、`capture_dir`、外部 `receipt`、
`probe_spec` 和可為 `null` 的 `inventory_receipt` 傳給 controller 的
頂層 `preflight`，並為每個 profile／workspace 在 `execution_preflights`
建立對應紀錄。這兩個 per-execution 欄位必須一起提供：
`execution_preflights` 與 `execution_inventories`；沒有 inventory 時後者
的對應值填 `null`，不能省略整個欄位。controller 另需既有的 confirmed
brief hash、base snapshot hash、seed、native 設定及 workspaces。
per-execution 的 key 由現有 `preflight_for_environment` 規則計算：先把
home／workspace resolve 為絕對路徑，再對
`{"home": "RESOLVED_HOME", "workspace": "RESOLVED_WORKSPACE"}`
做 `stage2_common.canonical_hash`；兩個欄位使用相同 key。

| 看見的結果 | 可以做什麼 |
|---|---|
| `production-single`、`passed`、四項能力均通過 | 可進入一般研究的 controller；不是研究品質保證 |
| 任一能力 `failed` 或 `unknown` | 先修正該能力，保留原始失敗；不能手改通過旗標 |
| inventory `unknown`，四項能力通過 | 一般研究保留未知並可繼續；正式 A/B 仍被阻擋 |
| 提供了 inventory，但 hash 或 session 不符 | 先修正證據來源；不能當成沒有提供而忽略 |
| profile、workspace、模型、runtime 或設定改變 | 原紀錄不可直接沿用；重新核對對應的執行證據 |
| `formal_ready=false` | 不得用此報告聲稱正式 A/B 已可啟動 |

恢復會先重建並比對完成紀錄；證據仍相符時不重做模型呼叫。
一般使用者不用準備另一組輸出或評分答案。需要獨立 reviewer 的研究
步驟仍按 workflow 執行，這與用兩組比較 harness 效果是不同工作。

The exact Python contracts are documented in `cli/stage2_live/preflight.py`.
`verify_preflight` recomputes a report; editing a success flag does not pass it.
Missing records, a source mismatch, an absent child, a successful read of a
sealed sentinel, or a failed capability blocks the runtime gate. A missing file
does not demonstrate isolation. Echoing a denial sentence does not demonstrate
a policy rejection. Synthetic tests establish parser behavior only.

Read probes use the literal operation generated by `read_probe_command`: a
PowerShell .NET file read or an absolute `/bin/cat` read. Arbitrary shell programs,
including programs that print a denial and exit with an error, are rejected even
when their request hash matches. The read answer must not appear in the prompt,
profile, injected inputs, earlier context, or the read request. Inventory load
errors and unfinished pagination remain unknown. A blocked CLI report exits with
code 2; callers must inspect the reconstructed report as well as the exit code.
The probe spec also binds `executor` (shell path, SHA-256, family, and working
directory). Native capture must include the shell in `config_bindings.probe_shell`.
Read calls must be native command executions using that shell and workspace with
`login=false`; a foreign MCP result or an unbound shell cannot prove isolation.

## Observed Windows limitation

On the tested CLI 0.153.3, a fresh profile without Windows sandbox configuration
silently projected an explicit workspace-write request into read-only policy.
Enabling `windows.sandbox = "unelevated"` corrected the no-model startup response.
An independent Git root removed ancestor project instructions from that startup.
Neither change establishes functional success or read isolation.

The unelevated restricted-token implementation explicitly refuses deny-read
restrictions. The installed binary also rejects the newer `mxc` option found in
the repository source. Do not disable the sandbox, erase the deny-read requirement,
use a privileged container, or advertise formal readiness to get past this failure.
Use a supported, provisioned isolation environment and rerun the functional probes.
No OS accounts, administrative setup, or personal sandbox credentials are changed
by profile preparation.

This gate always leaves overall `formal_ready` false: calibration, complete pilots
and the separately frozen formal evaluation contract remain necessary. An earlier
archive-validator pass must not be retrospectively described as a runtime pass.
