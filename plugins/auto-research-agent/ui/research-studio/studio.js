(() => {
  const root = document.getElementById('research-studio-preview'),
    $ = id => root.querySelector('#' + id),
    esc = v => String(v).replace(/[&<>"']/g, c => ({
      '&': '&amp;',
      '<': '&lt;',
      '>': '&gt;',
      '"': '&quot;',
      "'": '&#39;'
    })[c]);
  const stages = [null, {
    name: '文献发现与证据',
    short: '文献与证据',
    goal: '建立可追溯的文献池，让研究判断连接到原文证据。',
    input: '研究主题、检索范围与预算',
    output: '文献表、证据报告、原始记录',
    title: '文献覆盖概览',
    gate: '审阅检索范围、来源完整性与证据质量，再进入文献比较。',
    nodes: ['检索', '筛选', '原文证据']
  }, {
    name: '文献比较与研究缺口',
    short: '比较与缺口',
    goal: '统一比较研究方法、评价条件与局限，识别有证据支持的研究机会。',
    input: '审阅后的文献池与证据',
    output: '比较矩阵、研究缺口与证据链',
    title: '比较矩阵与研究缺口',
    gate: '确认比较口径一致、缺口有证据支持，再确定研究问题。',
    nodes: ['文献比较', '证据空白', '研究问题']
  }, {
    name: '研究设计与可行性',
    short: '设计与可行性',
    goal: '明确研究假设、实验对照与资源边界，形成可以批准执行的方案。',
    input: '研究问题、数据与可用资源',
    output: '实验计划、可行性与预算',
    title: '研究设计蓝图',
    gate: '批准实验配置、资源预算与评价判据后，再启动实验。',
    nodes: ['研究假设', '对照与基线', '评价指标']
  }, {
    name: '实验执行',
    short: '实验执行',
    goal: '按批准的配置运行实验，集中查看日志、失败原因与原始结果。',
    input: '批准后的方案与固定配置',
    output: '实验日志、原始结果与清单',
    title: '实验任务与运行轨迹',
    gate: '确认实验与失败记录完整，结果与配置一一对应。',
    nodes: ['任务队列', '运行日志', '原始结果']
  }, {
    name: '分析与图表',
    short: '分析与图表',
    goal: '从原始结果生成对比、消融与不确定性分析，让每张图可回到源数据。',
    input: '原始结果、基线与评价方案',
    output: '统计结果、图表与结论',
    title: '结果分析与不确定性',
    gate: '核对分析口径、对照条件与证据边界，再进入写作。',
    nodes: ['数据与指标', '比较与误差', '结论与局限']
  }, {
    name: '写作与投稿',
    short: '写作与投稿',
    goal: '组织论文与投稿材料，将关键主张连接到文献、实验和图表。',
    input: '审阅后的结论、图表与引用',
    output: '论文草稿、引用检查与投稿包',
    title: '论文结构与证据关联',
    gate: '完成内容与引用审阅；对外提交需要单独确认。',
    nodes: ['章节草稿', '图表与引用', '投稿准备']
  }];
  const topics = {
    traffic: {
      name: '强化学习交通信号控制',
      slug: 'traffic-control',
      rows: ['单路口控制', '多智能体协同', '泛化与迁移']
    },
    speech: {
      name: '语音情绪识别',
      slug: 'speech-emotion',
      rows: ['特征与模型', '说话人独立', '跨语料泛化']
    },
    custom: {
      name: '我的研究主题',
      slug: 'custom-project',
      rows: ['核心方法', '评价设计', '外部验证']
    }
  };
  const runs = [{
    id: 'run-015',
    stage: 2,
    status: 'completed',
    label: '示例已完成',
    description: '比较矩阵与研究缺口 · 3 项示例产物',
    time: '示例 · 第 3 次'
  }, {
    id: 'run-014',
    stage: 1,
    status: 'human-review',
    label: '示例待审阅',
    description: '文献发现与证据 · 6 项示例文件',
    time: '示例 · 第 2 次'
  }, {
    id: 'run-013',
    stage: 1,
    status: 'failed',
    label: '示例失败',
    description: '来源连接超时；保留部分响应、错误日志与清单',
    time: '示例 · 第 1 次'
  }];
  const files = [{
    id: 'csv',
    name: 'literature.csv',
    type: 'CSV',
    version: 'v1.0',
    stage: 1,
    run: 'run-014',
    folder: 'project',
    review: '示例 · 待核验',
    input: ['raw', 'config'],
    next: ['report', 'matrix', 'comparison'],
    kind: 'table',
    path: 'artifacts/literature.csv'
  }, {
    id: 'report',
    name: 'literature_review.md',
    type: 'MD',
    version: 'v1.0',
    stage: 1,
    run: 'run-014',
    folder: 'project',
    review: '示例 · 待审阅',
    input: ['config', 'csv', 'raw'],
    next: ['comparison'],
    kind: 'report',
    path: 'artifacts/literature_review.md'
  }, {
    id: 'chart',
    name: 'coverage.svg',
    type: 'SVG',
    version: 'v1.0',
    stage: 1,
    run: 'run-014',
    folder: 'project',
    review: '示例 · 待核验',
    input: ['csv'],
    next: ['report'],
    kind: 'chart',
    path: 'figures/coverage.svg'
  }, {
    id: 'raw',
    name: 'source-results.jsonl',
    type: 'JSONL',
    version: '原始快照',
    stage: 1,
    run: 'run-014',
    folder: 'private',
    review: '示例 · 来源待核验',
    input: ['config'],
    next: ['csv', 'report'],
    kind: 'raw',
    path: 'raw/source-results.jsonl'
  }, {
    id: 'manifest',
    name: 'run-manifest.json',
    type: 'JSON',
    version: 'v1.0',
    stage: 1,
    run: 'run-014',
    folder: 'index',
    review: '示例 · 哈希待计算',
    input: ['config'],
    next: ['csv', 'report', 'chart'],
    kind: 'manifest',
    path: 'run-manifest.json'
  }, {
    id: 'config',
    name: 'research-brief.yaml',
    type: 'YAML',
    version: 'v1.0',
    stage: 1,
    run: 'run-014',
    folder: 'project',
    review: '示例 · 配置快照',
    input: [],
    next: ['raw', 'csv', 'report'],
    kind: 'config',
    path: 'inputs/research-brief.yaml'
  }, {
    id: 'comparison',
    name: 'comparison.md',
    type: 'MD',
    version: 'v1.0',
    stage: 2,
    run: 'run-015',
    folder: 'project',
    review: '示例 · 待核验',
    input: ['csv', 'report'],
    next: [],
    kind: 'report',
    path: 'artifacts/comparison.md'
  }, {
    id: 'matrix',
    name: 'comparison-matrix.svg',
    type: 'SVG',
    version: 'v1.0',
    stage: 2,
    run: 'run-015',
    folder: 'project',
    review: '示例 · 待核验',
    input: ['csv'],
    next: ['comparison'],
    kind: 'chart',
    path: 'figures/comparison-matrix.svg'
  }, {
    id: 'manifest2',
    name: 'run-manifest.json',
    type: 'JSON',
    version: 'v1.0',
    stage: 2,
    run: 'run-015',
    folder: 'index',
    review: '示例 · 哈希待计算',
    input: ['csv', 'report'],
    next: ['comparison', 'matrix'],
    kind: 'manifest',
    path: 'run-manifest.json'
  }, {
    id: 'partial',
    name: 'retrieval.partial.jsonl',
    type: 'JSONL',
    version: '部分响应',
    stage: 1,
    run: 'run-013',
    folder: 'private',
    review: '示例 · 不完整',
    input: [],
    next: ['error'],
    kind: 'raw',
    path: 'raw/retrieval.partial.jsonl'
  }, {
    id: 'error',
    name: 'error.log',
    type: 'LOG',
    version: '失败快照',
    stage: 1,
    run: 'run-013',
    folder: 'private',
    review: '示例 · 失败已保留',
    input: ['partial'],
    next: [],
    kind: 'error',
    path: 'logs/error.log'
  }, {
    id: 'manifest0',
    name: 'run-manifest.json',
    type: 'JSON',
    version: '失败快照',
    stage: 1,
    run: 'run-013',
    folder: 'index',
    review: '示例 · 部分产物',
    input: [],
    next: ['partial', 'error'],
    kind: 'manifest',
    path: 'run-manifest.json'
  }];
  const state = {
    locale: 'zh-Hans',
    view: 'work',
    stage: 1,
    topic: 'traffic',
    custom: '我的研究主题',
    folder: 'all',
    run: 'all',
    file: 'report',
    tab: 'preview',
    evidence: false,
    density: 'compact',
    projectPath: 'D:/ResearchWorkspace/projects/{project}/',
    privatePath: 'D:/ResearchPrivate/{project}/',
    backupPath: '',
    storageApplied: false,
    demo: {},
    lastRuns: {
      1: 'run-014',
      2: 'run-015'
    }
  };
  // Explicit interface messages. Source text is the stable key; source documents,
  // user input, paths, filenames, run IDs and machine fields are never rewritten.
  const localeMessages = [['Research Studio 研究工作台方案', 'Research Studio workspace proposal', 'Research Studio 研究工作臺方案'], ['研究工作区导航', 'Research workspace navigation', '研究工作區導覽'], ['主要功能', 'Main navigation', '主要功能'], ['六个研究阶段', 'Six research stages', '六個研究階段'], ['选择研究阶段', 'Select a research stage', '選擇研究階段'], ['我的研究', 'My research', '我的研究'], ['工作台', 'Workspace', '工作臺'], ['项目文件', 'Project files', '專案檔案'], ['运行历史', 'Run history', '執行紀錄'], ['存储与归档设置', 'Storage & archive settings', '儲存與封存設定'], ['存储与归档', 'Storage & archive', '儲存與封存'], ['界面方案 · 演示数据', 'Interface proposal · Demo data', '介面方案 · 示範資料'], ['RESEARCH PIPELINE', 'RESEARCH PIPELINE', '研究流程'], ['LOCAL WORKSPACE', 'LOCAL WORKSPACE', '本機工作區'], ['PROJECT LIBRARY', 'PROJECT LIBRARY', '專案資料庫'], ['RUN HISTORY', 'RUN HISTORY', '執行紀錄'], ['STORAGE & ARCHIVE', 'STORAGE & ARCHIVE', '儲存與封存'], ['界面语言', 'Interface language', '介面語言'], ['选择课题', 'Select a research topic', '選擇研究主題'], ['自定义研究主题…', 'Custom research topic…', '自訂研究主題…'], ['主题', 'Topic', '主題'], ['强化学习交通信号控制', 'RL traffic signal control', '強化學習交通號誌控制'], ['语音情绪识别', 'Speech emotion recognition', '語音情緒辨識'], ['我的研究主题', 'My research topic', '我的研究主題'], ['单路口控制', 'Single-intersection control', '單路口控制'], ['多智能体协同', 'Multi-agent coordination', '多智慧體協作'], ['泛化与迁移', 'Generalization & transfer', '泛化與遷移'], ['特征与模型', 'Features & models', '特徵與模型'], ['说话人独立', 'Speaker independence', '說話者獨立'], ['跨语料泛化', 'Cross-corpus generalization', '跨語料泛化'], ['核心方法', 'Core methods', '核心方法'], ['评价设计', 'Evaluation design', '評估設計'], ['外部验证', 'External validation', '外部驗證'], ['方案预览 · 未连接执行', 'Proposal preview · Execution disconnected', '方案預覽 · 尚未連接執行'], ['本阶段输入', 'Stage inputs', '本階段輸入'], ['预期交付', 'Expected outputs', '預期交付'], ['结果与证据', 'Results & evidence', '結果與證據'], ['每个阶段都有固定展示位置', 'A dedicated view for every stage', '每個階段都有固定展示位置'], ['文献发现与证据', 'Literature discovery & evidence', '文獻探索與證據'], ['文献与证据', 'Literature & evidence', '文獻與證據'], ['建立可追溯的文献池，让研究判断连接到原文证据。', 'Build a traceable literature collection that links research judgments to source evidence.', '建立可追溯的文獻庫，讓研究判斷連結至原文證據。'], ['研究主题、检索范围与预算', 'Topic, search scope and budget', '研究主題、檢索範圍與預算'], ['文献表、证据报告、原始记录', 'Literature table, evidence report and raw records', '文獻表、證據報告與原始紀錄'], ['文献覆盖概览', 'Literature coverage overview', '文獻涵蓋概覽'], ['审阅检索范围、来源完整性与证据质量，再进入文献比较。', 'Review search scope, source completeness and evidence quality before comparing studies.', '審閱檢索範圍、來源完整性與證據品質，再進行文獻比較。'], ['文献比较与研究缺口', 'Literature comparison & research gaps', '文獻比較與研究缺口'], ['比较与缺口', 'Comparison & gaps', '比較與缺口'], ['统一比较研究方法、评价条件与局限，识别有证据支持的研究机会。', 'Compare methods, evaluation conditions and limitations consistently to identify evidence-backed research opportunities.', '以一致標準比較研究方法、評估條件與限制，辨識有證據支持的研究機會。'], ['审阅后的文献池与证据', 'Reviewed literature and evidence', '審閱後的文獻庫與證據'], ['比较矩阵、研究缺口与证据链', 'Comparison matrix, research gaps and evidence links', '比較矩陣、研究缺口與證據鏈'], ['比较矩阵与研究缺口', 'Comparison matrix & research gaps', '比較矩陣與研究缺口'], ['确认比较口径一致、缺口有证据支持，再确定研究问题。', 'Confirm consistent comparisons and evidence for each gap before choosing a research question.', '確認比較標準一致且缺口有證據支持，再確定研究問題。'], ['研究设计与可行性', 'Research design & feasibility', '研究設計與可行性'], ['设计与可行性', 'Design & feasibility', '設計與可行性'], ['明确研究假设、实验对照与资源边界，形成可以批准执行的方案。', 'Define hypotheses, experimental controls and resource limits in a plan ready for approval.', '明確定義研究假設、實驗對照與資源範圍，形成可核准執行的方案。'], ['研究问题、数据与可用资源', 'Research question, data and available resources', '研究問題、資料與可用資源'], ['实验计划、可行性与预算', 'Experiment plan, feasibility and budget', '實驗計畫、可行性與預算'], ['研究设计蓝图', 'Research design blueprint', '研究設計藍圖'], ['批准实验配置、资源预算与评价判据后，再启动实验。', 'Approve the experiment configuration, resource budget and evaluation criteria before execution.', '核准實驗設定、資源預算與評估準則後，再啟動實驗。'], ['实验执行', 'Experiment execution', '實驗執行'], ['按批准的配置运行实验，集中查看日志、失败原因与原始结果。', 'Run the approved configuration and inspect logs, failures and raw results in one place.', '依核准的設定執行實驗，集中查看日誌、失敗原因與原始結果。'], ['批准后的方案与固定配置', 'Approved plan and pinned configuration', '核准後的方案與固定設定'], ['实验日志、原始结果与清单', 'Experiment logs, raw results and manifests', '實驗日誌、原始結果與清單'], ['实验任务与运行轨迹', 'Experiment tasks & execution timeline', '實驗任務與執行軌跡'], ['确认实验与失败记录完整，结果与配置一一对应。', 'Check that experiment and failure records are complete and each result is tied to its configuration.', '確認實驗與失敗紀錄完整，且結果與設定一一對應。'], ['分析与图表', 'Analysis & figures', '分析與圖表'], ['从原始结果生成对比、消融与不确定性分析，让每张图可回到源数据。', 'Compare raw results, run ablations and analyze uncertainty, with every figure linked to its source data.', '從原始結果產生比較、消融與不確定性分析，讓每張圖都能追溯至來源資料。'], ['原始结果、基线与评价方案', 'Raw results, baselines and evaluation plan', '原始結果、基準與評估方案'], ['统计结果、图表与结论', 'Statistical results, figures and conclusions', '統計結果、圖表與結論'], ['结果分析与不确定性', 'Result analysis & uncertainty', '結果分析與不確定性'], ['核对分析口径、对照条件与证据边界，再进入写作。', 'Review analysis definitions, controls and evidence limits before writing.', '核對分析標準、對照條件與證據範圍，再進入寫作。'], ['写作与投稿', 'Writing & submission', '寫作與投稿'], ['组织论文与投稿材料，将关键主张连接到文献、实验和图表。', 'Prepare the manuscript and submission materials, linking central claims to literature, experiments and figures.', '整理論文與投稿資料，將核心主張連結至文獻、實驗與圖表。'], ['审阅后的结论、图表与引用', 'Reviewed conclusions, figures and citations', '審閱後的結論、圖表與引用'], ['论文草稿、引用检查与投稿包', 'Manuscript draft, citation checks and submission package', '論文草稿、引用檢查與投稿資料包'], ['论文结构与证据关联', 'Manuscript structure & evidence links', '論文結構與證據連結'], ['完成内容与引用审阅；对外提交需要单独确认。', 'Review content and citations; external submission requires separate confirmation.', '完成內容與引用審閱；對外提交需要另行確認。'], ['原文证据', 'Source evidence', '原文證據'], ['检索', 'Search', '檢索'], ['筛选', 'Screen', '篩選'], ['文献比较', 'Literature comparison', '文獻比較'], ['证据空白', 'Evidence gaps', '證據空白'], ['研究问题', 'Research question', '研究問題'], ['研究假设', 'Hypotheses', '研究假設'], ['对照与基线', 'Controls & baselines', '對照與基準'], ['评价指标', 'Evaluation metrics', '評估指標'], ['任务队列', 'Task queue', '任務佇列'], ['运行日志', 'Execution logs', '執行日誌'], ['原始结果', 'Raw results', '原始結果'], ['数据与指标', 'Data & metrics', '資料與指標'], ['比较与误差', 'Comparisons & errors', '比較與誤差'], ['结论与局限', 'Conclusions & limitations', '結論與限制'], ['章节草稿', 'Section drafts', '章節草稿'], ['图表与引用', 'Figures & citations', '圖表與引用'], ['投稿准备', 'Submission preparation', '投稿準備'], ['尚未运行 · 可视化位置已预留', 'Not run · Visualization space reserved', '尚未執行 · 已預留視覺化位置'], ['实验性能力，待接入界面', 'Experimental capability; UI integration pending', '實驗性功能，待整合至介面'], ['执行能力与产物渲染器待接入', 'Execution and artifact renderers await integration', '執行功能與產出檔案檢視器待整合'], ['占位', ' placeholder', '預留位置'], ['示例文献分类覆盖，所有数值仅用于界面演示', 'Example literature coverage; all numbers are interface demo data', '示範文獻分類涵蓋情況；所有數值僅供介面示範'], ['方法', 'Methods', '方法'], ['评估', 'Evaluation', '評估'], ['复现', 'Reproduction', '重現'], ['单元格：示例文献数 · 深色表示更多', 'Cells: example paper counts · Darker means more', '儲存格：示範文獻數 · 深色代表較多'], ['示例数据', 'Example data', '示範資料'], ['实验性能力 · 待接入', 'Experimental · Integration pending', '實驗性功能 · 待整合'], ['预留阶段', 'Reserved stage', '預留階段'], ['示例 · 非真实研究结果', 'Example · Not research results', '示範 · 非真實研究結果'], ['占位 · 尚未运行', 'Placeholder · Not run', '預留位置 · 尚未執行'], ['文献样例 A · 方法与评估证据', 'Sample paper A · Methods and evaluation evidence', '文獻範例 A · 方法與評估證據'], ['来源、原文位置与核验状态', 'Source, passage locator and verification status', '來源、原文位置與驗證狀態'], ['查看证据 →', 'View evidence →', '查看證據 →'], ['证据样例 · 不对应真实论文', 'Example evidence · Not a real paper', '證據範例 · 不對應真實論文'], ['正式接入后展示来源链接、页码、摘录与核验记录。证据卡与本次运行的原始响应关联。', 'Once integrated, show source links, page numbers, excerpts and verification records linked to this run’s raw responses.', '正式整合後顯示來源連結、頁碼、摘錄與驗證紀錄；證據卡將連結至本次執行的原始回應。'], ['打开本次产物 →', 'Open run artifacts →', '開啟本次產出檔案 →'], ['当前阶段操作', 'Current stage actions', '目前階段操作'], ['运行本阶段', 'Run this stage', '執行本階段'], ['运行方式', 'Execution mode', '執行方式'], ['演示模式', 'Demo mode', '示範模式'], ['产物位置', 'Artifact location', '產出檔案位置'], ['本次运行', 'This run', '本次執行'], ['阶段交接', 'Stage handoff', '階段交接'], ['审阅后继续', 'Continue after review', '審閱後繼續'], ['演示运行 Stage ', 'Demo run · Stage ', '示範執行 · Stage '], ['模拟确认已审阅', 'Simulate review confirmation', '模擬確認已審閱'], ['本次状态', 'Run status', '本次狀態'], ['预检', 'Preflight', '預檢'], ['运行', 'Run', '執行'], ['待审', 'Awaiting review', '待審'], ['审阅与交接', 'Review & handoff', '審閱與交接'], ['本地演示，不调用模型、接口或文件系统。', 'Local demo; no model, API or filesystem calls.', '本機示範，不呼叫模型、介面或檔案系統。'], ['模拟预检：检查输入与保存方案。', 'Simulated preflight: checking inputs and storage plan.', '模擬預檢：檢查輸入與儲存方案。'], ['模拟运行中：仅更新界面状态。', 'Simulation running: only interface state changes.', '模擬執行中：僅更新介面狀態。'], ['模拟待审阅：示例清单已进入项目文件，未实际写入磁盘。', 'Simulated review pending: example manifests appear in Project files; nothing was written to disk.', '模擬待審閱：示範清單已加入專案檔案，未實際寫入磁碟。'], ['模拟审阅已确认。下一阶段仍需独立启动。', 'Simulated review confirmed. Start the next stage separately.', '模擬審閱已確認；下一階段仍須個別啟動。'], ['尚无产物 · 演示后可查看示例清单', 'No artifacts yet · Run a demo to view an example manifest', '尚無產出檔案 · 示範後可查看範例清單'], ['正在本地模拟 · 无真实执行', 'Local simulation in progress · No real execution', '正在本機模擬 · 無真實執行'], ['未连接 Harness 执行接口', 'Harness execution interface not connected', '尚未連接 Harness 執行介面'], [' 项文件', ' files', ' 個檔案'], ['结果集中保存，保留版本、运行来源，以及后续使用关系。', 'Keep results together with versions, producing runs and downstream links.', '集中儲存結果，保留版本、執行來源與後續使用關係。'], ['存储设置', 'Storage settings', '儲存設定'], ['存储目录', 'Storage locations', '儲存目錄'], ['全部文件', 'All files', '所有檔案'], ['项目目录', 'Project directory', '專案目錄'], ['私有数据', 'Private data', '私有資料'], ['运行索引', 'Run index', '執行索引'], ['来源运行', 'Producing run', '來源執行'], ['文件预览与来源详情', 'File preview and provenance details', '檔案預覽與來源詳情'], ['全部为界面样例。显示的是建议保存位置，尚未创建目录或保存科研文件。', 'All items are interface examples. Locations are suggestions; no directories or research files have been saved.', '全部皆為介面範例；顯示的是建議儲存位置，尚未建立目錄或儲存研究檔案。'], ['所有产物', 'All artifacts', '所有產出檔案'], ['私有大文件区', 'Private large-file storage', '私有大型檔案區'], ['本地运行索引', 'Local run index', '本機執行索引'], ['建议目录 / ', 'Suggested location / ', '建議目錄 / '], [' 项示例', ' examples', ' 個範例'], ['全部示例运行', 'All example runs', '所有示範執行'], ['失败记录样例', 'Example failure record', '失敗紀錄範例'], ['示例 · 未核验', 'Example · Unverified', '範例 · 未驗證'], ['此筛选下没有示例文件。', 'No example files match this filter.', '此篩選條件下沒有範例檔案。'], ['选择运行或目录查看产物。', 'Select a run or location to view artifacts.', '選擇執行紀錄或目錄以查看產出檔案。'], ['文件详情', 'File details', '檔案詳情'], ['内容预览', 'Content preview', '內容預覽'], ['上下游溯源', 'Provenance', '輸入與衍生關係'], ['界面语言不改变原始文件与研究内容。下方预览保留原文。', 'Interface language does not alter source files or research content. The preview below retains its original language.', '介面語言不會變更原始檔案或研究內容；下方預覽保留原文。'], ['暂无已记录关联', 'No recorded links yet', '尚無已記錄的關聯'], ['输入文件 → 被本次运行使用', 'Inputs → Used by this run', '輸入檔案 → 由本次執行使用'], ['执行 → 生成当前产物', 'Execution → Produced this artifact', '執行 → 產生目前檔案'], ['配置快照、代码版本与工具记录：待接入', 'Configuration snapshot, code revision and tool records: integration pending', '設定快照、程式碼版本與工具紀錄：待整合'], ['当前产物 · ', 'Current artifact · ', '目前產出檔案 · '], ['下游计划引用 · 未实际执行', 'Planned downstream use · Not executed', '規劃引用 · 尚未執行'], ['建议保存位置 · 未实际保存', 'Suggested location · Not saved', '建議儲存位置 · 尚未實際儲存'], ['文件核验 / 研究审阅', 'File verification / Research review', '檔案驗證 / 研究審閱'], ['字节核验：SHA-256 未计算', 'File integrity: SHA-256 not computed', '位元組完整性驗證：SHA-256 尚未計算'], ['研究审阅：待人工审阅，非可信性认证', 'Research review: human review pending; not a reliability certification', '研究審閱：待人工審閱，並非可信度認證'], ['保存与备份', 'Saving & backups', '儲存與備份'], ['最近保存：无实际保存', 'Last saved: never saved', '最近儲存：尚未實際儲存'], ['最近备份：', 'Last backup: ', '最近備份：'], ['已填建议位置，尚未备份', 'Suggested location entered; no backup created', '已填入建議位置，尚未備份'], ['未配置', 'Not configured', '尚未設定'], ['生成来源', 'Produced by', '產生來源'], ['配置：', 'Configuration: ', '設定：'], ['代码版本：待接入', 'Code revision: integration pending', '程式碼版本：待整合'], ['产物身份（示例规则）', 'Artifact identity (example rules)', '產出檔案識別（範例規則）'], ['artifact_id 绑定 producer、attempt 与内容哈希；当前尚无真实哈希。', 'artifact_id binds producer, attempt and content hash; no real hash exists yet.', 'artifact_id 綁定 producer、attempt 與內容雜湊；目前尚無真實雜湊值。'], ['（示例）', ' (example)', '（範例）'], ['每次运行独立留存，失败记录与部分产物也可以追溯。以下均为示例。', 'Retain each run separately, including failures and partial artifacts. All entries below are examples.', '每次執行皆獨立保存，失敗紀錄與部分產出也可追溯；以下皆為範例。'], ['不可覆盖的运行记录 · 方案', 'Immutable run records · Proposal', '不可覆寫的執行紀錄 · 方案'], ['查看产物 →', 'View artifacts →', '查看產出檔案 →'], ['示例已完成', 'Example completed', '範例已完成'], ['示例待审阅', 'Example awaiting review', '範例待審閱'], ['示例失败', 'Example failed', '範例失敗'], ['比较矩阵与研究缺口 · 3 项示例产物', 'Comparison matrix and research gaps · 3 example artifacts', '比較矩陣與研究缺口 · 3 個範例產出檔案'], ['文献发现与证据 · 6 项示例文件', 'Literature discovery and evidence · 6 example files', '文獻探索與證據 · 6 個範例檔案'], ['来源连接超时；保留部分响应、错误日志与清单', 'Source connection timed out; partial responses, error log and manifest retained', '來源連線逾時；保留部分回應、錯誤日誌與清單'], ['示例 · 第 3 次', 'Example · Run 3', '範例 · 第 3 次'], ['示例 · 第 2 次', 'Example · Run 2', '範例 · 第 2 次'], ['示例 · 第 1 次', 'Example · Run 1', '範例 · 第 1 次'], ['模拟待审阅', 'Simulation awaiting review', '模擬待審閱'], ['模拟已审阅', 'Simulated review confirmed', '模擬已審閱'], ['本地流程演示；仅创建内存中的示例清单，未写入磁盘', 'Local workflow demo; example manifest created in memory only, with no disk writes', '本機流程示範；僅在記憶體中建立範例清單，未寫入磁碟'], ['刚刚 · 本地模拟', 'Just now · Local simulation', '剛剛 · 本機模擬'], ['原始快照', 'Raw snapshot', '原始快照'], ['部分响应', 'Partial response', '部分回應'], ['失败快照', 'Failure snapshot', '失敗快照'], ['演示快照', 'Demo snapshot', '示範快照'], ['示例 · 待核验', 'Example · Verification pending', '範例 · 待驗證'], ['示例 · 待审阅', 'Example · Review pending', '範例 · 待審閱'], ['示例 · 来源待核验', 'Example · Source verification pending', '範例 · 來源待驗證'], ['示例 · 哈希待计算', 'Example · Hash pending', '範例 · 雜湊待計算'], ['示例 · 配置快照', 'Example · Configuration snapshot', '範例 · 設定快照'], ['示例 · 不完整', 'Example · Incomplete', '範例 · 不完整'], ['示例 · 失败已保留', 'Example · Failure retained', '範例 · 已保留失敗紀錄'], ['示例 · 部分产物', 'Example · Partial artifacts', '範例 · 部分產出檔案'], ['模拟 · 未保存', 'Simulation · Not saved', '模擬 · 未儲存'], ['研究运行包保存于 Git checkout 外，私有区放置大文件，Git 保存源码与经筛选的可公开索引。', 'Store research run packages outside the Git checkout and large files in private storage. Git keeps source code and a curated public index.', '研究執行資料包儲存於 Git checkout 外，私有區保存大型檔案；Git 保存原始碼與經篩選的可公開索引。'], ['仅建议 · 未应用到磁盘', 'Suggestion only · Not applied to disk', '僅供建議 · 尚未套用至磁碟'], ['项目产物目录 · Git 外', 'Project artifact directory · Outside Git', '專案產出檔案目錄 · Git 外'], ['建议项目保存路径', 'Suggested project storage path', '建議專案儲存路徑'], ['按 run / stage / attempt 保存报告、表格、图表与审阅结果。新增版本，不覆盖历史。', 'Store reports, tables, figures and reviews by run / stage / attempt. Add versions without overwriting history.', '依 run / stage / attempt 儲存報告、表格、圖表與審閱結果；新增版本，不覆寫歷史。'], ['私有大文件区 · Git 外', 'Private large-file storage · Outside Git', '私有大型檔案區 · Git 外'], ['建议私有数据保存路径', 'Suggested private-data storage path', '建議私有資料儲存路徑'], ['原始响应、全文、数据集与模型保留于私有区。完整运行 manifest 留在私有项目目录。', 'Keep raw responses, full texts, datasets and models private. Store the complete run manifest in the private project directory.', '原始回應、全文、資料集與模型保留於私有區；完整執行 manifest 留在私有專案目錄。'], ['Git 保存什么', 'What Git stores', 'Git 儲存哪些內容'], ['UI 与执行源码', 'UI and execution source code', 'UI 與執行原始碼'], ['非敏感配置', 'Non-sensitive configuration', '非敏感設定'], ['经筛选的可公开索引', 'Curated public index', '經篩選的可公開索引'], ['实际研究文件留在 Git 外', 'Research files stay outside Git', '實際研究檔案保留於 Git 外'], ['经筛选的可公开索引可同步 Git。完整记录包含位置、内容哈希、producer、run / attempt 与关联关系；哈希用于核验，不代替文件备份。', 'Sync only a curated public index to Git. Full records include location, content hash, producer, run / attempt and links. Hashes verify integrity; they do not replace backups.', '僅將經篩選的可公開索引同步至 Git。完整紀錄包含位置、內容雜湊、producer、run / attempt 與關聯；雜湊用於驗證，不能取代檔案備份。'], ['备份位置', 'Backup location', '備份位置'], ['建议备份目录', 'Suggested backup directory', '建議備份目錄'], ['未配置 · 建议另一块磁盘或受控存储', 'Not configured · Use another disk or managed storage', '尚未設定 · 建議使用另一個磁碟或受控儲存空間'], ['上次备份：未配置。预览不会创建备份任务。', 'Last backup: not configured. This preview does not create backup jobs.', '上次備份：尚未設定；預覽不會建立備份工作。'], ['保存时同时记录', 'Also record when saving', '儲存時一併記錄'], ['文件版本 / 内容哈希', 'File version / Content hash', '檔案版本 / 內容雜湊'], ['输入与生成配置', 'Inputs and generation configuration', '輸入與產生設定'], ['代码版本与工具', 'Code revision and tools', '程式碼版本與工具'], ['来源与许可', 'Sources and licenses', '來源與授權'], ['核验与审阅分别记录', 'Record verification and review separately', '分別記錄驗證與審閱'], ['模拟应用保存方案', 'Simulate storage plan', '模擬套用儲存方案'], ['仅修改本预览，不创建或移动文件。', 'Changes this preview only; no files are created or moved.', '僅修改本預覽，不會建立或移動檔案。'], ['已更新本预览的建议位置；没有创建、移动、保存或备份文件。', 'Suggested locations updated in this preview; no files were created, moved, saved or backed up.', '已更新本預覽的建議位置；未建立、移動、儲存或備份任何檔案。'], ['所有内容均为示例 · 六阶段产物与来源记录统一管理', 'Example content only · Artifacts and provenance across six stages', '所有內容皆為範例 · 統一管理六階段產出檔案與來源紀錄'], ['示例 ', 'Example ', '範例 '], ['示例', 'Example', '範例']];
  const localeDictionaries = Object.fromEntries(['zh-Hans', 'en', 'zh-Hant'].map((locale, index) => [locale, Object.fromEntries(localeMessages.map(row => [row[0], row[index]]))]));
  const messagePattern = new RegExp(localeMessages.map(row => row[0]).sort((a, b) => b.length - a.length).map(key => key.replace(/[.*+?^${}()|[\]\\]/g, '\\$&')).join('|'), 'g');
  function t(source) {
    return state.locale === 'zh-Hans' ? String(source) : String(source).replace(messagePattern, key => localeDictionaries[state.locale][key]);
  }
  const localizedNodes = new WeakMap(),
    localizedAttributes = new WeakMap();
  function localizeUI() {
    root.lang = state.locale;
    document.documentElement.lang = state.locale;
    $('rs-language').value = state.locale;
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    while (walker.nextNode()) {
      const node = walker.currentNode,
        parent = node.parentElement;
      if (!parent || parent.closest('script,style,pre,code,[data-source-content],[data-verbatim],.rs-file-name,.rs-inspector-title,[data-file],#rs-language')) continue;
      let record = localizedNodes.get(node);
      if (!record || node.nodeValue !== record.last) record = {
        source: node.nodeValue,
        last: null
      };
      record.last = t(record.source);
      node.nodeValue = record.last;
      localizedNodes.set(node, record);
    }
    [root, ...root.querySelectorAll('[aria-label],[placeholder]')].forEach(el => {
      if (el.closest('[data-source-content],[data-verbatim]')) return;
      const records = localizedAttributes.get(el) || {};
      ['aria-label', 'placeholder'].forEach(attr => {
        if (!el.hasAttribute(attr)) return;
        let record = records[attr];
        const current = el.getAttribute(attr);
        if (!record || current !== record.last) record = {
          source: current,
          last: null
        };
        record.last = t(record.source);
        el.setAttribute(attr, record.last);
        records[attr] = record;
      });
      localizedAttributes.set(el, records);
    });
  }
  const names = {
      work: '工作台',
      files: '项目文件',
      history: '运行历史',
      storage: '存储与归档'
    },
    folderNames = {
      all: '所有产物',
      project: '项目目录',
      private: '私有大文件区',
      index: '本地运行索引'
    };
  let sequence = 0;
  const preferenceKey = 'auto-research-agent.research-studio.preferences.v1';
  const ownKey = (dictionary, value) => typeof value === 'string' && Object.hasOwn(dictionary, value);
  // Persist navigation preferences only. Topics entered by the user, paths,
  // demo runs, generated manifests and research content are never persisted.
  function save() {
    const preferences = {
      version: 1,
      locale: state.locale,
      view: state.view,
      stage: state.stage,
      topic: state.topic,
      folder: state.folder,
      run: state.run,
      file: state.file,
      tab: state.tab,
      density: state.density
    };
    try {
      localStorage.setItem(preferenceKey, JSON.stringify(preferences));
    } catch {/* Storage may be disabled, including for local files. */}
  }
  function restore() {
    let p;
    try {
      const raw = localStorage.getItem(preferenceKey);
      if (!raw || raw.length > 16384) return;
      p = JSON.parse(raw);
    } catch {
      return;
    }
    if (!p || typeof p !== 'object' || Array.isArray(p) || !Object.hasOwn(p, 'version') || p.version !== 1) return;
    if (ownKey(localeDictionaries, p.locale)) state.locale = p.locale;
    if (ownKey(names, p.view)) state.view = p.view;
    if (Number.isInteger(p.stage) && p.stage >= 1 && p.stage <= 6) state.stage = p.stage;
    if (ownKey(topics, p.topic)) state.topic = p.topic;
    if (ownKey(folderNames, p.folder)) state.folder = p.folder;
    if (p.run === 'all' || runs.some(r => r.id === p.run)) state.run = p.run;
    if (files.some(f => f.id === p.file)) state.file = p.file;
    if (p.tab === 'preview' || p.tab === 'trace') state.tab = p.tab;
    if (p.density === 'airy' || p.density === 'compact') state.density = p.density;
  }
  function stageVisual() {
    if (state.stage > 1) return '<div class="rs-placeholder"><div class="rs-blueprint" role="img" aria-label="' + stages[state.stage].title + '占位">' + stages[state.stage].nodes.map(n => '<span>' + n + '</span>').join('<b>→</b>') + '</div><p><strong>尚未运行 · 可视化位置已预留</strong>' + (state.stage === 2 ? '实验性能力，待接入界面' : '执行能力与产物渲染器待接入') + '</p></div>';
    let result = '<div class="rs-heatmap" role="img" aria-label="示例文献分类覆盖，所有数值仅用于界面演示"><span></span><span class="rs-col">方法</span><span class="rs-col">评估</span><span class="rs-col">复现</span>';
    topics[state.topic].rows.forEach((row, i) => {
      result += '<span>' + row + '</span>';
      [[8, 6, 3], [6, 4, 2], [4, 2, 1]][i].forEach(n => result += '<span class="rs-heat ' + (n >= 8 ? 'max' : n >= 5 ? 'high' : n >= 3 ? 'mid' : '') + '">' + n + '</span>');
    });
    return result + '</div><p class="rs-legend">单元格：示例文献数 · 深色表示更多</p>';
  }
  function renderWork() {
    const s = stages[state.stage];
    $('rs-stage-kicker').textContent = 'STAGE 0' + state.stage + ' / 06';
    $('rs-stage-title').textContent = s.name;
    $('rs-stage-description').textContent = s.goal;
    $('rs-stage-input').textContent = s.input;
    $('rs-stage-output').textContent = s.output;
    $('rs-stage-gate').textContent = s.gate;
    $('rs-stage-badge').textContent = state.stage === 1 ? '示例数据' : state.stage === 2 ? '实验性能力 · 待接入' : '预留阶段';
    $('rs-canvas-title').textContent = s.title;
    $('rs-canvas-label').textContent = state.stage === 1 ? '示例 · 非真实研究结果' : '占位 · 尚未运行';
    $('rs-stage-visual').innerHTML = stageVisual();
    $('rs-evidence-row').hidden = state.stage !== 1;
    $('rs-evidence-detail').hidden = state.stage !== 1 || !state.evidence;
    $('rs-evidence-toggle').setAttribute('aria-expanded', String(state.evidence));
    renderRun();
  }
  function renderRun() {
    const d = state.demo[state.stage],
      busy = d && d.status === 'running',
      run = state.lastRuns[state.stage];
    $('rs-run').disabled = !!busy;
    $('rs-run').textContent = '演示运行 Stage ' + state.stage;
    $('rs-review').hidden = !(d && d.status === 'human-review');
    root.querySelectorAll('[data-flow]').forEach(el => el.classList.toggle('active', !!d && Number(el.dataset.flow) <= d.step));
    $('rs-run-status').textContent = !d ? '本地演示，不调用模型、接口或文件系统。' : d.status === 'running' ? d.step === 1 ? '模拟预检：检查输入与保存方案。' : '模拟运行中：仅更新界面状态。' : d.status === 'human-review' ? '模拟待审阅：示例清单已进入项目文件，未实际写入磁盘。' : '模拟审阅已确认。下一阶段仍需独立启动。';
    $('rs-open-artifacts').disabled = !run;
    $('rs-artifact-summary').textContent = run ? '示例 ' + run + ' · ' + files.filter(f => f.run === run).length + ' 项文件' : '尚无产物 · 演示后可查看示例清单';
    $('rs-footer-status').textContent = busy ? '正在本地模拟 · 无真实执行' : '未连接 Harness 执行接口';
  }
  function filePreview(f) {
    if (f.kind === 'table') return '<table aria-label="示例文献表预览"><thead><tr><th>文献</th><th>方向</th><th>核验</th></tr></thead><tbody>' + topics[state.topic].rows.map((r, i) => '<tr><td>样例 ' + String.fromCharCode(65 + i) + '</td><td>' + r + '</td><td>待核验</td></tr>').join('') + '</tbody></table><p style="margin-top:12px">仅示例表格，不对应真实论文。</p>';
    if (f.kind === 'chart') return '<h3>示例文献覆盖</h3><div class="rs-bars" role="img" aria-label="示例分类覆盖条形图，数字为演示数据">' + topics[state.topic].rows.map((r, i) => '<div class="rs-bar-row"><span>' + r + '</span><span class="rs-bar-track"><span class="rs-bar" style="display:block;width:' + [100, 75, 50][i] + '%"></span></span><span>' + [8, 6, 4][i] + '</span></div>').join('') + '</div><p>示例 SVG 图表预览 · 非真实结果</p>';
    if (f.kind === 'report') return '<h3>' + esc(f.stage === 2 ? '文献比较与研究缺口' : '文献发现与证据报告') + '</h3><p>1. 研究范围与检索条件</p><p>2. 文献分类与关键证据</p><p>3. 已知局限与待核验项</p><p>示例报告结构。正式报告的主张将链接到文献表、原文证据和运行记录。</p>';
    let content;
    if (f.kind === 'manifest') content = {
      mode: 'preview-only',
      run_id: f.run,
      stage: f.stage,
      attempt: 'attempt-01',
      status: runs.find(r => r.id === f.run)?.status || 'human-review',
      input_artifacts: f.input,
      output_artifacts: f.next,
      sha256: '待真实文件生成后计算',
      code_revision: '待接入',
      config_snapshot: 'research-brief.yaml（示例）',
      saved_to_disk: false
    };else if (f.kind === 'config') content = {
      topic: state.topic === 'custom' ? state.custom : topics[state.topic].name,
      query: '示例检索式',
      budget: '待用户配置',
      source: '待接入'
    };else if (f.kind === 'error') return '<pre>EXAMPLE LOG\u000aSourceTimeout: 检索来源超时\u000a已保留部分响应与错误上下文。\u000a请检查来源后创建新的运行。\u000a\u000a此为失败状态演示。</pre>';else content = {
      record: 'example-only',
      source: '待连接真实来源',
      query_ref: 'research-brief.yaml',
      raw_payload: '原始响应预览占位',
      integrity: f.id === 'partial' ? 'incomplete' : 'unverified'
    };
    return '<pre>' + esc(JSON.stringify(content, null, 2)) + '</pre>';
  }
  function artifactLinks(ids) {
    return ids.length ? ids.map(id => {
      const f = files.find(x => x.id === id);
      return f ? '<button type="button" data-file="' + id + '" class="cursor-interaction">' + esc(f.name) + ' ↗</button>' : '';
    }).join('') : '<span class="rs-chain-value">' + (state.tab === 'trace' ? '暂无已记录关联' : '—') + '</span>';
  }
  function trace(f) {
    return '<div class="rs-chain"><div class="rs-chain-step"><div class="rs-chain-label">输入文件 → 被本次运行使用</div>' + artifactLinks(f.input) + '</div><div class="rs-chain-step"><div class="rs-chain-label">执行 → 生成当前产物</div><button type="button" data-run="' + f.run + '" class="cursor-interaction">Stage ' + f.stage + ' / ' + f.run + ' / attempt-01 ↗</button><div class="rs-chain-value">配置快照、代码版本与工具记录：待接入</div></div><div class="rs-chain-step current"><div class="rs-chain-label">当前产物 · ' + esc(f.version) + '</div><div class="rs-chain-value">' + esc(f.name) + '</div></div><div class="rs-chain-step"><div class="rs-chain-label">下游计划引用 · 未实际执行</div>' + artifactLinks(f.next) + '</div></div>';
  }
  function suggestedPath(f) {
    const slug = topics[state.topic].slug,
      base = (f.folder === 'private' ? state.privatePath : state.projectPath).replace('{project}', slug).replace(/[\\/]+$/, '');
    return base + '/runs/' + f.run + '/stage' + f.stage + '/attempt-01/' + f.path;
  }
  function renderFiles() {
    const visible = files.filter(f => (state.run === 'all' || f.run === state.run) && (state.folder === 'all' || f.folder === state.folder));
    if (!visible.some(f => f.id === state.file)) state.file = visible[0]?.id || null;
    const current = visible.find(f => f.id === state.file);
    $('rs-directory-label').textContent = '建议目录 / ' + folderNames[state.folder];
    $('rs-file-count').textContent = visible.length + ' 项示例';
    $('rs-run-filter').innerHTML = '<option value="all">全部示例运行</option>' + runs.map(r => '<option value="' + r.id + '">' + r.id + ' · Stage ' + r.stage + '</option>').join('');
    $('rs-run-filter').value = state.run;
    root.querySelectorAll('[data-folder]').forEach(el => el.classList.toggle('active', el.dataset.folder === state.folder));
    $('rs-file-list').innerHTML = visible.length ? visible.map(f => '<button type="button" class="rs-file-row cursor-interaction ' + (f.id === state.file ? 'active' : '') + '" data-select-file="' + f.id + '" aria-pressed="' + (f.id === state.file) + '"><span class="rs-file-main"><span class="rs-file-icon">' + f.type + '</span><span><span class="rs-file-name">' + f.name + '</span><span class="rs-file-sub" style="display:block">' + f.type + ' · ' + f.version + ' · ' + folderNames[f.folder] + '</span></span></span><span class="rs-file-origin">S' + f.stage + ' / ' + f.run + '<span>' + (f.run === 'run-013' ? '失败记录样例' : '示例 · 未核验') + '</span></span></button>').join('') : '<div class="rs-empty">此筛选下没有示例文件。</div>';
    if (!current) {
      $('rs-inspector-content').innerHTML = '<div class="rs-empty">选择运行或目录查看产物。</div>';
      return;
    }
    $('rs-inspector-content').innerHTML = '<div class="rs-inspector-title">' + current.name + '</div><div class="rs-inspector-caption">' + current.type + ' · ' + current.version + ' · Stage ' + current.stage + '</div><nav class="rs-tabs" aria-label="文件详情"><button type="button" class="rs-tab cursor-interaction ' + (state.tab === 'preview' ? 'active' : '') + '" data-file-tab="preview" aria-pressed="' + (state.tab === 'preview') + '">内容预览</button><button type="button" class="rs-tab cursor-interaction ' + (state.tab === 'trace' ? 'active' : '') + '" data-file-tab="trace" aria-pressed="' + (state.tab === 'trace') + '">上下游溯源</button></nav><div class="rs-preview">' + (state.tab === 'trace' ? trace(current) : filePreview(current)) + '</div><div class="rs-inspector-meta"><div><strong>建议保存位置 · 未实际保存</strong><p>' + esc(suggestedPath(current)) + '</p></div><div><strong>文件核验 / 研究审阅</strong><p>字节核验：SHA-256 未计算<br>研究审阅：待人工审阅，非可信性认证</p></div><div><strong>保存与备份</strong><p>最近保存：无实际保存<br>最近备份：' + (state.backupPath ? '已填建议位置，尚未备份' : '未配置') + '</p></div><div><strong>生成来源</strong><p>' + current.run + ' / Stage ' + current.stage + ' / attempt-01<br>配置：research-brief.yaml（示例）<br>代码版本：待接入</p></div><div><strong>产物身份（示例规则）</strong><p>artifact_id 绑定 producer、attempt 与内容哈希；当前尚无真实哈希。</p></div></div>';
    // Suggested locations are user text, not interface messages.
    $('rs-inspector-content').querySelector('.rs-inspector-meta p').setAttribute('data-verbatim', '');
  }
  function renderHistory() {
    $('rs-history-list').innerHTML = runs.map(r => '<div class="rs-history-row"><div class="rs-history-id">' + r.id + '<small>' + r.time + '</small></div><div class="rs-history-desc"><strong>Stage ' + r.stage + ' · ' + stages[r.stage].name + '</strong><p>' + r.description + '</p></div><span class="rs-badge ' + (r.status === 'failed' ? 'danger' : r.status === 'completed' ? 'good' : 'warm') + '">' + r.label + '</span><button type="button" data-run="' + r.id + '" class="rs-button cursor-interaction">查看产物 →</button></div>').join('');
  }
  function render() {
    root.classList.toggle('rs-airy', state.density === 'airy');
    $('rs-topic').value = state.topic;
    $('rs-custom-field').hidden = state.topic !== 'custom';
    $('rs-custom-input').value = state.custom;
    $('rs-crumb').textContent = names[state.view];
    ['work', 'files', 'history', 'storage'].forEach(v => $('rs-' + v + '-view').hidden = v !== state.view);
    root.querySelectorAll('[data-view]').forEach(el => el.classList.toggle('active', el.dataset.view === state.view));
    const stageNav = stages.slice(1).map((s, i) => '<button type="button" class="rs-stage cursor-interaction ' + (state.stage === i + 1 ? 'active' : '') + '" data-stage="' + (i + 1) + '" aria-pressed="' + (state.stage === i + 1) + '"><span class="rs-stage-num">' + (i + 1) + '</span>' + s.short + '</button>').join('');
    $('rs-stage-nav').innerHTML = stageNav;
    $('rs-mobile-stages').innerHTML = stages.slice(1).map((s, i) => '<button type="button" data-stage="' + (i + 1) + '" class="cursor-interaction ' + (state.stage === i + 1 ? 'active' : '') + '">' + (i + 1) + ' ' + s.short + '</button>').join('');
    if (state.view === 'work') renderWork();
    if (state.view === 'files') renderFiles();
    if (state.view === 'history') renderHistory();
    $('rs-project-path').value = state.projectPath;
    $('rs-private-path').value = state.privatePath;
  }
  function openRun(id) {
    state.view = 'files';
    state.run = id;
    state.folder = 'all';
    state.file = (files.find(f => f.run === id && f.id === 'report') || files.find(f => f.run === id))?.id || null;
    state.tab = 'preview';
    render();
    save();
  }
  root.addEventListener('click', e => {
    const b = e.target.closest('button');
    if (!b || !root.contains(b)) return;
    if (b.dataset.view) {
      state.view = b.dataset.view;
      render();
      save();
    } else if (b.dataset.stage) {
      state.stage = Number(b.dataset.stage);
      state.view = 'work';
      state.evidence = false;
      render();
      save();
    } else if (b.dataset.folder) {
      state.folder = b.dataset.folder;
      renderFiles();
      save();
    } else if (b.dataset.selectFile) {
      state.file = b.dataset.selectFile;
      renderFiles();
      save();
    } else if (b.dataset.fileTab) {
      state.tab = b.dataset.fileTab;
      renderFiles();
      save();
    } else if (b.dataset.file) {
      state.file = b.dataset.file;
      state.run = 'all';
      state.folder = 'all';
      renderFiles();
      save();
    } else if (b.dataset.run) openRun(b.dataset.run);
  });
  $('rs-topic').addEventListener('change', e => {
    if (!ownKey(topics, e.target.value)) return;
    state.topic = e.target.value;
    state.evidence = false;
    render();
    save();
  });
  $('rs-custom-input').addEventListener('change', e => {
    state.custom = e.target.value.trim().slice(0, 60) || '我的研究主题';
    render();
    save();
  });
  $('rs-run-filter').addEventListener('change', e => {
    if (e.target.value !== 'all' && !runs.some(run => run.id === e.target.value)) return;
    state.run = e.target.value;
    renderFiles();
    save();
  });
  $('rs-evidence-toggle').addEventListener('click', () => {
    state.evidence = !state.evidence;
    renderWork();
  });
  $('rs-open-artifacts').addEventListener('click', () => {
    const id = state.lastRuns[state.stage];
    if (id) openRun(id);
  });
  $('rs-run').addEventListener('click', () => {
    const stage = state.stage,
      id = 'demo-' + String(++sequence).padStart(3, '0'),
      d = {
        status: 'running',
        step: 1
      };
    state.demo[stage] = d;
    renderRun();
    setTimeout(() => {
      if (state.demo[stage] === d) {
        d.step = 2;
        if (state.view === 'work') renderRun();
      }
    }, 800);
    setTimeout(() => {
      if (state.demo[stage] !== d) return;
      d.status = 'human-review';
      d.step = 3;
      state.lastRuns[stage] = id;
      runs.unshift({
        id,
        stage,
        status: 'human-review',
        label: '模拟待审阅',
        description: '本地流程演示；仅创建内存中的示例清单，未写入磁盘',
        time: '刚刚 · 本地模拟'
      });
      files.unshift({
        id: 'manifest-' + id,
        name: 'run-manifest.json',
        type: 'JSON',
        version: '演示快照',
        stage,
        run: id,
        folder: 'index',
        review: '模拟 · 未保存',
        input: [],
        next: [],
        kind: 'manifest',
        path: 'run-manifest.json'
      });
      if (state.view === 'work') renderRun();
      if (state.view === 'history') renderHistory();
      if (state.view === 'files') renderFiles();
      save();
    }, 2100);
  });
  $('rs-review').addEventListener('click', () => {
    const d = state.demo[state.stage];
    if (d) {
      d.status = 'completed';
      const r = runs.find(r => r.id === state.lastRuns[state.stage]);
      if (r) {
        r.status = 'completed';
        r.label = '模拟已审阅';
      }
      renderRun();
      save();
    }
  });
  $('rs-apply-storage').addEventListener('click', () => {
    state.projectPath = $('rs-project-path').value.trim() || 'D:/ResearchWorkspace/projects/{project}/';
    state.privatePath = $('rs-private-path').value.trim() || 'D:/ResearchPrivate/{project}/';
    state.backupPath = $('rs-backup-path').value.trim();
    $('rs-storage-status').textContent = '已更新本预览的建议位置；没有创建、移动、保存或备份文件。';
  });
  // All paths that repaint interface content use the same locale, including
  // delayed simulation updates and direct file/history operations. Message
  // source snapshots make changing languages reversible without changing data.
  const renderSource = render,
    renderWorkSource = renderWork,
    renderRunSource = renderRun,
    renderFilesSource = renderFiles,
    renderHistorySource = renderHistory,
    filePreviewSource = filePreview;
  filePreview = function (file) {
    return '<p class="rs-file-foot" style="margin-bottom:12px">界面语言不改变原始文件与研究内容。下方预览保留原文。</p><div data-source-content lang="zh-Hans">' + filePreviewSource(file) + '</div>';
  };
  renderRun = function () {
    renderRunSource();
    localizeUI();
  };
  renderWork = function () {
    renderWorkSource();
    localizeUI();
  };
  renderFiles = function () {
    renderFilesSource();
    localizeUI();
  };
  renderHistory = function () {
    renderHistorySource();
    localizeUI();
  };
  render = function () {
    renderSource();
    localizeUI();
  };
  $('rs-language').addEventListener('change', event => {
    if (!Object.hasOwn(localeDictionaries, event.target.value)) return;
    state.locale = event.target.value;
    render();
    save();
  });
  $('rs-apply-storage').addEventListener('click', () => {
    state.storageApplied = true;
    localizeUI();
  });
  restore();
  render();
})();
