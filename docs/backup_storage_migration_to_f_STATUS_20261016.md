# Backup storage migration to F: — completed (2026-10-16)

## Intended layout

- Stable compatibility path: `D:\claude\backups`
- Physical backup storage: `F:\claude_storage\backups`
- Git recovery quarantines: `F:\claude_storage\git_quarantine`
- Migration logs and content manifests: `F:\claude_storage\migration_logs`

`D:\claude\backups` is retained as the application-facing path because the
research platform has several existing backup writers.  The finalizer replaces
the physical D: directory with an NTFS junction to the F: directory, so existing
code and scheduled tasks continue to work while all future bytes land on F:.

## Verified before cutover

- `D:\claude\backups` and `F:\claude_storage\backups` each contain 57,415
  files and 110,794,920,824 bytes.
- A full source/destination SHA-256 comparison passed for all 57,415 files.
  Receipt: `F:\claude_storage\migration_logs\backups_sha256_summary_20261016T2021Z.json`.
- The original 52-file Git quarantine was copied from E: to F:.  All 52
  manifest SHA-256 values passed.  Receipt:
  `F:\claude_storage\migration_logs\git_quarantine_hash_verification_20261016T2020Z.json`.
- Four later Git temporary pack files (7,600,185,070 bytes) were copied from
  `D:\claude\.git` to
  `F:\claude_storage\git_quarantine\post_ignore_git_temp_20261016T2050Z` and
  verified byte-for-byte with SHA-256.
- `.gitignore` now excludes local semantic-update generations, business index
  generations/updates, runtime locks, faculty raw captures, and downloaded
  academic-market release archives.  This reduced visible untracked content
  from about 19.41 GiB to about 0.10 GiB and prevents desktop Git snapshots
  from trying to repack the multi-GiB runtime artifacts.
- `server.py` and `watchdog.py` were deliberately stopped after confirming no
  active update lock or running research job.  The ABDC daily and weekly
  scheduled tasks were idle and were not disabled.

## Finalizer

Run from a normal local PowerShell session:

```powershell
& 'D:\claude\scripts\finalize_backup_storage_to_f.ps1' -Apply
```

The finalizer rechecks all accepted inventories and Git hashes, creates and
write-tests the junction, removes only the four verified new Git temporary
files, restarts the watchdog/server, waits for a healthy API, and only then
removes the verified old D: backup source and the superseded E: Git quarantine.
It stops before destructive work when a service, scheduled task, Git process,
lock, path, count, size, receipt, or hash differs from this checkpoint.

## Final verified state

- `D:\claude\backups` is an NTFS junction to
  `F:\claude_storage\backups`.
- `D:\claude\data\astar_semantic_updates` is an NTFS junction to
  `F:\claude_storage\astar_semantic_updates`.
- Guarded Faculty Jobs backups resolve through
  `data\faculty_jobs_backup_dir.txt` to
  `F:\claude_storage\faculty_jobs_backups`.
- The original E: Faculty Jobs backup source and Git quarantine were removed
  only after the F: retain sets passed SHA-256 verification.
- Faculty Jobs retention kept the newest three days, the newest two backups
  for every write tag, every unmanifested backup, and all 210 legacy snapshots.
  It omitted 163 superseded guarded database backups (42.7 GiB) from the F:
  retain set.
- Four unreferenced intermediate Business Research Phase 1 snapshots were
  removed; the documented pre-migration snapshot and final snapshot remain.
- The two old `tmp\backups` databases were preserved under
  `F:\claude_storage\backups\legacy_tmp_backups_20260727` before their D:
  copies were removed.
- The Git quarantine was removed after `git fsck --full --no-reflogs` exited
  successfully, local and upstream HEAD matched, and current Git garbage was
  zero.  Its small manifests remain under
  `F:\claude_storage\migration_logs\git_quarantine_receipts`.
- Live readback after cleanup: service health `ok`, update lock false, no
  running job, one server process, one watchdog process, and zero Git temporary
  pack files.
- Final free space readback: D: 162.71 GiB, E: 1287.04 GiB, F: 95.36 GiB.
- Final cleanup receipt:
  `F:\claude_storage\migration_logs\backup_cleanup_receipt_20261016T2120Z.json`.
