# -*- coding: utf-8 -*-
"""Folding one vacancy that two boards both carry.

A school syndicates a posting, the canonical key is built from the application
URL and a fingerprint of the listing text, so each board's copy became its own
row. That is a large part of why the coverage matrix reported 97-100% of
postings as single-sourced -- a number that read as a fact about the market and
was partly an artefact of our own keying.

The costs are asymmetric and these tests lean the same way the code does.
Merging two genuinely distinct vacancies erases one and understates a market
nobody can re-observe later; failing to merge overcounts, which is visible in
the matrix and fixable with both rows still on the table. So most of what
follows pins down the refusals.
"""

import json
import sqlite3
import tempfile
import unittest
from pathlib import Path

from services.cross_source_merge import (
    BASIS_BOARD_ID, BASIS_TITLE, REASON_ALREADY_MERGED, REASON_AMBIGUOUS,
    REASON_CONFIRMED_DISTINCT, REASON_GENERIC, apply_all, assess, board_id,
    candidate_groups,
    is_generic_title, plan,
)
from services.faculty_jobs_scope import catalogue_sql
from services.faculty_jobs_service import ensure_faculty_jobs_tables

NOW = "2026-09-05T00:00:00Z"


class GenericTitleTests(unittest.TestCase):
    def test_a_bare_rank_is_generic(self):
        # One school can advertise two of these on one day in two departments.
        for title in ("assistant professor", "Associate Professor",
                      "professor", "lecturer", "tenure-track professor",
                      "open rank faculty", "adjunct instructor",
                      "faculty position", "assistant professors"):
            with self.subTest(title=title):
                self.assertTrue(is_generic_title(title))

    def test_a_title_naming_a_field_is_not_generic(self):
        for title in ("assistant professor of finance",
                      "professor of marketing analytics",
                      "lecturer in operations management",
                      "assistant professor, accounting"):
            with self.subTest(title=title):
                self.assertFalse(is_generic_title(title))


class Fixture:
    """Shared setup only. Not a TestCase, so the rule tests below run once.

    Subclassing the class that holds the tests re-ran all of them under every
    later fixture -- 60 tests where 30 were distinct, and each setUp builds a
    database through the whole migration chain.
    """

    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.db = str(Path(self.dir.name) / "f.db")
        ensure_faculty_jobs_tables(self.db)
        self.conn = sqlite3.connect(self.db)
        self.conn.row_factory = sqlite3.Row
        for row_id, name in ((1, "Example University"), (2, "Other University")):
            self.conn.execute(
                "INSERT INTO institutions (id,official_name,normalized_name,country,"
                "created_at,updated_at) VALUES (?,?,?,'United States',?,?)",
                (row_id, name, name.lower(), NOW, NOW))
        self.sources = {row["name"]: row["id"] for row in
                        self.conn.execute("SELECT id,name FROM sources")}
        self.conn.commit()

    def tearDown(self):
        self.conn.close()
        self.dir.cleanup()

    def add(self, job_id, title, source, *, institution=1, body="Body text.",
            discipline="Finance", deadline=None, first_seen=NOW, last_seen=NOW,
            source_url=None):
        self.conn.execute("""
            INSERT INTO jobs (id,canonical_key,title_raw,title_normalized,institution_id,
                              status,business_scope,derived_quality,faculty_market_eligible,
                              faculty_market_role,description_excerpt,discipline_primary,
                              deadline_date,first_seen_at,last_seen_at,created_at,updated_at)
            VALUES (?,?,?,?,?,'open','business_school','accepted',1,'faculty',?,?,?,?,?,?,?)
        """, (job_id, f"key-{job_id}", title, title.lower(), institution,
              body, discipline, deadline, first_seen, last_seen, NOW, NOW))
        self.conn.execute("""
            INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,
                                     first_seen,last_seen)
            VALUES (?,?,?,?,1,?,?)
        """, (job_id, self.sources[source], f"{source}-{job_id}",
              source_url or f"https://{source}.example/{job_id}", first_seen, last_seen))
        self.conn.commit()

    def verdicts(self):
        return [assess(self.conn, group) for group in candidate_groups(self.conn)]

    def only(self):
        found = self.verdicts()
        self.assertEqual(1, len(found), "expected exactly one candidate group")
        return found[0]


class MergeTests(Fixture, unittest.TestCase):
    # --- what merges -------------------------------------------------------

    def test_the_same_specific_title_at_one_school_on_two_boards_merges(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed")
        verdict = self.only()
        self.assertTrue(verdict["merge"])
        self.assertEqual({1, 2}, {verdict["keep"], *verdict["absorb"]})

    def test_the_row_holding_the_most_posting_text_survives(self):
        # A merge must never cost us the fullest description we hold, and the
        # boards carry very different amounts of the same posting.
        self.add(1, "Assistant Professor of Finance", "higheredjobs", body="Short blurb.")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="The department invites applications. " * 100)
        verdict = self.only()
        self.assertEqual(2, verdict["keep"])
        self.assertEqual([1], verdict["absorb"])

    # --- what does not, and why -------------------------------------------

    def test_a_bare_rank_is_left_alone(self):
        self.add(1, "Assistant Professor", "higheredjobs")
        self.add(2, "Assistant Professor", "inside_higher_ed")
        verdict = self.only()
        self.assertFalse(verdict["merge"])
        self.assertEqual(REASON_GENERIC, verdict["reason"])

    def test_a_source_listing_the_title_twice_makes_the_pairing_a_guess(self):
        # Community colleges really do advertise seven "Adjunct Faculty,
        # Accounting" posts at once, each with its own id on the board. There
        # is no way to know which of them the other board's single listing is.
        self.add(1, "Adjunct Faculty, Accounting", "higheredjobs")
        self.add(2, "Adjunct Faculty, Accounting", "higheredjobs")
        self.add(3, "Adjunct Faculty, Accounting", "inside_higher_ed")
        verdict = self.only()
        self.assertFalse(verdict["merge"])
        self.assertEqual(REASON_AMBIGUOUS, verdict["reason"])

    def test_two_schools_with_the_same_title_are_not_one_job(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs", institution=1)
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed", institution=2)
        self.assertEqual([], self.verdicts())

    def test_one_board_listing_two_different_titles_is_not_a_group(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.add(2, "Assistant Professor of Marketing", "inside_higher_ed")
        self.assertEqual([], self.verdicts())

    def test_the_same_board_twice_is_never_a_cross_source_merge(self):
        # Two rows from one board are two vacancies that board listed
        # separately. 153 such groups exist and none of them are our error.
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.add(2, "Assistant Professor of Finance", "higheredjobs")
        self.assertEqual([], self.verdicts())

    # --- the two signals deliberately not used as gates --------------------

    def test_non_overlapping_observation_windows_do_not_block_a_merge(self):
        # first_seen_at records when *we* crawled, not when the vacancy
        # existed. Gating on it would let our crawl schedule decide what
        # counts as the same job.
        self.add(1, "Assistant Professor of Finance", "higheredjobs",
                 first_seen="2026-01-01T00:00:00Z", last_seen="2026-01-02T00:00:00Z")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 first_seen="2026-03-01T00:00:00Z", last_seen="2026-03-02T00:00:00Z")
        verdict = self.only()
        self.assertTrue(verdict["merge"])
        self.assertFalse(verdict["windows_overlap"], "reported, but not a gate")

    def test_disagreeing_discipline_labels_do_not_block_a_merge(self):
        # Our own classifier files Stanford's operations/information posting as
        # `Other` from one board and `Information Systems / MIS` from another.
        # Gating on it would veto exactly the pairs whose blurbs differ most.
        self.add(1, "GSB Faculty Positions in Operations and Information",
                 "higheredjobs", discipline="Other")
        self.add(2, "GSB Faculty Positions in Operations and Information",
                 "inside_higher_ed", discipline="Information Systems / MIS")
        verdict = self.only()
        self.assertTrue(verdict["merge"])
        self.assertFalse(verdict["disciplines_agree"], "reported, but not a gate")


class BoardIdTests(Fixture, unittest.TestCase):
    """The society boards are skins over one network, and share posting ids."""

    def url(self, source, slug, board):
        return f"https://{source}.careerwebsite.com/job/{slug}/{board}/"

    def test_a_board_id_is_read_out_of_the_url(self):
        self.assertEqual("85459292", board_id(
            "https://sms.careerwebsite.com/job/director-of-operations-education/85459292/"))
        self.assertIsNone(board_id("https://www.higheredjobs.com/details.cfm?JobCode=1"))

    def test_one_posting_id_on_two_skins_merges_despite_a_truncated_title(self):
        # The real pair: one skin cut the title at "...the Information", so
        # the normalised titles differ and the title rule cannot see them as
        # one vacancy. The board's own id says they are.
        self.add(1, "Tenure-Track Professor in the Information", "ais",
                 source_url=self.url("ais", "tenure-track-professor", "84951765"))
        self.add(2, "Tenure-Track Professor in the Information Technology", "sms",
                 body="Long body. " * 100,
                 source_url=self.url("sms", "tenure-track-professor", "84951765"))
        report = plan(self.conn)
        self.assertEqual(1, len(report["merges"]))
        self.assertEqual(BASIS_BOARD_ID, report["merges"][0]["basis"])

    def test_a_shared_id_at_two_different_schools_is_not_one_job(self):
        self.add(1, "Assistant Professor of Finance", "ais", institution=1,
                 source_url=self.url("ais", "x", "84951765"))
        self.add(2, "Assistant Professor of Marketing", "sms", institution=2,
                 source_url=self.url("sms", "x", "84951765"))
        self.assertEqual([], plan(self.conn)["merges"])

    def test_a_generic_title_still_merges_when_the_board_id_matches(self):
        # The rank-only veto exists because a title alone is weak evidence.
        # A shared posting id identifies the vacancy without it.
        self.add(1, "Assistant Professor", "ais",
                 source_url=self.url("ais", "assistant-professor", "84951765"))
        self.add(2, "Assistant Professor", "sms", body="Long body. " * 100,
                 source_url=self.url("sms", "assistant-professor", "84951765"))
        report = plan(self.conn)
        self.assertEqual(1, len(report["merges"]))
        self.assertEqual(BASIS_BOARD_ID, report["merges"][0]["basis"])

    def test_the_title_rule_wins_when_both_rules_see_one_group(self):
        # Both rules cover the U.S. News pair. It must be merged once, and the
        # plan must not contain the same postings twice.
        self.add(1, "Director of Operations, Education", "ais",
                 source_url=self.url("ais", "director-of-operations", "85459292"))
        self.add(2, "Director of Operations, Education", "sms",
                 body="Long body. " * 100,
                 source_url=self.url("sms", "director-of-operations", "85459292"))
        report = plan(self.conn)
        self.assertEqual(1, len(report["merges"]))
        self.assertEqual(BASIS_TITLE, report["merges"][0]["basis"])
        self.assertEqual({REASON_ALREADY_MERGED: 1}, report["held_back"],
                         "the board-id view of the same pair is reported, not dropped")


class AlreadyMultiSourcedTests(Fixture, unittest.TestCase):
    """A posting that already carries two boards, joined by a third row.

    This is what the rehearsal on real data caught: the member query returned
    one row per posting-and-board, so a posting already carrying two boards
    came back twice, went into the absorb list twice, and the second pass tried
    to move a link it had just moved.
    """

    def link(self, job_id, source):
        self.conn.execute(
            "INSERT INTO job_sources (job_id,source_id,source_job_id,source_url,active,"
            "first_seen,last_seen) VALUES (?,?,?,?,1,?,?)",
            (job_id, self.sources[source], f"{source}-extra-{job_id}",
             f"https://{source}.example/extra/{job_id}", NOW, NOW))
        self.conn.commit()

    def test_a_posting_appears_once_however_many_boards_carry_it(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.link(1, "poms")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="Long body. " * 100)
        verdict = self.only()
        self.assertEqual([1], verdict["absorb"], "the absorb list must not repeat a posting")
        self.assertEqual(["higheredjobs", "poms"],
                         next(m["sources"] for m in verdict["members"] if m["id"] == 1))

    def test_all_of_its_links_move_to_the_survivor(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.link(1, "poms")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="Long body. " * 100)
        apply_all(self.conn, plan(self.conn)["merges"], NOW)
        self.conn.commit()
        names = {row[0] for row in self.conn.execute(
            "SELECT s.name FROM job_sources js JOIN sources s ON s.id=js.source_id "
            "WHERE js.job_id=2")}
        self.assertEqual({"higheredjobs", "poms", "inside_higher_ed"}, names)

    def test_a_board_holding_two_of_the_postings_is_still_ambiguous(self):
        # The dedup must not accidentally hide a genuine ambiguity: poms lists
        # both postings, so which of them the third board's listing is remains
        # a guess.
        self.add(1, "Assistant Professor of Finance", "higheredjobs")
        self.link(1, "poms")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed")
        self.link(2, "poms")
        verdict = self.only()
        self.assertFalse(verdict["merge"])
        self.assertEqual(REASON_AMBIGUOUS, verdict["reason"])


class ApplyTests(Fixture, unittest.TestCase):
    def merge_all(self):
        result = apply_all(self.conn, plan(self.conn)["merges"], NOW)
        self.conn.commit()
        return result

    def two_boards(self):
        self.add(1, "Assistant Professor of Finance", "higheredjobs", body="Short.")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="The department invites applications. " * 100)

    def test_no_row_is_deleted(self):
        self.two_boards()
        self.merge_all()
        self.assertEqual(2, self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0],
                         "an absorbed posting is still something a board published")

    def test_the_absorbed_row_points_at_the_survivor(self):
        self.two_boards()
        self.merge_all()
        self.assertEqual(2, self.conn.execute(
            "SELECT merged_into_job_id FROM jobs WHERE id=1").fetchone()[0])
        self.assertIsNone(self.conn.execute(
            "SELECT merged_into_job_id FROM jobs WHERE id=2").fetchone()[0])

    def test_the_survivor_ends_up_carrying_both_source_links(self):
        # This is the whole point: the vacancy was seen on two boards, and
        # single_sourced_share must stop counting it as one board's.
        self.two_boards()
        self.merge_all()
        names = {row[0] for row in self.conn.execute(
            "SELECT s.name FROM job_sources js JOIN sources s ON s.id=js.source_id "
            "WHERE js.job_id=2")}
        self.assertEqual({"higheredjobs", "inside_higher_ed"}, names)

    def test_no_source_link_is_lost(self):
        self.two_boards()
        self.merge_all()
        self.assertEqual(2, self.conn.execute(
            "SELECT COUNT(*) FROM job_sources").fetchone()[0])

    def test_every_scope_stops_counting_the_absorbed_row(self):
        self.two_boards()
        self.merge_all()
        for scope in ("business_school", "business", "all"):
            with self.subTest(scope=scope):
                self.assertEqual(1, self.conn.execute(
                    "SELECT COUNT(*) FROM jobs j WHERE " + catalogue_sql(scope)
                ).fetchone()[0])

    def test_an_empty_field_is_filled_from_the_absorbed_row(self):
        # One board printing a deadline while the other stays silent is not a
        # disagreement, so the fact is kept.
        self.add(1, "Assistant Professor of Finance", "higheredjobs",
                 body="Short.", deadline="2026-11-30")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="Long body. " * 100, deadline=None)
        self.merge_all()
        self.assertEqual("2026-11-30", self.conn.execute(
            "SELECT deadline_date FROM jobs WHERE id=2").fetchone()[0])

    def test_a_field_the_survivor_already_has_is_not_overwritten(self):
        # Two boards stating different deadlines *is* a disagreement, and
        # picking a winner would be a guess dressed up as a repair.
        self.add(1, "Assistant Professor of Finance", "higheredjobs",
                 body="Short.", deadline="2026-11-30")
        self.add(2, "Assistant Professor of Finance", "inside_higher_ed",
                 body="Long body. " * 100, deadline="2026-12-15")
        self.merge_all()
        self.assertEqual("2026-12-15", self.conn.execute(
            "SELECT deadline_date FROM jobs WHERE id=2").fetchone()[0])

    def test_the_audit_row_records_enough_to_undo_the_merge(self):
        self.two_boards()
        self.merge_all()
        row = self.conn.execute(
            "SELECT * FROM faculty_job_repair_audit "
            "WHERE action='cross_source_duplicate_merge'").fetchone()
        self.assertIsNotNone(row)
        old = json.loads(row["old_value"])
        self.assertEqual([1], old["absorbed_job_ids"])
        self.assertEqual(1, old["moved_source_links"][0]["from_job_id"],
                         "which job each link came from is what makes it reversible")

    def test_a_queued_review_item_for_the_pair_is_closed(self):
        # The queue is only useful while everything in it is undecided. Eight
        # real items were pending on pairs this merge answers, including the
        # 0.87 fuzzy match on Shanghai Jiao Tong that nobody had adjudicated.
        self.two_boards()
        self.conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,"
            "match_basis,resolved,created_at) VALUES (1,2,0.87,'fuzzy_review_only',0,?)",
            (NOW,))
        self.conn.commit()
        self.merge_all()
        row = self.conn.execute("SELECT * FROM possible_duplicates").fetchone()
        self.assertEqual(1, row["resolved"])
        self.assertEqual("merged", row["resolution"])
        self.assertEqual(2, row["merged_into_job_id"], "the survivor is recorded")

    def test_an_unrelated_review_item_is_left_open(self):
        self.two_boards()
        self.add(3, "Assistant Professor of Marketing", "poms")
        self.conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,"
            "match_basis,resolved,created_at) VALUES (2,3,0.91,'fuzzy_review_only',0,?)",
            (NOW,))
        self.conn.commit()
        self.merge_all()
        self.assertEqual(0, self.conn.execute(
            "SELECT resolved FROM possible_duplicates WHERE job_id=2").fetchone()[0])

    def test_a_pair_a_person_judged_distinct_is_never_merged(self):
        # Someone looked at these two and said they are different jobs. A
        # batch rule that merges them anyway and leaves their verdict sitting
        # in the table is worse than one that simply overrules them: the record
        # would look respected while the data said otherwise.
        self.two_boards()
        self.conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,"
            "match_basis,resolved,resolution,created_at) "
            "VALUES (1,2,0.87,'fuzzy_review_only',1,'confirmed_distinct',?)", (NOW,))
        self.conn.commit()
        report = plan(self.conn)
        self.assertEqual([], report["merges"])
        self.assertEqual({REASON_CONFIRMED_DISTINCT: 1}, report["held_back"])

    def test_a_scorer_rejected_pair_is_still_eligible(self):
        # `rejected` is the fuzzy scorer closing its own low-scoring candidate,
        # not a person's verdict, and this rule rests on different evidence.
        self.two_boards()
        self.conn.execute(
            "INSERT INTO possible_duplicates (job_id,possible_job_id,confidence,"
            "match_basis,resolved,resolution,created_at) "
            "VALUES (1,2,0.44,'fuzzy_review_only',1,'rejected',?)", (NOW,))
        self.conn.commit()
        self.assertEqual(1, len(plan(self.conn)["merges"]))

    def test_running_the_merge_twice_changes_nothing(self):
        self.two_boards()
        self.merge_all()
        self.assertEqual([], plan(self.conn)["merges"])
        self.assertEqual(1, self.conn.execute(
            "SELECT COUNT(*) FROM faculty_job_repair_audit "
            "WHERE action='cross_source_duplicate_merge'").fetchone()[0])

    def test_held_back_groups_are_summarised_with_their_reasons(self):
        self.add(1, "Assistant Professor", "higheredjobs")
        self.add(2, "Assistant Professor", "inside_higher_ed")
        self.add(3, "Adjunct Faculty, Accounting", "higheredjobs")
        self.add(4, "Adjunct Faculty, Accounting", "higheredjobs")
        self.add(5, "Adjunct Faculty, Accounting", "inside_higher_ed")
        report = plan(self.conn)
        self.assertEqual(0, len(report["merges"]))
        self.assertEqual({REASON_GENERIC: 1, REASON_AMBIGUOUS: 1}, report["held_back"])


if __name__ == "__main__":
    unittest.main()
