# Academic Career / Faculty Job Market status — 2026-08-23

## Historical 2026-08-24/25 final precision audit (superseded by the 2026-08-25 source-expansion addendum below)

The current production view supersedes every count below this section. The default market contains 189 active, role-eligible business postings: 110 with explicit posting-level business-school evidence and 79 with business-discipline evidence; 144 are in the United States. The accepted boundary contains 197 records when one closed and seven stale/insufficiently current records are included. The explicit audit catalogue remains 1,198 canonical jobs. Graduate assistants, federal work study, staff roles, and non-business academic fields remain source-linked in `scope=all` but are excluded from the default.

The AACSB public endpoint reconciliation is 1,093 reported/observed results = 1,054 `/accredited/` roster records + 39 explicitly non-accredited member insertions. The roster consists of 881 named school-unit records and 173 organization-level records; 1,053 records expose an official website. Only 25 websites have been checked under the current rule `faculty_market_v2_20260824`; 1,028 remain stale or unchecked. The current batch saw 104 candidates, rejected 98, and extracted five eligible postings from two schools. Legacy scan outcomes remain visible as `Recheck required` and are not counted as current-rule checks.

The production database is migrated through v38. It retains 1,198 jobs, 1,200 source records, 1,200 source links, and one private saved state; `PRAGMA quick_check=ok` and `foreign_key_check` returns no rows. The latest location replay corrected exactly two `Washington D.C., WA` records to `DC` without changing any source grain. The final Academic Career regression ran 93 tests successfully, JavaScript and Python syntax checks passed, and the six-project boundary audit returned zero errors/warnings. Real-browser checks covered desktop and 375px Faculty Jobs and School Explorer with zero console errors; the United States filter rendered 144 records and the audit view showed GA records with explicit exclusion labels.

The complete root-cause analysis, migration notes, backup paths, screenshots, and remaining limitations are in [`academic_career_faculty_market_AUDIT_2026-08-24.md`](academic_career_faculty_market_AUDIT_2026-08-24.md). The full repository suite has one unrelated, reproducible Fiscal setup error because WSL cannot read the active 1.04GB `pboc_data.db`/WAL (`sqlite3.OperationalError: disk I/O error`); that database was not modified during this work.

## Historical 2026-08-24/25 IHE/AACSB snapshot (superseded)

This entire section records the earlier v32 snapshot. It is retained for audit history and must not be read as the current counts or current-rule AACSB website coverage.

### AACSB roster and official-site hiring scan

The official [AACSB Accredited School Directory](https://www.aacsb.edu/accredited) reported 1,093 results on the run date. The bounded parser accepted 1,054 `/accredited/` roster records, fetched 1,054 detail pages, obtained 1,053 official websites, and checked all 1,053 public official websites. The latest per-school scan found 68 raw postings across 29 schools. After the explicit individual-faculty and business-scope gate plus v32 precision replay, the database retains 219 AACSB source records/links representing 23 accepted canonical jobs/source identities and 194 quarantined canonical records. The quarantine retains source records, provenance, source links, and status history; it is not deletion. The stricter count supersedes the pre-gate 66/151 and intermediate 29/188 counts. The 39-result difference between the directory's reported total and parseable accredited-path records remains an explicit endpoint-reconciliation limitation, not silently treated as imported schools.

The persisted latest per-school scan ledger currently has 1,053 checked rows: 800 `ok`, 166 bounded request errors, and 87 blocked/access outcomes. Its latest job-scan statuses are 28 `jobs_found`, 646 `no_current_jobs`, 13 `no_eligible_business_faculty_jobs`, 106 `not_found`, 258 `unknown`, and 2 `blocked`, representing 67 raw postings in the latest per-school rows. The earlier run-level observation of 68 raw postings across 29 schools is retained as historical scan evidence. A blocked, inaccessible, or not-found page is not evidence that the school has no vacancy. The scan used public pages, a maximum of four discovered public career entries per school, timeout/backoff, and no login, CAPTCHA, Cloudflare, or anti-bot bypass.

The latest accepted AACSB source identities are restricted to public posting-level academic evidence; ordinary faculty directories, dean/research pages, policy pages, and explicit non-business postings remain quarantined. The default market/API excludes `derived_quality='quarantined'`; `scope=all` retains the complete audit catalogue. AACSB roster accreditation remains evidence of accreditation only, not evidence of a vacancy or a research tier.

### Inside Higher Ed complete public search capture

The user-supplied public search `https://careers.insidehighered.com/jobs/3/?keywords=assistant+professor+business` reports 838 matches and 42 numbered pages. The full bounded run fetched all 42 pages, observed 880 listing cards, and retained 836 unique parseable job cards. The production source-record grain now contains 849 Inside Higher Ed records/active links because 13 earlier source identities remain preserved for audit while the new search result set was reconciled. The default business scope, not the collector, excludes non-business and non-academic matches.

Listing capture is complete for the public result set observed on that run; detail-field coverage is still evidence-limited, not claimed complete for every possible field. The explicit bounded detail enrichment processed all 849 preserved IHE source records successfully (run 65: 849 updated, 0 errors), followed by targeted replays for the two user-supplied URLs and related records (runs 66 and 68: 7 updated, 0 errors). Current IHE active-link coverage is institution 100.0%, location 100.0%, posted date 100.0%, deadline/rolling 13.2%, parsed salary 16.7%, official application URL 10.1%, rank 100.0%, visa evidence 0.7%, and start term/year 7.7%. Four country/location-code repairs and school-link replays are recorded in the repair audit; missing city or application evidence remains Unknown. Listing URLs are not relabeled as official application URLs.

### Current production database after recovery

The production database was modified incrementally after consistent SQLite backups, including `data/backups/academic_career_20260824_pre_ihe_full_pagination/`, `data/backups/academic_career_20260824_pre_aacsb_parser_rescan/`, `data/backups/academic_career_20260824_pre_ihe_complete_source_import/`, `data/backups/academic_career_20260824_pre_ihe_detail_enrichment/`, and the latest pre/post school-boundary backups at `data/backups/academic_career_20260824_pre_ihe_school_boundary_repair/`, `data/backups/academic_career_20260824_post_ihe_school_boundary_repair/`, `data/backups/academic_career_20260824_post_ihe_school_boundary_repair_checkpoint/`, and `data/backups/academic_career_20260824_post_ihe_scope_boundary_v32/`; the earlier corrupt DB/WAL/SHM snapshot remains preserved at `data/backups/academic_career_20260824_post_aacsb_corrupt_snapshot/`. The final database reports `PRAGMA journal_mode=wal`, `quick_check=ok`, and zero foreign-key violations. No source records or private application state were deleted.

| Metric | Current value |
|---|---:|
| Canonical jobs | 1,198 |
| Source records | 1,200 |
| Job-source links | 1,200 |
| All retained institutions / business-school entities | 1,221 / 1,057 |
| Active institution / business-school entities | 1,150 / 999 |
| School-evidence rows | 939 |
| Job provenance / status-history rows | 45,753 / 8,336 |
| Unresolved possible duplicates | 331 |
| AACSB roster / scan-history rows | 1,054 / 2,360 |
| Application events / private saved state rows | 0 / 1 |

The default accepted business view contains 202 jobs: 159 `business_school` and 43 `business_discipline`. Its recomputed coverage is: posted date 82.7%, deadline or rolling 19.3%, official application URL 19.3%, parsed salary 26.2% (raw salary text 53.5%), linked school entity 77.7%, evidence-backed school row 40.1%, classified tier 39.1%, PhD evidence 0.5%, visa evidence 0.5%, current provenance rows 99.5%, and status history 100.0%. `scope=all` contains all 1,198 canonical records, including quarantined and non-business audit rows.

Source field coverage is calculated over active source links, not distinct canonical jobs:

| Source | n | Institution | Location | Posted | Deadline/rolling | Salary | Official URL | Rank | Visa | Start |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AIS | 29 | 72.4% | 100.0% | 41.4% | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| University Affairs | 60 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| jobs.ac.uk | 23 | 100.0% | 100.0% | 100.0% | 100.0% | 91.3% | 0.0% | 100.0% | 0.0% | 0.0% |
| EURAXESS | 9 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 33.3% | 100.0% | 11.1% | 0.0% |
| Inside Higher Ed | 849 | 100.0% | 100.0% | 100.0% | 13.2% | 16.7% | 10.1% | 100.0% | 0.7% | 7.7% |
| AACSB official sites | 219 | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 98.6% | 100.0% | 0.0% | 2.7% |

There are 331 unresolved review-only duplicate candidates; they remain review metadata rather than automatic merges. All pre-expansion source identities remain, and no private application state was deleted. After the v30/v31/v32 forward repairs were applied, two consecutive `ensure_faculty_jobs_tables()` calls left the current derived counts unchanged (45,753 provenance rows and 8,336 history rows); migrations 1–32 do not change source identity counts. Migration 29 specifically replays preserved IHE `structured_extraction.school_raw` before the faculty-market boundary pass, so a valid posting-level school cannot be cleared by a later roster-boundary repair. Migration 32 applies the expanded non-business/ambiguous-management gate as a derived-only precision correction.

### Analytics and evidence boundary

There are eight source-coverage-history observations across two dates. Analytics labels these as observed public-source coverage and warns that source expansion can raise counts without implying market growth; it is not a longitudinal labor-market trend. University research level and business-school tier remain separate: active institutions and schools retain Unknown/Unclassified where evidence is insufficient, Carnegie evidence is not claimed, and AACSB is not treated as a formal research ranking.

The public source catalogue has five enabled sources with successful latest runs: AIS, University Affairs, jobs.ac.uk, EURAXESS, and Inside Higher Ed. The AIS repair added bounded relative-date parsing (`N days/weeks ago`) and its one-page live refresh completed successfully. AACSB official-site scanning remains opt-in and disabled in the default daily scheduler. AOM remains manual/degraded because its public category is dynamically rendered; HigherEdJobs remains manual because the public audit observed an anti-bot challenge. These limitations are recorded rather than filled with inferred vacancies.

### Verification results

- `py_compile` for `server.py`, the Academic Career services, and all faculty-job source adapters: passed.
- Targeted Academic Career suite: 87 tests passed, including the IHE structured-school migration regression.
- Full suite: 779 tests passed. The earlier fiscal `disk I/O error` was not reproduced in this run; the fiscal DB was not modified. A bounded read-only `quick_check` against the 1.04 GB root `pboc_data.db` did not finish within the diagnostic timeout, while the fiscal payload contract itself passed and the isolated temporary-DB diagnostic also passed.
- `scripts/audit_projects.py`: passed, 6 projects, 0 errors, 0 warnings.
- `scripts/audit_one_plus_five.py`: compatibility wrapper passed with the same result.
- Real HTTP smoke: `/api/health`, all four Academic Career pages, filtered job/summary/analytics/AACSB APIs, and existing macro/ABDC page routes returned successfully using an isolated temporary fiscal DB.
- Real HTTP privacy check with trusted proxy headers enabled: public jobs remained readable, while `/api/my-applications` and `/api/faculty-jobs/profile` returned 403 for a simulated non-loopback client.
- Final v32 browser checks covered desktop 1280px and 375px for `/faculty-jobs`, `/school-explorer`, `/job-market-analytics`, and `/my-applications`; country display-name filtering, region-summary synchronization (Europe 13/13 and Canada 8/8), detail dialogs for both reported IHE URLs, CSV query propagation, school compare, console errors, and page horizontal overflow were checked. Console errors/warnings were zero and all four pages had `scrollWidth == innerWidth` at 375px.

## Delivery

The new domain is implemented inside the existing `server.py` + static-page + SQLite architecture. It adds four routes: `/faculty-jobs`, `/school-explorer`, `/job-market-analytics`, and `/my-applications`.

## 2026-08-24 P2 continuation

The historical 2026-08-23 snapshot above is preserved. A follow-up implementation added schema migrations 14–15 and the following local-only workflows:

- Saved searches store a bounded normalized query and create an idempotent local alert inbox. They do not send email or call an external alert service.
- Possible duplicates have auditable `resolution`, `resolved_at`, `resolution_reason`, and `merged_into_job_id` fields. Fuzzy candidates remain separate; reject/mark-distinct is human-recorded, while merge is accepted only for the same mergeable official application URL and is refused when both records have independent private state.
- Institution aliases have a private list/write API and School Explorer ledger. Alias decisions affect future conservative normalization only; source records and raw excerpts are retained.
- Source Health now reports field coverage for title, institution, location, posted date, deadline/rolling, salary, official URL, rank, PhD, visa, and start term/year. Analytics adds discipline-level observed field coverage and labels it as source coverage, not market strength.

Before the first v14 write, the database was checked read-only (`quick_check=ok`, no foreign-key violations) and backed up through SQLite's backup API at `data/backups/academic_career_20260824_pre_p2/faculty_jobs.db`; no WAL/SHM sidecars existed at backup time. Before the v15 Inside Higher Ed replay, a second consistent backup was created at `data/backups/academic_career_20260824_pre_ihe_location_replay/faculty_jobs.db`. After both migrations, the real database again reports `quick_check=ok` and no foreign-key violations. The current read-only counts on 2026-08-24 are 148 jobs, 148 source records, 148 source links, 7 catalogued sources, 24 ingestion runs, 103 current institutions, 17 current school entities, 15 school-evidence rows, 14,987 provenance rows, 2,512 status-history rows, 15 unresolved possible-duplicate rows, 2 source-coverage observations, and zero saved searches, alerts, or institution aliases.

Current all-observed coverage is official application URL 4.7% (7/148), deadline or rolling evidence 29.1% (43/148), salary 16.9% (25/148), linked school entity 12.2% (18/148), school evidence 4.1% (6/148), classified business tier 1.4% (2/148), and status history 100% (148/148). The default 34-job business view is 0.0%, 44.1%, 52.9%, 52.9%, 17.6%, 5.9%, and 100.0% respectively; the strict 18-job explicit-school view is 0.0%, 66.7%, 77.8%, 100.0%, 33.3%, 11.1%, and 100.0%. These percentages are recomputed from the current database and do not treat listing URLs as official application URLs.

The current source-field coverage API reports percentages over each source's active records:

| Source | n | Institution | Location | Posted | Deadline/rolling | Salary | Official URL | Rank | Visa | Start |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---:|---:|
| AIS | 25 | 84.0% | 100.0% | 0.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| University Affairs | 60 | 100.0% | 100.0% | 100.0% | 0.0% | 0.0% | 0.0% | 100.0% | 0.0% | 0.0% |
| jobs.ac.uk | 24 | 100.0% | 100.0% | 100.0% | 100.0% | 91.7% | 0.0% | 100.0% | 0.0% | 0.0% |
| EURAXESS | 19 | 100.0% | 100.0% | 100.0% | 100.0% | 0.0% | 36.8% | 100.0% | 5.3% | 0.0% |
| Inside Higher Ed | 20 | 100.0% | 100.0% | 0.0% | 0.0% | 15.0% | 0.0% | 100.0% | 0.0% | 5.0% |

University Affairs, jobs.ac.uk, EURAXESS, and Inside Higher Ed have successful latest runs. AIS has a prior successful run and 25 preserved active records, but its latest attempt is recorded as an error (`maximum recursion depth exceeded`); it is not counted as a latest success. AOM and HigherEdJobs remain manual/unsupported.

## Post-repair snapshot

The source-record-first repair is now applied through idempotent migrations 1–13. The current SQLite store has 138 canonical jobs, 138 `source_job_records`, and 138 `job_sources`; all source records from the pre-repair snapshot remain present. `PRAGMA quick_check` returns `ok` and `PRAGMA foreign_key_check` returns no rows. Migration 13 also handles a legacy replay that already created the Leeds official target by repointing job links and retaining the old label as an inactive audit row. The five enabled public adapters have successful latest runs; AOM and HigherEdJobs remain manual/unsupported under the no-bypass boundary.

The public default currently contains 34 business-scope jobs: 18 `business_school` records based on explicit business-school evidence and 16 `business_discipline` records. The active directory has 16 linked school entities and 15 school-evidence rows. Seven job records have a school with an official-page evidence ledger entry; three job records have a transparent evidence-backed tier (one T2, one T3, one T4), while the remaining school tiers stay `Unclassified`. University research level remains `Unknown` because no official university-level classification has been added.

Current all-observed coverage (138 jobs) is: official application URL 2.9%, deadline or rolling evidence 23.9%, salary 18.1%, evidence-backed school classification 2.2%, and 15 unresolved possible-duplicate review rows. On the default 34-job business view the corresponding values are 0.0%, 44.1%, 52.9%, 8.8%, and 2. The strict 18-job explicit-school view has 66.7% deadline evidence, 77.8% salary evidence, and 16.7% evidence-backed tier classification. Generic Galaxie recruitment portals are preserved as source-record values but are not counted as job-specific official application URLs. Percentages are recomputed from the current database, not inherited from the pre-repair snapshot.

The public layer has seven catalogued sources. Five are currently enabled for low-frequency public HTML collection: AIS (US), University Affairs (Canada), jobs.ac.uk (UK/Europe), EURAXESS (Europe), and Inside Higher Ed Careers (US). AOM is catalogued as manual because its current category listing is dynamically rendered; HigherEdJobs is catalogued as manual because the public audit observed an anti-bot challenge. The implementation does not use authentication, CAPTCHA solving, private endpoints, or anti-bot bypasses.

## Evidence observed in the 2026-08-23 smoke update

Using the private `data/faculty_jobs.db` store, bounded live updates returned successful adapter runs for AIS (25), University Affairs (60), jobs.ac.uk (23), EURAXESS (10), and Inside Higher Ed Careers (20). After source-record-first repair, the current snapshot contains 138 canonical jobs, including separate records for previously merged same-source postings. The adapters run independently and record each result in `sources` and `ingestion_runs`; one source failure does not delete earlier rows. The repair also corrected the confirmed state/country, city-label, institution/location, and deadline-derived-field errors, including `Stanford, CA` as United States, `Dublin` as Ireland, and `Auckland`, `Dhaka`, and `KAUST` country evidence.

This smoke output is a validation artifact, not a committed catalogue. The repository intentionally does not store `data/faculty_jobs.db`, source HTML, private profile contents, or application notes.

The database has one source-coverage-history observation, so Analytics explicitly reports insufficient history and does not present a longitudinal trend. These coverage metrics describe enabled-source observations, not estimates of the whole academic labor market.

## Data semantics

- `jobs` retains normalized fields plus bounded description excerpts, source URLs, source-job IDs, field provenance, status history, and evidence-sensitive unknown values.
- Deduplication uses source identity first, then a mergeable normalized official URL, and only complete compatible fingerprints. Similarity candidates are retained as `possible_duplicates` with `fuzzy_review_only`; they are not silently merged.
- A source record becomes inactive only after three successful missing runs for that source. An adapter error does not count as a successful missing run.
- Country/region, discipline, rank, career stage, track, visa evidence, salary, PhD evidence, deadline mode, and hiring cycle are separate fields. A UK/European local rank is not renamed as a US rank.
- University research level and business-school research tier are separate tables/fields. A school is `Unclassified` until explicit evidence or a logged manual override is present.
- Private fit scoring is deterministic, weighted, and explainable. It is omitted from public payloads and requires loopback access by default.

## Remaining limitations and next work

1. Official application URLs are still sparse for listing-only sources; users should verify the source page before applying.
2. EURAXESS is broad European research coverage, not a complete business-school catalogue. University Affairs and AIS are useful domain sources but are not exhaustive national inventories.
3. Discipline and location normalization are rule-based. Unknown and Other categories are expected and should be reviewed before substantive market claims.
4. School evidence enrichment is intentionally bounded: a small set of official-page entries is stored locally, while unsupported global rankings and automatic school-tier claims remain excluded. Unknown/Unclassified is still expected for the remaining entities.
5. The next high-value extension is source-specific detail enrichment for adapters whose public listing cards expose only partial evidence, followed by repeated low-frequency live updates so `source_coverage_history` can support a cautious comparison over time.

## 2026-08-24 AACSB expansion (implementation and live smoke boundary)

An opt-in AACSB expansion was added without changing the default daily source scheduler. The public AACSB accredited-school directory is stored separately from job records in `aacsb_directory_schools`, with `aacsb_scan_history` and `aacsb_scan_runs` for auditable detail/site-check status. The `aacsb_official` source row is intentionally disabled in the default scheduler because a full roster detail refresh and multi-domain official-site scan require explicit budgets.

The official public roster endpoint currently reports 1,093 results; the parser accepts only `/accredited/` detail paths and excludes membership-only/sponsored insertions. Each detail row preserves the AACSB directory URL, official website when exposed, accreditation scope, bounded excerpt, country/location evidence, and last-check state. AACSB evidence means accreditation only; it is not a hiring or research-tier claim.

A temporary isolated-database smoke run on 2026-08-24 imported three roster records and three detail pages, checked two official websites, and found one explicit public academic posting. One website was accessible but had no discoverable faculty entry; the third remained `not_checked`. This smoke run did not touch `data/faculty_jobs.db`. Synthetic parser tests cover directory filtering, detail accreditation/website extraction, official JobPosting JSON-LD, no-current-job semantics, and migration idempotence.

The production full-roster import and website scan must be reported below only after a SQLite backup and post-write `quick_check`/`foreign_key_check`. Official-site results will be reported as observed public-page outcomes, not as a complete vacancy census.

The first operator-interrupted official-site batch exposed an important parser boundary: ordinary `Faculty & Staff`, directory, research, policy, and dean pages were not job postings. Those 138 preserved AACSB source records were quarantined in the derived layer (`derived_quality=quarantined`, `business_scope=unknown`, current status `unknown`) with repair-audit rows; source records, provenance, source links, and status history remain intact. Migration 17 makes this quarantine persistent across table initialization. A later rule-checked replay of 68 schools restored only five explicit business academic postings; the remaining accepted-looking rows were not restored. The resumable CLI is `scripts/update_aacsb_directory.py --scan-existing --max-schools N`, and unvisited schools remain `not_checked`.

## Verification commands

```bash
python3 -m py_compile server.py services/faculty_jobs*.py services/faculty_jobs_sources/*.py
python3 -m unittest discover -s tests -q
python3 scripts/audit_projects.py
```

Browser acceptance should run with `FACULTY_JOBS_AUTO_UPDATE=0`, `PBOC_AUTO=0`, `ASTAR_AUTO=0`, `FISCAL_AUTO=0`, `RATES_AUTO=0`, and `RESEARCH_INDEX_AUTO=0` so page QA cannot start unrelated network jobs.

The 2026-08-23 browser pass covered the desktop Faculty Jobs page and all four domain pages at a 375px viewport. The detail dialog exposed field-level evidence, source provenance, and the local-only save action; School Explorer, Analytics, and My Applications rendered without horizontal content clipping in the page body. The shared navigation intentionally remains horizontally scrollable on narrow screens so all six project domains remain reachable.

## 2026-08-25 source expansion and IHE school replay

This dated addendum supersedes the older snapshot numbers above; historical sections are preserved for audit. Seven public, bounded adapters were added and successfully run once: Chronicle Business / Management (21 records), AAA Career Center (20), POMS (119), Decision Sciences Institute (10), Strategic Management Society (22), AcademicJobsOnline (40 bounded detail records), and AKADEUS (69). The source-specific audit matrix and machine-readable metrics are [academic_career_source_expansion_AUDIT_2026-08-25.md](academic_career_source_expansion_AUDIT_2026-08-25.md) and [academic_career_source_expansion_audit_20260825.json](../outputs/academic_career_source_expansion_audit_20260825.json).

The production database now contains 1,502 canonical jobs, 1,507 preserved source records, 1,507 active source links, 48,377 field-provenance rows, 8,879 status-history rows, 381 unresolved review-only duplicate candidates, 1,054 AACSB roster rows, and 2,385 AACSB scan-history rows. It has 1,386 total / 1,316 current institutions and 1,098 total / 941 current business-school entities, with 939 school-evidence rows. The private `user_job_state` count remains 1 and `application_events` remains 0. `PRAGMA quick_check` is `ok`; `PRAGMA foreign_key_check` returns zero rows; migration 40 is applied.

The current default business view is 340 records: 183 explicit `business_school` and 157 `business_discipline`, with 51 unresolved possible-duplicate candidates in the view. Recomputed coverage is posted date 82.1%, deadline or rolling 9.1%, official application URL 13.8%, parsed salary 16.8%, location 83.5%, PhD evidence 0.3%, visa evidence 0.3%, status history 100%, and current provenance 100%. The values are observed public-source coverage, not a complete US/global job-market estimate and not a longitudinal trend.

The AACSB roster remains a target list, not hiring evidence. The latest current-rule batch checked 25 schools with `--site-max-pages 4`, saw 184 candidates, rejected all 184 under the strict individual faculty/business evidence gate, and had 0 errors. Across the roster, current statuses are 26 `jobs_found`, 619 `no_current_jobs`, 42 `no_eligible_business_faculty_jobs`, 106 `not_found`, 258 `unknown`, 2 `blocked`, and 1 `not_checked`; 978 official websites remain stale/unchecked under the current rule. The scan is resumable but the remaining full scan was not started without an explicit bounded-batch authorization.

Migration 39 replays the expanded IHE parser over stored bounded excerpts. The Ohio State posting `3534806` now has institution `Ohio State University`, school `Fisher College of Business`, scope `business_school`, and context `structured_posting`; the Lebanese American University posting `3226393` has the correct institution and Lebanon location but remains `business_discipline` because no posting-level school entity is established by the stored evidence. Migration 40 removes observed portal prefixes from derived school labels while preserving inactive audit entities and source text.

Before each production write in this addendum, a new SQLite online-backup file was created without overwriting prior backups. The source and backup passed quick-check/foreign-key checks before the write; the production database passed them again afterward. No source record, provenance/history row, AACSB roster row, or private state was deleted. No raw third-party page was added to Git.

### Final verification addendum (2026-08-25)

The `/api/schools` timeout found during browser QA was fixed in `services/faculty_jobs_school_service.py` by aggregating eligible business-faculty jobs once and joining the result to current school entities. The default, GB, and Europe school API requests now return in about 0.26–0.33 seconds. Desktop and 375px browser checks of all four Academic Career pages passed with zero console errors and no main-page horizontal overflow; country filtering, region-summary synchronization, job detail, CSV URL, school comparison, analytics scope/history, and private application UI were exercised.

HTTP privacy verification with a simulated Cloudflare remote IP returned public jobs without private fields and returned 403 `academic_career_local_only` for private profile, application, and CSV routes. The current targeted Academic Career groups passed 108 tests; project audits passed (`projects=6 errors=0 warnings=0`). The full repository run is 801 tests with one unrelated fiscal `pboc_data.db` disk-I/O error; an isolated temporary fiscal database passed its smoke checks and the real fiscal database was not touched.

### Current repair addendum (2026-08-25 08:30 UTC; supersedes prior current-count paragraphs)

The production database is now migrated through v49. It contains 1,506 canonical jobs, 1,509 preserved source records, 1,509 active source links, 124,004 provenance rows, 20,086 status-history rows, 381 unresolved review-only duplicate candidates, 1,603 total / 1,193 current institutions, 1,196 total / 992 current business-school entities, and 939 school-evidence rows. The private `user_job_state` count remains 1 and `application_events` remains 0. `PRAGMA quick_check=ok`, foreign-key violations=0, and deadline evidence snippets longer than 300 characters=0.

The current default business view contains 359 active records: 202 `business_school` and 157 `business_discipline`; 56 unresolved possible-duplicate candidates remain in this view. Recomputed coverage is posted date 84.7%, deadline/rolling 13.9%, official application URL 18.1%, parsed salary 17.8%, location 94.2%, PhD evidence 0.6%, visa evidence 0.6%, start term/year 12.8%, status history 100%, and current provenance 100%. These are bounded source observations, not a complete market estimate or longitudinal trend.

Migration 42 replayed all derived fields from preserved source records after the deadline parser fix. It now distinguishes an explicit fixed deadline from `Open Until Filled: No`, keeps positive rolling/open-until-filled modes, and never uses an unrelated posting/date-placed token as a deadline. Migrations 43–49 repaired punctuation-delimited IHE employers/campuses, institution-country reuse, and narrative card text in city fields. For the user-supplied IHE records, job `3534806` is `Ohio State University / Columbus, OH / Fisher College of Business`, and job `3226393` is `Lebanese American University / Beirut and Byblos, Lebanon / open_until_filled`; IHE active records now have zero Unknown institutions, zero missing countries, and zero city values containing university narrative.

AACSB official-site scanning has progressed to 475 of 1,053 public official websites under `faculty_market_v2_20260824`; 578 remain stale or unchecked. The latest 100-school batch observed 1,136 candidate links, rejected all 1,136, added or updated no job records, and recorded 0 errors. Across all persisted roster observations, status counts are 20 `jobs_found`, 426 `no_current_jobs`, 242 `no_eligible_business_faculty_jobs`, 106 `not_found`, 257 `unknown`, 2 `blocked`, and 1 `not_checked`; among the 475 current-rule checks, they are 4, 47, 242, 55, and 127 respectively. This is meaningful progress but not a completed AACSB-wide vacancy scan.

New production backups include `pre_deadline_repair_v42`, `pre_ihe_location_chrome_repair_v48`, `pre_aacsb_batch4`, `pre_aacsb_batch5`, and `pre_aacsb_batch6` under `data/backups/`; each passed quick-check and foreign-key validation before use. No source records, private state, or raw third-party pages were deleted or added to Git. The source-expansion audit and JSON contain the current machine-readable metrics.
