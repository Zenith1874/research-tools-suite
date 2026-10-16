# -*- coding: utf-8 -*-
"""DOL PERM disclosure: institutional sponsorship history and academic mobility.

Two things this answers that nothing else public does.

**Which institutions have actually sponsored faculty green cards.** Not whether
a particular job will -- that is a claim about a posting and belongs to the
posting's own text -- but whether this employer has filed before, how often,
how recently, and with what outcome. The file carries
``APP_FOR_COLLEGE_U_TEACHER``, the flag for the §656.18 special-handling
process that exists only for college and university teachers, so faculty cases
are identifiable by the form's own field rather than by guessing at job titles.

**Where hired international faculty did their doctorates.**
``FOREIGN_WORKER_INST_OF_ED`` names the institution that awarded the degree,
so PhD-origin to hiring-institution flow is directly observable. It is the only
public source for that link.

The population is administrative and biased in a specific direction: it
contains people whose employer filed a labour certification, so it under-counts
EB-1B hires entirely -- outstanding-professor petitions need no PERM -- along
with everyone who never needed sponsorship and everyone who left. Counts from
here are floors on sponsorship activity, not a census of international faculty.

The disclosure file is ~500k rows and 155 columns a year. Only faculty cases
are kept: the rest is 99% non-academic and storing it would trade a 4 MB table
for a 600 MB one that no query here would touch.
"""

import re
import urllib.request
from datetime import date, timedelta
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from services.academic_market_store import (
    DATASET_PERM, DEFAULT_DOWNLOAD_ROOT, finish_event, register_release, start_event,
)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
UA = ("research-tools-suite/academic-career (+local research workstation; "
      "annual public disclosure file download)")

# Verified releases. DOL moves these between /media/ and /sites/dolgov/files/,
# so the URL that worked is recorded rather than templated.
PERM_RELEASES = {
    2024: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "PERM_Disclosure_Data_FY2024_Q4.xlsx"),
    2025: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "PERM_Disclosure_Data_FY2025_Q4.xlsx"),
    2023: ("https://www.dol.gov/sites/dolgov/files/ETA/oflc/pdfs/"
           "PERM_Disclosure_Data_FY2023_Q4.xlsx"),
}

# How we concluded a case is academic, most authoritative first. The form's own
# field beats any reading of a job title.
EVIDENCE_FORM_FLAG = "college_u_teacher_flag"
EVIDENCE_SOC = "postsecondary_soc"
EVIDENCE_TITLE = "faculty_title"

_FACULTY_SOC_RE = re.compile(r"postsecondary|professor", re.I)
_FACULTY_TITLE_RE = re.compile(
    r"\b(?:assistant|associate|clinical|visiting|research|teaching|full)?\s*"
    r"professor\b|\blecturer\b|\binstructor\b|\bfaculty\b", re.I)

# Business fields, from the job title and the degree major. Multi-label on
# purpose: "Assistant Professor of Information Systems and Operations" is both.
_FIELD_PATTERNS = (
    ("Accounting", r"\baccount"),
    ("Finance", r"\bfinanc|\bbanking\b"),
    ("Marketing", r"\bmarketing\b"),
    ("Information Systems", r"\binformation\s+systems?\b|\bMIS\b|\binformation\s+technology\b"),
    ("Operations", r"\boperations?\s+(?:management|research)\b"),
    ("Supply Chain", r"\bsupply\s+chain\b|\blogistics\b"),
    ("Business Analytics", r"\b(?:business\s+)?analytics\b|\bdata\s+science\b"),
    ("Strategy", r"\bstrateg"),
    ("Organizational Behavior", r"\borganizational\s+behavio"),
    ("Human Resources", r"\bhuman\s+resource"),
    ("Entrepreneurship", r"\bentrepreneur"),
    ("Management", r"\bmanagement\b|\bmanagerial\b"),
    ("Economics", r"\beconomic"),
    ("General Business", r"\bbusiness\b|\bcommerce\b"),
)
_FIELD_RES = tuple((name, re.compile(pattern, re.I)) for name, pattern in _FIELD_PATTERNS)


def classify_faculty(row, resolved=None):
    """Is this an academic case, and on what evidence?

    Returns ``(is_faculty, evidence)``. The form's own college-teacher flag is
    definitive; SOC and title are weaker readings, recorded as such so a later
    analysis can restrict to the strong ones.
    """
    resolved = resolved if resolved is not None else {
        name: candidates[-1] for name, candidates in PERM_COLUMNS.items()}
    flag = (field(row, resolved, "college_teacher_flag") or "").strip().upper()
    if flag in {"Y", "YES", "TRUE", "1"}:
        return True, EVIDENCE_FORM_FLAG
    soc = field(row, resolved, "soc_title") or ""
    if _FACULTY_SOC_RE.search(soc):
        return True, EVIDENCE_SOC
    title = field(row, resolved, "job_title") or ""
    if _FACULTY_TITLE_RE.search(title):
        return True, EVIDENCE_TITLE
    return False, None


def classify_business_fields(row):
    """Business fields a case touches, from title and degree major.

    Multi-label, and empty when nothing matches -- an academic case in
    chemistry gets no business field rather than a default one.
    """
    # Every name any release has used, across PERM and LCA: PERM renamed
    # PW_SOC_TITLE to PWD_SOC_TITLE in FY2025 and the LCA file calls it
    # SOC_TITLE. Reading whichever are present beats naming one and getting
    # an empty string from the others.
    haystack = " ".join(
        str(row.get(key) or "") for key in
        ("JOB_TITLE", "SOC_TITLE", "PW_SOC_TITLE", "PWD_SOC_TITLE",
         "FOREIGN_WORKER_INFO_MAJOR", "MAJOR_FIELD_OF_STUDY")
        if key in row)
    found = [name for name, pattern in _FIELD_RES if pattern.search(haystack)]
    # "General Business" is a fallback, not a peer: drop it when something
    # specific matched.
    if len(found) > 1 and "General Business" in found:
        found.remove("General Business")
    return found


def _shared_strings(archive):
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(raw).iter(NS + "si")]


def stream_rows(path, limit=None):
    """Yield the sheet as dicts without loading 500k rows into memory."""
    archive = zipfile.ZipFile(path)
    strings = _shared_strings(archive)
    sheets = sorted(n for n in archive.namelist()
                    if n.startswith("xl/worksheets/sheet"))
    header = None
    count = 0
    with archive.open(sheets[0]) as handle:
        for _event, element in ET.iterparse(handle, events=("end",)):
            if element.tag != NS + "row":
                continue
            cells = {}
            for cell in element.iter(NS + "c"):
                ref = cell.get("r") or ""
                column = re.match(r"([A-Z]+)", ref)
                if not column:
                    continue
                value = cell.find(NS + "v")
                text = value.text if value is not None else None
                if cell.get("t") == "s" and text is not None:
                    try:
                        text = strings[int(text)]
                    except (ValueError, IndexError):
                        pass
                elif cell.get("t") == "inlineStr":
                    text = "".join(t.text or "" for t in cell.iter(NS + "t"))
                cells[column.group(1)] = (text or "").strip()
            element.clear()
            if header is None:
                header = {col: name for col, name in cells.items() if name}
                continue
            yield {name: cells.get(col, "") for col, name in header.items()}
            count += 1
            if limit and count >= limit:
                return


def download(url, destination):
    """Fetch a DOL disclosure file. Shared by the PERM and LCA loaders.

    The request asks for ``Range: bytes=0-`` -- the whole file. Not an
    optimisation and not a way around anything: DOL's CDN began answering a
    plain GET for these paths with 403 while answering a range request with 206
    and the complete body, which it advertises by returning Content-Range. The
    FY2024 PERM file downloaded fine to a plain GET and then 403'd on the same
    URL hours later, so this is behaviour that changes over time rather than a
    property of a path -- which is exactly why the release registry records the
    URL that worked and the hash of what came back.

    The magic-byte check exists because a 200 carrying an HTML error page would
    otherwise be stored as an .xlsx and fail later, in the parser, as something
    that looks like a schema change.
    """
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(
        url, headers={"User-Agent": UA, "Range": "bytes=0-"})
    with urllib.request.urlopen(request, timeout=1800) as response:
        status = response.status
        payload = response.read()
    if not payload:
        raise IOError(f"{url} returned {status} with an empty body")
    if not payload.startswith(b"PK"):
        raise IOError(f"{url} returned {status} but the body is not an xlsx "
                      f"(starts {payload[:8]!r}); refusing to store it as one")
    destination.write_bytes(payload)
    return destination, status


# Excel stores dates as days since 1899-12-30. A cell read straight out of the
# XML is therefore "45454", and a dashboard showing "latest sponsorship: 45454"
# is broken in a way that looks like data rather than a bug.
_EXCEL_EPOCH = date(1899, 12, 30)


def _excel_date(value):
    """Return an ISO date for a DOL date cell, whatever form it arrived in."""
    raw = str(value or "").strip()
    if not raw:
        return None
    # Already a date string.
    match = re.match(r"^(\d{4})-(\d{2})-(\d{2})", raw)
    if match:
        return match.group(0)
    try:
        serial = float(raw)
    except ValueError:
        return raw[:32]
    # Excel's leap-year bug means serials below 61 are ambiguous; none of these
    # files carry a 1900 decision date, so anything that small is not a date.
    if serial < 61 or serial > 80000:
        return None
    return (_EXCEL_EPOCH + timedelta(days=int(serial))).isoformat()


def _number(value):
    try:
        return float(str(value).replace(",", "").replace("$", "").strip())
    except (TypeError, ValueError):
        return None


# --------------------------------------------------------------------------
# Column contract
# --------------------------------------------------------------------------
# DOL renamed 150 of 155 columns for FY2025 -- EMPLOYER_NAME became
# EMP_BUSINESS_NAME -- and the loader, reading by literal name, wrote 2,458
# faculty cases with an empty employer and one distinct employer for the whole
# year. Nothing failed; the rows just meant nothing.
#
# So the field names a loader reads are a contract with the release, and a
# release that does not satisfy it is an error rather than a quiet run of
# empty strings.
#
# Each canonical field lists the names seen in a real file, newest first.
PERM_COLUMNS = {
    "case_number":       ("CASE_NUMBER",),
    "case_status":       ("CASE_STATUS",),
    "decision_date":     ("DECISION_DATE",),
    "employer_name":     ("EMP_BUSINESS_NAME", "EMPLOYER_NAME"),
    "employer_state":    ("EMP_STATE", "EMPLOYER_STATE_PROVINCE"),
    "job_title":         ("JOB_TITLE",),
    "soc_code":          ("PWD_SOC_CODE", "PW_SOC_CODE"),
    "soc_title":         ("PWD_SOC_TITLE", "PW_SOC_TITLE"),
    "wage":              ("JOB_OPP_WAGE_FROM", "PW_WAGE"),
    "wage_unit":         ("JOB_OPP_WAGE_PER", "PW_UNIT_OF_PAY"),
    # Present through FY2024 and absent from FY2025. Their loss is a change in
    # what the public file discloses, not a parsing failure, so they are
    # optional -- but the load reports which ones the release did not carry,
    # because a column that silently becomes NULL looks like missing data
    # rather than a withdrawn disclosure.
    "college_teacher_flag": ("APP_FOR_COLLEGE_U_TEACHER",),
    "competitive_process":  ("COMPETITIVE_PROCESS",),
    "citizenship":          ("COUNTRY_OF_CITIZENSHIP",),
    "class_of_admission":   ("CLASS_OF_ADMISSION",),
    "phd_institution":      ("FOREIGN_WORKER_INST_OF_ED",),
    "phd_major":            ("FOREIGN_WORKER_INFO_MAJOR",),
}

# Without these a row cannot be identified or attributed, so a release missing
# any of them is refused rather than loaded.
PERM_REQUIRED = ("case_number", "case_status", "employer_name", "job_title",
                 "soc_code", "soc_title")


class PermSchemaChanged(RuntimeError):
    """A release does not carry the columns the loader reads."""


def resolve_columns(header):
    """Map canonical field -> the column name this release actually uses.

    Returns ``(resolved, missing)``. A field absent from the header is left out
    of ``resolved`` rather than mapped to a name that is not there.
    """
    present = set(header)
    resolved, missing = {}, []
    for field, candidates in PERM_COLUMNS.items():
        for candidate in candidates:
            if candidate in present:
                resolved[field] = candidate
                break
        else:
            missing.append(field)
    return resolved, missing


def check_contract(header, fiscal_year=None):
    """Refuse a release that cannot supply the fields a row is built from."""
    resolved, missing = resolve_columns(header)
    unmet = [field for field in PERM_REQUIRED if field not in resolved]
    if unmet:
        raise PermSchemaChanged(
            f"PERM release{f' FY{fiscal_year}' if fiscal_year else ''} does not "
            f"carry required column(s) {unmet}. The file has {len(header)} "
            f"columns; DOL renames these between years (EMPLOYER_NAME became "
            f"EMP_BUSINESS_NAME in FY2025). Add the new name to PERM_COLUMNS "
            f"rather than loading rows that would be blank.")
    return resolved, missing


def field(row, resolved, name):
    """Read a canonical field through the resolved column map."""
    column = resolved.get(name)
    return row.get(column) if column else None


def load_year(conn, fiscal_year, *, download_root=None, row_limit=None, echo=None):
    """Load one PERM release, keeping the faculty cases."""
    url = PERM_RELEASES.get(fiscal_year)
    if not url:
        raise KeyError(
            f"no verified PERM release recorded for FY{fiscal_year}. DOL moves "
            "these files between paths; add the discovered URL to PERM_RELEASES.")
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT) / "dol"
    key = f"PERM_FY{fiscal_year}"
    event = start_event(conn, DATASET_PERM, key)
    try:
        path, status = download(url, root / f"{key}.xlsx")
        release_id = register_release(
            conn, DATASET_PERM, key, url, data_year=fiscal_year, local_path=path,
            http_status=status, note="faculty cases only; full file is ~500k rows")
        read = written = 0
        resolved = None
        withdrawn_columns = []
        for row in stream_rows(path, limit=row_limit):
            if resolved is None:
                # The first row carries the header this release actually uses.
                resolved, withdrawn_columns = check_contract(
                    list(row.keys()), fiscal_year)
                if withdrawn_columns and echo:
                    echo(f"  FY{fiscal_year} does not carry: "
                         f"{', '.join(withdrawn_columns)}")
            read += 1
            is_faculty, evidence = classify_faculty(row, resolved)
            if not is_faculty:
                continue
            case = (field(row, resolved, "case_number") or "").strip()
            if not case:
                continue
            fields = classify_business_fields(row)
            conn.execute("""
                INSERT INTO perm_faculty_cases
                  (case_number, fiscal_year, decision_date, case_status, employer_name,
                   employer_state, job_title, soc_code, soc_title, college_teacher_flag,
                   competitive_process, wage, wage_unit, citizenship, class_of_admission,
                   phd_institution, phd_major, business_field, faculty_evidence,
                   institution_id, release_id)
                VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(case_number) DO UPDATE SET
                  case_status=excluded.case_status, decision_date=excluded.decision_date,
                  business_field=excluded.business_field,
                  faculty_evidence=excluded.faculty_evidence,
                  release_id=excluded.release_id
            """, (case, fiscal_year,
                  _excel_date(field(row, resolved, "decision_date")),
                  (field(row, resolved, "case_status") or "").strip() or None,
                  (field(row, resolved, "employer_name") or "").strip(),
                  (field(row, resolved, "employer_state") or "").strip() or None,
                  (field(row, resolved, "job_title") or "").strip() or None,
                  (field(row, resolved, "soc_code") or "").strip() or None,
                  (field(row, resolved, "soc_title") or "").strip() or None,
                  (field(row, resolved, "college_teacher_flag") or "").strip() or None,
                  (field(row, resolved, "competitive_process") or "").strip() or None,
                  _number(field(row, resolved, "wage")),
                  (field(row, resolved, "wage_unit") or "").strip() or None,
                  (field(row, resolved, "citizenship") or "").strip() or None,
                  (field(row, resolved, "class_of_admission") or "").strip() or None,
                  (field(row, resolved, "phd_institution") or "").strip() or None,
                  (field(row, resolved, "phd_major") or "").strip() or None,
                  ",".join(fields) or None, evidence, None, release_id))
            written += 1
        conn.commit()
        finish_event(conn, event, "ok", rows_read=read, rows_written=written,
                     rows_skipped=read - written,
                     detail={"row_limit": row_limit,
                             "columns_not_in_release": withdrawn_columns})
        if echo:
            echo(f"  PERM FY{fiscal_year}: {written} faculty cases of {read} rows")
        return {"fiscal_year": fiscal_year, "rows_read": read,
                "faculty_cases": written, "release_id": release_id,
                "columns_not_in_release": withdrawn_columns}
    except Exception as error:
        conn.rollback()
        finish_event(conn, event, "failed", error=error)
        conn.commit()
        raise


def institution_profile(conn, employer_like, years=5):
    """Sponsorship history for one employer.

    Reports what was filed. It says nothing about whether a given posting
    sponsors: that is a property of the job, and the posting's own words are
    the only evidence for it.
    """
    rows = conn.execute("""
        SELECT fiscal_year, case_status, business_field, faculty_evidence,
               phd_institution, citizenship, decision_date
        FROM perm_faculty_cases WHERE employer_name LIKE ?
    """, (employer_like,)).fetchall()
    if not rows:
        return {"employer": employer_like, "faculty_perm_cases": 0,
                "evidence": "no PERM faculty case found in the loaded releases",
                "caveat": "absence here is not evidence the employer does not sponsor"}
    certified = sum(1 for r in rows if (r["case_status"] or "").lower().startswith("certified"))
    denied = sum(1 for r in rows if (r["case_status"] or "").lower() == "denied")
    strong = sum(1 for r in rows if r["faculty_evidence"] == EVIDENCE_FORM_FLAG)
    origins = {}
    for row in rows:
        if row["phd_institution"]:
            origins[row["phd_institution"]] = origins.get(row["phd_institution"], 0) + 1
    return {
        "employer": employer_like,
        "faculty_perm_cases": len(rows),
        "certified": certified,
        "denied": denied,
        "college_teacher_flagged": strong,
        "latest_decision": max((r["decision_date"] or "") for r in rows) or None,
        "phd_origin_institutions": sorted(origins.items(), key=lambda kv: -kv[1])[:10],
        "claim": "historical institutional sponsorship evidence",
        "caveat": (
            "PERM covers labour certifications only. EB-1B outstanding-professor "
            "petitions require none and never appear here, so this is a floor on "
            "sponsorship activity. It is not a statement about any particular job."),
    }


def mobility_flows(conn, limit=25):
    """PhD institution -> hiring institution, as observed in PERM filings."""
    rows = conn.execute("""
        SELECT phd_institution, employer_name, COUNT(*) AS cases
        FROM perm_faculty_cases
        WHERE phd_institution IS NOT NULL AND phd_institution != ''
        GROUP BY 1,2 ORDER BY cases DESC LIMIT ?
    """, (limit,)).fetchall()
    return {
        "flows": [dict(row) for row in rows],
        "population": "PERM applicants only",
        "caveat": (
            "A biased administrative sample: only hires whose employer filed a "
            "labour certification. Domestic hires, EB-1B hires and anyone not "
            "needing sponsorship are absent."),
    }


__all__ = ["PERM_COLUMNS", "PERM_REQUIRED", "PermSchemaChanged",
    "check_contract", "field", "resolve_columns",
    "EVIDENCE_FORM_FLAG", "EVIDENCE_SOC", "EVIDENCE_TITLE", "PERM_RELEASES",
           "classify_business_fields", "classify_faculty", "download",
           "institution_profile", "load_year", "mobility_flows", "stream_rows"]
