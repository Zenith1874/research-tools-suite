# A* institution layer — 2026-08-26

## Why

School research strength was the emptiest axis in the Academic Career module. Measured on
the production `faculty_jobs.db` on 2026-08-26:

| Field | Observed |
|---|---|
| `business_schools.business_research_tier` | T4: 920 · Unclassified: 291 · T3: 1 · T2: 1 · **T1: 0** |
| `institutions.university_research_level` | **Unknown: 1,658 (100%)** |

Both axes render in School Explorer and neither carries information. Meanwhile the A* radar
holds 136,318 articles from ABDC A* journals, 135,691 of them with an OpenAlex work id —
the most credible evidence base for "which schools publish in top business journals" that
this suite could have, and it was not connected to the Academic Career domain at all.

The reason it could not be connected: `_parse_openalex_work` reduced each work's
`authorships` to a list of display names, so `authors_json` looked like `["Mara Olekalns"]`
and no institution, ROR id, author id or ORCID was ever stored.

## What was built

`services/astar_affiliation_service.py` owns an affiliation grain and nothing else. It does
not rank schools and does not assign a research tier; it records which institution published
which A* article, with the identity that supports the claim.

`astar_article_affiliations` — one row per (article, author position, institution):
author position/role/corresponding flag, OpenAlex author id, ORCID, institution OpenAlex id,
**ROR id**, display name, country code, institution type, and the raw affiliation string.
A dual appointment produces one row per institution.

`astar_articles` gained `affiliation_status` and `affiliation_checked_at`. Status is an
observed outcome, never a silent blank:

| Status | Meaning |
|---|---|
| `pending` | not attempted yet |
| `recorded` | at least one institution stored |
| `authors_no_institution` | OpenAlex has the authors but publishes no affiliation |
| `no_authorships` | the work record carries no authorships at all |
| `not_found` | the stored `openalex_id` no longer resolves |
| `no_openalex_id` | nothing to look the work up by |

The distinction that matters is `authors_no_institution` versus `pending`: "we looked and
OpenAlex has no affiliation" must not be indistinguishable from "we never looked".

### Backfill

`scripts/backfill_astar_affiliations.py` walks the corpus in bounded, resumable batches,
asking OpenAlex for up to 50 work ids per request with `select=id,authorships` so the
payload stays small.

```bash
# What is left, without touching the network.
python scripts/backfill_astar_affiliations.py --coverage

# A bounded batch.
python scripts/backfill_astar_affiliations.py --limit 500

# The full corpus; rerun until pending reaches zero.
python scripts/backfill_astar_affiliations.py --limit 140000

# Inspect what was recovered.
python scripts/backfill_astar_affiliations.py --top 25 --since 2020
```

Only rows whose status is NULL or `pending` are selected, so an interrupted run resumes
instead of refetching. A failed batch leaves its rows `pending` — a transport failure is
never recorded as a checked outcome — while an id OpenAlex does not return is marked
`not_found` and not retried forever.

### Ingest

`_parse_openalex_work` now keeps the whole `authorships` array, and `_upsert_article`
records affiliations for both inserts and updates, so newly fetched articles no longer need
a second pass. Crossref fallback records carry no authorships and deliberately stay
`pending` for the backfill rather than being recorded as having no affiliation. The write is
wrapped: the affiliation layer is additive and must never fail an article ingest.

## Validation

A consistent SQLite online backup was taken before the first write:
`data/backups/astar_20260826_pre_affiliation/pboc_data.db` (1.04 GB, 136,318 articles).
The migration is additive — one new table, two nullable columns, four indexes.

First bounded live run, 500 articles in 10 requests, zero errors:

| Outcome | Count |
|---|---:|
| `recorded` | 456 (91.2%) |
| `authors_no_institution` | 28 |
| `no_authorships` | 16 |
| `not_found` | 0 |
| affiliation rows | 1,715 |
| distinct institutions | 687 |

687 distinct institutions from 500 articles is the shape to expect: the corpus is wide, so
per-school counts only become meaningful once the backfill is complete.

13 tests in `tests/test_astar_affiliations.py` cover parsing (ROR, ORCID, dual affiliation,
author with no institution), the status vocabulary, idempotent re-recording, resumability,
the failed-batch and not-found paths, and that a profile counts **distinct articles** rather
than authorship rows — two co-authors at one school is one article, not two.

## Reading the counts

`top_institutions` returns a count of what the corpus contains, not a ranking. Coverage
depends on how much of the backfill has run, so it must be read alongside
`affiliation_coverage`. A* journal coverage is also not the same as business-school
research strength: the corpus is ABDC A* only, and a school's non-A* output is invisible to
it by construction.

## Not done yet

- **The link to Academic Career is not built.** `institutions` in `faculty_jobs.db` has no
  ROR column, so there is no join key to the affiliation grain yet. The next step is to
  resolve ROR ids for the 1,658 observed institutions (OpenAlex `/institutions` by name +
  country), store them, and then derive `university_research_level` and the business tier
  from observed A* output — marked `derived`, with the method and the n stated, rather than
  presented as an official classification.
- No page or API exposes the layer yet; it is service + CLI only.
- Author-level identity is stored but not deduplicated across name variants.
- The corpus counts articles, not faculty headcount; a school with one prolific author and a
  school with twenty occasional ones can produce the same number.
