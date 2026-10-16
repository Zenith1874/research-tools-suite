# -*- coding: utf-8 -*-
"""Content-addressed archive for the pages every derived field came from.

This is the one asset in the whole project that cannot be back-filled. IPEDS,
SED and PERM are annual archives and can be downloaded again in 2029. A job
posting's page cannot: it is replaced by the next posting and gone. So the
value of this module is not what it does today -- it is that a 2029 parser can
be re-run over the 2026 pages and produce a comparable series.

Three design choices, each with a reason:

**Content-addressed.** A Workday detail page that does not change for a week
is one blob and seven observations, not seven copies. The hash is the identity;
the observations carry the timeline.

**On disk, not in SQLite.** The production database is backed up in full before
every write. Putting raw HTML in it would make each crawl's backup proportional
to the archive, and the archive is meant to grow for four years. The rows here
hold the pointer and the metadata; the bytes live under ``data/faculty_jobs/raw``.

**gzip, not zstd.** ``zstandard`` is not installed and this project does not
add a dependency for one feature. gzip is in the standard library and reaches
roughly 4-5x on HTML, which is enough. The blob records its own codec, so a
later zstd blob can sit beside a gzip one without a migration.

Nothing here decides what is worth keeping. A challenge page and a real posting
are both observations; the difference is recorded in ``http_status`` and
``kind``, not by discarding one of them.
"""

import gzip
import hashlib
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

# Where the bytes live. Kept beside the database it describes rather than in a
# system temp directory: the archive is data, not scratch.
DEFAULT_ROOT = Path(__file__).resolve().parents[1] / "data" / "faculty_jobs" / "raw"

# Fan-out by the first two hex characters. 256 directories keeps any one of
# them to a few thousand files at the volumes this project will reach, which
# every filesystem handles without special care.
FANOUT = 2

CODEC_GZIP = "gzip"

# What a stored page is. Recorded per observation because the same URL can be
# fetched for different reasons and a later reader needs to know which.
KIND_LISTING = "listing"
KIND_DETAIL = "detail"
KIND_JMC = "jmc"
KIND_PLACEMENT = "placement"
KIND_POLICY = "policy"
KIND_ROSTER = "roster"
KINDS = (KIND_LISTING, KIND_DETAIL, KIND_JMC, KIND_PLACEMENT, KIND_POLICY, KIND_ROSTER)

EXTENSIONS = {
    "text/html": ".html",
    "application/json": ".json",
    "text/plain": ".txt",
    "application/xml": ".xml",
    "text/xml": ".xml",
}


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def content_hash(payload):
    """SHA-256 of the raw bytes, before compression.

    Hashing the uncompressed bytes means a blob written by gzip today and one
    written by a future codec are recognised as the same content.
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def blob_path(digest, mime_type="text/html", root=None):
    root = Path(root or DEFAULT_ROOT)
    extension = EXTENSIONS.get((mime_type or "").split(";")[0].strip(), ".bin")
    return root / digest[:FANOUT] / f"{digest}{extension}.gz"


def relative_path(digest, mime_type="text/html", root=None):
    """Path stored in the database: relative, so the archive can be moved."""
    root = Path(root or DEFAULT_ROOT)
    return blob_path(digest, mime_type, root).relative_to(root).as_posix()


def ensure_tables(conn):
    """Create the archive tables. Idempotent; safe to call on every open."""
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_source_blobs (
            content_hash   TEXT PRIMARY KEY,
            mime_type      TEXT NOT NULL,
            compression    TEXT NOT NULL,
            byte_size      INTEGER NOT NULL,
            stored_size    INTEGER NOT NULL,
            storage_path   TEXT NOT NULL,
            first_stored_at TEXT NOT NULL
        )
    """)
    # One row per fetch. The same blob may be referenced by thousands of these:
    # that is the point, and it is what lets a flat week of an unchanged page
    # cost one file.
    conn.execute("""
        CREATE TABLE IF NOT EXISTS raw_observations (
            id             INTEGER PRIMARY KEY AUTOINCREMENT,
            content_hash   TEXT,
            kind           TEXT NOT NULL,
            source_id      INTEGER,
            source_job_id  TEXT,
            source_url     TEXT NOT NULL,
            observed_at    TEXT NOT NULL,
            http_status    INTEGER,
            mime_type      TEXT,
            content_length INTEGER,
            parser_version TEXT,
            ingestion_run_id INTEGER,
            note           TEXT,
            FOREIGN KEY (content_hash) REFERENCES raw_source_blobs(content_hash)
        )
    """)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_obs_url_time "
                 "ON raw_observations(source_url, observed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_obs_source "
                 "ON raw_observations(source_id, kind, observed_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_obs_job "
                 "ON raw_observations(source_id, source_job_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_raw_obs_hash "
                 "ON raw_observations(content_hash)")


def store_blob(conn, payload, mime_type="text/html", root=None):
    """Write the bytes once. Returns ``(content_hash, was_new)``.

    A hash we already hold writes nothing: the file on disk is already the
    same bytes, and rewriting it would only risk replacing a good file with a
    truncated one.
    """
    if isinstance(payload, str):
        payload = payload.encode("utf-8")
    digest = content_hash(payload)
    existing = conn.execute(
        "SELECT 1 FROM raw_source_blobs WHERE content_hash=?", (digest,)).fetchone()
    target = blob_path(digest, mime_type, root)
    if existing and target.exists():
        return digest, False

    target.parent.mkdir(parents=True, exist_ok=True)
    # Write beside the target and rename: a crash mid-write leaves a partial
    # temp file rather than a corrupt blob under a hash that claims to be good.
    temporary = target.with_suffix(target.suffix + ".part")
    with gzip.open(temporary, "wb", compresslevel=6) as handle:
        handle.write(payload)
    os.replace(temporary, target)

    conn.execute("""
        INSERT INTO raw_source_blobs
          (content_hash, mime_type, compression, byte_size, stored_size,
           storage_path, first_stored_at)
        VALUES (?,?,?,?,?,?,?)
        ON CONFLICT(content_hash) DO NOTHING
    """, (digest, mime_type, CODEC_GZIP, len(payload), target.stat().st_size,
          relative_path(digest, mime_type, root), now_utc()))
    return digest, True


def record_observation(conn, *, kind, source_url, payload=None, mime_type="text/html",
                       source_id=None, source_job_id=None, http_status=None,
                       parser_version=None, ingestion_run_id=None, note=None,
                       observed_at=None, root=None):
    """Record that a URL was fetched, with or without a body.

    A refusal is an observation too. A 403, a Cloudflare challenge or a
    timeout gets a row with ``content_hash`` NULL and the status recorded --
    the fact that we asked and were turned away is exactly the kind of thing a
    2029 reader needs in order to interpret a gap in coverage.
    """
    if kind not in KINDS:
        raise ValueError(f"unknown archive kind {kind!r}; expected one of {KINDS}")
    digest = None
    length = None
    if payload is not None:
        digest, _new = store_blob(conn, payload, mime_type, root)
        length = len(payload.encode("utf-8") if isinstance(payload, str) else payload)
    cursor = conn.execute("""
        INSERT INTO raw_observations
          (content_hash, kind, source_id, source_job_id, source_url, observed_at,
           http_status, mime_type, content_length, parser_version,
           ingestion_run_id, note)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?)
    """, (digest, kind, source_id, source_job_id, source_url,
          observed_at or now_utc(), http_status, mime_type, length,
          parser_version, ingestion_run_id, note))
    return {"observation_id": cursor.lastrowid, "content_hash": digest,
            "content_length": length}


def load_blob(conn, digest, root=None):
    """Return the original bytes for a hash, or raise if the file is gone."""
    row = conn.execute(
        "SELECT mime_type, storage_path FROM raw_source_blobs WHERE content_hash=?",
        (digest,)).fetchone()
    if not row:
        raise KeyError(f"no blob recorded for {digest}")
    mime_type = row[0] if not hasattr(row, "keys") else row["mime_type"]
    stored = row[1] if not hasattr(row, "keys") else row["storage_path"]
    path = Path(root or DEFAULT_ROOT) / stored
    if not path.exists():
        # Fall back to recomputing the layout, in case the archive moved
        # between a relative and an absolute convention.
        path = blob_path(digest, mime_type, root)
    if not path.exists():
        raise FileNotFoundError(f"blob {digest} is recorded but missing at {path}")
    with gzip.open(path, "rb") as handle:
        payload = handle.read()
    if content_hash(payload) != digest:
        raise ValueError(f"blob {digest} does not hash to its own name; file is corrupt")
    return payload


def load_text(conn, digest, root=None, encoding="utf-8"):
    return load_blob(conn, digest, root).decode(encoding, "replace")


def archive_stats(conn, root=None):
    """What the archive holds, for the data-quality report."""
    row = conn.execute("""
        SELECT COUNT(*) AS blobs, COALESCE(SUM(byte_size),0) AS raw_bytes,
               COALESCE(SUM(stored_size),0) AS stored_bytes,
               MIN(first_stored_at) AS since
        FROM raw_source_blobs
    """).fetchone()
    observations = conn.execute("""
        SELECT COUNT(*) AS n,
               SUM(CASE WHEN content_hash IS NULL THEN 1 ELSE 0 END) AS bodiless,
               MIN(observed_at) AS since
        FROM raw_observations
    """).fetchone()
    keys = lambda r, k, i: (r[k] if hasattr(r, "keys") else r[i])
    raw_bytes = keys(row, "raw_bytes", 1) or 0
    stored_bytes = keys(row, "stored_bytes", 2) or 0
    return {
        "blobs": keys(row, "blobs", 0),
        "raw_bytes": raw_bytes,
        "stored_bytes": stored_bytes,
        "compression_ratio": round(raw_bytes / stored_bytes, 2) if stored_bytes else None,
        "blobs_since": keys(row, "since", 3),
        "observations": keys(observations, "n", 0),
        "observations_without_body": keys(observations, "bodiless", 1) or 0,
        "observations_since": keys(observations, "since", 2),
    }


__all__ = [
    "CODEC_GZIP", "DEFAULT_ROOT", "KINDS", "KIND_DETAIL", "KIND_JMC",
    "KIND_LISTING", "KIND_PLACEMENT", "KIND_POLICY", "KIND_ROSTER",
    "archive_stats", "blob_path", "content_hash", "ensure_tables", "load_blob",
    "load_text", "record_observation", "relative_path", "store_blob",
]
