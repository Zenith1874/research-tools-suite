# Academic Career correctness and crawl-policy fixes — 2026-08-26

Three defects found by reviewing the 2026-08-25 delivery, plus one repository-boundary
gap that was blocking the project audit. All four are fixed; 120 Academic Career tests
pass and `scripts/audit_projects.py` returns 0 errors / 0 warnings.

## 1. Relative posted dates were anchored on the UTC calendar day

`tests/test_faculty_jobs_source_expansion.py` failed on 2026-08-25 with
`'2026-08-22' != '2026-08-23'`. The cause was not the assertion.

`normalize_source_job` sets `first_seen` from `SourceJob.captured_at`, which
`base.now_utc()` writes as a UTC instant, then passes it to `parse_date` as the anchor
for relative expressions. `_reference_date` took `.date()` straight off that value, so
`"3 days ago"` counted back from the **UTC** calendar day. Every evening west of
Greenwich — after 18:00 local here — UTC has already rolled over while the local day and
the source's own day have not, so every relative date landed one day late.

Reproduced against the exact instant that produced the failure:

| captured_at | anchor before | anchor after |
|---|---|---|
| `2026-08-26T05:45:22Z` (local 2026-08-25 23:45) | 2026-08-26 | 2026-08-25 |

Affected `posted_date` and `parse_deadline` on every source publishing relative dates —
AIS and AAA Career Center today — which then feeds the `posted_after` filter, the
`newest` sort, and `_repair_job_status_recency`.

Fixed in `services/faculty_jobs_normalizer.py` by resolving an instant to the local
calendar day (`_local_calendar_date`) before using it as an anchor. Relative dates remain
inherently +/- 1 day precise, because no board publishes the timezone it renders them in;
that limitation is now stated rather than hidden behind a wrong-by-one value. The
deprecated naive `datetime.utcnow()` fallback on the same line was replaced with an
aware `datetime.now(timezone.utc)`.

The test itself was also wrong: it asserted a literal date against a relative input, so it
could only pass on the day it was written. It now pins `captured_at` explicitly, and a
second test locks the anchoring contract directly.

## 2. robots.txt was never consulted

The adapter layer had an honest User-Agent, bounded retries, `Retry-After` handling and
per-source delays, but no robots.txt check anywhere in the repository. That mattered most
for `scan_aacsb_official_websites`, which reaches **1,053 arbitrary institution websites**
and follows up to four discovered career pages each.

`SourceAdapter.request()` now checks the origin's rules before every fetch, matching the
`research-tools-suite` agent token, parsed once per origin and cached. Reachability
follows RFC 9309: 4xx means no rules are published and crawling proceeds; an unreachable
robots.txt (5xx or transport failure) is a full disallow, not permission.

A refusal raises `RobotsDisallowedError`, kept distinguishable from a transport error so
a refused site is never recorded as `no_current_jobs`. New AACSB scan outcomes:

- `website_status='robots_disallowed'` when the site itself is refused.
- `job_scan_status='unknown'` — not `no_current_jobs` — when robots refused part of a
  site that was otherwise readable, because the site was not fully read.

`Crawl-delay` is honoured as spacing between consecutive requests to the same origin, not
as a sleep before every request, and is capped at 30s. AIS publishes `Crawl-delay: 3600`
under `User-agent: *`; blocking a scheduled run for an hour would stall the global update
lock, so the cap is applied and logged rather than silently dropped.

**All five enabled sources and the AACSB directory were checked live against this gate on
2026-08-26 and are allowed**, so the change does not reduce current coverage:

| Source | robots.txt verdict |
|---|---|
| AIS | allow (`Crawl-delay: 3600`, capped to 30s) |
| University Affairs | allow |
| jobs.ac.uk | allow |
| EURAXESS | allow |
| Inside Higher Ed | allow |
| AACSB directory + load endpoint | allow (no robots.txt published) |

Covered by 11 new tests in `tests/test_faculty_jobs_robots.py`.

## 3. A filter dict passed positionally silently created an empty database

A 278KB SQLite file named `{'scope': 'business'}` was sitting in the repository root. Every
public builder takes `db_path` first and `query` second, and `_connect` did
`str(db_path or FACULTY_DB_PATH)`, so `build_faculty_jobs_payload({'scope': 'business'})`
stringified the dict into a filename, created a schema-correct empty database and returned
an empty result **without raising**.

`_connect` now rejects a non-path `db_path` with a `TypeError` naming the mistake. The
stray database was deleted.

## 4. The book-scan evidence layer had no declared migration policy

`scripts/audit_projects.py` was failing with 101 errors covering 971 ignored paths, all in
`data/research_source_text/**`, `data/research_sources/**`, `data/research_evidence/**` and
`data/business_research_state.db`. None of it is Academic Career: it is the Business
Research evidence work, whose pages are served under `/abdc/research` inside the existing
`abdc_research` domain but were never added to `projects/registry.json`.

Consequence beyond the red gate: `scripts/create_private_migration_snapshot.py` selects
from the registry's declared private paths, so the OCR'd book evidence was outside private
backup coverage entirely.

The `abdc_research` entry now declares the Business Research routes, source globs, tracked
`data/research_catalog.json`, and the four private data globs. Audit returns
`projects_audit=pass projects=6 errors=0 warnings=0`.

## Verification

```bash
python -m unittest tests.test_faculty_jobs_normalizer tests.test_faculty_jobs_schema \
  tests.test_faculty_jobs_security tests.test_faculty_jobs_p2 tests.test_faculty_jobs_sources \
  tests.test_faculty_jobs_aacsb tests.test_faculty_jobs_source_expansion \
  tests.test_faculty_jobs_robots -q
# Ran 120 tests — OK

python scripts/audit_projects.py
# projects_audit=pass projects=6 errors=0 warnings=0
```

## Not addressed here

- `services/faculty_jobs_service.py` is 5,651 lines; 17 `_repair_*` functions spanning
  lines 1809-4442 are spent one-shot migrations that will never fire again on this
  database and belong in a separate migrations module.
- `business_research_tier` is 920 `T4`, 291 `Unclassified`, 1 `T3`, 1 `T2`, 0 `T1`, and
  `university_research_level` is `Unknown` for all 1,658 institutions. Both axes are
  effectively empty. The 136,211-article A* corpus in `pboc_data.db` is the obvious
  evidence base and is not linked to this domain at all; `_parse_openalex_work` discards
  `authorships[].institutions`, so the affiliation data needed to link them was never
  stored. See the separate A* institution backfill plan.
- 525 of 1,522 jobs (35%) remain `business_scope='unknown'`.
- 331 unresolved duplicate-review rows have no batch review path.
- `visa` evidence coverage is 0.5%, which is the field that matters most for an
  international candidate on the US market.
