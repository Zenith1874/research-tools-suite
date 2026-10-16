#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Seed the PhD programme panel with a 20-school pilot.

Deliberately hand-written rather than crawled. The audit probed twelve
programmes and five hand-guessed URLs 404'd -- there is no pattern to
template, so the registry holds addresses a person confirmed. The panel is
mixed by tier on purpose: an elite-only panel would describe a market that
most candidates do not compete in.

URLs here are programme landing pages, which are stable. Roster, job-market
and placement URLs are left NULL until someone confirms each one; a guessed
URL that 404s is worse than an empty column, because a snapshot run would
record "checked, nothing found" for a page that exists somewhere else.

This writes to the faculty database, so it runs inside the write guard.

    python scripts/seed_phd_panel.py --status
    python scripts/seed_phd_panel.py --apply
"""

import argparse
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services import phd_pipeline
from services.faculty_jobs_service import FACULTY_DB_PATH
from services.faculty_jobs_write_guard import guarded_write, postflight, preflight

# (institution, programme, field, programme URL, Carnegie 2021 basic)
# Carnegie codes: 15 = R1, 16 = R2, 17 = doctoral/professional.
PILOT_PANEL = [
    ("University of Pennsylvania", "Wharton Management PhD", "Management",
     "https://mgmt.wharton.upenn.edu/programs/doctoral/", 15),
    ("Massachusetts Institute of Technology", "Sloan PhD", "Management",
     "https://mitsloan.mit.edu/phd", 15),
    ("Stanford University", "GSB PhD", "Management",
     "https://www.gsb.stanford.edu/programs/phd", 15),
    ("University of Michigan-Ann Arbor", "Ross PhD", "Management",
     "https://michiganross.umich.edu/programs/phd", 15),
    ("University of Texas at Austin", "McCombs PhD", "Management",
     "https://www.mccombs.utexas.edu/phd/", 15),
    ("Indiana University-Bloomington", "Kelley Doctoral", "Management",
     "https://kelley.iu.edu/programs/phd/index.html", 15),
    ("University of Maryland-College Park", "Smith PhD", "Management",
     "https://www.rhsmith.umd.edu/programs/phd", 15),
    ("Arizona State University", "W. P. Carey PhD", "Management",
     "https://wpcarey.asu.edu/phd", 15),
    ("University of Georgia", "Terry PhD", "Management",
     "https://www.terry.uga.edu/academics/phd/", 15),
    ("Ohio State University", "Fisher PhD", "Management",
     "https://fisher.osu.edu/graduate/phd", 15),
    ("Pennsylvania State University", "Smeal PhD", "Management",
     "https://www.smeal.psu.edu/phd", 15),
    ("Michigan State University", "Broad PhD", "Supply Chain",
     "https://broad.msu.edu/academics/phd/", 15),
    ("University of Florida", "Warrington PhD", "Management",
     "https://warrington.ufl.edu/phd/", 15),
    ("Florida State University", "Business Doctoral", "Management",
     "https://business.fsu.edu/doctoral-programs", 15),
    ("University of Nebraska-Lincoln", "Business PhD", "Management",
     "https://business.unl.edu/academic-programs/graduate/phd/", 15),
    ("Oklahoma State University", "Spears PhD", "Management",
     "https://business.okstate.edu/phd/", 15),
    ("University of Texas at San Antonio", "Carlos Alvarez PhD", "Management",
     "https://business.utsa.edu/phd/", 15),
    ("Kent State University", "Business Administration PhD", "Management",
     "https://www.kent.edu/business/phd", 16),
    ("New Mexico State University", "Business Administration PhD", "Management",
     "https://business.nmsu.edu/academics/graduate/phd/", 16),
    ("University of Texas at El Paso", "Business PhD", "Management",
     "https://www.utep.edu/business/phd/", 16),
]


def summarise(conn):
    rows = conn.execute("""
        SELECT carnegie_basic, COUNT(*) AS n FROM phd_program_sources
        WHERE status='active' GROUP BY carnegie_basic ORDER BY carnegie_basic
    """).fetchall()
    labels = {15: "R1", 16: "R2", 17: "doctoral/professional"}
    print(f"  programmes registered: "
          f"{conn.execute('SELECT COUNT(*) FROM phd_program_sources').fetchone()[0]}")
    for row in rows:
        print(f"    {labels.get(row['carnegie_basic'], 'unclassified'):<22} {row['n']}")
    confirmed = conn.execute("""
        SELECT SUM(jmc_url IS NOT NULL) AS jmc, SUM(placement_url IS NOT NULL) AS placement,
               SUM(roster_url IS NOT NULL) AS roster FROM phd_program_sources
    """).fetchone()
    print(f"    confirmed JMC URLs      {confirmed['jmc'] or 0}")
    print(f"    confirmed placement     {confirmed['placement'] or 0}")
    print(f"    confirmed roster        {confirmed['roster'] or 0}")
    print("    (left NULL until a person confirms each address: a guessed URL "
          "that 404s records 'checked, nothing there' for a page that exists)")


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true",
                        help="write the panel (guarded, backed up first)")
    parser.add_argument("--status", action="store_true", help="read-only summary")
    parser.add_argument("--db", default=str(FACULTY_DB_PATH))
    args = parser.parse_args(argv)

    if args.status or not args.apply:
        conn = sqlite3.connect(f"file:{Path(args.db).as_posix()}?mode=ro", uri=True)
        conn.row_factory = sqlite3.Row
        try:
            print("PhD panel status (read-only)")
            summarise(conn)
        except sqlite3.DatabaseError as error:
            print(f"  panel tables not present yet: {error}")
        finally:
            conn.close()
        if not args.apply:
            print(f"\n{len(PILOT_PANEL)} pilot programmes ready. Re-run with --apply "
                  "to write them.")
            return 0

    inventory = preflight(args.db, "phd_panel_seed")
    conn = sqlite3.connect(args.db, timeout=60)
    conn.row_factory = sqlite3.Row
    try:
        with guarded_write():
            phd_pipeline.ensure_tables(conn)
            for institution, program, field, url, carnegie in PILOT_PANEL:
                phd_pipeline.register_program(
                    conn, institution, program, field=field, program_url=url,
                    carnegie_basic=carnegie, source_type="manual_pilot",
                    notes="Pilot panel; roster/JMC/placement URLs pending confirmation.")
            conn.commit()
        print(f"\nwrote {len(PILOT_PANEL)} programmes")
        summarise(conn)
    finally:
        conn.close()
    postflight(args.db, inventory)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
