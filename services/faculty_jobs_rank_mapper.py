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
    # Multi-level advertisements must be recognized before any one component.
    # Otherwise word order makes the same open-rank search look Assistant,
    # Associate, or Full Professor at random.
    explicit_open_rank = re.search(r"\b(?:open[- ]rank|any rank|all ranks)\b", text)
    multi_professor_rank = (
        re.search(
            r"\bassistant(?:\s+professors?)?\s*(?:/|,|\bor\b|\band\b)\s*"
            r"(?:associate|full)\s+professors?\b",
            text,
        )
        or re.search(
            r"\bassociate(?:\s+professors?)?\s*(?:/|,|\bor\b|\band\b)\s*"
            r"(?:assistant|full)\s+professors?\b",
            text,
        )
        or re.search(
            r"\bassistant\s*[,/]\s*associate\s*(?:[,/]|\bor\b|\band\b)\s*"
            r"full(?:\s+professors?)?\b",
            text,
        )
        or re.search(r"\bassistant/associate/full\b", text)
    )
    if explicit_open_rank or multi_professor_rank:
        return RankMapping("Open Rank", UNKNOWN, 0.88,
                           "Explicit open-rank or multiple professor-level alternatives; career stage is not singular.")
    if re.search(r"\blecturers?\b.{0,12}\bsenior lecturers?\b|"
                 r"\bsenior lecturers?\b.{0,12}\blecturers?\b", text):
        return RankMapping("Lecturer / Senior Lecturer", UNKNOWN, 0.86,
                           "Multiple local lecturer levels are advertised; original ranks retained.")
    if re.search(r"\b(senior lecturer|reader)\b", text):
        return RankMapping("Senior Lecturer / Reader", MID, 0.82,
                           "Original lecturer/reader rank retained; approximate mid-career market-stage mapping.")
    if re.search(r"\blecturers?\b", text):
        # Lecturer is a local rank everywhere, not merely in the UK/Ireland.
        # Rewriting it as Assistant Professor asserted an equivalence the
        # mapping explicitly promises not to make.
        return RankMapping("Lecturer", EARLY, 0.80,
                           "Lecturer wording retained; approximate early-career market-stage mapping.")
    if re.search(
        r"\b(?:assistant professor(?:s|ship)?|professeur adjoint|professeure adjointe)\b|"
        r"\bassistant(?:\s+[a-z][a-z&/-]*){1,3}\s+professors?\b",
        text,
    ):
        return RankMapping("Assistant Professor", EARLY, 0.92,
                           "Explicit assistant-professor or equivalent wording.")
    if re.search(r"\b(associate professor|associate professorship|professeur agr[eé]g[eé]|professeure agr[eé]g[eé]e)\b", text):
        return RankMapping("Associate Professor", MID, 0.92,
                           "Explicit associate-professor or equivalent wording.")
    if re.search(r"\b(full professor|professor|professe[u]?r titulaire|professeure titulaire)\b", text):
        return RankMapping("Professor", SENIOR, 0.90,
                           "Explicit professor wording without a lower-rank qualifier.")

    return RankMapping("Unknown", UNKNOWN, 0.0,
                       "No sufficiently explicit faculty rank or career-stage signal.")


__all__ = [
    "EARLY", "MID", "SENIOR", "TEACHING", "PRACTICE", "POSTDOC", "VISITING", "UNKNOWN",
    "RankMapping", "map_rank",
]
