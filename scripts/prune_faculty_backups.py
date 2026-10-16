# -*- coding: utf-8 -*-
"""Report -- and, only when told to, remove -- superseded write-guard backups.

The write guard never overwrites a backup, which is the right rule: a backup
that can be clobbered is not a backup. The consequence is that every guarded
write leaves another ~190MB copy behind, and nothing has ever removed one. The
directory reached 204 files and 13GB.

This defaults to reporting. Deleting a backup is not a decision a script should
make on its own, so ``--apply`` is required, and even then the rules are
conservative:

* the newest backup overall is always kept;
* the newest ``--keep-per-tag`` for each tag is kept, so the most recent copy
  from before each *kind* of write survives;
* anything newer than ``--keep-days`` is kept regardless;
* a .db and its .manifest.json are treated as one unit -- removing one and
  leaving the other would leave a manifest describing a file that is gone.

A backup whose manifest is missing is reported and never removed: we cannot
confirm what it was taken before, and that is exactly when you want it.
"""

import argparse
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DIR = ROOT / "data" / "backups"

# faculty_jobs.20260903T044101Z.detail_all.pre.db
NAME_RE = re.compile(
    r"^(?P<stem>.+?)\.(?P<stamp>\d{8}T\d{6}Z)\.(?P<tag>.+?)\.pre\.db$")


def parse_stamp(text):
    return datetime.strptime(text, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)


def survey(directory):
    """Every backup, with its tag, age, size, and whether it has a manifest."""
    entries = []
    for path in sorted(directory.glob("*.pre.db")):
        match = NAME_RE.match(path.name)
        if not match:
            entries.append({"path": path, "tag": None, "taken": None,
                            "bytes": path.stat().st_size, "manifest": None,
                            "unparsed": True})
            continue
        manifest = path.with_suffix("").with_suffix(".pre.manifest.json")
        entries.append({
            "path": path,
            "tag": match.group("tag"),
            "taken": parse_stamp(match.group("stamp")),
            "bytes": path.stat().st_size,
            "manifest": manifest if manifest.exists() else None,
            "unparsed": False,
        })
    entries.sort(key=lambda e: (e["taken"] or datetime.min.replace(
        tzinfo=timezone.utc)), reverse=True)
    return entries


def plan(entries, *, keep_per_tag=2, keep_days=3, now=None):
    """Split into keep and remove, with a reason recorded for every file."""
    now = now or datetime.now(timezone.utc)
    cutoff = now - timedelta(days=keep_days)
    seen_per_tag = {}
    keep, remove = [], []
    for index, entry in enumerate(entries):
        reason = None
        if entry["unparsed"]:
            reason = "filename does not match the write-guard pattern"
        elif entry["manifest"] is None:
            reason = "no manifest: cannot confirm what this was taken before"
        elif index == 0:
            reason = "newest backup overall"
        elif entry["taken"] and entry["taken"] >= cutoff:
            reason = f"taken within the last {keep_days} day(s)"
        else:
            count = seen_per_tag.get(entry["tag"], 0)
            if count < keep_per_tag:
                reason = f"newest {count + 1} of {keep_per_tag} for tag {entry['tag']}"
        if entry["tag"]:
            seen_per_tag[entry["tag"]] = seen_per_tag.get(entry["tag"], 0) + 1
        if reason:
            keep.append({**entry, "reason": reason})
        else:
            remove.append({**entry, "reason": (
                f"superseded: newer backups exist for tag {entry['tag']} and it "
                f"is older than {keep_days} day(s)")})
    return keep, remove


def human(size):
    return f"{size / 1024 ** 3:.1f} GB" if size >= 1024 ** 3 else f"{size / 1024 ** 2:.0f} MB"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dir", default=str(DEFAULT_DIR))
    parser.add_argument("--keep-per-tag", type=int, default=2,
                        help="how many recent backups to keep for each write kind")
    parser.add_argument("--keep-days", type=float, default=3.0,
                        help="keep everything taken within this many days")
    parser.add_argument("--apply", action="store_true",
                        help="actually delete. Without it nothing is removed.")
    args = parser.parse_args()

    directory = Path(args.dir)
    if not directory.is_dir():
        raise SystemExit(f"no backup directory at {directory}")
    entries = survey(directory)
    if not entries:
        print(f"no backups in {directory}")
        return
    keep, remove = plan(entries, keep_per_tag=args.keep_per_tag,
                        keep_days=args.keep_days)

    total = sum(e["bytes"] for e in entries)
    freed = sum(e["bytes"] for e in remove)
    print(f"{directory}")
    print(f"  backups: {len(entries)}  total: {human(total)}")
    print(f"  keep:    {len(keep)}  ({human(total - freed)})")
    print(f"  remove:  {len(remove)}  ({human(freed)})")

    by_tag = {}
    for entry in entries:
        by_tag.setdefault(entry["tag"] or "(unparsed)", [0, 0])
        by_tag[entry["tag"] or "(unparsed)"][0] += 1
        by_tag[entry["tag"] or "(unparsed)"][1] += entry["bytes"]
    print("\n  by tag:")
    for tag, (count, size) in sorted(by_tag.items(), key=lambda kv: -kv[1][1]):
        print(f"    {str(tag)[:34]:36}{count:>4}  {human(size):>9}")

    if remove:
        print("\n  oldest candidates for removal:")
        for entry in sorted(remove, key=lambda e: e["taken"])[:8]:
            print(f"    {entry['path'].name[:56]:58}{human(entry['bytes']):>9}")

    unmanifested = [e for e in keep if not e["unparsed"] and e["manifest"] is None]
    if unmanifested:
        print(f"\n  {len(unmanifested)} backup(s) have no manifest and are kept "
              "regardless: without one we cannot say what they were taken before.")

    if not args.apply:
        print("\nno --apply: nothing was deleted. Review the list above first --"
              " these are the only copies of the database as it was before each write.")
        return

    removed_bytes = 0
    for entry in remove:
        entry["path"].unlink()
        if entry["manifest"]:
            entry["manifest"].unlink()
        removed_bytes += entry["bytes"]
    print(f"\nremoved {len(remove)} backup(s), freeing {human(removed_bytes)}")


if __name__ == "__main__":
    main()
