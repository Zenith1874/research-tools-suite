param([int]$ExpectedPid)
$ErrorActionPreference = 'Stop'
$serviceRoot = Split-Path -Parent $PSScriptRoot
$serverScriptPath = (Resolve-Path -LiteralPath (Join-Path $serviceRoot 'server.py')).Path

while ($true) {
    $jobsState = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/jobs' -TimeoutSec 10
    $translationState = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/translation/jobs' -TimeoutSec 10
    $audioState = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/audio/jobs' -TimeoutSec 10
    $activePrivate = @(@($translationState.jobs) + @($audioState.jobs) | Where-Object {
        $_.status -in @('queued','running','processing','transcribing','translating')
    })
    if (-not $jobsState.update_lock_busy -and $activePrivate.Count -eq 0) { break }
    Start-Sleep -Seconds 10
}

$listeners = @(Get-NetTCPConnection -LocalPort 5001 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count -ne 1 -or $listeners[0] -ne $ExpectedPid) {
    Write-Output 'The server identity changed before reload; leaving it untouched.'
    exit 0
}
$serviceProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ExpectedPid)
if (-not $serviceProcess -or $serviceProcess.CommandLine -notmatch [regex]::Escape($serverScriptPath)) {
    throw 'The port owner is not the verified project server.'
}
$serviceExecutable = $serviceProcess.ExecutablePath
Stop-Process -Id $ExpectedPid -ErrorAction Stop
Write-Output ('Stopped verified idle server PID ' + $ExpectedPid)
# The existing watchdog normally restores it. A fallback uses the same Python
# executable and project working directory, without opening a visible window.
Start-Sleep -Seconds 10
$newListener = Get-NetTCPConnection -LocalPort 5001 -State Listen -ErrorAction SilentlyContinue | Select-Object -First 1
if (-not $newListener) {
    Start-Process -FilePath $serviceExecutable -ArgumentList @($serverScriptPath) -WorkingDirectory $serviceRoot -WindowStyle Hidden
    Start-Sleep -Seconds 5
}
$healthy = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/faculty-jobs/requirements-comparison' -TimeoutSec 30
Write-Output ('Reload healthy: R2=' + $healthy.groups.r2_teaching.jobs + ', R1=' + $healthy.groups.r1.jobs)
