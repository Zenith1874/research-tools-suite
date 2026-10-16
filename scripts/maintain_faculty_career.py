"""Rehearse or execute guarded discipline and employer-evidence maintenance."""
import argparse
import json
from pathlib import Path
import sqlite3
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from services.faculty_jobs_maintenance import apply_discipline_repairs, discipline_repair_plan, refresh_requirements
from services.faculty_jobs_write_guard import guarded_write, open_read_only, postflight, preflight


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", default=str(ROOT / "data/faculty_jobs.db"))
    parser.add_argument("--rehearsal-from")
    parser.add_argument("--repair-disciplines", action="store_true")
    parser.add_argument("--refresh-requirements", action="store_true")
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--max-jobs", type=int, default=24)
    parser.add_argument("--max-pages", type=int, default=48)
    parser.add_argument("--output", type=Path)
    parser.add_argument("--override-path", type=Path)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    if args.report.exists():
        raise ValueError("Use a new report path")
    if args.rehearsal_from:
        if Path(args.db).exists():
            raise ValueError("Use a new rehearsal database path")
        src = open_read_only(args.rehearsal_from)
        dst = sqlite3.connect(args.db)
        src.backup(dst); dst.close(); src.close()
    plan = discipline_repair_plan(args.db) if args.repair_disciplines else None
    result = {"plan": plan}
    if args.apply:
        inventory = preflight(args.db, "faculty_career_maintenance")
        with guarded_write():
            if plan:
                result["repairs"] = apply_discipline_repairs(args.db, plan)
            if args.refresh_requirements:
                kwargs = {"override_path": args.override_path} if args.override_path else {}
                result["requirements"] = refresh_requirements(args.db, max_jobs=args.max_jobs,
                    max_pages=args.max_pages, force=args.force, output=args.output, **kwargs)
        result["postflight"] = postflight(args.db, inventory)
    args.report.parent.mkdir(parents=True, exist_ok=True)
    with args.report.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, ensure_ascii=False, indent=2)
    print(json.dumps({k: v for k, v in result.items() if k != "plan"}, ensure_ascii=False))
    if plan:
        print(json.dumps({"planned_repairs": len(plan["changes"]), "ids": [c["job_id"] for c in plan["changes"]]}))


if __name__ == "__main__":
    main()
