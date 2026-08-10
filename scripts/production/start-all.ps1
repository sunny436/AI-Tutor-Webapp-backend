<#
.SYNOPSIS
    Start (or repair) the three processes that make the site public.

.DESCRIPTION
    Idempotent by design: it starts only what is not already listening, so the
    same script can run at logon AND every few minutes as a watchdog without
    ever launching a duplicate.

        Next.js     127.0.0.1:3000   the dashboard
        FastAPI     127.0.0.1:4000   the AI backend
        cloudflared (no port)        outbound tunnel to Cloudflare

    Both servers bind loopback ONLY. cloudflared reaches them over 127.0.0.1, so
    nothing is lost, and the machine exposes no port to the LAN or the internet.

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

# ---- Python AI backend ------------------------------------------------------
# Started first: it loads the bge-m3 embedding model (~1.3 GB) and takes the
# longest to become useful, so giving it a head start shortens total downtime.
if (Test-Listening 4000) {
    Write-Log "backend  already listening on 4000"
} else {
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

Write-Log "check complete"
