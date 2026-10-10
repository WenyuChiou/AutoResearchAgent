The optional `--demonstrate-stage2-run` mode adds one fixed engineering action to
the saved-case review example. The normal launcher, production
StageActions allowlist and Codex/Harness execution permissions are unchanged.

Run from a complete checkout:

```powershell
python -B -X utf8 plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py --output C:/your/private/new-stage2-demo --serve --stage-actions --demonstrate-ready-saved-case --demonstrate-stage2-run
```

Open the printed Stage 2 URL, select Stage 2 in the sidebar, scroll to “Run the
repository Stage 2 case”, and tick the synthetic-demo confirmation. Click “Run
repository Stage 2 demo” once. The POST waits for the fixed isolated Python
worker, bounded to 20 seconds, and returns a durable outcome. A fresh workflow,
controller journal, independent synthetic review records, reconciliation and
delivery are written under `stage2-run-demo/run-once`. The output packet is the
repository `Stage2ControllerTests` fixture: two saved source works, one idea.

“Read run history”, page reload and reconnect issue GETs only. A saved completed,
failed or unknown intent disables another run. “Download the new delivery
report” reads the actual saved `selection.html` through an authenticated,
hash-checked fixed route; it does not generate new output. The original graph,
source index and previously saved Stage 2 example above remain separate.

This is the legacy `Stage2Packet 1.0.0` controller regression fixture, independent
of the displayed Stage 1. The ordinary `stage2-general-v3/daily_v3` route, its
rubric and fixed denominator are not evaluated here. SyntheticAdapter creates
test review records without a model, search, native Codex or external judge.
The missing topic matrix and independent assessment remain missing. A generated
delivery is not completed Stage 2, scientific acceptance, human selection or
permission to start Stage 3. Timeout/crash outcomes remain unknown and never
trigger automatic resume. The worker is killed and reaped on its time bound.

中文：在 Stage 2 页面选择侧栏 Stage 2 后，滚动到“运行仓库 Stage 2 案例”。确认
模拟案例后只点击一次。新交付与真实运行记录会保存；刷新只读历史，不会重跑。
这是两份源文本、一个候选方向的仓库工程测试，不是上方 Stage 1 文献的连续研究。
本例未启动 Codex、真实模型、搜索或评分，不修改普通 v3 的评分规则。交付生成后仍
显示缺少 topic matrix／独立评估，不能据此认为 Stage 2 已验收或自动进入 Stage 3。
