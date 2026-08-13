<#
.SYNOPSIS
    Start (or repair) the three processes that make the site public, and keep
    them responsive.

.DESCRIPTION
    Idempotent by design: it starts only what is not already listening, so the
    same script can run at logon AND every minute as a watchdog without ever
    launching a duplicate.

        Next.js     127.0.0.1:3000   the dashboard
        FastAPI     127.0.0.1:4000   the AI backend
        cloudflared (no port)        outbound tunnel to Cloudflare

    Both servers bind loopback ONLY. cloudflared reaches them over 127.0.0.1, so
    nothing is lost, and the machine exposes no port to the LAN or the internet.

    Beyond starting things, this also does two things that matter for speed on a
    machine with 8 GB of RAM — see "Keeping it warm" below.

.NOTES
    Runs without administrator rights, which is why this exists at all: without
    admin, `cloudflared service install` cannot register a real Windows service,
    so Task Scheduler drives this script instead.

    Consequence worth knowing: a logon-triggered task does not run until someone
    logs into the machine after a reboot. Until then the site is down.

    THE SCHEDULED TASK NEEDS A TIME LIMIT, and this is not stored in the repo, so
    it is written here to survive being forgotten:

        $t = Get-ScheduledTask -TaskName "AyurvedaSite"
        $s = $t.Settings; $s.ExecutionTimeLimit = "PT2M"
        Set-ScheduledTask -TaskName "AyurvedaSite" -Settings $s

    It shipped as `PT0S`, which means NO limit. One pass hung and sat there for
    32 minutes; because the task refuses a new instance while one is running,
    every scheduled pass after it was declined (0x800710E0) and nothing was
    supervised at all. The frontend went down during that window and stayed down,
    with a watchdog that looked perfectly healthy in Task Scheduler.

    A supervisor with no timeout is a single hang away from being no supervisor.
#>

$ErrorActionPreference = "Stop"

$Repo = "C:\Users\test\Desktop\Ayurveda-"
$Bun = "C:\Users\test\.bun\bin\bun.exe"
$Python = "$Repo\backend-python\.venv\Scripts\python.exe"
$Cloudflared = "C:\Users\test\.cloudflared\bin\cloudflared.exe"
$TunnelConfig = "$Repo\cloudflare\config.yml"
$LogDir = "$Repo\logs"

New-Item -ItemType Directory -Force -Path $LogDir | Out-Null

<#
Keep the previous run's logs.

`Start-Process -RedirectStandardOutput` TRUNCATES, so every restart destroyed the
evidence from the run before it. That cost a real diagnosis: a user reported a
wrongly-triggered emergency warning, `_escalate` had already logged its reason,
and by the time the report arrived the log had been overwritten by a restart.

One generation back is enough — the question is always "what happened just before
I restarted this".
#>
foreach ($name in @("backend-out", "backend-err", "frontend-out", "frontend-err", "tunnel-out", "tunnel-err")) {
    $current = Join-Path $LogDir "$name.log"
    if ((Test-Path $current) -and (Get-Item $current).Length -gt 0) {
        Move-Item -Path $current -Destination (Join-Path $LogDir "$name.prev.log") -Force -ErrorAction SilentlyContinue
    }
}

function Write-Log([string]$Message) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $Message
    Write-Output $line
    Add-Content -Path "$LogDir\supervisor.log" -Value $line -Encoding utf8
}

function Test-Listening([int]$Port) {
    $null -ne (Get-NetTCPConnection -State Listen -LocalPort $Port -ErrorAction SilentlyContinue)
}

<#
Is the tunnel actually serving?

The old check asked only whether a `cloudflared.exe` process existed with
"tunnel" on its command line. That cannot tell a working tunnel from a hung one:
a cloudflared that is alive but has lost every edge connection looks perfectly
healthy, so the watchdog would never restart it and the site would stay dark
indefinitely.

This is the same mistake already fixed on the backend, which now judges by
whether port 4000 answers rather than by what a command line says. The tunnel
listens on no port, but `--metrics` gives it one: `/ready` returns 200 with a
`readyConnections` count while at least one edge connection is live, and 503
when none is.

THREE outcomes, not two, and the third is the one that matters:

    ready      -> leave it alone
    not-ready  -> cloudflared itself said it has no connections. Real evidence
                  of failure, so restart.
    unknown    -> the check could not reach the endpoint. That is evidence about
                  the CHECK, not about the tunnel, so do nothing.

Collapsing "unknown" into "dead" is how this script once killed a perfectly
healthy backend every single minute. A broken probe must never be able to take
down a working service.
#>
$TunnelMetrics = "127.0.0.1:20241"

function Get-TunnelProcess {
    $procs = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) { if ($p.CommandLine -match "tunnel") { return $p } }
    return $null
}

function Get-TunnelReadiness {
    <# Returns @{ State = "ready"|"not-ready"|"unknown"; Connections = <int>; Detail = "" } #>
    try {
        $response = Invoke-WebRequest -Uri "http://$TunnelMetrics/ready" `
            -TimeoutSec 5 -UseBasicParsing -ErrorAction Stop
        $count = 0
        try { $count = [int](($response.Content | ConvertFrom-Json).readyConnections) } catch { }
        if ($response.StatusCode -eq 200) {
            return @{ State = "ready"; Connections = $count; Detail = "" }
        }
        return @{ State = "not-ready"; Connections = $count; Detail = "http $($response.StatusCode)" }
    } catch {
        # A 503 is cloudflared ANSWERING "I have no connections" — that is a real
        # verdict and must be acted on. PowerShell raises it as an exception, so
        # it has to be separated here from a genuine connection failure, which
        # tells us nothing about the tunnel at all.
        $status = $null
        try { $status = [int]$_.Exception.Response.StatusCode } catch { }
        if ($status -eq 503) {
            return @{ State = "not-ready"; Connections = 0; Detail = "503 no ready connections" }
        }
        return @{
            State       = "unknown"
            Connections = 0
            Detail      = $_.Exception.Message.Split([char]10)[0]
        }
    }
}

function Start-Tunnel {
    # --metrics is what makes the readiness check above possible. Bound to
    # loopback, so it adds no public surface.
    Start-Process -FilePath $Cloudflared `
        -ArgumentList "--config", $TunnelConfig, "--no-autoupdate", `
                      "--metrics", $TunnelMetrics, "tunnel", "run" `
        -RedirectStandardOutput "$LogDir\tunnel-out.log" `
        -RedirectStandardError  "$LogDir\tunnel-err.log" `
        -WindowStyle Hidden

    # Say what actually happened rather than assuming the launch worked. The old
    # script logged "tunnel starting" and moved on, so the log claimed success
    # even when the start had failed.
    $deadline = (Get-Date).AddSeconds(25)
    while ((Get-Date) -lt $deadline) {
        Start-Sleep -Seconds 2
        $check = Get-TunnelReadiness
        if ($check.State -eq "ready") {
            Write-Log "tunnel   ready ($($check.Connections) connections)"
            return $true
        }
    }
    $final = Get-TunnelReadiness
    Write-Log "tunnel   started but not ready after 25s (state=$($final.State) $($final.Detail))"
    return $false
}

<#
Keeping it warm.

Windows trims the working set of an idle process, and this box has 8 GB shared
between Next.js, Python and a 1.9 GB embedding model. Measured on the live site:
the Python worker had peaked at 1940 MB and was holding 40 MB — the rest had been
pushed to the page file. The next visitor paid to fault it all back, which showed
up as a 2.5 second first response against 134 ms once warm.

SetProcessWorkingSetSize with QUOTA_LIMITS_HARDWS_MIN_ENABLE asks Windows to stop
evicting a minimum. A process may set this on itself without administrator
rights. It is a request, not a guarantee — a hypervisor balloon driver can still
reclaim the pages — so the effect is measured after deploying rather than assumed.
#>
$pinSource = @"
using System;
using System.Runtime.InteropServices;
public static class WorkingSet {
    [DllImport("kernel32.dll", SetLastError = true)]
    static extern bool SetProcessWorkingSetSizeEx(IntPtr h, IntPtr min, IntPtr max, uint flags);
    // QUOTA_LIMITS_HARDWS_MIN_ENABLE (0x1) | QUOTA_LIMITS_HARDWS_MAX_DISABLE (0x8)
    public static bool Pin(IntPtr handle, long minBytes, long maxBytes) {
        return SetProcessWorkingSetSizeEx(handle, (IntPtr)minBytes, (IntPtr)maxBytes, 0x9);
    }
}
"@
if (-not ("WorkingSet" -as [type])) {
    try { Add-Type -TypeDefinition $pinSource -ErrorAction Stop } catch { }
}

function Set-MinimumWorkingSet([int]$ProcessId, [int]$MinMB, [int]$MaxMB) {
    if (-not ("WorkingSet" -as [type])) { return "unavailable" }
    try {
        $p = Get-Process -Id $ProcessId -ErrorAction Stop
        $ok = [WorkingSet]::Pin($p.Handle, ($MinMB * 1MB), ($MaxMB * 1MB))
        if ($ok) { return "pinned ${MinMB}-${MaxMB} MB" }
        return "refused (win32 error $([Runtime.InteropServices.Marshal]::GetLastWin32Error()))"
    } catch {
        return "failed: $($_.Exception.Message.Split([char]10)[0])"
    }
}

# ---- Python AI backend ------------------------------------------------------
# Started first: it loads the bge-m3 embedding model (~1.9 GB) and takes the
# longest to become useful, so giving it a head start shortens total downtime.
#
# Leftover server.py processes are cleared ONLY when nothing is serving port
# 4000. Never while the site is up.
#
# The first version of this check compared each process's command line against
# the venv interpreter and killed anything else. That killed the live backend
# every minute. On Windows `.venv\Scripts\python.exe` is a small launcher: it
# starts the base interpreter as a CHILD, and it is the child that loads the
# model, binds the port and reports the base interpreter's path on its command
# line. The real server therefore looks exactly like a "stray" from the outside.
#
# Judging by the port instead of by the path removes the guesswork: if something
# is answering on 4000 it is the server, whatever its argv says.
#
# STARTING IS NOT THE SAME AS STUCK.
#
# The backend takes 40-60 seconds to become useful: it loads a 1.9 GB embedding
# model before uvicorn accepts anything, and on a 2 GB-free machine that is slow.
# For all that time it is running and not yet serving 4000 — indistinguishable,
# to the check above, from a hung leftover.
#
# That was survivable while this ran once a minute. It stopped being survivable
# the moment the tunnel work added an offset trigger and halved the interval to
# 30 seconds: every pass killed a backend that was ~30 seconds into a ~50 second
# start, and started another one that met the same end. Measured in a loop —
#
#     623 MB -> 13 MB    (killed, restarted)
#     756 MB -> 33 MB    (killed, restarted)
#     420 MB -> ...      (and again)
#
# — the process climbing toward its 1.9 GB and being shot each time just before
# it could bind. The site's AI was down not because anything crashed, but
# because its own supervisor would not let it finish standing up.
#
# So a process gets a grace period. Only something older than that, and still
# not serving, is genuinely stuck.
$BackendStartupGraceSeconds = 150

if (Test-Listening 4000) {
    Write-Log "backend  already listening on 4000"
} else {
    $now = Get-Date
    $candidates = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "server\.py" }

    $starting = @($candidates | Where-Object {
        $_.CreationDate -and ($now - $_.CreationDate).TotalSeconds -lt $BackendStartupGraceSeconds
    })

    if ($starting.Count -gt 0) {
        # NOT `return` — at script scope that exits the whole file and would skip
        # the frontend and tunnel checks below, turning one slow backend into
        # three unsupervised services.
        $age = [Math]::Round(($now - ($starting | Sort-Object CreationDate | Select-Object -First 1).CreationDate).TotalSeconds)
        Write-Log "backend  still starting (${age}s old, grace ${BackendStartupGraceSeconds}s) - leaving it alone"
    }
    else {
        $leftovers = @($candidates)
        foreach ($leftover in $leftovers) {
            $age = [Math]::Round(($now - $leftover.CreationDate).TotalSeconds)
            Write-Log "backend  clearing leftover pid=$($leftover.ProcessId) (${age}s old, nothing serving 4000)"
            Stop-Process -Id $leftover.ProcessId -Force -ErrorAction SilentlyContinue
        }
        if ($leftovers.Count -gt 0) { Start-Sleep -Seconds 3 }

        Write-Log "backend  starting"
        Start-Process -FilePath $Python -ArgumentList "server.py" `
            -WorkingDirectory "$Repo\backend-python" `
            -RedirectStandardOutput "$LogDir\backend-out.log" `
            -RedirectStandardError  "$LogDir\backend-err.log" `
            -WindowStyle Hidden
    }
}

# ---- Next.js dashboard ------------------------------------------------------
# `bun run start` serves the PRODUCTION build. Do not switch this to `dev`:
# the dev server mishandles X-Forwarded-Proto behind the tunnel and 500s.
# After changing any NEXT_PUBLIC_* value, run `bun run build` before restarting —
# those values are compiled into the bundle, not read at runtime.
if (Test-Listening 3000) {
    Write-Log "frontend already listening on 3000"
} else {
    Write-Log "frontend starting"
    Start-Process -FilePath $Bun -ArgumentList "run", "start" `
        -WorkingDirectory "$Repo\apps\app" `
        -RedirectStandardOutput "$LogDir\frontend-out.log" `
        -RedirectStandardError  "$LogDir\frontend-err.log" `
        -WindowStyle Hidden
}

# ---- Cloudflare Tunnel ------------------------------------------------------
# Detected by process, not by port: the tunnel listens on nothing. It makes an
# OUTBOUND connection to Cloudflare, which is the whole reason no inbound port
# needs to be open.
$tunnelProcess = Get-TunnelProcess
if (-not $tunnelProcess) {
    Write-Log "tunnel   starting (no cloudflared process)"
    Start-Tunnel | Out-Null
} else {
    $readiness = Get-TunnelReadiness
    switch ($readiness.State) {
        "ready" {
            Write-Log "tunnel   already running and ready ($($readiness.Connections) connections)"
        }
        "not-ready" {
            # cloudflared is alive and says it is serving nothing. Before this
            # check existed, this state was invisible and lasted forever.
            Write-Log "tunnel   alive but NOT serving ($($readiness.Detail)) - restarting pid=$($tunnelProcess.ProcessId)"
            Stop-Process -Id $tunnelProcess.ProcessId -Force -ErrorAction SilentlyContinue
            Start-Sleep -Seconds 3
            Start-Tunnel | Out-Null
        }
        default {
            # Deliberately does nothing. Also the state every tunnel started
            # before this change reports, since those have no metrics listener —
            # so the first restart after deploying is what switches the real
            # check on, and until then the old behaviour stands. Restarting on
            # this would be killing a healthy tunnel on no evidence.
            Write-Log "tunnel   running, readiness unknown ($($readiness.Detail)) - leaving it alone"
        }
    }
}

# ---- Keep the pages resident ------------------------------------------------
# Ceilings are generous rather than tuned: the point is to stop eviction, not to
# cap growth, and MAX_DISABLE above means the maximum is advisory anyway.
foreach ($target in @(
    @{ Port = 4000; Name = "backend "; Min = 1600; Max = 2600 },
    @{ Port = 3000; Name = "frontend"; Min = 220;  Max = 700  }
)) {
    $conn = Get-NetTCPConnection -State Listen -LocalPort $target.Port -ErrorAction SilentlyContinue | Select-Object -First 1
    if ($conn) {
        $result = Set-MinimumWorkingSet -ProcessId $conn.OwningProcess -MinMB $target.Min -MaxMB $target.Max
        # Log what is actually resident, not just that the call returned true.
        # On this VM the call succeeds and the pages are reclaimed anyway — the
        # Python worker drops from ~1.9 GB back to tens of MB between requests —
        # so a log line saying "pinned" on its own would be quietly untrue.
        $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
        $resident = if ($proc) { [Math]::Round($proc.WorkingSet64 / 1MB) } else { "?" }
        $peak = if ($proc) { [Math]::Round($proc.PeakWorkingSet64 / 1MB) } else { "?" }
        Write-Log "$($target.Name) working set: $result | resident now ${resident} MB, peak ${peak} MB"
    }
}

# A request costs almost nothing and keeps the hot code paths faulted in, which
# also covers the case where the memory pin above was refused.
foreach ($probe in @("http://127.0.0.1:4000/health", "http://127.0.0.1:3000/en/login")) {
    try {
        Invoke-WebRequest -Uri $probe -TimeoutSec 20 -UseBasicParsing | Out-Null
    } catch {
        Write-Log "warm     $probe -> $($_.Exception.Message.Split([char]10)[0])"
    }
}

Write-Log "check complete"
