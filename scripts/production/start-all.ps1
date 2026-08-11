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

function Test-TunnelRunning {
    $procs = Get-CimInstance Win32_Process -Filter "Name='cloudflared.exe'" -ErrorAction SilentlyContinue
    foreach ($p in $procs) { if ($p.CommandLine -match "tunnel") { return $true } }
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
if (Test-Listening 4000) {
    Write-Log "backend  already listening on 4000"
} else {
    $leftovers = Get-CimInstance Win32_Process -Filter "Name='python.exe'" -ErrorAction SilentlyContinue |
        Where-Object { $_.CommandLine -match "server\.py" }
    foreach ($leftover in $leftovers) {
        Write-Log "backend  clearing leftover pid=$($leftover.ProcessId) (nothing was serving 4000)"
        Stop-Process -Id $leftover.ProcessId -Force -ErrorAction SilentlyContinue
    }
    if ($leftovers) { Start-Sleep -Seconds 3 }

    Write-Log "backend  starting"
    Start-Process -FilePath $Python -ArgumentList "server.py" `
        -WorkingDirectory "$Repo\backend-python" `
        -RedirectStandardOutput "$LogDir\backend-out.log" `
        -RedirectStandardError  "$LogDir\backend-err.log" `
        -WindowStyle Hidden
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
if (Test-TunnelRunning) {
    Write-Log "tunnel   already running"
} else {
    Write-Log "tunnel   starting"
    Start-Process -FilePath $Cloudflared `
        -ArgumentList "--config", $TunnelConfig, "--no-autoupdate", "tunnel", "run" `
        -RedirectStandardOutput "$LogDir\tunnel-out.log" `
        -RedirectStandardError  "$LogDir\tunnel-err.log" `
        -WindowStyle Hidden
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
