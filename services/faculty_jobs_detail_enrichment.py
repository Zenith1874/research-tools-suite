# -*- coding: utf-8 -*-
"""Resumable detail-page enrichment for boards read as listing cards only.

Most of what a candidate actually needs -- when applications close, where to
apply, whether the line is tenure-track -- lives on the posting's own page, not
on the card that links to it. Ten of the enabled adapters never open one, and
the largest source in the database (2,824 rows, 86% of the default market)
deliberately does not: opening every posting would be 2,824 extra requests
inside a single ingest run, and that board intermittently answers with an
Imperva challenge, so a run that insisted on finishing would throw away
thousands of good requests when it hit one.

So the pass is separated from ingestion and made resumable:

* every attempt is recorded in ``job_detail_fetches``, so "the page said
  nothing about a deadline" stays distinguishable from "we never opened it";
* a challenge or a refusal stops the run and is recorded as such -- never as
  evidence that the posting has no deadline;
* a rerun continues from what has not been attempted, so an interrupted pass
  costs only the requests it already spent.

Fields are read with the shared public-detail parser, which prefers a page's
own JobPosting schema and falls back to labelled text. Nothing here invents a
value: a field the page does not carry stays unset.
"""

from datetime import datetime, timedelta, timezone
import json
import sqlite3

from services import raw_archive
from services.faculty_jobs_normalizer import (classify_visa, clean_text, normalize_url,
                                             parse_deadline,
                                             parse_salary)
from services.faculty_jobs_sources.base import (AdapterError, CrawlBudgetExhaustedError,
                                                NonRetryableAdapterError, RobotsDisallowedError,
                                                adapter_catalog, now_utc)
from services.faculty_jobs_sources.source_jobboards import (
    DETAIL_TEXT_LIMIT, _parse_public_detail,
)

# Statuses recorded per posting. Only "ok" means the page was read; everything
# else marks a posting still owed a reading.
STATUS_OK = "ok"
STATUS_CHALLENGED = "challenged"
STATUS_REFUSED = "refused"
STATUS_ERROR = "error"
STATUS_EMPTY = "empty"

# Fields the pass may fill. It only ever fills a blank: a value already derived
# from the listing or repaired by hand is never overwritten by a detail page.
#
# Deliberately not including ``department``: the shared detail parser reads a
# page's JobPosting schema and a fixed set of labels, and department is not one
# of them. Listing it here would have the pass advertise a field it never
# supplies, and every run would then look like the page simply never carried
# one. Widening the shared parser is a separate change -- it is used by five
# other adapters.
ENRICHABLE = (
    "deadline_date", "deadline_mode", "official_url", "salary_raw",
    # The posting's own text, and what only its text can answer. The parser has
    # always returned `description`; the pass discarded it, which is why visa,
    # language and research-area coverage sat at 0.0% no matter how good their
    # parsers were.
    "description_excerpt", "visa_status", "visa_text", "visa_pathways",
)


# Below this a "description" is page chrome or a listing blurb, not a posting.
# Sponsorship, work-authorization and language paragraphs do not fit in one,
# so nothing downstream gains from storing it -- and treating it as a body
# would cost the `empty` status its meaning.
MIN_BODY_CHARS = 600


class DetailEnrichmentStopped(Exception):
    """The board stopped serving this run; progress is saved, not lost."""


def _adapter(source_name):
    for adapter in adapter_catalog():
        if adapter.name == source_name:
            return adapter
    raise AdapterError(f"no adapter installed for source {source_name!r}")


# A posting is finished once its page has been read, whether or not the page
# carried anything we could use. "We opened it and it said nothing" is an
# answer; re-asking every run would spend the whole budget rediscovering it.
# Stamped on every archived page so a re-parse years from now can tell
# which extraction produced the stored fields.
PARSER_VERSION = "detail_enrichment_v2_20260902"

TERMINAL_STATUSES = (STATUS_OK, STATUS_EMPTY)


def pending_count(conn, source_name, now=None):
    """Postings whose detail page still owes us a reading."""
    now = now or now_utc()
    row = conn.execute(f"""
        SELECT COUNT(*) FROM job_sources js
        JOIN sources s ON s.id = js.source_id
        LEFT JOIN job_detail_fetches f
          ON f.source_id = js.source_id AND f.source_job_id = js.source_job_id
        WHERE s.name = ? AND js.active = 1
          AND (f.source_job_id IS NULL
               OR (f.status NOT IN ({','.join('?' * len(TERMINAL_STATUSES))})
                   AND (f.next_retry_at IS NULL OR f.next_retry_at <= ?)))
    """, (source_name, *TERMINAL_STATUSES, now)).fetchone()
    return int(row[0])


def _pending_rows(conn, source_name, limit, now=None):
    now = now or now_utc()
    return conn.execute(f"""
        SELECT js.job_id, js.source_id, js.source_job_id, js.source_url,
               j.deadline_date, j.deadline_mode, j.official_url, j.department, j.salary_raw,
               -- The body and the fields derived from it. Reading a row key the
               -- query never selected is a silent no-op, not an error.
               j.title_raw, j.description_excerpt,
               j.visa_status, j.visa_text, j.visa_pathways,
               COALESCE(f.attempt_count, 0) AS attempt_count
        FROM job_sources js
        JOIN sources s ON s.id = js.source_id
        JOIN jobs j ON j.id = js.job_id
        LEFT JOIN job_detail_fetches f
          ON f.source_id = js.source_id AND f.source_job_id = js.source_job_id
        WHERE s.name = ? AND js.active = 1
          AND (f.source_job_id IS NULL
               OR (f.status NOT IN ({','.join('?' * len(TERMINAL_STATUSES))})
                   AND (f.next_retry_at IS NULL OR f.next_retry_at <= ?)))
        ORDER BY js.job_id
        LIMIT ?
    """, (source_name, *TERMINAL_STATUSES, now, int(limit))).fetchall()


# Unfinished postings back off rather than being retried tightly on every run.
RETRY_BACKOFF_HOURS = (1, 6, 24, 72)


def _next_retry(attempt_count):
    """When an unfinished posting may be asked for again."""
    index = min(max(int(attempt_count or 1), 1), len(RETRY_BACKOFF_HOURS)) - 1
    delay = timedelta(hours=RETRY_BACKOFF_HOURS[index])
    return (datetime.now(timezone.utc) + delay).isoformat(timespec="seconds").replace("+00:00", "Z")


def _record_attempt(conn, source_id, source_job_id, job_id, status,
                    http_status=None, observed=None, updated=None, reason=None,
                    attempt_count=0):
    """Record one attempt.

    ``observed`` is what the page carried; ``updated`` is what we wrote. They
    differ whenever the page held a value the job already had, and collapsing
    them would file such a page as though it carried nothing.
    """
    attempts = int(attempt_count or 0) + 1
    retry_at = None if status in TERMINAL_STATUSES else _next_retry(attempts)
    payload = json.dumps(sorted(updated or []), ensure_ascii=False)
    conn.execute("""
        INSERT INTO job_detail_fetches
          (source_id,source_job_id,job_id,attempted_at,status,http_status,
           fields_found,fields_updated,fields_observed,reason,
           attempt_count,last_attempt_at,next_retry_at)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(source_id,source_job_id) DO UPDATE SET
          job_id=excluded.job_id, attempted_at=excluded.attempted_at,
          status=excluded.status, http_status=excluded.http_status,
          fields_found=excluded.fields_found, fields_updated=excluded.fields_updated,
          fields_observed=excluded.fields_observed,
          reason=excluded.reason, attempt_count=excluded.attempt_count,
          last_attempt_at=excluded.last_attempt_at, next_retry_at=excluded.next_retry_at
    """, (source_id, source_job_id, job_id, now_utc(), status, http_status,
          # fields_found is retained as the historical name for the same value
          # so older rows and readers keep working.
          payload, payload,
          json.dumps(sorted(observed or []), ensure_ascii=False),
          (reason or None), attempts, now_utc(), retry_at))


def _is_blank(value):
    """NULL, empty and the literal 'unknown' all mean the slot is unfilled.

    deadline_mode in particular is stored as 'unknown' rather than NULL by the
    normalizer, so treating only NULL as fillable left every such row
    permanently unfillable.
    """
    return value is None or str(value).strip() in ("", "unknown", "Unknown")


def _derived_updates(row, fields, reference_date):
    """Split what the page carried from what we may write.

    Returns ``(observed, updates)``. A page that states a deadline we already
    hold contributes to ``observed`` and not to ``updates`` -- recording only
    the latter would file such a page as having carried nothing.
    """
    # Key names come from _parse_public_detail, which calls them "deadline" and
    # "salary" rather than the column names they land in.
    observed, updates = [], {}

    deadline_raw = clean_text(fields.get("deadline"))
    if deadline_raw:
        observed.append("deadline_date")
        parsed = parse_deadline(deadline_raw, reference_date=reference_date)
        if parsed.get("date") and _is_blank(row["deadline_date"]):
            updates["deadline_date"] = parsed["date"]
            if parsed.get("mode"):
                updates["deadline_mode"] = parsed["mode"]
            updates["deadline_evidence"] = "detail_page"
            updates["deadline_parse_reason"] = (
                f"Parsed from the posting's own page: {deadline_raw[:160]}")
        elif parsed.get("mode") and _is_blank(row["deadline_mode"]):
            updates["deadline_mode"] = parsed["mode"]
            updates["deadline_evidence"] = "detail_page"
            updates["deadline_parse_reason"] = (
                f"Mode only, from the posting's own page: {deadline_raw[:160]}")

    official = clean_text(fields.get("official_url"))
    if official.startswith(("http://", "https://")):
        observed.append("official_url")
        normalized_url = normalize_url(official) or official
        if _is_blank(row["official_url"]):
            updates["official_url"] = normalized_url

    salary = clean_text(fields.get("salary"))
    if salary:
        observed.append("salary_raw")
        if _is_blank(row["salary_raw"]):
            updates["salary_raw"] = salary[:400]
            parsed_salary = parse_salary(salary) or {}
            for column, key in (("salary_min", "min"), ("salary_max", "max"),
                                ("salary_currency", "currency"), ("salary_period", "period")):
                if parsed_salary.get(key) is not None:
                    updates[column] = parsed_salary[key]

    # The body, and the fields that exist only inside it.
    #
    # The shared parser falls back to the page's raw text when a page carries
    # no structured description, so `description` is non-empty even for a page
    # whose entire content is a heading. Requiring a real length keeps "we
    # opened it and it said nothing" a reachable answer -- without it every
    # readable page counts as carrying a body, `empty` never happens, and the
    # queue re-reads pages that will never say anything.
    body = clean_text(fields.get("description"))
    if body and len(body) >= MIN_BODY_CHARS:
        observed.append("description_excerpt")
        held = clean_text(row["description_excerpt"] if "description_excerpt" in row.keys() else "")
        # Longer wins rather than newer: the listing blurb and the posting are
        # the same source describing the same job, and the fuller text is the
        # one every derived field wants. Equal length changes nothing.
        if len(body) > len(held):
            updates["description_excerpt"] = body[:DETAIL_TEXT_LIMIT]

        combined = " ".join(
            item for item in (
                clean_text(row["title_raw"] if "title_raw" in row.keys() else ""),
                clean_text(row["department"] if "department" in row.keys() else ""),
                body,
            ) if item
        )
        verdict = classify_visa(combined)
        if verdict["status"] != "unknown":
            observed.append("visa_status")
            held_status = row["visa_status"] if "visa_status" in row.keys() else None
            if (held_status or "unknown") != verdict["status"]:
                updates["visa_status"] = verdict["status"]
            if verdict["evidence"] and _is_blank(
                    row["visa_text"] if "visa_text" in row.keys() else None):
                updates["visa_text"] = verdict["evidence"]
        if verdict["pathways"]:
            observed.append("visa_pathways")
            if _is_blank(row["visa_pathways"] if "visa_pathways" in row.keys() else None):
                updates["visa_pathways"] = ",".join(verdict["pathways"])
    return observed, updates


def _write_provenance(conn, row, updates, url):
    """Record which page supplied each filled field.

    The repair audit says a change happened; provenance says which observation
    is currently behind the value. A reader asking "where did this deadline
    come from" needs the second, and only the audit was being written.
    """
    for field, value in updates.items():
        conn.execute(
            "UPDATE job_field_provenance SET is_current=0 WHERE job_id=? AND field_name=?",
            (row["job_id"], field))
        conn.execute("""
            INSERT INTO job_field_provenance
              (job_id,field_name,value_text,source_id,source_job_id,source_url,
               evidence_text,captured_at,is_current)
            VALUES (?,?,?,?,?,?,?,?,1)
        """, (row["job_id"], field, None if value is None else str(value)[:500],
              row["source_id"], row["source_job_id"], url,
              "detail page read by the bounded enrichment pass", now_utc()))


def _refresh_status(conn, job_id, deadline_date):
    """A newly learned deadline can change whether the job is still open.

    Leaving the status at its listing-derived value would show a competition
    that closed last month as open, which is the one thing a deadline is for.
    """
    current = conn.execute("SELECT status FROM jobs WHERE id=?", (job_id,)).fetchone()
    if current is None:
        return
    today = now_utc()[:10]
    if not deadline_date:
        return
    if str(deadline_date) < today:
        new_status = "closed"
    elif str(deadline_date) <= (datetime.now(timezone.utc) + timedelta(days=14)
                                ).date().isoformat():
        new_status = "closing_soon"
    else:
        new_status = "open"
    if new_status == current["status"]:
        return
    conn.execute("UPDATE jobs SET status=?,updated_at=? WHERE id=?",
                 (new_status, now_utc(), job_id))
    conn.execute("""
        INSERT INTO job_status_history (job_id,status,observed_at,change_reason)
        VALUES (?,?,?,?)
    """, (job_id, new_status, now_utc(),
          f"Recomputed after the posting's own page gave a deadline of {deadline_date}."))


def enrich_source_details(conn, source_name, limit=50, sleep=None):
    """Read up to ``limit`` unread detail pages, stopping cleanly on a refusal.

    Returns a summary; raises nothing on a challenge -- the caller gets
    ``stopped_reason`` and can rerun later from where this left off.
    """
    adapter = _adapter(source_name)
    if not getattr(adapter, "supports_detail_enrichment", True):
        return {"source": source_name, "considered": 0, "read": 0, "updated": 0,
                "empty": 0, "errors": 0, "fields_filled": {},
                "stopped_reason": (
                    f"{source_name} does not expose per-posting detail pages; every record "
                    "points at the same listing anchor, so a detail pass would request one "
                    "page once per row"),
                "pending_after": pending_count(conn, source_name)}
    rows = _pending_rows(conn, source_name, limit)
    stats = {"source": source_name, "considered": len(rows), "read": 0, "updated": 0,
             "empty": 0, "errors": 0, "stopped_reason": None,
             "fields_filled": {field: 0 for field in ENRICHABLE}}
    for row in rows:
        url = row["source_url"]
        if not url:
            _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                            STATUS_ERROR, reason="no source URL recorded",
                            attempt_count=row["attempt_count"])
            stats["errors"] += 1
            continue
        try:
            response = adapter.request(url)
        except (CrawlBudgetExhaustedError, RobotsDisallowedError) as exc:
            # A policy refusal. Record it against this posting and stop: the
            # rest of the queue would be refused too, and spending the attempts
            # would only fill the table with the same reason.
            _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                            STATUS_REFUSED, reason=str(exc)[:300],
                            attempt_count=row["attempt_count"])
            stats["stopped_reason"] = f"refused: {str(exc)[:200]}"
            break
        except NonRetryableAdapterError as exc:
            _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                            STATUS_ERROR, reason=str(exc)[:300],
                            attempt_count=row["attempt_count"])
            stats["errors"] += 1
            continue
        except Exception as exc:  # transport failure: this posting only
            _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                            STATUS_ERROR, reason=f"{type(exc).__name__}: {str(exc)[:260]}",
                            attempt_count=row["attempt_count"])
            stats["errors"] += 1
            continue

        body = response.text or ""
        # Archive before parsing. The parser will change over the next four
        # years; this page will not exist to be re-read. A challenge page is
        # archived too -- what a board served instead of the posting is part of
        # the record of why coverage has a hole here.
        try:
            raw_archive.record_observation(
                conn, kind=raw_archive.KIND_DETAIL, source_url=url, payload=body,
                source_id=row["source_id"], source_job_id=row["source_job_id"],
                http_status=getattr(response, "status_code", None),
                parser_version=PARSER_VERSION)
        except Exception as error:  # noqa: BLE001 - a storage fault must not lose the read
            stats.setdefault("archive_errors", []).append(f"{url}: {error!r}")

        challenge = getattr(adapter, "_challenge_reason", lambda _html: None)(body)
        if challenge:
            # Not evidence about this posting. The board substituted an
            # interstitial for the page, so stop and keep the progress.
            _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                            STATUS_CHALLENGED, http_status=getattr(response, "status_code", None),
                            reason=str(challenge)[:300],
                            attempt_count=row["attempt_count"])
            stats["stopped_reason"] = f"challenged: {challenge}"
            break

        fields = _parse_public_detail(body, source_name, url) or {}
        observed, updates = _derived_updates(row, fields, reference_date=now_utc()[:10])
        found = sorted(updates)
        if updates:
            assignments = ",".join(f"{key}=?" for key in updates)
            conn.execute(f"UPDATE jobs SET {assignments},updated_at=? WHERE id=?",
                         (*updates.values(), now_utc(), row["job_id"]))
            for key in updates:
                stats["fields_filled"][key] = stats["fields_filled"].get(key, 0) + 1
            _write_provenance(conn, row, updates, url)
            conn.execute("""
                INSERT INTO faculty_job_repair_audit
                  (observed_at,action,job_id,source_id,source_job_id,old_value,new_value,reason)
                VALUES (?,?,?,?,?,?,?,?)
            """, (now_utc(), "detail_page_enrichment", row["job_id"], row["source_id"],
                  row["source_job_id"],
                  json.dumps({key: (row[key] if key in row.keys() else None)
                              for key in updates}, ensure_ascii=False),
                  json.dumps(updates, ensure_ascii=False),
                  f"Read the posting's own page at {url}. Only fields the job left blank were "
                  "filled; listing values and manual repairs are not overwritten."))
            if "deadline_date" in updates:
                _refresh_status(conn, row["job_id"], updates["deadline_date"])
            stats["updated"] += 1
        else:
            stats["empty"] += 1
        # The page was read. Whether it changed anything is a separate fact:
        # a posting whose deadline we already hold is not a posting whose page
        # said nothing, and recording it as `empty` erased that distinction.
        page_carried_something = bool(observed)
        _record_attempt(conn, row["source_id"], row["source_job_id"], row["job_id"],
                        STATUS_OK if page_carried_something else STATUS_EMPTY,
                        http_status=getattr(response, "status_code", None),
                        observed=observed, updated=found,
                        attempt_count=row["attempt_count"],
                        reason=(None if found else (
                            "page read; it carried " + ", ".join(observed)
                            + " and the job already held those values"
                            if observed else "page read; it carried none of these fields")))
        stats["read"] += 1
        if sleep:
            import time
            time.sleep(float(sleep))
    conn.commit()
    stats["pending_after"] = pending_count(conn, source_name)
    return stats


def detail_progress(conn, source_name):
    """What has been attempted for a source, by outcome."""
    rows = conn.execute("""
        SELECT f.status, COUNT(*) AS n FROM job_detail_fetches f
        JOIN sources s ON s.id = f.source_id
        WHERE s.name = ? GROUP BY f.status ORDER BY n DESC
    """, (source_name,)).fetchall()
    return {"source": source_name,
            "by_status": {row["status"]: int(row["n"]) for row in rows},
            "pending": pending_count(conn, source_name)}


__all__ = ["DetailEnrichmentStopped", "ENRICHABLE", "detail_progress",
           "enrich_source_details", "pending_count"]
