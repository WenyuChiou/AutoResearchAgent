<#
.SYNOPSIS
  One-command local start of the Research Wiki in zero-quota mode (Windows PowerShell 5.1+).
.DESCRIPTION
  Locates the repository from this script's own location, runs the required
  doctor.ps1 checks, creates the data sub-directories, computes the helper
  SHA-256, picks a free port, starts harness-ui/run_v9.py with
  harness-ui/zero-limits.json (no model, no Codex, no quota) and prints the
  actual address. If a Wiki recorded for the same data directory is already
  running, it is reused instead of starting a second one.
.PARAMETER DataDir
  Private data directory (default C:/ara). Must be outside every Git checkout and
  short: <DataDir>/projects may not exceed 60 characters.
.PARAMETER Port
  Preferred port (default 8765). When busy, the next free port is used.
.PARAMETER Python
  Optional python executable (also read from $env:ARA_PYTHON). Needs Python 3.11+
  with the modules from harness-ui/requirements.txt.
.PARAMETER Open
  Open the Wiki in the default browser.
.PARAMETER CheckOnly
  Dry run: run the checks and `run_v9.py --check-only`; start nothing. It creates
  the empty data sub-directories because that preflight needs them to exist.
.PARAMETER Stop
  Stop the Wiki that this script recorded for the data directory, then exit.
.PARAMETER Real
  Reserved for connecting Codex. Not provided yet; exits with an explanation.
#>
[CmdletBinding()]
param(
    [string]$DataDir = 'C:/ara',
    [int]$Port = 8765,
    [string]$Python = '',
    [switch]$Open,
    [switch]$CheckOnly,
    [switch]$Stop,
    [switch]$Real
)

$ErrorActionPreference = 'Stop'

if ($Real) {
    Write-Host '真实运行模式尚未提供。' -ForegroundColor Red
    Write-Host '现在只有零额度模式：不接模型、不接 Codex、不花额度。去掉 -Real 再运行即可。'
    exit 2
}

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Ui = Join-Path $Repo 'harness-ui'
$Doctor = Join-Path $Ui 'doctor.ps1'
$RunV9 = Join-Path $Ui 'run_v9.py'
$Limits = Join-Path $Ui 'zero-limits.json'
$Helper = Join-Path $Repo 'plugins\auto-research-agent\cli\research_workspace_native\atlas_local_source.py'
$DataFull = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\')
$StateDir = Join-Path $DataFull 'launcher'
$StateFile = Join-Path $StateDir 'wiki.json'
$Utf8NoBom = New-Object System.Text.UTF8Encoding($false)

function Invoke-Sync {
    param([string]$File, [string]$Arguments, [string]$WorkDir, [int]$TimeoutMs = 120000)
    $psi = New-Object System.Diagnostics.ProcessStartInfo
    $psi.FileName = $File
    $psi.Arguments = $Arguments
    $psi.WorkingDirectory = $WorkDir
    $psi.UseShellExecute = $false
    $psi.CreateNoWindow = $true
    $psi.RedirectStandardOutput = $true
    $psi.RedirectStandardError = $true
    $proc = [System.Diagnostics.Process]::Start($psi)
    $o = $proc.StandardOutput.ReadToEndAsync()
    $e = $proc.StandardError.ReadToEndAsync()
    if (-not $proc.WaitForExit($TimeoutMs)) { try { $proc.Kill() } catch { }; return [pscustomobject]@{ Code = -1; Out = ''; Err = 'timeout' } }
    $proc.WaitForExit()
    return [pscustomobject]@{ Code = $proc.ExitCode; Out = $o.Result.Trim(); Err = $e.Result.Trim() }
}

function Get-CommandLine {
    param([int]$ProcessId)
    try { return (Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ProcessId)).CommandLine } catch { return $null }
}

function Test-PortFree {
    param([int]$Number)
    $l = $null
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Number)
        $l.Start()
        return $true
    } catch { return $false } finally { if ($l) { $l.Stop() } }
}

# Returns the recorded instance only when it is really alive for THIS data directory.
function Get-RunningInstance {
    if (-not (Test-Path -LiteralPath $StateFile)) { return $null }
    try { $state = (Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8) | ConvertFrom-Json } catch { return $null }
    if (-not $state.pid -or -not $state.port) { return $null }
    if (-not (Get-Process -Id ([int]$state.pid) -ErrorAction SilentlyContinue)) { return $null }
    $cmd = Get-CommandLine ([int]$state.pid)
    if (-not $cmd -or $cmd -notlike '*run_v9.py*' -or $cmd -notlike ('*' + $DataFull + '*')) { return $null }
    try {
        $r = Invoke-WebRequest -Uri ('http://127.0.0.1:' + $state.port + '/') -UseBasicParsing -TimeoutSec 5
        if ($r.StatusCode -ne 200) { return $null }
    } catch { return $null }
    return $state
}

function Stop-Instance {
    param($State)
    # /T also ends the real interpreter behind a virtual-environment launcher.
    & taskkill.exe /PID ([int]$State.pid) /T /F | Out-Null
}

# ---- -Stop -----------------------------------------------------------------------
if ($Stop) {
    $running = Get-RunningInstance
    if (-not $running) {
        Write-Host ('没有找到这个数据目录正在运行的 Wiki：' + $DataFull)
        exit 0
    }
    Stop-Instance $running
    Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
    Write-Host ('已停止 Wiki（进程号 ' + $running.pid + '，' + $running.url + '）。') -ForegroundColor Green
    exit 0
}

# ---- Reuse a running instance --------------------------------------------------------
$existing = Get-RunningInstance
if ($existing) {
    Write-Host ('这个数据目录的 Wiki 已在运行，直接使用：' + $existing.url + '  （进程号 ' + $existing.pid + '）') -ForegroundColor Green
    if ($CheckOnly) {
        Write-Host '-CheckOnly：不重复启动，也未再做检查。'
    } elseif ($Open) {
        Start-Process $existing.url
    }
    exit 0
}

# ---- Required checks ---------------------------------------------------------------------
$results = @(& $Doctor -DataDir $DataDir -Port $Port -Python $Python -PassThru -Quiet)
$failed = @($results | Where-Object { $_.Level -eq '必需' -and -not $_.Ok })
if ($failed.Count -gt 0) {
    Write-Host '启动前检查没通过，先处理下面这些：' -ForegroundColor Red
    foreach ($item in $failed) {
        Write-Host ('  - ' + $item.Name + '：' + $item.Message) -ForegroundColor Red
        Write-Host ('    怎么修：' + $item.Fix)
    }
    Write-Host '处理完再运行一次。想看完整清单：powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\doctor.ps1'
    exit 1
}
$py = ($results | Where-Object { $_.Id -eq 'python' } | Select-Object -First 1).Extra
if (-not $py) { Write-Host '没有可用的 Python。' -ForegroundColor Red; exit 1 }

# ---- Data directories --------------------------------------------------------------------------
foreach ($name in @('projects', 'ui-state', 'incoming', 'launcher')) {
    New-Item -ItemType Directory -Force -Path (Join-Path $DataFull $name) | Out-Null
}

# ---- Helper SHA-256 and port ------------------------------------------------------------------------
if (-not (Test-Path -LiteralPath $Helper)) { Write-Host ('找不到 helper 文件：' + $Helper) -ForegroundColor Red; exit 1 }
$helperSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $Helper).Hash.ToLower()

$chosen = $null
for ($candidate = $Port; $candidate -lt ($Port + 50) -and $candidate -le 65535; $candidate++) {
    if (Test-PortFree $candidate) { $chosen = $candidate; break }
}
if (-not $chosen) { Write-Host ('从 ' + $Port + ' 起连续 50 个端口都被占用，请用 -Port 指定其他端口。') -ForegroundColor Red; exit 1 }
if ($chosen -ne $Port) { Write-Host ('端口 ' + $Port + ' 被占用，改用 ' + $chosen + '。') -ForegroundColor Yellow }

$args9 = '-X utf8 "' + $RunV9 + '" --repo "' + $Repo + '" --source-helper-sha256 ' + $helperSha +
    ' --projects-root "' + (Join-Path $DataFull 'projects') + '"' +
    ' --ui-state-root "' + (Join-Path $DataFull 'ui-state') + '"' +
    ' --incoming-root "' + (Join-Path $DataFull 'incoming') + '"' +
    ' --run-limits "' + $Limits + '" --port ' + $chosen

# ---- -CheckOnly -----------------------------------------------------------------------------------------
if ($CheckOnly) {
    $r = Invoke-Sync $py ($args9 + ' --check-only') $Repo
    if ($r.Code -eq 0) {
        Write-Host '-CheckOnly：run_v9.py --check-only 通过，什么都没启动。' -ForegroundColor Green
        Write-Host ('  Python：' + $py)
        Write-Host ('  数据目录：' + $DataFull + '（已建空子目录 projects、ui-state、incoming、launcher）')
        Write-Host ('  将使用的地址：http://127.0.0.1:' + $chosen + '/')
        Write-Host '  模式：零额度（不接模型、不接 Codex）'
        Write-Host ('  预检回执：' + $r.Out)
        exit 0
    }
    Write-Host '-CheckOnly：run_v9.py --check-only 没通过。' -ForegroundColor Red
    Write-Host $r.Err
    Write-Host $r.Out
    exit 1
}

# ---- Start --------------------------------------------------------------------------------------------------
$stamp = Get-Date -Format 'yyyyMMdd-HHmmss'
$outLog = Join-Path $StateDir ('wiki-' + $stamp + '.out.log')
$errLog = Join-Path $StateDir ('wiki-' + $stamp + '.err.log')
Write-Host '正在启动 Wiki（零额度模式）……'
# Start through cmd.exe + ShellExecute so the Wiki inherits none of this script's
# handles (a caller that captures our output through a pipe would otherwise wait
# for the Wiki to exit). cmd redirects the two logs itself.
$psi = New-Object System.Diagnostics.ProcessStartInfo
$psi.FileName = $env:ComSpec
$psi.Arguments = '/c ""' + $py + '" ' + $args9 + ' >"' + $outLog + '" 2>"' + $errLog + '""'
$psi.WorkingDirectory = $Repo
$psi.UseShellExecute = $true
$psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
$proc = [System.Diagnostics.Process]::Start($psi)

$url = $null
$deadline = (Get-Date).AddSeconds(90)
while ((Get-Date) -lt $deadline) {
    Start-Sleep -Milliseconds 500
    if (Test-Path -LiteralPath $outLog) {
        $line = Get-Content -LiteralPath $outLog -Encoding UTF8 | Where-Object { $_ -like '*local-V7-Wiki-ready*' } | Select-Object -First 1
        if ($line) {
            try { $url = ($line | ConvertFrom-Json).url } catch { $url = 'http://127.0.0.1:' + $chosen + '/' }
            break
        }
    }
    if ($proc.HasExited) { break }
}
if (-not $url) {
    $alive = -not $proc.HasExited
    if ($alive) { & taskkill.exe /PID $proc.Id /T /F | Out-Null }
    Write-Host '启动没有成功。日志末尾：' -ForegroundColor Red
    if (Test-Path -LiteralPath $errLog) { Get-Content -LiteralPath $errLog -Encoding UTF8 -Tail 15 }
    if (Test-Path -LiteralPath $outLog) { Get-Content -LiteralPath $outLog -Encoding UTF8 -Tail 5 }
    Write-Host ('完整日志：' + $StateDir)
    exit 1
}

$state = [ordered]@{ pid = $proc.Id; port = $chosen; url = $url; started = (Get-Date).ToString('s'); data_dir = $DataFull; python = $py; mode = 'zero-quota' }
[System.IO.File]::WriteAllText($StateFile, ($state | ConvertTo-Json), $Utf8NoBom)

Write-Host ('Wiki 已启动：' + $url) -ForegroundColor Green
Write-Host ('  进程号 ' + $proc.Id + '；数据目录 ' + $DataFull + '；日志 ' + $StateDir)
Write-Host '  模式：零额度（不接模型、不接 Codex）。'
Write-Host ('  停止：powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Stop -DataDir "' + $DataDir + '"')
if ($Open) { Start-Process $url }
exit 0
