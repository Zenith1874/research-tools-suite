"""Transparent public action queues, independent of private candidate scoring."""
from datetime import date, timedelta

PREFERRED_QUERY = {
    "scope": "business_school", "country": "US", "career_view": "r2_teaching",
    "discipline": "Information Systems / MIS,Management,Organizational Behavior / HR",
}
POSITION_TYPES = ("tt", "teaching", "clinical", "adjunct", "other")
ACTION_VIEWS = ("all", "new", "worth_review", "review_soon", "needs_verification")
ACTION_RULES = {
    "new": "本地首次发现不超过 7 天；不是原站发布日期。",
    "worth_review": "符合当前筛选，排除 Adjunct、博士后及明显标题学科冲突；不是个人匹配分或录用概率。",
    "review_soon": "原文明示的首轮/优先审查在未来 30 天内，或固定截止在未来 14 天内；两种日期分开显示。",
    "needs_verification": "官方五项信息未齐、读取受阻、超过 14 天未核验，或标题与目标学科可能不符；缺信息不代表不符合条件。",
}


def pool_sql(alias="j"):
    title = f"LOWER(COALESCE({alias}.title_raw,''))"
    body = f"LOWER(COALESCE({alias}.description_excerpt,''))"
    official = "COALESCE((rq.status='ok' AND rq.identity_verified=1 AND rq.source_kind='official_posting' AND json_extract(rq.fields_json,'$.posting_kind.status')='supported' AND json_extract(rq.fields_json,'$.posting_kind.value')='pool'),0)"
    return "(" + " OR ".join([official] + [f"{title} LIKE '%{term}%'" for term in
        ("pool", "continuous recruitment", "future openings", "ongoing recruitment")]
        + [f"{body} LIKE '%{term}%'" for term in
           ("applicant pool", "candidate pool", "adjunct pool", "future vacancies", "as needs arise", "generating an applicant pool")]) + ")"


def posting_kind_filter(value):
    if value in (None, "", "all"):
        return "1=1"
    if value == "pool":
        return pool_sql()
    if value == "advertisement":
        return "NOT " + pool_sql()
    raise ValueError("posting_kind must be all, pool, or advertisement")


def position_sql(alias="j"):
    title = f"LOWER(COALESCE({alias}.title_raw,''))"
    known = {
        "tt": f"{alias}.track_type IN ('tenure_track','tenured')",
        "teaching": "(" + " OR ".join(f"{title} LIKE '%{term}%'" for term in ("lecturer", "instructor", "teaching", "professor of practice", "professor-of-practice")) + ")",
        "clinical": f"{title} LIKE '%clinical%'",
        "adjunct": f"(COALESCE({alias}.appointment_type,'')='adjunct' OR {title} LIKE '%adjunct%')",
    }
    known["other"] = "NOT (" + " OR ".join(f"COALESCE(({v}),0)" for v in known.values()) + ")"
    return known


def position_filter(value):
    values = list(dict.fromkeys(x.strip().lower() for x in str(value or "").split(",") if x.strip()))
    if any(x not in POSITION_TYPES for x in values):
        raise ValueError("position_type must contain tt, teaching, clinical, adjunct, or other")
    predicates = position_sql()
    return " OR ".join(f"({predicates[x]})" for x in values) or "1=1"


def title_conflict_sql(alias="j"):
    # These are prompts to inspect a questionable normalized discipline, not
    # automatic stored reclassifications or institution-level judgments.
    title = f"REPLACE(REPLACE(LOWER(COALESCE({alias}.title_raw,'')),'college of business and economics','college of business'),'college of business & economics','college of business')"
    off_topic = " OR ".join(f"{title} LIKE '%{term}%'" for term in ("economics", "marketing", "business law", "real estate", "public law", "cannabis"))
    role_title = f"(CASE WHEN INSTR({title},' - department')>0 THEN SUBSTR({title},1,INSTR({title},' - department')-1) ELSE {title} END)"
    target = " OR ".join(f"{role_title} LIKE '%{term}%'" for term in ("information systems", "organizational behav", "human resource"))
    return f"({alias}.discipline_primary IN ('Information Systems / MIS','Management','Organizational Behavior / HR') AND ({off_topic}) AND NOT ({target}))"


def hard_deadline_sql():
    return """(CASE WHEN json_extract(rq.fields_json,'$.hard_deadline.status')='supported'
        THEN json_extract(rq.fields_json,'$.hard_deadline.normalized_date')
        WHEN rq.status='ok' AND rq.identity_verified=1 AND rq.source_kind='official_posting' THEN NULL
        WHEN j.deadline_mode='fixed' THEN j.deadline_date ELSE NULL END)"""


def action_sql(value, today=None):
    value = str(value or "all").lower()
    if value not in ACTION_VIEWS:
        raise ValueError("action_view must be all, new, worth_review, review_soon, or needs_verification")
    day = today or date.today()
    iso = day.isoformat()
    seven = (day - timedelta(days=7)).isoformat()
    stale = (day - timedelta(days=14)).isoformat()
    fourteen = (day + timedelta(days=14)).isoformat()
    thirty = (day + timedelta(days=30)).isoformat()
    conflict = title_conflict_sql()
    return {
        "all": "1=1",
        "new": f"(CASE WHEN LENGTH(j.first_seen_at)>10 THEN DATE(j.first_seen_at,'localtime') ELSE SUBSTR(j.first_seen_at,1,10) END) BETWEEN '{seven}' AND '{iso}'",
        "worth_review": f"NOT ({position_sql()['adjunct']}) AND COALESCE(j.career_stage,'')<>'postdoc' AND LOWER(COALESCE(j.title_raw,'')) NOT LIKE '%postdoc%' AND NOT ({conflict})",
        "review_soon": f"((rq.review_date BETWEEN '{iso}' AND '{thirty}') OR ({hard_deadline_sql()} BETWEEN '{iso}' AND '{fourteen}'))",
        "needs_verification": f"""(rq.id IS NULL OR rq.status<>'ok' OR rq.identity_verified<>1
            OR rq.source_kind<>'official_posting' OR rq.supported_count<5
            OR DATE(COALESCE(rq.captured_at,j.last_seen_at,''),'localtime')<'{stale}'
            OR COALESCE((SELECT lr.status FROM job_requirement_reads lr WHERE lr.job_id=j.id
                ORDER BY lr.captured_at DESC,lr.id DESC LIMIT 1),'not_read')<>'ok'
            OR ({conflict}))""",
    }[value]


def select_columns():
    return ",\n".join(
        [f"COALESCE(({sql}),0) AS position_{name}" for name, sql in position_sql().items()]
        + [f"COALESCE(({action_sql(name)}),0) AS action_{name}" for name in ACTION_VIEWS[1:]]
        + [f"COALESCE(({title_conflict_sql()}),0) AS discipline_needs_verification",
           f"COALESCE(({pool_sql()}),0) AS posting_pool"])


def decorate_job(value):
    value["position_types"] = [name for name in POSITION_TYPES if value.pop("position_" + name, 0)]
    value["position_type_basis"] = "TT from explicit contract mapping; Teaching/Clinical/Adjunct from this job title or appointment. Labels may overlap; never inferred from school type."
    value["actions"] = [name for name in ACTION_VIEWS[1:] if value.pop("action_" + name, 0)]
    value["action_rules"] = {name: ACTION_RULES[name] for name in value["actions"]}
    return value
