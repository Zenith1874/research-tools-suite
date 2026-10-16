[CmdletBinding()]
param([switch]$Apply)

$ErrorActionPreference = 'Stop'

$repoRoot = 'D:\claude'
$fRoot = 'F:\claude_storage'
$logRoot = Join-Path $fRoot 'migration_logs'
$pythonw = 'C:\Users\cui10\AppData\Local\Programs\Python\Python312\pythonw.exe'
$watchdog = Join-Path $repoRoot 'scripts\watchdog.py'

$gitQuarantine = Join-Path $fRoot 'git_quarantine'
$oldGitQuarantine = Join-Path $gitQuarantine 'claude_git_garbage_quarantine_20261016T1944Z'
$newGitQuarantine = Join-Path $gitQuarantine 'post_ignore_git_temp_20261016T2050Z'
$oldGitReceipt = Join-Path $logRoot 'git_quarantine_hash_verification_20261016T2020Z.json'

$facultySource = 'E:\claude-backups\faculty_jobs'
$facultyTarget = Join-Path $fRoot 'faculty_jobs_backups'
$facultyManifestPath = Join-Path $logRoot 'faculty_jobs_f_migration_manifest_20261016T2115Z.json'
$facultyLegacyManifestPath = Join-Path $logRoot 'faculty_jobs_legacy_manifest_20261016T2125Z.json'
$facultyRetentionPath = Join-Path $logRoot 'faculty_jobs_retention_plan_20261016T2115Z.json'
$facultyPointer = Join-Path $repoRoot 'data\faculty_jobs_backup_dir.txt'

$semanticSource = Join-Path $repoRoot 'data\astar_semantic_updates'
$semanticStaged = Join-Path $repoRoot 'data\astar_semantic_updates.migration_source_20261016T2120Z'
$semanticTarget = Join-Path $fRoot 'astar_semantic_updates'
$semanticManifestPath = Join-Path $logRoot 'astar_semantic_updates_manifest_20261016T2120Z.json'

$legacySource = Join-Path $repoRoot 'tmp\backups'
$legacyTarget = Join-Path $fRoot 'backups\legacy_tmp_backups_20260727'
$legacyManifestPath = Join-Path $logRoot 'legacy_tmp_backups_manifest_20261016T2120Z.json'
$phaseOnePlanPath = Join-Path $logRoot 'phase1_retention_cleanup_plan_20261016T2120Z.json'

function Assert-ExactResolvedPath {
    param([string]$Path, [string]$Expected)
    $resolved = (Resolve-Path -LiteralPath $Path).Path.TrimEnd('\')
    if (-not $resolved.Equals($Expected.TrimEnd('\'), [StringComparison]::OrdinalIgnoreCase)) {
        throw "Resolved path is not the expected target: $resolved"
    }
    return $resolved
}

function Assert-ServiceStopped {
    $processes = @(Get-CimInstance Win32_Process | Where-Object {
        $_.CommandLine -match 'D:\\claude\\server\.py' -or
        $_.CommandLine -match 'D:\\claude\\scripts\\watchdog\.py'
    })
    if ($processes.Count -gt 0) {
        throw 'server.py or watchdog.py is running; cleanup not started.'
    }
    foreach ($taskName in @('ABDC_Astar_DailyUpdate', 'ABDC_Astar_WeeklySnapshot')) {
        $task = Get-ScheduledTask -TaskName $taskName -ErrorAction SilentlyContinue
        if ($task -and $task.State -eq 'Running') {
            throw "Scheduled task is running: $taskName"
        }
    }
}

function Assert-ManifestFiles {
    param(
        [psobject[]]$Entries,
        [string]$Root,
        [string]$PathProperty = 'relative_path'
    )
    $index = 0
    $verifiedBytes = [int64]0
    Write-Host "Verifying $($Entries.Count) manifest file(s) under $Root"
    foreach ($entry in $Entries) {
        $index++
        $relative = [string]$entry.$PathProperty
        $path = Join-Path $Root $relative.Replace('/', '\')
        if (-not (Test-Path -LiteralPath $path -PathType Leaf)) {
            throw "Manifest file is missing: $path"
        }
        if ((Get-Item -LiteralPath $path).Length -ne [int64]$entry.size_bytes) {
            throw "Manifest size mismatch: $path"
        }
        $hash = (Get-FileHash -LiteralPath $path -Algorithm SHA256).Hash.ToLowerInvariant()
        if ($hash -ne ([string]$entry.sha256).ToLowerInvariant()) {
            throw "Manifest SHA-256 mismatch: $path"
        }
        $verifiedBytes += [int64]$entry.size_bytes
        if ($index % 25 -eq 0 -or [int64]$entry.size_bytes -ge 1GB -or $index -eq $Entries.Count) {
            Write-Host ("  verified {0}/{1}; {2:N2} GiB" -f `
                $index, $Entries.Count, ($verifiedBytes / 1GB))
        }
    }
}

function Write-JsonReceipt {
    param([string]$Path, [System.Collections.IDictionary]$Payload)
    [System.IO.File]::WriteAllText(
        $Path,
        ($Payload | ConvertTo-Json -Depth 8),
        [System.Text.UTF8Encoding]::new($false)
    )
}

if (-not $Apply) {
    throw 'Dry-run guard: review this script, then rerun with -Apply.'
}

Assert-ServiceStopped

# The main backup path must already be the verified D: -> F: junction.
$backupLink = Get-Item -LiteralPath (Join-Path $repoRoot 'backups') -Force
if ($backupLink.LinkType -ne 'Junction' -or
    -not ([string]$backupLink.Target).TrimEnd('\').Equals(
        (Join-Path $fRoot 'backups').TrimEnd('\'),
        [StringComparison]::OrdinalIgnoreCase)) {
    throw 'The main backup junction is not the verified F: target.'
}

# Verify both Git quarantine batches before deleting the recovery copies.
$oldResult = Get-Content -LiteralPath $oldGitReceipt -Raw | ConvertFrom-Json
if (-not $oldResult.passed -or [int]$oldResult.files -ne 52) {
    throw 'Original Git quarantine verification receipt is invalid.'
}
$oldManifest = Get-Content -LiteralPath (Join-Path $oldGitQuarantine 'manifest.json') -Raw | ConvertFrom-Json
Assert-ManifestFiles -Entries @($oldManifest.files) -Root $oldGitQuarantine
$newManifest = Get-Content -LiteralPath (Join-Path $newGitQuarantine 'manifest.json') -Raw | ConvertFrom-Json
Assert-ManifestFiles -Entries @($newManifest.files) -Root $newGitQuarantine

# Verify the Faculty Jobs keep set, including the separately preserved legacy
# snapshots.  Then prove every E: source file is either retained or explicitly
# listed as a superseded retention candidate.
$facultyManifest = Get-Content -LiteralPath $facultyManifestPath -Raw | ConvertFrom-Json
if (-not $facultyManifest.passed) { throw 'Faculty Jobs migration manifest is not passed.' }
Assert-ManifestFiles -Entries @($facultyManifest.entries) -Root $facultyTarget -PathProperty 'name'
$facultyLegacyManifest = Get-Content -LiteralPath $facultyLegacyManifestPath -Raw | ConvertFrom-Json
if (-not $facultyLegacyManifest.passed) { throw 'Faculty Jobs legacy manifest is not passed.' }
Assert-ManifestFiles -Entries @($facultyLegacyManifest.entries) `
    -Root (Join-Path $facultyTarget 'legacy_snapshots')
$facultyRetention = Get-Content -LiteralPath $facultyRetentionPath -Raw | ConvertFrom-Json
$coveredFacultyPaths = [System.Collections.Generic.HashSet[string]]::new(
    [StringComparer]::OrdinalIgnoreCase
)
foreach ($entry in @($facultyManifest.entries)) {
    [void]$coveredFacultyPaths.Add(([string]$entry.name).Replace('/', '\'))
}
foreach ($entry in @($facultyLegacyManifest.entries)) {
    [void]$coveredFacultyPaths.Add(('legacy_snapshots\' + [string]$entry.relative_path).Replace('/', '\'))
}
foreach ($candidate in @($facultyRetention.remove_candidates)) {
    [void]$coveredFacultyPaths.Add([string]$candidate.database)
    if ($candidate.manifest) { [void]$coveredFacultyPaths.Add([string]$candidate.manifest) }
}
$sourceFacultyFiles = @(Get-ChildItem -LiteralPath $facultySource -File -Recurse -Force)
$uncoveredFaculty = @($sourceFacultyFiles | Where-Object {
    -not $coveredFacultyPaths.Contains($_.FullName.Substring($facultySource.Length + 1))
})
if ($uncoveredFaculty.Count -gt 0 -or $coveredFacultyPaths.Count -ne $sourceFacultyFiles.Count) {
    throw 'Faculty Jobs source coverage changed; E: source retained.'
}
$pointerValue = (Get-Content -LiteralPath $facultyPointer -Raw).Trim()
if (-not $pointerValue.Equals($facultyTarget, [StringComparison]::OrdinalIgnoreCase)) {
    throw 'Faculty Jobs backup pointer does not target F:.'
}

# Verify both sides of the semantic recovery migration before replacing the D:
# directory with a junction.
$semanticManifest = Get-Content -LiteralPath $semanticManifestPath -Raw | ConvertFrom-Json
if (-not $semanticManifest.passed -or [int]$semanticManifest.files -ne 178) {
    throw 'Semantic recovery migration manifest is invalid.'
}
Assert-ManifestFiles -Entries @($semanticManifest.entries) -Root $semanticSource
Assert-ManifestFiles -Entries @($semanticManifest.entries) -Root $semanticTarget
if (Test-Path -LiteralPath $semanticStaged) {
    throw "Semantic staging path already exists: $semanticStaged"
}

# Verify the two legacy temporary backups on both drives.
$legacyManifest = Get-Content -LiteralPath $legacyManifestPath -Raw | ConvertFrom-Json
if (-not $legacyManifest.passed -or [int]$legacyManifest.files -ne 2) {
    throw 'Legacy temporary-backup manifest is invalid.'
}
Assert-ManifestFiles -Entries @($legacyManifest.entries) -Root $legacySource -PathProperty 'name'
Assert-ManifestFiles -Entries @($legacyManifest.entries) -Root $legacyTarget -PathProperty 'name'

# Verify every Phase 1 intermediate snapshot against the accepted full backup
# manifest before removing those four unreferenced transient checkpoints.
$phaseOnePlan = Get-Content -LiteralPath $phaseOnePlanPath -Raw | ConvertFrom-Json
foreach ($directory in @($phaseOnePlan.remove_directories)) {
    $path = Join-Path (Join-Path $fRoot 'backups') $directory.name
    $actual = @(Get-ChildItem -LiteralPath $path -File -Recurse -Force)
    if ($actual.Count -ne [int]$directory.files) {
        throw "Phase 1 snapshot file count changed: $path"
    }
    Assert-ManifestFiles -Entries @($directory.entries) -Root (Join-Path $fRoot 'backups')
}

Write-Host 'All retention and migration guards passed.'

# Replace the active semantic recovery directory with a write-through junction.
$semanticJunctionActivated = $false
try {
    Move-Item -LiteralPath $semanticSource -Destination $semanticStaged -ErrorAction Stop
    New-Item -ItemType Junction -Path $semanticSource -Target $semanticTarget -ErrorAction Stop | Out-Null
    $link = Get-Item -LiteralPath $semanticSource -Force
    if ($link.LinkType -ne 'Junction') { throw 'Semantic recovery path is not a junction.' }
    $probeName = '.semantic-junction-probe'
    $viaLink = Join-Path $semanticSource $probeName
    $onTarget = Join-Path $semanticTarget $probeName
    [System.IO.File]::WriteAllText($viaLink, 'verified', [System.Text.UTF8Encoding]::new($false))
    if (-not (Test-Path -LiteralPath $onTarget -PathType Leaf)) {
        throw 'Semantic recovery junction write-through failed.'
    }
    Remove-Item -LiteralPath $viaLink -Force
    $semanticJunctionActivated = $true
}
catch {
    if (Test-Path -LiteralPath $semanticSource) {
        $possibleLink = Get-Item -LiteralPath $semanticSource -Force
        if ($possibleLink.LinkType -eq 'Junction') {
            Remove-Item -LiteralPath $semanticSource -Force
        }
    }
    if (Test-Path -LiteralPath $semanticStaged -PathType Container) {
        Move-Item -LiteralPath $semanticStaged -Destination $semanticSource
    }
    throw
}
if (-not $semanticJunctionActivated) { throw 'Semantic junction activation failed.' }

# Restore the normal service before deleting any verified source tree.
Start-Process -FilePath $pythonw -ArgumentList @($watchdog, '--start-if-down') `
    -WorkingDirectory $repoRoot -WindowStyle Hidden
$healthy = $false
for ($attempt = 1; $attempt -le 20; $attempt++) {
    Start-Sleep -Seconds 2
    try {
        $health = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/health' -TimeoutSec 3
        if ($health.status -eq 'ok') { $healthy = $true; break }
    }
    catch { }
}
if (-not $healthy) {
    throw 'Service did not become healthy; verified source trees were retained.'
}

# Save small Git manifests before deleting the 45 GiB quarantine payload.
$gitReceiptDir = Join-Path $logRoot 'git_quarantine_receipts'
New-Item -ItemType Directory -Path $gitReceiptDir -Force | Out-Null
foreach ($batch in @($oldGitQuarantine, $newGitQuarantine)) {
    $destination = Join-Path $gitReceiptDir (Split-Path -Leaf $batch)
    New-Item -ItemType Directory -Path $destination -Force | Out-Null
    Get-ChildItem -LiteralPath $batch -File -Force |
        Where-Object { $_.Name -in @('manifest.json', 'RESTORE.txt', 'cleanup_git_temp_garbage.ps1') } |
        Copy-Item -Destination $destination -Force
}

$cleanupReceipt = Join-Path $logRoot 'backup_cleanup_receipt_20261016T2120Z.json'
Write-JsonReceipt -Path $cleanupReceipt -Payload ([ordered]@{
    completed_at_utc = (Get-Date).ToUniversalTime().ToString('o')
    git_quarantine_bytes = [int64](
        (Get-ChildItem -LiteralPath $gitQuarantine -File -Recurse -Force |
            Measure-Object -Property Length -Sum).Sum
    )
    faculty_source_files = $sourceFacultyFiles.Count
    faculty_retention_candidates = @($facultyRetention.remove_candidates).Count
    faculty_retention_candidate_bytes = [int64]$facultyRetention.remove_candidate_bytes
    semantic_files = [int]$semanticManifest.files
    semantic_bytes = [int64]$semanticManifest.total_bytes
    phase_one_removed_bytes = [int64]$phaseOnePlan.remove_total_bytes
    legacy_tmp_bytes = [int64]$legacyManifest.total_bytes
    retained_targets = @($facultyTarget, $semanticTarget, $legacyTarget)
})

# All retained copies have been verified and the service is healthy on the F:
# targets.  The following exact, pre-resolved paths are now superseded.
Assert-ExactResolvedPath -Path $gitQuarantine -Expected $gitQuarantine | Out-Null
Assert-ExactResolvedPath -Path $facultySource -Expected $facultySource | Out-Null
Assert-ExactResolvedPath -Path $semanticStaged -Expected $semanticStaged | Out-Null
Assert-ExactResolvedPath -Path $legacySource -Expected $legacySource | Out-Null
Remove-Item -LiteralPath $gitQuarantine -Recurse -Force -ErrorAction Stop
Remove-Item -LiteralPath $facultySource -Recurse -Force -ErrorAction Stop
Remove-Item -LiteralPath $semanticStaged -Recurse -Force -ErrorAction Stop
Remove-Item -LiteralPath $legacySource -Recurse -Force -ErrorAction Stop
foreach ($directory in @($phaseOnePlan.remove_directories)) {
    $path = Join-Path (Join-Path $fRoot 'backups') $directory.name
    Assert-ExactResolvedPath -Path $path -Expected $path | Out-Null
    Remove-Item -LiteralPath $path -Recurse -Force -ErrorAction Stop
}

$jobs = Invoke-RestMethod -Uri 'http://127.0.0.1:5001/api/jobs' -TimeoutSec 10
Push-Location $repoRoot
try {
    $backupResolution = & 'C:\Users\cui10\AppData\Local\Programs\Python\Python312\python.exe' `
        -B -c "from services.faculty_jobs_write_guard import backup_directory; from services.faculty_jobs_service import FACULTY_DB_PATH; print(backup_directory(FACULTY_DB_PATH).resolve())"
}
finally {
    Pop-Location
}

[pscustomobject]@{
    status = 'completed'
    service_health = $health.status
    update_lock_busy = $jobs.update_lock_busy
    main_backup_target = [string](Get-Item -LiteralPath (Join-Path $repoRoot 'backups') -Force).Target
    faculty_backup_target = ($backupResolution | Select-Object -Last 1)
    semantic_recovery_target = [string](Get-Item -LiteralPath $semanticSource -Force).Target
    git_quarantine_removed = -not (Test-Path -LiteralPath $gitQuarantine)
    faculty_e_source_removed = -not (Test-Path -LiteralPath $facultySource)
    phase_one_intermediate_directories_removed = @($phaseOnePlan.remove_directories).Count
    d_free_gib = [math]::Round((Get-Volume -DriveLetter D).SizeRemaining / 1GB, 2)
    e_free_gib = [math]::Round((Get-Volume -DriveLetter E).SizeRemaining / 1GB, 2)
    f_free_gib = [math]::Round((Get-Volume -DriveLetter F).SizeRemaining / 1GB, 2)
    cleanup_receipt = $cleanupReceipt
} | Format-List
