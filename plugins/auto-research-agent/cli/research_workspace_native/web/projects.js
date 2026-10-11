/* Universal project UI. Saved intent keys survive reload; no action auto-resends. */
(function () {
  "use strict";
  const bootstrap = window.RESEARCH_PROJECTS;
  if (!bootstrap || typeof bootstrap.credential !== "string") return;
  const words = {
    en: {
      newProject: "New project", projects: "PROJECTS", savedViews: "SAVED RESULTS",
      ownAccount: "Your projects · Your own Codex account", workspace: "Research workspace", language: "Language",
      eyebrow: "TOPIC → EVIDENCE → RESEARCH DIRECTIONS", title: "Start with your research question",
      intro: "Use the same Harness workflow for different topics. Confirm the scope and resources, then review each saved step.",
      topic: "Research topic", topicLabel: "Topic or area you would like to explore",
      needsLabel: "What do you need to learn or decide? One question per line.",
      suggestionHelp: "For topic suggestions, describe your interests first. Codex suggestions remain proposals until you choose and confirm them.",
      create: "Create research project", refresh: "Refresh saved state", confirmTitle: "Confirm the research scope",
      confirmHelp: "A proposed count is not a submitted answer. Saving settings does not start a model call or a search.",
      geography: "Geographic scope", choose: "Choose explicitly", unrestricted: "Unrestricted", specified: "Specify a region",
      notApplicable: "Not applicable to this research", geographyValue: "Region / explanation",
      formalCount: "Target formally usable papers", priorityCount: "Priority reading target",
      resources: "Research resources, timing, constraints and alternatives", budgetTitle: "Run budget and tool consent",
      modelCalls: "Model calls", seconds: "Execution seconds", searchCalls: "Search attempts", sourceReads: "Source reads", rounds: "Search rounds",
      searchConsent: "Request public external search", readConsent: "Request lawful public source reading",
      consentHelp: "Requests remain separate from a registered execution permit. Browser/computer fallback needs its own applicable consent. Unknown usage and price stay Unknown.",
      confirmation: "Your confirmation or constraints, saved verbatim", confirm: "Confirm and save this scope version",
      stage1Title: "Literature & evidence", stage2Title: "Comparison & research directions",
      stage1Outputs: "Knowledge network · Complete screening library · Source notes · Bibliography · Coverage and stop decision",
      stage2Outputs: "Shared comparison dimensions · Evidence-backed opportunities · Candidate routes · Independent review · Selection package",
      suggestTopic: "Ask Codex for topic options", planSearch: "Ask Codex to propose a search plan",
      activateStage2: "Accept this Stage1 evidence for Stage2",
      activationHelp: "Import binds saved evidence. It does not start research, approve a direction or unlock Stage3.",
      historyTitle: "Saved actions and results", refreshHistory: "Read action history",
      workflowTitle: "Workflow, expected outputs and remaining connections",
      workflow1: "1. Confirm the scope", output1: "Versioned ResearchBrief and resource limits",
      workflow2: "2. Search, read and screen", output2: "Query/source attempts, keep/reject reasons and source-bound claims",
      workflow3: "3. Check coverage and deliver Stage1", output3: "Real coverage gate, canonical reports and accepted evidence handoff",
      workflow4: "4. Compare and propose Stage2 routes", output4: "Comparison, candidates, independent checks and retained revisions",
      workflow5: "5. Review and select", output5: "User choice and unresolved conditions; Stage3–6 planned/unconnected",
      completionHelp: "A completed call, a valid artifact and an accepted research stage are different states. A partial result or Unknown is retained; refresh reads history and never resends.",
      pending: "Scope confirmation pending", confirmed: "Scope version saved", saved: "Saved. No research was started.",
      planMissing: "Search plan not yet compiled. A topic is not an executed query.",
      planReady: "Confirmed brief and compiled plan are saved. Searches need a separate, bound tool permit.",
      modelMissing: "Codex content provider is not registered for this project. No model call is available.",
      modelReady: "Only registered, budgeted content tasks can run. Suggestions and planning do not complete Stage1.",
      modelConfigured: "The local content service is configured. A bounded task permit is still required; this does not verify Codex account authentication.",
      modelHeld: "An earlier task has an uncertain result, so new submissions stay held. Inspect saved operations below; refresh never resends the task.",
      stage2Missing: "No accepted canonical Stage1 package is registered for this project/version.",
      stage2Ready: "A source-bound Stage1 import is available for explicit review.",
      emptyHistory: "No actions are saved yet.", working: "Saving the action intent…",
      responseLost: "The response was lost or rejected. Read saved history before taking another action; nothing is automatically resent.",
      recovered: "Saved history loaded. Any unknown action remains unknown.", sourceDetails: "Input versions and saved identity",
      noProjects: "Create your first research project.", none: "No saved results registered.",
      missingChoice: "Choose a geographic scope explicitly and provide your confirmation.",
      unsent: "This action has an unresolved saved intent. Use history to check it; do not resend."
    },
    "zh-Hans": {
      newProject: "新建项目", projects: "研究项目", savedViews: "已保存成果", ownAccount: "独立项目 · 使用自己的 Codex 账号",
      workspace: "研究工作台", language: "语言", eyebrow: "主题 → 文献证据 → 研究方向", title: "从你的研究问题开始",
      intro: "不同主题使用同一套 Harness 流程。先确认范围与资源，再逐步审阅保存的结果。",
      topic: "研究主题", topicLabel: "你想研究的主题或领域", needsLabel: "你需要了解或决定什么？每行一个问题。",
      suggestionHelp: "若希望获得选题建议，先描述兴趣。Codex 的建议仍是提案，须由你选择并确认。",
      create: "创建研究项目", refresh: "刷新保存状态", confirmTitle: "确认研究范围",
      confirmHelp: "提议的篇数不是已提交的答案。保存设置不会启动模型或搜索。",
      geography: "地域范围", choose: "请明确选择", unrestricted: "不限定地域", specified: "指定地域",
      notApplicable: "此研究不涉及地域", geographyValue: "地域 / 说明", formalCount: "正式可用文献目标", priorityCount: "优先阅读目标",
      resources: "研究资源、时间、限制与备选方案", budgetTitle: "执行预算与工具授权", modelCalls: "模型调用次数",
      seconds: "执行秒数", searchCalls: "搜索尝试次数", sourceReads: "来源读取次数", rounds: "搜索轮数",
      searchConsent: "申请公开外部搜索", readConsent: "申请合法读取公开来源",
      consentHelp: "申请与服务端执行许可分开。浏览器或电脑操作需另有适用授权；未知用量和费用仍保持 Unknown。",
      confirmation: "你的确认或限制，按原文保存", confirm: "确认并保存此范围版本",
      stage1Title: "文献与证据", stage2Title: "比较与研究方向",
      stage1Outputs: "知识网络 · 完整筛选文献库 · 来源笔记 · 参考文献 · 覆盖与停止判断",
      stage2Outputs: "共同比较维度 · 有据的研究机会 · 候选路线 · 独立查核 · 方向选择包",
      suggestTopic: "请 Codex 提出主题选项", planSearch: "请 Codex 提出检索计划", activateStage2: "确认此 Stage1 证据供 Stage2 使用",
      activationHelp: "导入只绑定保存的证据，不启动研究、不批准方向，也不开放 Stage3。",
      historyTitle: "保存的操作与结果", refreshHistory: "读取操作历史", workflowTitle: "工作流程、预期产物与待接入项",
      workflow1: "1. 确认范围", output1: "版本化 ResearchBrief 与资源限制",
      workflow2: "2. 搜索、读取与筛选", output2: "查询与来源尝试、保留/排除理由及来源绑定主张",
      workflow3: "3. 检查覆盖并交付 Stage1", output3: "真实覆盖门、规范报告与已接受的证据交接",
      workflow4: "4. 比较并提出 Stage2 路线", output4: "比较、候选、独立查核及修订历史",
      workflow5: "5. 审阅与选择", output5: "用户选择及待解条件；Stage3–6 仍为 planned/unconnected",
      completionHelp: "一次调用完成、文件有效、研究阶段通过是不同状态。partial 与 Unknown 均保留；刷新只读历史，不重发。",
      pending: "等待范围确认", confirmed: "范围版本已保存", saved: "已保存，未启动研究。",
      planMissing: "尚未编译检索计划。输入主题不代表已执行查询。",
      planReady: "已保存确认范围与编译计划。搜索仍需另行绑定的工具许可。",
      modelMissing: "此项目尚未注册 Codex 内容服务，当前不能调用模型。",
      modelReady: "只可运行已注册、预算绑定的内容任务。选题与规划不代表 Stage1 完成。",
      modelConfigured: "本地内容服务已配置，仍需有界任务许可；这不代表 Codex 账号认证已通过。",
      modelHeld: "此前任务结果尚不确定，已暂停新的送出。请查看下方保存的操作；刷新不会重发任务。",
      stage2Missing: "此项目/版本尚未注册已接受的规范 Stage1 交付包。",
      stage2Ready: "已有来源绑定的 Stage1 导入选项，等待明确审阅。",
      emptyHistory: "尚无保存操作。", working: "正在保存操作意图…",
      responseLost: "响应丢失或请求被拒绝。继续操作前先读取保存历史；系统不会自动重发。",
      recovered: "已读取保存历史，未知操作仍保持未知。", sourceDetails: "输入版本与保存的身份绑定",
      noProjects: "创建你的第一个研究项目。", none: "尚未注册保存成果。",
      missingChoice: "请明确选择地域范围并填写确认。", unsent: "此操作仍有未确认结果的意图，请查历史，勿重复送出。"
    },
    "zh-Hant": {
      newProject: "新增專案", projects: "研究專案", savedViews: "已保存成果", ownAccount: "獨立專案 · 使用自己的 Codex 帳號",
      workspace: "研究工作台", language: "語言", eyebrow: "主題 → 文獻證據 → 研究方向", title: "從你的研究問題開始",
      intro: "不同主題使用同一套 Harness 流程。先確認範圍與資源，再逐步審閱保存的結果。",
      topic: "研究主題", topicLabel: "你想研究的主題或領域", needsLabel: "你需要了解或決定什麼？每行一個問題。",
      suggestionHelp: "若希望獲得選題建議，先描述興趣。Codex 的建議仍是提案，須由你選擇並確認。",
      create: "建立研究專案", refresh: "重新讀取保存狀態", confirmTitle: "確認研究範圍",
      confirmHelp: "提議的篇數不是已提交的答案。保存設定不會啟動模型或搜尋。",
      geography: "地域範圍", choose: "請明確選擇", unrestricted: "不限定地域", specified: "指定地域",
      notApplicable: "此研究不涉及地域", geographyValue: "地域 / 說明", formalCount: "正式可用文獻目標", priorityCount: "優先閱讀目標",
      resources: "研究資源、時間、限制與備選方案", budgetTitle: "執行預算與工具授權", modelCalls: "模型呼叫次數",
      seconds: "執行秒數", searchCalls: "搜尋嘗試次數", sourceReads: "來源讀取次數", rounds: "搜尋輪數",
      searchConsent: "申請公開外部搜尋", readConsent: "申請合法讀取公開來源",
      consentHelp: "申請與伺服器執行許可分開。瀏覽器或電腦操作需另有適用授權；未知用量和費用仍保持 Unknown。",
      confirmation: "你的確認或限制，按原文保存", confirm: "確認並保存此範圍版本",
      stage1Title: "文獻與證據", stage2Title: "比較與研究方向",
      stage1Outputs: "知識網絡 · 完整篩選文獻庫 · 來源筆記 · 參考文獻 · 覆蓋與停止判斷",
      stage2Outputs: "共同比較維度 · 有據的研究機會 · 候選路線 · 獨立查核 · 方向選擇包",
      suggestTopic: "請 Codex 提出主題選項", planSearch: "請 Codex 提出檢索計畫", activateStage2: "確認此 Stage1 證據供 Stage2 使用",
      activationHelp: "匯入只綁定保存的證據，不啟動研究、不批准方向，也不開放 Stage3。",
      historyTitle: "保存的操作與結果", refreshHistory: "讀取操作歷史", workflowTitle: "工作流程、預期產物與待接入項",
      workflow1: "1. 確認範圍", output1: "版本化 ResearchBrief 與資源限制",
      workflow2: "2. 搜尋、讀取與篩選", output2: "查詢與來源嘗試、保留/排除理由及來源綁定主張",
      workflow3: "3. 檢查覆蓋並交付 Stage1", output3: "真實覆蓋門、規範報告與已接受的證據交接",
      workflow4: "4. 比較並提出 Stage2 路線", output4: "比較、候選、獨立查核及修訂歷史",
      workflow5: "5. 審閱與選擇", output5: "使用者選擇及待解條件；Stage3–6 仍為 planned/unconnected",
      completionHelp: "一次呼叫完成、檔案有效、研究階段通過是不同狀態。partial 與 Unknown 均保留；重新整理只讀歷史，不重送。",
      pending: "等待範圍確認", confirmed: "範圍版本已保存", saved: "已保存，未啟動研究。",
      planMissing: "尚未編譯檢索計畫。輸入主題不代表已執行查詢。",
      planReady: "已保存確認範圍與編譯計畫。搜尋仍需另行綁定的工具許可。",
      modelMissing: "此專案尚未註冊 Codex 內容服務，目前不能呼叫模型。",
      modelReady: "只可執行已註冊、預算綁定的內容任務。選題與規劃不代表 Stage1 完成。",
      modelConfigured: "本機內容服務已設定，仍需有界任務許可；這不代表 Codex 帳號認證已通過。",
      modelHeld: "先前任務結果仍不確定，已暫停新的送出。請查看下方保存的操作；重新整理不會重送任務。",
      stage2Missing: "此專案/版本尚未註冊已接受的規範 Stage1 交付包。",
      stage2Ready: "已有來源綁定的 Stage1 匯入選項，等待明確審閱。",
      emptyHistory: "尚無保存操作。", working: "正在保存操作意圖…",
      responseLost: "回應遺失或請求被拒絕。繼續操作前先讀取保存歷史；系統不會自動重送。",
      recovered: "已讀取保存歷史，未知操作仍保持未知。", sourceDetails: "輸入版本與保存的身分綁定",
      noProjects: "建立你的第一個研究專案。", none: "尚未註冊保存成果。",
      missingChoice: "請明確選擇地域範圍並填寫確認。", unsent: "此操作仍有未確認結果的意圖，請查歷史，勿重複送出。"
    }
  };
  Object.assign(words.en, {reviseTitle: "Choose or revise the topic", reviseHelp: "A new topic creates a new input version. Previous scope answers, plans and results remain in history.", revise: "Save a new topic version", configure: "Save resources for topic suggestions", tooLarge: "Text exceeds the UTF-8 input limit or contains invalid characters. Shorten it before sending."});
  Object.assign(words["zh-Hans"], {reviseTitle: "选择或修改主题", reviseHelp: "修改主题会建立新的输入版本。旧范围、计划和结果保留在历史中。", revise: "保存新的主题版本", configure: "保存选题建议所用资源", tooLarge: "文字超过 UTF-8 输入限制或包含无效字符，请修改后再提交。"});
  Object.assign(words["zh-Hant"], {reviseTitle: "選擇或修改主題", reviseHelp: "修改主題會建立新的輸入版本。舊範圍、計畫和結果保留在歷史中。", revise: "保存新的主題版本", configure: "保存選題建議所用資源", tooLarge: "文字超過 UTF-8 輸入限制或包含無效字元，請修改後再提交。"});
  Object.assign(words.en, {authorizationTitle: "Authorize a bounded Codex content task", authorizationHelp: "This authorizes one content call only. No search, commands, file changes or stage completion is granted. Sending the offered task is a separate step.", authorizeTopic: "Authorize topic options", authorizePlan: "Authorize search-plan proposal", nativeTitle: "Codex questions and approvals", nativeRefresh: "Read current session", nativeHelp: "Content tasks can ask questions. Tool requests may only be declined or cancelled here. Reading does not start or resume a session.", nativeEmpty: "No active native questions are connected.", sendAnswer: "Send answer", decline: "Decline", cancel: "Cancel", interrupt: "Interrupt active call", preview: "Output preview · Original bytes and hash are retained", viewOutput: "Read full output", nextOutput: "Read next part"});
  Object.assign(words["zh-Hans"], {authorizationTitle: "授权有界 Codex 内容任务", authorizationHelp: "只授权一次内容调用，不授权搜索、命令、文件修改或阶段通过。发送已提供的任务是另一步。", authorizeTopic: "授权选题建议", authorizePlan: "授权检索计划提案", nativeTitle: "Codex 问题与审批", nativeRefresh: "读取当前会话", nativeHelp: "内容任务可以提问，此处工具请求只可拒绝或取消。读取不会启动或恢复会话。", nativeEmpty: "当前没有接通的原生问题。", sendAnswer: "提交回答", decline: "拒绝", cancel: "取消", interrupt: "中断当前调用", preview: "输出预览 · 原始字节与 hash 保留", viewOutput: "读取完整输出", nextOutput: "读取下一段"});
  Object.assign(words["zh-Hant"], {authorizationTitle: "授權有界 Codex 內容任務", authorizationHelp: "只授權一次內容呼叫，不授權搜尋、命令、檔案修改或階段通過。送出已提供的任務是另一步。", authorizeTopic: "授權選題建議", authorizePlan: "授權檢索計畫提案", nativeTitle: "Codex 問題與核准", nativeRefresh: "讀取目前工作階段", nativeHelp: "內容任務可以提問，此處工具請求只可拒絕或取消。讀取不會啟動或恢復工作階段。", nativeEmpty: "目前沒有接通的原生問題。", sendAnswer: "提交回答", decline: "拒絕", cancel: "取消", interrupt: "中斷目前呼叫", preview: "輸出預覽 · 原始位元組與 hash 保留", viewOutput: "讀取完整輸出", nextOutput: "讀取下一段"});
  Object.assign(words.en, {ledgerTitle: "Stage1 coverage and saved evidence", ledgerInit: "Initialize the bound evidence ledger", ledgerHelp: "A ledger records the real Harness plan and evidence history. Initialization and a checkpoint do not execute a search or complete Stage1.", ledgerCheckpoint: "Check the current evidence gate", ledgerExport: "Export saved ledger artifacts", plannedQueries: "Planned queries", moreHistory: "Read more history"});
  Object.assign(words["zh-Hans"], {ledgerTitle: "Stage1 覆盖与证据记录", ledgerInit: "初始化绑定的证据记录", ledgerHelp: "记录真实 Harness 计划与证据历史。初始化和检查点不会执行搜索，也不代表 Stage1 完成。", ledgerCheckpoint: "检查当前证据门", ledgerExport: "导出已保存记录", plannedQueries: "计划查询", moreHistory: "读取更多历史"});
  Object.assign(words["zh-Hant"], {ledgerTitle: "Stage1 覆蓋與證據紀錄", ledgerInit: "初始化綁定的證據紀錄", ledgerHelp: "紀錄真實 Harness 計畫與證據歷史。初始化和檢查點不會執行搜尋，也不代表 Stage1 完成。", ledgerCheckpoint: "檢查目前證據門", ledgerExport: "匯出已保存紀錄", plannedQueries: "計畫查詢", moreHistory: "讀取更多歷史"});
  Object.assign(words.en, {queryTitle: "Stage1 search execution", queryHelp: "Authorize a bound search budget, initialize the runtime, then send one offered query. Each step retains an intent and its observed outcome. Refresh reads history; it never retries.", queryAuthorize: "Authorize these search limits", queryBootstrap: "Initialize the search runtime", queryExecute: "Execute the offered query", queryRestore: "Restore saved ledger ownership", querySaved: "Action recorded. Read the execution history for its actual outcome.", queryBudget: "Reserved budget", queryAttempts: "Backend attempts", queryNoReading: "Source acquisition and model reading need separate permits; they are not granted here.", queryUnavailable: "No search runtime is registered. Saved evidence remains readable.", queryOffer: "Next offered query", queryHistory: "Execution observations"});
  Object.assign(words["zh-Hans"], {queryTitle: "Stage1 搜索执行", queryHelp: "先授权绑定的搜索预算，再初始化运行时，然后执行一条服务端提供的查询。每步保留意图和实际结果；刷新只读历史，不重试。", queryAuthorize: "授权此搜索范围与限额", queryBootstrap: "初始化搜索运行时", queryExecute: "执行当前查询", queryRestore: "恢复保存记录的写入控制", querySaved: "已记录操作，请读取执行历史确认实际结果。", queryBudget: "已预留预算", queryAttempts: "后端尝试次数", queryNoReading: "来源获取与模型阅读需要独立许可；此处未授予。", queryUnavailable: "尚未注册搜索运行时，保存的证据仍可读取。", queryOffer: "下一条可执行查询", queryHistory: "执行回执"});
  Object.assign(words["zh-Hant"], {queryTitle: "Stage1 搜尋執行", queryHelp: "先授權綁定的搜尋預算，再初始化執行環境，然後執行一條伺服器提供的查詢。每步保留意圖和實際結果；重新整理只讀歷史，不重試。", queryAuthorize: "授權此搜尋範圍與限額", queryBootstrap: "初始化搜尋執行環境", queryExecute: "執行目前查詢", queryRestore: "恢復保存紀錄的寫入控制", querySaved: "已記錄操作，請讀取執行歷史確認實際結果。", queryBudget: "已預留預算", queryAttempts: "後端嘗試次數", queryNoReading: "來源取得與模型閱讀需要獨立許可；此處未授予。", queryUnavailable: "尚未註冊搜尋執行環境，保存的證據仍可讀取。", queryOffer: "下一條可執行查詢", queryHistory: "執行回執"});
  Object.assign(words.en, {queryResultLimit: "Results per query", queryProbes: "Runtime probes"});
  Object.assign(words["zh-Hans"], {queryResultLimit: "每次查询结果上限", queryProbes: "运行时探测次数"});
  Object.assign(words["zh-Hant"], {queryResultLimit: "每次查詢結果上限", queryProbes: "執行環境探測次數"});
  const $ = (id) => document.getElementById(id);
  Object.assign(words.en, {retire: "End this unsent attempt", retirementHelp: "Only a server-verified, never-dispatched attempt can be ended. Unknown outcome and reserved budget remain; this never reruns the task.", retirementReason: "Reason for ending this unsent attempt", retired: "Ended without resend · original outcome remains Unknown", retirementBlocked: "Native dispatch or cleanup remains unproven; this attempt stays held."});
  Object.assign(words["zh-Hans"], {retire: "结束这次未派发尝试", retirementHelp: "仅能结束服务端确认未派发的尝试。未知结果与已预留预算保留，不会重跑任务。", retirementReason: "结束这次未派发尝试的原因", retired: "已结束且不重发 · 原结果仍为 Unknown", retirementBlocked: "缺少原生派发或清理证据；这次尝试继续保持暂停。"});
  Object.assign(words["zh-Hant"], {retire: "結束這次未派發嘗試", retirementHelp: "僅能結束伺服器確認未派發的嘗試。未知結果與已預留預算保留，不會重跑任務。", retirementReason: "結束這次未派發嘗試的原因", retired: "已結束且不重送 · 原結果仍為 Unknown", retirementBlocked: "缺少原生派發或清理證據；這次嘗試繼續保持暫停。"});
  Object.assign(words.en, {ledgerPrepare: "Prepare saved reading delivery", ledgerDeliver: "Build the canonical delivery from saved reading", deliveryMissing: "No version-bound reading records are registered yet. A ledger export is separate from the research package.", deliveryReady: "Saved reading records are bound to this checkpoint. Building a package does not approve coverage or research quality.", deliverySaved: "Canonical research package saved · Check coverage before proceeding."});
  Object.assign(words["zh-Hans"], {ledgerPrepare: "准备已保存阅读交付", ledgerDeliver: "用已保存阅读记录生成正式交付包", deliveryMissing: "尚无此版本绑定的阅读记录。记录导出与研究交付包是不同产物。", deliveryReady: "阅读记录已绑定当前检查点。生成文件不代表覆盖或研究质量通过。", deliverySaved: "已保存正式研究交付包 · 继续前请检查覆盖判断。"});
  Object.assign(words["zh-Hant"], {ledgerPrepare: "準備已保存閱讀交付", ledgerDeliver: "用已保存閱讀紀錄產生正式交付包", deliveryMissing: "尚無此版本綁定的閱讀紀錄。紀錄匯出與研究交付包是不同產物。", deliveryReady: "閱讀紀錄已綁定目前檢查點。產生檔案不代表覆蓋或研究品質通過。", deliverySaved: "已保存正式研究交付包 · 繼續前請檢查覆蓋判斷。"});
  const state = { language: "en", project: null, modelOffers: [], modelStatus: null, stage1: null, stage2: null, busy: false, loading: false, activeJob: false, generation: 0, modelHistory: [], historyNext: null, historyBusy: false, output: null, outputGeneration: 0, readingReview: null, readingGeneration: 0 };
  const storageKey = "harness-project-ui-intents-v1";
  let pending = [];
  try { pending = JSON.parse(sessionStorage.getItem(storageKey) || "[]"); } catch (_) {}
  if (!Array.isArray(pending)) pending = [];
  pending = pending.filter((r) => r && typeof r.key === "string" && /^[A-Za-z0-9_-]{1,128}$/.test(r.key) && (r.project_ref === null || typeof r.project_ref === "string" && /^[A-Za-z0-9_-]{1,64}$/.test(r.project_ref)));
  function t(key) { return words[state.language][key] || words.en[key] || key; }
  function notice(text, error) { $("notice").textContent = text; $("notice").classList.toggle("error", Boolean(error)); }
  function key() { return crypto.randomUUID(); }
  function remember(record) { pending.push(record); sessionStorage.setItem(storageKey, JSON.stringify(pending)); }
  function forget(actionKey) { pending = pending.filter((row) => row.key !== actionKey); sessionStorage.setItem(storageKey, JSON.stringify(pending)); }
  function route(ref, tail) { return "/api/projects" + (ref ? "/" + encodeURIComponent(ref) : "") + (tail ? "/" + tail : ""); }
  async function request(path, body) {
    const headers = { Authorization: "Bearer " + bootstrap.credential };
    if (body) headers["Content-Type"] = "application/json";
    const response = await fetch(path, { method: body ? "POST" : "GET", headers, body: body ? JSON.stringify(body) : undefined, credentials: "same-origin", cache: "no-store" });
    const value = await response.json();
    if (!response.ok) { const error = new Error(value.error || "request-failed"); error.receipt = value.receipt; throw error; }
    return value;
  }
  function rows(value, field) { return Array.isArray(value) ? value : value && Array.isArray(value[field]) ? value[field] : []; }
  function bounded(value, maximum) {
    for (let i = 0; i < value.length; ++i) {
      const c = value.charCodeAt(i);
      if (c >= 0xD800 && c <= 0xDBFF) { const next = value.charCodeAt(++i); if (!(next >= 0xDC00 && next <= 0xDFFF)) return false; }
      else if (c >= 0xDC00 && c <= 0xDFFF) return false;
    }
    return new TextEncoder().encode(value).length <= maximum;
  }
  function canonical(value) {
    // Match Python's Unicode codepoint ordering, including supplementary IDs.
    // Default JavaScript sorting compares UTF-16 units and changes intent hashes.
    const compare = (left, right) => {
      const a = Array.from(left), b = Array.from(right);
      for (let i = 0; i < Math.min(a.length, b.length); ++i) {
        const difference = a[i].codePointAt(0) - b[i].codePointAt(0);
        if (difference) return difference;
      }
      return a.length - b.length;
    };
    if (Array.isArray(value)) return "[" + value.map(canonical).join(",") + "]";
    if (value && typeof value === "object") return "{" + Object.keys(value).sort(compare).map((k) => JSON.stringify(k) + ":" + canonical(value[k])).join(",") + "}";
    return JSON.stringify(value);
  }
  async function requestHash(kind, body) { const semantic = Object.fromEntries(Object.entries(body).filter(([name]) => name !== "revision")); const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical({kind, body: semantic}))); return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join(""); }
  async function nativeRequestHash(kind, body) { const digest = await crypto.subtle.digest("SHA-256", new TextEncoder().encode(canonical({kind, body}))); return Array.from(new Uint8Array(digest), (b) => b.toString(16).padStart(2, "0")).join(""); }
  function availableStage2() { return state.stage2 && !state.stage2.activation && rows(state.stage2, "offers").find((row) => row.status === "ready-for-researcher-activation"); }
  function text(parent, tag, value, className) { const node = document.createElement(tag); node.textContent = String(value === null || value === undefined ? "Unknown" : value); if (className) node.className = className; parent.append(node); return node; }
  function buttons() {
    const blocked = state.busy || state.loading;
    $("create-form").querySelector("button").disabled = blocked || pending.some((row) => !row.project_ref);
    const projectBlocked = blocked || !state.project || !state.project.brief || (bootstrap.models && !state.modelStatus) || state.activeJob || pending.some((row) => state.project && row.project_ref === state.project.project_ref);
    $("confirm-form").querySelectorAll("button").forEach((button) => { button.disabled = projectBlocked; });
    $("revise-form").querySelector("button").disabled = projectBlocked;
    for (const [id, operation] of [["suggest-topic", "suggest-topic"], ["plan-search", "plan-search"]]) {
      $(id).disabled = projectBlocked || !state.modelOffers.some((row) => row.operation === operation && row.available === true);
    }
    $("activate-stage2").disabled = projectBlocked || !availableStage2();
    for (const id of ["authorize-topic", "authorize-plan"]) $(id).disabled = projectBlocked || !state.modelStatus || state.modelStatus.authorization_available !== true;
    $("authorize-plan").disabled ||= !state.project || !state.project.intake_report || !state.project.intake_report.necessary_clarification_complete;
    $("native-refresh").disabled = state.loading || !state.project;
    document.querySelectorAll("button[data-model-retire]").forEach((button) => { button.disabled = blocked || !state.project; });
    $("ledger-init").disabled = projectBlocked || !state.stage1 || !state.stage1.initialization_offer;
    for (const id of ["ledger-checkpoint", "ledger-export"]) $(id).disabled = projectBlocked || !state.stage1 || !state.stage1.ledger;
    $("ledger-prepare").disabled = projectBlocked || !availableSavedPreparation();
    $("ledger-deliver").disabled = projectBlocked || !availableDelivery();
    const queries = state.stage1 && state.stage1.query_execution;
    for (const [id, field] of [["query-authorize", "authorization_offer"], ["query-bootstrap", "bootstrap_offer"], ["query-execute", "query_offer"], ["query-restore-owner", "owner_offer"]]) $(id).disabled = projectBlocked || !queries || !queries[field];
    if (window.ResearchProjectCoverage) window.ResearchProjectCoverage.update({project: state.project, stage1: state.stage1, language: state.language, busy: blocked, held: projectBlocked, submit: submitCoverage});
    if (window.ResearchProjectReading) window.ResearchProjectReading.update({project: state.project, stage1: state.stage1, language: state.language, busy: blocked, held: projectBlocked});
    document.querySelectorAll("button[data-reading-draft]").forEach(button => { button.disabled = blocked || !state.project || button.dataset.readingInput !== String(state.project.input_version) || button.dataset.readingBrief !== state.project.brief_sha256; });
  }
  async function openReadingDraft(ref, result) {
    const project = state.project, generation = state.generation, language = state.language;
    const draftSha = result.reading_draft && result.reading_draft.sha256;
    if (!window.ResearchProjectReading || state.busy || state.loading || !project || project.project_ref !== ref
        || result.input_version !== project.input_version || result.brief_sha256 !== project.brief_sha256
        || !/^[0-9a-f]{64}$/.test(result.output_ref || "") || !/^[0-9a-f]{64}$/.test(draftSha || "")) return;
    const task = ++state.readingGeneration;
    const reply = await request(route(ref, "stage1/reading/" + result.output_ref));
    if (generation !== state.generation || task !== state.readingGeneration || language !== state.language
        || !state.project || state.project.project_ref !== ref) return;
    if (reply.output_ref !== result.output_ref || reply.draft_sha256 !== draftSha
        || !window.ResearchProjectReading.render(reply, submitReadingClaim, submitReadingReview)) throw new Error("reading-draft-binding-differs");
    state.readingReview = reply;
  }
  async function submitReadingClaim(item) {
    const project = state.project, view = state.readingReview;
    if (!project || state.busy || state.loading || state.activeJob || !view
        || pending.some(row => row.project_ref === project.project_ref)
        || item.project_ref !== project.project_ref || item.input_version !== project.input_version
        || item.brief_sha256 !== project.brief_sha256 || !state.stage1 || !state.stage1.ledger
        || item.ledger_state_sha256 !== state.stage1.ledger.state_sha256
        || item.output_ref !== view.output_ref || item.draft_sha256 !== view.draft_sha256
        || !rows(view, "offers").some(offer => offer.evidence_index === item.evidence_index && offer.offer_ref === item.offer_ref && offer.offer_sha256 === item.offer_sha256)) return null;
    const ref = project.project_ref, generation = state.generation, version = project.input_version, brief = project.brief_sha256;
    const result = await mutate("stage1/claim", Object.assign(identity(), {ledger_state_sha256: item.ledger_state_sha256, output_ref: item.output_ref, draft_sha256: item.draft_sha256, evidence_index: item.evidence_index, offer_ref: item.offer_ref, offer_sha256: item.offer_sha256, review: item.review, confirmed: true}), ref);
    if (result && generation === state.generation && state.project && state.project.project_ref === ref
        && state.project.input_version === version && state.project.brief_sha256 === brief) await loadProject(ref);
    return result;
  }
  async function submitReadingReview(item) {
    const project = state.project, view = state.readingReview, offer = view && view.reading_review_offer;
    if (!project || state.busy || state.loading || state.activeJob || !offer || item.confirmed !== true
        || pending.some(row => row.project_ref === project.project_ref)
        || item.project_ref !== project.project_ref || item.input_version !== project.input_version
        || item.brief_sha256 !== project.brief_sha256 || !state.stage1 || !state.stage1.ledger
        || item.ledger_state_sha256 !== state.stage1.ledger.state_sha256
        || item.output_ref !== view.output_ref || item.draft_sha256 !== view.draft_sha256
        || item.offer_ref !== offer.offer_ref || item.offer_sha256 !== offer.offer_sha256) return null;
    const ref = project.project_ref, generation = state.generation, version = project.input_version, brief = project.brief_sha256;
    const result = await mutate("stage1/reading-review", Object.assign(identity(), {ledger_state_sha256: item.ledger_state_sha256, output_ref: item.output_ref, draft_sha256: item.draft_sha256, offer_ref: item.offer_ref, offer_sha256: item.offer_sha256, review: item.review, confirmed: true}), ref);
    if (result && generation === state.generation && state.project && state.project.project_ref === ref
        && state.project.input_version === version && state.project.brief_sha256 === brief) await loadProject(ref);
    return result;
  }
  async function submitCoverage(item) {
    const project = state.project, view = state.stage1 && state.stage1.coverage_actions;
    if (!project || state.busy || state.loading || state.activeJob || !view
        || pending.some(row => row.project_ref === project.project_ref)
        || item.project_ref !== project.project_ref || item.input_version !== project.input_version
        || item.brief_sha256 !== project.brief_sha256 || item.ledger_state_sha256 !== view.ledger_state_sha256
        || !state.stage1.ledger || item.ledger_state_sha256 !== state.stage1.ledger.state_sha256
        || !rows(view, "offers").some(offer => offer.operation === item.operation && offer.offer_ref === item.offer_ref && offer.offer_sha256 === item.offer_sha256)) return null;
    const ref = project.project_ref;
    const result = await mutate("stage1/coverage", Object.assign(identity(), {ledger_state_sha256: item.ledger_state_sha256, operation: item.operation, offer_ref: item.offer_ref, offer_sha256: item.offer_sha256, review: item.review, confirmed: true}), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
    return result;
  }
  async function mutate(operation, body, ref) {
    if (state.busy || state.loading) return null;
    if (pending.some((row) => row.project_ref === (ref || null) && !(operation === "models/retire" && row.kind === "model-operation" && row.key === body.job_ref && row.request_sha256 === body.job_request_sha256))) { notice(t("unsent"), true); return null; }
    state.busy = true; buttons(); notice(t("working"));
    const actionKey = key(); body.key = actionKey;
    let sent = false;
    try {
      const kind = {create: "create", confirm: "submit", "models/actions": "model-operation", "models/retire": "model-retirement", "models/authorize": "model-authorization", "stage2/actions": "stage2-activate", "stage1/sources/authorize": "stage1-source-authorize", "stage1/sources/execute": "stage1-source-execute", "stage1/reading-review": "stage1-reading-registry", "stage1/prepare-delivery": "stage1-produce-records"}[operation] || operation.replace("stage1/", "stage1-");
      const request_sha256 = await requestHash(kind, body);
      remember({ key: actionKey, project_ref: ref || null, operation, kind, request_sha256 });
      sent = true;
      const result = await request(route(ref, operation === "create" ? "" : operation), body);
      // The canonical admission receipt is saved before asynchronous model work.
      // Its saved/queued admission is not a completed call. Only history's exact,
      // source-bound terminal job can reconcile a model-operation key.
      if (operation !== "models/actions" && !["queued", "running", "execution-unknown", "failed-or-unknown"].includes(result.model_status || result.status)) forget(actionKey);
      notice(t(operation.startsWith("stage1/query-") ? "querySaved" : "saved")); return result;
    } catch (error) {
      if (!sent) { pending = pending.filter((row) => row.key !== actionKey); }
      const record = pending.find((row) => row.key === actionKey), receipt = error.receipt;
      if (record && receipt && receipt.key === actionKey && receipt.kind === record.kind && receipt.project_ref === record.project_ref && receipt.request_sha256 === record.request_sha256 && receipt.status === "known-unsent") forget(actionKey);
      notice(t("responseLost") + " (" + error.message + ")", true); return null;
    } finally { state.busy = false; buttons(); }
  }
  function renderProject() {
    document.dispatchEvent(new CustomEvent("project-screening-state", {detail: {project: state.project, stage1: state.stage1, language: state.language}}));
    const project = state.project;
    if (!project) return;
    if (!project.brief) {
      $("project-heading").textContent = "execution-unknown"; $("project-content").hidden = true; $("create-card").hidden = true;
      notice(t("responseLost"), true); buttons(); return;
    }
    $("project-heading").textContent = project.brief.original_description;
    $("topic-heading").textContent = project.brief.original_description;
    $("needs-summary").textContent = project.brief.needs.map((row) => row.question).join(" · ");
    $("project-state").textContent = t(project.intake_report && project.intake_report.necessary_clarification_complete ? "confirmed" : "pending");
    $("stage1-state").textContent = state.stage1 && state.stage1.stage1_status || project.stage1_status || "not-started";
    $("stage2-state").textContent = state.stage2 && state.stage2.activation && state.stage2.activation.stage2_status || project.stage2_status || "not-started";
    $("plan-summary").textContent = t(project.plan ? "planReady" : "planMissing");
    $("model-state").textContent = t(state.modelStatus && (state.modelStatus.blocking_unknown_count ?? state.modelStatus.unknown_count) > 0
      ? "modelHeld" : state.modelOffers.some((row) => row.available === true)
        ? "modelReady" : state.modelStatus && state.modelStatus.authorization_available === true
          ? "modelConfigured" : "modelMissing");
    $("stage2-offer").textContent = t(availableStage2() ? "stage2Ready" : "stage2Missing");
    const budgets = project.settings && project.settings.budgets;
    $("authorization-budget").textContent = budgets ? "1 × Codex · ≤ " + Math.min(budgets.seconds, state.modelStatus && state.modelStatus.local_cap_seconds || 600) + " s · " + budgets.model_calls + " " + t("modelCalls") : "Unknown";
    const ledger = state.stage1 && state.stage1.ledger;
    $("ledger-state").textContent = ledger ? ledger.gate.outcome + " · " + ledger.next_allowed_action : state.stage1 && state.stage1.stage1_status || "unconnected";
    const delivered = state.stage1 && state.stage1.delivery && state.stage1.delivery.canonical_package;
    $("delivery-state").textContent = t(delivered ? "deliverySaved" : availableDelivery() ? "deliveryReady" : "deliveryMissing");
    const artifactArea = $("delivery-artifact"); artifactArea.replaceChildren();
    if (delivered) {
      text(artifactArea, "p", delivered.status + " · " + delivered.counts.papers + " · " + delivered.artifact_kind);
      text(artifactArea, "p", "SHA-256: " + delivered.manifest_sha256, "subtle");
    }
    const queries = $("ledger-queries"); queries.replaceChildren();
    for (const query of state.stage1 && state.stage1.queries || []) { const card = document.createElement("div"); card.className = "history-row"; queries.append(card); text(card, "p", query.query); text(card, "p", query.purpose + " · " + query.status, "subtle"); }
    renderQueries();
    renderSources();
    renderReadingOffers();
    $("create-card").hidden = true; $("project-content").hidden = false;
    $("intake-card").open = !Boolean(project.intake_report && project.intake_report.necessary_clarification_complete);
    buttons();
  }
  function renderQueries() {
    const value = state.stage1 && state.stage1.query_execution;
    $("query-state").textContent = value ? value.status : t("queryUnavailable");
    const limits = $("query-limits"), history = $("query-observations");
    limits.replaceChildren(); history.replaceChildren();
    if (!value) return;
    const allowed = value.limits || value.authorization_offer && value.authorization_offer.document && value.authorization_offer.document.limits;
    if (allowed) text(limits, "p", t("queryAttempts") + ": ≤ " + allowed.max_attempts + " · " + t("seconds") + ": ≤ " + allowed.max_reserved_seconds + " · " + t("queryResultLimit") + ": ≤ " + allowed.max_results);
    if (value.budget) text(limits, "p", t("queryBudget") + ": " + value.budget.attempts + " " + t("queryAttempts") + " · " + value.budget.seconds + " s · " + t("queryProbes") + ": " + value.budget.probes, "subtle");
    text(limits, "p", t("queryNoReading"), "subtle");
    if (value.refusal || value.query_offer_refusal) text(limits, "p", value.refusal || value.query_offer_refusal, "subtle");
    const offered = value.query_offer && value.query_offer.document;
    if (offered) { text(history, "strong", t("queryOffer")); text(history, "p", offered.backend + " · " + (offered.arguments && offered.arguments.query || offered.planned_id)); }
    const observations = (value.jobs || []).concat(rows(value.query_history, "history"));
    if (observations.length) text(history, "strong", t("queryHistory"));
    for (const row of observations) {
      const card = document.createElement("div"); card.className = "history-row"; history.append(card);
      text(card, "p", (row.operation || row.action || "runtime") + " · " + (row.status || "Unknown"));
      if (row.error || row.failure) text(card, "p", typeof row.error === "object" ? row.error.code : row.error || row.failure);
      const observation = row.result || row.receipt;
      if (observation) text(card, "p", observation.execution_ref || observation.probe_observation || observation.outcome || "Unknown", "subtle");
    }
  }
  function availableDelivery() {
    const delivery = state.stage1 && state.stage1.delivery;
    if (!delivery || delivery.canonical_package && delivery.canonical_package.status === "saved-evidence-validated") return null;
    return (delivery.offers || []).find((row) => row.status === "ready-for-saved-evidence-delivery") || null;
  }
  function availableSavedPreparation() {
    const stage1 = state.stage1;
    return Boolean(stage1 && stage1.ledger && stage1.checkpoint && stage1.checkpoint.current === true && stage1.saved_records_connected === true);
  }
  function renderSources() {
    const source = state.stage1 && state.stage1.source_execution;
    if (!source) return;
    const area = $("query-observations"), lang = state.language;
    text(area, "strong", {en: "Public source jobs", "zh-Hans": "公开来源任务", "zh-Hant": "公開來源任務"}[lang] || "Public source jobs");
    text(area, "p", {en: "Acquisition, parsing and reading are separate observations. Refresh reads saved history and never repeats execution.", "zh-Hans": "取得、解析和阅读分别记录。刷新只读取历史，不会重复执行。", "zh-Hant": "取得、解析及閱讀分別記錄。重新整理只讀取歷史，不會重複執行。"}[lang], "subtle");
    for (const job of Object.values(source.jobs || {})) {
      const card = text(area, "div", "", "history-row");
      text(card, "p", job.work_ref + " · " + job.status);
      if (job.failure) text(card, "p", job.failure.code || "Unknown", "subtle");
      if (job.processing) text(card, "p", job.processing.status || "Unknown", "subtle");
    }
    const project = state.project;
    for (const grant of Object.values(source.grants || {})) {
      if (!project || grant.status !== "authorized" || grant.input_version !== project.input_version
          || grant.brief_sha256 !== project.brief_sha256 || grant.expires_at * 1000 <= Date.now()
          || Object.values(source.jobs || {}).some(job => job.grant_ref === grant.grant_ref)) continue;
      const card = text(area, "div", "", "history-row");
      text(card, "p", grant.work_ref + " · " + {en: "Permission saved; not executed", "zh-Hans": "许可已保存，尚未执行", "zh-Hant": "許可已保存，尚未執行"}[lang]);
      const button = text(card, "button", {en: "Execute this saved source permission", "zh-Hans": "执行此保存的来源许可", "zh-Hant": "執行此已保存的來源許可"}[lang]);
      button.type = "button";
      button.onclick = guarded(() => executeSourceGrant(grant, project.project_ref, project.input_version, project.brief_sha256));
    }
  }
  async function executeSourceGrant(grant, ref, version, brief) {
    if (state.busy || state.loading || !grant.grant_ref || !grant.grant_sha256) return;
    await loadProject(ref);
    if (!state.project || state.project.project_ref !== ref || state.project.input_version !== version
        || state.project.brief_sha256 !== brief) return;
    const result = await mutate("stage1/sources/execute", Object.assign(identity(), {
      grant_ref: grant.grant_ref, grant_sha256: grant.grant_sha256, confirmed: true
    }), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  function renderReadingOffers() {
    const project = state.project, lang = state.language;
    if (!project) return;
    for (const offer of state.modelOffers) {
      if (offer.operation !== "read-paper" || offer.available !== true || offer.input_version !== project.input_version
          || offer.brief_sha256 !== project.brief_sha256) continue;
      const card = text($("query-observations"), "div", "", "history-row");
      text(card, "p", offer.work_ref + " · " + {en: "Reading permission saved; not executed", "zh-Hans": "阅读许可已保存，尚未执行", "zh-Hant": "閱讀許可已保存，尚未執行"}[lang]);
      const button = text(card, "button", {en: "Execute this saved reading permission", "zh-Hans": "执行此保存的阅读许可", "zh-Hant": "執行此已保存的閱讀許可"}[lang]);
      button.type = "button";
      button.onclick = guarded(() => executeReadingOffer(offer, project.project_ref, project.input_version, project.brief_sha256));
    }
  }
  async function executeReadingOffer(offer, ref, version, brief) {
    if (state.busy || state.loading) return;
    await loadProject(ref);
    if (!state.project || state.project.project_ref !== ref || state.project.input_version !== version
        || state.project.brief_sha256 !== brief || !state.modelOffers.some(row => row.offer_ref === offer.offer_ref
          && row.offer_sha256 === offer.offer_sha256 && row.available === true)) return;
    const result = await mutate("models/actions", Object.assign(identity(), {
      offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, confirmed: true
    }), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  async function refreshList() {
    const value = await request(route());
    const projects = rows(value, "projects");
    const list = $("project-list"); list.replaceChildren();
    if (!projects.length) text(list, "p", t("noProjects"), "subtle");
    for (const project of projects) {
      const button = text(list, "button", project.topic || project.original_description || project.project_ref);
      button.type = "button";
      button.setAttribute("aria-current", String(Boolean(state.project && state.project.project_ref === project.project_ref)));
      button.onclick = () => loadProject(project.project_ref).catch((error) => notice(error.message, true));
    }
  }
  async function loadProject(ref) {
    const generation = ++state.generation;
    document.dispatchEvent(new Event("project-screening-clear"));
    state.readingReview = null; ++state.readingGeneration;
    state.modelHistory = []; state.historyNext = null; state.output = null;
    $("output-reader").hidden = true; $("history-more").hidden = true;
    state.loading = true; state.activeJob = false; state.modelOffers = []; state.modelStatus = null; state.stage1 = null; state.stage2 = null; buttons();
    try {
      const snapshot = await request(route(ref, "overview")), project = snapshot.project;
      if (generation !== state.generation) return;
      state.project = project;
      $("confirm-form").reset(); $("revised-topic").value = project.brief ? project.brief.original_description : "";
      const settings = project.settings;
      if (settings) {
        $("resources").value = settings.resource_envelope; $("confirmation").value = settings.user_input;
        for (const [name, id] of Object.entries(budgetIds)) $(id).value = settings.budgets[name];
        $("search-consent").checked = settings.consent.external_search; $("read-consent").checked = settings.consent.public_source_read;
      }
      renderProject();
      state.modelOffers = rows(snapshot.model_offers, "offers"); state.stage2 = snapshot.stage2;
      state.modelStatus = snapshot.models; state.stage1 = snapshot.stage1;
      renderProject(); await refreshList(); await history(); await native();
    } finally { if (generation === state.generation) { state.loading = false; buttons(); } }
  }
  function identity() {
    const project = state.project;
    return { revision: project.revision, input_version: project.input_version, brief_sha256: project.brief_sha256 };
  }
  function reconcile(rowsToCheck) {
    for (const row of rowsToCheck) {
      const record = pending.find((item) => item.key === row.key);
      const safeTerminal = row.kind === "model-operation"
        ? row.operation ? ["content-review-pending", "plan-validated-not-executed", "validation-failed"].includes(row.status) || Boolean(row.retirement && row.retirement.status === "retired-no-resend" && row.retirement.job_request_sha256 === row.request_sha256 && row.retirement.evidence && row.retirement.evidence.basis === "never-admitted-no-runtime") : row.status === "known-unsent"
        : ["saved", "failed", "known-unsent"].includes(row.status);
      if (record && safeTerminal && row.kind === record.kind && row.project_ref === record.project_ref && row.request_sha256 === record.request_sha256) forget(row.key);
    }
  }
  async function history(more = false) {
    const ref = state.project && state.project.project_ref;
    const generation = state.generation;
    if (!ref) return;
    if (state.historyBusy) return;
    state.historyBusy = true; $("history-more").disabled = true;
    let replies;
    try { replies = await Promise.allSettled([
      request(route(ref, "history")), request(route(ref, more ? "models/actions/" + state.historyNext : "models/actions/0")), request(route(ref, "stage2/actions"))
    ]); } finally { state.historyBusy = false; $("history-more").disabled = false; }
    if (generation !== state.generation || !state.project || state.project.project_ref !== ref) return;
    const list = $("history"); list.replaceChildren();
    let all = [];
    for (const reply of replies) if (reply.status === "fulfilled") {
      const value = reply.value;
      all = all.concat(rows(value, "actions"));
    }
    // Terminal model observations must carry the original, server-saved intent
    // identity. A queued admission or an arbitrary operation name is not proof.
    if (replies[0].status === "fulfilled") reconcile(rows(replies[0].value, "actions"));
    if (replies[1].status === "fulfilled") {
      const page = replies[1].value;
      state.modelHistory = (more ? state.modelHistory : []).concat(rows(page, "actions"));
      state.historyNext = Number.isInteger(page.next_offset) ? page.next_offset : null;
    }
    all = all.concat(state.modelHistory, rows(state.modelStatus, "jobs"));
    reconcile(all);
    $("history-more").hidden = state.historyNext === null;
    if (bootstrap.models && replies[1].status !== "fulfilled") {
      text(list, "p", t("responseLost"), "subtle");
    }
    const unique = new Map();
    for (const row of all) {
      const existing = unique.get(row.key);
      if (!existing || row.operation || !existing.operation) unique.set(row.key, row);
    }
    all = Array.from(unique.values());
    state.activeJob = Boolean(bootstrap.models && !state.modelStatus) || Boolean(state.modelStatus && (rows(state.modelStatus, "active_jobs").length || (state.modelStatus.blocking_unknown_count ?? state.modelStatus.unknown_count)));
    for (const row of all) {
      const card = document.createElement("div"); card.className = "history-row"; list.append(card);
      text(card, "strong", (row.operation || row.kind || row.action || "action") + " · " + (row.status || "Unknown"));
      if (row.error || row.failure) text(card, "p", row.error || row.failure);
      if (row.retirement && row.retirement.status === "retired-no-resend") text(card, "p", t("retired"), "subtle");
      else if (row.retirement_offer) {
        const offer = row.retirement_offer;
        text(card, "p", t(offer.available ? "retirementHelp" : "retirementBlocked"), "subtle");
        if (offer.available) {
          const label = text(card, "label", t("retirementReason"));
          const input = document.createElement("input"); label.append(input); input.maxLength = 4096;
          const button = text(card, "button", t("retire")); button.type = "button";
          button.dataset.modelRetire = offer.job_ref;
          button.disabled = state.busy || state.loading;
          button.onclick = guarded(async () => {
            if (!state.project || state.project.project_ref !== ref || !input.value.trim() || !bounded(input.value, 4096)) return;
            const result = await mutate("models/retire", Object.assign(identity(), {job_ref: offer.job_ref, job_request_sha256: offer.job_request_sha256, job_snapshot_sha256: offer.job_snapshot_sha256, confirmed: true, user_input: input.value}), ref);
            if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
          });
        }
      }
      const result = row.result || row;
      if (result.output_preview || result.output || result.final_text || result.proposal_text || result.text) text(card, "pre", result.output_preview || result.output || result.final_text || result.proposal_text || result.text);
      if (result.output_truncated) text(card, "p", t("preview"), "subtle");
      if (result.output_ref && result.output_sha256) { const button = text(card, "button", t("viewOutput")); button.type = "button"; button.onclick = guarded(() => readOutput(ref, result.output_ref, 0, result.output_sha256)); }
      if (window.ResearchProjectReading && result.reading_draft && /^[0-9a-f]{64}$/.test(result.reading_draft.sha256 || "") && /^[0-9a-f]{64}$/.test(result.output_ref || "")) {
        const button = text(card, "button", window.ResearchProjectReading.text("open")); button.type = "button";
        button.dataset.readingDraft = result.output_ref; button.dataset.readingInput = String(result.input_version); button.dataset.readingBrief = result.brief_sha256;
        button.onclick = guarded(() => openReadingDraft(ref, result));
      }
      if (result.plan || result.plan_manifest_sha256) text(card, "p", t("planReady"));
      if (result.import_status || result.workflow_status) text(card, "p", result.import_status || result.workflow_status);
      const details = document.createElement("details"); card.append(details); text(details, "summary", t("sourceDetails"));
      text(details, "pre", JSON.stringify({ key: row.key, input_version: row.input_version, brief_sha256: row.brief_sha256, source_sha256: row.source_sha256, result_sha256: row.result_sha256 }, null, 2));
    }
    if (!all.length) text(list, "p", t("emptyHistory"), "subtle");
    buttons();
  }
  async function readOutput(ref, outputRef, offset = 0, expectedSha = null) {
    const generation = state.generation;
    const saved = state.output;
    if (offset && (!saved || saved.ref !== ref || saved.outputRef !== outputRef || saved.next !== offset)) return;
    const outputGeneration = ++state.outputGeneration;
    const sha = offset ? saved.sha : expectedSha;
    if (typeof sha !== "string" || !/^[0-9a-f]{64}$/.test(sha)) return;
    $("output-next").disabled = true;
    try {
      const page = await request(route(ref, "models/outputs/" + encodeURIComponent(outputRef) + "/" + offset));
      if (generation !== state.generation || outputGeneration !== state.outputGeneration || !state.project || state.project.project_ref !== ref) return;
      if (page.project_ref !== ref || page.output_ref !== outputRef || page.offset !== offset || page.output_sha256 !== sha) throw new Error("output-binding-differs");
      state.output = {ref, outputRef, sha: page.output_sha256, next: page.next_offset};
      $("output-text").textContent = (offset ? $("output-text").textContent : "") + page.text;
      $("output-identity").textContent = "v" + page.input_version + " · " + page.output_sha256;
      $("output-reader").hidden = false; $("output-next").hidden = page.next_offset === null;
    } finally { if (outputGeneration === state.outputGeneration) $("output-next").disabled = false; }
  }
  async function recover() {
    for (const record of [...pending].filter((row) => row.project_ref === null)) {
      try {
        const value = await request("/api/projects/actions/" + encodeURIComponent(record.key));
        const action = value.action;
        if (action && action.key === record.key && action.kind === record.kind && action.request_sha256 === record.request_sha256 && ["saved", "failed", "known-unsent"].includes(action.status)) {
          forget(record.key);
          if (action.status === "saved" && action.project_ref && !state.project) await loadProject(action.project_ref);
        }
      } catch (_) { /* Unobserved admission stays unresolved; never infer it was unsent. */ }
    }
    await refreshList(); if (state.project) await history(); buttons();
  }
  let nativePending = [];
  const nativeStorage = "harness-project-native-intents-v1";
  try { nativePending = JSON.parse(sessionStorage.getItem(nativeStorage) || "[]"); } catch (_) {}
  if (!Array.isArray(nativePending)) nativePending = [];
  nativePending = nativePending.filter((row) => row && typeof row.key === "string" && typeof row.project_ref === "string" && typeof row.target === "string");
  function nativeObservationMatches(record, action) {
    return action && action.kind === "ProjectNativeActionObservation.v1" && action.key === record.key && action.project_ref === record.project_ref && action.target_ref === record.target && action.operation === record.operation && /^[0-9a-f]{64}$/.test(record.request_sha256) && action.request_sha256 === record.request_sha256 && ["known-unsent", "result-observed"].includes(action.status);
  }
  function reconcileNative(actions) {
    if (!Array.isArray(actions)) return;
    nativePending = nativePending.filter((record) => !actions.some((action) => nativeObservationMatches(record, action)));
    try { sessionStorage.setItem(nativeStorage, JSON.stringify(nativePending)); } catch (_) {}
  }
  async function native() {
    const ref = state.project && state.project.project_ref, generation = state.generation;
    if (!ref) return;
    let observed;
    try { observed = await request(route(ref, "models/native")); } catch (_) { observed = null; }
    if (generation !== state.generation || !state.project || state.project.project_ref !== ref) return;
    const area = $("native-questions"); area.replaceChildren();
    // Only bound durable broker observations reconcile an intent. A provider's
    // client_key, HTTP error or queued/unknown outcome alone cannot release it.
    reconcileNative(observed && observed.native_actions);
    const view = observed && observed.native_view;
    if (!view || !Array.isArray(view.requests) || !Array.isArray(view.operations) || !Array.isArray(view.actions)) { text(area, "p", t("nativeEmpty")); return; }
    const held = (target) => nativePending.some((row) => row.project_ref === ref && row.target === target);
    for (const question of view.requests.filter((row) => row.status === "pending")) {
      const card = document.createElement("form"); card.className = "history-row"; area.append(card);
      if (question.method === "item/tool/requestUserInput") {
        const answers = [];
        for (const row of question.payload.questions || []) {
          const label = text(card, "label", row.question), field = document.createElement("input");
          field.type = row.isSecret ? "password" : "text"; field.maxLength = 4096; field.required = true;
          field.setAttribute("aria-label", row.question); label.append(field); answers.push([row.id, field]);
          for (const option of row.options || []) { const button = text(card, "button", option.label); button.type = "button"; button.onclick = () => { field.value = option.label; }; }
        }
        const button = text(card, "button", t("sendAnswer")); button.type = "submit";
        button.disabled = held(question.request_ref) || Boolean(view.failure);
        card.onsubmit = guarded((event) => { event.preventDefault(); return nativeSubmit(ref, view, question, "answer", {answers: Object.fromEntries(answers.map(([id, field]) => [id, {answers: [field.value]}]))}); });
      } else if (["item/commandExecution/requestApproval", "item/fileChange/requestApproval"].includes(question.method)) {
        text(card, "p", t("nativeHelp"));
        for (const decision of ["decline", "cancel"]) { const button = text(card, "button", t(decision)); button.type = "button"; button.disabled = held(question.request_ref) || Boolean(view.failure); button.onclick = guarded(() => nativeSubmit(ref, view, question, "answer", {decision})); }
      } else text(card, "p", "unsupported");
      if (held(question.request_ref)) text(card, "p", t("responseLost"), "subtle");
    }
    for (const action of view.operations.filter((row) => row.can_interrupt === true)) {
      const button = text(area, "button", t("interrupt")); button.type = "button";
      button.disabled = held(action.action_ref) || Boolean(view.failure);
      button.onclick = guarded(() => nativeSubmit(ref, view, action, "interrupt"));
    }
    if (!area.childElementCount) text(area, "p", t("nativeEmpty"));
  }
  async function nativeSubmit(ref, view, target, kind, result) {
    const targetRef = target.request_ref || target.action_ref;
    if (nativePending.some((row) => row.project_ref === ref && row.target === targetRef) || !state.project || state.project.project_ref !== ref || state.loading) return;
    const actionKey = key(), body = {key: actionKey, revision: view.revision, index_sha256: view.index_sha256, input_version: view.input_version};
    if (kind === "answer") Object.assign(body, {request_ref: target.request_ref, request_sha256: target.request_sha256, result});
    else Object.assign(body, {action_ref: target.action_ref, action_sha256: target.action_sha256});
    if (!bounded(JSON.stringify(body), 32768)) { notice(t("tooLarge"), true); return; }
    const generation = state.generation, request_sha256 = await nativeRequestHash(kind, body);
    if (generation !== state.generation || !state.project || state.project.project_ref !== ref || state.loading || nativePending.some((row) => row.project_ref === ref && row.target === targetRef)) return;
    const record = {key: actionKey, project_ref: ref, target: targetRef, operation: kind, request_sha256};
    sessionStorage.setItem(nativeStorage, JSON.stringify([...nativePending, record])); nativePending.push(record);
    try { await request(route(ref, "models/native/" + kind), body); }
    catch (error) { notice(t("responseLost") + " (" + error.message + ")", true); }
    finally { if (state.project && state.project.project_ref === ref) await native(); }
  }
  function translate() {
    document.documentElement.lang = state.language;
    document.querySelectorAll("[data-text]").forEach((node) => { node.textContent = t(node.dataset.text); });
    renderProject();
    const list = $("view-list"); list.replaceChildren();
    if (!bootstrap.views.length) text(list, "p", t("none"), "subtle");
    for (const view of bootstrap.views) {
      // Trusted same-origin host URLs, never a document-supplied link.
      if (!/^\/views\/[A-Za-z0-9_-]{1,64}\/atlas\.html$/.test(view.url)) continue;
      const link = text(list, "a", view.label); link.href = view.url;
    }
    buttons();
  }
  $("language").onchange = guarded(async () => { state.language = $("language").value; translate(); if (state.project) await Promise.all([history(), native()]); });
  $("new-project").onclick = () => { document.dispatchEvent(new Event("project-screening-clear")); ++state.generation; state.loading = false; state.project = null; state.modelOffers = []; state.stage2 = null; $("create-card").hidden = false; $("project-content").hidden = true; $("project-heading").textContent = t("workspace"); buttons(); $("topic").focus(); };
  $("create-form").onsubmit = async (event) => {
    event.preventDefault();
    const generation = state.generation;
    const topic = $("topic").value, questions = $("needs").value.split("\n").filter((line) => line.trim());
    if (!topic.trim() || !questions.length || questions.length > 20) return;
    if (!bounded(topic, 4096) || questions.some((question) => !bounded(question, 4096))) { notice(t("tooLarge"), true); return; }
    const result = await mutate("create", { topic, needs: questions.map((question, index) => ({ need_id: "need-" + (index + 1), question })), scope_fields: [{ field: "geography", material: true, reason: "The researcher must explicitly specify, leave unrestricted, or explain why geography is not applicable." }] });
    if (result && generation === state.generation) { const ref = result.project_ref || result.result && result.result.project_ref; if (ref) await loadProject(ref); else await refreshList(); }
  };
  const budgetIds = { model_calls: "model-calls", seconds: "seconds", search_calls: "search-calls", source_reads: "source-reads", rounds: "rounds" };
  function resourcesBody() {
    if (![[$("confirmation").value, 4096], [$("resources").value, 8192], [$("geography-value").value, 4096]].every(([value, limit]) => bounded(value, limit))) { notice(t("tooLarge"), true); return null; }
    return Object.assign(identity(), {
      resource_envelope: $("resources").value,
      budgets: Object.fromEntries(Object.entries(budgetIds).map(([name, id]) => [name, Number($(id).value)])),
      consent: { external_search: $("search-consent").checked, public_source_read: $("read-consent").checked, browser_fallback: false },
      user_input: $("confirmation").value, confirmed: true
    });
  }
  async function confirm(event) {
    event.preventDefault(); if (state.loading || !state.project) return;
    const status = $("geography").value, input = $("confirmation").value;
    if (!status || !input.trim() || (status !== "unrestricted" && !$("geography-value").value.trim())) { notice(t("missingChoice"), true); return; }
    const body = resourcesBody(); if (!body) return;
    Object.assign(body, {
      choices: [{ field: "geography", status, value: status === "specified" ? $("geography-value").value : null, reason: $("geography-value").value || input, user_input: input }],
      formal_target: Number($("formal-count").value), priority_reading_target: Number($("priority-count").value),
    });
    const ref = state.project.project_ref, result = await mutate("confirm", body, ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  function guarded(action) { return (event) => Promise.resolve(action(event)).catch((error) => notice(error.message, true)); }
  $("create-form").onsubmit = guarded($("create-form").onsubmit);
  $("confirm-form").onsubmit = guarded(confirm);
  $("configure").onclick = guarded(async () => {
    if (state.loading || !state.project) return;
    const body = resourcesBody(); if (!body) return;
    const ref = state.project.project_ref, result = await mutate("configure", body, ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  });
  $("revise-form").onsubmit = guarded(async (event) => {
    event.preventDefault(); if (state.loading || !state.project) return;
    const topic = $("revised-topic").value; if (!bounded(topic, 4096)) { notice(t("tooLarge"), true); return; }
    const ref = state.project.project_ref, result = await mutate("revise", Object.assign(identity(), {topic}), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  });
  async function model(operation) {
    const offer = state.modelOffers.find((row) => row.operation === operation && row.available === true);
    if (!offer) return;
    const ref = state.project.project_ref;
    const result = await mutate("models/actions", Object.assign(identity(), { offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, confirmed: true }), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  $("suggest-topic").onclick = guarded(() => model("suggest-topic"));
  $("plan-search").onclick = guarded(() => model("plan-search"));
  async function authorize(operation) {
    if (!state.project || state.loading) return;
    const input = $("model-consent").value;
    if (!input.trim() || !bounded(input, 4096)) { notice(t("missingChoice"), true); return; }
    const ref = state.project.project_ref;
    const result = await mutate("models/authorize", Object.assign(identity(), {operation, user_input: input, confirmed: true}), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  $("authorize-topic").onclick = guarded(() => authorize("suggest-topic"));
  $("authorize-plan").onclick = guarded(() => authorize("plan-search"));
  document.addEventListener("project-screen-paper", guarded(async event => {
    const item = event.detail, project = state.project;
    if (!project || state.loading || state.busy || !item || item.project_ref !== project.project_ref
        || item.input_version !== project.input_version || item.brief_sha256 !== project.brief_sha256) return;
    if (!["include", "exclude", "pending"].includes(item.decision) || !item.rationale.trim() || !bounded(item.rationale, 4096)) {
      notice(t("missingChoice"), true); return;
    }
    const ref = project.project_ref;
    await loadProject(ref);
    if (!state.project || state.project.project_ref !== ref || state.project.input_version !== item.input_version
        || state.project.brief_sha256 !== item.brief_sha256 || !state.stage1 || !state.stage1.ledger) return;
    if (state.stage1.ledger.state_sha256 !== item.ledger_state_sha256) { notice(t("recovered"), true); return; }
    const result = await mutate("stage1/screen", Object.assign(identity(), {
      ledger_state_sha256: item.ledger_state_sha256, work_ref: item.work_ref,
      decision: item.decision, rationale: item.rationale, confirmed: true
    }), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }));
  document.addEventListener("project-acquire-paper", guarded(async event => {
    const item = event.detail, project = state.project;
    if (!project || state.loading || state.busy || !item || item.project_ref !== project.project_ref
        || item.input_version !== project.input_version || item.brief_sha256 !== project.brief_sha256) return;
    const ref = project.project_ref;
    await loadProject(ref);
    if (!state.project || state.project.project_ref !== ref || state.project.input_version !== item.input_version
        || state.project.brief_sha256 !== item.brief_sha256) return;
    const offer = await request(route(ref, "stage1/sources/works/" + encodeURIComponent(item.work_ref)));
    if (!offer || offer.runner_connected !== true || !offer.offer_ref || !offer.offer_sha256) return;
    const permission = await mutate("stage1/sources/authorize", Object.assign(identity(), {
      work_ref: item.work_ref, offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, confirmed: true
    }), ref);
    if (!permission) return;
    const grant = permission.result || permission;
    await executeSourceGrant(grant, ref, item.input_version, item.brief_sha256);
  }));
  document.addEventListener("project-read-paper", guarded(async event => {
    const item = event.detail, project = state.project;
    if (!project || state.loading || !item || item.project_ref !== project.project_ref
        || item.input_version !== project.input_version || item.brief_sha256 !== project.brief_sha256) return;
    const input = $("model-consent").value;
    if (!input.trim() || !bounded(input, 4096)) { notice(t("missingChoice"), true); $("model-consent").focus(); return; }
    const ref = project.project_ref;
    const permission = await mutate("models/authorize", Object.assign(identity(), {
      operation: "read-paper", work_ref: item.work_ref, snapshot_sha256: item.snapshot_sha256,
      user_input: input, confirmed: true
    }), ref);
    if (!permission || !state.project || state.project.project_ref !== ref) return;
    await loadProject(ref);
    const granted = permission.result || permission;
    const offer = state.modelOffers.find(row => row.offer_ref === granted.offer_ref && row.offer_sha256 === granted.offer_sha256
      && row.operation === "read-paper" && row.work_ref === item.work_ref
      && row.snapshot_sha256 === item.snapshot_sha256 && row.available === true);
    if (!offer) return;
    await executeReadingOffer(offer, ref, item.input_version, item.brief_sha256);
  }));
  $("native-refresh").onclick = guarded(() => native());
  async function ledger(operation) {
    if (!state.project || !state.stage1 || state.loading) return;
    const body = Object.assign(identity(), {confirmed: true});
    if (operation === "initialize") { const offer = state.stage1.initialization_offer; if (!offer) return; Object.assign(body, {offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256}); }
    else { if (!state.stage1.ledger) return; body.ledger_state_sha256 = state.stage1.ledger.state_sha256; }
    if (operation === "deliver") { const offer = availableDelivery(); if (!offer) return; Object.assign(body, {offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256}); }
    if (operation === "prepare-delivery") { if (!availableSavedPreparation()) return; body.checkpoint_event_id = state.stage1.checkpoint.event_id; }
    const ref = state.project.project_ref, generation = state.generation, version = state.project.input_version, brief = state.project.brief_sha256;
    const result = await mutate("stage1/" + operation, body, ref);
    if (result && generation === state.generation && state.project && state.project.project_ref === ref
        && state.project.input_version === version && state.project.brief_sha256 === brief) await loadProject(ref);
  }
  $("ledger-init").onclick = guarded(() => ledger("initialize"));
  $("ledger-checkpoint").onclick = guarded(() => ledger("checkpoint"));
  $("ledger-export").onclick = guarded(() => ledger("export"));
  $("ledger-prepare").onclick = guarded(() => ledger("prepare-delivery"));
  $("ledger-deliver").onclick = guarded(() => ledger("deliver"));
  async function queryAction(operation, field) {
    if (!state.project || state.loading || !state.stage1) return;
    const view = state.stage1.query_execution, offer = view && view[field];
    if (!offer) return;
    const body = Object.assign(identity(), {offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, confirmed: true});
    if (operation === "authorize") {
      const value = $("query-consent").value;
      if (!value.trim() || !bounded(value, 4096)) { notice(t("missingChoice"), true); return; }
      body.user_input = value;
    }
    const ref = state.project.project_ref, result = await mutate("stage1/query-" + operation, body, ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  }
  $("query-authorize").onclick = guarded(() => queryAction("authorize", "authorization_offer"));
  $("query-bootstrap").onclick = guarded(() => queryAction("bootstrap", "bootstrap_offer"));
  $("query-execute").onclick = guarded(() => queryAction("execute", "query_offer"));
  $("query-restore-owner").onclick = guarded(() => queryAction("restore-owner", "owner_offer"));
  $("activate-stage2").onclick = guarded(async () => {
    const offer = availableStage2(); if (!offer) return;
    const ref = state.project.project_ref;
    const result = await mutate("stage2/actions", Object.assign(identity(), { offer_ref: offer.offer_ref, offer_sha256: offer.offer_sha256, confirmed: true }), ref);
    if (result && state.project && state.project.project_ref === ref) await loadProject(ref);
  });
  $("refresh").onclick = guarded(async () => { await recover(); if (state.project) await loadProject(state.project.project_ref); notice(t("recovered")); });
  $("history-refresh").onclick = guarded(async () => { await recover(); if (state.project) await loadProject(state.project.project_ref); notice(t("recovered")); });
  $("history-more").onclick = guarded(() => state.historyNext !== null && history(true));
  $("output-next").onclick = guarded(() => state.output && state.output.next !== null && readOutput(state.output.ref, state.output.outputRef, state.output.next));
  $("recover-intents").onclick = guarded(async () => { await recover(); if (state.project) await loadProject(state.project.project_ref); notice(t("recovered")); });
  translate();
  recover().catch((error) => notice(error.message, true));
  if (pending.length) notice(t("responseLost"), true);
}());
