# -*- coding: utf-8 -*-
"""Retention rules for write-guard backups.

These files are the only copy of the database as it stood before each write, so
the planner is tested the way deletion logic should be: on what it refuses to
remove. The write guard's own rule -- never overwrite a backup -- is what makes
them trustworthy, and a pruner that is too clever undoes that guarantee.
"""

import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from scripts.prune_faculty_backups import parse_stamp, plan

NOW = datetime(2026, 9, 3, 12, 0, 0, tzinfo=timezone.utc)


def entry(tag, days_old, *, manifest=True, unparsed=False, size=190_000_000):
    taken = NOW - timedelta(days=days_old)
    stamp = taken.strftime("%Y%m%dT%H%M%SZ")
    name = f"faculty_jobs.{stamp}.{tag}.pre.db"
    return {"path": Path(name), "tag": tag, "taken": taken, "bytes": size,
            "manifest": Path(name + ".manifest.json") if manifest else None,
            "unparsed": unparsed}


def run(entries, **kwargs):
    ordered = sorted(entries, key=lambda e: e["taken"], reverse=True)
    keep, remove = plan(ordered, now=NOW, **kwargs)
    return {e["path"].name for e in keep}, {e["path"].name for e in remove}


class RetentionTests(unittest.TestCase):
    def test_the_newest_backup_is_never_removed(self):
        entries = [entry("scheduled", n) for n in range(1, 30)]
        _keep, remove = run(entries, keep_per_tag=1, keep_days=0)
        newest = min(entries, key=lambda e: NOW - e["taken"])["path"].name
        self.assertNotIn(newest, remove)

    def test_recent_backups_survive_regardless_of_tag_count(self):
        entries = [entry("scheduled", n) for n in (0.1, 0.5, 1, 2)]
        _keep, remove = run(entries, keep_per_tag=1, keep_days=3)
        self.assertEqual(set(), remove, "everything inside the window is kept")

    def test_each_tag_keeps_its_own_recent_copies(self):
        # The point of per-tag retention: the last backup taken before a
        # *migration* matters even when twenty crawl backups are newer.
        entries = [entry("scheduled", n) for n in range(10, 40)]
        entries.append(entry("schema_migration", 35))
        keep, _remove = run(entries, keep_per_tag=2, keep_days=3)
        migration = [e for e in entries if e["tag"] == "schema_migration"][0]
        self.assertIn(migration["path"].name, keep,
                      "an old backup for a rare tag is not superseded by common ones")

    def test_a_backup_without_a_manifest_is_kept_and_flagged(self):
        # Without a manifest we cannot say what state it captured. That is
        # precisely when it should not be thrown away.
        entries = [entry("scheduled", n) for n in range(1, 10)]
        entries.append(entry("orphan", 40, manifest=False))
        keep, remove = run(entries, keep_per_tag=1, keep_days=1)
        orphan = [e for e in entries if e["tag"] == "orphan"][0]
        self.assertIn(orphan["path"].name, keep)
        self.assertNotIn(orphan["path"].name, remove)

    def test_an_unrecognised_filename_is_never_removed(self):
        entries = [entry("scheduled", n) for n in range(1, 10)]
        stray = {"path": Path("something-else.pre.db"), "tag": None, "taken": None,
                 "bytes": 10, "manifest": None, "unparsed": True}
        keep, remove = plan([*entries, stray], now=NOW, keep_per_tag=1, keep_days=1)
        self.assertIn("something-else.pre.db", {e["path"].name for e in keep})
        self.assertEqual(set(), {e["path"].name for e in remove} & {"something-else.pre.db"})

    def test_every_file_lands_in_exactly_one_bucket_with_a_reason(self):
        entries = [entry("a", 1), entry("a", 10), entry("b", 20), entry("b", 30)]
        ordered = sorted(entries, key=lambda e: e["taken"], reverse=True)
        keep, remove = plan(ordered, now=NOW, keep_per_tag=1, keep_days=3)
        self.assertEqual(len(entries), len(keep) + len(remove))
        for row in (*keep, *remove):
            self.assertTrue(row["reason"], "every decision must carry its reason")

    def test_the_newest_backup_also_counts_as_its_tags_kept_copy(self):
        # Four backups of one tag; only the newest is kept. It is not kept
        # twice -- being newest overall and being the tag's one retained copy
        # are the same file, so the other three are superseded.
        entries = [entry("scheduled", n) for n in (1, 10, 20, 30)]
        keep, remove = run(entries, keep_per_tag=1, keep_days=3)
        self.assertEqual(1, len(keep))
        self.assertEqual(3, len(remove))

    def test_the_stamp_parser_reads_the_write_guards_format(self):
        self.assertEqual(
            datetime(2026, 9, 3, 4, 41, 1, tzinfo=timezone.utc),
            parse_stamp("20260903T044101Z"))


if __name__ == "__main__":
    unittest.main()
