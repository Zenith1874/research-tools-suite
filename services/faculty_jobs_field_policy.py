# -*- coding: utf-8 -*-
"""What happens to a job field when the same posting is observed again.

A job row is written once and then re-observed many times, sometimes by the
board that first carried it and sometimes by a different one that carries the
same posting. Those two cases must not be treated alike.

* The **same** board re-reading its own posting is authoritative about it. If
  the card no longer shows a deadline, the deadline is gone, and keeping the
  old one would show a closed competition as open.
* A **different** board carrying the same posting is an additional witness,
  not a replacement. Overwriting a deadline we already hold with another
  board's blank -- or with its vaguer copy -- loses evidence for nothing.

So the policy is per field *class*, and the class is applied differently
depending on which of those two situations produced the update.

``AUTHORITATIVE`` fields are recomputed deterministically from the observation
itself (rank, discipline, scope, location, the derived market verdict). They
follow the observing source, and a same-source observation may clear them.

``EVIDENCE`` fields are things a posting may or may not disclose (salary,
deadline, application URL, teaching load, visa wording). The current source
owns them; another source may only fill what is blank.

``LAST_SEEN`` advances monotonically: a job seen today and re-seen by an older
snapshot tomorrow was still seen today.

``IMMUTABLE`` fields describe the row's own history and are never rewritten by
an observation.
"""

AUTHORITATIVE = (
    "title_raw", "title_normalized", "original_title", "description_excerpt",
    "institution_id", "school_id", "school_evidence_context",
    "discipline_primary", "discipline_secondary_json", "classification_reason",
    "business_scope", "business_scope_confidence", "business_scope_reason",
    "faculty_market_role", "faculty_market_eligible", "faculty_market_reason",
    "keywords_json", "rank_raw", "rank_normalized", "career_stage",
    "rank_mapping_confidence", "rank_mapping_explanation",
    "track_type", "contract_type", "employment_type", "appointment_type",
    "country", "country_code", "region_group", "state_province", "city",
    "location_evidence", "remote_type",
    "posted_date", "deadline_date", "deadline_mode", "deadline_evidence",
    "deadline_parse_reason", "hiring_cycle", "hiring_cycle_reason",
    "status", "verification_note", "derived_quality", "fingerprint", "updated_at",
)

EVIDENCE = (
    "department", "salary_raw", "salary_min", "salary_max", "salary_currency",
    "salary_period", "phd_required", "phd_required_by",
    "teaching_areas_json", "research_areas_json", "teaching_load_raw",
    "visa_text", "visa_status", "language_requirements",
    "contract_length", "start_term", "start_year", "official_url",
)

LAST_SEEN = ("last_seen_at",)

IMMUTABLE = ("canonical_key", "first_seen_at", "created_at")

# Fields an authoritative observation may set back to empty. A source that has
# stopped publishing a deadline is telling us something, and a stale deadline
# is worse than none.
CLEARABLE = frozenset({
    "posted_date", "deadline_date", "deadline_mode", "deadline_evidence",
    "deadline_parse_reason", "location_evidence", "city", "state_province",
    "country", "country_code", "region_group", "original_title",
    "institution_id", "school_id", "appointment_type",
})

_BLANK = (None, "", "unknown", "Unknown")


def _is_blank(value):
    return value in _BLANK


def plan_field_updates(current, values, *, same_source):
    """Return the fields to write for one re-observation, and why.

    ``current`` is the stored row, ``values`` the normalized observation.
    ``same_source`` says whether the board producing this observation is one
    already linked to the job.
    """
    changes = {}
    reasons = {}

    for field in AUTHORITATIVE:
        if field not in values:
            continue
        new_value, old_value = values.get(field), current[field]
        if new_value == old_value:
            continue
        if same_source and field in CLEARABLE:
            # The owning source is allowed to withdraw a value it no longer
            # publishes; anything else would keep a closed deadline alive.
            changes[field] = new_value
            reasons[field] = "authoritative-same-source"
        elif not _is_blank(new_value):
            changes[field] = new_value
            reasons[field] = "authoritative"

    for field in EVIDENCE:
        if field not in values:
            continue
        new_value, old_value = values.get(field), current[field]
        if new_value == old_value or _is_blank(new_value):
            continue
        if same_source:
            changes[field] = new_value
            reasons[field] = "evidence-owner"
        elif _is_blank(old_value):
            # Another board may add what we do not have. It may not replace
            # what we do: two boards disagreeing about a salary is not a
            # reason to take whichever was scraped last.
            changes[field] = new_value
            reasons[field] = "evidence-fills-blank"

    for field in LAST_SEEN:
        if field not in values:
            continue
        new_value, old_value = values.get(field), current[field]
        if new_value and (not old_value or str(new_value) > str(old_value)):
            changes[field] = new_value
            reasons[field] = "latest-observation"

    return changes, reasons


__all__ = ["AUTHORITATIVE", "CLEARABLE", "EVIDENCE", "IMMUTABLE", "LAST_SEEN",
           "plan_field_updates"]
