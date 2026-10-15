# PR #295 7 文件增量的独立只读审阅

结论：在本次明确限定的 7 文件候选补丁中，未发现需要阻断交付的 correctness/security 问题，也未发现生产 runtime pin、测试分母、平台要求、时限或科研权限漂移。这是静态源码审阅结论；本报告没有运行测试、安装依赖、下载新 checkout、启动 Wiki、执行浏览器验收、调用模型、搜索或原生研究过程。它不批准 PR、不 resolve review、不授权 merge，也不是 Core acceptance。

## 被审版本和证据绑定

- Checkout：`D:/Codex_Learning/harness_building/_d14/pr295-team-wiki`。
- 原 HEAD 与比较基线：`de4815a5f3045546dd956a81398d68b3e1515651`。
- 被审对象：该 HEAD 之上的未提交候选补丁，恰好 7 个普通修改文件（Wiki docs 2 + CI/test 5）。
- 取样 UTC：`2026-10-14T07:39:59.211335+00:00`。
- Patch 字节：14692。
- Patch SHA-256：`9971aa7cdbfc45e32a225b8fd8cf0328dc9e309bd207f47b456806ff5e1c7dae`。
- Patch 重建命令：`git diff --binary --full-index --no-ext-diff --no-textconv de4815a5f3045546dd956a81398d68b3e1515651 --`。Hash 是 Git stdout 的原始字节 SHA-256；采用 full-index。使用不同 diff 参数或重排文档后必须重新绑定。
- 取样时没有从远端重新验证 PR 状态或 branch head。Wiki 的 clone 命令会下载可变 PR branch，并打印实际 HEAD；终端验收仍须把该 HEAD 和执行记录绑定到最终候选。

| 候选文件 | 取样工作文件 SHA-256 |
|---|---|
| `.github/scripts/stage1_test_scope.py` | `60841721dbb0aa5cf1cb9b79a7db6222636e1edd4c092b1b21c95cc025b0883c` |
| `.github/scripts/test_stage1_ci_quality.py` | `46d816076d2af1ffd5b5126388aa10185ce568f1af4a44763beafba9bccef69c` |
| `.github/scripts/test_stage1_test_scope.py` | `2d815af5a6c21cbc22a01ee87cf47360d716d12633ea29564021824404567a89` |
| `.github/workflows/stage1-plugin.yml` | `f1cc64ab2ede252175cb0791c40330dbc133a6f4de0e4e2c5a74a325b423ab6b` |
| `plugins/auto-research-agent/references/research-workspace/PORTABLE_ATLAS_SETUP.md` | `483b13aad6dd5b8153d1c04262fd1d7ff6de22b7f632e419af0f4c20bb631fe3` |
| `plugins/auto-research-agent/references/research-workspace/atlas-launch-guide.md` | `e7d2ac0305789fee3eabef75f1ddbefc7ff9d93a69bfdf6ea57c7552162a6ba7` |
| `plugins/auto-research-agent/tests/test_research_workspace_process_channel_recovery.py` | `7dd684c22b466c24fb8f2118bc8affa9b2054038f2296b6efc798cc6dba06426` |

## Correctness / security 核对

### 1. Job 环境传到 parent、spawn 与 nested Python

`.github/workflows/stage1-plugin.yml:50` 在 contracts job 设置 `PYTHONDONTWRITEBYTECODE: "1"`，涵盖三个平台的每一步，现有测试步骤没有覆盖/删除该变量。`stage1_test_scope.py:258` 与 `:272` 的 ProcessPoolExecutor 使用 spawn，且没有另造过滤 environment；常规子进程继承 job 环境。

新增 `test_stage1_ci_quality.py:171` 从 YAML contracts job env 构造环境；先移除宿主同名变量，所以不能靠宿主预置误通过。它对父解释器、真实 spawn worker、worker 的 nested subprocess 分别断言 `sys.dont_write_bytecode`，最后检查整个临时目录无 .pyc。外层 subprocess 保留 20 秒 timeout。这里是代码路径和测试设计核对，本报告未执行该新增测试。

生产 `stage1_retrieval/runtime_identity.py` 未变：inspect_python 与 verify_identity 仍显式要求 `-I -B`；tree_files 仍包含 .pyc 等代码/cache bytes；verify_identity 仍重建完整 actual inventory 并与冻结 files 相等比较。隔离解释器忽略环境变量时，由其显式 `-B` 保持同一要求。没有通过排除 cache bytes 或修改 runtime validator 来掩盖 drift。raw-source loader 与 saved parser 的 guard 也未变。

### 2. Serial deadline 只改变调度，保留全部测试和截止要求

`stage1_test_scope.py:52` 仅新增 `test_owned_source_observations` 和 `test_portable_atlas_git_checkout` 到已有 serial group。run_parallel 仍先完成并关闭全部 parallel executor，再以单独 spawn worker 执行 serial inventory。partition 和 serial/parallel 联合清单保留 Counter 比较；run_partition 保留 loader errors、完整 IDs、planned_tests 与 tests_run 相等、failures/errors/skips 和 incomplete_partitions 报告。serial 的异常或退出仍走失败状态。

扩展 `test_deadline_modules_run_after_workers_without_losing_cases` 到三个 serial fixture，保持 worker-finished 前置检查和非 MainProcess 检查，并把精确期望更新为 (6 planned, 6 run, 0 incomplete)、serial_tests=3。已有 serial-only、失败、zero-exit 和 incomplete-partition 回归仍在；没有删除 selector 或 skip guard。

workflow 的 ubuntu/windows/macos matrix、fail-fast=false、selector fail-closed 门、full 90 分钟，以及各非 full 时限均与 baseline 相同。原始 socket/SQLite/subprocess 时限未改；portable Git fixture 仍有每次 15 秒 timeout，owned-source raw runner 仍使用 `-I -B`。自修改 selector/workflow 的 diff 仍触发 full suite。最终全套 CI 的实际完成情况须由父任务/CI 记录确认，不能由这份静态审阅推导。

### 3. Windows busy fixture 只缩小拦截范围，真实清理保留

`test_research_workspace_process_channel_recovery.py:92` 复制 process_channel 的 subprocess namespace，并仅替换该副本的 Popen。这样业务子进程仍经过 after_spawn、真实 spawn、BEGIN IMMEDIATE 和时间观测；共享标准 subprocess 模块没有被替换。

production `process_channel.py` 导入的 `codex_probe._cleanup` 在自己的模块 namespace 查找 subprocess。因此 Windows 的真实 `taskkill.exe /PID ... /T /F` 及其 3 秒 timeout、wait/kill fallback 与 pipe close 保留，不会被测试当成第二个业务 spawn，也不会第二次 BEGIN IMMEDIATE。该测试仍要求 1 个 owned child、1 个 startup deadline、0.8 秒内失败返回、真实 child poll 结束、finally wait(timeout=2) 和数据库 rollback/close。没有把物理清理换成 mock，也没有放宽本次候选的时间断言。

源码仍保留 `process_tree_containment_verified=False` 与 Windows containment 未验证边界；本改动不能据此宣称 Windows 树隔离已通过。

### 4. Wiki 终端命令与现有 CLI 一致

`PORTABLE_ATLAS_SETUP.md:3` 使用 PR #295 的分支名称克隆完整仓库，command-scoped longpaths 与 clone-local autocrlf=false 保留源字节；失败后中止。明确要求 Git/Python 3.11，并通过该 venv 的绝对 Python 安装固定 requirements-test.txt（包含研究 SDK 的固定 Git SHA），后续所有命令使用同一 Python、`-B -X utf8`。依赖导入检查与报错说明相符。

case 与 projects 使用同一短 outside-Git parent 下的不同新 timestamp 路径；默认 projects root 约 39 个 UTF-16 字符，低于原有 60 字符限。实际 launcher 保留 absolute path、reparse/link、repo overlap、任何父级 .git、private parent 与 Windows 深度检查；builder 的 private_output 也要求 Git 并检查 outside-Git。文档保留失败输出和历史 attempt，没有指示绕过 guard。

builder 默认生成独立 synthetic saved Stage 1/2 fixture，并保存 config/config_sha256 receipt；不是真实完整研究链或新项目的自动结果。launcher 的参数名称与新命令一致；CLI helper 的实际 SHA-256 与 receipt 的 views hash 被传入，launcher 启动前验证 source-helper/script/views bytes。该 SHA 是所选 checkout 的本地源绑定；clone branch 是可变引用，所以它不是独立证明远端最终 head 已与这份补丁完全相同。

命令没有 `--enable-content-model`、Codex/home/model 参数、query runtime 或 public-source enable。源码把 factory 保持 None、models provider 不连接，queries 不创建；startup、GET、topic 输入不探测或启动 Codex。启动 receipt 明示 content_model disabled、native_calls=0、model_calls=0 与 Stage 3–6 planned/unconnected。父任务终端验收须仍保留这些实际 receipt。

ProjectHost 在已注册 views 时 root / 重定向到首个 saved view，配置顺序首先是 stage1；/projects.html 保持 portal。文档更正与 `project_host.py:755` 实现一致。模板 HTML、旧 localhost URL、check-only 和真实 server/dependency/authentication/research completion 的边界写明。最终浏览器布局、点击与启动成功不在本报告执行证据内。

## Harness drift 核对

当前 root/plugin AGENTS 的 routing、review-only 和 Core-only merge 条款已核对；并读取适用 CONTRIBUTING、evaluation/readiness/PR guide、科研指标准则与 registry 的相关段落。使用 research-harness 文件审计模式和 anti-defensive-writing 规则。没有创建科研 job 或改变项目状态。

本增量仅解释现有入口、抑制 CI cache 写入、调整测试调度和缩小测试 patch namespace。它没有改生产 runtime/schema/registry、研究评分、正式 A/B/freeze、Core merge ownership、配置/凭据或 model/search/native admission。两份文档仍将 synthetic saved reference 与新项目 delivery 区分，保持未生成/未连接状态。

在 checkout 范围内，layout/runtime 关键文件与 baseline 原字节相同（下面列 hash）；因此该增量没有修改仓库内既有布局。用户本地 v6 原件的跨目录历史 hash 未提供给本审阅者，本报告不会把“diff 没有布局文件”扩大为对外部 v6 原件的历史证明。父任务应保留其既有 v6 原 hash 比较记录。

- `.gitattributes`: baseline 字节相同；SHA-256 `01454eb0236faa686a2ab5b5fbed6b7e0fafaf7762d70f14444a52511d3e9925`。
- `plugins/auto-research-agent/cli/stage1_retrieval/runtime_identity.py`: baseline 字节相同；SHA-256 `da4ee52b8922539039494c1b9683ed8e0516ae9ff9c405d64c3cddd164f1415f`。
- `plugins/auto-research-agent/cli/research_workspace_native/codex_probe.py`: baseline 字节相同；SHA-256 `f2d560349cc4dda0dd8c2196caff3b341d8a5a849a833625081515bfe3724f6c`。
- `plugins/auto-research-agent/cli/research_workspace_native/process_channel.py`: baseline 字节相同；SHA-256 `52341ff439f1c90298ff288db593bfa7e2542fbb4212e8deb06dd60fbf2f408b`。
- `plugins/auto-research-agent/cli/research_workspace_native/saved_source_parser_runtime.py`: baseline 字节相同；SHA-256 `7f2b765e164860cc085a6b0d1476ff5fd5c3a58905f3f052a424385c700b5cdb`。
- `plugins/auto-research-agent/cli/research_workspace_native/atlas_local_source.py`: baseline 字节相同；SHA-256 `7e09e7f3be5ee894863959d8774c2b0e39de11f4e164088933fb738aadaefef4`。
- `plugins/auto-research-agent/cli/research_workspace_native/project_host.py`: baseline 字节相同；SHA-256 `869cf0f2ea34e84ff5c24c13d30c5cf8431e1c8db675b35041d8f11139555cde`。
- `plugins/auto-research-agent/references/research-workspace/examples/run-project-workspace.py`: baseline 字节相同；SHA-256 `8f7dc4096baa9ba290a04cd45789adc75c87fc93baf740c953aa1e40738728b7`。
- `plugins/auto-research-agent/references/research-workspace/examples/build-review-fixture.py`: baseline 字节相同；SHA-256 `948acd26443f5d6dc793f2473f1142327535e202543a44bb70863cd7675897cf`。
- `plugins/auto-research-agent/evals/capability-metric-map.v1.json`: baseline 字节相同；SHA-256 `b75122de16fe93317958c5d81ab29310a9185103c03eaf2ea22202b7cfa00598`。
- `plugins/auto-research-agent/evals/capability-metric-map.v3.json`: baseline 字节相同；SHA-256 `71b396a541e4bca96df00eb6f9a48311ad468b1ce689043f31b31ec83f9544b2`。
- `plugins/auto-research-agent/references/research-workspace/atlas/atlas.html`: baseline 字节相同；SHA-256 `6870e7999674c66ac23de25cce14a360dad47e4ff58d1ba2a823a1199a1c7cc3`。
- `plugins/auto-research-agent/references/research-workspace/atlas/atlas.css`: baseline 字节相同；SHA-256 `bec89cbf2176de13e347ce69770ce8c5f32f3f67b57fcf024695c249a6918350`。

## 交付边界

- Blocking findings：未发现（只限上述 7 文件和相关消费者的静态审阅）。
- 实际 tests：本审阅者未执行；父任务所述运行中的测试需独立记录最终结果及确切版本。
- Clean clone / terminal Wiki / rendered UI：本审阅者未执行；文档与源码一致性已核对，仍需父任务实际验收。
- Scientific improvement：not yet demonstrated；本改动及局部测试不证明 P1–P9、G1、freeze 或 formal A/B。
- 本报告不构成 PR approval、review resolution、Core acceptance 或 merge 授权。
