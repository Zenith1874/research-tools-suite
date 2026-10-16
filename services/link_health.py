# -*- coding: utf-8 -*-
"""Whether the link on a posting still opens, and why it does not.

Every posting carries a ``source_url`` that a person will eventually click.
Nothing has ever checked that those still resolve, so a board can reorganise
its files or fall over and the site keeps handing out addresses that go
nowhere.

**The distinction the whole module is built around is 404 versus 5xx.** A 404
is about the resource: the file is gone. A 502 is about the server: it is
failing, and says nothing at all about whether the posting exists. When
poms.org went down, 113 stored links stopped opening -- and reading that as
"113 postings withdrawn" would have been completely wrong. The site came back
with the postings intact.

So the states are kept apart, and only one of them is evidence about a posting:

``ok``            2xx or 3xx. The link opens.
``gone``          404 or 410. The resource is absent -- this is about the posting.
``server_error``  5xx. The host is failing. Not evidence about the posting.
``blocked``       401/403, or robots.txt refuses us. We are not permitted to look.
``unreachable``   DNS failure, timeout, connection reset. We could not ask.

And a host-level roll-up on top: when every link on a host fails the same way,
that is one fact about the host, not N facts about N postings.

**This never changes a job's status.** A link check is not a closure signal,
and wiring it to one would let a bad afternoon at a publisher close hundreds of
live postings.
"""

import re
import socket
import urllib.error
import urllib.request
from collections import defaultdict
from datetime import datetime, timezone
from urllib.parse import urlparse

STATE_OK = "ok"
STATE_GONE = "gone"
STATE_SERVER_ERROR = "server_error"
STATE_BLOCKED = "blocked"
STATE_UNREACHABLE = "unreachable"

STATES = (STATE_OK, STATE_GONE, STATE_SERVER_ERROR, STATE_BLOCKED, STATE_UNREACHABLE)

# Only this one says anything about the posting itself.
STATES_ABOUT_THE_POSTING = (STATE_GONE,)

USER_AGENT = ("research-tools-suite/academic-career (+local research workstation; "
              "link health check, no content stored)")

# A host is called down when this many of its links fail and they all fail the
# same non-ok way. Two is enough to distinguish a host outage from one missing
# file, and requiring unanimity keeps a genuinely deleted posting visible.
HOST_DOWN_MIN_LINKS = 2


def now_utc():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def ensure_tables(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS link_checks (
            id            INTEGER PRIMARY KEY,
            job_id        INTEGER NOT NULL,
            source_id     INTEGER,
            source_url    TEXT NOT NULL,
            host          TEXT,
            checked_at    TEXT NOT NULL,
            http_status   INTEGER,
            state         TEXT NOT NULL,
            note          TEXT,
            FOREIGN KEY (job_id) REFERENCES jobs(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_link_checks_job "
                 "ON link_checks(job_id, checked_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_link_checks_host "
                 "ON link_checks(host, checked_at DESC)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_link_checks_state "
                 "ON link_checks(state, checked_at DESC)")
    return conn


def host_of(url):
    return (urlparse(url or "").hostname or "").lower()


def classify_status(status):
    """Map an HTTP status onto a state."""
    if status is None:
        return STATE_UNREACHABLE
    if 200 <= status < 400:
        return STATE_OK
    if status in (404, 410):
        return STATE_GONE
    if status in (401, 403):
        return STATE_BLOCKED
    if status >= 500:
        return STATE_SERVER_ERROR
    # 4xx that is neither absence nor refusal -- 429, 400, and friends. The
    # request was rejected, which is not the posting being gone.
    return STATE_BLOCKED


def check_url(url, *, timeout=20, opener=None):
    """Probe one URL. Returns ``(state, http_status, note)``.

    Tries HEAD first because a link check does not need the body, then falls
    back to a ranged GET: several publishers answer HEAD with 403 while serving
    the file perfectly well, and treating that as `blocked` would report a
    healthy link as unreachable.
    """
    opener = opener or urllib.request.urlopen
    attempts = (
        ("HEAD", {"User-Agent": USER_AGENT}),
        ("GET", {"User-Agent": USER_AGENT, "Range": "bytes=0-0"}),
    )
    last = (STATE_UNREACHABLE, None, "no attempt completed")
    for method, headers in attempts:
        request = urllib.request.Request(url, headers=headers, method=method)
        try:
            with opener(request, timeout=timeout) as response:
                status = getattr(response, "status", None)
                return classify_status(status), status, None
        except urllib.error.HTTPError as exc:
            state = classify_status(exc.code)
            last = (state, exc.code, f"{method} -> HTTP {exc.code}")
            if state in (STATE_OK, STATE_GONE, STATE_SERVER_ERROR):
                # Definitive: no point re-asking with another verb.
                return last
            # 401/403/429 may be a refusal of the verb rather than the URL.
            continue
        except (urllib.error.URLError, socket.timeout, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            last = (STATE_UNREACHABLE, None, f"{type(exc).__name__}: {str(reason)[:160]}")
            continue
    return last


def pending_links(conn, *, scope_sql="1=1", limit=None, host=None, recheck_after=None):
    """Active links owed a check, newest-unchecked first.

    A link already checked since ``recheck_after`` is skipped, so a run can be
    resumed without re-probing what it just did.
    """
    args = []
    where = ["js.active = 1", "js.source_url IS NOT NULL", "js.source_url != ''",
             scope_sql]
    clause = " AND ".join(part for part in where if part)
    sql = f"""
        SELECT js.job_id, js.source_id, js.source_url,
               (SELECT MAX(checked_at) FROM link_checks c
                 WHERE c.source_url = js.source_url) AS last_checked
        FROM job_sources js
        JOIN jobs j ON j.id = js.job_id
        WHERE {clause}
        GROUP BY js.source_url
        ORDER BY last_checked IS NOT NULL, last_checked
    """
    rows = conn.execute(sql, args).fetchall()
    if host:
        # Matched on the parsed hostname, not a SQL prefix: a bare "poms.org"
        # has to find "www.poms.org", and a LIKE on the raw URL never did.
        wanted = host.lower().lstrip(".")
        rows = [r for r in rows
                if host_of(r["source_url"]) == wanted
                or host_of(r["source_url"]).endswith("." + wanted)]
    if recheck_after:
        rows = [r for r in rows
                if not r["last_checked"] or r["last_checked"] < recheck_after]
    return rows[:limit] if limit else rows


def record_check(conn, job_id, source_id, url, state, http_status, note=None,
                 checked_at=None):
    conn.execute("""
        INSERT INTO link_checks
          (job_id, source_id, source_url, host, checked_at, http_status, state, note)
        VALUES (?,?,?,?,?,?,?,?)
    """, (job_id, source_id, url, host_of(url), checked_at or now_utc(),
          http_status, state, note))


def host_rollup(rows):
    """Group outcomes by host and mark hosts that are uniformly failing.

    ``rows`` is an iterable of ``(host, state)``. A host whose links all fail
    the same non-ok way is reported as down, and its links are then evidence
    about the host rather than about the postings.
    """
    by_host = defaultdict(lambda: defaultdict(int))
    for host, state in rows:
        by_host[host][state] += 1

    report = {}
    for host, counts in by_host.items():
        total = sum(counts.values())
        failing = {s: n for s, n in counts.items() if s != STATE_OK}
        down = (counts.get(STATE_OK, 0) == 0
                and total >= HOST_DOWN_MIN_LINKS
                and len(failing) == 1)
        report[host] = {
            "links": total,
            "by_state": dict(counts),
            "host_down": down,
            "host_down_state": next(iter(failing)) if down else None,
            "note": (
                f"every one of this host's {total} checked links failed the same way "
                f"({next(iter(failing))}). That is one fact about the host, not "
                f"{total} facts about {total} postings."
                if down else None),
        }
    return report


def health_summary(conn, since=None):
    """The latest state of every checked link, plus the host roll-up."""
    rows = conn.execute("""
        SELECT c.host, c.state, c.http_status, c.source_url, c.checked_at
        FROM link_checks c
        JOIN (SELECT source_url, MAX(checked_at) AS latest
                FROM link_checks GROUP BY source_url) newest
          ON newest.source_url = c.source_url AND newest.latest = c.checked_at
    """).fetchall()
    by_state = defaultdict(int)
    for row in rows:
        by_state[row["state"]] += 1
    hosts = host_rollup((row["host"], row["state"]) for row in rows)
    down = {h: v for h, v in hosts.items() if v["host_down"]}
    # Links that are broken *and* not explained by their host being down.
    genuinely_gone = sum(
        1 for row in rows
        if row["state"] == STATE_GONE and not hosts.get(row["host"], {}).get("host_down"))
    return {
        "checked_links": len(rows),
        "by_state": dict(by_state),
        "hosts_down": down,
        "postings_with_a_dead_link": genuinely_gone,
        "last_checked": max((row["checked_at"] for row in rows), default=None),
        "reading_note": (
            "Only `gone` (404/410) says anything about a posting. `server_error` "
            "means the publisher's site is failing, `blocked` means we are not "
            "permitted to look, and `unreachable` means we could not ask -- none "
            "of the three is evidence that a posting was withdrawn. A link check "
            "never changes a job's status."),
    }


__all__ = ["HOST_DOWN_MIN_LINKS", "STATES", "STATES_ABOUT_THE_POSTING",
           "STATE_BLOCKED", "STATE_GONE", "STATE_OK", "STATE_SERVER_ERROR",
           "STATE_UNREACHABLE", "check_url", "classify_status", "ensure_tables",
           "health_summary", "host_of", "host_rollup", "pending_links",
           "record_check"]
