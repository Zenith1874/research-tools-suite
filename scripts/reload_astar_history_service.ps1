param(
    [Parameter(Mandatory=$true)][string]$RunDirectory,
    [Parameter(Mandatory=$true)][int]$ExpectedProcessId,
    [Parameter(Mandatory=$true)][datetime]$NextDueLocal
)

# One authorized reload, after a fresh read-only idle and process-identity check.
# Independent history and semantic workers are not stopped by this script.
$ErrorActionPreference = 'Stop'
$serviceRoot = Split-Path -Parent $PSScriptRoot
$runRoot = (Resolve-Path -LiteralPath $RunDirectory).Path
$serverScript = (Resolve-Path -LiteralPath (Join-Path $serviceRoot 'server.py')).Path
$serverProcess = Get-CimInstance Win32_Process -Filter ('ProcessId=' + $ExpectedProcessId)
if (-not $serverProcess -or $serverProcess.CommandLine -notmatch [regex]::Escape($serverScript)) {
    throw 'The expected process is not this project server.'
}
$listeners = @(Get-NetTCPConnection -LocalPort 5001 -State Listen | Select-Object -ExpandProperty OwningProcess -Unique)
if ($listeners.Count -ne 1 -or $listeners[0] -ne $ExpectedProcessId) {
    throw 'The verified server is not the sole port owner.'
}
$jobs = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/jobs' -TimeoutSec 25
$running = @($jobs.jobs.PSObject.Properties | Where-Object { $_.Value.status -eq 'running' } | Select-Object -ExpandProperty Name)
$freshPrivate = 0
foreach ($kind in @('translation_jobs','audio_jobs','ebook_jobs')) {
    $folder = Join-Path (Join-Path $serviceRoot 'data') $kind
    if (Test-Path -LiteralPath $folder) {
        foreach ($manifest in @(Get-ChildItem -LiteralPath $folder -Filter manifest.json -Recurse -File)) {
            if ($manifest.LastWriteTimeUtc -lt [datetime]::UtcNow.AddMinutes(-15)) { continue }
            $state = Get-Content -LiteralPath $manifest.FullName -Raw | ConvertFrom-Json
            if ($state.status -in @('queued','running','processing','transcribing','translating','converting')) {
                $freshPrivate += 1
            }
        }
    }
}
$indexScript = @'
import json,sqlite3,sys
from pathlib import Path
incomplete=[]
for path in Path(sys.argv[1]).glob('generation_*.db'):
    db=sqlite3.connect(path.as_uri()+'?mode=ro',uri=True,timeout=3)
    try:
        if not db.execute("SELECT value FROM research_index_meta WHERE key='built_at'").fetchone():
            incomplete.append(path.name)
    finally:db.close()
print(json.dumps({'incomplete_generations':incomplete}))
'@
$index = ($indexScript | & $serverProcess.ExecutablePath - (Join-Path $serviceRoot 'data/business_research_index_generations')) | ConvertFrom-Json
if ($LASTEXITCODE -ne 0) { throw 'Unable to verify the index generation state.' }
$stamp = [datetime]::UtcNow.ToString('yyyyMMddTHHmmssfffZ')
$preflight = @{
    checked_at_utc=[datetime]::UtcNow.ToString('o'); expected_process_id=$ExpectedProcessId;
    update_lock_busy=[bool]$jobs.update_lock_busy; running_updates=$running;
    fresh_active_document_jobs=$freshPrivate; incomplete_index_generations=@($index.incomplete_generations)
}
$utf8 = New-Object System.Text.UTF8Encoding($false)
function Write-NewJson([string]$Path, $Value) {
    $stream = [System.IO.File]::Open($Path, [System.IO.FileMode]::CreateNew, [System.IO.FileAccess]::Write)
    try {
        $bytes = $utf8.GetBytes(($Value | ConvertTo-Json -Depth 8))
        $stream.Write($bytes,0,$bytes.Length)
    } finally { $stream.Dispose() }
}
Write-NewJson (Join-Path $runRoot ('reload_preflight_' + $stamp + '.json')) $preflight
if ($preflight.update_lock_busy -or $running.Count -gt 0 -or $freshPrivate -gt 0 -or @($index.incomplete_generations).Count -gt 0) {
    Write-Output ($preflight | ConvertTo-Json -Compress)
    exit 2
}

$delay = [Math]::Max(600,[int]($NextDueLocal - (Get-Date)).TotalSeconds)
$priorDelay = $env:ASTAR_INITIAL_DELAY_SECONDS
$env:ASTAR_INITIAL_DELAY_SECONDS = [string]$delay
$stdout = Join-Path $runRoot ('server_' + $stamp + '.stdout.log')
$stderr = Join-Path $runRoot ('server_' + $stamp + '.stderr.log')
try {
    Stop-Process -Id $ExpectedProcessId -ErrorAction Stop
    $replacement = Start-Process -FilePath $serverProcess.ExecutablePath -ArgumentList @('-u',$serverScript) -WorkingDirectory $serviceRoot -WindowStyle Hidden -RedirectStandardOutput $stdout -RedirectStandardError $stderr -PassThru
} finally { $env:ASTAR_INITIAL_DELAY_SECONDS = $priorDelay }
$receipt = @{
    process_id=$replacement.Id; previous_process_id=$ExpectedProcessId;
    started_at_utc=[datetime]::UtcNow.ToString('o'); stdout=$stdout; stderr=$stderr;
    astar_initial_delay_seconds=$delay; existing_next_due_local=$NextDueLocal.ToString('o');
    user_authorization='Explicit approval in this chat';
    reason='Load the tested scheduled index entry point and semantic author handling';
    script_sha256=(Get-FileHash -LiteralPath $PSCommandPath -Algorithm SHA256).Hash
}
Write-NewJson (Join-Path $runRoot ('server_launch_' + $stamp + '.json')) $receipt
Write-Output ($receipt | ConvertTo-Json -Compress)
