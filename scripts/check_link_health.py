# -*- coding: utf-8 -*-
"""Check whether the URL on each posting still opens.

Nothing had ever verified the addresses this site hands out. The prompt was
poms.org returning 502 on every one of our 113 stored links at once -- which
looks like mass withdrawal and was a server outage.

So the run is deliberately gentle and deliberately literal:

* one request per host at a time, with a pause, and HEAD before a ranged GET;
* a 5xx stops that host for the rest of the run, because a struggling server
  does not need another 112 requests to tell us the same thing;
* every outcome is stored with its own state, and **no outcome changes a job's
  status**.

Usage:
    python scripts/check_link_health.py
    python scripts/check_link_health.py --limit 400 --apply
"""

import argparse
import sqlite3
import sys
import time
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services import link_health  # noqa: E402
from services.faculty_jobs_service import (  # noqa: E402
    FACULTY_DB_PATH, FACULTY_JOBS_SCHEMA_VERSION, ensure_faculty_jobs_tables,
)
from services.faculty_jobs_write_guard import (  # noqa: E402
    guarded_write, open_read_only, postflight, preflight,
)


def survey(db_path, host=None, limit=None):
    conn = open_read_only(db_path)
    conn.row_factory = sqlite3.Row
    try:
        version = conn.execute("PRAGMA user_version").fetchone()[0]
        if int(version) != int(FACULTY_JOBS_SCHEMA_VERSION):
            raise SystemExit(f"schema user_version={version}, expected "
                             f"{FACULTY_JOBS_SCHEMA_VERSION}; run a write-mode "
                             "command to migrate first")
        return link_health.pending_links(conn, host=host, limit=limit)
    finally:
        conn.close()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--limit", type=int, default=300,
                        help="maximum distinct URLs to check this run")
    parser.add_argument("--host", default=None, help="restrict to one host")
    parser.add_argument("--sleep", type=float, default=0.7,
                        help="pause between requests to the same host")
    parser.add_argument("--timeout", type=int, default=20)
    parser.add_argument("--host-failure-probes", type=int, default=3,
                        help="how many 5xx on one host before it is abandoned "
                             "for the rest of the run")
    parser.add_argument("--apply", action="store_true",
                        help="actually probe and write; without it nothing happens")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args()

    links = survey(args.db, host=args.host, limit=args.limit)
    by_host = defaultdict(int)
    for row in links:
        by_host[link_health.host_of(row["source_url"])] += 1
    print(f"distinct URLs owed a check: {len(links)}")
    for host, count in sorted(by_host.items(), key=lambda kv: -kv[1])[:12]:
        print(f"  {count:>5}  {host}")
    if not args.apply:
        print("\nno --apply: nothing was requested and nothing was written")
        return

    inventory = preflight(args.db, "link_health")
    outcomes = []
    stopped_hosts = {}
    # One 502 could be a single broken file; a host verdict needs more than one
    # path to fail. Three is enough to tell a site outage from a bad link, and
    # is still 3 requests rather than 113.
    server_errors = defaultdict(int)
    with guarded_write():
        ensure_faculty_jobs_tables(args.db)
        conn = sqlite3.connect(str(args.db), timeout=60)
        conn.row_factory = sqlite3.Row
        try:
            for row in links:
                url = row["source_url"]
                host = link_health.host_of(url)
                if host in stopped_hosts:
                    # The host already told us it is failing. Recording the same
                    # verdict without asking keeps the run honest about what was
                    # observed, so it is skipped rather than assumed.
                    continue
                state, status, note = link_health.check_url(url, timeout=args.timeout)
                link_health.record_check(conn, row["job_id"], row["source_id"],
                                         url, state, status, note)
                outcomes.append((host, state))
                if state == link_health.STATE_SERVER_ERROR:
                    server_errors[host] += 1
                    if server_errors[host] >= args.host_failure_probes:
                        stopped_hosts[host] = status
                        print(f"  {host}: {server_errors[host]} paths returned "
                              f"{status}; treating it as a host outage and "
                              f"leaving the rest of its links alone", flush=True)
                # Commit as we go. A long network run that commits only at the
                # end loses everything to any interruption, and a probe already
                # made is worth keeping.
                if len(outcomes) % 25 == 0:
                    conn.commit()
                    print(f"  ... {len(outcomes)} checked", flush=True)
                if args.sleep:
                    time.sleep(args.sleep)
            conn.commit()
        finally:
            conn.close()

    print("\n" + "=" * 66)
    tally = defaultdict(int)
    for _host, state in outcomes:
        tally[state] += 1
    for state, count in sorted(tally.items(), key=lambda kv: -kv[1]):
        print(f"  {state:16}{count}")
    rollup = link_health.host_rollup(outcomes)
    down = {h: v for h, v in rollup.items() if v["host_down"]}
    if down:
        print("\nhosts failing uniformly (one fact about the host, not about "
              "each posting):")
        for host, info in down.items():
            print(f"  {host:34}{info['links']:>5} links  {info['host_down_state']}")
    if stopped_hosts:
        print("\nstopped early, unchecked links remain:",
              ", ".join(f"{h} ({s})" for h, s in stopped_hosts.items()))
    print("\nNo job status was changed. A link that does not open is not a "
          "posting that was withdrawn.")
    postflight(args.db, inventory)


if __name__ == "__main__":
    main()
