# 一次设计 self-review

作者自查一次，不是独立code review、真人usability或科学评审。

| ID | finding | 设计修正／unknown | 对应位置／状态 | 剩余限制 |
|---|---|---|---|---|
| SR01 | 首版通用 Stage 3 大标题压过研究案例，手机首屏科学问题不突出。 | 以合成研究题目作为 h1；通用续接说明降为小字，完整技术收据留在详情。 | tools/build_mock.py: page hero<br>tools/render_wireframes.ps1: hero / saved-draft / needs-information | 实际浏览器390px/200%缩放 usability NOT_RUN；GDI图仅布局示意。 |
| SR02 | 观察案例同一资源被两个 SQ 重复完整展示，可能误读为两份独立材料。 | 按原 resource_id 分组，只列一份入口/文件/权利信息，同时逐题保留用途与适配。 | tools/build_mock.py: grouped resources<br>fixtures/observation.json / saved-draft | 合成资源没有真实 URL/文件/使用权利证据，保持 unknown/null。 |
| SR03 | 首版结构化字段和状态注释存在中英混用的 UI 标签。 | 93个界面标签统一经过三语言 copy；原科学文字保持 zh-CN 原文，不生成第二份科学内容。 | copy.json<br>tools/build_mock.py: ui labels / language change | 未做真人翻译质量/辅助技术验证；科学原文不是自动翻译。 |
| SR04 | 页面顶部语言链接无法表达保留具体 SQ 的阅读位置。 | 每个 SQ 增加指向同案例/同locale文件/同SQ锚点的语言链接；顶部切换保持当前案例并定位研究区。 | tools/build_mock.py: data-preserve-sq links / language change / refresh-readback | 静态文件链接不是 Host URL/导航接线或同key/hash重送的验证。 |
| SR05 | 条件式结果只有逐题自由文本，不能支撑完整 F03 的独立设计/分析/产物节点。 | 显示结构化引用缺件并保留逐题表；只有理论合成 fixture 的明示 ID 引用用于静态 F03 草图。 | mock-observation.*.html: figures<br>mock-theory.*.html: explicit edge table<br>source-map.json:F01/F02/F03 / missing-SQ-or-graph | F03私人修正候选未取得/未亲读；F01/F02 typed 来源仍 future/待补，不补造 DAG。 |
| SR06 | saved、预期产物和实际结果容易被合并理解为研究完成。 | 草稿保存/待核/研究未执行分开；实际结果保留 not-run/null，P7/P8/P9无总分，原费用/时程未知不填0。 | fixtures/*.json<br>mock-*.html: status/results/reviews/raw receipt / saved-draft / needs-information | 未执行研究、评分、先导或正式 A/B；没有科学有效性结论。 |
| SR07 | 理论案例的基线 selected view 未保证带完整 Stage2 背景/closest work；跨候选补内容会混版。 | 背景缺件显示 null/unknown，不借观察案例或其他版本；未来投影由 canonical owner 决定。 | mock-theory.*.html: overview<br>DESIGN.md: source projection limitation / version-changed / structured draft | 不扩API、不造选择/receiver pins；fixture不做产品schema/admission验证。 |
| SR08 | 静态按钮与绘图检查不能证明真人可用性、键盘行为、200%缩放或产品 E2E。 | 操作按钮全部 disabled，明确不接backend；规范写出44px目标、可见焦点和图的阅读键盘路径，验证状态保持 NOT_RUN。 | mock.css<br>state-matrix.json<br>README.md / all states | 真人usability、实际可及性/浏览器/缩放/E2E/独立source diff review仍需未来另验，不作merge gate。 |

NOT_RUN：human usability, actual keyboard/assistive technology/200% zoom verification, browser or product UI control, product source tests and CI, actual E2E/navigation/replay, real NativePlanner/model/grader, research/scoring/calibration/held-out/formal A/B/experiments, scientific validity

未造参与者、成功率、评分或费用；五项权限保持false。
