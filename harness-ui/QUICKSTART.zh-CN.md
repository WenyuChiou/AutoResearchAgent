# Research Wiki 快速开始（Windows，零额度）

English: [QUICKSTART.md](QUICKSTART.md)

三步从零把 Wiki 打开。**这是零额度模式：不接模型、不接 Codex、不做任何检索，也不会自动运行研究**，所以不会花任何额度。需要 Windows PowerShell 5.1（系统自带）、Git 和 Python 3.11 或更新版本。

## 1. 克隆并装好依赖

```powershell
git config --global core.longpaths true
git clone https://github.com/WenyuChiou/AutoResearchAgent.git
cd AutoResearchAgent
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r harness-ui\requirements.txt
.\.venv\Scripts\python.exe harness-ui\setup_vendor.py
```

最后一句下载前端依赖 `three.core.js`（它被 Git 忽略，克隆下来默认没有，缺了 Wiki 起不来），并校验固定哈希。没有网络时加 `--from-file <已有的 three.core.js>`。

## 2. 自检（只读）

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\doctor.ps1
```

每一项显示“通过”，或“没通过：原因；怎么修”。只要“必需项”没通过，就照“怎么修”处理，再运行一次，直到最后写着“必需项全部通过”。自检不会替你安装或修改系统设置；标着“仅前端测试”“仅真实运行”“建议”的项不影响启动。其中 Codex 项会运行 `codex --version` 和 `codex login status`（只读本机状态，不调用模型、不检索）；不想运行它就给 doctor 加 `-SkipCodex`，`Start-Wiki.ps1` 调用 doctor 时已自动加上。

## 3. 启动

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Open
```

脚本会建好数据目录（默认 `C:/ara`，可用 `-DataDir` 换成别的短路径）、选一个空闲端口、启动并打开浏览器，首次启动大约要二三十秒。重复运行不会起第二个：同一个数据目录已有 Wiki 在运行时，直接打开已有的。

- 先干跑检查、什么都不启动：加 `-CheckOnly`
- 停止：`powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Stop`（数据目录不是默认值时加同一个 `-DataDir`）
- 默认端口被占用时自动换下一个，不会动占用它的程序；脚本只会停止它自己启动的、能确认是本项目 Wiki 的那个进程。

打开后在首页“新研究主题”里输入标题，点“创建项目”即可开始。

## 现在的限制

- 一键脚本只有零额度模式，`-Real` 会直接报错。要真实运行 Stage 1，直接给 `harness-ui/run_v9.py` 加参数（`python harness-ui/run_v9.py --help` 有完整说明）：查询运行时和材料根、公开来源、内容模型加 Codex。这些参数只是注册，不是授权，每一步仍要在页面里授权；开启后自动检索会花额度。要让整轮自动推进，再加 `--enable-stage1-run`（需要内容模型和公开来源），然后在 Stage 1 页的「运行许可与授权理由」里写下你的理由并确认，创建运行许可；命令行的 `--stage1-run-request` 不再支持，启动时会被拒绝。
- 零额度下可以新建课题、写范围、导入已有检索规划，但**拿不到文献**：没有检索，账本里就没有来源，「导入已保存的来源包」的入口还没有。
- Stage 2、Stage 3 需要的运行配置，这个脚本没有传，默认不启用。
- 唯一入口是 `run_v9.py`（`Start-Wiki.ps1` 是它的零额度一键启动）。旧启动器 `run-project-workspace.py` 只为兼容保留，不再推荐，不支持的参数 `run_v9.py` 会在启动时拒绝并说明。
- 项目数据都在数据目录里，不在 Git 检出中。路径不能太长：`<数据目录>/projects` 不超过 60 个字符，超过时自检会提示换短路径。
- `Start-Wiki.ps1` 在 `.venv` 存在时会自动用它；也可以用 `-Python <路径>` 或环境变量 `ARA_PYTHON` 指定别的 Python。
- 只在已有的 Windows 账号上测过；没有在全新的干净 Windows 账号上测过。
