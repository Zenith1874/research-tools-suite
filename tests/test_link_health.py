# -*- coding: utf-8 -*-
"""Link checking, and the one distinction it exists to protect.

A 404 is about the resource; a 502 is about the server. When poms.org went
down, 113 stored links stopped opening at once -- and reading that as "113
postings withdrawn" would have been wrong in the most damaging way available,
because the site came back with every posting intact.

So these tests are mostly about what a failed check is *not* allowed to mean.
"""

import sqlite3
import tempfile
import unittest
import urllib.error
from pathlib import Path

from services.link_health import (
    STATE_BLOCKED, STATE_GONE, STATE_OK, STATE_SERVER_ERROR, STATE_UNREACHABLE,
    check_url, classify_status, ensure_tables, health_summary, host_of,
    host_rollup, pending_links, record_check,
)


class _Response:
    def __init__(self, status):
        self.status = status

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


def opener_returning(status):
    def _open(request, timeout=None):
        return _Response(status)
    return _open


def opener_raising(*outcomes):
    """Replay a sequence of attempts: raise an exception, or return a response."""
    calls = {"n": 0}

    def _open(request, timeout=None):
        index = min(calls["n"], len(outcomes) - 1)
        calls["n"] += 1
        outcome = outcomes[index]
        if isinstance(outcome, BaseException):
            raise outcome
        return outcome
    return _open


def http_error(code):
    return urllib.error.HTTPError("http://x", code, "err", {}, None)


class ClassificationTests(unittest.TestCase):
    def test_a_404_is_about_the_resource(self):
        self.assertEqual(STATE_GONE, classify_status(404))
        self.assertEqual(STATE_GONE, classify_status(410))

    def test_a_5xx_is_about_the_server_not_the_posting(self):
        # The poms.org case: 502 on the file, the listing page, and the site
        # root alike.
        for code in (500, 502, 503, 504):
            with self.subTest(code=code):
                self.assertEqual(STATE_SERVER_ERROR, classify_status(code))

    def test_a_refusal_is_not_an_absence(self):
        self.assertEqual(STATE_BLOCKED, classify_status(403))
        self.assertEqual(STATE_BLOCKED, classify_status(401))
        self.assertEqual(STATE_BLOCKED, classify_status(429),
                         "rate limiting is a refusal, not a missing posting")

    def test_a_redirect_is_a_working_link(self):
        self.assertEqual(STATE_OK, classify_status(301))
        self.assertEqual(STATE_OK, classify_status(200))

    def test_no_status_at_all_is_unreachable(self):
        self.assertEqual(STATE_UNREACHABLE, classify_status(None))


class ProbeTests(unittest.TestCase):
    def test_a_working_link_reports_ok(self):
        state, status, _note = check_url("https://example.edu/x",
                                         opener=opener_returning(200))
        self.assertEqual((STATE_OK, 200), (state, status))

    def test_a_head_refusal_falls_back_to_a_ranged_get(self):
        # Several publishers answer HEAD with 403 and serve the file fine. DOL
        # does exactly this. Calling that link dead would be wrong.
        state, status, _note = check_url(
            "https://example.edu/x",
            opener=opener_raising(http_error(403), _Response(206)))
        self.assertEqual(STATE_OK, state)
        self.assertEqual(206, status)

    def test_a_5xx_is_not_retried_with_another_verb(self):
        # It is already definitive, and re-asking just doubles the load on a
        # host that is visibly struggling.
        state, status, _note = check_url("https://www.poms.org/x.pdf",
                                         opener=opener_raising(http_error(502)))
        self.assertEqual((STATE_SERVER_ERROR, 502), (state, status))

    def test_a_404_is_not_retried_either(self):
        state, status, _note = check_url("https://example.edu/x",
                                         opener=opener_raising(http_error(404)))
        self.assertEqual((STATE_GONE, 404), (state, status))

    def test_a_transport_failure_is_unreachable_with_the_reason(self):
        state, status, note = check_url(
            "https://nope.invalid/x",
            opener=opener_raising(urllib.error.URLError("name resolution failed")))
        self.assertEqual(STATE_UNREACHABLE, state)
        self.assertIsNone(status)
        self.assertIn("name resolution", note)


class HostRollupTests(unittest.TestCase):
    def test_a_uniformly_failing_host_is_reported_as_one_fact(self):
        rows = [("www.poms.org", STATE_SERVER_ERROR)] * 113
        report = host_rollup(rows)["www.poms.org"]
        self.assertTrue(report["host_down"])
        self.assertEqual(STATE_SERVER_ERROR, report["host_down_state"])
        self.assertIn("not 113 facts", report["note"])

    def test_a_host_with_one_working_link_is_not_down(self):
        rows = [("example.edu", STATE_GONE)] * 5 + [("example.edu", STATE_OK)]
        self.assertFalse(host_rollup(rows)["example.edu"]["host_down"])

    def test_mixed_failures_are_not_a_host_outage(self):
        # A host with some 404s and some 403s is not simply down; the 404s are
        # still about their own postings.
        rows = [("example.edu", STATE_GONE), ("example.edu", STATE_BLOCKED)]
        self.assertFalse(host_rollup(rows)["example.edu"]["host_down"])

    def test_a_single_dead_link_is_not_a_host_outage(self):
        # One 404 on a host must stay a fact about that posting.
        self.assertFalse(host_rollup([("example.edu", STATE_GONE)])["example.edu"]["host_down"])

    def test_host_of_reads_the_hostname(self):
        self.assertEqual("www.poms.org",
                         host_of("https://www.poms.org/sites/default/files/x.pdf"))
        self.assertEqual("", host_of(None))


class StoreTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.conn = sqlite3.connect(str(Path(self.dir.name) / "f.db"))
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("CREATE TABLE jobs (id INTEGER PRIMARY KEY, status TEXT)")
        ensure_tables(self.conn)

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, url, state, status=None, job_id=1, at="2026-09-03T00:00:00Z"):
        self.conn.execute("INSERT OR IGNORE INTO jobs (id,status) VALUES (?,'open')",
                          (job_id,))
        record_check(self.conn, job_id, 1, url, state, status, checked_at=at)
        self.conn.commit()

    def test_a_host_outage_does_not_count_as_postings_with_dead_links(self):
        for n in range(3):
            self.add(f"https://www.poms.org/{n}.pdf", STATE_SERVER_ERROR, 502, job_id=n + 1)
        summary = health_summary(self.conn)
        self.assertIn("www.poms.org", summary["hosts_down"])
        self.assertEqual(0, summary["postings_with_a_dead_link"],
                         "a site being down is not postings being withdrawn")

    def test_a_genuine_404_on_a_healthy_host_is_counted(self):
        self.add("https://example.edu/live", STATE_OK, 200, job_id=1)
        self.add("https://example.edu/dead", STATE_GONE, 404, job_id=2)
        summary = health_summary(self.conn)
        self.assertEqual(1, summary["postings_with_a_dead_link"])

    def test_only_the_latest_check_of_a_url_counts(self):
        self.add("https://example.edu/x", STATE_SERVER_ERROR, 502,
                 at="2026-09-01T00:00:00Z")
        self.add("https://example.edu/x", STATE_OK, 200, at="2026-09-03T00:00:00Z")
        summary = health_summary(self.conn)
        self.assertEqual(1, summary["checked_links"])
        self.assertEqual({STATE_OK: 1}, summary["by_state"])

    def test_the_summary_states_what_a_failure_does_not_mean(self):
        self.add("https://example.edu/x", STATE_SERVER_ERROR, 502)
        note = health_summary(self.conn)["reading_note"]
        self.assertIn("never changes a job's status", note)

    def test_a_link_check_leaves_job_status_alone(self):
        # The rule that keeps a publisher's bad afternoon from closing
        # hundreds of live postings.
        self.add("https://example.edu/x", STATE_GONE, 404)
        self.assertEqual("open",
                         self.conn.execute("SELECT status FROM jobs WHERE id=1")
                         .fetchone()["status"])


if __name__ == "__main__":
    unittest.main()
