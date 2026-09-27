# P3 完整證據判讀與匯合

Stage 1 evaluator / T2；`implementation-only`，尚未证明科研指标改善。

`criterion_execution.judge_process_complete` 执行 P3 的三个 frozen criteria。
`judge_process_criterion` 可执行单项。调用者先验证 capture/packet，传入
冻结模型配置；此层不联网、不修补受测资料，也不替代完整 evaluator 入口。

每个 criterion 复用 PR #34 的完整 span routing，以 4,500 UTF-8 bytes 划分
证据及邻近上下文。R1/R2 在不同目录分别产生原生调用；提示没有角色或组别标签。
若 Unicode 原片段及上下文无法放入预算，执行前改为 300 字符的片段，生成可重建的
`Stage1CriterionCoveragePlan.v2`；不删除原文，默认 900 字符的 v1 计划保持原格式。
每个主片段必须返回 supporting / contrary / uncertain / irrelevant 与原因，
代码还原原文位置。上下文不重复计入完成数；缺失或重复的处理结果会失败。
同一事件的原始与解码视图共享中性 document 标记。提示明确：片段观察计数不是
独立搜索、结果或作品数量；实际行动只能按原始记录判断。

汇合是每次两个子节点的树。模型解释每个子节点如何影响判断；程序保留所有
原始子判定、位置、父子 hash 和各类观察计数，反证或未知的摘要不得变为空。
最终节点按原 rubric 给 0/1/2 或 null；不平均片段分数。汇合模型仍可能解释错误，
完整提交与位置校验不能证明模型理解或判断正确，必须保留独立复核。

R1/R2 的分數、狀態、穩定結論代碼、缺失證據代碼或任一片段的語義分類不同時，
才執行 ADJ。ADJ 重新處理同一份證據，並只看到對應單元的兩份先前判斷；保留
所有版本。純措辭差異不觸發 ADJ，但兩位 judge 指出不同種類的缺失證據時不能
假裝已達成一致。
全部输入、模型执行记录及输出都通过重放校验后才复用；不把一次生成算成两个 judge。

初始及纠错提示均限制为 9,000 UTF-8 bytes，输出限制为 3,000 bytes。超限、超时、
缺档或篡改是 evaluator error，保留 completed/pending/error 清单，不转成 subject
unknown 或零分。P0：提示可能超过 1,000 tokens，需独立人工 context review。

執行前會以最壞情況（R1、R2、ADJ；每個 generation 最多四次原生嘗試）一次計算
整個呼叫的成本上限。每個 criterion 最多 42 個 leaf units；三個 P3 criteria 合計
最多 126 個 criterion-units、756 個 logical generations、3,024 次原生嘗試。任一
上限超過時，在第一個 model call 前失敗；不得截掉 evidence 來硬塞進預算。

返回 `Stage1CompleteProcessCriterion.v1` 包含所有原生节点与 coverage manifest。
`formal_eligible=false`：P1/P2 逐作品/claim 的整合、重大错误独立判读、共同 observer、
正式入口整合及核心组审核仍待完成。这是实际可调用的 P3 判读路径，不是正式 A/B 结果。
