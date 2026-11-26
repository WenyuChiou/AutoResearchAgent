# Research Wiki 快速开始（Windows，零额度）

只写一条顺利路径：克隆 → 自检 → 启动 → 新建课题。全程不接模型、不接 Codex、不花额度。需要 Windows PowerShell 5.1（系统自带）、Git 和 Python 3.11 或更新版本。

## 1. 克隆

先设置两项 Git 选项（只需做一次），再克隆：

```powershell
git config --global core.longpaths true
git config --global core.autocrlf false
git clone https://github.com/WenyuChiou/AutoResearchAgent.git
cd AutoResearchAgent
```

## 2. 自检

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\doctor.ps1
```

每一项显示“通过”，或“没通过：原因；怎么修”。只要“必需项”没通过，就照它写的命令处理，再运行一次，直到最后一行写着“必需项全部通过”。全新克隆通常会先提示两件事：

```powershell
python -m pip install -r harness-ui\requirements.txt
python harness-ui\setup_vendor.py
```

自检只读，不会替你安装或修改系统设置。标着“仅前端测试”“仅真实运行”的项不影响启动。

## 3. 启动

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Open
```

脚本会自动建好数据目录（默认 `C:/ara`，可用 `-DataDir` 改成别的短路径）、选一个空闲端口、启动后打开浏览器。重复运行不会再起第二个：同一个数据目录的 Wiki 已在运行时，直接打开已有的。想先干跑检查，加 `-CheckOnly`；想停掉，加 `-Stop`。

## 4. 新建课题

在首页“新研究主题”里输入标题，点“创建项目”。

## 现在的限制

- 从首页新建的课题，目前只能走到 Stage 1 的范围确认。Stage 2 和 Stage 3 要等后台改动，现在还接不上。
- 只有零额度模式。真实运行模式（接 Codex）尚未提供，`-Real` 会直接报错。
- 项目数据都在数据目录里，不在 Git 检出中。路径不能太长：`<数据目录>/projects` 不超过 60 个字符。
