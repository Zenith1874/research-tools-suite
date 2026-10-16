# -*- coding: utf-8 -*-
"""NSF Survey of Earned Doctorates: the national research-doctorate benchmark.

SED is a census of every research doctorate awarded by a US institution, so it
is the authoritative answer to "how many business research doctorates were
produced" -- 1,510 in 2023, against IPEDS's 4,201 for the same nominal concept.
It also carries the whole supply-to-outcome funnel and the cohort lag that a
pipeline model needs: median 5.0 years from doctoral program start.

Three things it cannot do, and the loader is shaped so nobody can accidentally
ask it to:

* **No institution grain.** Every table is national. "How many did NMSU
  produce" is an IPEDS question.
* **Business splits two ways only** -- "Business administration and management"
  and "Business, other". There is no OB, Strategy or IS line.
* **No forward pipeline.** SED counts people who finished, not people enrolled.

And the number that must not be mislabelled. The funnel gives
1,510 -> 1,303 reporting -> 77.6% definite employment -> 77.6% academe ->
84.2% tenure track, which is roughly 660. That is a **realised outcome**, not a
candidate supply: it excludes everyone still seeking, everyone who took a
postdoc or industry job after competing, every foreign-trained candidate, and
every lateral move. The field is named ``realized_tt_outcomes_est`` for that
reason and the estimator refuses to produce anything called supply.

Asset paths differ between publication years -- the report publication carries
only its own in-text tables, while the 96 data tables live under a separate id
-- so releases are discovered from the downloads page and recorded, never
templated.
"""

import io
import re
import urllib.request
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

from services.academic_market_store import (
    DATASET_SED_TABLES, DEFAULT_DOWNLOAD_ROOT, finish_event, register_release,
    start_event,
)

NS = "{http://schemas.openxmlformats.org/spreadsheetml/2006/main}"
UA = ("research-tools-suite/academic-career (+local research workstation; "
      "annual public statistical file download)")

# Verified releases. A registry, not a template: nsf25300 is the report and
# holds four in-text tables; nsf24336 is the data-tables publication and holds
# 96. Guessing the second from the first is what made this look unavailable.
# Verified releases, discovered rather than templated. The publication id
# carries no usable pattern: the SED 2023 tables are nsf24336 and the 2024
# tables are nsf25349, and the numerically "obvious" nsf22336 is the Survey of
# Postdocs at FFRDCs -- a different survey that also ships data tables, and
# exactly the file a templated guess would have loaded as SED.
#
# To add a year: open https://ncses.nsf.gov/surveys/earned-doctorates/, follow
# the "Data Tables" link, confirm the page title reads "Survey of Earned
# Doctorates (SED) <year>", and record the excels zip it actually offers.
SED_RELEASES = {
    2023: {
        "publication_id": "nsf24336",
        "tables_zip": ("https://ncses.nsf.gov/pubs/nsf24336/assets/data-tables/"
                       "nsf24336-data-tables-tables-excels.zip"),
        "note": "Data tables for the SED 2023 cycle.",
    },
    2024: {
        "publication_id": "nsf25349",
        "tables_zip": ("https://ncses.nsf.gov/pubs/nsf25349/assets/data-tables/"
                       "nsf25349-data-tables-tables-excels.zip"),
        "note": "Data tables for the SED 2024 cycle; page title verified as "
                "'Survey of Earned Doctorates (SED) 2024'.",
    },
}

# The two business tables, by the number printed in the index.
BUSINESS_PROFILE_TABLE = "8-16"
BUSINESS_OUTCOMES_TABLE = "9-16"

# A row that opens a subsection rather than carrying a value: "Male doctorate
# recipients", "Female doctorate recipients". Everything after one belongs to
# that group until the next opener.
#
# The phrase has to be complete. These tables also carry a "Sex (%)" breakdown
# whose rows are literally "Male" and "Female" -- those are values in the
# overall block, and treating them as openers moves the national citizenship
# and outcome figures into a per-sex section, where a lookup for the national
# figure then finds nothing.
_SECTION_RE = re.compile(
    r"^(male|female|men|women)\b[^,]{0,24}\bdoctorate\s+recipients\b", re.I)


def _shared_strings(archive):
    try:
        raw = archive.read("xl/sharedStrings.xml")
    except KeyError:
        return []
    return ["".join(t.text or "" for t in si.iter(NS + "t"))
            for si in ET.fromstring(raw).iter(NS + "si")]


def read_sheet(workbook_bytes, limit=400):
    """Rows of an xlsx as lists of strings, with the standard library only.

    openpyxl is installed, but an xlsx is a zip of XML and this needs one
    sheet's cells; going through the stdlib keeps the loader working in any
    environment the rest of the project runs in.
    """
    archive = zipfile.ZipFile(io.BytesIO(workbook_bytes))
    strings = _shared_strings(archive)
    sheets = sorted(n for n in archive.namelist()
                    if n.startswith("xl/worksheets/sheet"))
    if not sheets:
        raise ValueError("workbook contains no worksheet")
    rows = []
    for row in ET.fromstring(archive.read(sheets[0])).iter(NS + "row"):
        cells = []
        for cell in row.iter(NS + "c"):
            value = cell.find(NS + "v")
            text = value.text if value is not None else None
            if cell.get("t") == "s" and text is not None:
                try:
                    text = strings[int(text)]
                except (ValueError, IndexError):
                    pass
            elif cell.get("t") == "inlineStr":
                text = "".join(t.text or "" for t in cell.iter(NS + "t"))
            cells.append((text or "").strip())
        while cells and not cells[-1]:
            cells.pop()
        if cells:
            rows.append(cells)
        if len(rows) >= limit:
            break
    return rows


def _numeric(text):
    """A cell's number and what kind it is.

    SED marks suppressed cells ``D`` and rounds percentages; a suppressed cell
    is not zero and storing it as zero would understate a share and overstate
    everything computed against it.
    """
    raw = (text or "").strip()
    if not raw:
        return None, "missing"
    if raw.upper() in {"D", "S", "NA", "N/A", "-", "—"}:
        return None, "suppressed"
    cleaned = raw.replace(",", "").replace("%", "").strip()
    try:
        value = float(cleaned)
    except ValueError:
        return None, "text"
    kind = "percent" if "%" in raw or (0 <= value <= 100 and "." in cleaned) else "count"
    return value, kind


def download_tables(url, destination):
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


def _table_member(archive, table_number):
    """Find a table's workbook inside the archive by its printed number."""
    flat = table_number.replace("-", "")
    major, minor = table_number.split("-")
    patterns = (
        f"tab{int(major):03d}-{int(minor):03d}",
        f"tab{flat}",
    )
    for name in archive.namelist():
        lowered = name.lower()
        if lowered.endswith(".xlsx") and any(p in lowered for p in patterns):
            return name
    return None


def load_year(conn, year, *, download_root=None, tables=(BUSINESS_PROFILE_TABLE,
                                                         BUSINESS_OUTCOMES_TABLE),
              echo=None):
    """Load the business tables for one SED cycle."""
    release = SED_RELEASES.get(year)
    if not release:
        raise KeyError(
            f"no verified SED release recorded for {year}. Asset paths differ "
            "between publication years; add the discovered URL to SED_RELEASES "
            "rather than templating one.")
    root = Path(download_root or DEFAULT_DOWNLOAD_ROOT) / "sed"
    key = f"{release['publication_id']}-tables"
    event = start_event(conn, DATASET_SED_TABLES, key)
    try:
        path, status = download_tables(release["tables_zip"], root / f"{key}.zip")
        release_id = register_release(
            conn, DATASET_SED_TABLES, key, release["tables_zip"],
            publication_id=release["publication_id"], data_year=year,
            local_path=path, http_status=status, note=release.get("note"))
        archive = zipfile.ZipFile(path)
        written = read = 0
        missing = []
        for table_number in tables:
            member = _table_member(archive, table_number)
            if not member:
                missing.append(table_number)
                continue
            rows = read_sheet(archive.read(member))
            title = rows[0][0] if rows else table_number
            # The header row is the one whose first cell names the row
            # dimension; everything above it is title and units.
            header_index = next(
                (i for i, row in enumerate(rows[:8])
                 if row and row[0].lower().startswith("characteristic")), 3)
            columns = rows[header_index][1:]
            # SED repeats row labels inside per-sex subsections. A header row
            # like "Male doctorate recipients" opens a new section; without
            # tracking it, the last block's values overwrite the national ones.
            section = "all"
            for row in rows[header_index + 1:]:
                read += 1
                characteristic = row[0] if row else ""
                if not characteristic:
                    continue
                opener = _SECTION_RE.match(characteristic)
                if opener:
                    section = opener.group(1).strip().casefold()
                for offset, column in enumerate(columns, start=1):
                    if offset >= len(row):
                        continue
                    value, kind = _numeric(row[offset])
                    if kind in {"text", "missing"}:
                        continue
                    conn.execute("""
                        INSERT INTO sed_observations
                          (data_year, table_number, table_title, section, characteristic,
                           column_label, value, value_kind, release_id)
                        VALUES (?,?,?,?,?,?,?,?,?)
                        ON CONFLICT(data_year, table_number, section, characteristic,
                                    column_label)
                        DO UPDATE SET value=excluded.value, value_kind=excluded.value_kind,
                                      release_id=excluded.release_id
                    """, (year, table_number, title, section, characteristic, column,
                          value, kind, release_id))
                    written += 1
        conn.commit()
        if missing:
            # Not a silent zero: a table we expected and did not find is an
            # event with a reason attached.
            finish_event(conn, event, "partial", rows_read=read, rows_written=written,
                         error=f"tables not found in archive: {missing}",
                         detail={"missing": missing})
        else:
            finish_event(conn, event, "ok", rows_read=read, rows_written=written)
        conn.commit()
        if echo:
            echo(f"  SED {year}: {written} observations from tables {list(tables)}")
        return {"year": year, "rows_written": written, "missing_tables": missing,
                "release_id": release_id}
    except Exception as error:
        conn.rollback()
        finish_event(conn, event, "failed", error=error)
        conn.commit()
        raise


def _value(conn, year, table, characteristic_like, column="All business fields",
           section="all"):
    """One national figure. Section defaults to the overall block, never a sex."""
    row = conn.execute("""
        SELECT value FROM sed_observations
        WHERE data_year=? AND table_number=? AND column_label=? AND section=?
          AND characteristic LIKE ?
        ORDER BY LENGTH(characteristic) LIMIT 1
    """, (year, table, column, section, characteristic_like)).fetchone()
    return row["value"] if row else None


def business_benchmark(conn, year):
    """The national business figures, each named for what it actually is."""
    total = _value(conn, year, BUSINESS_PROFILE_TABLE, "All doctorate recipients%")
    visa = _value(conn, year, BUSINESS_PROFILE_TABLE, "Temporary visa holder%")
    reporting = _value(conn, year, BUSINESS_OUTCOMES_TABLE,
                       "Doctorate recipients reporting%")
    definite = _value(conn, year, BUSINESS_OUTCOMES_TABLE, "Definite employment plans%")
    seeking = _value(conn, year, BUSINESS_OUTCOMES_TABLE, "Seeking employment%")
    academe = _value(conn, year, BUSINESS_OUTCOMES_TABLE, "Academe%")
    tenure_track = _value(conn, year, BUSINESS_OUTCOMES_TABLE, "In tenure track%")

    realized = None
    if None not in (reporting, definite, academe, tenure_track):
        realized = round(reporting * definite / 100 * academe / 100 * tenure_track / 100)

    return {
        "data_year": year,
        "business_research_doctorates": total,
        "temporary_visa_share": visa,
        "reporting_postgraduation_plans": reporting,
        "definite_employment_share": definite,
        "seeking_share": seeking,
        "academe_share_of_employed": academe,
        "tenure_track_share_of_academe": tenure_track,
        # Named for what it is. Everyone still seeking competed too; so did
        # the postdocs, many who took industry jobs, every foreign-trained
        # candidate, and every lateral move. None of them are in this number.
        "realized_tt_outcomes_est": realized,
        "not_a_candidate_supply": (
            "realized_tt_outcomes_est counts people who ended up in a tenure-track "
            "post, not people who competed for one. It excludes those still seeking, "
            "those who took postdocs or industry roles after competing, all "
            "foreign-trained candidates, and all lateral moves. It must never be "
            "presented as candidate supply or as an applicant pool."),
        "grain": "national; business splits only into administration/management and other",
    }


__all__ = ["BUSINESS_OUTCOMES_TABLE", "BUSINESS_PROFILE_TABLE", "SED_RELEASES",
           "business_benchmark", "download_tables", "load_year", "read_sheet"]
