<#
.SYNOPSIS
    Nightly snapshot of the self-hosted Convex deployment.

.DESCRIPTION
    Convex Cloud took snapshots automatically. Nothing does now, so this is the
    only thing standing between a bad mutation and permanent data loss.

    A `docker volume` copy is NOT a substitute: it captures the database
    mid-write and may not restore cleanly. `convex export` produces a consistent
    snapshot that `convex import` accepts, and it includes file storage
    (uploaded reports and avatars), not just the tables.

    node.exe and the CLI entry point are called by ABSOLUTE PATH on purpose.
    A scheduled task runs with a minimal environment: `npx` is not on PATH, and
    `npx.ps1` is additionally blocked by this machine's execution policy.

.NOTES
    Register (already done once, kept here so it can be recreated):

        schtasks /Create /TN "Convex nightly backup" /SC DAILY /ST 03:15 ^
          /TR "powershell -ExecutionPolicy Bypass -NoProfile -File C:\Users\test\Desktop\Ayurveda-\scripts\production\convex-backup.ps1"

    Restore from any archive:

        cd C:\Users\test\Desktop\ayurveda-frontend\packages\backend
        node ..\..\node_modules\convex\bin\main.js import --replace <archive.zip>
#>

$ErrorActionPreference = "Stop"

$Node       = "C:\Users\test\AppData\Local\Microsoft\WinGet\Packages\OpenJS.NodeJS.LTS_Microsoft.Winget.Source_8wekyb3d8bbwe\node-v24.19.0-win-x64\node.exe"
$ConvexCli  = "C:\Users\test\Desktop\ayurveda-frontend\node_modules\convex\bin\main.js"
# Run from the package that owns the deployment: the CLI reads .env.local there
# for CONVEX_SELF_HOSTED_URL and CONVEX_SELF_HOSTED_ADMIN_KEY.
$WorkDir    = "C:\Users\test\Desktop\ayurveda-frontend\packages\backend"
$BackupDir  = "C:\Users\test\Desktop\convex-backups"
$KeepDays   = 30
$LogFile    = Join-Path $BackupDir "backup.log"

function Write-Log($msg) {
    $line = "{0}  {1}" -f (Get-Date -Format "yyyy-MM-dd HH:mm:ss"), $msg
    Write-Output $line
    Add-Content -Path $LogFile -Value $line -Encoding utf8
}

New-Item -ItemType Directory -Force -Path $BackupDir | Out-Null

# Seconds included: `convex export` refuses to write to an occupied path, so a
# minute-resolution name makes two runs in the same minute fail the second one.
$stamp  = Get-Date -Format "yyyy-MM-dd-HHmmss"
$out    = Join-Path $BackupDir "convex-$stamp.zip"

Write-Log "starting export -> $out"

Push-Location $WorkDir
try {
    # --include-file-storage is not the default. Without it you get the tables
    # and none of the uploaded files, which you discover during a restore
    # rather than during a backup.
    #
    # No `2>&1`, and EAP relaxed around the call: in Windows PowerShell 5.1,
    # redirecting a native executable's stderr wraps every line in an
    # ErrorRecord, which under `$ErrorActionPreference = "Stop"` aborts the
    # script even when the exe exited 0. convex writes its progress to stderr,
    # so this aborted a perfectly good export.
    $ErrorActionPreference = "Continue"
    & $Node $ConvexCli export --path $out --include-file-storage
    $code = $LASTEXITCODE
    $ErrorActionPreference = "Stop"
} finally {
    Pop-Location
}

if ($code -ne 0) {
    Write-Log "FAILED: convex export exited $code"
    exit 1
}

# Fail loudly on a missing or zero-byte archive rather than reporting success
# and then rotating away the last good copy below.
if (-not (Test-Path $out) -or (Get-Item $out).Length -eq 0) {
    Write-Log "FAILED: no data written to $out"
    exit 1
}

$sizeKb = [math]::Round((Get-Item $out).Length / 1KB)
Write-Log "OK: wrote $out ($sizeKb KB)"

# Rotate only after the new archive is confirmed non-empty.
$cutoff = (Get-Date).AddDays(-$KeepDays)
Get-ChildItem $BackupDir -Filter "convex-*.zip" -File |
    Where-Object { $_.LastWriteTime -lt $cutoff } |
    ForEach-Object { Write-Log "rotating out $($_.Name)"; Remove-Item $_.FullName -Force }

$kept = (Get-ChildItem $BackupDir -Filter "convex-*.zip" -File).Count
Write-Log "done. $kept archive(s) retained."

# An off-box copy is what makes this a real backup — a copy on the same disk
# does not survive the failure it exists for. Point this at your own storage.
# robocopy $BackupDir "\\nas\backups\convex" /MIR
