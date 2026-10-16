# -*- coding: utf-8 -*-
"""The store for official external data: IPEDS, SED, DOL.

Kept in its own SQLite file rather than in ``faculty_jobs.db``, for one
operational reason. The write guard copies the whole faculty database before
every crawl; adding several million IPEDS and PERM rows would make each
routine backup proportional to reference data that never changes between
crawls. These datasets also have a different lifecycle -- annual, and
re-downloadable -- so losing this file costs a download, while losing
``faculty_jobs.db`` costs observations that cannot be recovered.

Institution matching crosses the two with ``ATTACH``.

Every load goes through a **release registry**. The audit found that NCSES
changes its asset paths between publication years, so a URL template that
works today silently 404s next year. A registry records which publication was
downloaded, from where, when, and what its bytes hashed to -- so a figure on a
dashboard in 2029 can be traced to the exact file it came from, and a re-run
can tell a changed release from an unchanged one.
"""

import hashlib
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_DB = ROOT / "data" / "academic_market.db"
DEFAULT_DOWNLOAD_ROOT = ROOT / "data" / "academic_market" / "releases"

SCHEMA_VERSION = 2

# Datasets this store holds. Named so a registry row says what it is without a
# lookup table elsewhere.
DATASET_IPEDS_COMPLETIONS = "ipeds_completions"
DATASET_IPEDS_HD = "ipeds_hd"
DATASET_SED_TABLES = "sed_data_tables"
DATASET_PERM = "dol_perm"
DATASET_LCA = "dol_lca"

# How confident we are in a value. The same vocabulary the job side uses, so a
# reader does not have to learn two.
CONFIDENCE = ("verified", "observed", "derived", "estimated", "inferred",
              "stale", "unknown", "blocked")


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def connect(db_path=None):
    conn = sqlite3.connect(str(db_path or DEFAULT_DB), timeout=60)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def ensure_tables(conn):
    """Create everything. Idempotent, and safe to call on each open."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS academic_market_migrations (
            version    INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL,
            note       TEXT
        )
    """)

    # ---- release registry -------------------------------------------------
    # One row per file we actually downloaded. Paths are not templated: the
    # audit found NCSES asset paths differ between publication years, so the
    # URL that worked is recorded rather than reconstructed.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS source_releases (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset        TEXT NOT NULL,
            release_key    TEXT NOT NULL,
            publication_id TEXT,
            data_year      INTEGER,
            source_url     TEXT NOT NULL,
            downloaded_at  TEXT NOT NULL,
            byte_size      INTEGER,
            sha256         TEXT,
            local_path     TEXT,
            http_status    INTEGER,
            status         TEXT NOT NULL,
            note           TEXT,
            UNIQUE (dataset, release_key)
        )
    """)
    # A load that failed is a row, not a silent zero. Without this a 404 and an
    # empty year are indistinguishable in the data-quality report.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ingest_events (
            id           INTEGER PRIMARY KEY AUTOINCREMENT,
            dataset      TEXT NOT NULL,
            release_key  TEXT,
            started_at   TEXT NOT NULL,
            finished_at  TEXT,
            status       TEXT NOT NULL,
            rows_read    INTEGER DEFAULT 0,
            rows_written INTEGER DEFAULT 0,
            rows_skipped INTEGER DEFAULT 0,
            error        TEXT,
            detail       TEXT
        )
    """)

    # ---- IPEDS ------------------------------------------------------------
    # Completions at the grain the file supplies. Demographic breakdowns are
    # deliberately not all copied: the total and the nonresident count are
    # what the market questions need, and widening later is a migration, while
    # copying sixty columns now is dead weight in every query.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ipeds_completions (
            data_year   INTEGER NOT NULL,
            unitid      INTEGER NOT NULL,
            cipcode     TEXT NOT NULL,
            majornum    INTEGER NOT NULL,
            awlevel     INTEGER NOT NULL,
            total       INTEGER NOT NULL DEFAULT 0,
            men         INTEGER,
            women       INTEGER,
            nonresident INTEGER,
            release_id  INTEGER NOT NULL,
            PRIMARY KEY (data_year, unitid, cipcode, majornum, awlevel),
            FOREIGN KEY (release_id) REFERENCES source_releases(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ipeds_cip "
                 "ON ipeds_completions(cipcode, awlevel, data_year)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_ipeds_unit "
                 "ON ipeds_completions(unitid, data_year)")
    conn.execute("""
        CREATE TABLE IF NOT EXISTS ipeds_institutions (
            data_year        INTEGER NOT NULL,
            unitid           INTEGER NOT NULL,
            institution_name TEXT NOT NULL,
            state            TEXT,
            control          INTEGER,
            carnegie_basic   INTEGER,
            website          TEXT,
            release_id       INTEGER NOT NULL,
            PRIMARY KEY (data_year, unitid),
            FOREIGN KEY (release_id) REFERENCES source_releases(id)
        )
    """)

    # CIP -> field crosswalk. Confidence is a column because it varies wildly:
    # 52.1003 is Organizational Behavior outright, while 52.0201 is a general
    # bucket holding most of the market and mapping to nothing narrower.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS business_cip_crosswalk (
            cip_code       TEXT PRIMARY KEY,
            cip_title      TEXT NOT NULL,
            broad_field    TEXT NOT NULL,
            narrow_field   TEXT,
            confidence     TEXT NOT NULL,
            notes          TEXT
        )
    """)

    # ---- institution matching --------------------------------------------
    # Deliberately a table, not a join condition. A match made by a person and
    # a match made by normalising a string are different kinds of claim, and
    # the difference has to survive.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS institution_matches (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            external_kind  TEXT NOT NULL,
            external_key   TEXT NOT NULL,
            external_name  TEXT NOT NULL,
            institution_id INTEGER,
            method         TEXT NOT NULL,
            confidence     TEXT NOT NULL,
            matched_at     TEXT NOT NULL,
            note           TEXT,
            UNIQUE (external_kind, external_key)
        )
    """)
    # Anything that failed to match waits here rather than disappearing.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS institution_match_queue (
            id            INTEGER PRIMARY KEY AUTOINCREMENT,
            external_kind TEXT NOT NULL,
            external_key  TEXT NOT NULL,
            external_name TEXT NOT NULL,
            occurrences   INTEGER NOT NULL DEFAULT 1,
            first_seen_at TEXT NOT NULL,
            last_seen_at  TEXT NOT NULL,
            reason        TEXT,
            UNIQUE (external_kind, external_key)
        )
    """)

    # ---- SED --------------------------------------------------------------
    # Long form: one row per year, table, characteristic and column. SED
    # reshapes its tables between years, and a wide schema would need a
    # migration each time; long survives the reshaping.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS sed_observations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            data_year      INTEGER NOT NULL,
            table_number   TEXT NOT NULL,
            table_title    TEXT,
            -- SED repeats the same row labels inside "All", "Male" and
            -- "Female" subsections of one table. Without the section in the
            -- key, the female block silently overwrites the overall figure and
            -- a share that looks national is actually one sex's.
            section        TEXT NOT NULL DEFAULT 'all',
            characteristic TEXT NOT NULL,
            column_label   TEXT NOT NULL,
            value          REAL,
            value_kind     TEXT NOT NULL,
            release_id     INTEGER NOT NULL,
            FOREIGN KEY (release_id) REFERENCES source_releases(id),
            UNIQUE (data_year, table_number, section, characteristic, column_label)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sed_year "
                 "ON sed_observations(data_year, table_number)")

    # ---- DOL --------------------------------------------------------------
    # Faculty cases only. The full disclosure file is ~500k rows a year and
    # almost none of it is academic; keeping the faculty slice keeps this file
    # small enough to stay in SQLite without a second storage engine.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS perm_faculty_cases (
            case_number       TEXT PRIMARY KEY,
            fiscal_year       INTEGER,
            decision_date     TEXT,
            case_status       TEXT,
            employer_name     TEXT NOT NULL,
            employer_state    TEXT,
            job_title         TEXT,
            soc_code          TEXT,
            soc_title         TEXT,
            college_teacher_flag TEXT,
            competitive_process  TEXT,
            wage              REAL,
            wage_unit         TEXT,
            citizenship       TEXT,
            class_of_admission TEXT,
            phd_institution   TEXT,
            phd_major         TEXT,
            business_field    TEXT,
            faculty_evidence  TEXT NOT NULL,
            institution_id    INTEGER,
            release_id        INTEGER NOT NULL,
            FOREIGN KEY (release_id) REFERENCES source_releases(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_employer "
                 "ON perm_faculty_cases(employer_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_year "
                 "ON perm_faculty_cases(fiscal_year, business_field)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_perm_institution "
                 "ON perm_faculty_cases(institution_id)")

    # H-1B labour condition applications, faculty slice.
    #
    # This is a different thing from PERM and the difference is the whole
    # point of keeping it in its own table. PERM is the permanent-residency
    # step: an employer sponsoring someone for a green card. An LCA is the
    # step before an H-1B petition -- the employer attesting to wage and
    # working conditions for a role. So:
    #
    #   * A certified LCA is not an approved H-1B, and not a hire. Employers
    #     file more than they use, and DOL certifies almost all of them.
    #   * `total_worker_positions` can be greater than one. Counting rows is
    #     not counting people.
    #   * `new_employment` separates a new hire from an extension or an
    #     amendment for someone already employed. Only the first says the
    #     institution went to the international market for this role.
    #
    # Kept per case so those distinctions survive; aggregates that drop them
    # would read as "this school hired N international faculty", which the
    # file does not support.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS lca_faculty_cases (
            case_number       TEXT PRIMARY KEY,
            fiscal_year       INTEGER,
            decision_date     TEXT,
            begin_date        TEXT,
            end_date          TEXT,
            case_status       TEXT,
            visa_class        TEXT,
            employer_name     TEXT NOT NULL,
            employer_state    TEXT,
            worksite_state    TEXT,
            job_title         TEXT,
            soc_code          TEXT,
            soc_title         TEXT,
            full_time         TEXT,
            total_worker_positions INTEGER,
            new_employment    INTEGER,
            continued_employment INTEGER,
            change_employer   INTEGER,
            amended_petition  INTEGER,
            wage_from         REAL,
            wage_to           REAL,
            wage_unit         TEXT,
            prevailing_wage   REAL,
            pw_wage_level     TEXT,
            business_field    TEXT,
            faculty_evidence  TEXT NOT NULL,
            institution_id    INTEGER,
            release_id        INTEGER NOT NULL,
            FOREIGN KEY (release_id) REFERENCES source_releases(id)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lca_employer "
                 "ON lca_faculty_cases(employer_name)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lca_year "
                 "ON lca_faculty_cases(fiscal_year, business_field)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lca_institution "
                 "ON lca_faculty_cases(institution_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_lca_soc "
                 "ON lca_faculty_cases(soc_code, fiscal_year)")

    version = conn.execute(
        "SELECT COALESCE(MAX(version),0) FROM academic_market_migrations").fetchone()[0]
    if version < SCHEMA_VERSION:
        conn.execute(
            "INSERT OR REPLACE INTO academic_market_migrations (version, applied_at, note) "
            "VALUES (?,?,?)",
            (SCHEMA_VERSION, now_utc(),
             "Official external reference data: IPEDS completions and institutions, "
             "SED national observations, DOL PERM faculty cases, plus the release "
             "registry that records which file each figure came from. Separate from "
             "faculty_jobs.db because the write guard copies that file before every "
             "crawl and these datasets are annual, large, and re-downloadable."))
    if version < 2:
        conn.execute(
            "INSERT OR REPLACE INTO academic_market_migrations (version, applied_at, note) "
            "VALUES (?,?,?)",
            (2, now_utc(),
             "Added lca_faculty_cases: the H-1B labour condition application slice. "
             "Separate from perm_faculty_cases because an LCA is a pre-petition "
             "attestation rather than a permanent-residency sponsorship, and because "
             "one LCA can cover several positions -- distinctions a shared table "
             "would flatten."))
    conn.commit()
    return conn


# --------------------------------------------------------------------------
# Release registry
# --------------------------------------------------------------------------

def register_release(conn, dataset, release_key, source_url, *, publication_id=None,
                     data_year=None, local_path=None, http_status=None,
                     status="downloaded", note=None):
    """Record a downloaded file and return its id.

    The sha256 is of the file as it arrived. Re-running a year later and
    getting a different hash means the publisher revised the release -- which
    is a fact worth knowing before a series changes shape underneath a chart.
    """
    digest = byte_size = None
    if local_path and Path(local_path).exists():
        hasher = hashlib.sha256()
        with open(local_path, "rb") as handle:
            for chunk in iter(lambda: handle.read(1 << 20), b""):
                hasher.update(chunk)
        digest = hasher.hexdigest()
        byte_size = Path(local_path).stat().st_size
    conn.execute("""
        INSERT INTO source_releases
          (dataset, release_key, publication_id, data_year, source_url,
           downloaded_at, byte_size, sha256, local_path, http_status, status, note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
        ON CONFLICT(dataset, release_key) DO UPDATE SET
          source_url=excluded.source_url, downloaded_at=excluded.downloaded_at,
          byte_size=excluded.byte_size, sha256=excluded.sha256,
          local_path=excluded.local_path, http_status=excluded.http_status,
          status=excluded.status, note=excluded.note
    """, (dataset, release_key, publication_id, data_year, source_url, now_utc(),
          byte_size, digest, str(local_path) if local_path else None,
          http_status, status, note))
    return conn.execute(
        "SELECT id FROM source_releases WHERE dataset=? AND release_key=?",
        (dataset, release_key)).fetchone()["id"]


def start_event(conn, dataset, release_key=None):
    """Open an event and commit it immediately.

    The commit is the point. A loader that fails rolls back its partial data,
    and an uncommitted event row would roll back with it -- leaving a failed
    load indistinguishable from one that never ran. The event has to outlive
    the transaction it describes.
    """
    cursor = conn.execute("""
        INSERT INTO ingest_events (dataset, release_key, started_at, status)
        VALUES (?,?,?,'running')
    """, (dataset, release_key, now_utc()))
    event_id = cursor.lastrowid
    conn.commit()
    return event_id


def finish_event(conn, event_id, status, *, rows_read=0, rows_written=0,
                 rows_skipped=0, error=None, detail=None):
    """Close an event. A failure is recorded, never returned as an empty success."""
    conn.execute("""
        UPDATE ingest_events SET finished_at=?, status=?, rows_read=?, rows_written=?,
               rows_skipped=?, error=?, detail=? WHERE id=?
    """, (now_utc(), status, rows_read, rows_written, rows_skipped,
          (str(error)[:900] if error else None),
          (json.dumps(detail, ensure_ascii=False)[:2000] if detail else None), event_id))


def release_summary(conn):
    """What has been loaded, for the data-quality report."""
    rows = conn.execute("""
        SELECT dataset, COUNT(*) AS releases, MIN(data_year) AS first_year,
               MAX(data_year) AS last_year, MAX(downloaded_at) AS latest_download
        FROM source_releases WHERE status='downloaded' GROUP BY dataset
    """).fetchall()
    failures = conn.execute("""
        SELECT dataset, COUNT(*) AS n FROM ingest_events
        WHERE status NOT IN ('ok','running') GROUP BY dataset
    """).fetchall()
    return {
        "releases": [dict(row) for row in rows],
        "failed_events": {row["dataset"]: row["n"] for row in failures},
    }


__all__ = [
    "CONFIDENCE", "DATASET_IPEDS_COMPLETIONS", "DATASET_IPEDS_HD", "DATASET_LCA",
    "DATASET_PERM", "DATASET_SED_TABLES", "DEFAULT_DB", "DEFAULT_DOWNLOAD_ROOT",
    "SCHEMA_VERSION", "connect", "ensure_tables", "finish_event", "now_utc",
    "register_release", "release_summary", "start_event",
]
