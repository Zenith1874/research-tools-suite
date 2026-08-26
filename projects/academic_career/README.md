# Academic Career / Faculty Job Market

This project domain adds a public-source faculty job explorer while keeping the existing Python `HTTPServer`, static HTML/CSS/JS, SQLite, global update lock, and navigation architecture intact.

## Pages and APIs

- `/faculty-jobs` — public normalized job list, filters, source health, CSV export, and source-backed detail.
- `/school-explorer` — observed institutions, university research level versus business-school evidence tier, compare view, and local evidence entry.
- `/job-market-analytics` — descriptive distributions and coverage diagnostics.
- `/my-applications` — loopback-only profile, deterministic fit breakdown, saved jobs, application states, events, and notes.
- `/api/faculty-jobs`, `/api/faculty-jobs/<id>`, `/api/faculty-jobs/summary`, `/filters`, `/sources`, `/runs`, `/export.csv`.
- Private P2 routes include `/api/faculty-jobs/saved-searches`, `/api/faculty-jobs/alerts`, `/api/faculty-jobs/duplicates`, and `/api/institution-aliases`; they are loopback/private only.
- `/api/schools`, `/api/schools/<id>`, `/api/schools/compare`, `/api/job-market-analytics`.
- Private `/api/faculty-jobs/profile`, `/api/my-applications`, saved-search/alert/duplicate-review routes, institution-alias routes, and application PATCH routes require the service machine by default.

## Data boundary

The separate `data/faculty_jobs.db` SQLite/WAL store contains source catalog, ingestion runs, normalized jobs, institutions, business-school evidence, many-to-many source links, provenance, status history, possible duplicates, and private application state. The database, WAL/SHM, cache, profile, and private notes are gitignored. Raw HTML is not retained by the adapter layer; only bounded excerpts and structured extraction are stored.

Normalization keeps raw title/location/evidence semantics visible. Discipline, country/region, deadline mode, salary, PhD, visa, track, and start-term fields can be `Unknown`; unknown is not treated as negative evidence. Rank mapping preserves local country terms and explicitly avoids equating UK/European ranks with US ranks. School tiers are local evidence classifications, not official rankings.

The Faculty Jobs page defaults to the business-market scope. The derived `business_scope` field separates explicit business-school evidence (`business_school`) from business-discipline evidence where the school is not independently verified (`business_discipline`), and retains `non_business`, `non_academic`, and `unknown` rows for audit. Use `scope=business_school` for the strict explicit-business-school-evidence view or `scope=all` for the unfiltered source catalogue. A linked local school entity is not the same as verified school evidence; all scope decisions remain derived and auditable. These filters never delete raw jobs or source provenance.

The 2026-08-23 repair migration is source-record-first and idempotent. It corrected deadline, institution, location, country, school-entity, and deduplication-derived fields in place while retaining source records, provenance, status history, and any private application state. The Leeds school-entity migration also handles a legacy replay that already created the official target by repointing derived job links and retaining the old label as an inactive audit row. Fuzzy similarity now creates a review record only; automatic merging requires an exact source identity, a mergeable canonical official URL, or a complete compatible fingerprint.

## Public adapters and support status

Enabled low-frequency public HTML adapters currently cover AIS (US), University Affairs (Canada), jobs.ac.uk (UK/Europe), EURAXESS (Europe), and Inside Higher Ed Careers (Global). Every adapter request is gated on the origin's robots.txt (see below). Inside Higher Ed uses the public `assistant professor business` search and explicit numbered-page budgets; the full result set is retained in the audit/source-record layer and the default business scope filters it downstream. AOM is retained as a manual/degraded catalog because its current listing results are dynamically rendered; HigherEdJobs is manual because the public audit observed an anti-bot challenge. No authentication, CAPTCHA solving, reverse-engineered private endpoint, or anti-bot bypass is used.

## robots.txt

`SourceAdapter.request()` checks the origin's robots.txt before every fetch, including
each institution website reached by the AACSB scan. Rules are matched against the
`research-tools-suite` agent token, parsed once per origin and cached for the run.

Reachability follows RFC 9309: a 4xx means no rules are published and crawling proceeds,
while an unreachable robots.txt (5xx or a transport failure) is treated as a full
disallow rather than as permission. A refusal raises `RobotsDisallowedError`, which stays
distinguishable from a transport error so it is never recorded as evidence that a school
has no vacancy.

A declared `Crawl-delay` is enforced as spacing between consecutive requests to the same
origin, not as a sleep before every request. It is honoured up to a 30s ceiling; AIS
publishes `Crawl-delay: 3600` under `User-agent: *`, and blocking a scheduled run for an
hour would stall the global update lock, so the cap is applied and logged rather than
silently dropped.

All five enabled sources plus the AACSB directory were checked against this gate on
2026-08-26 and are allowed.

Every source has an independent `ingestion_runs` record. A failed source does not erase its last successful rows. A missing record is only made inactive after three successful runs for that source; a single empty or failed run does not close jobs.

## Private matching and privacy

Fit scoring is a transparent weighted rule system in `services/faculty_job_fit_service.py`; it is a decision aid, not a hiring prediction. Private fields are omitted from public job payloads and CSV unless the local-only access check passes. Remote private access is an explicit opt-in (`FACULTY_JOBS_ALLOW_REMOTE_PRIVATE=1`) and should only be enabled after reviewing the LAN threat model.

Saved searches are local definitions over the same normalized filter vocabulary as Faculty Jobs. Running one records idempotent local alerts; there is no outbound email/SaaS notification. Duplicate review is deliberately conservative: fuzzy similarity is review-only, and exact-URL merge is auditable and guarded. Institution aliases are local normalization metadata and preserve source spelling/provenance.

Final verification on 2026-08-25 also replaced the slow correlated school-list query with one grouped job-statistics join. `/api/schools` now returns the default, GB, and Europe queries in about 0.26–0.33 seconds on the production snapshot. Real-browser checks passed for all four Academic Career pages at desktop and 375px widths with zero console errors and no horizontal overflow. The remote privacy check returned 403 for profile, applications, and private CSV while public jobs remained field-redacted. The full-suite fiscal disk-I/O error remains documented as unrelated; 108 Academic Career tests and both project audits passed.

## AACSB accredited-school directory (opt-in)

The project keeps a separate AACSB roster grain in `aacsb_directory_schools`. It imports the public AACSB accredited-school directory and, when explicitly requested, follows the official website exposed by each AACSB detail page. The roster is not a job source by itself: only an explicit public academic/faculty posting discovered on the school’s own site becomes an `aacsb_official` job record. Accreditation evidence is stored in the school evidence ledger and does not imply hiring, research tier, or current vacancies.

The default scheduler does not run this crawl. Use a bounded command and record the returned run metrics:

```bash
# Import the full public AACSB roster and detail pages; no school websites yet.
python3 scripts/update_aacsb_directory.py \
  --max-pages 110 --max-details 1093 --delay 0.45

# Check a deliberately bounded batch of public official websites.
python3 scripts/update_aacsb_directory.py \
  --max-pages 10 --max-records 100 --max-details 100 \
  --scan-websites --max-schools 25 --site-max-pages 4 --delay 0.75 --timeout 20

# Resume site checks without refetching AACSB pagination; unchecked rows only.
python3 scripts/update_aacsb_directory.py \
  --scan-existing --max-schools 25 --site-max-pages 4 --delay 0.75 --timeout 20
```

Website results are recorded as `jobs_found`, `no_current_jobs`, `not_found`, `not_checked`, `blocked`, `robots_disallowed`, or `unknown`. A blocked or inaccessible page is never treated as evidence that a school has no vacancy. The scanner uses public pages only, a small page budget, timeouts/backoff, and bounded excerpts; it honours robots.txt and does not bypass login, CAPTCHA, Cloudflare, or anti-bot controls. When robots.txt refuses part of a site, the scan is reported as `unknown` rather than `no_current_jobs`, because the site was not fully read. Synthetic AACSB fixtures in `tests/fixtures/faculty_jobs/` test parsing without internet access; they are not live-source evidence.

## Verification

```bash
python3 -m py_compile server.py services/faculty_jobs*.py services/faculty_jobs_sources/*.py
python3 -m unittest tests.test_faculty_jobs_normalizer tests.test_faculty_jobs_schema tests.test_faculty_jobs_security tests.test_faculty_jobs_p2 tests.test_faculty_jobs_robots -q
python3 scripts/audit_projects.py
```

The live update command is intentionally bounded and writes only the private database:

```bash
python3 -c "from services.faculty_jobs_service import update_faculty_jobs; print(update_faculty_jobs(timeout=20, max_pages=1))"
```

For an explicit full public Inside Higher Ed search refresh, use the exact
numbered-page budget rather than relying on the scheduler's one-page default:

```bash
python3 scripts/update_faculty_jobs.py \
  --source inside_higher_ed --max-pages 42 --timeout 20
```

Use `FACULTY_JOBS_AUTO_UPDATE=0` during read-only/browser tests. The server scheduler defaults to one low-frequency refresh every 24 hours, with `FACULTY_JOBS_UPDATE_HOURS`, `FACULTY_JOBS_HTTP_TIMEOUT`, and `FACULTY_JOBS_MAX_PAGES_PER_SOURCE` available for explicit configuration. The current local snapshot has eight source-coverage observations across two calendar dates; Analytics permits a cautious comparison but still labels the result as source coverage rather than a longitudinal market trend.

## Historical verified snapshot (2026-08-24 Mountain / 2026-08-25 UTC; superseded below)

The production default is now a current, role-eligible business-faculty view: 189 active records, comprising 110 `business_school` and 79 `business_discipline` records; 144 are in the United States. The broader accepted boundary contains 197 records, including one closed posting and seven stale/insufficiently current records now labeled `unknown`. `scope=all` retains all 1,198 canonical records for audit. The screenshot false positives—graduate assistant, federal work study, computer-science chair, cosmetology instructor, and radiopharmaceutical roles—remain source-linked but no longer enter the default market.

The public AACSB endpoint reported and returned 1,093 results. Only 1,054 `/accredited/` records enter the roster; 39 non-accredited educational-member insertions are recorded as excluded. The roster contains 881 named school-unit records and 173 organization-level records, with 1,053 official websites exposed. Legacy website observations remain visible, but only 25 sites have been checked under `faculty_market_v2_20260824`; 1,028 websites remain stale or unchecked under the current rule. That current batch saw 104 candidate links/JobPosting objects, rejected 98, and extracted five eligible postings from two schools. The job source retains 219 source records/links, including 23 accepted jobs and 194 quarantined derived records.

Migrations through v38 repair role/business boundaries, IHE posting-level school evidence, duplicate school labels, stale/past status, stale-process writeback, and the `Washington D.C. → WA` location error. The production database retains 1,200 source records, 1,200 source links, and the existing private saved state; `PRAGMA quick_check=ok` and `foreign_key_check` returns zero rows. Missing evidence stays explicit: among the 189 active default records, 165 lack a fixed deadline, 150 lack an official application URL, six lack an institution, and 82 have no linked school entity.

The AACSB website scan is resumable and opt-in; this historical section predates migrations 39–40 and the later bounded batches. The current 2026-08-25 values are in the source-expansion section below; the snapshot is not a census of all US or global vacancies. See [the final precision audit](../../docs/academic_career_faculty_market_AUDIT_2026-08-24.md) for the earlier root-cause record.

## 2026-08-25 source expansion follow-up (latest)

The latest production snapshot adds seven bounded public adapters: Chronicle Business / Management, AAA Career Center, POMS, Decision Sciences Institute, Strategic Management Society, AcademicJobsOnline, and AKADEUS. Their bounded runs retain 21, 20, 119, 10, 22, 40, and 71 source records respectively. After migrations 42–49, the current default business-faculty view is 359 active records (202 explicit `business_school`, 157 `business_discipline`), with 56 unresolved possible-duplicate candidates in the view; these figures are observed source coverage, not a complete market estimate. Current coverage is posted date 84.7%, deadline/rolling 13.9%, official application URL 18.1%, parsed salary 17.8%, location 94.2%, PhD evidence 0.6%, visa evidence 0.6%, and start term/year 12.8%. The machine-readable audit is [academic_career_source_expansion_audit_20260825.json](../../outputs/academic_career_source_expansion_audit_20260825.json), and the full source matrix is [academic_career_source_expansion_AUDIT_2026-08-25.md](../../docs/academic_career_source_expansion_AUDIT_2026-08-25.md).

The new adapters keep board listing URLs separate from official application URLs. POMS remains honest about its public table's missing locations, Chronicle remains honest about cards without posted dates, AJO remains broad and downstream-gated, and DSI records a direct target URL only when the public table exposes one. AOM, AACSB Career Connection, AMA, FMA, INFORMS, HigherEdJobs, HERC, and EFMD remain manual/blocked catalog entries under the no-bypass boundary.

Migrations 39 and 41–49 replay the expanded IHE detail-school, institution, country, campus/location, and deadline parsers over preserved bounded excerpts. The reported Ohio State posting now derives `Ohio State University`, `Fisher College of Business`, `business_school`, and `structured_posting`; the Lebanese American University posting retains its correct institution/country and remains `business_discipline` because its stored excerpt does not establish a posting-level school entity. The parser now removes IHE card phrases such as `Augusta University Full/Part Time` and `University System of Georgia` from city fields, while leaving unsupported cities Unknown. Migration 42 also repaired explicit fixed deadlines that had been overridden by `Open Until Filled: No`; source records, field provenance, status history, AACSB evidence, and private state remain source-record-first and intact. Production `quick_check=ok`, foreign-key violations=0, source records/links=1,509/1,509, and long deadline evidence snippets=0.

The AACSB roster remains separate from hiring evidence: 1,054 directory rows, 1,053 exposed official websites, 475 current-rule checks, and 578 stale/unchecked sites. The latest 100-school check saw 1,136 candidates, rejected all 1,136, added or updated no job records, and recorded no errors. A full remaining-site scan is intentionally not part of the daily scheduler and requires explicit bounded batches; it is not complete. `source_jobboards.py` and `tests/test_faculty_jobs_source_expansion.py` contain the adapters and synthetic parser contracts; no raw third-party HTML is stored.
