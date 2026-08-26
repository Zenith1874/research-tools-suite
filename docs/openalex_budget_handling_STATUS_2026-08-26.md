# OpenAlex daily-budget handling — 2026-08-26

## What changed upstream

OpenAlex now meters by daily request budget. The free tier is 1,000 requests/day, reset at
midnight UTC, after which every request is refused:

```
x-ratelimit-limit: 1000
x-ratelimit-remaining: 0
Retry-After: 60561
{"error":"Rate limit exceeded","message":"Insufficient budget. This request costs
 $0.0001 but you only have $0 remaining. Resets at midnight UTC."}
```

Discovered when the affiliation backfill stopped at 37.1% coverage: 990 batches succeeded,
then 1,714 were refused, matching the 1,000/day limit exactly.

## Why the radar needed fixing too

`_http_get_json` had only `raise_for_status()`. On a spent budget:

1. Every journal raised a generic `HTTPError` with no indication of the cause.
2. `fetch_recent_articles_for_journal` caught it and moved to the next journal, so a
   219-journal run spent **219 more refused requests** rediscovering the same fact — up to
   438, since a journal with both a print and an online ISSN was tried twice.
3. The run was written to `astar_update_logs` with **`success=1`** even when every single
   journal had failed, and `error_message` was hard-coded to `None`.

The last one is the worst of the three: the run that consumed the budget on 2026-08-26 would
have been recorded as a healthy update.

## The shared layer

`services/openalex_budget.py` is now the single implementation, used by both the radar and
the affiliation backfill.

Two different refusals share status 429 and must be handled differently:

| Refusal | Signal | Response |
|---|---|---|
| burst limit | short `Retry-After` | wait the interval **the server states**, retry up to 5× |
| daily budget spent | `Retry-After` > 900s | stop asking; waiting means sleeping until midnight UTC |

`BudgetState` carries the second across a run. The first refusal sets the flag, and every
later OpenAlex call in that run is skipped without a request. One refusal now covers all
remaining journals instead of costing one request each.

The classification is deliberately conservative: a missing or unparseable `Retry-After`
(for example an HTTP-date form) is **not** treated as budget exhaustion, so an ambiguous
response degrades into retrying rather than into shutting the source off.

## Behaviour on a spent budget

- OpenAlex is attempted once, then skipped for the rest of the run.
- **Crossref fallback still runs**, so the radar keeps collecting articles — with the usual
  Crossref limitations, and without authorships, so those articles stay `pending` for the
  affiliation backfill rather than being recorded as having no affiliation.
- The run is logged with `success=0` and an `error_message` naming the budget, plus a
  warning recording how many journals were skipped and that Crossref was used.
- A run where *some* journals succeeded is still `success=1`. Only a run where every journal
  with an ISSN failed is recorded as a failure.

## Budget arithmetic

| Consumer | Requests |
|---|---:|
| daily incremental | ~219 (one per A* journal, two if the first ISSN misses) |
| weekly incremental | ~219 |
| affiliation backfill, full corpus | ~2,700 |
| **free daily budget** | **1,000** |

An ordinary day sits well inside the budget. A backfill does not: it must be run after the
day's scheduled update, and it will still need several windows. Paying for the corpus in one
run costs about $0.27 at $0.0001/request.

## Tests

- `tests/test_openalex_budget.py` — 15 tests: 429 classification, header capture, the
  burst/budget boundary, ambiguous `Retry-After` values, broken JSON bodies, the wait
  calculation (server value beats our exponential guess; explicit `0` is honoured; capped at
  300s), and `BudgetState` accounting.
- `tests/test_astar_radar_budget.py` — 9 tests: one refusal covers 50 journals, the second
  ISSN is not burned, Crossref keeps serving while OpenAlex is shut out, a burst limit does
  not disable the source, the `budget` parameter is optional, and the update log records
  total failure as `success=0` with the reason while a partial run stays `success=1`.

Full suite: 869 tests, all passing. `scripts/audit_projects.py`: 6 projects, 0 errors.

## Self-healing backfill

The affiliation backfill now runs as a bounded step in `astar_scheduler_thread`, placed
**after** the radar update so the radar gets the budget it needs first. It consumes only
what is left, stops itself when the budget is gone, and leaves the remainder `pending` for
the next day. The corpus therefore completes over the next few days without a manual run.

`AFFIL_AUTO=0` disables it; `AFFIL_AUTO_LIMIT` bounds one pass (default 40000, still capped
by the day's real budget). This follows the existing `LLM_AUTO` / `EMB_AUTO` pattern: an
optional step, wrapped so a failure is logged and never breaks the radar update.

## Not done

`fetch_crossref` has no equivalent rate-limit handling. Crossref is not metered the same way
and has not caused a failure here, so this is noted rather than pre-emptively built.
