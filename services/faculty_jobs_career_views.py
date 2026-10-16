"""Explicit Carnegie import and exact institution links; never fuzzy-match campuses."""
from collections import Counter
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path

from services.institution_matching import normalize_institution

PUBLIC_FILE = Path(__file__).resolve().parents[1] / "data/academic_market/releases/carnegie/2025-Public-Data-File.xlsx"
SOURCE_URL = "https://carnegieclassifications.acenet.edu/wp-content/uploads/2025/04/2025-Public-Data-File.xlsx"
SYSTEM = "Carnegie 2025"
CAREER_VIEWS = ("all", "r2_teaching", "r1", "r2", "teaching", "unclassified")
PROXY_RULE = "Baccalaureate or Undergraduate/Graduate-Master's; excludes Associate/Baccalaureate; institutional proxy, not a job requirement"


def now_utc():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def ensure_career_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS carnegie_institution_catalog (
        unitid INTEGER PRIMARY KEY, data_year INTEGER NOT NULL,
        official_name TEXT NOT NULL, name_key TEXT NOT NULL,
        research_level TEXT NOT NULL, research_designation TEXT NOT NULL,
        institutional_classification TEXT NOT NULL, teaching_proxy INTEGER NOT NULL,
        state TEXT, city TEXT, source_url TEXT NOT NULL,
        source_sha256 TEXT NOT NULL, loaded_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_career_profile_name ON carnegie_institution_catalog(name_key)")
    conn.execute("""CREATE TABLE IF NOT EXISTS institution_career_links (
        institution_id INTEGER PRIMARY KEY REFERENCES institutions(id),
        unitid INTEGER NOT NULL REFERENCES carnegie_institution_catalog(unitid),
        method TEXT NOT NULL, name_evidence TEXT NOT NULL, linked_at TEXT NOT NULL)""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_career_link_unitid ON institution_career_links(unitid)")


def read_public_profiles(path=PUBLIC_FILE):
    """Read the preserved full 2025 workbook, validating schema and identity."""
    import openpyxl
    from services.faculty_jobs_normalizer import STATE_PROVINCE_ALIASES
    path = Path(path)
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    book = openpyxl.load_workbook(path, read_only=True, data_only=True)
    profiles = []
    try:
        rows = book["data"].values
        headers = [str(value or "").strip() for value in next(rows)]
        required = {"unitid", "instnm", "stabbr", "research2025name", "ic2025name"}
        if not required.issubset(headers):
            raise ValueError("Unexpected Carnegie public-file schema")
        for values in rows:
            row = dict(zip(headers, values))
            if row.get("unitid") is None:
                continue
            unitid = int(row["unitid"])
            name = str(row.get("instnm") or "").strip()
            designation = str(row.get("research2025name") or "").strip()
            classification = str(row.get("ic2025name") or "").strip()
            level = {
                "Research 1: Very High Spending and Doctorate Production": "R1",
                "Research 2: High Spending and Doctorate Production": "R2",
                "Research Colleges and Universities": "RCU",
                "No research designation": "Other",
            }.get(designation)
            if not name or level is None:
                raise ValueError(f"Unexpected designation for UNITID {unitid}")
            teaching = "Associate/Baccalaureate" not in classification and (
                "Baccalaureate" in classification or "Undergraduate/Graduate-Master's" in classification)
            state = str(row.get("stabbr") or "").strip()
            profiles.append(dict(
                unitid=unitid, data_year=2025, official_name=name,
                name_key=normalize_institution(name), research_level=level,
                research_designation=designation, institutional_classification=classification,
                teaching_proxy=int(teaching), state=STATE_PROVINCE_ALIASES.get(state, state),
                city=row.get("city"), source_url=SOURCE_URL, source_sha256=digest))
    finally:
        book.close()
    if not profiles or len({p["unitid"] for p in profiles}) != len(profiles):
        raise ValueError("Empty catalogue or duplicate UNITIDs; import stopped")
    return profiles


def import_profiles(conn, profiles):
    """Idempotent frozen-release import, never replacement of another release."""
    existing = {row[0] for row in conn.execute("SELECT DISTINCT source_sha256 FROM carnegie_institution_catalog")}
    incoming = {row["source_sha256"] for row in profiles}
    if len(incoming) != 1 or (existing and existing != incoming):
        raise ValueError("Catalogue release changed; requires a versioned migration")
    fields = tuple(profiles[0])
    stamp = now_utc()
    conn.executemany(
        f"INSERT OR IGNORE INTO carnegie_institution_catalog ({','.join(fields)},loaded_at) "
        f"VALUES ({','.join('?' for _ in fields)},?)",
        [tuple(row[field] for field in fields) + (stamp,) for row in profiles])
    return dict(Counter(p["research_level"] for p in profiles))


def link_institution(conn, institution_id):
    # Historical migrations can create institutions before migration 86.
    if not conn.execute("SELECT 1 FROM sqlite_master WHERE name='carnegie_institution_catalog'").fetchone():
        return "catalogue_unavailable"
    row = conn.execute("SELECT * FROM institutions WHERE id=?", (institution_id,)).fetchone()
    if not row or not row["is_current"] or row["country_code"] not in (None, "", "US"):
        return "ineligible"
    from services.faculty_jobs_normalizer import country_code_for
    if not row["country_code"] and row["country"] and str(row["country"]).lower() not in {"unknown", "global"} and country_code_for(row["country"]) != "US":
        return "ineligible"
    if not row["country_code"] and row["region_group"] in {"Europe", "Canada", "Asia", "Oceania", "Africa", "Latin America"}:
        return "ineligible"
    if conn.execute("SELECT 1 FROM institution_career_links WHERE institution_id=?", (institution_id,)).fetchone():
        return "already_linked"
    if row["university_research_level"] not in (None, "", "Unknown", "unknown") and row["university_research_level_system"] != SYSTEM:
        return "existing_classification_preserved"
    try:
        aliases = json.loads(row["aliases_json"] or "[]")
    except (TypeError, ValueError):
        aliases = []
    if not isinstance(aliases, list):
        aliases = []
    from services.faculty_jobs_normalizer import STATE_PROVINCE_ALIASES
    state = row["state_province"] or ""
    state = STATE_PROVINCE_ALIASES.get(state, state).upper()
    candidates = {}
    for name in [row["official_name"], *aliases]:
        if not isinstance(name, str):
            continue
        for profile in conn.execute("SELECT * FROM carnegie_institution_catalog WHERE name_key=?", (normalize_institution(name),)):
            if state and profile["state"] and state != profile["state"].upper():
                continue
            candidates.setdefault(profile["unitid"], (profile, name))
    if len(candidates) != 1:
        return "ambiguous" if candidates else "unmatched"
    profile, evidence = next(iter(candidates.values()))
    method = "exact_normalized_name" if normalize_institution(evidence) == normalize_institution(row["official_name"]) else "exact_retained_alias"
    stamp = now_utc()
    conn.execute("INSERT INTO institution_career_links VALUES (?,?,?,?,?)",
                 (institution_id, profile["unitid"], method, evidence, stamp))
    conn.execute("UPDATE institutions SET university_research_level=?,university_research_level_system=?,updated_at=? WHERE id=?",
                 (profile["research_level"], SYSTEM, stamp, institution_id))
    conn.execute("""INSERT INTO faculty_job_repair_audit
        (observed_at,action,old_value,new_value,reason) VALUES (?,?,?,?,?)""",
        (stamp, "carnegie_2025_institution_link",
         json.dumps({"institution_id": institution_id, "level": row["university_research_level"], "system": row["university_research_level_system"]}),
         json.dumps({"unitid": profile["unitid"], "level": profile["research_level"], "source_sha256": profile["source_sha256"]}),
         f"{method}: {evidence}; {profile['source_url']}"))
    return "linked"


def career_view_sql(value, alias="cp"):
    value = str(value or "all").strip().lower()
    if value not in CAREER_VIEWS:
        raise ValueError("career_view must be all, r2_teaching, r1, r2, teaching, or unclassified")
    level, proxy = f"{alias}.research_level", f"{alias}.teaching_proxy"
    return {
        "all": "1=1", "r1": f"{level}='R1'", "r2": f"{level}='R2'",
        "teaching": f"{proxy}=1 AND {level}<>'R1'",
        "r2_teaching": f"({level}='R2' OR {proxy}=1) AND {level}<>'R1'",
        "unclassified": f"{alias}.unitid IS NULL",
    }[value]
