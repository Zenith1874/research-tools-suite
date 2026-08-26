# -*- coding: utf-8 -*-
"""Conservative cross-country faculty rank and career-stage mapping.

The raw title is always retained by the caller.  The mapping in this module is
only a market-stage aid; it deliberately does not translate a European rank
into an American tenure rank.
"""

from dataclasses import dataclass
import re


EARLY = "early_career_faculty"
MID = "mid_career_faculty"
SENIOR = "senior_faculty"
TEACHING = "teaching_faculty"
PRACTICE = "practice_faculty"
POSTDOC = "postdoc"
VISITING = "visiting"
UNKNOWN = "unknown"


@dataclass(frozen=True)
class RankMapping:
    rank_normalized: str
    career_stage: str
    confidence: float
    explanation: str


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def map_rank(country_code, title):
    """Return a transparent mapping without asserting rank equivalence."""
    raw = _clean(title)
    text = raw.casefold()
    country = str(country_code or "").upper()

    if re.search(r"\b(postdoc|post-doctoral|postdoctoral|research fellow)\b", text):
        return RankMapping("Postdoc / Research Fellow", POSTDOC, 0.96,
                           "Explicit postdoctoral or research-fellow wording.")
    if re.search(r"\b(visiting|visiteur|visiting scholar)\b", text):
        return RankMapping("Visiting", VISITING, 0.96,
                           "Explicit visiting appointment wording.")
    if re.search(r"\b(professor of practice|professor-practitioner|practice professor)\b", text):
        return RankMapping("Professor of Practice", PRACTICE, 0.98,
                           "Explicit practice-faculty wording.")
    if re.search(r"\b(clinical professor|clinical faculty)\b", text):
        return RankMapping("Clinical Faculty", PRACTICE, 0.92,
                           "Explicit clinical-faculty wording.")
    if re.search(r"\b(teaching professor|teaching faculty|teaching stream|educator track|instructor)\b", text):
        return RankMapping("Teaching Faculty", TEACHING, 0.90,
                           "Explicit teaching-stream or instructor wording.")

    # German career ranks remain visibly German.  They are not rewritten as
    # Assistant/Associate/Full Professor.
    if re.search(r"\b(w1|juniorprofessor|junior professor)\b", text):
        return RankMapping("W1 / Juniorprofessor", EARLY, 0.90,
                           "German W1 or Juniorprofessor; early-career market-stage mapping.")
    if re.search(r"\b(w2)\b", text):
        return RankMapping("W2", MID, 0.88,
                           "German W2; mid-career market-stage mapping.")
    if re.search(r"\b(w3)\b", text):
        return RankMapping("W3", SENIOR, 0.88,
                           "German W3; senior-faculty market-stage mapping.")

    if re.search(r"ma[iî]tre[s]? de conf[eé]rences|ma[iî]tre de conférences", text):
        return RankMapping("Maître de conférences", EARLY, 0.78,
                           "French original rank retained; approximate early-career market-stage mapping.")
    if re.search(r"\b(senior lecturer|reader)\b", text):
        return RankMapping("Senior Lecturer / Reader", MID, 0.82,
                           "Original lecturer/reader rank retained; approximate mid-career market-stage mapping.")
    if re.search(r"\b(lecturer|assistant professor|assistant professorship|professeur adjoint|professeure adjointe)\b", text):
        # In the UK and Ireland, Lecturer is not an American Assistant
        # Professor.  The normalized value intentionally remains local.
        if "lecturer" in text and country in {"GB", "IE"}:
            return RankMapping("Lecturer", EARLY, 0.76,
                               "UK/Irish Lecturer retained; approximate early-career market-stage mapping.")
        return RankMapping("Assistant Professor", EARLY, 0.92,
                           "Explicit assistant-professor or equivalent wording.")
    if re.search(r"\b(associate professor|associate professorship|professeur agr[eé]g[eé]|professeure agr[eé]g[eé]e)\b", text):
        return RankMapping("Associate Professor", MID, 0.92,
                           "Explicit associate-professor or equivalent wording.")
    if re.search(r"\b(full professor|professor|professe[u]?r titulaire|professeure titulaire)\b", text):
        return RankMapping("Professor", SENIOR, 0.90,
                           "Explicit professor wording without a lower-rank qualifier.")

    if re.search(r"\b(open rank|any rank|all ranks|assistant/associate/full)\b", text):
        return RankMapping("Open Rank", UNKNOWN, 0.84,
                           "Open-rank wording; career stage cannot be determined from the title alone.")

    return RankMapping("Unknown", UNKNOWN, 0.0,
                       "No sufficiently explicit faculty rank or career-stage signal.")


__all__ = [
    "EARLY", "MID", "SENIOR", "TEACHING", "PRACTICE", "POSTDOC", "VISITING", "UNKNOWN",
    "RankMapping", "map_rank",
]
