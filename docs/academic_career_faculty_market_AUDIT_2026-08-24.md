# Academic Career / Faculty Job Market final precision audit — 2026-08-24

Run date: 2026-08-24 Mountain / 2026-08-25 UTC  
Production store: `data/faculty_jobs.db`  
Current schema migration: v38  
Current AACSB website rule: `faculty_market_v2_20260824`

## Outcome

The reported GA problem was real and is fixed at the market-view boundary. Graduate assistants, federal work study, staff jobs, and explicit non-business academic fields remain in the source/audit layer but no longer enter the default business-faculty market. The live default now contains 189 active role-eligible business jobs; 144 are in the United States. The broader accepted business boundary contains 197 records, while `scope=all` retains all 1,198 canonical jobs.

The AACSB directory and school-site feature is implemented, but its evidence grains are now separated. The official [AACSB Accredited School Directory](https://www.aacsb.edu/accredited) is accreditation evidence, not vacancy evidence. Legacy website scan results remain visible but only 25 websites have been checked under the current faculty-role/business-scope rule; 1,028 websites remain stale or unchecked. A complete current-rule vacancy scan is therefore still pending and no claim of complete AACSB or US-market coverage is made.

## Confirmed defects and root causes

| Defect | Production evidence | Root cause | Repair |
|---|---|---|---|
| Graduate assistants and Federal Work Study appeared as faculty jobs | Jobs 1018, 1022, and 1023 were business-school associated but were student roles | School/business text could override the absence of an eligible faculty role | Added a first-class role classifier and required `faculty_market_eligible=1` before default inclusion |
| Computer science, cosmetology, radiopharmaceutical, law, and similar roles leaked into business scope | Screenshot examples included jobs 1060, 1065, and 1074 | Broad management/business terms and school associations outweighed an explicit non-business field | Expanded explicit non-business/ambiguous-field rules and made the non-business unit decisive |
| Some IHE jobs inherited the wrong business school | 43 stale school links were cleared in v33 | The old detail parser could promote a later collaborator/cross-appointment mention to the recruiting school | Versioned IHE school evidence and restricted it to the primary posting-level recruiting unit |
| Generic school pages were treated as AACSB job evidence | Legacy scan retained directory, dean, policy, research, student-career, and generic faculty pages | AACSB accreditation or a linked school entity was allowed to supply too much posting context | Required an individual eligible role plus posting-level business evidence; rejected generic pages and quarantined unsupported derived rows |
| Legacy AACSB checks looked current | 1,053 websites had historical observations, but those observations predated the current gate | Scan evidence had no rule version | Added `scan_rule_version`, current-rule counts, stale labels, current-first ordering, and resumable unchecked/stale selection |
| Corrected business scopes reverted after reads | Strict count returned from 197 to 227 without timestamp/audit changes | A long-lived Windows `server.py` process still held the pre-repair unconditional backfill code and rewrote derived fields during table initialization | Removed the unconditional legacy backfill, stopped the exact stale process, restarted one current process, and replayed the boundary in v37 |
| Old and past-deadline postings looked active | One accepted record had a passed fixed deadline and seven were older than 365 days without future deadline evidence | Status did not apply a recency boundary | v36 marks passed fixed deadlines `closed` and stale unsupported records `unknown`; default scope now applies the active-status gate |
| `Washington D.C.` was normalized to Washington state | Jobs 682 and 912 displayed `Washington D.C., WA` | Named-state matching found `Washington` before recognizing D.C. | Added a D.C.-first parser rule and v38 source-location replay; exactly two jobs changed to `DC` |
| `scope=all` copy called excluded records role-eligible | Browser audit search displayed student/staff rows beneath a role-eligible summary | Frontend copy did not vary by scope | Audit scope now says “observed source records, including excluded roles” and uses an audit-specific heading |

## Current production market

| Grain or metric | Current value |
|---|---:|
| Canonical jobs in `scope=all` | 1,198 |
| Accepted business boundary | 197 |
| Active default business market | 189 |
| Active United States default | 144 |
| Active `business_school` | 110 |
| Active `business_discipline` | 79 |
| Active faculty / academic leadership | 180 / 9 |
| Accepted but closed / unknown | 1 / 7 |
| Source records / job-source links | 1,200 / 1,200 |
| Private saved-state rows | 1 |

Active default jobs by source are Inside Higher Ed 135, AACSB official sites 23, jobs.ac.uk 14, AIS 13, and University Affairs 4. These are observed source contributions, not estimates of the entire labor market.

The default evidence gaps remain material: 165 of 189 records have no fixed deadline, 150 have no official application URL, six have no institution, and 82 have no linked school entity. Missing values remain Unknown rather than being inferred. There are ten repeated exact-fingerprint groups in the active default and 331 unresolved review-ledger candidates overall. Same-source requisitions are not automatically merged merely because their titles look similar.

## AACSB roster and website evidence

| AACSB grain | Current value |
|---|---:|
| Directory results reported / observed | 1,093 / 1,093 |
| `/accredited/` roster records | 1,054 |
| Non-accredited member insertions excluded | 39 |
| Named school-unit records | 881 |
| Organization-level records with no separate public school field | 173 |
| Linked local school entities | 881 |
| Detail pages parsed | 1,054 |
| Official websites exposed | 1,053 |
| Legacy + current websites ever checked | 1,053 |
| Checks under the current rule | 25 |
| Current-rule stale/unchecked websites remaining | 1,028 |
| Current-rule candidates seen / rejected | 104 / 98 |
| Current-rule eligible postings extracted | 5 from 2 schools |
| AACSB source records / links | 219 / 219 |
| Accepted / quarantined AACSB-linked canonical records | 23 / 194 |

The current 25-site batch found four postings at American University in the Emirates and one at American University of Sharjah. Thirteen sites had candidate links but no candidate satisfying both the role and business-posting gate; four had no current eligible posting, two had no discoverable public faculty entry, and four remained unknown because of access/network evidence. These outcomes must not be collapsed into “no vacancy.”

The 173 organization-level records are not labeled “unknown business school.” They represent public AACSB results where the organization itself is the returned accredited entity and the endpoint supplied no separate `school_name` field.

## Production migrations applied in this audit chain

| Migration | Purpose |
|---|---|
| v28 | Replayed the individual-vacancy/business-unit boundary and high-confidence source-location country evidence |
| v29 | Restored explicit IHE posting-level school fields before the boundary pass |
| v30 | Reversed an evidence-label-only overbroad location replay without discarding audit rows |
| v31 | Versioned AACSB website-scan evidence |
| v32 | Expanded non-business and ambiguous-management field rules |
| v33 | Revalidated legacy IHE school associations; 67 jobs changed and 43 stale links cleared |
| v34 | Merged 75 duplicate/chrome-contaminated school entities and deactivated 14 unreferenced derived rows |
| v35 | Applied law-school and late title-boundary follow-up |
| v36 | Reclassified 78 stale/past-deadline statuses |
| v37 | Replayed 334 strict derived boundaries after the stale server-process writeback |
| v38 | Corrected two `Washington D.C. → WA` rows to `DC` from preserved source locations |

All migrations are idempotent and derived-field/evidence-ledger oriented. No raw source identity or private application row was deleted.

## Backups and preservation

The final corrective stages were preceded by SQLite-consistent online backups:

- `data/backups/academic_career_20260824_pre_v33_ihe_school_revalidation/faculty_jobs.db`
- `data/backups/academic_career_20260824_pre_v34_v35_school_entities/faculty_jobs.db`
- `data/backups/academic_career_20260824_pre_v36_v37_stale_server_recovery/faculty_jobs.db`
- `data/backups/academic_career_20260824_pre_v38_dc_location_fix/faculty_jobs.db`

The final production database reports `PRAGMA quick_check=ok` and zero `foreign_key_check` rows. It retains 1,198 jobs, 1,200 source records, 1,200 source links, 45,763 provenance rows, 8,416 status-history rows, 939 school-evidence rows, and the existing private saved state. The v38 backup independently reports `quick_check=ok`, zero foreign-key violations, and migration max v37.

## Verification evidence

- Final Academic Career regression: 93 tests passed. The AIS warning is an intentional fixture that verifies source-failure isolation.
- Python compile checks: `server.py`, all Faculty Jobs services/adapters, and updater scripts passed.
- JavaScript syntax: `static/faculty_jobs.js` and `static/school_explorer.js` passed the bundled Node `--check`.
- Project boundary audit: `projects_audit=pass projects=6 errors=0 warnings=0`.
- Live API after final restart: default 189, United States 144, `scope=all` 1,198, AACSB current checks 25, remaining 1,028, current candidates 104/98.
- Repeated live reads left strict counts and the six screenshot-row classifications unchanged, confirming that the stale-process writeback is gone.
- Desktop and 375px real-browser checks covered Faculty Jobs and School Explorer. Both pages had zero console errors/warnings. School Explorer at 375px reported viewport width 375 and document/body width 360, with no page-level horizontal overflow.
- The default browser view contained none of Graduate Assistant, Federal Work Study, School of Computer Science chair, Cosmetology, or Radiopharmaceutical. `scope=all&q=Graduate Assistant` displayed the retained GA rows as `Excluded: non-academic` and `student_role`.
- The US browser filter rendered 144 records. The AACSB browser view rendered 1,054 roster records, the 881/173 entity split, 25 current checks, 1,028 remaining, and a `Continue bounded current-rule scan` button without starting an external scan.

Browser artifacts:

- `output/playwright/academic-career-20260824/faculty-jobs-desktop.png`
- `output/playwright/academic-career-20260824/faculty-jobs-mobile-viewport.png`
- `output/playwright/academic-career-20260824/school-explorer-desktop.png`
- `output/playwright/academic-career-20260824/school-explorer-mobile-viewport.png`

A final repository-wide run executed 784 tests and stopped with one unrelated Fiscal setup error: WSL could not read the active 1.04GB `pboc_data.db`/WAL and raised `sqlite3.OperationalError: disk I/O error`. A direct read-only `quick_check` reproduced the same error. That database and its WAL/SHM were not changed; the final 93-test Academic Career suite passed independently.

## Remaining work and explicit non-claims

1. The remaining 1,028 AACSB websites have not been rescanned under the current rule. At the observed bounded-batch pace, a complete continuation is a long-running opt-in operation; it should be run in recorded batches rather than implied complete.
2. This snapshot is not a census of all current US faculty jobs. It is the current active subset observed by the configured public sources and evidence rules.
3. An AACSB roster row establishes directory/accreditation context only. It does not establish a vacancy, research tier, Carnegie class, doctoral program, or current hiring.
4. Official application URLs, fixed deadlines, institution names, and school links remain sparse for some listing-only sources. Users must verify the public source before applying.
5. Exact-fingerprint and fuzzy duplicate candidates remain review items unless safe source identity or official-URL evidence supports a merge.
6. Historical AACSB scan rows remain intentionally visible with `Recheck required`; they must not be aggregated with current-rule outcomes.

## Safe continuation commands

Resume a bounded current-rule website batch without refetching the AACSB directory:

```bash
FACULTY_JOBS_AUTO_UPDATE=0 python3 scripts/update_aacsb_directory.py \
  --scan-existing --max-schools 25 --site-max-pages 4 --delay 0.75 --timeout 20
```

After each batch, record its run metrics and verify the production store:

```bash
python3 - <<'PY'
import sqlite3
c = sqlite3.connect('data/faculty_jobs.db')
print(c.execute('PRAGMA quick_check').fetchone()[0])
print(c.execute('PRAGMA foreign_key_check').fetchall())
PY
```

Do not call the remaining scan complete until `stale_or_unchecked_websites` reaches zero under the same rule version, and do not convert blocked/unknown/not-found outcomes into inferred absence of vacancies.
