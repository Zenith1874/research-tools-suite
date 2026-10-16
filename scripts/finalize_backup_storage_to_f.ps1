[CmdletBinding()]
param(
    [switch]$Apply
)

$ErrorActionPreference = 'Stop'

$repoRoot = 'D:\claude'
$sourceBackups = 'D:\claude\backups'
$stagedBackups = 'D:\claude\backups.migration_source_20261016T2049Z'
$targetBackups = 'F:\claude_storage\backups'
$migrationLogs = 'F:\claude_storage\migration_logs'
$backupSummaryPath = Join-Path $migrationLogs 'backups_sha256_summary_20261016T2021Z.json'
$oldGitSource = 'E:\claude_git_garbage_quarantine_20261016T1944Z'
$oldGitTarget = 'F:\claude_storage\git_quarantine\claude_git_garbage_quarantine_20261016T1944Z'
$oldGitVerification = Join-Path $migrationLogs 'git_quarantine_hash_verification_20261016T2020Z.json'
$newGitTarget = 'F:\claude_storage\git_quarantine\post_ignore_git_temp_20261016T2050Z'
$newGitManifestPath = Join-Path $newGitTarget 'manifest.json'
$pythonw = 'C:\Users\cui10\AppData\Local\Programs\Python\Python312\pythonw.exe'
$watchdog = Join-Path $repoRoot 'scripts\watchdog.py'
$expectedBackupFiles = 57415
$expectedBackupBytes = [int64]110794920824

function Assert-ExactResolvedPath {
    param([string]$Path, [string]$Expected)
    $resolved = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    if (-not $resolved.Equals($Expected.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved path is not the expected target: $resolved"
    }
    return $resolved
}

function Get-TreeStats {
    param([string]$Path)
    $files = @(Get-ChildItem -LiteralPath $Path -File -Recurse -Force -ErrorAction Stop)
    [pscustomobject]@{
        Files = $files.Count
        Bytes = [int64](($files | Measure-Object -Property Length -Sum).Sum)
    }
}

function Assert-ServiceStoppedAndTasksIdle {
    $serviceProcesses = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match 'D:\\claude\\server\.py' -or
        $_.CommandLine -match 'D:\\claude\\scripts\\watchdog\.py'
    })
    if ($serviceProcesses.Count -gt 0) {
        throw 'server.py or watchdog.py is running; no cutover performed.'
    }
    foreach ($taskName in @('ABDC_Astar_DailyUpdate', 'ABDC_Astar_WeeklySnapshot')) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq 'Running') {
            throw "Scheduled task is running: $taskName"
        }
    }
}

function Assert-GitIdle {
    $gitProcesses = @(Get-CimInstance Win32_Process | Where-Object { $_.Name -match '^git.*\.exe$' })
    $gitLocks = @(Get-ChildItem -LiteralPath (Join-Path $repoRoot '.git') -File -Recurse -Force -ErrorAction SilentlyContinue |
        Where-Object { $_.Name -match '\.lock$|^gc\.pid$|^gc\.log$|^maintenance\.log$' })
    if ($gitProcesses.Count -gt 0 -or $gitLocks.Count -gt 0) {
        throw 'A Git process or lock is active; no Git temporary files were removed.'
    }
}

function Assert-ManifestCopy {
    param(
        [string]$ManifestPath,
        [string]$SourceRoot,
        [string]$CopyRoot,
        [switch]$RequireSource
    )
    $manifest = Get-Content -LiteralPath $ManifestPath -Raw | ConvertFrom-Json
    foreach ($record in @($manifest.files)) {
        $relative = $record.relative_path.Replace('/', '\')
        if ($relative -notmatch '^objects\\pack\\tmp_pack_[^\\]+$' -and
            $relative -notmatch '^objects\\[0-9a-fA-F]{2}\\tmp_obj_[^\\]+$') {
            throw "Unexpected Git path in manifest: $relative"
        }
        $copy = Join-Path $CopyRoot $relative
        if (-not (Test-Path -LiteralPath $copy -PathType Leaf)) {
            throw "Missing verified Git copy: $copy"
        }
        if ((Get-Item -LiteralPath $copy).Length -ne [int64]$record.size_bytes) {
            throw "Git copy size mismatch: $copy"
        }
        $expected = $record.sha256.ToLowerInvariant()
        $copyHash = (Get-FileHash -LiteralPath $copy -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($copyHash -ne $expected) {
            throw "Git copy SHA-256 mismatch: $copy"
        }
        if ($RequireSource) {
            $source = Join-Path $SourceRoot $relative
            if (-not (Test-Path -LiteralPath $source -PathType Leaf)) {
                throw "Missing Git source: $source"
            }
            if ((Get-Item -LiteralPath $source).Length -ne [int64]$record.size_bytes) {
                throw "Git source size mismatch: $source"
            }
            $sourceHash = (Get-FileHash -LiteralPath $source -Algorithm SHA256).Hash.ToLowerInvariant()
            if ($sourceHash -ne $expected) {
                throw "Git source SHA-256 mismatch: $source"
            }
        }
    }
    return $manifest
}

if (-not $Apply) {
    throw 'Dry-run guard: rerun this script with -Apply after reviewing it.'
}

Assert-ServiceStoppedAndTasksIdle
Assert-GitIdle

if (Test-Path -LiteralPath $stagedBackups) {
    throw "Staged backup path already exists: $stagedBackups"
}
$sourceItem = Get-Item -LiteralPath $sourceBackups -Force
if ($sourceItem.LinkType) {
    throw 'D:\claude\backups is already a link; refusing to replay the migration.'
}
Assert-ExactResolvedPath -Path $sourceBackups -Expected $sourceBackups | Out-Null
Assert-ExactResolvedPath -Path $targetBackups -Expected $targetBackups | Out-Null

$backupSummary = Get-Content -LiteralPath $backupSummaryPath -Raw | ConvertFrom-Json
if (-not $backupSummary.passed -or
    [int]$backupSummary.files -ne $expectedBackupFiles -or
    [int64]$backupSummary.total_bytes -ne $expectedBackupBytes) {
    throw 'The full backup SHA-256 summary does not match the accepted migration inventory.'
}
$sourceStats = Get-TreeStats -Path $sourceBackups
$targetStats = Get-TreeStats -Path $targetBackups
foreach ($stats in @($sourceStats, $targetStats)) {
    if ($stats.Files -ne $expectedBackupFiles -or $stats.Bytes -ne $expectedBackupBytes) {
        throw "Backup tree count/size changed: files=$($stats.Files), bytes=$($stats.Bytes)"
    }
}

$oldGitResult = Get-Content -LiteralPath $oldGitVerification -Raw | ConvertFrom-Json
if (-not $oldGitResult.passed -or [int]$oldGitResult.files -ne 52) {
    throw 'The original Git quarantine verification receipt is not valid.'
}
$oldSourceStats = Get-TreeStats -Path $oldGitSource
$oldTargetStats = Get-TreeStats -Path $oldGitTarget
if ($oldSourceStats.Files -ne $oldTargetStats.Files -or $oldSourceStats.Bytes -ne $oldTargetStats.Bytes) {
    throw 'The E: and F: copies of the original Git quarantine differ in count or size.'
}

$gitObjectRoot = Join-Path $repoRoot '.git'
$newGitManifest = Assert-ManifestCopy -ManifestPath $newGitManifestPath `
    -SourceRoot $gitObjectRoot -CopyRoot $newGitTarget -RequireSource

Write-Host 'All pre-cutover guards passed.'

# Remove only the four exact Git temporary files whose F: copies were just
# checked against the saved SHA-256 manifest.  Do this before the backup
# junction cutover so a Git-busy failure cannot leave the service stopped with
# a half-finished directory transition.
Assert-GitIdle
foreach ($record in @($newGitManifest.files)) {
    $source = Join-Path $gitObjectRoot $record.relative_path.Replace('/', '\')
    Remove-Item -LiteralPath $source -Force -ErrorAction Stop
}

$junctionActivated = $false
try {
    Move-Item -LiteralPath $sourceBackups -Destination $stagedBackups -ErrorAction Stop
    New-Item -ItemType Junction -Path $sourceBackups -Target $targetBackups -ErrorAction Stop | Out-Null
    $junction = Get-Item -LiteralPath $sourceBackups -Force
    if ($junction.LinkType -ne 'Junction') {
        throw 'D:\claude\backups was not created as a junction.'
    }
    $probeName = '.migration_probe_20261016T2049Z.txt'
    $probeViaLink = Join-Path $sourceBackups $probeName
    $probeOnTarget = Join-Path $targetBackups $probeName
    [System.IO.File]::WriteAllText(
        $probeViaLink,
        'backup junction write-through verified',
        [System.Text.UTF8Encoding]::new($false)
    )
    if (-not (Test-Path -LiteralPath $probeOnTarget -PathType Leaf)) {
        throw 'The backup junction write-through probe did not reach F:.'
    }
    Remove-Item -LiteralPath $probeViaLink -Force
    $junctionActivated = $true
}
catch {
    if (Test-Path -LiteralPath $sourceBackups) {
        $possibleLink = Get-Item -LiteralPath $sourceBackups -Force
        if ($possibleLink.LinkType -eq 'Junction') {
            Remove-Item -LiteralPath $sourceBackups -Force
        }
    }
    if (Test-Path -LiteralPath $stagedBackups -PathType Container) {
        Move-Item -LiteralPath $stagedBackups -Destination $sourceBackups
    }
    throw
}

if (-not $junctionActivated) {
    throw 'Backup junction activation did not complete.'
}

Start-Process -FilePath $pythonw `
    -ArgumentList @($watchdog, '--start-if-down') `
    -WorkingDirectory $repoRoot `
    -WindowStyle Hidden

$healthy = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/health' -TimeoutSec 3
        if ($health.status -eq 'ok') {
            $healthy = $true
            break
        }
    }
    catch {
        # The watchdog may still be starting server.py.
    }
}
if (-not $healthy) {
    throw 'The backup junction is active, but server.py did not return healthy within 40 seconds. The staged D: source remains available.'
}

$postLink = Get-Item -LiteralPath $sourceBackups -Force
$postTarget = [string]$postLink.Target
if ($postLink.LinkType -ne 'Junction' -or
    -not $postTarget.TrimEnd('\').Equals(
        $targetBackups.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Post-restart backup junction verification failed. The staged D: source remains available.'
}

# The F: copies have passed SHA-256 validation and the live service now uses
# the verified junction. Removing the two old source copies completes the move.
Assert-ExactResolvedPath -Path $stagedBackups -Expected $stagedBackups | Out-Null
Assert-ExactResolvedPath -Path $oldGitSource -Expected $oldGitSource | Out-Null
Remove-Item -LiteralPath $stagedBackups -Recurse -Force -ErrorAction Stop
Remove-Item -LiteralPath $oldGitSource -Recurse -Force -ErrorAction Stop

$finalJobs = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/jobs' -TimeoutSec 10
$finalD = Get-Volume -DriveLetter D
$finalE = Get-Volume -DriveLetter E
$finalF = Get-Volume -DriveLetter F

[pscustomobject]@{
    status = 'completed'
    backup_link = $sourceBackups
    backup_target = $targetBackups
    backup_files = $expectedBackupFiles
    backup_bytes = $expectedBackupBytes
    git_quarantine_target = Split-Path -Parent $oldGitTarget
    new_git_temp_files_removed_from_D = @($newGitManifest.files).Count
    old_git_quarantine_removed_from_E = -not (Test-Path -LiteralPath $oldGitSource)
    service_health = $health.status
    update_lock_busy = $finalJobs.update_lock_busy
    d_free_gib = [math]::Round($finalD.SizeRemaining / 1GB, 2)
    e_free_gib = [math]::Round($finalE.SizeRemaining / 1GB, 2)
    f_free_gib = [math]::Round($finalF.SizeRemaining / 1GB, 2)
    backup_sha256_summary = $backupSummaryPath
    backup_sha256_manifest = $backupSummary.manifest
} | Format-List
