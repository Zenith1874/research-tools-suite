# -*- coding: utf-8 -*-
"""Full-text search over posting text.

There were 5,236 postings holding 4MB of text and no way to search it but a
``LIKE`` scan of every row. This is an FTS5 index over the fields a person
actually searches: the title, the posting's own body, the department, and the
discipline.

**External-content index.** ``jobs`` stays the single source of truth and the
index stores no copy of the text -- it points back at the row. That matters
here beyond the disk saving: a duplicated body is a body that can drift, and
this project has already had one field mean two things in two places.

**It answers "which postings mention this", not "is this true of the job".**
A posting matching `sponsorship` might be offering it or refusing it, and the
snippet is there so a reader sees which. Search is a way to find rows to read,
never a substitute for the parsed fields -- `visa_status` is the derived answer
and carries its evidence; a keyword hit does not.

Rebuilding is cheap (seconds over 5k rows), so the index is rebuilt after a
bulk text change rather than trusted to have kept up.
"""

import re
import sqlite3

# The columns worth searching. `visa_text` is deliberately absent: it is an
# extracted quote, so indexing it would make a posting match twice for the same
# sentence and rank it above postings whose body says more.
INDEXED_COLUMNS = ("title_raw", "description_excerpt", "department",
                   "discipline_primary")

# FTS5 syntax characters. A person typing `assistant professor (finance)` means
# a phrase, not a boolean expression, and an unbalanced quote is a hard error
# rather than zero results -- so queries are sanitised into quoted terms.
_FTS_SPECIAL = re.compile(r'["\'()*:^-]')


def ensure_tables(conn):
    """Create the index and the triggers that keep it in step with ``jobs``."""
    columns = ", ".join(INDEXED_COLUMNS)
    conn.execute(f"""
        CREATE VIRTUAL TABLE IF NOT EXISTS jobs_fts USING fts5(
            {columns},
            content='jobs',
            content_rowid='id',
            tokenize='unicode61 remove_diacritics 2'
        )
    """)
    values = ", ".join(f"new.{name}" for name in INDEXED_COLUMNS)
    old_values = ", ".join(f"old.{name}" for name in INDEXED_COLUMNS)
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS jobs_fts_insert AFTER INSERT ON jobs BEGIN
            INSERT INTO jobs_fts(rowid, {columns}) VALUES (new.id, {values});
        END""")
    # An external-content index is updated by writing a 'delete' row carrying
    # the OLD values; using the new ones leaves the old terms in the index and
    # a posting keeps matching text it no longer contains.
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS jobs_fts_delete AFTER DELETE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, {columns})
            VALUES ('delete', old.id, {old_values});
        END""")
    conn.execute(f"""
        CREATE TRIGGER IF NOT EXISTS jobs_fts_update AFTER UPDATE ON jobs BEGIN
            INSERT INTO jobs_fts(jobs_fts, rowid, {columns})
            VALUES ('delete', old.id, {old_values});
            INSERT INTO jobs_fts(rowid, {columns}) VALUES (new.id, {values});
        END""")
    return conn


def rebuild(conn):
    """Rebuild the index from ``jobs``. Returns the number of rows indexed."""
    conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES ('rebuild')")
    return conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0]


def integrity_ok(conn):
    """Whether the index still agrees with the table it points at."""
    try:
        conn.execute("INSERT INTO jobs_fts(jobs_fts) VALUES ('integrity-check')")
        return True
    except sqlite3.DatabaseError:
        return False


def sanitise(query):
    """Turn what a person typed into a safe FTS5 expression.

    Each word becomes a quoted term and terms are ANDed. Nothing here exposes
    FTS5's boolean syntax: `NEAR`, `OR` and column filters would let a typo
    become a syntax error, and a search box that errors on an apostrophe is
    worse than one that cannot express a boolean.
    """
    cleaned = _FTS_SPECIAL.sub(" ", query or "")
    terms = [t for t in cleaned.split() if t]
    return " AND ".join(f'"{t}"' for t in terms)


def search(conn, query, *, scope_sql="1=1", limit=25, offset=0, snippet=True):
    """Postings whose text matches, best first.

    ``scope_sql`` is the caller's scope predicate on ``j``, so search obeys the
    same scope contract as every other count rather than inventing its own.
    """
    expression = sanitise(query)
    if not expression:
        return {"query": query, "expression": None, "total": 0, "results": [],
                "note": "an empty query matches nothing rather than everything"}

    total = conn.execute(f"""
        SELECT COUNT(*) FROM jobs_fts f JOIN jobs j ON j.id = f.rowid
        WHERE jobs_fts MATCH ? AND {scope_sql}
    """, (expression,)).fetchone()[0]

    # bm25 weights the title above the body: a posting titled "Assistant
    # Professor of Finance" is a better hit for `finance` than one that says
    # the word once in a paragraph about the department.
    snippet_sql = (", snippet(jobs_fts, 1, '<mark>', '</mark>', ' … ', 24) AS snippet"
                   if snippet else "")
    rows = conn.execute(f"""
        SELECT j.id, j.title_raw, j.discipline_primary, j.status, j.visa_status,
               bm25(jobs_fts, 10.0, 1.0, 2.0, 3.0) AS rank{snippet_sql}
        FROM jobs_fts f JOIN jobs j ON j.id = f.rowid
        WHERE jobs_fts MATCH ? AND {scope_sql}
        ORDER BY rank LIMIT ? OFFSET ?
    """, (expression, limit, offset)).fetchall()

    return {
        "query": query,
        "expression": expression,
        "total": total,
        "results": [dict(row) for row in rows],
        "note": ("Matches are postings whose text contains these words. A hit on "
                 "`sponsorship` may be a posting offering it or refusing it -- read "
                 "the snippet. The derived fields, `visa_status` above all, are the "
                 "answer to what a posting means; a keyword is only a way to find "
                 "rows worth reading."),
    }


def index_status(conn):
    """What the index holds, for the health report."""
    try:
        indexed = conn.execute("SELECT COUNT(*) FROM jobs_fts").fetchone()[0]
    except sqlite3.OperationalError:
        return {"available": False, "reason": "jobs_fts not present"}
    jobs = conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
    return {
        "available": True,
        "indexed_rows": indexed,
        "jobs": jobs,
        "in_step": indexed == jobs,
        "indexed_columns": list(INDEXED_COLUMNS),
        "note": ("An external-content index: `jobs` holds the text and this points "
                 "at it, so the two cannot drift into disagreeing."),
    }


__all__ = ["INDEXED_COLUMNS", "ensure_tables", "index_status", "integrity_ok",
           "rebuild", "sanitise", "search"]
