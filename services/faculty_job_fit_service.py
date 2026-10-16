# -*- coding: utf-8 -*-
"""Private, deterministic and explainable faculty-job fit scoring."""

from datetime import datetime
import json
import os
import re
import tempfile
from pathlib import Path

from services.faculty_jobs_normalizer import country_code_for


ROOT = Path(__file__).resolve().parents[1]
PROFILE_PATH = ROOT / "data" / "faculty_job_profile.json"
PROFILE_VERSION = 3
DEFAULT_WEIGHTS = {
    "field_match": 30,
    "research_topic_match": 20,
    "teaching_match": 15,
    "career_stage_match": 10,
    "school_fit": 10,
    "contract_fit": 5,
    "geography": 5,
    "visa_evidence": 5,
}
DEFAULT_PROFILE = {
    "version": PROFILE_VERSION,
    "target_disciplines": [],
    "research_keywords": [],
    "teaching_areas": [],
    "desired_career_stages": ["early_career_faculty"],
    "preferred_regions": ["United States", "Canada", "Europe"],
    "preferred_countries": [],
    "preferred_states_provinces": [],
    "research_intensity_preference": "balanced",
    "contract_preferences": ["tenure_track", "permanent_open_ended"],
    "weights": DEFAULT_WEIGHTS.copy(),
    "strong_match_threshold": 75,
    "possible_match_threshold": 50,
    "qualification_evidence": {
        "doctoral_status": "unknown", "expected_completion_date": "",
        "research_record": "", "teaching_record": "",
        "peer_reviewed_publications": None, "independent_courses_taught": None,
    },
}


def _clean_list(value):
    if isinstance(value, str):
        value = re.split(r"[,;\n]+", value)
    if not isinstance(value, list):
        return []
    out = []
    for item in value:
        text = re.sub(r"\s+", " ", str(item or "")).strip()
        if text and text.casefold() not in {x.casefold() for x in out}:
            out.append(text)
    return out[:100]


def default_profile():
    return json.loads(json.dumps(DEFAULT_PROFILE, ensure_ascii=False))


def load_profile(path=None):
    path = Path(path or PROFILE_PATH)
    if not path.exists():
        return default_profile()
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
        return validate_profile(value)
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return default_profile()


def validate_profile(value):
    if not isinstance(value, dict):
        raise ValueError("profile must be an object")
    profile = default_profile()
    for key in ("target_disciplines", "research_keywords", "teaching_areas",
                "desired_career_stages", "preferred_regions", "preferred_countries",
                "preferred_states_provinces",
                "contract_preferences"):
        profile[key] = _clean_list(value.get(key, profile[key]))
    intensity = str(value.get("research_intensity_preference", profile["research_intensity_preference"]))
    profile["research_intensity_preference"] = intensity if intensity in {"high", "balanced", "teaching"} else "balanced"
    weights = value.get("weights") if isinstance(value.get("weights"), dict) else {}
    for key, default in DEFAULT_WEIGHTS.items():
        try:
            number = float(weights.get(key, default))
        except (TypeError, ValueError):
            number = float(default)
        profile["weights"][key] = max(0.0, number)
    total = sum(profile["weights"].values())
    if total <= 0:
        profile["weights"] = DEFAULT_WEIGHTS.copy()
        total = 100
    # Weights are configuration, but the UI and score explanation operate on a
    # 100-point scale.  Normalize explicit custom weights transparently.
    profile["weights"] = {key: round(value * 100 / total, 4)
                           for key, value in profile["weights"].items()}
    for key, default in (("strong_match_threshold", 75), ("possible_match_threshold", 50)):
        try:
            profile[key] = max(0, min(100, int(value.get(key, default))))
        except (TypeError, ValueError):
            profile[key] = default
    profile["version"] = PROFILE_VERSION
    facts = value.get("qualification_evidence") or {}
    if not isinstance(facts, dict):
        raise ValueError("qualification_evidence must be an object")
    status = str(facts.get("doctoral_status") or "unknown")
    if status not in {"unknown", "doctoral_student", "abd", "completed"}:
        raise ValueError("Invalid doctoral_status")
    profile["qualification_evidence"]["doctoral_status"] = status
    expected = str(facts.get("expected_completion_date") or "").strip()
    if expected and not re.fullmatch(r"20\d{2}(?:-(?:0[1-9]|1[0-2])(?:-(?:0[1-9]|[12]\d|3[01]))?)?", expected):
        raise ValueError("Expected completion date must be YYYY, YYYY-MM or YYYY-MM-DD")
    if len(expected) == 10:
        try:
            datetime.fromisoformat(expected)
        except ValueError:
            raise ValueError("Invalid expected completion calendar date") from None
    profile["qualification_evidence"]["expected_completion_date"] = expected
    for key in ("research_record", "teaching_record"):
        profile["qualification_evidence"][key] = str(facts.get(key) or "").strip()[:4000]
    for key in ("peer_reviewed_publications", "independent_courses_taught"):
        count = facts.get(key)
        if count is None or count == "":
            profile["qualification_evidence"][key] = None
        else:
            try:
                count = int(count)
            except (TypeError, ValueError):
                raise ValueError(f"{key} must be a nonnegative integer or null") from None
            if count < 0:
                raise ValueError(f"{key} must be nonnegative")
            profile["qualification_evidence"][key] = count
    return profile


def save_profile(value, path=None):
    path = Path(path or PROFILE_PATH)
    profile = validate_profile(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, temporary = tempfile.mkstemp(prefix=path.name + ".", suffix=".tmp", dir=str(path.parent))
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(profile, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)
    return profile


def _tokens(values):
    if isinstance(values, str):
        values = [values]
    tokens = set()
    for value in values or []:
        tokens.update(re.findall(r"[a-z0-9][a-z0-9/+&-]{2,}", str(value).casefold()))
    return tokens


def _overlap_score(preferences, values):
    wanted = _tokens(preferences)
    available = _tokens(values)
    if not wanted:
        return 0.0, "No preference configured."
    hits = sorted(wanted & available)
    return min(1.0, len(hits) / max(1, min(len(wanted), 5))), (
        "Matched: " + ", ".join(hits[:8]) if hits else "No configured keyword matched."
    )


def score_job(job, profile=None):
    """Return a stable score payload; never return profile contents."""
    profile = validate_profile(profile or default_profile())
    weights = profile["weights"]
    breakdown = []

    primary = job.get("discipline_primary")
    secondary = job.get("discipline_secondary") or job.get("discipline_secondary_json") or []
    if isinstance(secondary, str):
        try:
            secondary = json.loads(secondary)
        except (TypeError, ValueError):
            secondary = [secondary]
    fields = [primary] + list(secondary or [])
    target_fields = {item.casefold() for item in profile["target_disciplines"]}
    field_hit = bool(target_fields and any(str(item or "").casefold() in target_fields for item in fields))
    field_fraction = 1.0 if field_hit else (0.0 if target_fields else 0.0)
    breakdown.append({"key": "field_match", "label": "Field", "earned": round(weights["field_match"] * field_fraction, 2), "maximum": weights["field_match"], "reason": "Primary or secondary discipline matched." if field_hit else "No target-discipline match."})

    research_values = [job.get("title_raw"), job.get("description_excerpt"), job.get("research_areas_json"), job.get("keywords_json")]
    research_fraction, research_reason = _overlap_score(profile["research_keywords"], research_values)
    breakdown.append({"key": "research_topic_match", "label": "Research", "earned": round(weights["research_topic_match"] * research_fraction, 2), "maximum": weights["research_topic_match"], "reason": research_reason})

    teaching_fraction, teaching_reason = _overlap_score(profile["teaching_areas"], [job.get("title_raw"), job.get("teaching_areas_json"), job.get("description_excerpt")])
    breakdown.append({"key": "teaching_match", "label": "Teaching", "earned": round(weights["teaching_match"] * teaching_fraction, 2), "maximum": weights["teaching_match"], "reason": teaching_reason})

    stages = {str(item).casefold() for item in profile["desired_career_stages"]}
    stage = str(job.get("career_stage") or "unknown").casefold()
    stage_fraction = 1.0 if stages and stage in stages else (0.0 if stages else 0.0)
    breakdown.append({"key": "career_stage_match", "label": "Rank / stage", "earned": round(weights["career_stage_match"] * stage_fraction, 2), "maximum": weights["career_stage_match"], "reason": "Career stage matched configured preference." if stage_fraction else "Career stage did not match or is unknown."})

    level = str(job.get("university_research_level") or "Unknown")
    tier = str(job.get("business_research_tier") or "Unclassified")
    intensity = profile["research_intensity_preference"]
    high = level in {"R1", "R2"} or tier in {"T1", "T2"}
    teaching = level in {"RCU", "Other"} or tier == "T4"
    school_fraction = 1.0 if ((intensity == "high" and high) or (intensity == "teaching" and teaching) or (intensity == "balanced" and (high or teaching))) else 0.0
    breakdown.append({"key": "school_fit", "label": "School", "earned": round(weights["school_fit"] * school_fraction, 2), "maximum": weights["school_fit"], "reason": f"Configured intensity={intensity}; evidence level={level}, tier={tier}."})

    contracts = {item.casefold() for item in profile["contract_preferences"]}
    contract = str(job.get("track_type") or "unknown").casefold()
    contract_fraction = 1.0 if contracts and contract in contracts else (0.0 if contracts else 0.0)
    breakdown.append({"key": "contract_fit", "label": "Contract", "earned": round(weights["contract_fit"] * contract_fraction, 2), "maximum": weights["contract_fit"], "reason": "Contract preference matched." if contract_fraction else "Contract preference did not match or is unknown."})

    regions = {item.casefold() for item in profile["preferred_regions"]}
    countries = {item.casefold() for item in profile["preferred_countries"]}
    country_codes = {str(country_code_for(item) or item).casefold() for item in profile["preferred_countries"]}
    states = {item.casefold() for item in profile["preferred_states_provinces"]}
    geo_region = str(job.get("region_group") or "Other").casefold()
    geo_country = str(job.get("country") or "Unknown").casefold()
    geo_code = str(job.get("country_code") or "").casefold()
    geo_state = str(job.get("state_province") or "").casefold()
    geo_fraction = 1.0 if ((regions and geo_region in regions) or (countries and geo_country in countries) or (country_codes and geo_code in country_codes) or (states and geo_state in states)) else 0.0
    breakdown.append({"key": "geography", "label": "Geography", "earned": round(weights["geography"] * geo_fraction, 2), "maximum": weights["geography"], "reason": "Preferred region/country matched." if geo_fraction else "No preferred geography match."})

    visa = str(job.get("visa_status") or "unknown")
    visa_fraction = {"sponsorship_explicit_yes": 1.0, "international_candidates_welcome": 0.6}.get(visa, 0.0)
    breakdown.append({"key": "visa_evidence", "label": "Visa evidence", "earned": round(weights["visa_evidence"] * visa_fraction, 2), "maximum": weights["visa_evidence"], "reason": "Explicit source evidence: " + visa if visa_fraction else "Visa evidence is unknown or not positive; no inference made."})

    score = round(sum(item["earned"] for item in breakdown), 2)
    if score >= profile["strong_match_threshold"]:
        label = "Strong Match"
    elif score >= profile["possible_match_threshold"]:
        label = "Possible Match"
    else:
        label = "Low Match"
    return {
        "score": score,
        "label": label,
        "breakdown": breakdown,
        "thresholds": {
            "strong_match": profile["strong_match_threshold"],
            "possible_match": profile["possible_match_threshold"],
        },
        "scoring_version": PROFILE_VERSION,
    }


__all__ = ["PROFILE_PATH", "DEFAULT_PROFILE", "default_profile", "load_profile", "save_profile", "validate_profile", "score_job"]
