/* Research Studio: authenticated, single-owner API client. No sample research data. */
(() => {
  "use strict";
  const root = document.getElementById("research-studio-preview");
  const $ = (id) => document.getElementById(id);
  const locales = ["zh-Hans", "en", "zh-Hant"];
  const messages = {
    navigation: ["主要导航", "Main navigation", "主要導覽"], stages: ["研究阶段", "Research stages", "研究階段"], pipeline: ["研究流程", "RESEARCH PIPELINE", "研究流程"], myResearch: ["我的研究", "Research", "我的研究"], library: ["项目资料库", "PROJECT LIBRARY", "專案資料庫"], privateApi: ["私有研究 API", "PRIVATE RESEARCH API", "私有研究 API"], connectionLost: ["连接中断 · 执行已禁用", "Connection lost · Run disabled", "連線中斷 · 執行已停用"],
    workspace: ["工作台", "Workspace", "工作臺"], files: ["项目文件", "Project files", "專案檔案"], history: ["运行历史", "Run history", "執行紀錄"], connection: ["连接与访问", "Connection & access", "連線與存取"], language: ["界面语言", "Language", "介面語言"], singleOwner: ["单一所有者工作区", "Single-owner workspace", "單一擁有者工作區"],
    inputs: ["本阶段输入", "Stage inputs", "本階段輸入"], outputs: ["预期输出", "Expected outputs", "預期輸出"], execution: ["将执行什么", "What will run", "將執行什麼"], reviewGate: ["审核条件", "Review conditions", "審核條件"], runSetup: ["确认主题与研究范围", "Confirm topic and scope", "確認主題與研究範圍"], topic: ["研究主题", "Research topic", "研究主題"], scope: ["明确范围与约束", "Explicit scope and constraints", "明確範圍與限制"], topicPlaceholder: ["例如：强化学习交通信号控制", "For example: RL traffic signal control", "例如：強化學習交通號誌控制"], scopePlaceholder: ["说明研究问题、地区（或不限地区）、时间范围、来源和交付要求。", "Specify the question, geography (or unrestricted), time range, sources and required deliverables.", "說明研究問題、地區（或不限地區）、時間範圍、來源與交付要求。"], timeout: ["执行时限", "Execution timeout", "執行時限"], seconds: ["秒 · 60–3600", "seconds · 60–3600", "秒 · 60–3600"],
    costNotice: ["时限仅限制运行时间，不是费用上限。模型与工具费用由后端账户承担。", "The timeout limits wall-clock time, not spending. Model and tool charges belong to the backend account.", "時限僅限制執行時間，不是費用上限；模型與工具費用由後端帳戶承擔。"], scopeConfirmation: ["我确认以上范围，并授权在已连接的服务器执行本次 Stage 1。", "I confirm this scope and authorize this Stage 1 run on the connected server.", "我確認以上範圍，並授權在已連線的伺服器執行本次 Stage 1。"], run: ["确认并运行 Stage 1", "Confirm & run Stage 1", "確認並執行 Stage 1"], retry: ["重试同一次提交", "Retry the same submission", "重試同一次提交"], submitting: ["正在提交…", "Submitting…", "正在提交…"], stop: ["停止本次运行", "Stop this run", "停止本次執行"], stopping: ["正在请求停止…", "Requesting stop…", "正在請求停止…"],
    plannedView: ["输出展示预留", "Reserved output view", "輸出展示預留"], notIntegrated: ["尚未接入", "Not integrated", "尚未整合"], futureNotice: ["此阶段尚无执行接口。下列内容是预期输出类型，不是已生成结果。", "This stage has no execution adapter yet. These are expected output types, not generated results.", "此階段尚無執行介面；下列內容是預期輸出類型，不是已產生結果。"], runEvents: ["真实运行日志", "Run event log", "實際執行日誌"], openArtifacts: ["打开本次产物 →", "Open run artifacts →", "開啟本次產出檔案 →"], currentRun: ["当前运行", "Current run", "目前執行"], exitNotice: ["进程退出码 0 只进入待审阅，不代表科研完成、结论可信或产物通过审核。", "Exit code 0 means awaiting review. It does not establish research completion, reliable conclusions or approved artifacts.", "程序退出碼 0 僅代表待審閱，不表示研究完成、結論可信或產出通過審核。"],
    filesIntro: ["查看服务器实际保存的文件、内容哈希和运行来源。", "Inspect files actually saved by the server, their content hashes and producing runs.", "查看伺服器實際儲存的檔案、內容雜湊與執行來源。"], refresh: ["刷新", "Refresh", "重新整理"], producingRun: ["来源运行", "Producing run", "來源執行"], serverArtifacts: ["服务器产物", "Server artifacts", "伺服器產出檔案"], sourceLanguageNotice: ["界面切换语言不改写文件、日志、范围或来源内容。HTML 与 SVG 不在页面中执行。", "Language changes preserve files, logs, scope and source content. HTML and SVG are never executed in this page.", "介面切換語言不改寫檔案、日誌、範圍或來源內容；HTML 與 SVG 不會在頁面中執行。"], historyIntro: ["显示后端最近 100 次真实运行，包括失败、超时与中断。", "The backend's latest 100 real runs, including failures, timeouts and interruptions.", "顯示後端最近 100 次實際執行，包括失敗、逾時與中斷。"],
    connectionIntro: ["连接你控制的研究服务器。访问令牌只用于当前页面会话。", "Connect to a research server you control. The access token is held only for this page session.", "連線至你控制的研究伺服器；存取權杖僅用於目前頁面工作階段。"], apiUrl: ["API 地址", "API URL", "API 位址"], token: ["所有者访问令牌", "Owner access token", "擁有者存取權杖"], tokenNotice: ["令牌只保留在内存，不写入浏览器存储、链接、配置文件或下载地址。", "The token stays in memory and is never placed in browser storage, links, config files or download URLs.", "權杖僅保留於記憶體，不寫入瀏覽器儲存、連結、設定檔或下載位址。"], connect: ["连接服务器", "Connect", "連線伺服器"], disconnect: ["断开并清除页面数据", "Disconnect & clear page data", "中斷並清除頁面資料"], serverStatus: ["后端状态", "Backend status", "後端狀態"], hostingNotice: ["网页本身不提供计算。后端需要单独部署、配置模型账户，并允许此网页的精确 Origin。断开网页不会停止服务器任务。", "This page supplies no compute. Deploy the backend, configure its model account and allow this page's exact Origin. Disconnecting does not stop server jobs.", "網頁本身不提供運算；後端須另行部署、設定模型帳戶並允許此網頁的精確 Origin。中斷網頁不會停止伺服器任務。"], realDataNotice: ["只展示真实 API 数据 · 不生成演示结果", "Real API data only · No simulated results", "僅展示實際 API 資料 · 不產生示範結果"],
    disconnected: ["未连接服务器", "Disconnected", "尚未連線伺服器"], connecting: ["正在连接…", "Connecting…", "正在連線…"], connected: ["已连接", "Connected", "已連線"], ready: ["Stage 1 可执行", "Stage 1 available", "Stage 1 可執行"], blocked: ["执行受阻", "Execution blocked", "執行受阻"], connectFirst: ["连接服务器后才能运行和查看私有产物。", "Connect before running research or viewing private artifacts.", "連線伺服器後才能執行研究或查看私有產出檔案。"], activeExists: ["服务器已有活动任务，请先查看或停止该任务。", "The server already has an active run. Inspect or stop it first.", "伺服器已有活動任務，請先查看或停止該任務。"], noRun: ["尚未选择运行", "No run selected", "尚未選擇執行紀錄"], noHistory: ["后端暂无运行记录。", "No runs have been recorded by this backend.", "後端尚無執行紀錄。"], noArtifacts: ["本次运行尚未记录任何产物。", "No artifacts have been recorded for this run yet.", "本次執行尚未記錄任何產出檔案。"], selectFile: ["选择一个文件查看详情。", "Select a file to inspect it.", "選擇檔案以查看詳情。"], noEvents: ["正在等待后端事件。", "Waiting for backend events.", "正在等待後端事件。"], newestEvents: ["显示最近事件", "Showing recent events", "顯示最近事件"], created: ["已创建", "Created", "已建立"], queued: ["排队中", "Queued", "排隊中"], running: ["运行中", "Running", "執行中"], "human-review": ["待审阅", "Awaiting review", "待審閱"], failed: ["失败", "Failed", "失敗"], stopped: ["已停止", "Stopped", "已停止"], "timed-out": ["超时", "Timed out", "逾時"], interrupted: ["已中断", "Interrupted", "已中斷"], unknown: ["未知", "Unknown", "未知"],
    inspect: ["查看运行 →", "Inspect run →", "查看執行 →"], preview: ["预览内容", "Preview content", "預覽內容"], download: ["下载文件", "Download file", "下載檔案"], source: ["运行来源", "Run provenance", "執行來源"], path: ["服务器相对路径", "Server-relative path", "伺服器相對路徑"], size: ["文件大小", "File size", "檔案大小"], version: ["版本", "Version", "版本"], sha: ["记录的 SHA-256", "Recorded SHA-256", "記錄的 SHA-256"], verifyPending: ["未在浏览器核验字节", "Bytes not yet checked in this browser", "尚未在瀏覽器驗證位元組"], verifyPassed: ["下载字节与记录的哈希一致", "Downloaded bytes match the recorded hash", "下載位元組與記錄的雜湊一致"], hashNotice: ["哈希一致只验证文件字节，不证明研究结论正确。", "Matching hashes verify file bytes, not research conclusions.", "雜湊一致僅驗證檔案位元組，不證明研究結論正確。"], manifest: ["后端来源清单", "Backend provenance manifest", "後端來源清單"], sourceUnknown: ["后端未提供关联，不能推断上下游关系。", "The backend supplied no links; upstream or downstream relationships cannot be inferred.", "後端未提供關聯，不能推斷輸入或衍生關係。"], loading: ["正在读取并核验…", "Reading and verifying…", "正在讀取並驗證…"], previewUnavailable: ["此类型仅支持下载。文本预览限 2 MiB，PNG/JPEG 限 5 MiB。", "Download only. Text previews are limited to 2 MiB; PNG/JPEG previews to 5 MiB.", "此類型僅支援下載；文字預覽限 2 MiB，PNG/JPEG 限 5 MiB。"], artifactChanged: ["文件字节与记录的哈希不符，已阻止预览和下载。", "File bytes do not match the recorded hash. Preview and download were blocked.", "檔案位元組與記錄雜湊不符，已阻止預覽及下載。"],
    invalidUrl: ["请输入 HTTPS API 地址；HTTP 仅允许 localhost。地址不能包含令牌、用户名、查询参数或片段。", "Use an HTTPS API URL (HTTP only for localhost), without credentials, query parameters or fragments.", "請使用 HTTPS API 位址（HTTP 僅限 localhost），且不可包含帳密、查詢參數或片段。"], invalidInput: ["请填写主题、明确范围、60–3600 秒整数时限，并确认授权。", "Provide a topic, explicit scope, an integer timeout of 60–3600 seconds, and confirmation.", "請填寫主題、明確範圍、60–3600 秒整數時限，並確認授權。"], networkError: ["无法连接 API。检查服务器、HTTPS、精确 Origin 和网络。", "Cannot reach the API. Check the server, HTTPS, exact allowed Origin and network.", "無法連線 API；請檢查伺服器、HTTPS、精確 Origin 與網路。"], unauthorized: ["访问令牌无效或已失效。请重新连接。", "The access token is invalid or expired. Reconnect.", "存取權杖無效或已過期，請重新連線。"], forbidden: ["服务器拒绝此网页来源或访问权限。", "The server rejected this page's Origin or access.", "伺服器拒絕此網頁來源或存取權限。"], apiError: ["API 请求失败", "API request failed", "API 請求失敗"], malformed: ["API 返回了不兼容的数据。", "The API returned incompatible data.", "API 回傳不相容的資料。"], uncertainSubmit: ["提交结果未确认。重试会使用同一 request_id，避免重复启动。也可刷新运行历史。", "Submission outcome is unknown. Retrying reuses the same request_id to avoid duplicate starts. You can also refresh history.", "提交結果尚未確認；重試會沿用同一 request_id，避免重複啟動，亦可重新整理執行紀錄。"], tooLarge: ["浏览器下载上限为 64 MiB。", "Browser downloads are limited to 64 MiB.", "瀏覽器下載上限為 64 MiB。"],
    stage1: ["文献发现与证据", "Literature discovery & evidence", "文獻探索與證據"], stage2: ["文献比较与研究缺口", "Literature comparison & gaps", "文獻比較與研究缺口"], stage3: ["研究设计与可行性", "Research design & feasibility", "研究設計與可行性"], stage4: ["实验执行", "Experiment execution", "實驗執行"], stage5: ["分析与图表", "Analysis & figures", "分析與圖表"], stage6: ["写作与投稿", "Writing & submission", "寫作與投稿"],
    goal1: ["围绕已确认的研究范围查找文献，并保留原始执行和文件记录。", "Research the confirmed scope while retaining actual execution and artifact records.", "依已確認的研究範圍查找文獻，保留實際執行與檔案紀錄。"], goal2: ["统一比较已有研究，形成有来源支持的缺口判断。", "Compare studies consistently and identify source-backed gaps.", "以一致標準比較既有研究，形成有來源支持的缺口判斷。"], goal3: ["将问题变成可执行且有验证条件的研究方案。", "Turn the question into a feasible, testable research plan.", "將問題轉為可執行且具驗證條件的研究方案。"], goal4: ["执行批准后的实验并保留成功、失败与重试。", "Execute approved experiments and retain successes, failures and retries.", "執行核准後的實驗，保留成功、失敗與重試。"], goal5: ["从原始结果生成可追溯的分析与不确定性图表。", "Create traceable analyses and uncertainty figures from raw results.", "由原始結果產生可追溯的分析與不確定性圖表。"], goal6: ["把论文主张连接到已审阅的文献、实验和图表。", "Connect manuscript claims to reviewed literature, experiments and figures.", "將論文主張連結至已審閱的文獻、實驗及圖表。"],
    in1: ["主题、明确范围、时限与授权", "Topic, explicit scope, timeout and authorization", "主題、明確範圍、時限與授權"], in2: ["审阅后的文献与证据", "Reviewed literature and evidence", "審閱後的文獻與證據"], in3: ["研究问题、数据与资源", "Research question, data and resources", "研究問題、資料與資源"], in4: ["已批准的方案与配置", "Approved plan and configuration", "已核准的方案與設定"], in5: ["原始结果与评价方案", "Raw results and evaluation plan", "原始結果與評估方案"], in6: ["审阅后的结论、图表与引用", "Reviewed conclusions, figures and citations", "審閱後的結論、圖表與引用"],
    out1: ["实际文件、执行日志、哈希清单", "Actual files, execution logs and hash manifest", "實際檔案、執行日誌與雜湊清單"], out2: ["比较矩阵 / 缺口报告 / 证据链", "Comparison matrix / Gap report / Evidence links", "比較矩陣 / 缺口報告 / 證據鏈"], out3: ["实验计划 / 基线设计 / 预算", "Experiment plan / Baselines / Budget", "實驗計畫 / 基準設計 / 預算"], out4: ["任务队列 / 原始结果 / 失败日志", "Task queue / Raw results / Failure logs", "任務佇列 / 原始結果 / 失敗日誌"], out5: ["结果表 / 图表 / 不确定性分析", "Result tables / Figures / Uncertainty analysis", "結果表 / 圖表 / 不確定性分析"], out6: ["论文草稿 / 引用检查 / 投稿包", "Manuscript / Citation checks / Submission package", "論文草稿 / 引用檢查 / 投稿資料包"],
    exec1: ["后端启动已配置的 Stage 1 worker，保存真实事件与其实际产物。", "The backend starts its configured Stage 1 worker and records real events and resulting artifacts.", "後端啟動已設定的 Stage 1 worker，保存實際事件與其產出檔案。"], execFuture: ["适配器尚未接入；此页面不会启动该阶段。", "The adapter is not integrated; this page cannot start this stage.", "適配器尚未整合；此頁面不會啟動此階段。"], gate1: ["核对来源、范围覆盖、文件与未解决问题。当前界面不替代研究审阅。", "Review sources, scope coverage, files and unresolved questions. This UI does not perform research review.", "核對來源、範圍涵蓋、檔案與未解問題；目前介面不取代研究審閱。"], gateFuture: ["在适配器接入后，依据证据完整性与本阶段标准单独审阅。", "Once integrated, review evidence completeness and the stage's criteria separately.", "適配器整合後，依證據完整性與本階段標準個別審閱。"]
  };
  Object.assign(messages, {
    attachText: ["可选：附带一个文本产物（最多 12 KB）", "Optional: attach one text artifact (up to 12 KB)", "可選：附上一個文字產出檔案（最多 12 KB）"], noAttachment: ["不附带文件内容", "Do not attach file contents", "不附上檔案內容"],
    dialogueTitle: ["本阶段对话 · Codex", "Stage conversation · Codex", "本階段對話 · Codex"], newDialogue: ["新对话", "New conversation", "新對話"], savedDialogues: ["已保存的对话", "Saved conversations", "已儲存的對話"], answerHere: ["在这里回答或提问", "Answer or ask here", "在這裡回答或提問"], answerPlaceholder: ["回答上方问题，或补充研究要求…", "Answer the question above or add research requirements…", "回答上方問題，或補充研究要求…"], sendDialogue: ["发送给 Codex", "Send to Codex", "傳送給 Codex"], attachRun: ["附带当前运行的范围与来源记录", "Include the selected run's scope and provenance", "附上目前執行的範圍與來源紀錄"], yourActions: ["待你处理", "Your actions", "待你處理"], scopeDraft: ["1 · 编辑并确认研究范围", "1 · Edit and confirm scope", "1 · 編輯並確認研究範圍"], useSuggestion: ["填入 Codex 建议", "Use Codex suggestion", "填入 Codex 建議"], confirmScope: ["确认此范围", "Confirm this scope", "確認此範圍"], reviewNote: ["2 · 审阅意见（退回修改时必填）", "2 · Review notes (required for changes)", "2 · 審閱意見（退回修改時必填）"], acceptReview: ["记录审阅通过", "Record review acceptance", "記錄審閱通過"], requestChanges: ["退回修改", "Request changes", "退回修改"], decisionHistory: ["确认与审阅记录", "Scope and review history", "確認與審閱紀錄"], awaitingAnswer: ["待你回答", "Your answer is needed", "待你回答"], confirmedScope: ["已确认范围", "Confirmed scope", "已確認範圍"], noDecisions: ["暂无确认或审阅记录。", "No scope or review decisions yet.", "尚無確認或審閱紀錄。"], dialogueHelp: ["每次发送调用后端 Codex；保留全部对话，模型读取最近 6 轮。讨论不会启动研究。", "Each send calls backend Codex. All turns are saved; the model reads the latest 6. Discussion does not start research.", "每次傳送呼叫後端 Codex；保留全部對話，模型讀取最近 6 輪。討論不會啟動研究。"], dialogueUnavailable: ["连接支持阶段对话的 Harness 服务器后，可在此回答 Codex。", "Connect a Harness server with stage conversations to answer Codex here.", "連線支援階段對話的 Harness 伺服器後，可在此回答 Codex。"], decisionBoundary: ["确认范围不会启动任务。审阅记录绑定当前产物版本，不自动推进下一阶段，也不替代科研验证。", "Scope confirmation does not launch work. Review records bind the artifact version; they neither advance stages nor replace research validation.", "確認範圍不會啟動任務。審閱紀錄綁定目前產出版本，不自動推進下一階段，亦不取代研究驗證。"], noDialogue: ["先填写顶部研究主题，再开始对话。", "Enter a research topic above, then start a conversation.", "先填寫頂部研究主題，再開始對話。"], scopeRequired: ["请先在“待你处理”中确认与本次执行完全一致的范围。", "First confirm the exact execution scope in Your actions.", "請先在「待你處理」中確認與本次執行完全一致的範圍。"], reviewSelected: ["审阅当前运行", "Review selected run", "審閱目前執行"], you: ["你", "You", "你"], confirm_scope: ["确认范围", "Scope confirmed", "確認範圍"], accept_review: ["审阅通过记录", "Review acceptance recorded", "審閱通過紀錄"], request_changes: ["要求修改", "Changes requested", "要求修改"],
    resultsEvidence: ["结果与证据", "Results & evidence", "結果與證據"], fixedStageView: ["每个阶段都有固定展示位置", "A dedicated view for every stage", "每個階段皆有固定展示位置"], runStage: ["运行本阶段", "Run this stage", "執行本階段"],
    view1: ["文献覆盖概览", "Literature coverage overview", "文獻涵蓋概覽"], view2: ["比较矩阵与研究缺口", "Comparison matrix & research gaps", "比較矩陣與研究缺口"], view3: ["研究设计蓝图", "Research design blueprint", "研究設計藍圖"], view4: ["实验任务与运行轨迹", "Experiment tasks & execution trace", "實驗任務與執行軌跡"], view5: ["结果分析与不确定性", "Analysis & uncertainty", "結果分析與不確定性"], view6: ["论文结构与证据关联", "Manuscript structure & evidence", "論文結構與證據關聯"],
    awaitingResults: ["等待研究结果", "Awaiting research results", "等待研究結果"], coveragePending: ["预留展示 · 尚无结构化覆盖数据，横线表示未知，不是零。", "Reserved view · No structured coverage data yet. Dashes mean unknown, not zero.", "預留展示 · 尚無結構化涵蓋資料；橫線表示未知，而非零。"], direction: ["研究方向", "Research area", "研究方向"], method: ["方法", "Methods", "方法"], evaluation: ["评估", "Evaluation", "評估"], reproduction: ["复现", "Reproduction", "重現"],
    evidenceFiles: ["证据与产物", "Evidence & artifacts", "證據與產出"], inspectEvidence: ["查看证据 →", "Inspect evidence →", "查看證據 →"], evidencePending: ["来源、原文位置与核验记录将在产物中查看。", "Inspect sources, locators and verification records in the output files.", "於產出檔案中查看來源、原文位置與核驗紀錄。"], outputTypes: ["本次文件类型 · 不代表文献覆盖率", "Run file types · Not literature coverage", "本次檔案類型 · 不代表文獻涵蓋率"],
    short1: ["文献与证据", "Literature & evidence", "文獻與證據"], short2: ["比较与缺口", "Comparison & gaps", "比較與缺口"], short3: ["设计与可行性", "Design & feasibility", "設計與可行性"], short4: ["实验执行", "Experiments", "實驗執行"], short5: ["分析与图表", "Analysis & figures", "分析與圖表"], short6: ["写作与投稿", "Writing & submission", "寫作與投稿"],
    goal1: ["建立可追溯的文献池，让研究判断连接到原文证据。", "Build a traceable literature collection and connect research decisions to source evidence.", "建立可追溯的文獻池，讓研究判斷連結至原文證據。"],
    out1: ["文献表、证据报告、原始记录", "Literature tables, evidence reports, original records", "文獻表、證據報告、原始紀錄"]
  });
  const state = { locale: "zh-Hans", view: "work", stage: 1, base: "", token: "", connected: false, connecting: false, reachable: false, status: null, runs: [], run: null, events: [], cursor: 0, artifacts: [], manifest: null, artifactId: null, preview: null, verified: new Set(), submitting: false, stopping: false, pending: null, notice: null };
  const controllers = new Set(), objectUrls = new Set();
  let generation = 0, selection = 0, pollTimer = null, previewSerial = 0, lastStatusAt = 0;
  const t = (key) => Object.hasOwn(messages, key) ? messages[key][locales.indexOf(state.locale)] : key;
  const node = (tag, className, text) => { const element = document.createElement(tag); if (className) element.className = className; if (text !== undefined) element.textContent = String(text); return element; };
  const text = (value) => typeof value === "string" ? value : "";
  const isRecord = (value) => value !== null && typeof value === "object" && !Array.isArray(value);
  const active = (run) => run && ["queued", "running"].includes(run.status);
  const usableRun = (run) => isRecord(run) && typeof run.id === "string" && run.id.length > 0 && run.id.length <= 200;
  const validArtifact = (file) => isRecord(file) && typeof file.id === "string" && typeof file.path === "string" && Number.isSafeInteger(file.size) && file.size >= 0;
  const sizeLabel = (bytes) => bytes < 1024 ? `${bytes} B` : bytes < 1048576 ? `${(bytes / 1024).toFixed(1)} KiB` : `${(bytes / 1048576).toFixed(1)} MiB`;
  const statusLabel = (status) => typeof status === "string" && Object.hasOwn(messages, status) ? t(status) : typeof status === "string" ? `${t("unknown")} (${status})` : t("unknown");
  const dateLabel = (value) => { const date = new Date(typeof value === "number" ? value * 1000 : value); return Number.isFinite(date.getTime()) ? date.toLocaleString(state.locale) : text(value) || "—"; };
  const extension = (path) => path.split(".").pop().toLowerCase();
  const filename = (path) => path.split(/[\\/]/).pop() || "artifact";
  function notify(key, detail = "") { state.notice = { key, detail }; renderNotice(); }
  function renderNotice() { $("notice").hidden = !state.notice; $("notice").textContent = state.notice ? t(state.notice.key) + (state.notice.detail ? ` ${state.notice.detail}` : "") : ""; }
  function clearPreview() { previewSerial++; for (const url of objectUrls) URL.revokeObjectURL(url); objectUrls.clear(); state.preview = null; }
  function clearConnection(clearInputs = true) {
    resetInteraction();
    generation++; selection++; clearTimeout(pollTimer); pollTimer = null;
    for (const controller of controllers) controller.abort(); controllers.clear(); clearPreview();
    Object.assign(state, { token: "", connected: false, connecting: false, reachable: false, status: null, runs: [], run: null, events: [], cursor: 0, artifacts: [], manifest: null, artifactId: null, submitting: false, stopping: false, pending: null, notice: null }); lastStatusAt = 0;
    state.verified.clear(); $("access-token").value = "";
    if (clearInputs) { $("topic").value = ""; $("scope").value = ""; $("scope-confirmed").checked = false; }
  }
  function baseUrl(raw) {
    let url; try { url = new URL(raw); } catch { throw new Error(t("invalidUrl")); }
    const local = ["localhost", "127.0.0.1", "[::1]"].includes(url.hostname);
    if ((url.protocol !== "https:" && !(url.protocol === "http:" && local)) || url.username || url.password || url.search || url.hash) throw new Error(t("invalidUrl"));
    return url.href.replace(/\/+$/, "");
  }
  async function api(path, { method = "GET", body, binary = false } = {}) {
    const current = generation, controller = new AbortController(); controllers.add(controller);
    const timeout = setTimeout(() => controller.abort(), binary ? 120000 : 20000);
    try {
      const headers = { Authorization: `Bearer ${state.token}` }; if (body !== undefined) headers["Content-Type"] = "application/json";
      const response = await fetch(state.base + path, { method, headers, body: body === undefined ? undefined : JSON.stringify(body), credentials: "omit", cache: "no-store", redirect: "error", referrerPolicy: "no-referrer", signal: controller.signal });
      if (current !== generation) throw new DOMException("Stale connection", "AbortError");
      if (!response.ok) { let detail = ""; try { detail = text((await response.json()).error).slice(0, 500); } catch {} const error = new Error(`${t(response.status === 401 ? "unauthorized" : response.status === 403 ? "forbidden" : "apiError")} (${response.status})${detail ? ": " + detail.replaceAll(state.token, "[redacted]") : ""}`); error.httpStatus = response.status; throw error; }
      const result = binary ? await response.arrayBuffer() : await response.json();
      if (current !== generation) throw new DOMException("Stale connection", "AbortError");
      return result;
    } catch (error) {
      if (current !== generation) throw new DOMException("Stale connection", "AbortError");
      if (error.httpStatus) throw error;
      const networkError = new Error(t("networkError")); networkError.networkFailure = true; throw networkError;
    } finally { clearTimeout(timeout); controllers.delete(controller); }
  }
  function handleError(error) { if (error.name === "AbortError") return; if (error.httpStatus === 401) { clearConnection(); notify("unauthorized"); } else { if (error.networkFailure && state.connected) { state.reachable = false; if (state.status) state.status = { ...state.status, available: false, reason: error.message }; lastStatusAt = 0; } notify("apiError", error.message); } render(); }
  async function refreshRuns() { const data = await api("/api/runs"); if (!isRecord(data) || !Array.isArray(data.runs)) throw new Error(t("malformed")); state.runs = data.runs.filter(usableRun).slice(0, 100); }
  async function refreshStatus() { const data = await api("/api/status"); if (!isRecord(data) || typeof data.available !== "boolean" || !Array.isArray(data.stages)) throw new Error(t("malformed")); state.status = data; state.reachable = true; lastStatusAt = Date.now(); }
  async function loadRun(id, reset = false) {
    const currentSelection = reset ? ++selection : selection;
    if (reset) { state.run = state.runs.find(run => run.id === id) || { id, status: "unknown" }; state.events = []; state.cursor = 0; state.artifacts = []; state.manifest = null; state.manifestSha = null; state.artifactId = null; clearPreview(); render(); }
    const data = await api(`/api/runs/${encodeURIComponent(id)}?after=${state.cursor}`);
    if (currentSelection !== selection || !state.run || state.run.id !== id) return;
    if (!isRecord(data) || !usableRun(data.run) || data.run.id !== id || !Array.isArray(data.events) || !Array.isArray(data.artifacts) || !Number.isSafeInteger(data.cursor) || data.cursor < state.cursor) throw new Error(t("malformed"));
    const becameTerminal = active(state.run) && !active(data.run);
    state.run = data.run;
    const known = new Set(state.events.map(event => event.seq));
    for (const event of data.events) if (isRecord(event) && Number.isSafeInteger(event.seq) && event.seq >= 0 && !known.has(event.seq)) { state.events.push({ seq: event.seq, type: text(event.type), text: text(event.text).slice(0, 8192), created_at: typeof event.created_at === "number" ? event.created_at : text(event.created_at) }); known.add(event.seq); }
    state.events = state.events.slice(-1000); state.cursor = data.cursor; state.artifacts = data.artifacts.filter(validArtifact);
    state.manifest = isRecord(data.manifest) ? data.manifest : null;
    state.manifestSha = data.manifest_sha256 || null;
    if (!state.artifacts.some(file => file.id === state.artifactId)) { state.artifactId = state.artifacts[0]?.id || null; clearPreview(); }
    if (becameTerminal) await refreshStatus();
    render();
  }
  function schedulePoll() {
    clearTimeout(pollTimer); if (!state.connected) return;
    const current = generation;
    pollTimer = setTimeout(async () => { try { if (Date.now() - lastStatusAt >= 30000) await refreshStatus(); await refreshRuns(); if (state.run) await loadRun(state.run.id); else render(); } catch (error) { handleError(error); } finally { if (current === generation) schedulePoll(); } }, 3000);
  }
  function backendReady() { return state.connected && state.reachable && state.status?.available === true && state.status.stages.some(stage => stage.id === 1 && stage.enabled === true) && !state.status.active_run_id; }
  function canRun() { return backendReady() && state.stage === 1 && !state.submitting; }
  function render() {
    root.lang = state.locale; document.documentElement.lang = state.locale; $("language").value = state.locale;
    root.querySelectorAll("[data-i18n]").forEach(element => { element.textContent = t(element.dataset.i18n); });
    root.querySelectorAll("[data-placeholder]").forEach(element => { element.placeholder = t(element.dataset.placeholder); });
    root.querySelectorAll("[data-aria]").forEach(element => { element.setAttribute("aria-label", t(element.dataset.aria)); });
    for (const view of ["work", "files", "history", "connection"]) $(`${view}-view`).hidden = state.view !== view;
    root.querySelectorAll("[data-view]").forEach(button => button.classList.toggle("active", button.dataset.view === state.view));
    $("breadcrumb").textContent = t(state.view === "work" ? "workspace" : state.view);
    $("connection-button").textContent = t(state.connecting ? "connecting" : state.connected ? state.reachable ? "connected" : "connectionLost" : "disconnected");
    $("connection-button").classList.toggle("warm", !state.connected || !state.reachable);
    $("connect-button").disabled = state.connecting; $("disconnect-button").disabled = !state.connected && !state.connecting;
    $("refresh-history").disabled = !state.connected; $("refresh-files").disabled = !state.connected || !state.run;
    $("server-status").textContent = t(!state.connected ? "disconnected" : state.status?.available ? "ready" : "blocked"); $("server-reason").textContent = state.connected ? text(state.status?.reason) : "";
    $("footer-status").textContent = state.connected ? state.base : t("disconnected");
    renderStages(); renderWorkspace(); renderHistory(); renderFiles(); renderNotice(); renderInteraction();
  }
  function renderStages() {
    for (const id of ["stage-nav", "mobile-stages"]) {
      const buttons = [];
      for (let stage = 1; stage <= 6; stage++) { const button = node("button", id === "stage-nav" ? "rs-stage" : ""); button.type = "button"; button.classList.toggle("active", state.stage === stage); button.setAttribute("aria-pressed", String(state.stage === stage)); if (id === "stage-nav") button.append(node("span", "rs-stage-num", stage)); button.append(node("span", "", `${id === "mobile-stages" ? stage + " " : ""}${t("short" + stage)}`)); button.addEventListener("click", () => { state.stage = stage; state.view = "work"; render(); }); buttons.push(button); }
      $(id).replaceChildren(...buttons);
    }
    $("stage-kicker").textContent = `STAGE 0${state.stage} / 06`; $("stage-title").textContent = t("stage" + state.stage); $("stage-goal").textContent = t("goal" + state.stage); $("stage-inputs").textContent = t("in" + state.stage); $("stage-outputs").textContent = t("out" + state.stage); $("stage-execution").textContent = t(state.stage === 1 ? "exec1" : "execFuture"); $("stage-gate").textContent = t(state.stage === 1 ? "gate1" : "gateFuture");
    $("stage-availability").textContent = t(state.stage > 1 ? "notIntegrated" : !state.connected ? "disconnected" : state.status?.available ? "ready" : "blocked"); $("run-settings").hidden = state.stage !== 1; $("run-button").hidden = state.stage !== 1;
    renderResults();
  }
  function renderResults() {
    const current = state.stage === 1 && state.run, files = current ? state.artifacts : [];
    $("result-title").textContent = t("view" + state.stage);
    $("result-label").textContent = t(state.stage === 1 ? "awaitingResults" : "notIntegrated");
    const visual = $("stage-visual"); visual.replaceChildren();
    if (state.stage === 1) {
      const table = node("table", "rs-coverage-table"), head = node("tr"), body = node("tbody");
      for (const key of ["direction", "method", "evaluation", "reproduction"]) { const cell = node("th", "", t(key)); cell.scope = "col"; head.append(cell); }
      const thead = node("thead"); thead.append(head); table.append(thead);
      for (let row = 1; row <= 3; row++) { const tr = node("tr"), label = node("th", "", `${t("direction")} ${row}`); label.scope = "row"; tr.append(label); for (let col = 0; col < 3; col++) tr.append(node("td", "", "—")); body.append(tr); }
      table.append(body); const caption = node("caption", "", t("coveragePending")); table.append(caption); visual.append(table);
    } else {
      const placeholder = node("div", "rs-placeholder"), blueprint = node("div", "rs-blueprint");
      blueprint.append(...t("out" + state.stage).split(" / ").map(label => node("span", "", label)));
      placeholder.append(blueprint, node("p", "", t("futureNotice"))); visual.append(placeholder);
    }
    if (files.length) {
      const groups = new Map(); for (const file of files) { const type = extension(file.path); groups.set(type, (groups.get(type) || 0) + 1); }
      const chart = node("div", "rs-output-chart"); chart.append(node("p", "rs-section-label", t("outputTypes")));
      for (const [type, count] of Array.from(groups).sort((a, b) => b[1] - a[1]).slice(0, 6)) { const row = node("div", "rs-output-row"), meter = node("meter"); meter.min = 0; meter.max = files.length; meter.value = count; meter.setAttribute("aria-label", `${type} ${count} / ${files.length}`); row.append(node("span", "", type.toUpperCase()), meter, node("span", "", count)); chart.append(row); } visual.append(chart);
    }
    $("evidence-summary").textContent = files.length ? files.slice(0, 2).map(file => filename(file.path)).join(" · ") : t("evidencePending");
    $("open-evidence").disabled = !files.length; $("open-artifacts").disabled = !current;
    $("artifact-summary").textContent = current ? `${state.run.id} · ${files.length} ${t("files")}` : t("noRun");
  }
  function renderWorkspace() {
    for (const id of ["topic", "scope", "timeout", "scope-confirmed"]) $(id).disabled = state.submitting;
    $("topic-history").replaceChildren(...Array.from(new Set(state.runs.map(run => text(run.topic)).filter(Boolean)), topic => { const option = node("option"); option.value = topic; return option; }));
    $("run-button").disabled = !canRun(); $("run-button").textContent = t(state.submitting ? "submitting" : state.pending ? "retry" : "run");
    $("run-blocker").textContent = !state.connected ? t("connectFirst") : state.status?.active_run_id ? t("activeExists") : !state.status?.available ? text(state.status?.reason) || t("blocked") : "";
    $("current-run").replaceChildren(); $("status-timeline").replaceChildren();
    if (!state.run || state.run.stage !== state.stage) $("current-run").append(node("p", "rs-empty-run", t("noRun")));
    else { $("current-run").append(node("p", "rs-run-id", state.run.id), node("span", "rs-badge blue", statusLabel(state.run.status)), node("p", "rs-source-text", state.run.topic)); for (const status of ["created", "running", "human-review"]) { const item = node("span", "", t(status)); item.classList.toggle("active", status === "created" || state.run.status === status); $("status-timeline").append(item); } if (state.run.error) $("current-run").append(node("p", "rs-source-text", state.run.error)); }
    $("stop-button").disabled = !state.connected || state.run?.stage !== state.stage || !active(state.run) || state.stopping; $("stop-button").textContent = t(state.stopping ? "stopping" : "stop");
    $("execution-panel").hidden = !state.run || state.stage !== 1; $("event-count").textContent = `${t("newestEvents")} · ${state.events.length}`;
    $("event-log").replaceChildren(...(state.events.length ? state.events.map(event => { const row = node("div", "rs-event"); row.append(node("div", "rs-event-meta", `${event.seq} · ${event.type} · ${dateLabel(event.created_at)}`), node("pre", "", event.text)); return row; }) : [node("p", "rs-empty", t("noEvents"))]));
    renderResults();
  }
  function renderHistory() {
    $("history-list").replaceChildren();
    if (!state.connected || !state.runs.length) { $("history-list").append(node("p", "rs-empty", t(state.connected ? "noHistory" : "connectFirst"))); return; }
    for (const run of state.runs) { const row = node("div", "rs-history-row"), identity = node("div", "rs-history-id", run.id), description = node("div", "rs-history-desc"); identity.append(node("small", "", dateLabel(run.created_at))); description.append(node("strong", "", run.topic), node("p", "rs-source-text", run.scope)); const button = node("button", "rs-button", t("inspect")); button.type = "button"; button.addEventListener("click", () => { state.stage = 1; state.view = "work"; loadRun(run.id, true).catch(handleError); }); row.append(identity, description, node("span", "rs-badge", statusLabel(run.status)), button); $("history-list").append(row); }
  }
  function renderFiles() {
    $("file-run").replaceChildren(node("option", "", t("noRun"))); $("file-run").firstChild.value = "";
    for (const run of state.runs) { const option = node("option", "", `${run.id} · ${text(run.topic)}`); option.value = run.id; $("file-run").append(option); }
    if (state.run && !state.runs.some(run => run.id === state.run.id)) { const option = node("option", "", state.run.id); option.value = state.run.id; $("file-run").append(option); } $("file-run").value = state.run?.id || ""; $("file-run").disabled = !state.connected;
    const groups = new Map(); for (const file of state.artifacts) { const type = extension(file.path); groups.set(type, (groups.get(type) || 0) + 1); } $("file-groups").textContent = Array.from(groups, ([type, count]) => `${type.toUpperCase()} × ${count}`).join(" · "); $("file-count").textContent = state.artifacts.length;
    $("file-list").replaceChildren();
    if (!state.connected || !state.run || !state.artifacts.length) $("file-list").append(node("p", "rs-empty", t(!state.connected ? "connectFirst" : !state.run ? "noRun" : "noArtifacts")));
    for (const file of state.artifacts) { const button = node("button", "rs-file-row"), main = node("span", "rs-file-main"), name = node("span"); button.type = "button"; button.classList.toggle("active", file.id === state.artifactId); button.setAttribute("aria-pressed", String(file.id === state.artifactId)); name.append(node("span", "rs-file-name", filename(file.path)), node("span", "rs-file-sub", file.path)); main.append(node("span", "rs-file-icon", extension(file.path).toUpperCase().slice(0, 5)), name); button.append(main, node("span", "rs-file-origin", sizeLabel(file.size))); button.addEventListener("click", () => { state.artifactId = file.id; clearPreview(); renderFiles(); }); $("file-list").append(button); }
    renderFileDetail();
  }
  function renderFileDetail() {
    const file = state.artifacts.find(item => item.id === state.artifactId), panel = $("file-detail"), sourceOpen = panel.querySelector("details")?.open; panel.replaceChildren();
    if (!file) { panel.append(node("p", "rs-empty", t("selectFile"))); return; }
    panel.append(node("h3", "rs-inspector-title", filename(file.path)));
    const actions = node("div", "rs-action-row"); for (const mode of ["preview", "download"]) { const button = node("button", "rs-button", t(mode)); button.type = "button"; button.disabled = state.preview?.loading === true; button.addEventListener("click", () => readArtifact(file, mode).catch(handleError)); actions.append(button); } panel.append(actions);
    const meta = node("dl", "rs-file-metadata");
    for (const [key, value] of [["path", file.path], ["size", sizeLabel(file.size)], ["version", String(file.version ?? "—")], ["producingRun", state.run?.id || "—"], ["sha", file.sha256 || "—"]]) meta.append(node("dt", "", t(key)), node("dd", "", value)); panel.append(meta, node("p", "rs-file-foot", t(state.verified.has(`${state.run?.id}:${file.id}:${file.sha256}`) ? "verifyPassed" : "verifyPending")), node("p", "rs-file-foot", t("hashNotice")));
    if (state.preview?.fileId === file.id) { if (state.preview.loading) panel.append(node("p", "rs-file-foot", t("loading"))); else if (state.preview.imageUrl) { const image = node("img", "rs-artifact-image"); image.src = state.preview.imageUrl; image.alt = filename(file.path); panel.append(image); } else if (state.preview.text !== undefined) panel.append(node("pre", "rs-source-preview", state.preview.text)); else if (state.preview.message) panel.append(node("p", "rs-file-foot", t(state.preview.message))); }
    const details = node("details", "rs-provenance"); details.open = !!sourceOpen; details.append(node("summary", "", t("manifest"))); if (state.manifest) details.append(node("pre", "rs-source-preview", JSON.stringify(state.manifest, null, 2))); else details.append(node("p", "rs-file-foot", t("sourceUnknown"))); panel.append(details);
  }
  async function readArtifact(file, mode) {
    if (!state.run || !state.connected) return;
    clearPreview();
    const runId = state.run.id, current = generation, currentSelection = selection, serial = previewSerial, type = extension(file.path), image = ["png", "jpg", "jpeg"].includes(type), plain = ["txt", "md", "json", "jsonl", "csv", "tsv", "yaml", "yml", "log", "bib", "py"].includes(type);
    if (file.size > 64 * 1048576) throw new Error(t("tooLarge"));
    if (mode === "preview" && ((!image && !plain) || file.size > (image ? 5 : 2) * 1048576)) { state.preview = { fileId: file.id, message: "previewUnavailable" }; renderFileDetail(); return; }
    state.preview = { fileId: file.id, loading: true }; renderFileDetail();
    try {
      const bytes = await api(`/api/runs/${encodeURIComponent(runId)}/artifacts/${encodeURIComponent(file.id)}`, { binary: true });
      if (current !== generation || currentSelection !== selection || serial !== previewSerial) return;
      if (bytes.byteLength > 64 * 1048576 || bytes.byteLength !== file.size) throw new Error(t("artifactChanged"));
      const hash = Array.from(new Uint8Array(await crypto.subtle.digest("SHA-256", bytes)), byte => byte.toString(16).padStart(2, "0")).join("");
      if (current !== generation || currentSelection !== selection || serial !== previewSerial) return;
      if (typeof file.sha256 !== "string" || hash !== file.sha256.toLowerCase()) throw new Error(t("artifactChanged"));
      state.verified.add(`${runId}:${file.id}:${file.sha256}`); state.preview = { fileId: file.id };
      if (mode === "download" || image) { const blob = new Blob([bytes], { type: mode === "download" ? "application/octet-stream" : type === "png" ? "image/png" : "image/jpeg" }), url = URL.createObjectURL(blob); objectUrls.add(url); if (mode === "download") { const anchor = node("a"); anchor.href = url; anchor.download = filename(file.path); document.body.append(anchor); anchor.click(); anchor.remove(); } else state.preview.imageUrl = url; }
      else state.preview.text = new TextDecoder("utf-8", { fatal: true }).decode(bytes);
      renderFileDetail();
    } catch (error) { if (current !== generation || currentSelection !== selection || serial !== previewSerial) return; state.preview = null; renderFileDetail(); throw error; }
  }
  const interaction = { key: "", serial: 0, thread: null, turns: [], threads: [], decisions: [], pending: null, busy: false, loading: false, decisionPending: null };
  const interactionKey = () => JSON.stringify([state.stage, $("topic").value.trim()]);
  const interactionEnabled = () => state.connected && state.reachable && state.status?.features?.stage_dialogue === true;
  const matchingRun = () => state.run && state.run.stage === state.stage && state.run.topic === $("topic").value.trim() && !active(state.run);
  function resetInteraction() {
    interaction.serial++; Object.assign(interaction, { key: interactionKey(), thread: null, turns: [], threads: [], decisions: [], pending: null, busy: false, loading: false, decisionPending: null });
    for (const id of ["dialogue-message", "decision-scope", "review-note"]) $(id).value = "";
    $("dialogue-context").checked = false;
  }
  function confirmedScope() { return interaction.key === interactionKey() ? interaction.decisions.findLast(item => item.request.action === "confirm_scope" && item.request.scope === $("scope").value.trim()) : null; }
  async function refreshInteraction() {
    if (!interactionEnabled() || interaction.loading || !$("topic").value.trim()) return;
    const serial = interaction.serial, key = interaction.key, thread = interaction.thread;
    interaction.loading = true;
    try {
      const threads = await api(`/api/dialogue/threads?stage=${state.stage}`);
      const decisions = await api("/api/decisions/query", { method: "POST", body: { stage: state.stage, topic: $("topic").value.trim() } });
      const result = thread ? await api(`/api/dialogue/threads/${encodeURIComponent(thread)}`) : null;
      if (serial !== interaction.serial || key !== interactionKey() || thread !== interaction.thread) return;
      interaction.threads = threads.threads.filter(run => run.topic === $("topic").value.trim()); interaction.decisions = decisions.decisions;
      if (result) interaction.turns = result.turns;
      const latest = interaction.turns.at(-1)?.run;
      if (latest && !active(latest) && state.status?.active_run_id === latest.id) { await refreshStatus(); if (serial !== interaction.serial) return; renderWorkspace(); }
      if (interaction.pending && interaction.turns.some(turn => turn.run.id === interaction.pending.request_id)) { interaction.pending = null; $("dialogue-message").value = ""; }
      renderInteraction(false);
    } finally { if (serial === interaction.serial) interaction.loading = false; }
  }
  function renderInteraction(refresh = true) {
    if (interaction.key !== interactionKey()) resetInteraction();
    const enabled = interactionEnabled(), last = interaction.turns.at(-1), busy = interaction.busy || active(last?.run), source = matchingRun();
    $("dialogue-hint").textContent = t(enabled ? "dialogueHelp" : "dialogueUnavailable");
    const options = [node("option", "", t("newDialogue"))]; options[0].value = "";
    for (const run of interaction.threads) { const option = node("option", "", `${dateLabel(run.created_at)} · ${run.thread_id.slice(0, 8)}`); option.value = run.thread_id; options.push(option); }
    if (interaction.thread && !options.some(option => option.value === interaction.thread)) { const option = node("option", "", interaction.thread.slice(0, 8)); option.value = interaction.thread; options.push(option); }
    $("dialogue-thread").replaceChildren(...options); $("dialogue-thread").value = interaction.thread || "";
    $("dialogue-thread").disabled = interaction.busy || !!interaction.pending || !!interaction.decisionPending; $("new-dialogue").disabled = $("dialogue-thread").disabled;
    const log = $("dialogue-log");
    // Keep the live region stable when polling returns identical messages.
    const signature = JSON.stringify([state.locale, interaction.turns]);
    if (log.dataset.signature !== signature) {
      log.dataset.signature = signature; log.replaceChildren();
      if (!interaction.turns.length) log.append(node("p", "rs-disclosure", t("noDialogue")));
      for (const turn of interaction.turns) {
        const user = node("div", "rs-chat-message rs-chat-user"), assistant = node("div", "rs-chat-message");
        user.append(node("strong", "", t("you")), node("p", "rs-source-text", turn.run.message));
        assistant.append(node("strong", "", "Codex"), node("p", "rs-source-text", turn.reply?.message || turn.reply_error || turn.run.error || statusLabel(turn.run.status)), node("small", "rs-disclosure", `${turn.run.id} · ${dateLabel(turn.run.created_at)}`));
        log.append(user, assistant);
      }
    }
    $("dialogue-question").hidden = !last?.reply?.question; $("dialogue-question").textContent = last?.reply?.question ? `${t("awaitingAnswer")} · ${last.reply.question}` : "";
    $("dialogue-message").disabled = interaction.busy || !!interaction.pending;
    $("dialogue-send").disabled = !enabled || busy || (!interaction.pending && ((!interaction.turns.length && !!interaction.thread) || !state.status?.available || !!state.status.active_run_id));
    $("dialogue-send").textContent = t(interaction.pending ? "retry" : "sendDialogue"); $("dialogue-stop").disabled = !enabled || !active(last?.run);
    $("dialogue-context").disabled = !source || busy || !!interaction.pending;
    $("dialogue-source").textContent = source ? `${state.run.id} · ${t("source")}` : t("noRun");
    const selectedFile = $("dialogue-file").value, files = [node("option", "", t("noAttachment"))]; files[0].value = "";
    if (source && $("dialogue-context").checked) for (const file of state.artifacts.filter(file => file.size <= 12000 && ["md", "txt", "json", "csv", "bib", "yaml", "yml", "tsv", "log"].includes(extension(file.path)))) { const option = node("option", "", `${file.path} · ${sizeLabel(file.size)}`); option.value = file.id; files.push(option); }
    $("dialogue-file").replaceChildren(...files); $("dialogue-file").value = files.some(file => file.value === selectedFile) ? selectedFile : ""; $("dialogue-file").disabled = !source || !$("dialogue-context").checked || busy || !!interaction.pending;
    $("use-scope").disabled = !last?.reply?.suggested_scope || !!interaction.decisionPending;
    $("confirm-scope").disabled = !enabled || interaction.busy; $("decision-scope").disabled = !!interaction.decisionPending;
    $("scope-receipt").textContent = confirmedScope() ? `${t("confirmedScope")} · ${confirmedScope().id}` : "";
    $("review-target").textContent = source ? `${t("reviewSelected")} · ${state.run.id}\nSHA-256 ${state.manifestSha || "—"}` : t("noRun");
    $("accept-review").disabled = !enabled || !source || !state.manifestSha || state.run.status !== "human-review" || interaction.busy;
    $("request-changes").disabled = !enabled || !source || !state.manifestSha || state.run.status === "blocked" || interaction.busy;
    $("review-note").disabled = !!interaction.decisionPending;
    $("decision-history").replaceChildren(...interaction.decisions.map(item => node("p", "rs-source-text", `${t(item.request.action)} · ${dateLabel(item.created_at)}\n${item.request.scope || item.request.note || ""}\n${item.id}${item.request.run_id ? " · " + item.request.run_id : ""}`)));
    if (!interaction.decisions.length) $("decision-history").append(node("p", "rs-disclosure", t("noDecisions")));
    const locked = interaction.busy || !!interaction.pending || !!interaction.decisionPending;
    $("topic").disabled = state.submitting || locked;
    root.querySelectorAll(".rs-stage, #mobile-stages button").forEach(button => { button.disabled = locked; });
    if (refresh && enabled) refreshInteraction().catch(error => { if (error.name !== "AbortError") notify("apiError", error.message); });
  }
  $("dialogue-thread").addEventListener("change", () => { interaction.serial++; interaction.loading = false; interaction.thread = $("dialogue-thread").value || null; interaction.turns = []; renderInteraction(); });
  $("new-dialogue").addEventListener("click", () => { resetInteraction(); renderInteraction(); });
  $("topic").addEventListener("change", () => { resetInteraction(); renderInteraction(); });
  $("dialogue-context").addEventListener("change", () => renderInteraction(false));
  $("dialogue-form").addEventListener("submit", async event => {
    event.preventDefault(); if (!interactionEnabled() || interaction.busy) return;
    const topic = $("topic").value.trim(), message = $("dialogue-message").value.trim(); if (!topic || !message) { notify("noDialogue"); return; }
    if (!interaction.thread) interaction.thread = crypto.randomUUID();
    const payload = interaction.pending || { kind: "dialogue", request_id: crypto.randomUUID(), thread_id: interaction.thread, parent_turn_id: interaction.turns.at(-1)?.run.id || null, stage: state.stage, topic, message, context_run_id: $("dialogue-context").checked && matchingRun() ? state.run.id : null, artifact_ids: [], timeout_seconds: 600 };
    if (!interaction.pending && payload.context_run_id && $("dialogue-file").value) payload.artifact_ids = [$("dialogue-file").value];
    interaction.pending = payload; interaction.busy = true; const serial = interaction.serial;
    renderInteraction(false);
    try { const data = await api("/api/dialogue/turns", { method: "POST", body: payload }); if (serial !== interaction.serial) return; if (!usableRun(data.run)) throw new Error(t("malformed")); interaction.pending = null; $("dialogue-message").value = ""; await refreshStatus(); await refreshInteraction(); }
    catch (error) { if (serial === interaction.serial) { if (error.httpStatus) interaction.pending = null; handleError(error); } }
    finally { if (serial === interaction.serial) { interaction.busy = false; renderInteraction(); } }
  });
  $("dialogue-stop").addEventListener("click", async () => { const run = interaction.turns.at(-1)?.run; if (!active(run)) return; try { await api(`/api/runs/${encodeURIComponent(run.id)}/stop`, { method: "POST", body: {} }); await refreshStatus(); await refreshInteraction(); } catch (error) { handleError(error); } });
  $("use-scope").addEventListener("click", () => { $("decision-scope").value = interaction.turns.at(-1)?.reply?.suggested_scope || ""; });
  for (const [id, action] of [["confirm-scope", "confirm_scope"], ["accept-review", "accept_review"], ["request-changes", "request_changes"]]) $(id).addEventListener("click", async () => {
    if (!interactionEnabled() || interaction.busy) return;
    const topic = $("topic").value.trim(), scope = $("decision-scope").value.trim(), note = $("review-note").value.trim();
    if (!topic || (action === "confirm_scope" && !scope) || (action === "request_changes" && !note)) { notify("invalidInput"); return; }
    const payload = interaction.decisionPending || { request_id: crypto.randomUUID(), stage: state.stage, topic, action, scope: action === "confirm_scope" ? scope : null, run_id: action === "confirm_scope" ? null : state.run?.id, manifest_sha256: action === "confirm_scope" ? null : state.manifestSha, note };
    if (payload.action !== action) { notify("uncertainSubmit"); return; }
    interaction.decisionPending = payload; interaction.busy = true; const serial = interaction.serial; renderInteraction(false);
    try { const result = await api("/api/decisions", { method: "POST", body: payload }); if (serial !== interaction.serial) return; interaction.decisions.push(result.decision); interaction.decisionPending = null; if (action === "confirm_scope" && state.stage === 1) { $("scope").value = payload.scope; $("scope-confirmed").checked = false; state.pending = null; } await refreshInteraction(); }
    catch (error) { if (serial === interaction.serial) { if (error.httpStatus) interaction.decisionPending = null; handleError(error); } }
    finally { if (serial === interaction.serial) { interaction.busy = false; renderInteraction(); } }
  });
  root.querySelectorAll("[data-view]").forEach(button => button.addEventListener("click", () => { state.view = button.dataset.view; render(); }));
  $("connection-button").addEventListener("click", () => { state.view = "connection"; render(); });
  $("language").addEventListener("change", () => { if (!locales.includes($("language").value)) return; state.locale = $("language").value; try { localStorage.setItem("research-studio.locale", state.locale); } catch {} render(); });
  $("connection-form").addEventListener("submit", async event => {
    event.preventDefault(); let base; try { base = baseUrl($("api-url").value.trim()); } catch (error) { notify("invalidUrl"); return; }
    const token = $("access-token").value.trim(); if (!token) return;
    clearConnection(false); state.base = base; state.token = token; state.connecting = true; const current = generation; render();
    try { await refreshStatus(); await refreshRuns(); if (current !== generation) return; state.connected = true; state.connecting = false; $("access-token").value = ""; render(); schedulePoll(); }
    catch (error) { if (current !== generation) return; clearConnection(false); notify("apiError", error.message); render(); }
  });
  $("disconnect-button").addEventListener("click", () => { clearConnection(); render(); });
  for (const id of ["topic", "scope", "timeout"]) $(id).addEventListener("input", () => { $("scope-confirmed").checked = false; state.pending = null; });
  $("run-form").addEventListener("submit", async event => {
    event.preventDefault(); const topic = $("topic").value.trim(), scope = $("scope").value.trim(), timeout = Number($("timeout").value);
    if (!canRun() || !topic || !scope || topic.length > 4000 || scope.length > 4000 || !Number.isInteger(timeout) || timeout < 60 || timeout > 3600 || !$("scope-confirmed").checked) { notify("invalidInput"); return; }
    const payload = state.pending || { topic, scope, scope_confirmed: true, stage: 1, timeout_seconds: timeout, request_id: crypto.randomUUID() };
    if (interactionEnabled()) { const confirmation = confirmedScope(); if (!confirmation) { notify("scopeRequired"); return; } payload.scope_confirmation_id = confirmation.id; }
    state.pending = payload; state.submitting = true; state.notice = null; const current = generation; let posted = false, acknowledged = false; render();
    try {
      await refreshStatus();
      if (!backendReady()) { state.pending = null; notify(state.status?.active_run_id ? "activeExists" : "blocked", text(state.status?.reason)); return; }
      posted = true; const data = await api("/api/runs", { method: "POST", body: payload });
      if (!usableRun(data.run)) throw new Error(t("malformed"));
      acknowledged = true; state.pending = null; state.run = data.run; $("scope-confirmed").checked = false;
      await refreshRuns(); await refreshStatus(); await loadRun(data.run.id, true);
    }
    catch (error) { if (current === generation && error.name !== "AbortError") { if (error.httpStatus || !posted || acknowledged) { if (error.httpStatus) state.pending = null; handleError(error); } else { state.reachable = false; if (state.status) state.status.available = false; lastStatusAt = 0; notify("uncertainSubmit", error.message); } } }
    finally { if (current === generation) { state.submitting = false; render(); } }
  });
  $("stop-button").addEventListener("click", async () => { if (!active(state.run) || state.stopping) return; const id = state.run.id, current = generation; state.stopping = true; render(); try { await api(`/api/runs/${encodeURIComponent(id)}/stop`, { method: "POST", body: {} }); await refreshStatus(); if (state.run?.id === id) await loadRun(id); } catch (error) { handleError(error); } finally { if (current === generation) { state.stopping = false; render(); } } });
  $("open-artifacts").addEventListener("click", () => { state.view = "files"; render(); });
  $("open-evidence").addEventListener("click", () => { state.view = "files"; render(); });
  $("run-form").addEventListener("invalid", () => { $("run-settings").open = true; }, true);
  $("file-run").addEventListener("change", () => { const id = $("file-run").value; if (state.runs.some(run => run.id === id)) loadRun(id, true).catch(handleError); });
  $("refresh-history").addEventListener("click", () => refreshRuns().then(render).catch(handleError));
  $("refresh-files").addEventListener("click", () => { if (state.run) loadRun(state.run.id).catch(handleError); });
  try { const locale = localStorage.getItem("research-studio.locale"); if (locales.includes(locale)) state.locale = locale; } catch {}
  const configuredUrl = window.RESEARCH_STUDIO_CONFIG?.apiBaseUrl; if (typeof configuredUrl === "string") $("api-url").value = configuredUrl;
  render();
})();
