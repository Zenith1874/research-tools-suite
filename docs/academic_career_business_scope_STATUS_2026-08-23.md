# Academic Career business-market scope status — 2026-08-23

## 2026-08-25 final role/business/status boundary (current)

The production default contains 189 active role-eligible business-market jobs: 110 `business_school` and 79 `business_discipline`; 144 are in the United States. The accepted boundary contains 197 jobs before the current-status gate: 117 `business_school`, 80 `business_discipline`, one `closed`, and seven `unknown`. The raw audit catalogue contains 1,198 canonical jobs. `scope=all` intentionally exposes excluded rows with their `faculty_market_role` and `business_scope` labels; it is not another business-market count.

The role gate now rejects graduate assistants, student work, staff/administrative listings, and unknown roles before school association can influence inclusion. The field gate prevents computer science, cosmetology, radiopharmaceutical science, law-school, and other explicit non-business units from entering merely because a later excerpt mentions management or a business collaborator. IHE school evidence must come from the current bounded posting parser; an AACSB roster or local school link cannot turn a generic page into a vacancy.

Status is also part of the default boundary unless the caller explicitly requests a status: a passed fixed deadline becomes `closed`, and a record older than 365 days without future fixed-deadline evidence becomes `unknown`. This is why the 197 accepted boundary and 189 active default are both retained and reported separately.

## Historical v32 boundary after IHE/AACSB expansion (superseded)

The following 202-job section is a historical intermediate snapshot. It predates migrations v33–v38 and must not be used as the current market count.

The current production default contains 202 accepted business-market jobs: 159 `business_school` and 43 `business_discipline`. The raw catalogue contains 1,198 canonical jobs, including 194 quarantined AACSB-derived canonical records and the broader Inside Higher Ed search capture. Records with `derived_quality='quarantined'` remain source-linked and auditable but are excluded from default `business` and `business_school` views; `scope=all` is the explicit audit view. This prevents ordinary faculty directories, dean/research pages, policy pages, and explicit non-business AACSB postings from being presented as current business vacancies.

The label `Explicit business-school evidence` refers to source text/fields that explicitly name a business school, college, department, or equivalent. `Linked local school entity` means an entity was conservatively linked. `Verified school evidence` is used only when an auditable `school_evidence` row exists. AACSB evidence is an accreditation evidence row; it does not by itself establish a research tier, Carnegie class, PhD program, or current hiring.

The accepted business view has 202/202 status-history coverage; current provenance rows cover 201/202 (99.5%). Other observed coverage is 19.3% official application URL, 19.3% deadline-or-rolling, 26.2% parsed salary (53.5% raw salary text), 77.7% linked school entity, 40.1% school-evidence ledger coverage, and 39.1% classified school tier. Explicit PhD and visa evidence is sparse (0.5% and 0.5%); the UI displays missing evidence as Unknown rather than guessing. Manual include/exclude scope overrides remain separate, local, and auditable.

The full public Inside Higher Ed query retains 836 unique parseable listing cards from 838 reported results and 849 preserved source identities; its current detail-enriched capture contributes 148 accepted business-scope canonical jobs after the v32 precision boundary, including 128 with explicit posting-level school evidence. AACSB official-site rescanning found 68 raw postings across 29 schools; the stricter faculty-market boundary currently accepts 23 canonical AACSB jobs/source identities and retains 194 roster/non-posting or unsupported derived canonical records as quarantined (219 source records and 219 active source links remain). These are source-coverage observations, not estimates of the whole market.

## Change

The public Faculty Jobs view now defaults to business-school / business-discipline scope. The raw normalized catalogue remains available through `scope=all`; `scope=business_school` is the strict explicit-business-school-evidence view. It is not a claim that accreditation, Carnegie, a PhD program, or a formal school tier has been independently verified.

Each job receives an auditable derived classification:

- `business_school`: explicit business school/college/department evidence, optionally linked to a local school entity. The scope reason preserves the source field/excerpt; it does not imply independent school verification.
- `business_discipline`: a business subject appears in the title/department or an explicit department/category excerpt, but no independently verified school evidence is present.
- `non_business`: a named non-business academic field is present.
- `non_academic`: the title is a technical, product, or administrative role rather than an academic appointment.
- `unknown`: the captured evidence is insufficient; it is excluded from the default business view.

The raw job, excerpt, source links, and provenance remain unchanged. Existing rows are backfilled at database initialization; new and updated rows receive the same classification during normalization. The API distinguishes `explicit_business_school_text`, `linked_school_entity`, `verified_school_evidence`, and local manual overrides. Manual include/exclude scope decisions live in a separate auditable table and never overwrite `jobs.business_scope`.

## 2026-08-24 continuation

The following paragraph is a historical intermediate snapshot and is superseded by the current 2026-08-25 section above.

The private management surface now includes saved-search alerts, a duplicate-review queue, and institution-alias management. These controls do not change raw source records. A fuzzy candidate can be rejected or marked distinct with a reason; a merge is guarded by exact equality of a mergeable official application URL and refuses ambiguous private-state conflicts. The School Explorer label remains `Explicit business-school evidence` rather than `Verified` unless an evidence ledger row exists.

The current database has 34 business-scope records: 18 `business_school` and 16 `business_discipline`. Of these, 18 have a linked local school entity, 6 have an official-page evidence row, and 2 have a classified business tier. The remaining records intentionally stay Unknown/Unclassified where evidence is insufficient.

## Reason

The previous page queried the full faculty-oriented source catalogue. That allowed medical, architecture, poetry, and technical/product postings to appear beside business jobs because discipline classification was displayed but not used as an inclusion boundary. AIS also exposes non-faculty jobs, so source membership alone is not sufficient evidence.

## 2026-08-24/25 IHE detail and evidence-boundary correction

The two reported IHE detail pages are now represented with explicit structured evidence:

- source job 3534806: Ohio State University; Columbus, OH, United States; Fisher College of Business; salary range 185,000 to 200,000 USD; no application deadline was invented from the board expiry field.
- source job 3226393: Lebanese American University; Beirut and Byblos, Lebanon; School of Business; explicit open-until-filled wording; no salary or official application URL was invented.

The institution, school, location, and deadline fields come from preserved public detail-page extraction and are separately auditable. An IHE detail page without an explicit school remains institution-only or business-discipline evidence; a later cross-appointment mention is not promoted to the primary school. Migrations 26 and 27 repaired bare ISO location tokens and restored explicit school links from preserved structured source fields; migration 29 replays that school field before the boundary pass, without deleting source records. The resulting IHE source grain is 849 source records, 849 canonical links, 148 accepted business-scope jobs, and 128 accepted business-school jobs; all IHE records have a non-Unknown institution and country, while 54 have no city because the public evidence is region/state/country-only. Migration 32 further separates explicit non-business and ambiguous-management records without deleting source evidence.

The faculty-market gate now distinguishes an individual posting from a school roster page. AACSB roster accreditation can supply an entity/evidence context but cannot by itself turn a directory, dean page, policy page, or generic faculty page into a vacancy. Accepted AACSB rows therefore contain 23 canonical jobs/source identities; 194 derived canonical rows remain quarantined and source-linked for audit. This is a precision correction, not deletion or a claim that the 68 raw official-site observations are a complete vacancy census.

## Verification target

Run the normalizer and schema tests, query `/api/faculty-jobs?country=US` (business scope is now the default), compare with `/api/faculty-jobs?country=US&scope=all`, and confirm the page badges expose explicit text, linked-entity, evidence, manual-override, and business-discipline states separately.
