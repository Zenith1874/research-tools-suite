# Academic Career project-boundary addendum — 2026-08-23

This is a post-migration addendum to the historical one-plus-five boundary documents. It does not rewrite the earlier snapshot. The live registry is now dynamic and declares `one_plus_six`; `scripts/audit_one_plus_five.py` remains only as a compatibility wrapper around `scripts/audit_projects.py`.

## Boundary

The new `academic_career` project owns the four faculty-career routes, the faculty-job service/source adapters, the normalizer/rank mapper/fit/school helpers, their static pages, fixtures/tests, taxonomy rulebooks, and the project README. It continues to share the root server, global update lock, navigation, dependencies, access security, and test runner.

## Private paths

The separate `data/faculty_jobs.db*`, `data/faculty_jobs_cache/`, `data/faculty_job_profile.json`, and `data/faculty_jobs_private/` paths are explicitly gitignored and registered as private. The public registry records the schema and rulebooks, not runtime rows, raw HTML, personal profile values, or application notes.

## Audit interpretation

The dynamic audit checks unique project IDs/navigation keys, route ownership and navigation presence, source-glob coverage, tracked rulebooks, private-path tracking/ignore status, unexplained ignored paths, public file-size limits, and high-confidence secret patterns. It does not assume a fixed project count.

## 2026-08-24 incremental schema note

Migration 14 adds `saved_searches`, `saved_search_alerts`, and duplicate-review resolution metadata. It also exposes a private institution-alias ledger through the existing server. The migration is idempotent, uses the existing Academic Career database/update-lock boundary, and does not delete source records, provenance, status history, or personal application data. Saved-search deletion removes only the local search definition and its alert metadata; it never deletes a job.
