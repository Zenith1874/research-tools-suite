"""Evidence-first R1/reference comparison with optional local candidate facts."""
from collections import Counter
from datetime import datetime, timezone
import re

from services.faculty_job_fit_service import default_profile, validate_profile
from services.faculty_jobs_actions import PREFERRED_QUERY
from services.faculty_jobs_requirements import REQUIRED_FIELDS


def compare_candidate(job, profile=None):
    """Return inspectable evidence pairs; no hiring score or inferred credentials."""
    facts = validate_profile(profile or default_profile())["qualification_evidence"]
    req = job.get("requirements") or {}
    fields = req.get("fields") or {}
    official = req.get("source_kind") == "official_posting" and req.get("status") == "ok" and req.get("identity_verified")
    rows = []
    for field, fact_key, label in (("phd_requirement", "doctoral_status", "博士要求"),
        ("research_requirements", "research_record", "研究成果要求"),
        ("teaching_experience", "teaching_record", "教学经历要求"),
        ("teaching_load", "teaching_record", "教学负担"),
        ("materials", None, "申请材料"), ("start_date", "expected_completion_date", "入职与毕业时间")):
        evidence = fields.get(field) or {}
        fact = facts.get(fact_key) if fact_key else None
        if field == "research_requirements" and not fact and facts.get("peer_reviewed_publications") is not None:
            fact = f"同行评议论文：{facts['peer_reviewed_publications']} 篇（本人记录）"
        if field in {"teaching_experience", "teaching_load"} and not fact and facts.get("independent_courses_taught") is not None:
            fact = f"独立授课：{facts['independent_courses_taught']} 门（本人记录）"
        state = "manual_comparison"
        explanation = "请逐项比较原文条件与本机记录；关键词命中不等于已满足要求。"
        if not official or evidence.get("status") != "supported":
            state, explanation = "source_needed", "缺少可核验的官方条件原文。"
        elif fact_key and fact in (None, "", "unknown"):
            state, explanation = "profile_needed", "补充实际经历或成果后可对照；偏好关键词不能替代资格事实。"
        elif field == "phd_requirement" and fact == "completed":
            state, explanation = "self_reported", "你记录为博士已完成；具体学科及授予时间仍按公告核对。"
        elif field == "research_requirements" and facts.get("peer_reviewed_publications") == 0:
            state, explanation = "preparation_needed", "你记录的同行评议论文为 0；请重点核对公告要求已有发表记录还是研究潜力。"
        elif field == "teaching_experience" and facts.get("independent_courses_taught") == 0:
            state, explanation = "preparation_needed", "你记录的独立授课为 0；请核对公告对授课经验和教学效果证据的要求。"
        elif field == "materials":
            explanation = "依据材料原文准备清单；上传和投递由你完成。"
        if official and field == "start_date" and evidence.get("status") == "supported" and facts.get("doctoral_status") not in {"unknown", "completed"}:
            starts = re.findall(r"\b20\d{2}\b", evidence.get("quote") or "")
            graduation = facts.get("expected_completion_date") or ""
            phd = fields.get("phd_requirement") or {}
            if starts and graduation and phd.get("status") == "supported" and int(graduation[:4]) > max(map(int, starts)):
                state = "timeline_gap"
                explanation = f"你预计 {graduation} 毕业，晚于公告入职年份；请核对该岗位的博士完成要求。可作为未来准备参照。"
        rows.append({"field": field, "label": label, "status": state,
            "official_quote": evidence.get("quote") if official else None,
            "source_url": req.get("source_url") if official else None,
            "verified_at": req.get("captured_at") if official else None,
            "candidate_record": fact, "explanation": explanation})
    configured = any(v not in (None, "", "unknown") for v in facts.values())
    return {"job_id": job["id"], "private": True, "profile_configured": configured,
        "rows": rows, "rule": "official_condition_vs_user_report_v1_20261002",
        "boundary": "Only user-entered qualification facts are used. No candidate attributes are inferred from school type, keyword preferences or other projects."}


def requirements_comparison(db):
    """Public aggregate comparison contains only employer evidence, no profile."""
    from services.faculty_jobs_service import build_faculty_jobs_payload
    groups = {}
    for view in ("r2_teaching", "r1"):
        jobs, offset = [], 0
        while True:
            payload = build_faculty_jobs_payload(db, {**PREFERRED_QUERY, "career_view": view, "limit": 200, "offset": offset})
            jobs.extend(payload["jobs"])
            if not payload["pagination"]["has_more"]:
                break
            offset += len(payload["jobs"])
        verified = [job for job in jobs if job.get("last_verified_at")]
        groups[view] = {"jobs": len(jobs), "official_readings": len(verified),
            "pool_records": sum(job.get("posting_kind") == "pool" for job in jobs),
            "supported_fields": dict(Counter(name for job in verified
                for name, f in job["requirements"]["fields"].items() if f.get("status") == "supported")),
            "examples": [{"job_id": job["id"], "title": job["title_raw"], "institution": job["institution_name"],
                "source_url": job["requirements"]["source_url"], "verified_at": job["last_verified_at"],
                "research_quote": job["requirements"]["fields"].get("research_requirements", {}).get("quote"),
                "teaching_quote": job["requirements"]["fields"].get("teaching_load", {}).get("quote")}
                for job in verified if "adjunct" not in job.get("position_types", [])][:6]}
    return {"ok": True, "as_of": datetime.now(timezone.utc).isoformat(), "groups": groups,
        "scope": PREFERRED_QUERY, "boundary": "Observed postings in the current cohort; missing fields do not establish lighter requirements. Schools without readable postings do not imply no vacancy."}
