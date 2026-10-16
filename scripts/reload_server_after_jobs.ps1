$ErrorActionPreference = 'Stop'

while ($true) {
    try {
        $jobs = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/jobs' -TimeoutSec 5
        if (-not $jobs.update_lock_busy) {
            break
        }
    } catch {
        exit 0
    }
    Start-Sleep -Seconds 10
}

$server = Get-CimInstance Win32_Process | Where-Object {
    $_.Name -eq 'pythonw.exe' -and $_.CommandLine -match 'D:\\claude\\server.py'
}
if ($server) {
    Stop-Process -Id $server.ProcessId
}
