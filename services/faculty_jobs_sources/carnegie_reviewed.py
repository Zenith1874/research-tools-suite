"""Bounded, reviewed official PageUp seeds under the existing Carnegie source.

Seeds are discovery leads, not truth: every application re-fetches the public
posting and verifies its ID, heading and explicit employer against the registry.
This supplementary workflow does not count a detail page as a visited portal.
"""

import hashlib
import json
from pathlib import Path
import re
import sqlite3
import unicodedata

from bs4 import BeautifulSoup

from services import raw_archive
from services.faculty_jobs_normalizer import classify_faculty_market_role, parse_deadline
from .base import AdapterError, AdapterResponse, SourceJob, now_utc, visible_text
from .carnegie import CarnegieOfficialAdapter, POOL_RE, POOL_BODY_RE, _read_only


PARSER_VERSION = "carnegie_reviewed_pageup_v1_20260920"
OFFICIAL_URL_RE = re.compile(
    r"^https://csucareers\.calstate\.edu/(?:cw/)?en-us/job/(\d+)/[^/?#]+$"
)


def _name(value):
    text = unicodedata.normalize("NFKD", str(value or "")).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()


def parse_reviewed_posting(payload, url, seed, targets, *, captured_at=None):
    """Return a SourceJob only for a fresh, identified public posting page."""
    match = OFFICIAL_URL_RE.fullmatch(url)
    if not match or url != seed["url"]:
        raise ValueError("Unexpected official URL or redirect; review again.")
    target = targets.get(seed["unitid"])
    if not target:
        raise ValueError("Seed UNITID is outside the selected Carnegie population.")
    soup = BeautifulSoup(payload, "html.parser")
    containers = soup.select("#job")
    if len(containers) != 1:
        raise ValueError("One public PageUp job container was not observed.")
    container = containers[0]
    headings = container.select("#job-content > h2")
    number = container.select_one(".job-externalJobNo")
    detail = container.select_one("#job-details")
    if len(headings) != 1 or number is None or detail is None:
        raise ValueError("Missing individual posting heading, identifier or body.")
    title = headings[0].get_text(" ", strip=True)
    if number.get_text(strip=True) != match[1] or _name(title) != _name(seed["expected_title"]):
        raise ValueError("Live posting identity differs from the reviewed seed.")
    description = visible_text(detail)
    if len(description) < 500:
        raise ValueError("Public posting body is too short for employer verification.")
    normalized_body = " " + _name(description) + " "
    employers = [row for row in targets.values()
                 if " " + _name(row["institution_name"]) + " " in normalized_body]
    if {row["unitid"] for row in employers} != {target["unitid"]}:
        raise ValueError("Body did not uniquely identify the expected registry institution.")
    if not classify_faculty_market_role(title, description, url).get("eligible"):
        raise ValueError("Live page does not establish an eligible faculty role.")
    if POOL_RE.search(title) or POOL_BODY_RE.search(description):
        raise ValueError("Pool or ongoing recruitment requires separate review.")
    school = seed.get("school")
    if school and _name(school) not in normalized_body:
        raise ValueError("Expected business school was not present in the live body.")
    # Read closing evidence outside #job-details too. The footer can contradict
    # 'open until filled' boilerplate; a dated expired footer blocks promotion.
    page_text = visible_text(container)
    closing = re.search(
        r"Applications\s+close:\s*(.*?)(?:Back to search results|Apply now|$)", page_text, re.I)
    closing_text = closing.group(1).strip() if closing else ""
    captured_at = captured_at or now_utc()
    deadline_raw = "Closing date: " + closing_text if closing_text else None
    deadline = parse_deadline(deadline_raw, description,
                              reference_date=captured_at, return_details=True)
    parsed_date = deadline.get("date") or deadline.get("deadline_date")
    if parsed_date and str(parsed_date)[:10] < captured_at[:10] and closing_text:
        raise ValueError("An explicit application closing date has passed.")
    stable_id = hashlib.sha256(f"{target['unitid']}|{url}".encode()).hexdigest()[:32]
    return SourceJob(
        source="carnegie_official", source_job_id=stable_id,
        source_url=url, official_url=url, title_raw=title,
        institution_raw=target["institution_name"], school_raw=school,
        location_raw=", ".join(str(target[key]) for key in ("city", "state") if target.get(key)),
        description_excerpt=description, deadline_raw=deadline_raw,
        captured_at=captured_at,
        extra={"unitid": target["unitid"], "target_segment": target.get("target_segment"),
               "posting_scope": "individual_advertisement", "posting_id": match[1],
               "parser_version": PARSER_VERSION, "school_evidence_context": "posting",
               "location_origin": "registry", "discovery_method": "reviewed_official_seed"},
    )


class CarnegieReviewedPageUpAdapter(CarnegieOfficialAdapter):
    def __init__(self, manifest_path, *args, audit_db=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.manifest_path = Path(manifest_path)
        self.manifest_bytes = self.manifest_path.read_bytes()
        self.seeds = json.loads(self.manifest_bytes)["postings"]
        if not 1 <= len(self.seeds) <= 20:
            raise ValueError("A reviewed batch must contain 1-20 official posting seeds.")
        if len({seed["url"] for seed in self.seeds}) != len(self.seeds):
            raise ValueError("Duplicate seed URLs are not permitted.")
        if any(not OFFICIAL_URL_RE.fullmatch(seed["url"]) for seed in self.seeds):
            raise ValueError("Only reviewed official CSU PageUp URLs are supported.")
        self.audit_db = Path(audit_db or self.scan_db.with_name("carnegie_reviewed_postings.db"))

    def fetch(self):
        registry = _read_only(self.registry_db)
        try:
            targets = {row["unitid"]: dict(row) for row in registry.execute(
                "SELECT * FROM institution_recruitment_targets")}
        finally:
            registry.close()
        self.audit_db.parent.mkdir(parents=True, exist_ok=True)
        audit = sqlite3.connect(self.audit_db)
        raw_archive.ensure_tables(audit)
        manifest_hash = hashlib.sha256(self.manifest_bytes).hexdigest()
        jobs, decisions, pages = [], [], 0
        try:
            for seed in self.seeds:
                captured_at, payload, http_status, job = now_utc(), None, None, None
                try:
                    response = self.request(seed["url"])
                    pages += 1
                    payload, http_status = response.content, response.status_code
                    if http_status != 200:
                        raise ValueError(f"HTTP {http_status}: a complete public posting was not returned.")
                    job = parse_reviewed_posting(payload, response.url, seed, targets,
                                                 captured_at=captured_at)
                    decision = "accepted"
                except Exception as error:
                    decision = f"held: {error}"
                note = {"manifest_sha256": manifest_hash, "seed": seed, "decision": decision}
                with audit:
                    raw_archive.record_observation(
                        audit, kind="detail", source_url=seed["url"], payload=payload,
                        source_job_id=job.source_job_id if job else None,
                        http_status=http_status, parser_version=PARSER_VERSION,
                        observed_at=captured_at, note=json.dumps(note, ensure_ascii=False),
                        root=self.audit_db.parent / "carnegie_reviewed_raw")
                decisions.append({"url": seed["url"], "decision": decision})
                if job:
                    jobs.append(job)
        finally:
            audit.close()
        if not pages:
            raise AdapterError(f"No readable reviewed official pages: {decisions}")
        return AdapterResponse(
            jobs=jobs, pages_fetched=pages, listing_pages=0, coverage_complete=False,
            notes=["Reviewed official supplement; no portal coverage or absence reconciliation. "
                   + json.dumps(decisions, ensure_ascii=False)],
        )
