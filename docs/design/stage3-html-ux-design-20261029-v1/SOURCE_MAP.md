# 同版来源→画面元素对照

固定基线57ae0509；图、表、卡只读同一个saved view。下列为具体JSON pointer示例，不使用通配符；null表示基线缺件/future。

| 类别／元素 | 原view JSON pointer | 显示条件 | 空值处置 |
|---|---|---|---|
| D01 / 身份条 | /project_ref | 始终；project 未匹配则 empty | 缺失不猜默认项目 |
| D01 / 来源版本摘要 | /revision | 有同版 view 才显示 | null 与缺失分开，不制造 hash |
| D01 / 方向/候选版本 | /direction_context/questions/0/candidate_version | conditional；按 candidate_id + candidate_version join | 缺失显示未记录，不借其他候选 |
| D01 / 背景与重要性 | /direction_context/preferred_options/0/candidate/scientific_argument/motivation | 同候选版本才读 | 无原字段则 unknown；不补理由 |
| D01 / 现况/应用/closest work | /direction_context/preferred_options/0/candidate/scientific_argument/current_state | 仅原 claim/source_refs 明示内容 | 无文献来源不填引用或假结论 |
| D01 / gap/挑战 | /direction_context/preferred_options/0/candidate/scientific_argument/gaps/0/statement | 按原 gap_id / question.gap_ids | 缺字段保持缺件；意图贡献不写成已证贡献 |
| D02 / 逐 SQ 原题 | /direction_context/questions/0/text | conditional；question_ref 原样保留 | 缺 SQ 显示 missing mapping，不创建新问题 |
| D02 / 逐 SQ 原题 | /plan/questions/0/text | structured plan view；不证明正式选择 | source version 缺失则不宣称同版 |
| D02 / 方法/设计/验证/分析 | /plan/question_plans/0/method | question_ref 精确匹配；相邻原字段分别显示 | 未记录逐字段缺件；不根据题目生成方法 |
| D02 / 本题材料用途 | /plan/question_plans/0/materials | conditional question_ref join | 保留原文/原 unknown |
| D02 / 可能判读边界 | /plan/question_plans/0/interpretation | conditional 原记录 | 自由文本不自动拆成假结构化结论 |
| D05 / 材料入口/原资源 | /direction_context/preferred_cards/0/scientific_questions/0/resource_uses/0/resource | 同 candidate/version + question_id；原 source resource 对象 | 无 URL/原件收据则分别 unknown |
| D05 / 材料适配状态 | /direction_context/preferred_cards/0/scientific_questions/0/resource_uses/0/resource_ref/fit_status | 只展示原 fit_status | 入口存在不等于适配 |
| D05 / 来源记录的可用性 | /plan/resources/0/availability | structured resource_id join | unknown 不改 available；不等于已取得文件 |
| D05 / 使用条件/权利 | /plan/resources/0/access_conditions | 有原条件才显示其文字 | 没有合法权利证据时不显示已获许可 |
| D05 / 实际取得的文件与版本 | null / unknown | 基线 view 未保证含取得收据；未来仅接受原 owner 同版收据 | 未取得/未提供保持 unknown，不从 availability 推断 |
| D04 / 方案卡与共享标记 | /plan/designs/0/question_refs | design_id 精确 join；多 SQ 共享显示一次 | 引用不闭合显示缺件，不静默修补 |
| D04 / 输入/程序/验证/停止 | /plan/designs/0/procedure | 仅显式设计字段，比较从 comparisons 保留不适用理由 | 不将自由文字解析为 F02 DAG |
| D02 / 分析卡/引用 | /plan/analyses/0/design_ids | analysis_id 与设计、问题明确引用 | 不重复当独立实验 |
| D02 / 预期产物 | /plan/results/0/artifact | result_id join，标计划产物 | 无产物说明则未记录，不编造图 |
| D02 / 本研究实际结果 | /plan/results/0/observed_value | 与 status 同显；未执行显示 not-run/null | 不把 null 改0或画假趋势 |
| D02 / 支持/反驳/无法判定 | /plan/results/0/interpretation/supports | 同 result 的三个原字段 | 缺一项即该项未记录，不填成功 |
| D03 / F03 图位与完整文本对照 | /plan/question_plans/0/design_ids | 仅 structured 明确 question/design/analysis/result 引用 | conditional 无 IDs 时仅表/缺件；无图也不隐藏来源 |
| D03 / 整体科学路线占位 | null / unknown | future；无足够 typed scientific-route 来源 | 待补，禁止 Stage2→Python 替代科学论证 |
| D03 / 方案操作流程占位 | null / unknown | future；无足够 typed procedure relation | 待补；不从 procedure 自由文字推 DAG |
| D05 / unknown 最迟处理步骤 | /plan/unknowns/0/resolve_before | structured；与 question_refs/resource_ids 同版 | 不是日历期限；owner/null 保留 |
| D05 / 来源 unknown | /direction_context/source_unresolved/0 | conditional 分组显示 | 空数组=无记录条目，不证明没有风险 |
| D05 / 用户条件 | /direction_context/conditions/0 | 与 source unknown 分组 | 不作为已确认科学事实 |
| D05 / 用户 unresolved | /direction_context/unresolved/0 | 与 pending_scope_questions/missing_mapping 分组 | 缺件不消失、不变 available |
| D06 / P7/P8/P9 独立原评语/状态 | null / unknown | 基线 view 未提供完整绑定评审记录；未来由 core 接同版记录 | 当前 not-run/null，无总分，无伪评语 |
| D06 / 版本变动影响 | null / unknown | 只有既有 owner 绑定的 revision impact 才作为证据 | 缺失为未知，设计不自行宣布未受影响 |
| D07 / 按方案接续/规模依据 | /plan/milestones/0/duration_basis | 有同版 milestone 才显示 | 工时/日期未知不补数；未有代码/数据不称可执行 |
| D07 / 最小交付与下一步 | /plan/question_plans/0/minimum_deliverable | 对应原 SQ，不把文件存在当科学有效 | 未记录保持缺件 |
| D07 / 规划工作状态/主动作 | /job/outcome | 与 status/planning_status 分开显示 | saved 不等于研究完成；failed/unknown 保留 |
| D07 / 可展开的技术收据 | /default_request/key | 仅原 typed request/key/hash；mock 为 null | 没有 request 不生成一个或重发 run |
| D07 / 权限边界 | /execution_authorized | 五项 authority 原值始终保留 | false 不隐藏；不因视觉完成改变 |

版本标示：project/input_version/revision、candidate/version、原question_ref，以及已提供的plan/version或direction intent。完整hash没有提供就保持unknown，不补seal。

原字段来源/行号与版本规则见[source-map.json](source-map.json)，固定Git blob与原bytes hashes见[SOURCE_MANIFEST.json](SOURCE_MANIFEST.json)。
