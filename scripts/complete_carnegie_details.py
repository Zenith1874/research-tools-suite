"""Read remaining business-title detail links from the newest portal observations."""
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.carnegie_vacancy_scan import DEFAULT_SCAN_DB, scan_vacancies
from services.faculty_jobs_normalizer import classify_business_scope, classify_faculty_market_role


def main():
    conn = sqlite3.connect(Path(DEFAULT_SCAN_DB).resolve().as_uri() + "?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row
    portals = set()
    candidates = []
    try:
        for row in conn.execute("""SELECT r.*,o.portal_url FROM vacancy_records r JOIN vacancy_observations o ON o.id=r.observation_id
            WHERE o.id IN (SELECT MAX(id) FROM vacancy_observations GROUP BY portal_url)
            AND r.detail_status IN ('not_attempted','empty')"""):
            if classify_business_scope(title=row["title_raw"])["scope"] not in {"business_school", "business_discipline"}:
                continue
            if not classify_faculty_market_role(row["title_raw"]).get("eligible"):
                continue
            portals.add(row["portal_url"])
            candidates.append({"title": row["title_raw"], "url": row["official_url"], "portal": row["portal_url"]})
    finally:
        conn.close()
    print(json.dumps({"remaining_business_details": len(candidates), "portals": len(portals)}, ensure_ascii=False), flush=True)
    if not portals:
        return
    output = ROOT / "outputs/faculty_jobs_completion_20261002/carnegie-business-detail-pass.json"
    def progress(item):
        print(json.dumps({k:item[k] for k in ("index","total","status","jobs_found")}), flush=True)
    result = scan_vacancies(max_portals=1000, portal_urls=sorted(portals), max_detail_pages=20,
        timeout=15, delay=1.2, max_jobs=100, prioritize_business=True, progress=progress)
    with output.open("x", encoding="utf-8") as handle:
        json.dump({"input_candidates": candidates, "result": result}, handle, ensure_ascii=False, indent=2)
    print(json.dumps(result, ensure_ascii=False), flush=True)


if __name__ == "__main__":
    main()
