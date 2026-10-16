# -*- coding: utf-8 -*-
"""IPEDS Completions and institutional characteristics.

What this answers: how many doctorates each US institution awarded, in which
CIP, at which level, each year.

What it does **not** answer, and the distinction is the whole point: how many
business PhDs entered the academic job market. ``AWLEVEL=17`` is IPEDS's
"Doctor's degree - research/scholarship", which institutions self-report and
which includes online DBAs and practitioner doctorates alongside research PhDs.
In 2022-23 the largest CIP-52 producers under that code were Walden (291),
Liberty (223), Northcentral (176) and Capella (148); the national total was
4,201 while NSF's SED -- a census of research doctorate recipients -- counted
1,510. Restricting to Carnegie R1 gives 1,460, within 3% of SED.

So the loader keeps two named concepts and never collapses them:

  ``broad_doctoral_production``      every AWLEVEL 17 award in the CIP
  ``research_academic_proxy``        the R1 subset, a proxy and labelled as one

Neither is a candidate pool. R1 is not "the real doctorates" and the rest are
not fake -- they are a different population, mostly not entering research
faculty search.

One implementation note that cost an hour: the CSV is UTF-8 **with BOM**.
Decoding as plain UTF-8 leaves the first column named ``﻿UNITID``, so
``row["UNITID"]`` raises KeyError while every other column works, and a naive
loader silently produces zero rows.
"""

import csv
import io
import re
import urllib.request
import zipfile
from pathlib import Path

from services.academic_market_store import (
    DATASET_IPEDS_COMPLETIONS, DATASET_IPEDS_HD, DEFAULT_DOWNLOAD_ROOT,
    finish_event, register_release, start_event,
)

BASE_URL = "https://nces.ed.gov/ipeds/datacenter/data"
UA = ("research-tools-suite/academic-career (+local research workstation; "
      "annual public statistical file download)")

# Doctor's degree - research/scholarship. 18 is professional practice and 19
# is "other"; folding those in would put JDs and MDs in a business PhD count.
AWLEVEL_RESEARCH_DOCTORATE = 17

# Carnegie 2021 basic classification codes, from IPEDS HD's C21BASIC.
CARNEGIE_R1 = 15
CARNEGIE_R2 = 16
CARNEGIE_DOCTORAL_PROFESSIONAL = 17

BUSINESS_CIP_SERIES = "52"

# CIP -> field. Confidence is per row because it genuinely varies: 52.1003 is
# Organizational Behavior by name, while 52.0201 is a general bucket that in
# 2023 held 47% of all business research doctorates and maps to no narrow
# field at all. Anything that claims to break OB out of 52.0201 is inventing.
CIP_CROSSWALK = (
    ("52.0101", "Business/Commerce, General", "General Business", None, "verified",
     "General bucket; no narrow field is recoverable."),
    ("52.0201", "Business Administration and Management, General", "General Business",
     None, "verified",
     "Holds 47% of CIP-52 research doctorates. Contains Management, OB, HR and "
     "Strategy indistinguishably. Must never be attributed to a narrow field."),
    ("52.0213", "Organizational Leadership", "Management", None, "observed",
     "Second largest bucket (26%). Heavily used by online and practitioner "
     "doctorates; not a research-OB proxy."),
    ("52.0206", "Non-Profit/Public/Organizational Management", "Management", None,
     "observed", None),
    ("52.0299", "Business Administration, Management and Operations, Other",
     "Management", None, "observed", None),
    ("52.1001", "Human Resources Management/Personnel Administration, General",
     "Management", "Human Resources", "verified", None),
    ("52.1002", "Labor and Industrial Relations", "Management", "Human Resources",
     "observed", None),
    ("52.1003", "Organizational Behavior Studies", "Management",
     "Organizational Behavior", "verified",
     "The only CIP that names OB. 178 doctorates in 2022-23 -- an order of "
     "magnitude below the real OB market, because most sit in 52.0201."),
    ("52.1005", "Human Resources Development", "Management", "Human Resources",
     "observed", None),
    ("52.0701", "Entrepreneurship/Entrepreneurial Studies", "Management",
     "Entrepreneurship", "verified", None),
    ("52.0801", "Finance, General", "Finance", None, "verified", None),
    ("52.0804", "Financial Planning and Services", "Finance", None, "observed", None),
    ("52.0899", "Finance and Financial Management Services, Other", "Finance", None,
     "observed", None),
    ("52.0301", "Accounting", "Accounting", None, "verified", None),
    ("52.0399", "Accounting and Related Services, Other", "Accounting", None,
     "observed", None),
    ("52.1401", "Marketing/Marketing Management, General", "Marketing", None,
     "verified", None),
    ("52.1499", "Marketing, Other", "Marketing", None, "observed", None),
    ("52.1201", "Management Information Systems, General", "Information Systems",
     None, "verified", None),
    ("52.1206", "Information Resources Management", "Information Systems", None,
     "observed", None),
    ("52.1299", "Management Information Systems and Services, Other",
     "Information Systems", None, "observed", None),
    ("52.0203", "Logistics, Materials, and Supply Chain Management",
     "Operations and Supply Chain", "Supply Chain", "verified", None),
    ("52.0205", "Operations Management and Supervision",
     "Operations and Supply Chain", "Operations", "verified", None),
    ("52.1301", "Management Science", "Management Science", None, "verified", None),
    ("52.1302", "Business Statistics", "Business Analytics", None, "verified", None),
    ("52.1304", "Actuarial Science", "Business Analytics", None, "observed", None),
    ("52.1399", "Management Sciences and Quantitative Methods, Other",
     "Management Science", None, "observed", None),
    ("52.0501", "Business/Corporate Communications", "Other Business", None,
     "observed", None),
    ("52.0901", "Hospitality Administration/Management, General", "Other Business",
     None, "observed", None),
    ("52.1101", "International Business/Trade/Commerce", "Other Business", None,
     "observed", None),
)


def load_crosswalk(conn):
    """Install the CIP crosswalk. Idempotent."""
    for row in CIP_CROSSWALK:
        conn.execute("""
            INSERT INTO business_cip_crosswalk
              (cip_code, cip_title, broad_field, narrow_field, confidence, notes)
            VALUES (?,?,?,?,?,?)
            ON CONFLICT(cip_code) DO UPDATE SET
              cip_title=excluded.cip_title, broad_field=excluded.broad_field,
              narrow_field=excluded.narrow_field, confidence=excluded.confidence,
              notes=excluded.notes
        """, row)
    conn.commit()
    return len(CIP_CROSSWALK)


def completions_url(year):
    return f"{BASE_URL}/C{year}_A.zip"


def hd_url(year):
    return f"{BASE_URL}/HD{year}.zip"


def download(url, destination):
    """Fetch a file. Raises on anything but a body -- never returns empty."""
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(request, timeout=300) as response:
        status = response.status
        payload = response.read()
    if not payload:
        raise IOError(f"{url} returned {status} with an empty body")
    destination.write_bytes(payload)
    return destination, status


def _read_csv(zip_path, prefer_revised=False):
    """Yield dict rows from the CSV inside an IPEDS zip.

    Decoded as ``utf-8-sig``. The files carry a byte-order mark, and decoding
    as plain UTF-8 renames the first column to ``﻿UNITID`` -- every other
    column reads fine, so the failure looks like missing data rather than an
    encoding problem.
    """
    archive = zipfile.ZipFile(zip_path)
    names = [n for n in archive.namelist() if n.lower().endswith(".csv")]
    if not names:
        raise ValueError(f"{zip_path} contains no CSV")
    revised = [n for n in names if n.lower().endswith("_rv.csv")]
    plain = [n for n in names if not n.lower().endswith("_rv.csv")]
    chosen = (revised or plain)[0] if prefer_revised else (plain or revised)[0]
    text = archive.read(chosen).decode("utf-8-sig", errors="replace")
    return chosen, csv.DictReader(io.StringIO(text))


def _as_int(value):
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def load_completions(conn, year, *, download_root=None, cip_prefix=BUSINESS_CIP_SERIES,
                     awlevels=(AWLEVEL_RESEARCH_DOCTORATE,), echo=None):
    """Load one Completions year, filtered to the CIP series we analyse.

    Filtering at load rather than at query keeps the file to thousands of rows
    instead of 300,000 a year. The filter is recorded on the event so a later
    reader knows the table is a slice, not the whole release.
    """
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT) / "ipeds"
    url = completions_url(year)
    key = f"C{year}_A"
    event = start_event(conn, DATASET_IPEDS_COMPLETIONS, key)
    try:
        path, status = download(url, root / f"{key}.zip")
        release_id = register_release(
            conn, DATASET_IPEDS_COMPLETIONS, key, url, data_year=year,
            local_path=path, http_status=status,
            note=f"filtered to CIP {cip_prefix}.* and AWLEVEL {sorted(awlevels)}")
        member, reader = _read_csv(path)
        read = written = skipped = 0
        for row in reader:
            read += 1
            cip = (row.get("CIPCODE") or "").strip()
            awlevel = _as_int(row.get("AWLEVEL"))
            if awlevel not in awlevels or not cip.startswith(cip_prefix + "."):
                skipped += 1
                continue
            unitid = _as_int(row.get("UNITID"))
            if unitid is None:
                # The BOM failure mode. Loud, because silently skipping every
                # row is exactly what it looks like when it happens.
                raise ValueError(
                    f"{member}: UNITID missing; columns are {list(row)[:3]}. "
                    "The file is UTF-8 with a BOM and must be decoded utf-8-sig.")
            conn.execute("""
                INSERT INTO ipeds_completions
                  (data_year, unitid, cipcode, majornum, awlevel, total, men, women,
                   nonresident, release_id)
                VALUES (?,?,?,?,?,?,?,?,?,?)
                ON CONFLICT(data_year, unitid, cipcode, majornum, awlevel)
                DO UPDATE SET total=excluded.total, men=excluded.men,
                              women=excluded.women, nonresident=excluded.nonresident,
                              release_id=excluded.release_id
            """, (year, unitid, cip, _as_int(row.get("MAJORNUM")) or 1, awlevel,
                  _as_int(row.get("CTOTALT")) or 0, _as_int(row.get("CTOTALM")),
                  _as_int(row.get("CTOTALW")), _as_int(row.get("CNRALT")), release_id))
            written += 1
        conn.commit()
        finish_event(conn, event, "ok", rows_read=read, rows_written=written,
                     rows_skipped=skipped,
                     detail={"member": member, "cip_prefix": cip_prefix})
        if echo:
            echo(f"  IPEDS completions {year}: {written} rows kept of {read}")
        return {"year": year, "rows_read": read, "rows_written": written,
                "rows_skipped": skipped, "release_id": release_id}
    except Exception as error:
        conn.rollback()
        finish_event(conn, event, "failed", error=error)
        conn.commit()
        raise


def load_institutions(conn, year, *, download_root=None, echo=None):
    """Load one HD year: names, control, state, and the Carnegie class.

    Carnegie comes free here. The separate licensed Carnegie file carries a
    NonCommercial term; ``C21BASIC`` in HD is the same 2021 basic
    classification and is public, so the R1/R2 split needs no licence.
    """
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT) / "ipeds"
    url = hd_url(year)
    key = f"HD{year}"
    event = start_event(conn, DATASET_IPEDS_HD, key)
    try:
        path, status = download(url, root / f"{key}.zip")
        release_id = register_release(conn, DATASET_IPEDS_HD, key, url, data_year=year,
                                      local_path=path, http_status=status)
        member, reader = _read_csv(path)
        read = written = 0
        for row in reader:
            read += 1
            unitid = _as_int(row.get("UNITID"))
            if unitid is None:
                raise ValueError(f"{member}: UNITID missing; decode as utf-8-sig")
            conn.execute("""
                INSERT INTO ipeds_institutions
                  (data_year, unitid, institution_name, state, control,
                   carnegie_basic, website, release_id)
                VALUES (?,?,?,?,?,?,?,?)
                ON CONFLICT(data_year, unitid) DO UPDATE SET
                  institution_name=excluded.institution_name, state=excluded.state,
                  control=excluded.control, carnegie_basic=excluded.carnegie_basic,
                  website=excluded.website, release_id=excluded.release_id
            """, (year, unitid, (row.get("INSTNM") or "").strip(),
                  (row.get("STABBR") or "").strip() or None, _as_int(row.get("CONTROL")),
                  _as_int(row.get("C21BASIC")), (row.get("WEBADDR") or "").strip() or None,
                  release_id))
            written += 1
        conn.commit()
        finish_event(conn, event, "ok", rows_read=read, rows_written=written,
                     detail={"member": member})
        if echo:
            echo(f"  IPEDS institutions {year}: {written} rows")
        return {"year": year, "rows_read": read, "rows_written": written,
                "release_id": release_id}
    except Exception as error:
        conn.rollback()
        finish_event(conn, event, "failed", error=error)
        conn.commit()
        raise


def doctoral_production(conn, year, *, carnegie=None, broad_field=None):
    """Doctorates awarded in the business CIP series for a year.

    ``carnegie`` restricts to a Carnegie class -- pass ``(CARNEGIE_R1,)`` for
    the research-oriented proxy. The unrestricted figure is
    ``broad_doctoral_production``; the restricted one is a proxy and the
    return value names it as such rather than letting a caller present either
    as a candidate count.
    """
    where = ["c.data_year = ?", "c.majornum = 1"]
    args = [year]
    if carnegie:
        placeholders = ",".join("?" for _ in carnegie)
        where.append(f"i.carnegie_basic IN ({placeholders})")
        args.extend(carnegie)
    if broad_field:
        where.append("x.broad_field = ?")
        args.append(broad_field)
    rows = conn.execute(f"""
        SELECT COALESCE(x.broad_field,'Unmapped business CIP') AS broad_field,
               SUM(c.total) AS doctorates,
               SUM(COALESCE(c.nonresident,0)) AS nonresident,
               COUNT(DISTINCT c.unitid) AS institutions
        FROM ipeds_completions c
        LEFT JOIN ipeds_institutions i
          ON i.unitid = c.unitid AND i.data_year = c.data_year
        LEFT JOIN business_cip_crosswalk x ON x.cip_code = c.cipcode
        WHERE {' AND '.join(where)}
        GROUP BY 1 ORDER BY doctorates DESC
    """, args).fetchall()
    total = sum(row["doctorates"] or 0 for row in rows)
    return {
        "data_year": year,
        "measure": ("research_academic_proxy" if carnegie else "broad_doctoral_production"),
        "carnegie_filter": list(carnegie) if carnegie else None,
        "total_doctorates": total,
        "by_broad_field": [dict(row) for row in rows],
        "caveat": (
            "IPEDS AWLEVEL 17 is the institution's own report of a research/"
            "scholarship doctorate and includes practitioner and online doctorates. "
            "This is doctoral production, not a job-market candidate pool. Narrow "
            "fields are not recoverable: 52.0201 alone held 47% of 2022-23 business "
            "research doctorates and contains Management, OB, HR and Strategy "
            "indistinguishably."),
    }


__all__ = [
    "AWLEVEL_RESEARCH_DOCTORATE", "BUSINESS_CIP_SERIES", "CARNEGIE_DOCTORAL_PROFESSIONAL",
    "CARNEGIE_R1", "CARNEGIE_R2", "CIP_CROSSWALK", "completions_url",
    "doctoral_production", "download", "hd_url", "load_completions",
    "load_crosswalk", "load_institutions",
]
