# -*- coding: utf-8 -*-
"""Optional model-assisted reading of sponsorship wording.

The rules in ``faculty_jobs_normalizer`` are the authority. They answer from
patterns we chose, they are auditable, and they run on every posting for free.
This module exists for the residue: postings whose body we have read in full
and whose sponsorship paragraph is phrased in a way no pattern anticipated.

Two properties make this safe to store next to rule-derived values.

**Grounding is enforced, not requested.** The model must return the sentence it
decided from, and that sentence must appear verbatim in the posting text --
whitespace normalized, nothing else. A quote that is not in the source is
discarded along with the whole verdict. A model that invents "the university
will sponsor an H-1B" for a posting that never said so produces no row, not a
wrong row. This is the only reason a probabilistic reader is allowed near a
field where an inverted answer costs a candidate an application.

**It never overrides the rules.** It is only ever asked about postings the
rules returned ``unknown`` for, and only when there is enough text to read. It
cannot flip a rule-derived yes to a no.

Provenance records ``llm`` as the deriver, so any value from here is separable
from the rule-derived ones and can be reverted as a set.

Off by default. Set ``ANTHROPIC_API_KEY`` (or ``DEEPSEEK_API_KEY``) to enable;
with no key configured every entry point here is a no-op that says so.

The provider call is raw HTTP over ``requests``, matching
``services/abdc_astar_research_service.py`` -- the project's existing and only
LLM integration -- rather than adding an SDK dependency.
"""

import json
import os
import re

import requests

from services import deepseek_client
from services.faculty_jobs_normalizer import VISA_STATUSES, clean_text, visa_pathways

ANTHROPIC_URL = "https://api.anthropic.com/v1/messages"
DEEPSEEK_URL = "https://api.deepseek.com/chat/completions"
ANTHROPIC_MODEL_DEFAULT = "claude-opus-5"
DEEPSEEK_MODEL_DEFAULT = "deepseek-v4-flash"

# Below this there is no sponsorship paragraph to find, only a listing blurb.
# Asking about one wastes a call and invites the model to guess from the
# institution's name, which is the failure this project has spent its whole
# history avoiding.
MIN_BODY_CHARS = 400

# The posting's own words, capped. Sponsorship wording is at the end, so when a
# body is longer than this the tail is what we keep.
MAX_BODY_CHARS = 6000

SYSTEM = (
    "You extract visa-sponsorship facts from academic job postings. You report "
    "only what the posting states. You never infer sponsorship from the "
    "institution's name, country, prestige, or the seniority of the role.\n\n"
    "Return exactly one JSON object, no other text:\n"
    '  {"status": <one of the values below>, "quote": <verbatim sentence from '
    'the posting, or null>, "pathways": [<named programmes>]}\n\n'
    "status values:\n"
    "  citizenship_required            - the posting requires US citizenship\n"
    "  citizen_or_pr_required          - requires citizenship OR permanent residency\n"
    "  sponsorship_explicit_no         - states it will not sponsor\n"
    "  permanent_residency_supported   - states it will support a green card / PERM / EB petition\n"
    "  sponsorship_explicit_yes        - states it will sponsor a work visa\n"
    "  international_candidates_welcome- welcomes international applicants, no sponsorship commitment\n"
    "  unclear                         - mentions the subject without committing\n"
    "  unknown                         - the posting does not address it\n\n"
    "pathways: only programmes the posting names literally. Allowed values: "
    "h1b, j1, o1, tn, e3, eb1, eb2, perm, green_card. Never infer a category "
    "the posting does not name -- an employer chooses an EB category after "
    "hiring, so it cannot be read out of a job advertisement.\n\n"
    "quote: copy the sentence exactly from the posting. Do not paraphrase, "
    "correct, or shorten it. If status is unknown, quote must be null. A quote "
    "that does not appear in the posting causes the whole answer to be "
    "discarded, so when in doubt return unknown."
)


class VisaLLMUnavailable(RuntimeError):
    """No provider is configured; the caller should carry on without one."""


def provider():
    """Return ``(provider, model)``, or ``(None, None)`` when unconfigured."""
    if os.environ.get("ANTHROPIC_API_KEY"):
        return "anthropic", os.environ.get(
            "FACULTY_VISA_LLM_MODEL", ANTHROPIC_MODEL_DEFAULT)
    if os.environ.get("DEEPSEEK_API_KEY"):
        return "deepseek", os.environ.get(
            "FACULTY_VISA_LLM_MODEL", DEEPSEEK_MODEL_DEFAULT)
    return None, None


def available():
    return provider()[0] is not None


def _body_for(text):
    """The tail of the posting, where sponsorship wording lives."""
    cleaned = clean_text(text)
    if len(cleaned) <= MAX_BODY_CHARS:
        return cleaned
    return cleaned[-MAX_BODY_CHARS:]


def _normalized(value):
    return " ".join(str(value or "").split()).casefold()


def _quote_is_in_source(quote, body):
    """Verbatim check, whitespace-normalized and nothing else.

    Deliberately strict. Allowing near-matches would re-admit the failure mode
    this check exists to prevent: a plausible sentence that the posting never
    contained.
    """
    if not quote:
        return False
    needle = _normalized(quote)
    if len(needle) < 12:
        return False
    return needle in _normalized(body)


def _anthropic_call(body, model, timeout):
    response = requests.post(
        ANTHROPIC_URL,
        headers={
            "x-api-key": os.environ["ANTHROPIC_API_KEY"],
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": model,
            "max_tokens": 700,
            "system": SYSTEM,
            "messages": [{"role": "user", "content": body + "\n\nReturn only the JSON object."}],
        },
        timeout=timeout,
    )
    response.raise_for_status()
    return "".join(
        block.get("text", "") for block in response.json().get("content", [])
    )


def _deepseek_call(body, model, timeout):
    # 请求怎么构造交给 services/deepseek_client。"thinking 必须关掉"这一条曾经
    # 在这里漏掉：20 条实测里 3 条拿到空回复，而账照付。
    return deepseek_client.chat(
        SYSTEM, body + "\n\nReturn only the JSON object.",
        model=model, max_tokens=700, temperature=0, timeout=timeout)


def classify(text, timeout=45):
    """Read one posting. Returns the same shape as ``classify_visa``.

    Adds ``rejected`` when an answer was received and thrown away, naming why.
    A rejected answer is reported rather than silently downgraded, because
    "the model answered and we did not believe it" is a different fact from
    "the posting said nothing", and only the first says anything about the
    reader.
    """
    name, model = provider()
    if not name:
        raise VisaLLMUnavailable("no ANTHROPIC_API_KEY or DEEPSEEK_API_KEY configured")

    body = _body_for(text)
    if len(body) < MIN_BODY_CHARS:
        return {"status": "unknown", "evidence": None, "pathways": [],
                "rejected": "body too short to contain a sponsorship statement",
                "model": model}

    raw = (_anthropic_call if name == "anthropic" else _deepseek_call)(body, model, timeout)
    match = re.search(r"\{.*\}", raw or "", re.DOTALL)
    if not match:
        return {"status": "unknown", "evidence": None, "pathways": [],
                "rejected": "no JSON object in the reply", "model": model}
    try:
        parsed = json.loads(match.group(0))
    except ValueError:
        return {"status": "unknown", "evidence": None, "pathways": [],
                "rejected": "reply was not valid JSON", "model": model}

    status = str(parsed.get("status") or "unknown").strip()
    if status not in VISA_STATUSES:
        return {"status": "unknown", "evidence": None, "pathways": [],
                "rejected": f"status {status!r} is not one of the allowed values",
                "model": model}
    if status == "unknown":
        return {"status": "unknown", "evidence": None, "pathways": [], "model": model}

    quote = parsed.get("quote")
    if not _quote_is_in_source(quote, body):
        # The whole verdict goes, not just the quote. An answer we cannot trace
        # to the posting is an answer about some other posting.
        return {"status": "unknown", "evidence": None, "pathways": [],
                "rejected": "quoted sentence does not appear in the posting",
                "model": model}

    # Pathways are re-derived from the text rather than taken on trust: the
    # model is asked for them only so its attention is on the right sentences.
    return {
        "status": status,
        "evidence": " ".join(str(quote).split())[:400],
        "pathways": visa_pathways(body),
        "model": model,
    }


__all__ = ["MIN_BODY_CHARS", "VisaLLMUnavailable", "available", "classify", "provider"]
