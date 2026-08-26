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

# One daily window's worth (~1,000 requests). Rerun after midnight UTC
# until --coverage reports zero pending; the run stops itself when the
# budget is gone.
python scripts/backfill_astar_affiliations.py --limit 45000

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

### The binding constraint: OpenAlex is metered

The full-corpus run stopped at **37.1% coverage**, and the reason is not this code.
OpenAlex now meters by daily request budget:

```
x-ratelimit-limit: 1000          requests/day on the free tier
x-ratelimit-remaining: 0
Retry-After: 60561               resets at midnight UTC
{"error":"Rate limit exceeded","message":"Insufficient budget. This request costs
 $0.0001 but you only have $0 remaining. Resets at midnight UTC."}
```

The run completed 990 successful batches and then every one of the following 1,714
batches was refused. That matches the 1,000/day limit exactly.

Two consequences:

1. **The remaining 85,691 pending articles need ~1,714 more requests**, which is two more
   daily windows on the free tier, or about **$0.17** of prepaid budget in one run.
2. **This budget is shared with the radar's own updates.** The daily incremental queries
   one request per A* journal (219 journals), so an ordinary day sits well inside 1,000 —
   but a backfill run can starve it. The 2026-08-26 backfill consumed the whole day's
   budget, so that day's scheduled A* update would have been refused.

The first version of this backfill handled the refusal badly: it logged each 429 and moved
straight to the next batch at full speed, spending 1,714 requests on responses it could not
use. Fixed in three parts:

- A 429 carrying a `Retry-After` under 15 minutes is a burst limit: wait the stated
  interval (the server's number, not our own exponential guess) and retry, up to 5 times.
- A `Retry-After` above that threshold is the daily budget: **stop the run immediately**.
  Sleeping until midnight UTC inside a run is not backoff. This now costs exactly one
  request to discover, verified by test.
- Five consecutive failed batches from any cause open a circuit breaker and end the run.

An aborted run leaves every unprocessed row `pending`, so the next window resumes cleanly.

### Live results

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

State after the 2026-08-26 window closed:

| | |
|---|---:|
| articles checked | 50,627 / 136,318 (**37.1%**) |
| `recorded` | 45,425 |
| `authors_no_institution` | 3,115 |
| `no_authorships` | 1,422 |
| `no_openalex_id` | 627 |
| `not_found` | 38 |
| **still `pending`** | **85,691** |
| affiliation rows | 181,627 |
| distinct institutions | 9,414 |

**The 37% is not a random sample, and that is the important part.** Backfill walks the
corpus in id order, which is insert order, which tracks the years the radar ingested first.
Observed coverage by publication year:

| Year | Covered |
|---|---:|
| 2019 | 0.0% |
| 2020 | 1.8% |
| 2021 | 1.5% |
| 2022 | 1.3% |
| 2023 | 1.1% |
| 2024 | 97.5% |
| 2025 | 95.4% |
| 2026 | 70.0% |

So the current institution counts are effectively a **2024-2026** table, not an all-time
one. 6 of 261 journals are fully covered, 237 partly, 18 untouched.

`affiliation_coverage` now returns `coverage_by_year`, `year_coverage_spread_pct` and a
`comparable_across_years` flag, and the CLI prints a warning above `--top` whenever the
spread exceeds 5 points. A partial backfill must not be read as a partial ranking.

The skew resolves itself: two more daily windows bring every year to full coverage.

16 tests in `tests/test_astar_affiliations.py` cover parsing (ROR, ORCID, dual affiliation,
author with no institution), the status vocabulary, idempotent re-recording, resumability,
the failed-batch and not-found paths, rate-limit retry, circuit breaking, daily-budget abort,
and that a profile counts **distinct articles** rather than authorship rows — two co-authors
at one school is one article, not two.

## Reading the counts

`top_institutions` returns a count of what the corpus contains, not a ranking. Coverage
depends on how much of the backfill has run, so it must be read alongside
`affiliation_coverage`. A* journal coverage is also not the same as business-school
research strength: the corpus is ABDC A* only, and a school's non-A* output is invisible to
it by construction.

## Next window

```bash
# After midnight UTC, until --coverage reports zero pending.
python scripts/backfill_astar_affiliations.py --limit 45000
python scripts/backfill_astar_affiliations.py --coverage
```

Two more windows finish the corpus. Run it when the day's scheduled A* update has already
gone out, or the backfill will take the budget the radar needs.

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
