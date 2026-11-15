# Restart the API on a given port, killing whatever already holds it.
#
# Stopping the shell that launched uvicorn does not always stop uvicorn: the
# python process outlives it and keeps the port, so the next start fails with
# exit code 3 and the old code carries on answering requests. That is a nasty
# way to lose an afternoon -- the app looks like it reloaded and did not. So
# this finds the listener by port and stops that process by pid.
#
#   powershell -File restart_api.ps1 -Port 8095

param(
    [int]$Port = 8095,
    [string]$LogPath = "$env:TEMP\api-$Port.log"
)

$ErrorActionPreference = "Stop"
$here = Split-Path -Parent $MyInvocation.MyCommand.Path

$conns = Get-NetTCPConnection -LocalPort $Port -State Listen -ErrorAction SilentlyContinue
foreach ($conn in $conns) {
    $proc = Get-Process -Id $conn.OwningProcess -ErrorAction SilentlyContinue
    if ($proc) {
        Write-Host "stopping pid $($proc.Id) ($($proc.ProcessName)) on port $Port"
        try { Stop-Process -Id $proc.Id -Force -ErrorAction Stop } catch {
            Write-Host "  could not stop: $($_.Exception.Message)"
        }
    } else {
        # A listening socket whose process is gone. Windows clears these on
        # its own; nothing to kill, and a new bind on the port still works.
        Write-Host "port $Port has a stale socket (pid $($conn.OwningProcess), no process)"
    }
}

Start-Process -FilePath "python" `
    -ArgumentList "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", "$Port" `
    -WorkingDirectory $here `
    -RedirectStandardOutput $LogPath `
    -RedirectStandardError "$LogPath.err" `
    -WindowStyle Hidden

# Wait for it to answer rather than guessing at a sleep.
$deadline = (Get-Date).AddSeconds(45)
while ((Get-Date) -lt $deadline) {
    try {
        $r = Invoke-RestMethod -Uri "http://127.0.0.1:$Port/api/health" -TimeoutSec 2
        Write-Host "ready on $Port -- server_date $($r.server_date)"
        exit 0
    } catch { Start-Sleep -Milliseconds 400 }
}

Write-Host "did not come up within 45s; last lines of $LogPath.err:"
if (Test-Path "$LogPath.err") { Get-Content "$LogPath.err" -Tail 20 }
exit 1
