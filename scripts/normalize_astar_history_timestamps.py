#!/usr/bin/env python3
"""Normalize only this run's generated article audit timestamps to legacy format.

The project's article writer and index watermarks use naive local timestamps.
This run initially wrote offset-qualified UTC values. Publication dates and all
article content remain unchanged; an immutable before/after receipt is saved.
"""

import argparse
import gzip
import json
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.astar_history_service import utc_now, write_new_json


def local_legacy(value):
    return datetime.fromisoformat(value).astimezone().replace(tzinfo=None).isoformat(timespec="seconds")


def normalize(run_dir):
    manifest = json.loads((run_dir / "manifest.json").read_text(encoding="utf-8"))
    conn = sqlite3.connect(Path(manifest["db_path"]).as_uri() + "?mode=rw", uri=True, timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout=60000")
    conn.execute("ATTACH DATABASE ? AS original", (Path(manifest["snapshot_path"]).as_uri() + "?mode=ro",))
    conn.execute("ATTACH DATABASE ? AS history", ((run_dir / "checkpoint.sqlite3").as_uri() + "?mode=ro",))
    pub_path = run_dir / "publisher_tax_forum/checkpoint.sqlite3"
    conn.execute("ATTACH DATABASE ? AS publisher", (pub_path.as_uri() + "?mode=ro",))
    baseline_max = conn.execute("SELECT MAX(id) FROM original.astar_articles").fetchone()[0]
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    folder = run_dir / "timestamp_normalization" / stamp
    folder.mkdir(parents=True)
    with (folder / "normalization_script.py").open("xb") as stream:
        stream.write(Path(__file__).read_bytes())
    rows = conn.execute("""
        SELECT a.id,a.created_at,a.updated_at,b.updated_at AS baseline_updated_at
        FROM main.astar_articles a LEFT JOIN original.astar_articles b ON b.id=a.id
        WHERE (a.created_at LIKE '%+00:00' OR a.updated_at LIKE '%+00:00')
          AND (EXISTS (SELECT 1 FROM history.records r WHERE r.article_id=a.id)
               OR EXISTS (SELECT 1 FROM publisher.articles p WHERE p.article_id=a.id AND p.status='IMPORTED'))
        ORDER BY a.id
    """).fetchall()
    touched_rows = created_changes = updated_changes = 0
    receipts = folder / "before_after.jsonl.gz"
    try:
        with receipts.open("xb") as binary:
            with gzip.GzipFile(fileobj=binary, mode="wb") as stream:
                batch = []
                for row in rows:
                    created = row["created_at"]
                    updated = row["updated_at"]
                    if row["id"] > baseline_max and created and created.endswith("+00:00"):
                        created = local_legacy(created)
                        created_changes += 1
                    if updated and updated.endswith("+00:00") and updated != row["baseline_updated_at"]:
                        updated = local_legacy(updated)
                        updated_changes += 1
                    if created == row["created_at"] and updated == row["updated_at"]:
                        continue
                    receipt = {"id": row["id"], "before_created_at": row["created_at"],
                               "after_created_at": created, "before_updated_at": row["updated_at"],
                               "after_updated_at": updated}
                    stream.write((json.dumps(receipt) + "\n").encode("utf-8"))
                    batch.append((created, updated, row["id"]))
                    touched_rows += 1
                    if len(batch) >= 2000:
                        conn.executemany("UPDATE astar_articles SET created_at=?,updated_at=? WHERE id=?", batch)
                        conn.commit()
                        batch.clear()
                if batch:
                    conn.executemany("UPDATE astar_articles SET created_at=?,updated_at=? WHERE id=?", batch)
                    conn.commit()
        result = {"created_at_utc": utc_now(), "legacy_local_timezone": str(datetime.now().astimezone().tzinfo),
                  "source_utc_offset": str(datetime.now().astimezone().utcoffset()),
                  "touched_rows": touched_rows, "created_at_values_normalized": created_changes,
                  "updated_at_values_normalized": updated_changes, "baseline_max_id": baseline_max,
                  "receipt_path": str(receipts), "publication_dates_changed": 0}
        write_new_json(folder / "result.json", result)
        return result
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def main():
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--run-dir", type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(normalize(args.run_dir.resolve()), indent=2))


if __name__ == "__main__":
    main()
