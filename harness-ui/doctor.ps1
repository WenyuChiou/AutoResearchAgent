<#
.SYNOPSIS
  Read-only environment check for the local Research Wiki (Windows PowerShell 5.1+).
.DESCRIPTION
  Prints one line per check: pass, or "not passed: reason; how to fix".
  It installs nothing and changes no system setting. The only write is a
  throw-away probe file that is created and deleted inside the data directory
  (or its nearest existing parent) to see whether that location is writable.
  Exit code: 0 when every required check passes, 1 otherwise.
.PARAMETER DataDir
  Candidate data directory (default C:/ara). Same default as Start-Wiki.ps1.
.PARAMETER Port
  Candidate port (default 8765). A busy port is only advisory because
  Start-Wiki.ps1 picks another one automatically.
.PARAMETER Python
  Optional python executable to check first (also read from $env:ARA_PYTHON).
.PARAMETER PassThru
  Return the result objects instead of exiting (used by Start-Wiki.ps1).
.PARAMETER Quiet
  Do not print the per-check lines (use with -PassThru).
#>
[CmdletBinding()]
param(
    [string]$DataDir = 'C:/ara',
    [int]$Port = 8765,
    [string]$Python = '',
    [switch]$PassThru,
    [switch]$Quiet
)

$ErrorActionPreference = 'Stop'
$script:Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$script:Results = New-Object System.Collections.ArrayList

# Levels: 必需 (required) | 建议 (advisory) | 仅前端测试 | 仅真实运行
function Add-Result {
    param([string]$Id, [string]$Name, [string]$Level, [bool]$Ok, [string]$Message, [string]$Fix = '', $Extra = $null)
    $item = [pscustomobject]@{ Id = $Id; Name = $Name; Level = $Level; Ok = $Ok; Message = $Message; Fix = $Fix; Extra = $Extra }
    [void]$script:Results.Add($item)
    if (-not $Quiet) {
        if ($Ok) {
            Write-Host ('[通过]   ' + $Name + ' - ' + $Message) -ForegroundColor Green
        } else {
            $tag = if ($Level -eq '必需') { '[没通过] ' } else { '[没通过·' + $Level + '] ' }
            $color = if ($Level -eq '必需') { 'Red' } else { 'Yellow' }
            Write-Host ($tag + $Name + ' - 没通过：' + $Message + '；怎么修：' + $Fix) -ForegroundColor $color
        }
    }
}

# Run a native program with a timeout; never throws for a non-zero exit code.
function Invoke-Native {
    param([string]$File, [string[]]$ArgList = @(), [int]$TimeoutMs = 20000, [string]$WorkDir = '')
    $parts = @()
    foreach ($a in $ArgList) {
        if ($a -match '[\s"]' -or $a -eq '') { $parts += ('"' + ($a -replace '"', '\"') + '"') } else { $parts += $a }
    }
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    if ($File -match '\.(cmd|bat)$') {
        $psi.FileName = $env:ComSpec
        $psi.Arguments = '/c ""' + $File + '" ' + ($parts -join ' ') + '"'
    } else {
        $psi.FileName = $File
        $psi.Arguments = ($parts -join ' ')
    }
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    if ($WorkDir) { $psi.WorkingDirectory = $WorkDir }
    try {
        $proc = [System.Diagnostics.Process]::Start($psi)
    } catch {
        return [pscustomobject]@{ Started = $false; Code = -1; Out = ''; Err = $_.Exception.Message; TimedOut = $false }
    }
    $outTask = $proc.StandardOutput.ReadToEndAsync()
    $errTask = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit($TimeoutMs)) {
        try { $proc.Kill() } catch { }
        return [pscustomobject]@{ Started = $true; Code = -1; Out = ''; Err = 'timeout'; TimedOut = $true }
    }
    $proc.WaitForExit()
    return [pscustomobject]@{ Started = $true; Code = $proc.ExitCode; Out = $outTask.Result.Trim(); Err = $errTask.Result.Trim(); TimedOut = $false }
}

# ---- 1. Git -------------------------------------------------------------
$git = Get-Command git -ErrorAction SilentlyContinue
if ($git) {
    $v = Invoke-Native $git.Source @('--version')
    Add-Result 'git' 'Git' '必需' $true $v.Out
    $lp = Invoke-Native $git.Source @('config', '--get', 'core.longpaths')
    if ($lp.Out -eq 'true') {
        Add-Result 'git-longpaths' 'Git core.longpaths' '建议' $true 'true'
    } else {
        Add-Result 'git-longpaths' 'Git core.longpaths' '建议' $false ('当前值是 "' + $lp.Out + '"，克隆深层目录时 Windows 可能报路径太长') 'git config --global core.longpaths true'
    }
} else {
    Add-Result 'git' 'Git' '必需' $false '找不到 git' '安装 Git for Windows（https://git-scm.com/download/win），装完重开 PowerShell'
}

# ---- 2/3. Python version and modules --------------------------------------
$probe = @"
import sys, json
miss = []
for m in ('jsonschema', 'docx', 'openpyxl', 'sqlite3'):
    try:
        __import__(m)
    except Exception:
        miss.append(m)
print(json.dumps({'v': list(sys.version_info[:3]), 'exe': sys.executable, 'missing': miss}))
"@
# The import test uses the same rules as Start-Wiki.ps1 (no -I): packages installed
# for the current user count, exactly as they will when the Wiki starts. It runs in a
# neutral directory so nothing in the current folder can shadow a module.
$candidates = New-Object System.Collections.ArrayList
if ($Python) { [void]$candidates.Add(@($Python)) }
if ($env:ARA_PYTHON) { [void]$candidates.Add(@($env:ARA_PYTHON)) }
$repoVenv = Join-Path $script:Repo '.venv\Scripts\python.exe'
if (Test-Path -LiteralPath $repoVenv -PathType Leaf) { [void]$candidates.Add(@($repoVenv)) }
$pyLauncher = Get-Command py -ErrorAction SilentlyContinue
if ($pyLauncher) {
    foreach ($ver in @('-3.12', '-3.11', '-3')) { [void]$candidates.Add(@($pyLauncher.Source, $ver)) }
}
foreach ($name in @('python', 'python3')) {
    $c = Get-Command $name -ErrorAction SilentlyContinue
    if ($c) { [void]$candidates.Add(@($c.Source)) }
}
$found = New-Object System.Collections.ArrayList
$seen = @{}
foreach ($cand in $candidates) {
    $file = $cand[0]
    $pre = @()
    if ($cand.Count -gt 1) { $pre = @($cand[1..($cand.Count - 1)]) }
    $r = Invoke-Native $file ($pre + @('-c', $probe)) 20000 ([System.IO.Path]::GetTempPath())
    if ($r.Started -and $r.Code -eq 0) {
        try { $info = $r.Out | ConvertFrom-Json } catch { continue }
        if ($seen.ContainsKey($info.exe)) { continue }
        $seen[$info.exe] = $true
        [void]$found.Add($info)
    }
}
$good = $null
foreach ($info in $found) {
    if (([version]($info.v -join '.')) -ge [version]'3.11' -and @($info.missing).Count -eq 0) { $good = $info; break }
}
$newEnough = @($found | Where-Object { ([version]($_.v -join '.')) -ge [version]'3.11' })
if ($found.Count -eq 0) {
    Add-Result 'python' 'Python 版本' '必需' $false '找不到可运行的 Python' '安装 Python 3.11 或更新版本（winget install Python.Python.3.11），装完重开 PowerShell；也可用 -Python 指定路径'
    Add-Result 'python-modules' 'Python 模块' '必需' $false '没有 Python 可检查' '先装好 Python 3.11+'
} elseif ($newEnough.Count -eq 0) {
    $top = $found[0]
    Add-Result 'python' 'Python 版本' '必需' $false ('只找到 ' + ($top.v -join '.') + '（' + $top.exe + '），仓库 CI 用 3.11') '安装 Python 3.11 或更新版本，或用 -Python 指定路径'
    Add-Result 'python-modules' 'Python 模块' '必需' $false '没有满足版本的 Python 可检查' '先装好 Python 3.11+'
} else {
    $pick = if ($good) { $good } else { $newEnough[0] }
    Add-Result 'python' 'Python 版本' '必需' $true (($pick.v -join '.') + '  ' + $pick.exe) '' $pick.exe
    if ($good) {
        Add-Result 'python-modules' 'Python 模块（jsonschema、docx、openpyxl、sqlite3）' '必需' $true '全部可导入' '' $good.exe
    } else {
        $req = Join-Path $script:Repo 'harness-ui\requirements.txt'
        Add-Result 'python-modules' 'Python 模块（jsonschema、docx、openpyxl、sqlite3）' '必需' $false ('缺少：' + (@($pick.missing) -join '、')) ('在仓库根目录依次运行这两行（建专用虚拟环境，并用同一个 Python 安装；本脚本不会替你装，装好后 doctor 和 Start-Wiki 会自动用 .venv）：& "' + $pick.exe + '" -m venv .venv ; .\.venv\Scripts\python.exe -m pip install -r "' + $req + '"')
    }
}

# ---- 4. Frontend vendor file -------------------------------------------------
$vendor = Join-Path $script:Repo 'harness-ui\renderer\vendor\three.core.js'
$vendorFix = '在仓库根目录运行一句：python harness-ui\setup_vendor.py （联网下载并校验固定哈希；没有网络时加 --from-file <已有的 three.core.js>）'
if (Test-Path -LiteralPath $vendor -PathType Leaf) {
    $wantSha = $null
    try { $wantSha = ((Get-Content -LiteralPath (Join-Path $script:Repo 'harness-ui\renderer\vendor\three.core.provenance.json') -Raw -Encoding UTF8) | ConvertFrom-Json).archive_member_sha256 } catch { }
    $haveSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $vendor).Hash.ToLower()
    if ($wantSha -and $haveSha -ne $wantSha) {
        Add-Result 'vendor' '前端依赖 three.core.js' '必需' $false '文件存在，但哈希和仓库记录的不一致（文件损坏或版本不对）' $vendorFix
    } else {
        Add-Result 'vendor' '前端依赖 three.core.js' '必需' $true $vendor
    }
} else {
    Add-Result 'vendor' '前端依赖 three.core.js' '必需' $false '文件不存在（它被 Git 忽略，克隆后默认没有），没有它 Wiki 起不来' $vendorFix
}

# ---- 5. Node (frontend tests only) ----------------------------------------------
$nodeExe = $null
$nodeCmd = Get-Command node -ErrorAction SilentlyContinue
if ($nodeCmd) { $nodeExe = $nodeCmd.Source }
if (-not $nodeExe -and $env:ARA_NODE -and (Test-Path -LiteralPath $env:ARA_NODE -PathType Leaf)) { $nodeExe = $env:ARA_NODE }
if (-not $nodeExe) {
    foreach ($base in @($env:ProgramFiles, ${env:ProgramFiles(x86)}, $env:LOCALAPPDATA)) {
        if ($base) {
            $guess = Join-Path $base 'nodejs\node.exe'
            if (Test-Path -LiteralPath $guess -PathType Leaf) { $nodeExe = $guess; break }
        }
    }
}
if ($nodeExe) {
    $nv = Invoke-Native $nodeExe @('--version')
    $where = ''
    if (-not $nodeCmd) { $where = '（不在 PATH 里，用完整路径调用：& "' + $nodeExe + '" harness-ui\test_xxx.cjs）' }
    Add-Result 'node' 'Node.js' '仅前端测试' $true ($nv.Out + $where) '' $nodeExe
} else {
    Add-Result 'node' 'Node.js' '仅前端测试' $false '找不到 node（只有跑前端测试 harness-ui\test_*.cjs 时才需要，启动 Wiki 不需要）' '需要时安装 Node.js 22（winget install OpenJS.NodeJS.LTS），或设置环境变量 ARA_NODE 指向已有的 node.exe'
}

# ---- 6. Data directory ----------------------------------------------------------
$dataFull = [System.IO.Path]::GetFullPath($DataDir)
$projectsRoot = Join-Path $dataFull 'projects'
$problems = @()
$cursor = $dataFull
while ($cursor) {
    if (Test-Path -LiteralPath (Join-Path $cursor '.git')) { $problems += ('在 Git 检出里面（' + $cursor + '）'); break }
    $parent = [System.IO.Directory]::GetParent($cursor)
    if ($parent) { $cursor = $parent.FullName } else { $cursor = $null }
}
$repoNorm = $script:Repo.TrimEnd('\') + '\'
if (($dataFull.TrimEnd('\') + '\').StartsWith($repoNorm, [System.StringComparison]::OrdinalIgnoreCase) -or $repoNorm.StartsWith(($dataFull.TrimEnd('\') + '\'), [System.StringComparison]::OrdinalIgnoreCase)) {
    $problems += '和仓库目录互相包含'
}
$cursor = $dataFull
while ($cursor) {
    if (Test-Path -LiteralPath $cursor) {
        $attr = [System.IO.File]::GetAttributes($cursor)
        if (($attr -band [System.IO.FileAttributes]::ReparsePoint) -ne 0) { $problems += ('路径中有链接或联接点（' + $cursor + '），产品会拒绝'); break }
    }
    $parent = [System.IO.Directory]::GetParent($cursor)
    if ($parent) { $cursor = $parent.FullName } else { $cursor = $null }
}
if ($problems.Count -eq 0) {
    Add-Result 'data-location' ('数据目录位置 ' + $dataFull) '必需' $true '在 Git 检出之外，且路径中没有链接'
} else {
    Add-Result 'data-location' ('数据目录位置 ' + $dataFull) '必需' $false ($problems -join '；') '用 -DataDir 指向 Git 检出之外的普通短目录，例如 C:/ara'
}

# The product rejects a Windows projects root longer than 60 UTF-16 characters.
$len = $projectsRoot.Length
if ($len -le 60) {
    Add-Result 'data-length' '数据目录路径长度' '必需' $true ('项目根 ' + $projectsRoot + ' 共 ' + $len + ' 个字符（上限 60）')
} else {
    Add-Result 'data-length' '数据目录路径长度' '必需' $false ('项目根 ' + $projectsRoot + ' 共 ' + $len + ' 个字符，超过上限 60') '换一个更短的 -DataDir，例如 C:/ara'
}

$probeDir = $dataFull
$blockingFile = $null
while ($probeDir -and -not (Test-Path -LiteralPath $probeDir -PathType Container)) {
    if (Test-Path -LiteralPath $probeDir -PathType Leaf) { $blockingFile = $probeDir; break }
    $parent = [System.IO.Directory]::GetParent($probeDir)
    if ($parent) { $probeDir = $parent.FullName } else { $probeDir = $null }
}
if ($blockingFile) {
    Add-Result 'data-writable' '数据目录可写' '必需' $false ('路径里已经有一个同名的普通文件：' + $blockingFile + '，不能再当目录用') '用 -DataDir 另选一个目录（或先把这个文件移走），例如 C:/ara'
} elseif (-not $probeDir) {
    Add-Result 'data-writable' '数据目录可写' '必需' $false '找不到任何已存在的上级目录' '换一个 -DataDir'
} else {
    $probePath = Join-Path $probeDir ('.ara-doctor-' + [guid]::NewGuid().ToString('N') + '.tmp')
    try {
        if ($probeDir -eq $dataFull) {
            # The directory exists: it must accept files.
            [System.IO.File]::WriteAllText($probePath, 'x')
            Remove-Item -LiteralPath $probePath -Force
        } else {
            # The directory will be created by Start-Wiki: it must accept a new folder
            # (a drive root allows folders but not files by default).
            [void][System.IO.Directory]::CreateDirectory($probePath)
            Remove-Item -LiteralPath $probePath -Force
        }
        $where = if ($probeDir -eq $dataFull) { '已存在且可写' } else { '尚不存在，将在可写的 ' + $probeDir + ' 下创建' }
        Add-Result 'data-writable' '数据目录可写' '必需' $true $where
    } catch {
        Add-Result 'data-writable' '数据目录可写' '必需' $false ($probeDir + ' 不能写入：' + $_.Exception.Message) '换一个你有写权限的短目录，例如 -DataDir "$env:USERPROFILE\ara"（用户名太长时改用 D:/ara 之类，项目根路径不能超过 60 个字符）'
    }
}

# ---- 7. Port -----------------------------------------------------------------------
$listener = $null
try {
    $listener = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Port)
    $listener.Start()
    Add-Result 'port' ('端口 ' + $Port) '建议' $true '空闲'
} catch {
    Add-Result 'port' ('端口 ' + $Port) '建议' $false '已被占用（可能是本数据目录已在运行的 Wiki）' 'Start-Wiki.ps1 会自动换一个端口；也可用 -Port 指定'
} finally {
    if ($listener) { $listener.Stop() }
}

# ---- 8. GIT_EDITOR --------------------------------------------------------------------
if ($env:GIT_EDITOR) {
    Add-Result 'git-editor' '环境变量 GIT_EDITOR' '建议' $false ('已设置为 "' + $env:GIT_EDITOR + '"，会让部分 Python 测试在需要编辑器时卡住或失败；不影响启动 Wiki') '只在跑测试的窗口里取消：Remove-Item Env:GIT_EDITOR（本脚本不会替你改）'
} else {
    Add-Result 'git-editor' '环境变量 GIT_EDITOR' '建议' $true '未设置'
}

# ---- 9. Codex (real runs only) ------------------------------------------------------------
$codex = Get-Command codex -ErrorAction SilentlyContinue
if (-not $codex) {
    Add-Result 'codex' 'Codex 安装与登录' '仅真实运行' $false '找不到 codex（只有以后接真实模型时才需要，零额度启动不需要）' '需要时按 Codex 官方说明安装，并自己在终端运行 codex login'
} else {
    $cv = Invoke-Native $codex.Source @('--version')
    $cs = Invoke-Native $codex.Source @('login', 'status')
    $text = ($cs.Out + ' ' + $cs.Err).Trim()
    if ($cs.Code -eq 0) {
        Add-Result 'codex' 'Codex 安装与登录' '仅真实运行' $true ($cv.Out + '；' + $text)
    } else {
        Add-Result 'codex' 'Codex 安装与登录' '仅真实运行' $false ($cv.Out + '，但未登录或状态未知：' + $text) '需要真实运行时自己在终端运行 codex login（本脚本不会替你登录）'
    }
}

# ---- Summary ---------------------------------------------------------------------------------
$required = @($script:Results | Where-Object { $_.Level -eq '必需' })
$requiredFailed = @($required | Where-Object { -not $_.Ok })
$optionalFailed = @($script:Results | Where-Object { $_.Level -ne '必需' -and -not $_.Ok })
if (-not $Quiet) {
    Write-Host ''
    if ($requiredFailed.Count -eq 0) {
        Write-Host ('总结：必需项 ' + $required.Count + ' 项全部通过。') -ForegroundColor Green
    } else {
        Write-Host ('总结：必需项 ' + $required.Count + ' 项中有 ' + $requiredFailed.Count + ' 项没通过，先按上面的“怎么修”处理。') -ForegroundColor Red
    }
    if ($optionalFailed.Count -gt 0) {
        Write-Host ('另有 ' + $optionalFailed.Count + ' 项可选/场景项没通过，不影响零额度启动。') -ForegroundColor Yellow
    }
}
if ($PassThru) {
    $script:Results
} else {
    if ($requiredFailed.Count -eq 0) { exit 0 } else { exit 1 }
}
