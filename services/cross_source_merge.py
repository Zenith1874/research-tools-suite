# -*- coding: utf-8 -*-
"""One vacancy listed on two boards is one vacancy.

Schools syndicate a posting to several boards. The existing canonical key is
built from the application URL and a fingerprint of the listing text, so two
boards carrying the same vacancy produce different keys and two rows. The
coverage matrix then reported 97-100% of postings as "single-sourced", which
read as a fact about the market and was partly an artefact of this.

**The costs are asymmetric, so the rules lean towards not merging.** Merging
two genuinely distinct vacancies erases one and understates the market; failing
to merge overcounts, which is visible and can be fixed later with both rows
still intact.

Three rules, and the reasoning for each is the point:

**Same institution and the same normalised title.** Both are external facts --
the institution comes from entity resolution and the title from the board's own
text. Nothing here uses a field we derived.

**The title must be specific.** A bare "Assistant Professor" is not evidence:
one school can advertise two of them in different departments on the same day.

**Each source contributes exactly one row.** Where a board lists seven "Adjunct
Faculty, Accounting" postings -- community colleges really do -- there is no way
to know which of the seven a second board's single listing corresponds to, and
picking one would be a guess.

Two things deliberately *not* used as gates:

* **Observation windows.** ``first_seen_at`` records when *we* looked, not when
  the vacancy existed. Two live postings crawled two days apart have
  non-overlapping windows, and gating on that would let our crawl schedule
  decide what counts as the same job.
* **Discipline agreement.** It is our own classification, derived from whichever
  blurb each board carried, and it disagrees with itself on the same vacancy --
  Stanford's "GSB Faculty Positions in Operations, Information..." is filed as
  `Other` from one board and `Information Systems / MIS` from another. Gating on
  it would let our noise veto correct merges, and worst of all it would veto
  exactly the pairs whose blurbs differ most.

Both remain useful as review signals, and both are reported.
"""

import json
import re
from collections import defaultdict

# A title that names only a rank. Merging on one of these would treat two
# departments' vacancies as a single job.
GENERIC_TITLE_RE = re.compile(
    r"^(?:(?:assistant|associate|full|open[ -]?rank|tenure[ -]?track|clinical|"
    r"visiting|adjunct|teaching|part[ -]?time|temporary)\s+)*"
    r"(?:professor|lecturer|instructor|faculty|faculty\s+position)s?\.?$", re.I)

REASON_GENERIC = "title names only a rank; one school can advertise several"
REASON_AMBIGUOUS = "a source lists more than one posting with this title, so the pairing would be a guess"
REASON_SINGLE_SOURCE = "only one source carries it"


class MergeCollision(RuntimeError):
    """The surviving row already holds a link the merge would move onto it."""


def is_generic_title(title):
    return bool(GENERIC_TITLE_RE.match(str(title or "").strip()))


# Several of the society boards -- AIS, SMS, POMS, the Chronicle's business
# listings -- are skins over one careerwebsite/YM Careers network, and each
# carries the underlying posting's own id in the URL. That id is the board's
# fact about its own posting, which makes it better evidence than a title:
# Shanghai Jiao Tong's IT & Innovation posting is one vacancy under id
# 84951765, and the title rule missed it only because one skin truncated the
# title to "...the Information" and the other did not.
BOARD_ID_RE = re.compile(r"/job/[^/]+/(\d{6,})/?$")

BASIS_TITLE = "same institution, same specific title, one posting per source"
BASIS_BOARD_ID = ("same institution and the same board posting id in both URLs, "
                  "one posting per source")


def board_id(url):
    match = BOARD_ID_RE.search(str(url or ""))
    return match.group(1) if match else None


def board_id_groups(conn, scope_sql="1=1"):
    """Postings that two boards publish under one shared-network posting id.

    Narrower than the title rule -- only the shared network puts an id in the
    URL at all -- but stronger where it applies, and it catches vacancies the
    title rule cannot, such as a board that truncates long titles.
    """
    buckets = defaultdict(set)
    labels = {}
    for row in conn.execute(f"""
            SELECT js.job_id, js.source_url, j.institution_id, j.title_normalized,
                   i.official_name AS institution
            FROM job_sources js
            JOIN jobs j ON j.id = js.job_id
            JOIN institutions i ON i.id = j.institution_id
            WHERE js.active = 1 AND j.merged_into_job_id IS NULL AND {scope_sql}
    """).fetchall():
        found = board_id(row["source_url"])
        if not found:
            continue
        key = (row["institution_id"], found)
        buckets[key].add(row["job_id"])
        # The fuller title, not whichever row came last: a truncated one is
        # exactly what this rule exists to see past, so it should not be the
        # label the report shows.
        title = row["title_normalized"] or ""
        if len(title) > len(labels.get(key, ("", ""))[1]):
            labels[key] = (row["institution"], title)
    groups = []
    for (institution_id, found), ids in buckets.items():
        if len(ids) < 2:
            continue
        institution, title = labels[(institution_id, found)]
        groups.append({"institution_id": institution_id, "institution": institution,
                       "title": title, "board_id": found,
                       "ids": ",".join(str(i) for i in sorted(ids))})
    return groups


def candidate_groups(conn, scope_sql="1=1"):
    """Postings sharing an institution and a normalised title across sources."""
    # Plain dicts, so a group from here and one from board_id_groups are the
    # same shape to everything downstream.
    return [dict(row) for row in conn.execute(f"""
        SELECT j.institution_id, i.official_name AS institution,
               j.title_normalized AS title,
               GROUP_CONCAT(DISTINCT j.id) AS ids
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        JOIN sources s ON s.id = js.source_id
        JOIN institutions i ON i.id = j.institution_id
        WHERE j.title_normalized IS NOT NULL AND TRIM(j.title_normalized) != ''
          AND j.merged_into_job_id IS NULL
          AND {scope_sql}
        GROUP BY j.institution_id, j.title_normalized
        HAVING COUNT(DISTINCT j.id) > 1 AND COUNT(DISTINCT s.name) > 1
    """)]


def _members(conn, ids):
    """One entry per posting, carrying every board that lists it.

    Per *posting*, not per posting-and-board: a row that already carries two
    boards came back twice, so it landed in the absorb list twice and the
    second pass tried to move a link it had just moved. It never got written --
    the collision check stopped the run -- but the count of postings per source
    was being read off duplicated rows too, which is the number the ambiguity
    rule depends on.
    """
    marks = ",".join("?" * len(ids))
    rows = conn.execute(f"""
        SELECT j.id, j.title_raw, j.status, j.discipline_primary, j.deadline_date,
               j.official_url, j.first_seen_at, j.last_seen_at,
               LENGTH(COALESCE(j.description_excerpt, '')) AS body_chars,
               s.name AS source
        FROM jobs j
        JOIN job_sources js ON js.job_id = j.id AND js.active = 1
        JOIN sources s ON s.id = js.source_id
        WHERE j.id IN ({marks})
    """, ids).fetchall()
    members = {}
    for row in rows:
        entry = members.setdefault(row["id"], dict(row))
        entry.pop("source", None)
        entry.setdefault("sources", []).append(row["source"])
    for entry in members.values():
        entry["sources"] = sorted(set(entry["sources"]))
    return sorted(members.values(), key=lambda e: e["id"])


REASON_ALREADY_MERGED = "already folded in by the title rule"
REASON_CONFIRMED_DISTINCT = ("a person reviewed this pair and recorded that they are "
                             "different jobs")


def _confirmed_distinct(conn, ids):
    """True if any pair among these postings was judged distinct by a person."""
    marks = ",".join("?" * len(ids))
    return conn.execute(f"""
        SELECT 1 FROM possible_duplicates
        WHERE resolution = 'confirmed_distinct'
          AND job_id IN ({marks}) AND possible_job_id IN ({marks})
        LIMIT 1
    """, (*ids, *ids)).fetchone() is not None


def assess(conn, group, basis=BASIS_TITLE):
    """Decide one group. Returns a verdict dict; never writes."""
    ids = [int(x) for x in str(group["ids"]).split(",")]
    rows = _members(conn, ids)
    # Distinct postings per board, which is what the ambiguity rule is about.
    by_source = defaultdict(set)
    for row in rows:
        for source in row["sources"]:
            by_source[source].add(row["id"])

    verdict = {
        "institution": group["institution"],
        "title": group["title"],
        "basis": basis,
        "board_id": group.get("board_id"),
        "sources": sorted(by_source),
        "members": rows,
        "merge": False,
        "reason": None,
    }
    if len(by_source) < 2:
        verdict["reason"] = REASON_SINGLE_SOURCE
        return verdict
    # A shared board id identifies the posting on its own, so a title that
    # names only a rank is no longer the only thing being relied on.
    if basis == BASIS_TITLE and is_generic_title(group["title"]):
        verdict["reason"] = REASON_GENERIC
        return verdict
    if any(len(jobs) > 1 for jobs in by_source.values()):
        verdict["reason"] = REASON_AMBIGUOUS
        return verdict
    # A person who looked at the pair and said they are different jobs outranks
    # anything inferred here. Only `confirmed_distinct` vetoes: `rejected` is
    # the fuzzy scorer closing its own low-scoring candidate, and this rule
    # rests on different evidence than the score it rejected.
    if _confirmed_distinct(conn, [row["id"] for row in rows]):
        verdict["reason"] = REASON_CONFIRMED_DISTINCT
        return verdict

    # The surviving row is the one carrying the most posting text: a merge
    # should never lose the fullest description we hold.
    members = sorted(rows, key=lambda r: (-(r["body_chars"] or 0), r["id"]))
    verdict.update({
        "merge": True,
        "reason": basis,
        "keep": members[0]["id"],
        "absorb": [r["id"] for r in members[1:]],
        # Reported, not used to decide: both are ours, and both disagree with
        # themselves on postings that are plainly the same vacancy.
        "disciplines_agree": len({r["discipline_primary"] for r in rows}) == 1,
        "windows_overlap": max(r["first_seen_at"] for r in rows)
                           <= min(r["last_seen_at"] for r in rows),
    })
    return verdict


def plan(conn, scope_sql="1=1"):
    """Every group with its verdict, and a summary of why the rest were left.

    Title groups are decided first and the board-id rule then fills in what
    they could not see. A board-id group that shares a posting with an already
    accepted group is refused rather than reconciled: two plans disagreeing
    about which row survives is exactly the situation where a merge quietly
    does the wrong thing.
    """
    verdicts = [assess(conn, g) for g in candidate_groups(conn, scope_sql)]
    claimed = {row["id"] for v in verdicts if v["merge"] for row in v["members"]}
    for group in board_id_groups(conn, scope_sql):
        verdict = assess(conn, group, BASIS_BOARD_ID)
        # A posting an accepted group already covers is not merged twice. It
        # is still reported: a group vanishing from the plan with no line
        # explaining it is how a rule stops being reviewable.
        if {row["id"] for row in verdict["members"]} & claimed:
            verdict.update({"merge": False, "reason": REASON_ALREADY_MERGED})
        elif verdict["merge"]:
            claimed |= {row["id"] for row in verdict["members"]}
        verdicts.append(verdict)
    merges = [v for v in verdicts if v["merge"]]
    held = defaultdict(int)
    for v in verdicts:
        if not v["merge"]:
            held[v["reason"]] += 1
    return {
        "groups": len(verdicts),
        "merges": merges,
        "rows_absorbed": sum(len(v["absorb"]) for v in merges),
        "held_back": dict(held),
        "note": ("Held-back groups are left as separate postings on purpose. "
                 "Over-counting is visible and reversible; merging two real "
                 "vacancies erases one."),
    }


# Fields worth carrying across from an absorbed row. Only ever filled where the
# survivor has nothing: one board stating a deadline and another staying silent
# is not a disagreement, but two boards stating different deadlines is, and
# overwriting would pick a winner with no evidence for it.
CARRIED_FIELDS = (
    "deadline_date", "official_url", "department", "discipline_primary",
    "posted_date", "salary_raw", "start_term", "start_year",
)


def _carry_over(conn, keep_id, absorb_ids):
    """Fill only the survivor's empty fields. Returns what was filled."""
    keep = conn.execute("SELECT * FROM jobs WHERE id=?", (keep_id,)).fetchone()
    filled = {}
    for field in CARRIED_FIELDS:
        if keep[field] not in (None, ""):
            continue
        for row_id in absorb_ids:
            value = conn.execute(
                f"SELECT {field} FROM jobs WHERE id=?", (row_id,)).fetchone()[0]
            if value not in (None, ""):
                filled[field] = value
                break
    for field, value in filled.items():
        conn.execute(f"UPDATE jobs SET {field}=? WHERE id=?", (value, keep_id))
    return filled


def _close_review_items(conn, keep, absorb, now, basis):
    """Resolve queued duplicate pairs this merge answers. Returns their ids."""
    closed = []
    for row_id in absorb:
        for pending in conn.execute("""
                SELECT id FROM possible_duplicates
                WHERE resolved = 0
                  AND ((job_id = ? AND possible_job_id = ?)
                       OR (job_id = ? AND possible_job_id = ?))
        """, (keep, row_id, row_id, keep)).fetchall():
            conn.execute("""
                UPDATE possible_duplicates
                SET resolved = 1, resolution = 'merged', resolved_at = ?,
                    resolution_reason = ?, merged_into_job_id = ?
                WHERE id = ?
            """, (now, f"Folded by the cross-source duplicate merge: {basis}.",
                  keep, pending["id"]))
            closed.append(pending["id"])
    return closed


def apply_merge(conn, verdict, now):
    """Fold one group onto its surviving row. Deletes nothing.

    ``jobs`` is a preserved table -- the write guard fails the run if its count
    drops -- and that constraint is the right one: an absorbed row is still a
    thing a board published, and a merge is a claim we might have got wrong.
    So the row stays exactly as it was and gains a pointer to the survivor;
    the scope contract stops counting it, and clearing one column undoes it.

    The source links move, because a link records where the vacancy was seen
    and the whole assertion is that it was seen in both places. The audit row
    keeps each link's original job so the move is reversible too.
    """
    keep, absorb = verdict["keep"], verdict["absorb"]
    moved, blocked = [], []
    for row_id in absorb:
        for link in conn.execute(
                "SELECT source_id, source_job_id FROM job_sources WHERE job_id=?",
                (row_id,)).fetchall():
            # UNIQUE(source_id, source_job_id) makes a collision impossible for
            # the groups this admits -- one posting per source. Checked anyway:
            # a crash mid-merge would be a far worse way to find out.
            clash = conn.execute(
                "SELECT 1 FROM job_sources WHERE job_id=? AND source_id=? AND source_job_id=?",
                (keep, link["source_id"], link["source_job_id"])).fetchone()
            if clash:
                blocked.append((row_id, link["source_id"], link["source_job_id"]))
                continue
            conn.execute(
                "UPDATE job_sources SET job_id=? WHERE job_id=? AND source_id=? AND source_job_id=?",
                (keep, row_id, link["source_id"], link["source_job_id"]))
            moved.append({"from_job_id": row_id, "source_id": link["source_id"],
                          "source_job_id": link["source_job_id"]})
    if blocked:
        raise MergeCollision(
            f"group {verdict['institution']} / {verdict['title']}: "
            f"the surviving row already holds {blocked}")

    # Anything in the review queue that this decides is closed here. Leaving it
    # open would ask a person to judge a pair the database has already folded,
    # and the queue is only useful while everything in it is still undecided.
    closed = _close_review_items(conn, keep, absorb, now, verdict["basis"])

    filled = _carry_over(conn, keep, absorb)
    marks = ",".join("?" * len(absorb))
    conn.execute(
        f"UPDATE jobs SET merged_into_job_id=?, updated_at=? WHERE id IN ({marks})",
        (keep, now, *absorb))

    conn.execute("""
        INSERT INTO faculty_job_repair_audit
          (observed_at, action, job_id, old_value, new_value, reason)
        VALUES (?,?,?,?,?,?)
    """, (now, "cross_source_duplicate_merge", keep,
          json.dumps({"absorbed_job_ids": absorb, "moved_source_links": moved,
                      "review_items_closed": closed},
                     ensure_ascii=False, sort_keys=True),
          json.dumps({"surviving_job_id": keep, "fields_filled": filled,
                      "sources": verdict["sources"],
                      "disciplines_agree": verdict["disciplines_agree"],
                      "windows_overlap": verdict["windows_overlap"]},
                     ensure_ascii=False, sort_keys=True),
          (f"{verdict['institution']} lists \"{verdict['title']}\" on "
           f"{len(verdict['sources'])} boards, one posting each. Accepted because: "
           f"{verdict['basis']} -- facts from outside our derivations. "
           "Observation windows and discipline labels were not used to decide: "
           "the first records when we crawled, the second is our own classifier "
           "and it disagrees with itself on postings that are plainly the same "
           "vacancy. Rows are retained and pointed at the survivor, not deleted; "
           "clearing merged_into_job_id restores them.")))
    return {"keep": keep, "absorbed": absorb, "moved_source_links": moved,
            "fields_filled": filled, "review_items_closed": closed}


def apply_all(conn, merges, now):
    """Apply every accepted group. Caller owns the transaction and the guard."""
    return [apply_merge(conn, verdict, now) for verdict in merges]


__all__ = ["BASIS_BOARD_ID", "BASIS_TITLE", "BOARD_ID_RE", "CARRIED_FIELDS",
           "GENERIC_TITLE_RE", "MergeCollision", "REASON_AMBIGUOUS",
           "REASON_ALREADY_MERGED", "REASON_CONFIRMED_DISTINCT", "REASON_GENERIC",
           "REASON_SINGLE_SOURCE",
           "apply_all", "apply_merge", "assess", "board_id", "board_id_groups",
           "candidate_groups", "is_generic_title", "plan"]
