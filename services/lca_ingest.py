# -*- coding: utf-8 -*-
"""H-1B labour condition applications, faculty slice.

**What an LCA is, and what it is not.** Before filing an H-1B petition an
employer must file a Labor Condition Application attesting to the wage and
working conditions for a role. DOL certifies nearly all of them. So a certified
LCA is evidence that an institution *prepared* to employ someone on an H-1B in
a role of this kind -- not that a petition was filed, not that it was approved,
and not that anyone was hired. Anything built on this file has to keep saying
so, because "certified" reads like an outcome and is not one.

**Why it is worth having anyway.** PERM answers "has this employer sponsored
someone for permanent residency", which is the end of a long road and rare in a
given year. The LCA file answers the much more common question: does this
institution file H-1B paperwork for faculty roles at all, in what fields, and
at what wage. For a candidate asking "is this school even set up to hire
someone who needs sponsorship", that is the closer question -- and PERM alone
understates it badly, because most institutions hire on H-1B for years before
anyone reaches the green-card step.

**What makes the faculty slice cleaner here than in PERM.** The LCA form has no
"college or university teacher" flag, but the SOC taxonomy does the work
instead: ``25-1011`` is literally *Business Teachers, Postsecondary*, and the
whole ``25-1xxx`` block is postsecondary teaching. That is a classification the
publisher made, not one we inferred from a job title.

Three properties of the file that a naive aggregate gets wrong:

* ``TOTAL_WORKER_POSITIONS`` is often greater than one. Counting rows is not
  counting people.
* ``NEW_EMPLOYMENT`` distinguishes a genuinely new hire from a continuation,
  amendment, or transfer for someone already employed. Only the first means the
  institution went to the international market for this role.
* One role can appear across several worksite rows.

Read-only against DOL; writes only to ``academic_market.db``.
"""

import re
import statistics
import urllib.request
from pathlib import Path

from services.academic_market_store import (
    DATASET_LCA, DEFAULT_DOWNLOAD_ROOT, finish_event, register_release, start_event,
)
from services.perm_ingest import (
    _excel_date, _number, classify_business_fields, download, stream_rows,
)

# Verified releases: the URL that actually returned the bytes, with the size
# seen at download time. DOL moves these between /media/ and
# /sites/dolgov/files/, so nothing here is templated from a year number.
LCA_RELEASES = {
    2023: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "LCA_Disclosure_Data_FY2023_Q4.xlsx"),
    2024: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "LCA_Disclosure_Data_FY2024_Q4.xlsx"),
    2025: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "LCA_Disclosure_Data_FY2025_Q4.xlsx"),
}

# The publisher's own classification, strongest first.
EVIDENCE_BUSINESS_SOC = "business_teacher_soc"      # 25-1011 exactly
EVIDENCE_POSTSECONDARY_SOC = "postsecondary_soc"    # 25-1xxx
EVIDENCE_TITLE = "faculty_title"                    # inferred from the title

# 25-1011 Business Teachers, Postsecondary. The one SOC that names this market.
BUSINESS_TEACHER_SOC = "25-1011"
# 25-1xxx is the postsecondary teaching block.
_POSTSECONDARY_SOC_RE = re.compile(r"^25-1\d{3}")

# The fallback for when the code is mistyped. It has to be the phrase, not the
# word: matching "postsecondary" anywhere in the SOC title pulled in 66 rows of
# `11-9033 Education Administrators, Postsecondary` and 3 of `25-9044 Teaching
# Assistants, Postsecondary` against 2 genuine rows -- and labelled them
# `postsecondary_soc`, which claims the publisher classified them as teachers
# when the publisher classified them as administrators.
_POSTSECONDARY_TITLE_RE = re.compile(r"\bteachers,\s*postsecondary\b", re.I)

_FACULTY_TITLE_RE = re.compile(
    r"\b(?:assistant|associate|clinical|visiting|research|teaching|adjunct|full)?\s*"
    r"professor\b|\blecturer\b|\binstructor\b|\bfaculty\b", re.I)

# Titles that contain "professor" or "faculty" without being a faculty post.
# A research administrator is not a hire into the academic labour market.
_NOT_FACULTY_RE = re.compile(
    r"\b(?:faculty\s+(?:assistant|associate\s+(?:dean|director)|affairs|services|"
    r"support|coordinator)|professor(?:'s|s')?\s+assistant)\b", re.I)


def classify_faculty(row):
    """Return the evidence that this case is a faculty post, or None.

    Ordered by who made the judgement. A SOC code is the publisher's
    classification of the occupation; a job title is our reading of free text,
    and the file is full of industry titles that merely contain the word.
    """
    soc = (row.get("SOC_CODE") or "").strip()
    title = (row.get("JOB_TITLE") or "").strip()
    soc_title = (row.get("SOC_TITLE") or "").strip()

    if soc.startswith(BUSINESS_TEACHER_SOC):
        return EVIDENCE_BUSINESS_SOC
    # The SOC title is consulted only to rescue a mistyped code (the file
    # carries `24-1124` for a row whose title is "Foreign Language and
    # Literature Teachers, Postsecondary"), never to widen the category.
    if _POSTSECONDARY_SOC_RE.match(soc) or _POSTSECONDARY_TITLE_RE.search(soc_title):
        return EVIDENCE_POSTSECONDARY_SOC
    if _NOT_FACULTY_RE.search(title):
        return None
    if _FACULTY_TITLE_RE.search(title):
        return EVIDENCE_TITLE
    return None


# The columns a release supplies. `institution_id` is deliberately not among
# them: it is resolved afterwards by institution matching, against the whole
# faculty database, and re-reading the release must not discard that work. A
# re-load that silently orphaned 7,885 resolved cases would look like the
# matcher having regressed.
UPSERT_COLUMNS = (
    "fiscal_year", "decision_date", "begin_date", "end_date", "case_status",
    "visa_class", "employer_name", "employer_state", "worksite_state",
    "job_title", "soc_code", "soc_title", "full_time", "total_worker_positions",
    "new_employment", "continued_employment", "change_employer",
    "amended_petition", "wage_from", "wage_to", "wage_unit", "prevailing_wage",
    "pw_wage_level", "business_field", "faculty_evidence", "release_id",
)

PRESERVED_ON_RELOAD = ("institution_id",)


def upsert_sql():
    """The INSERT used by the loader, built from ``UPSERT_COLUMNS``.

    A case number can appear in two annual files -- certified in one,
    "Certified - Withdrawn" in a later one with a later decision date. The
    later row is the current state of the filing, so the conflict is resolved
    by decision date rather than by whichever file happened to load last.
    """
    columns = ("case_number", *UPSERT_COLUMNS)
    assignments = ", ".join(
        f"{name} = excluded.{name}" for name in UPSERT_COLUMNS)
    placeholders = ",".join("?" * len(columns))
    return (
        f"INSERT INTO lca_faculty_cases ({', '.join(columns)}) "
        f"VALUES ({placeholders}) "
        f"ON CONFLICT(case_number) DO UPDATE SET {assignments} "
        f"WHERE excluded.decision_date > lca_faculty_cases.decision_date"
    )


def _int(value):
    try:
        return int(float(str(value).replace(",", "").strip()))
    except (TypeError, ValueError):
        return None


def load_year(conn, fiscal_year, *, download_root=None, row_limit=None, echo=None):
    """Download (if needed) and load one fiscal year's faculty cases.

    The whole file is streamed and only faculty cases are kept: the FY2024
    release is 83MB and roughly 800k rows, almost none of it academic.
    """
    echo = echo or (lambda *_args, **_kwargs: None)
    if fiscal_year not in LCA_RELEASES:
        raise ValueError(
            f"no verified LCA release recorded for FY{fiscal_year}; "
            f"known: {sorted(LCA_RELEASES)}. Add the URL that actually worked "
            "rather than templating one.")
    url = LCA_RELEASES[fiscal_year]
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT) / "dol"
    local = root / f"LCA_FY{fiscal_year}.xlsx"

    event_id = start_event(conn, DATASET_LCA, f"LCA_FY{fiscal_year}")
    try:
        if local.exists() and local.stat().st_size > 1_000_000:
            echo(f"using the file already downloaded: {local.name} "
                 f"({local.stat().st_size} bytes)")
            status = None
        else:
            echo(f"downloading {url}")
            local, status = download(url, local)
            echo(f"  {local.stat().st_size} bytes")

        release_id = register_release(
            conn, DATASET_LCA, f"LCA_FY{fiscal_year}", url,
            data_year=fiscal_year, local_path=str(local), http_status=status,
            note=("faculty cases only; the full file is ~800k rows. A certified "
                  "LCA is a pre-petition attestation, not an approved H-1B and "
                  "not a hire."))

        considered = kept = superseded = 0
        by_evidence = {}
        rows = stream_rows(str(local), limit=row_limit)
        for row in rows:
            considered += 1
            evidence = classify_faculty(row)
            if not evidence:
                continue
            fields = classify_business_fields(row)
            # A case number can appear in two annual files: certified in one,
            # "Certified - Withdrawn" in a later one, with a later decision
            # date. The later row is the current state of the filing. With
            # INSERT OR REPLACE the surviving row was whichever file happened
            # to load last, so a withdrawal was recorded as a certification
            # whenever the years were loaded out of order.
            cursor = conn.execute(upsert_sql(), (
                (row.get("CASE_NUMBER") or "").strip() or f"row-{considered}",
                fiscal_year,
                _excel_date(row.get("DECISION_DATE")),
                _excel_date(row.get("BEGIN_DATE")),
                _excel_date(row.get("END_DATE")),
                (row.get("CASE_STATUS") or "").strip() or None,
                (row.get("VISA_CLASS") or "").strip() or None,
                (row.get("EMPLOYER_NAME") or "").strip(),
                (row.get("EMPLOYER_STATE") or "").strip() or None,
                (row.get("WORKSITE_STATE") or "").strip() or None,
                (row.get("JOB_TITLE") or "").strip() or None,
                (row.get("SOC_CODE") or "").strip() or None,
                (row.get("SOC_TITLE") or "").strip() or None,
                (row.get("FULL_TIME_POSITION") or "").strip() or None,
                _int(row.get("TOTAL_WORKER_POSITIONS")),
                _int(row.get("NEW_EMPLOYMENT")),
                _int(row.get("CONTINUED_EMPLOYMENT")),
                _int(row.get("CHANGE_EMPLOYER")),
                _int(row.get("AMENDED_PETITION")),
                _number(row.get("WAGE_RATE_OF_PAY_FROM")),
                _number(row.get("WAGE_RATE_OF_PAY_TO")),
                (row.get("WAGE_UNIT_OF_PAY") or "").strip() or None,
                _number(row.get("PREVAILING_WAGE")),
                (row.get("PW_WAGE_LEVEL") or "").strip() or None,
                ",".join(fields) if fields else None,
                evidence,
                release_id,
            ))
            if cursor.rowcount:
                kept += 1
                by_evidence[evidence] = by_evidence.get(evidence, 0) + 1
            else:
                # The stored row already carries a decision at least as late as
                # this one. Counted, not discarded quietly.
                superseded += 1
            if kept % 500 == 0:
                conn.commit()
                echo(f"  {considered} rows scanned, {kept} faculty cases kept")
        conn.commit()
        summary = {"fiscal_year": fiscal_year, "rows_scanned": considered,
                   "faculty_cases": kept, "superseded": superseded,
                   "by_evidence": by_evidence, "release_id": release_id}
        finish_event(conn, event_id, "ok", rows_read=considered, rows_written=kept,
                     rows_skipped=considered - kept,
                     detail={"by_evidence": by_evidence, "superseded": superseded,
                             "note": ("faculty slice only; a certified LCA is a "
                                      "pre-petition attestation, not a hire. "
                                      "`superseded` rows lost to a later decision "
                                      "on the same case number.")})
        return summary
    except Exception as exc:
        finish_event(conn, event_id, "error", error=f"{type(exc).__name__}: {exc}")
        raise


# A filing whose offered wage is wildly out of line with the prevailing wage
# attested on the same form is a keying error, not a salary. Kent State filed
# one assistant professorship four times at $81,553 and once at $8,155,283
# against a prevailing wage of $52,397 -- a mean over that row reported the
# institution at $1.24m. The threshold is anchored to the file's own number
# rather than to an assumption about what a professor earns, and the row is
# reported as excluded rather than quietly dropped.
IMPLAUSIBLE_WAGE_RATIO = 10.0


def _annual_wage_rows(conn, where, args):
    """Annual offered wages, split into usable values and keying errors."""
    rows = conn.execute(f"""
        SELECT wage_from, prevailing_wage, employer_name, case_number
        FROM lca_faculty_cases
        {where} AND wage_unit = 'Year' AND wage_from IS NOT NULL AND wage_from > 0
    """, args).fetchall()
    usable, outliers = [], []
    for row in rows:
        prevailing = row["prevailing_wage"] or 0
        if prevailing > 0 and row["wage_from"] > prevailing * IMPLAUSIBLE_WAGE_RATIO:
            outliers.append({"case_number": row["case_number"],
                             "employer_name": row["employer_name"],
                             "wage_from": row["wage_from"],
                             "prevailing_wage": prevailing})
        else:
            usable.append(row["wage_from"])
    return usable, outliers


def _wage_summary(conn, where, args):
    """Median, not mean. One keyed-in extra digit moves a mean and not a median.

    Non-annual units are excluded rather than converted: the file carries
    hourly rows with 80000 in the amount, so a unit conversion would turn a
    second keying error into a plausible-looking salary.
    """
    usable, outliers = _annual_wage_rows(conn, where, args)
    return {
        "median_annual_wage": round(statistics.median(usable)) if usable else None,
        "wage_rows_used": len(usable),
        "wage_rows_excluded": len(outliers),
        "excluded_examples": outliers[:3],
        "wage_note": (
            "Median of the offered annual wage, over filings quoting a yearly "
            f"rate. {len(outliers)} row(s) were excluded as keying errors -- the "
            f"offered wage exceeded the prevailing wage attested on the same form "
            f"by more than {IMPLAUSIBLE_WAGE_RATIO:.0f}x. Hourly, monthly and "
            "weekly filings are not converted, because the file also contains "
            "annual amounts entered under an hourly unit."),
    }


def institution_profile(conn, employer_like, years=5):
    """One institution's H-1B faculty filings, with the distinctions kept.

    Deliberately reports new employment separately from the total. A school
    with forty continuations and no new filings is not currently hiring from
    the international market, and one number for both would say it was.
    """
    rows = conn.execute("""
        SELECT fiscal_year,
               COUNT(*)                             AS cases,
               SUM(COALESCE(total_worker_positions,1)) AS positions,
               SUM(COALESCE(new_employment,0))      AS new_employment,
               SUM(COALESCE(continued_employment,0)) AS continued,
               SUM(COALESCE(change_employer,0))     AS transfers,
               SUM(CASE WHEN case_status = 'Certified' THEN 1 ELSE 0 END) AS certified,
               SUM(CASE WHEN case_status LIKE '%Withdrawn%' THEN 1 ELSE 0 END) AS withdrawn,
               SUM(CASE WHEN case_status = 'Denied' THEN 1 ELSE 0 END) AS denied,
               SUM(CASE WHEN soc_code LIKE ? THEN 1 ELSE 0 END) AS business_teacher
        FROM lca_faculty_cases
        WHERE employer_name LIKE ?
        GROUP BY fiscal_year ORDER BY fiscal_year DESC LIMIT ?
    """, (BUSINESS_TEACHER_SOC + "%", employer_like, years)).fetchall()
    wages = _wage_summary(conn, "WHERE employer_name LIKE ?", (employer_like,))
    return {
        "employer_like": employer_like,
        "years": [dict(row) for row in rows],
        "wages": wages,
        "caveat": (
            "A certified LCA is a pre-petition attestation, not an approved H-1B "
            "and not a hire. `positions` counts the worker positions each filing "
            "covers, which is larger than the number of filings. `new_employment` "
            "is the only column that indicates hiring rather than continuing "
            "someone already employed. `withdrawn` filings are counted separately "
            "because the employer took them back. An institution's filing history "
            "says nothing about whether a particular job will sponsor."),
    }


def business_faculty_summary(conn, fiscal_year=None):
    """Who files H-1B paperwork for business faculty, and at what wage."""
    where = "WHERE soc_code LIKE ?"
    args = [BUSINESS_TEACHER_SOC + "%"]
    if fiscal_year:
        where += " AND fiscal_year = ?"
        args.append(fiscal_year)
    top = conn.execute(f"""
        SELECT employer_name,
               COUNT(*) AS cases,
               SUM(CASE WHEN case_status = 'Certified' THEN 1 ELSE 0 END) AS certified,
               SUM(COALESCE(new_employment,0)) AS new_employment
        FROM lca_faculty_cases {where}
        GROUP BY employer_name ORDER BY cases DESC LIMIT 25
    """, args).fetchall()
    totals = conn.execute(f"""
        SELECT COUNT(*) AS cases,
               COUNT(DISTINCT employer_name) AS employers,
               SUM(COALESCE(total_worker_positions,1)) AS positions,
               SUM(COALESCE(new_employment,0)) AS new_employment,
               SUM(CASE WHEN case_status = 'Certified' THEN 1 ELSE 0 END) AS certified,
               SUM(CASE WHEN case_status LIKE '%Withdrawn%' THEN 1 ELSE 0 END) AS withdrawn
        FROM lca_faculty_cases {where}
    """, args).fetchone()
    # Each employer's own median, so one keying error cannot move a row.
    employers = []
    for row in top:
        entry = dict(row)
        entry.update(_wage_summary(
            conn, where + " AND employer_name = ?", [*args, row["employer_name"]]))
        employers.append(entry)
    return {
        "soc_code": BUSINESS_TEACHER_SOC,
        "soc_title": "Business Teachers, Postsecondary",
        "fiscal_year": fiscal_year,
        "totals": dict(totals) if totals else {},
        "wages": _wage_summary(conn, where, args),
        "top_employers": employers,
        "caveat": (
            "Filings, not hires. Restricted to SOC 25-1011, the publisher's own "
            "code for business teachers; a business-school appointment filed "
            "under another code is not counted here, so these are floors. "
            "`certified` excludes withdrawn and denied filings, which `cases` "
            "includes."),
    }


__all__ = ["BUSINESS_TEACHER_SOC", "IMPLAUSIBLE_WAGE_RATIO", "EVIDENCE_BUSINESS_SOC", "EVIDENCE_POSTSECONDARY_SOC",
           "EVIDENCE_TITLE", "LCA_RELEASES", "business_faculty_summary", "classify_faculty",
           "institution_profile", "load_year"]
