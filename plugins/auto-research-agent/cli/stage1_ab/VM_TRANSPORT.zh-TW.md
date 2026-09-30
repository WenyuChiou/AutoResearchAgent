# 分離 VM 的單一受試者傳輸與准入 v2

此介面為 implementation-only。離線測試執行合成 Python 程序，未啟動 VM、研究 subject 或模型。G1、Japan pilot、FREEZE_READY 與正式 A/B 的批准仍各自必要。

## 信任邊界

每個全新 guest 僅有自己的 subject profile、空 workspace、固定 public lock/prompt、自己的 runtime pin（僅 B）和唯讀 accepted 程式。B 保留完整 `stage1-literature`、`stage2-directions` inventory；研究任務只做 Stage 1。VM 不共享主機檔案或其他 guest 的資料。這個條件仍由現有 VM 隔離證據及實際部署檢查證明，程式無法由 JSON 證明不存在隱藏掛載。

Guest broker 以 root 運行；獨立 subject 帳戶沒有 sudo 能力。actual subject 的 native version/login/app-server/capture 程序都明確降權為 subject UID/GID；functional-skill 僅在獨立 diagnostic UID/GID 執行。所有程序清空附加群組，使用自己的 HOME/tmp。Observer 的歸檔寫入留在 broker；subject workspace、final output 的讀取與 runtime import probe 都降權。讀取 helper 的最小標準庫程式由 broker 透過 `python -I -B -c` 傳入，不開放 root-only treatment 原始碼給 A。B 的 workspace 初始化只傳入既有初始化函式，亦降權執行，避免 symlink race 變成 root 讀寫。即使 subject 在檢查後換成指向私有檔案的 symlink，核心的 UID 權限仍拒絕讀取。簽章 key、guest config、instance marker、probe、admission 與 captures 都在 root-owned 0700 目錄；key 為 root-owned 0600。Subject 無法自簽 probe 或准入。每次以 root 查詢 `sudo -n -l -U subject`，只有明確無任何 sudo grants 才通過；受限 Python grant 也拒絕。Broker source、interpreter 與祖先目錄必須 root-owned 且不能被其他帳戶寫入。

sudo policy 查詢固定使用 `LC_ALL=C`。只接受 exit 0 或 1、空 stderr，以及 stdout 完整一句 `User <實際帳號> is not allowed to run sudo on <本機 hostname>.`（可有一個結尾換行）。Hostname 必須等於核心回報的 hostname 或其 short form，不查 DNS。Debian 的成功 policy listing 可在沒有 grants 時回傳 0；這不是權限授予。其他帳號／主機、grant 清單、混合輸出、額外診斷或其他 exit status 全部拒絕。此修正源自保留的 proof-only guest 失敗；尚未重跑 Linux kernel proof，不把 parser 測試當成隔離通過。

Controller 是單一受信任操作者，持有每個 guest 不同的隨機 HMAC key；它不是對抗 controller 作假的硬體遠端認證。初始身份由操作者建立全新 VM 後核對：guest ID、配置原始 bytes hash、唯一 instance marker hash、實際 `/etc/machine-id` hash及 public lock hash。基底 clone 的 machine-id 可以相同，instance marker、config 和 key 必須每 guest 不同。SSH known_hosts 需預先核對，禁止自動接受未知 key。錯連 guest 時其獨立 key/config/instance 不匹配，即拒絕。

只有 controller 保存完整 ordered series 和先前 captures。Guest 收到的 request 欄位僅 version、action、自己的 identity、nonce、series ID、自己的 preflight hash；沒有 path/file 上傳介面。全體共用的 public lock 僅含公開計畫，沒有別人的 profile、workspace、答案、transcript、capture、evaluator/private 資料或 controller registry。

## 部署與配置

在每個 guest 的 root-only 程式目錄保存 accepted plugin/CLI；B 另安裝完全相同 plugin bytes 到自己的 Codex profile。將 root-only CLI 透過專用 interpreter 的 site-packages `.pth` 配置為可匯入，讓 `python -I -m stage1_ab.vm_guest` 能解析 accepted 程式；不要依賴環境 PYTHONPATH 或安裝另一版插件。所有檔案與設定完成後才能凍結對應 hashes。Provisioning 不在 transport 裡自動完成。

Public lock 由既有 `freeze-v3 ... --guest-adapter` 建立，額外綁定 `Stage1GuestTransport.v2` 及所有 adapter/runner/sequence 檔案 hashes。原 local API 保持原行為；帶 guest_adapter 的 lock 不允許偽造 local pair preflight。Observer 新增可選的降權 subprocess 參數，預設 local 執行不變，但 observer bytes 與 evaluator capture-module binding 改變，須重新凍結。不得重綁目前執行中的 G1。

既有 v3.1 evaluator 亦核對 lock 的 Codex binary hash、Python/hub executable 與 dependency paths。Linux subjects 的正式／pilot lock 不能拿去讓 Windows 原生 evaluator 冒充同一 runtime。可在獨立的私有 Linux evaluator 環境使用相同凍結 Codex bytes，並在該 evaluator 準備 spec/background 與 lock；Windows 僅作外部 transport controller。若需不同平台的 subject/evaluator binary，必須另行審查明確的 runtime split。此 adapter 不放寬該檢查，也不更動現有 Windows G1。

Guest config 精確欄位如下（路徑均為該 guest 自己的路徑）：

```json
{
  "kind": "Stage1GuestConfig.v2",
  "guest_id": "japan-a-unique-instance",
  "condition": "baseline",
  "repeat": 1,
  "instance_file": "/root/stage1/instance.txt",
  "machine_id_file": "/etc/machine-id",
  "profile": "/home/subject/.codex",
  "workspace": "/home/subject/workspace",
  "codex": "/usr/local/bin/codex",
  "lock": "/root/stage1/public-lock.json",
  "prompt": "/root/stage1/prompt.txt",
  "private_root": "/absent-evaluator-private-root",
  "runtime_pin": null,
  "state_root": "/root/stage1/state",
  "secret_file": "/root/stage1/key.bin",
  "native_user": "subject",
  "native_tmp": "/home/subject/tmp",
  "diagnostic": {
    "native_user": "diagnostic",
    "profile": "/home/diagnostic/.codex",
    "workspace": "/home/diagnostic/workspace",
    "native_tmp": "/home/diagnostic/tmp"
  }
}
```

B 改為 `condition=treatment` 並提供自己可讀、已凍結的 runtime pin path。每個 B repeat 均重新量測。Config、instance、key 的父目錄需 root-owned 0700。State 也是 0700；profile/workspace/tmp 屬 subject。Private root 必須確實不存在。

Controller plan 精確包含 `kind=Stage1GuestControllerPlan.v2`、本機 `lock`、outside-Git `registry_root`、按凍結順序排列的 `slots`。每個 slot 有：

- `identity`：guest_id、config_sha256、instance_sha256、machine_id_sha256、lock_sha256，以及 public lock 中自己的 repeat、condition、run_id、subject_id。
- `secret_file`：controller 私有的相應 guest key 路徑。
- `transport`：ssh executable、host（只接受 localhost/127.0.0.1）、port、user、identity_file、known_hosts、guest_python、guest_config。使用既有 OpenSSH；只允許安全的遠端 token，`shell=False`，不轉發 agent。

所有 controller 文件及回執留在私有目錄。Windows 必須以 filesystem ACL 限制其他使用者；POSIX key 另由程式檢查 owner/mode。不要把 key、SSH identity、profile、VM disk 上傳 Git 或交付 evidence ZIP。

## 操作順序與恢復

```text
python -m stage1_ab.vm_transport prepare CONTROLLER_PLAN
python -m stage1_ab.vm_transport capture CONTROLLER_PLAN
python -m stage1_ab.vm_transport fetch CONTROLLER_PLAN
python -m stage1_ab.vm_transport resume CONTROLLER_PLAN
```

先以每 guest 的 root broker 執行 `python -I -m stage1_ab.vm_lifecycle /root/stage1/config.json`。這是明確、不可重跑的 preparation 命令：B 使用獨立 diagnostic 帳戶進行一次 Sol/high skill read 模型呼叫；A 保留 discovery-only，零模型呼叫。它保存 start/stop、raw diagnostic evidence、signed receipt；失敗保留、禁止自動重試。成功記錄 duration、模型呼叫數、可得 token usage；cost 無資訊時明確 unknown。失敗若無法確定是否已呼叫則記錄 unknown，不能當零成本。這些都不進研究 subject transcript 或科學結果。

`prepare` 與 `capture` 的 actual-subject probe 固定為 `subject-non-model-v2`：只執行自己的 binary/login/config、native search/capability、完整 plugin discovery/bytes/skill file hash、runtime dependency 及隔離檢查，不呼叫 functional smoke。Controller 核對 `Stage1GuestPreflight.v2` 中分開的 actual evidence 與 `Stage1GuestLifecycle.v2` diagnostic receipt；matching runtime、相關非秘密設定、capabilities、plugin bytes、task/result 都需一致。Actual profile/config/guest identity 由原始 config hash 與 slot 綁定，diagnostic identity 不能代替。Capture/reverification 重新驗證這些非模型欄位與同一 signed receipt。原 local `probe_profile` 預設仍執行 functional probe，只有顯式版本化 guest 路徑改為非模型模式。

`capture` 僅准入下一個 slot，先持久保留 reservation 再傳送。Guest 驗證已認證 request、自己的實際配置與 runtime、不可重複 nonce、原 probe hash，才使用既有 capture/observer。它建立的是新的 single-guest admission，不是複製 host registry。每個 guest 用本機 exclusive lock；controller 同時用唯一 lock-by-public-lock-SHA anchor 和 atomic registry。換 plan/registry 目錄不能另建 series。

Capture 只傳回 `run.json` 與每個 attempt inventory 指定的 own capture files。Controller 先驗證 HMAC/request/guest identity、逐檔傳輸 hash和安全路徑，再保存新的不可覆寫 transfer archive，執行原 portable verification。所有先前完成 captures 也在 controller 重驗，僅 complete 才推進序列。原始不足、錯誤或未完成保留；不判定研究分數。

SSH 斷線不表示模型沒跑。Reservation 保留；先查 guest evidence。`fetch` 僅回傳當前保存 capture，不作模型呼叫，適合回覆遺失。`resume` 必須有已保存、不 complete、可信 thread ID 的同一 run，沿用既有 workspace/attempt 檢查。完成 run 不能 resume；nonce 重播拒絕。沒有可信 capture 的啟動中斷、stale busy directory 或 prepare 中斷不自動回收或換目錄，需保存現場並請 core 決定處置。

JSON 傳输會把自己的 capture files 編成 base64，在記憶體驗證後落盤；大型 captures 會有記憶體成本，尚無串流傳輸。傳輸失敗保存 stdout/stderr bytes 與 exit 記錄。它們仍是私有 evidence，不能公開貼出。

## 驗證範圍

`test_vm_transport.py` 另測受限 sudo grant、降權 helper、observer 不作 root source read 與 dependency import UID；涵蓋 real capture/observer/replay 的合成程序、錯 guest、過期 probe/response、重複准入、跨 guest 順序、swapped pin、傳輸 tamper/path traversal、回覆遺失、same-run resume、外部 controller 防重建及 outbound 欄位白名單。Native platform、帳戶及 probe 在跨平台測試裡隔離替換，測試不宣稱 Linux 身分隔離已重新 live 驗證。既有 native 雙臂準備證據仍只限 historical preflight；Japan 需在 accepted G1 及 reviewed adapter 之後實際執行。

## 全新 subject 與 diagnostic 的生命周期

Core PR65 comment-5902470413 明確要求這個分離。每個 pilot/formal arm/repeat 仍使用全新 VM/profile/workspace；historical preflight guest 與 pilot guest 不得用作 formal subject。允許同一 guest 中兩個完全分開、沒有 sudo grants 的 UID。

操作者須從 accepted 公開安裝 bytes 逐項建立全新 actual 與 diagnostic profile，僅配置 config.toml、auth.json 及 B 的完整 accepted plugin 安裝資料；不得複製使用過的 diagnostic profile、history、cache 或 outputs。兩個 home 及各自 profile/workspace/tmp 必須各自 UID-owned 0700；不可重疊或經 symlink 連結。Workspace/tmp 必須空，home cache 空或不存在；初始 profile 非 setup 檔案或 hardlink 被拒絕，原始檔案只記私有 hashes。安裝來源與 root provisioning 可信，程式不能由一個 hash 證明人為重新命名的惡意材料不是舊答案。

Broker 在原生 UID 下實測雙向不可讀／不可 traverse 對方 roots；shared 9p/virtiofs/CIFS/NFS mount 拒絕，root-only key/state 不得位於任何 native home。Diagnostic call 結束後，broker 停止該專用 UID 的所有剩餘程序，確認無程序並保留私有 artifacts；不得重啟該帳戶或再使用該 profile。每次 actual admission 再驗 UID/private permissions、不可跨讀、無 diagnostic 程序及 receipt HMAC。Root/操作者仍是信任邊界：不宣稱這能阻止 root 製造隱藏 namespace、變更權限或偷偷複製資料。只有實際 Linux 部署驗證可以確認 kernel 權限，Windows synthetic tests 不替代它。

`initial-setup.json`、`diagnostic-start.json`、`diagnostic-stop.json`、`diagnostic-evidence/`、`diagnostic-receipt.json` 全在 broker-private state。後續 app-server 的非模型探索可能寫 actual profile 自己的 cache/logs；那是記錄內的 setup 變化，不能宣稱整個 profile bytes 永遠 pristine，也不能混入 diagnostic files。B 的完整 `stage1-literature` / `stage2-directions` inventory 不變。

此版本改變 adapter/runner/evaluator capture-module bundle。須在 accepted head 重新綁定新 Linux private evaluator 與新 lock；不得把本版本塞進正在執行的 Windows G1。單一 Linux Codex binary hash gate 保持，不引入 runtime split。G1、adapter review/CI/merge、Japan 與 exact-digest FREEZE_READY 授權仍分別必要；本 PR 只交付 implementation-only。
