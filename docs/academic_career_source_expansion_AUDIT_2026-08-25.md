# Academic Career source-expansion audit — 2026-08-25 UTC

This is an observed public-source snapshot, not a census of the academic labor market. The audit used public listing/detail pages with bounded requests, timeouts, and backoff. It did not submit login forms, solve CAPTCHA/Cloudflare challenges, call private APIs, or retain raw third-party pages. Robots/terms were not treated as implicit permission: each enabled adapter remains a low-frequency public-HTML collector and should be rechecked if a source publishes a restrictive automated-access rule.

## Production result

The source expansion was implemented inside the existing `HTTPServer` + services + SQLite architecture. The seven newly enabled adapters were run on one bounded page/detail budget on 2026-08-25 UTC:

| Source | Public endpoint | Pages/details | Observed source records | Faculty-role eligible | Accepted business-scope links | Current default contribution | Latest run |
|---|---|---:|---:|---:|---:|---:|---|
| Chronicle Business / Management | [jobs.chronicle.com/jobs/business-and-management](https://jobs.chronicle.com/jobs/business-and-management/) | 1 page | 21 | 12 | 12 | 12 | success |
| AAA Career Center | [careercenter.aaahq.org/jobs](https://careercenter.aaahq.org/jobs) | 1 page + bounded detail budget | 20 | 18 | 17 | 17 | success |
| POMS | [poms.org/opportunities](https://www.poms.org/opportunities) | 1 page | 119 | 109 | 76 | 64 | success |
| Decision Sciences Institute | [decisionsciences.org/professional-growth/open-positions](https://decisionsciences.org/professional-growth/open-positions/) | 1 page | 10 | 10 | 9 | 9 | success |
| Strategic Management Society | [sms.careerwebsite.com/jobs](https://sms.careerwebsite.com/jobs) | 1 page + bounded detail budget | 22 | 20 | 19 | 19 | success |
| AcademicJobsOnline | [academicjobsonline.org/ajo/jobs](https://academicjobsonline.org/ajo/jobs) | 1 listing + 40 public details | 40 | 34 | 4 | 4 | success |
| AKADEUS | [akadeus.com/announcements](https://akadeus.com/announcements) | 1 page + bounded detail budget | 71 | 51 | 39 | 39 | success |

The accepted-business column is a source-link metric and may overlap across sources after exact-URL/fingerprint deduplication. The default contribution is the current public default (`accepted`, eligible faculty role, business discipline/school, and `open`/`likely_open`/`closing_soon` status), so old POMS announcements and stale broad-board records are not presented as current openings.

## Source-by-source audit matrix

| Source ID | Coverage / focus | Public access observed | Fields observed | Pagination / limits | Precision and risk | Final state |
|---|---|---|---|---|---|---|
| `chronicle_business` | Global; business and management category | HTTP 200 public HTML; listing cards expose title, employer, location, salary, excerpt | title, institution, location, salary, source job URL; no posted date on the observed cards; no official application URL | `Next` link; run limited to 1 page / 100 adapter cap | 12/21 faculty-role eligible; broad category can include non-faculty and non-business records; no deadline evidence on cards | enabled |
| `aaa_career_center` | Global accounting education faculty | HTTP 200 public HTML; Web-Scribble-style cards | title, employer, location, relative posted text, salary, source job URL; bounded public detail fields | `Next` link; run limited to 1 page plus bounded detail budget | 18/20 faculty-role eligible; 17 accepted business-scope; card employer is retained as source evidence and not treated as accreditation evidence | enabled |
| `poms` | Global operations / supply-chain opportunities; table also includes industry jobs | HTTP 200 public HTML table | position, university/employer, date, public view URL; location and salary generally absent | one current public table; 120 adapter cap | 109/119 faculty-role eligible; 76 accepted business-scope; 10 role rejects; most location values remain Unknown rather than being assigned to a country | enabled |
| `decision_sciences` | Global decision-sciences academic positions | HTTP 200 public HTML table | posted date, institution, location, title, job type, area, direct public detail/application URL | one current table; 100 adapter cap | 10/10 faculty-role eligible; 9 accepted business-scope; direct target URL is stored separately from the DSI listing URL | enabled |
| `sms` | Global strategic-management faculty board | HTTP 200 public HTML cards | full title from public title/hidden field, company, location, relative posted text, source job URL; bounded public detail fields | public result page plus bounded detail budget; 100 adapter cap | 20/22 faculty-role eligible; 19 accepted business-scope; no guessing of school or deadline | enabled |
| `academic_jobs_online` | Global broad academic board | HTTP 200 listing page and bounded public detail pages | institution/department, title/type, location, subject area, posted date, application deadline, bounded description, occasional salary/PhD evidence | 40 listing details at 0.15s spacing | 34/40 faculty-role eligible; 4 accepted business-scope; broad board intentionally leaves non-business roles in audit scope only | enabled |
| `akadeus` | Global business-school/academic announcements | HTTP 200 public announcement list | title, employer, location, discipline, employment type, explicitly labelled `Posted` date, source detail URL | one public list; 100 adapter cap | 49/69 faculty-role eligible; 39 accepted business-scope; no salary/deadline inference; `DD/MM/YYYY` is normalized with original source identity retained | enabled |
| `ais` | US / information-systems academic market | Existing public adapter; latest success | 29 active source records; 13 current default business links | existing bounded scheduler budget | Domain-focused; source is not a complete US market inventory | enabled |
| `university_affairs` | Canada | Existing public adapter; latest success | 66 active source records; 4 current default business links | existing bounded scheduler budget | Canada-focused; no deadline evidence is counted without explicit closing text | enabled |
| `jobs_ac_uk` | UK and global listings | Existing public adapter; latest success | 23 active records; 11 current default links; closing-date evidence retained | existing bounded budget | Global board is not assigned GB by fallback; `Closes`/`Expires` is parsed only when explicitly labelled | enabled |
| `euraxess` | Europe / international research | Existing public adapter; latest success | 9 active records; 0 current default business links | existing bounded budget | Work-location structure and country evidence are retained; broad research source, not a business-school census | enabled |
| `inside_higher_ed` | Global, using public `assistant professor business` search | Existing public listing + bounded detail enrichment | 849 active records; 134 current default links; school evidence now replays from the full 2,000-character bounded detail excerpt | numbered pages; current default scheduler remains bounded | institution/location/detail extraction is source-specific; Ohio State and other Workday-backed records now use explicit employer/detail evidence | enabled |
| `aacsb_official` | AACSB accredited-school roster plus opt-in official-site checks | public roster imported; official school websites checked only in bounded batches | 1,054 roster rows; 1,053 public official websites; 219 preserved source links; 33 accepted business links | separate opt-in command; not daily | accreditation is not hiring evidence; candidate rejection remains separate from accepted vacancy evidence; current-rule scan status is kept separate from legacy observations | opt-in |
| `aacsb_career_connection` | AACSB job board / teaching-faculty category | public audit returned a Cloudflare challenge | no source records | no retry/bypass | no member/private endpoint and no challenge bypass | manual |
| `aom` | Academy of Management job board | public audit returned a Cloudflare challenge/dynamic boundary | no source records | no retry/bypass | member/detail status is not claimed | manual |
| `ama_academic_placement` | AMA academic placement | public audit returned a Cloudflare challenge | no source records | no retry/bypass | no private/member endpoint | manual |
| `fma` | Finance faculty / academic board | public audit returned a Cloudflare challenge | no source records | no retry/bypass | no private/member endpoint | manual |
| `informs` | INFORMS career center | public audit returned a Cloudflare challenge | no source records | no retry/bypass | no bypass; any future connector also needs a strict business/faculty gate | manual |
| `higheredjobs` | Broad higher-education board | existing audit observed an anti-bot challenge | no new source records | no retry/bypass | remains manual under the existing boundary | manual |
| `herc` | HERC explore endpoint | requested endpoint was not a stable public listing during audit | no source records | no replacement tenant guessed | manual recheck only | manual |
| `efmd_jobs` | EFMD jobs | public endpoint was not stably accessible during audit | no source records | no member/private fallback | manual recheck only | manual |

No row in this matrix treats a listing URL as an official application URL. The DSI adapter is the only newly enabled adapter in this batch with observed direct target URLs; other sources retain official URL as Unknown unless the public evidence exposes a distinct employer destination.

## AACSB official-site discovery

The AACSB roster currently contains 1,054 active directory rows and 1,053 rows with an official website. The latest current-rule run was a 100-school resumable batch:

```text
FACULTY_JOBS_AUTO_UPDATE=0 python3 scripts/update_aacsb_directory.py \
  --scan-existing --max-schools 100 --site-max-pages 4 \
  --delay 0.75 --timeout 20
```

It checked 100 schools, saw 1,136 candidate links/JobPosting objects, rejected all 1,136 under the current individual-role/business-evidence rule, added or updated no job records, and recorded 0 errors. Across all persisted roster observations, status counts are 20 `jobs_found`, 426 `no_current_jobs`, 242 `no_eligible_business_faculty_jobs`, 106 `not_found`, 257 `unknown`, 2 `blocked`, and 1 `not_checked`. Among the 475 current-rule checks specifically, the counts are 4 `jobs_found`, 47 `no_current_jobs`, 242 `no_eligible_business_faculty_jobs`, 55 `not_found`, and 127 `unknown`. Those categories are intentionally not collapsed into “no vacancy”.

The current rule has checked 475 schools in total; 578 official websites remain stale or unchecked. Earlier legacy scans are retained as historical observations but are not counted as current-rule checks. The AACSB source currently preserves 219 source links attached to 217 canonical jobs; 33 are accepted business-market links. The source identity, URLs, bounded excerpts, provenance, and history remain auditable; rejected candidate links are not promoted to vacancy records.

The next safe step is another user-authorized, resumable batch stratified by US/non-US, organization-level/school-unit roster, and public ATS type (Workday, PeopleAdmin, PageUp, Interfolio, or institution HTML/JSON-LD). A 100-school batch at the observed pace takes about 10 minutes and produces at most 100 homepage requests plus four candidate-page requests per school, with bounded excerpts and no raw-page archive. A full remaining 578-school current-rule scan is therefore still not complete.

## Database and evidence snapshot

After the source imports, AACSB sample, IHE school replay, and school-label cleanup, the production database reports:

| Metric | Value |
|---|---:|
| Canonical jobs | 1,506 |
| Preserved source records | 1,509 |
| Active job-source links | 1,509 |
| All / current institutions | 1,603 / 1,193 |
| All / current business-school entities | 1,196 / 992 |
| School-evidence rows | 939 |
| Current field-provenance rows | 124,004 total provenance rows |
| Status-history rows | 20,086 |
| Unresolved possible-duplicate candidates | 381 |
| AACSB roster / scan-history rows | 1,054 / 2,810 |
| Private saved state / application events | 1 / 0 |
| `PRAGMA quick_check` | `ok` |
| `PRAGMA foreign_key_check` | 0 violations |

The current production default business view contains 359 records: 202 explicit `business_school` and 157 `business_discipline`, with 56 unresolved possible-duplicate candidates in this view. Its actual coverage is posted date 84.7%, deadline/rolling 13.9%, official application URL 18.1%, parsed salary 17.8%, location evidence 94.2%, PhD evidence 0.6%, visa evidence 0.6%, start term/year 12.8%, status history 100%, and current provenance 100%. These values were recomputed after migrations 42–49 and do not imply market completeness or a longitudinal trend. Deadline evidence snippets longer than 300 characters: 0.

## Reproducibility and privacy

Before each production write in this expansion, the database was copied with SQLite's online backup API to a new non-overwriting file under `data/backups/`. The source and backup were checked before use; after writes, `quick_check` remained `ok` and `foreign_key_check` remained empty. The named backups include:

- `data/backups/academic_career_source_expansion_20260825_pre_aacsb_sample.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_catalog_sync.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_ihe_school_replay.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_school_label_repair.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_aacsb_batch2.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_deadline_repair_v42.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_ihe_location_chrome_repair_v48.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_aacsb_batch4.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_aacsb_batch5.sqlite3`
- `data/backups/academic_career_source_expansion_20260825_pre_aacsb_batch6.sqlite3`

The source record count increased from 1,206 before the new source batch to 1,509 after it; no source record was deleted. The private `user_job_state` row remained present and no application event or personal profile field was exported by the public adapters, APIs, or CSV layer.

## Final API/browser verification (2026-08-25)

The school explorer list query was changed from repeated correlated `EXISTS`/`COUNT`/`MAX` subqueries to one grouped accepted-job relation joined to current school entities. On the production snapshot, `/api/schools?limit=3`, the GB filter, and the Europe filter each returned HTTP 200 in about 0.26–0.33 seconds; the previous endpoint timeout is resolved without changing the database.

The same isolated local HTTPServer was checked at desktop and 375px viewports for `/faculty-jobs`, `/school-explorer`, `/job-market-analytics`, and `/my-applications`. All four pages had zero browser console errors and `document.documentElement.scrollWidth <= window.innerWidth` at both viewport classes. Browser checks covered country-name filtering (`United Kingdom`), URL-synchronized region summary, current-results CSV URL, job detail evidence dialog, school comparison, analytics scope/history, and the private application/profile form. Screenshots are retained under `output/playwright/` as browser QA artifacts.

With `TRUST_CLOUDFLARE_HEADERS=1` and a simulated remote `CF-Connecting-IP`, public jobs returned HTTP 200 without private fields; `/api/faculty-jobs/profile`, `/api/my-applications`, and private CSV returned HTTP 403 with `academic_career_local_only`. A loopback application read remained HTTP 200 with `Cache-Control: no-store, private`. No private state was changed during browser QA.

The final compile and Academic Career test groups passed 108 tests. The full repository suite ran 801 tests with 800 passing and one unrelated `test_core_guards.FiscalPayloadContract` error when the real root `pboc_data.db` attempts `CREATE TABLE` and receives `sqlite3.OperationalError: disk I/O error`; an isolated temporary fiscal database passes initialization, payload construction, quick-check, and foreign-key checks. The real fiscal database was not modified or deleted. Both project-audit commands pass with six projects, zero errors, and zero warnings.
