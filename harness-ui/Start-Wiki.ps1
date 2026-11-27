<#
.SYNOPSIS
  One-command local start of the Research Wiki in zero-quota mode (Windows PowerShell 5.1+).
.DESCRIPTION
  Locates the repository from this script's own location, runs the required
  doctor.ps1 checks, creates the data sub-directories, computes the helper
  SHA-256, picks a free port, starts harness-ui/run_v9.py with
  harness-ui/zero-limits.json (no model, no Codex, no quota) and prints the
  actual address.

  Safety rules:
  - Only one Wiki per data directory. Start and stop are serialized by an exclusive
    lock file in <DataDir>/launcher, so two windows started together end up sharing
    one instance.
  - The script only reuses or stops a process that it can prove is the Wiki it
    started for this data directory: the recorded process id must still carry the
    recorded start time and a command line with this repository's run_v9.py and this
    data directory, and the recorded port must be listened on by that process tree.
    A busy port alone never counts. Anything else is left untouched.
  - The address that is opened is always built from the verified local port.
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
  Dry run: run the checks and `run_v9.py --check-only` (always, even when a Wiki is
  already running); start nothing. It creates the empty data sub-directories because
  that preflight needs them to exist.
.PARAMETER Stop
  Stop the Wiki that this script started for the data directory, then exit.
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
if ($Port -lt 1024 -or $Port -gt 65535) {
    Write-Host ('-Port 要在 1024 到 65535 之间，收到 ' + $Port + '。') -ForegroundColor Red
    exit 1
}

$Repo = (Resolve-Path (Join-Path $PSScriptRoot '..')).Path
$Ui = Join-Path $Repo 'harness-ui'
$Doctor = Join-Path $Ui 'doctor.ps1'
$RunV9 = Join-Path $Ui 'run_v9.py'
$Limits = Join-Path $Ui 'zero-limits.json'
$Helper = Join-Path $Repo 'plugins\auto-research-agent\cli\research_workspace_native\atlas_local_source.py'
$DataFull = [System.IO.Path]::GetFullPath($DataDir).TrimEnd('\')
$ProjectsRoot = Join-Path $DataFull 'projects'
$StateDir = Join-Path $DataFull 'launcher'
$StateFile = Join-Path $StateDir 'wiki.json'
$LockFile = Join-Path $StateDir 'start.lock'
$StopNote = Join-Path $StateDir 'stop-failed.txt'
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

# ---- process and port facts ----------------------------------------------------------
function Get-ProcInfo {
    param([int]$ProcessId)
    try {
        $p = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ProcessId)
        if (-not $p) { return $null }
        return [pscustomobject]@{ Pid = [int]$p.ProcessId; Parent = [int]$p.ParentProcessId; CommandLine = $p.CommandLine; Created = $p.CreationDate }
    } catch { return $null }
}

# The process plus everything it started (cmd.exe -> venv launcher -> real python).
function Get-TreePids {
    param([int]$RootPid)
    $all = @{}
    try { foreach ($p in (Get-CimInstance Win32_Process)) { $all[[int]$p.ProcessId] = [int]$p.ParentProcessId } } catch { }
    $tree = New-Object System.Collections.ArrayList
    [void]$tree.Add($RootPid)
    $i = 0
    while ($i -lt $tree.Count) {
        foreach ($k in $all.Keys) { if ($all[$k] -eq $tree[$i] -and -not $tree.Contains($k)) { [void]$tree.Add($k) } }
        $i++
    }
    return @($tree)
}

# Process ids that are listening on a TCP port (any local address).
function Get-ListenerPids {
    param([int]$Number)
    $found = @()
    try {
        $found = @(Get-NetTCPConnection -State Listen -LocalPort $Number -ErrorAction Stop | ForEach-Object { [int]$_.OwningProcess })
    } catch {
        foreach ($line in @(& netstat.exe -ano -p TCP)) {
            if ($line -match ('^\s*TCP\s+\S+:' + $Number + '\s+\S+\s+LISTENING\s+(\d+)\s*$')) { $found += [int]$Matches[1] }
        }
    }
    return @($found | Select-Object -Unique)
}

function Test-PortFree {
    param([int]$Number)
    if ((Get-ListenerPids $Number).Count -gt 0) { return $false }
    $l = $null
    try {
        $l = New-Object System.Net.Sockets.TcpListener([System.Net.IPAddress]::Loopback, $Number)
        $l.Start()
        return $true
    } catch { return $false } finally { if ($l) { $l.Stop() } }
}

function Test-Contains {
    param([string]$Text, [string]$Part)
    return ($Text -and $Text.IndexOf($Part, [System.StringComparison]::OrdinalIgnoreCase) -ge 0)
}

function Test-WikiResponds {
    param([int]$Number)
    try {
        $r = Invoke-WebRequest -Uri ('http://127.0.0.1:' + $Number + '/') -UseBasicParsing -TimeoutSec 5
        return ($r.StatusCode -eq 200)
    } catch { return $false }
}

# ---- recorded instance -----------------------------------------------------------------
# Status:
#   none        no record
#   stale       record exists but its process is gone or the id now belongs to another program
#   running     process proven to be ours, listening on the recorded port and answering HTTP 200
#   unresponsive process proven to be ours but not listening or not answering (do not start a second one)
#   unknown     cannot decide (unreadable record, or process details not readable): hands off
function Get-InstanceState {
    if (-not (Test-Path -LiteralPath $StateFile)) { return [pscustomobject]@{ Status = 'none'; State = $null; Reason = '' } }
    try {
        $state = (Get-Content -LiteralPath $StateFile -Raw -Encoding UTF8) | ConvertFrom-Json
        $recPid = [int]$state.pid
        $recPort = [int]$state.port
        $recStart = [datetime]::FromFileTimeUtc([long]$state.process_started_filetime)
    } catch {
        return [pscustomobject]@{ Status = 'unknown'; State = $null; Reason = '记录文件读不懂：' + $StateFile }
    }
    if ($recPort -lt 1024 -or $recPort -gt 65535 -or $recPid -le 4) {
        return [pscustomobject]@{ Status = 'unknown'; State = $state; Reason = '记录里的进程号或端口不合理' }
    }
    $info = Get-ProcInfo $recPid
    if (-not $info) {
        # The recorded launcher is gone. If something that looks like our Wiki still
        # listens, it was orphaned: do not touch it and do not start a second one.
        foreach ($lp in (Get-ListenerPids $recPort)) {
            $li = Get-ProcInfo $lp
            if ($li -and (Test-Contains $li.CommandLine $RunV9) -and (Test-Contains $li.CommandLine $ProjectsRoot)) {
                return [pscustomobject]@{ Status = 'unknown'; State = $state; Reason = ('记录的启动进程已退出，但端口 ' + $recPort + ' 上还有一个像本 Wiki 的进程（进程号 ' + $lp + '）') }
            }
        }
        return [pscustomobject]@{ Status = 'stale'; State = $state; Reason = '记录的进程已不存在' }
    }
    if (-not $info.CommandLine -or -not $info.Created) {
        return [pscustomobject]@{ Status = 'unknown'; State = $state; Reason = ('读不到进程 ' + $recPid + ' 的启动信息（权限不够？）') }
    }
    $sameStart = ([math]::Abs(($info.Created.ToUniversalTime() - $recStart.ToUniversalTime()).TotalSeconds) -le 2)
    $sameCmd = (Test-Contains $info.CommandLine $RunV9) -and (Test-Contains $info.CommandLine ('--projects-root "' + $ProjectsRoot + '"'))
    if (-not $sameStart -or -not $sameCmd) {
        return [pscustomobject]@{ Status = 'stale'; State = $state; Reason = ('进程号 ' + $recPid + ' 现在属于别的程序（启动时间或命令行对不上），记录已过期') }
    }
    $tree = Get-TreePids $recPid
    $owned = @(Get-ListenerPids $recPort | Where-Object { $tree -contains $_ })
    if ($owned.Count -eq 0) {
        return [pscustomobject]@{ Status = 'unresponsive'; State = $state; Reason = ('进程 ' + $recPid + ' 还活着，但没有在端口 ' + $recPort + ' 上监听') }
    }
    if (-not (Test-WikiResponds $recPort)) {
        return [pscustomobject]@{ Status = 'unresponsive'; State = $state; Reason = ('进程 ' + $recPid + ' 在监听端口 ' + $recPort + '，但首页 5 秒内没有返回 200') }
    }
    return [pscustomobject]@{ Status = 'running'; State = $state; Reason = '' }
}

function Write-State {
    param($Object)
    $tmp = $StateFile + '.tmp'
    [System.IO.File]::WriteAllText($tmp, ($Object | ConvertTo-Json), $Utf8NoBom)
    Move-Item -LiteralPath $tmp -Destination $StateFile -Force
}

# Ends a process tree that is proven to be ours and waits until it is really gone.
# Returns an object: Ok, Code, Message.
function Stop-Tree {
    param([int]$RootPid, [int]$Port)
    $out = & taskkill.exe /PID $RootPid /T /F 2>&1
    $code = $LASTEXITCODE
    $deadline = (Get-Date).AddSeconds(15)
    $gone = $false
    while ((Get-Date) -lt $deadline) {
        $alive = [bool](Get-Process -Id $RootPid -ErrorAction SilentlyContinue)
        $listening = $false
        if ($Port -gt 0) { $listening = ((Get-ListenerPids $Port | Where-Object { (Get-TreePids $RootPid) -contains $_ }).Count -gt 0) }
        if (-not $alive -and -not $listening) { $gone = $true; break }
        Start-Sleep -Milliseconds 300
    }
    return [pscustomobject]@{ Ok = $gone; Code = $code; Message = (($out | ForEach-Object { [string]$_ }) -join ' ').Trim() }
}

function Report-StopFailure {
    param($State, $Result)
    $time = (Get-Date).ToString('s')
    $text = @(
        ('停止失败（' + $time + '）'),
        ('Wiki 进程号 ' + $State.pid + '，端口 ' + $State.port + '，数据目录 ' + $DataFull),
        ('taskkill 退出码 ' + $Result.Code + '；输出：' + $Result.Message),
        '这份记录（wiki.json）保留着，不会被删除，所以现在不能再启动第二个。',
        '下一步：',
        '  1. 关掉所有运行 Wiki 的窗口，或用“以管理员身份运行”的 PowerShell 再执行一次 -Stop。',
        ('  2. 还不行就在任务管理器里结束进程号 ' + $State.pid + ' 和它的子进程，然后再执行一次 -Stop（记录会自行判为过期并清掉）。')
    ) -join "`r`n"
    [System.IO.File]::WriteAllText($StopNote, $text, $Utf8NoBom)
    Write-Host '停止没有成功：' -ForegroundColor Red
    Write-Host $text
    Write-Host ('（以上内容也写在 ' + $StopNote + '）')
}

# ---- lock -------------------------------------------------------------------------------------
function Enter-Lock {
    New-Item -ItemType Directory -Force -Path $StateDir | Out-Null
    $deadline = (Get-Date).AddSeconds(150)
    $told = $false
    while ($true) {
        $h = $null
        try { $h = [System.IO.File]::Open($LockFile, [System.IO.FileMode]::OpenOrCreate, [System.IO.FileAccess]::ReadWrite, [System.IO.FileShare]::None) } catch { $h = $null }
        if ($h) { return $h }
        if (-not $told) { Write-Host '另一个窗口正在启动或停止这个数据目录的 Wiki，等它做完……' -ForegroundColor Yellow; $told = $true }
        if ((Get-Date) -gt $deadline) { return $null }
        Start-Sleep -Milliseconds 500
    }
}

function Start-WikiMain {
    # ---- -Stop -----------------------------------------------------------------------
    if ($Stop) {
        $inst = Get-InstanceState
        switch ($inst.Status) {
            'none' { Write-Host ('这个数据目录没有记录在运行的 Wiki：' + $DataFull); return 0 }
            'stale' {
                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
                Remove-Item -LiteralPath $StopNote -Force -ErrorAction SilentlyContinue
                Write-Host ($inst.Reason + '。没有结束任何进程，只清掉了过期记录。') -ForegroundColor Yellow
                return 0
            }
            'unknown' {
                Write-Host ('无法确认归属，没有动任何进程：' + $inst.Reason) -ForegroundColor Red
                Write-Host ('确认没有 Wiki 在运行后，手工删除记录文件即可：' + $StateFile)
                return 1
            }
        }
        $res = Stop-Tree ([int]$inst.State.pid) ([int]$inst.State.port)
        if (-not $res.Ok) { Report-StopFailure $inst.State $res; return 1 }
        Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
        Remove-Item -LiteralPath $StopNote -Force -ErrorAction SilentlyContinue
        Write-Host ('已停止 Wiki（进程号 ' + $inst.State.pid + '，端口 ' + $inst.State.port + '）。') -ForegroundColor Green
        return 0
    }

    # ---- Required checks (also for -CheckOnly) -------------------------------------------
    $results = @(& $Doctor -DataDir $DataDir -Port $Port -Python $Python -PassThru -Quiet)
    $failed = @($results | Where-Object { $_.Level -eq '必需' -and -not $_.Ok })
    if ($failed.Count -gt 0) {
        Write-Host '启动前检查没通过，先处理下面这些：' -ForegroundColor Red
        foreach ($item in $failed) {
            Write-Host ('  - ' + $item.Name + '：' + $item.Message) -ForegroundColor Red
            Write-Host ('    怎么修：' + $item.Fix)
        }
        Write-Host '处理完再运行一次。想看完整清单：powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\doctor.ps1'
        return 1
    }
    $py = ($results | Where-Object { $_.Id -eq 'python' } | Select-Object -First 1).Extra
    if (-not $py) { Write-Host '没有可用的 Python。' -ForegroundColor Red; return 1 }
    if (-not (Test-Path -LiteralPath $Helper)) { Write-Host ('找不到 helper 文件：' + $Helper) -ForegroundColor Red; return 1 }
    $helperSha = (Get-FileHash -Algorithm SHA256 -LiteralPath $Helper).Hash.ToLower()

    foreach ($name in @('projects', 'ui-state', 'incoming', 'launcher')) {
        New-Item -ItemType Directory -Force -Path (Join-Path $DataFull $name) | Out-Null
    }

    # ---- -CheckOnly: no lock, no start; runs the preflight even when a Wiki is running ----
    if ($CheckOnly) {
        $chosenCheck = $null
        for ($c = $Port; $c -lt ($Port + 50) -and $c -le 65535; $c++) { if (Test-PortFree $c) { $chosenCheck = $c; break } }
        if (-not $chosenCheck) { Write-Host ('从 ' + $Port + ' 起连续 50 个端口都被占用，请用 -Port 指定其他端口。') -ForegroundColor Red; return 1 }
        $r = Invoke-Sync $py ((Get-RunArgs $helperSha $chosenCheck) + ' --check-only') $Repo
        if ($r.Code -ne 0) {
            Write-Host '-CheckOnly：run_v9.py --check-only 没通过。' -ForegroundColor Red
            Write-Host $r.Err
            Write-Host $r.Out
            return 1
        }
        Write-Host '-CheckOnly：检查通过，什么都没启动。' -ForegroundColor Green
        Write-Host ('  Python：' + $py)
        Write-Host ('  数据目录：' + $DataFull + '（已建空子目录 projects、ui-state、incoming、launcher）')
        $inst = Get-InstanceState
        switch ($inst.Status) {
            'running' { Write-Host ('  这个数据目录已有 Wiki 在运行：http://127.0.0.1:' + [int]$inst.State.port + '/  （进程号 ' + [int]$inst.State.pid + '），正式启动会直接复用它。') }
            'none' { Write-Host ('  将使用的地址：http://127.0.0.1:' + $chosenCheck + '/') }
            default { Write-Host ('  注意：已有记录但状态是 ' + $inst.Status + '：' + $inst.Reason) -ForegroundColor Yellow }
        }
        Write-Host '  模式：零额度（不接模型、不接 Codex）'
        Write-Host ('  预检回执：' + $r.Out)
        return 0
    }

    # ---- Start under the data-directory lock -------------------------------------------------
    $lock = Enter-Lock
    if (-not $lock) {
        Write-Host '等了 150 秒，另一个窗口还没做完启动或停止。先看看它，不要重复运行。' -ForegroundColor Red
        return 1
    }
    try {
        $inst = Get-InstanceState
        switch ($inst.Status) {
            'running' {
                $url = 'http://127.0.0.1:' + [int]$inst.State.port + '/'
                Write-Host ('这个数据目录的 Wiki 已在运行，直接使用：' + $url + '  （进程号 ' + [int]$inst.State.pid + '）') -ForegroundColor Green
                if ($Open) { Start-Process $url }
                return 0
            }
            'stale' {
                Write-Host ($inst.Reason + '，清掉过期记录后重新启动（没有动那个进程）。') -ForegroundColor Yellow
                Remove-Item -LiteralPath $StateFile -Force -ErrorAction SilentlyContinue
            }
            'unresponsive' {
                Write-Host ('这个数据目录已记录的 Wiki 进程还活着但现在没响应，所以不再起第二个：' + $inst.Reason) -ForegroundColor Red
                Write-Host ('等一会儿再运行一次；一直不行就先停掉它：powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Stop -DataDir "' + $DataDir + '"')
                return 1
            }
            'unknown' {
                Write-Host ('无法确认已有记录的归属，没有启动也没有动任何进程：' + $inst.Reason) -ForegroundColor Red
                Write-Host ('确认没有 Wiki 在运行后，手工删除记录文件再重试：' + $StateFile)
                return 1
            }
        }

        $chosen = $null
        for ($candidate = $Port; $candidate -lt ($Port + 50) -and $candidate -le 65535; $candidate++) {
            if (Test-PortFree $candidate) { $chosen = $candidate; break }
        }
        if (-not $chosen) { Write-Host ('从 ' + $Port + ' 起连续 50 个端口都被占用，请用 -Port 指定其他端口。') -ForegroundColor Red; return 1 }
        if ($chosen -ne $Port) { Write-Host ('端口 ' + $Port + ' 被占用，改用 ' + $chosen + '（没有动占用它的程序）。') -ForegroundColor Yellow }

        $stamp = (Get-Date -Format 'yyyyMMdd-HHmmss') + '-' + [guid]::NewGuid().ToString('N').Substring(0, 6)
        $outLog = Join-Path $StateDir ('wiki-' + $stamp + '.out.log')
        $errLog = Join-Path $StateDir ('wiki-' + $stamp + '.err.log')
        Write-Host '正在启动 Wiki（零额度模式）……'
        # Start through cmd.exe + ShellExecute so the Wiki inherits none of this script's
        # handles (neither the output pipe of a caller nor the lock file). cmd redirects
        # the two logs itself.
        $psi = New-Object System.Diagnostics.ProcessStartInfo
        $psi.FileName = $env:ComSpec
        $psi.Arguments = '/c ""' + $py + '" ' + (Get-RunArgs $helperSha $chosen) + ' >"' + $outLog + '" 2>"' + $errLog + '""'
        $psi.WorkingDirectory = $Repo
        $psi.UseShellExecute = $true
        $psi.WindowStyle = [System.Diagnostics.ProcessWindowStyle]::Hidden
        $proc = [System.Diagnostics.Process]::Start($psi)
        $procInfo = Get-ProcInfo $proc.Id

        $ready = $false
        $deadline = (Get-Date).AddSeconds(90)
        while ((Get-Date) -lt $deadline) {
            Start-Sleep -Milliseconds 500
            if ((Test-Path -LiteralPath $outLog) -and (Select-String -LiteralPath $outLog -Pattern 'local-V7-Wiki-ready' -SimpleMatch -Quiet)) { $ready = $true; break }
            if ($proc.HasExited) { break }
        }
        # Verify what is really listening: it must be our own process tree, on our port.
        $verified = $false
        if ($ready) {
            $tree = Get-TreePids $proc.Id
            $verified = ((@(Get-ListenerPids $chosen | Where-Object { $tree -contains $_ }).Count -gt 0) -and (Test-WikiResponds $chosen))
        }
        if (-not $verified) {
            $res = $null
            if (-not $proc.HasExited -or (Get-TreePids $proc.Id).Count -gt 1) { $res = Stop-Tree $proc.Id 0 }
            Write-Host '启动没有成功。日志末尾：' -ForegroundColor Red
            if (Test-Path -LiteralPath $errLog) { Get-Content -LiteralPath $errLog -Encoding UTF8 -Tail 15 }
            if (Test-Path -LiteralPath $outLog) { Get-Content -LiteralPath $outLog -Encoding UTF8 -Tail 5 }
            Write-Host ('完整日志：' + $StateDir)
            if ($res -and -not $res.Ok) {
                Write-Host ('刚启动的进程（进程号 ' + $proc.Id + '）没能结束，请在任务管理器里手工结束它和它的子进程。') -ForegroundColor Red
            }
            return 1
        }

        $startedAt = $procInfo.Created.ToFileTimeUtc()
        $state = [ordered]@{ pid = $proc.Id; process_started_filetime = $startedAt; port = $chosen; url = ('http://127.0.0.1:' + $chosen + '/'); started = (Get-Date).ToString('s'); data_dir = $DataFull; python = $py; mode = 'zero-quota' }
        Write-State $state
        Remove-Item -LiteralPath $StopNote -Force -ErrorAction SilentlyContinue

        $url = 'http://127.0.0.1:' + $chosen + '/'
        Write-Host ('Wiki 已启动：' + $url) -ForegroundColor Green
        Write-Host ('  进程号 ' + $proc.Id + '；数据目录 ' + $DataFull + '；日志 ' + $StateDir)
        Write-Host '  模式：零额度（不接模型、不接 Codex，也不做任何检索）。'
        Write-Host ('  停止：powershell -NoProfile -ExecutionPolicy Bypass -File harness-ui\Start-Wiki.ps1 -Stop -DataDir "' + $DataDir + '"')
        if ($Open) { Start-Process $url }
        return 0
    } finally {
        $lock.Dispose()
    }
}

function Get-RunArgs {
    param([string]$HelperSha, [int]$PortNumber)
    return '-X utf8 "' + $RunV9 + '" --repo "' + $Repo + '" --source-helper-sha256 ' + $HelperSha +
        ' --projects-root "' + $ProjectsRoot + '"' +
        ' --ui-state-root "' + (Join-Path $DataFull 'ui-state') + '"' +
        ' --incoming-root "' + (Join-Path $DataFull 'incoming') + '"' +
        ' --run-limits "' + $Limits + '" --port ' + $PortNumber
}

# Stop needs the lock too, so it cannot interleave with a start.
if ($Stop -and (Test-Path -LiteralPath $StateDir)) {
    $lock = Enter-Lock
    if (-not $lock) { Write-Host '等了 150 秒，另一个窗口还没做完启动或停止。' -ForegroundColor Red; exit 1 }
    try { $code = @(Start-WikiMain)[-1] } finally { $lock.Dispose() }
    exit $code
}
$code = @(Start-WikiMain)[-1]
exit $code
