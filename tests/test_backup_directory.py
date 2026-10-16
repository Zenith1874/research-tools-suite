# -*- coding: utf-8 -*-
"""Where a guarded backup lands.

Every guarded write copies the whole database and never overwrites an earlier
copy. That rule is right and it is also why the directory only grows -- one
day's work left 71 copies and 11.8GB -- so the location has to be movable off
the drive the database itself lives on.

The case worth being careful about is a configured directory that turns out to
be unusable: an unplugged drive, a typo, a permission. Falling back silently
would keep writing to the disk we were trying to spare, and refusing would stop
the write entirely. Neither is acceptable on its own, so it falls back *and*
says so -- because failing to take a backup is the only outcome worse than
taking it in the wrong place.
"""

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from services.faculty_jobs_write_guard import BACKUP_DIR_ENV, backup_directory


class BackupDirectoryTests(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.TemporaryDirectory(ignore_cleanup_errors=True)
        self.root = Path(self.dir.name)
        self.db = self.root / "data" / "faculty_jobs.db"
        self.db.parent.mkdir(parents=True, exist_ok=True)
        self.db.touch()

    def tearDown(self):
        self.dir.cleanup()

    def test_the_default_is_unchanged_when_nothing_is_configured(self):
        # Anyone who sets neither knob keeps exactly the old behaviour.
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BACKUP_DIR_ENV, None)
            self.assertEqual(self.db.parent / "backups", backup_directory(self.db))

    def test_the_environment_variable_wins(self):
        target = self.root / "elsewhere"
        with mock.patch.dict(os.environ, {BACKUP_DIR_ENV: str(target)}):
            self.assertEqual(target, backup_directory(self.db))

    def test_a_pointer_file_is_used_when_the_environment_is_unset(self):
        # The scheduled runs get their environment from a script outside this
        # repository, so a file beside the database is the reachable knob.
        target = self.root / "from-file"
        (self.db.parent / "faculty_jobs_backup_dir.txt").write_text(
            str(target) + "\n", encoding="utf-8")
        with mock.patch.dict(os.environ, {}, clear=False):
            os.environ.pop(BACKUP_DIR_ENV, None)
            self.assertEqual(target, backup_directory(self.db))

    def test_the_environment_beats_the_pointer_file(self):
        (self.db.parent / "faculty_jobs_backup_dir.txt").write_text(
            str(self.root / "from-file"), encoding="utf-8")
        chosen = self.root / "from-env"
        with mock.patch.dict(os.environ, {BACKUP_DIR_ENV: str(chosen)}):
            self.assertEqual(chosen, backup_directory(self.db))

    def test_an_unusable_directory_falls_back_and_says_so(self):
        # A drive that is not there must not silently send backups to the disk
        # we were trying to spare without a word.
        unusable = self.root / "blocked"
        with mock.patch.dict(os.environ, {BACKUP_DIR_ENV: str(unusable)}), \
                mock.patch("pathlib.Path.mkdir", side_effect=OSError("no such drive")), \
                mock.patch("builtins.print") as said:
            self.assertEqual(self.db.parent / "backups", backup_directory(self.db))
        self.assertTrue(said.called, "an unusable backup directory must be reported")
        spoken = " ".join(str(arg) for call in said.call_args_list for arg in call.args)
        self.assertIn("unusable", spoken)
        self.assertIn("no such drive", spoken, "the reason belongs in the message")

    def test_the_probe_does_not_leave_a_file_behind(self):
        target = self.root / "probed"
        with mock.patch.dict(os.environ, {BACKUP_DIR_ENV: str(target)}):
            backup_directory(self.db)
        self.assertEqual([], list(target.iterdir()),
                         "the writability probe must clean up after itself")

    def test_a_blank_setting_is_treated_as_unset(self):
        with mock.patch.dict(os.environ, {BACKUP_DIR_ENV: "   "}):
            self.assertEqual(self.db.parent / "backups", backup_directory(self.db))


if __name__ == "__main__":
    unittest.main()
