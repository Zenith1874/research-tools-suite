"""Append-only, posting-level requirements. Missing evidence is never a negative fact."""
from datetime import datetime, timezone
import hashlib
import ipaddress
import json
import re
import unicodedata
from urllib.parse import urljoin, urlsplit

from bs4 import BeautifulSoup

PARSER_VERSION = "priority_requirements_v10_20261002"
FIELDS = ("application_url", "teaching_load", "research_requirements", "start_date", "materials", "review_date", "hard_deadline", "recruitment_mode", "phd_requirement", "teaching_experience", "appointment_contract", "posting_kind")
REQUIRED_FIELDS = FIELDS[:5]


def ensure_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS job_requirement_reads (
        id INTEGER PRIMARY KEY, observation_key TEXT NOT NULL UNIQUE,
        job_id INTEGER NOT NULL REFERENCES jobs(id), source_url TEXT NOT NULL,
        final_url TEXT, source_kind TEXT NOT NULL, captured_at TEXT NOT NULL,
        status TEXT NOT NULL, reason TEXT, http_status INTEGER, content_hash TEXT,
        parser_version TEXT NOT NULL, identity_verified INTEGER NOT NULL DEFAULT 0,
        fields_json TEXT NOT NULL, supported_count INTEGER NOT NULL DEFAULT 0,
        review_date TEXT, raw_observation_id INTEGER REFERENCES raw_observations(id))""")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_requirement_job_time ON job_requirement_reads(job_id,captured_at DESC,id DESC)")
    # Prefer a complete official read over a board read. A failed subsequent
    # visit does not erase historical evidence; the read model exposes both.
    conn.execute("""CREATE VIEW IF NOT EXISTS job_requirement_current AS
        SELECT r.* FROM job_requirement_reads r WHERE r.id=(
          SELECT x.id FROM job_requirement_reads x WHERE x.job_id=r.job_id
          ORDER BY CASE WHEN x.status='ok' AND x.identity_verified=1 THEN
            CASE WHEN x.source_kind='official_posting' THEN 0 ELSE 1 END ELSE 2 END,
            x.captured_at DESC,x.id DESC LIMIT 1)""")


def public_url(value):
    try:
        parsed = urlsplit(value or "")
        if parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username or parsed.password:
            return False
        host = parsed.hostname.lower()
        if host in {"localhost", "localhost.localdomain"} or host.endswith(".local"):
            return False
        try:
            return ipaddress.ip_address(host).is_global
        except ValueError:
            return True
    except ValueError:
        return False


def _tokens(value):
    ignore = {"assistant", "associate", "professor", "faculty", "university", "college", "school", "department", "position", "positions", "tenure", "track", "with", "from", "this", "that", "full", "time", "state", "the", "and", "for", "of", "in", "or"}
    return {x for x in re.findall(r"[a-z0-9]+", (value or "").lower()) if len(x) > 2 and x not in ignore
            and not x.isdigit() and not re.fullmatch(r"[a-z]{1,3}\d{3,}[a-z]?", x)}


def date_in_quote(text):
    """Only explicit calendar dates with years; never invent a term's day."""
    months = "January February March April May June July August September October November December".split()
    month_pattern = "|".join(m + "|" + m[:3] + r"\.?" for m in months)
    match = re.search(rf"\b({month_pattern})\s+(\d{{1,2}})(?:st|nd|rd|th)?\s*,?\s*(20\d{{2}})\b", text, re.I)
    if match:
        month = next(i + 1 for i, name in enumerate(months) if name.lower().startswith(match[1][:3].lower()))
        parts = int(match[3]), month, int(match[2])
    else:
        match = re.search(r"\b(20\d{2})-(\d{2})-(\d{2})\b", text)
        if not match:
            match = re.search(r"\b(\d{1,2})/(\d{1,2})/(20\d{2})\b", text)
            if not match:
                return None
            parts = int(match[3]), int(match[1]), int(match[2])
        else:
            parts = tuple(map(int, match.groups()))
    try:
        return datetime(*parts).date().isoformat()
    except ValueError:
        return None


def empty_fields(status="not_read"):
    return {name: {"status": status, "value": None, "quote": None, "normalized_date": None} for name in FIELDS}


def _jobposting_nodes(value):
    """Yield public schema.org JobPosting objects embedded in employer HTML."""
    if isinstance(value, list):
        for item in value:
            yield from _jobposting_nodes(item)
    elif isinstance(value, dict):
        if value.get("@type") == "JobPosting":
            yield value
        for key in ("@graph", "mainEntity", "itemListElement"):
            if key in value:
                yield from _jobposting_nodes(value[key])


def _append_structured_jobposting(soup):
    """Expose an official page's JSON-LD as the same literal rendered text.

    Workday often ships the complete public posting in schema.org JSON-LD while
    leaving the visible DOM as a JavaScript shell.  This is first-party page
    content, not a hidden or authenticated endpoint.
    """
    nodes = []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        try:
            nodes.extend(_jobposting_nodes(json.loads(script.string or script.get_text() or "")))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
    if not nodes:
        return False
    node = nodes[0]
    container = soup.new_tag("section")
    container["data-source"] = "official-schema-jobposting"
    title = node.get("title")
    organization = ((node.get("hiringOrganization") or {}).get("name")
                    if isinstance(node.get("hiringOrganization"), dict) else None)
    for tag_name, value in (("h1", title), ("p", organization)):
        if value:
            tag = soup.new_tag(tag_name)
            tag.string = str(value)
            container.append(tag)
    if node.get("description"):
        description = str(node["description"])
        fragment = BeautifulSoup(description, "html.parser")
        if "<" in description:
            for child in list(fragment.contents):
                container.append(child.extract())
        else:
            labels = ("Position Title", "Job Category", "Employment Type", "Job Profile",
                      "Position Summary", "Job Duties", "Key Job Responsibilities", "Department",
                      "Compensation", "Required Qualifications", "Preferred Qualifications",
                      "To Apply", "Required application materials", "Application Instructions",
                      "Job Title", "Job Details", "Job Summary", "Qualifications", "Applicants should submit",
                      "INSTRUCTIONS TO APPLICANT", "SUMMARY", "DUTIES & RESPONSIBILITIES",
                      "MINIMUM REQUIREMENTS", "PREFERRED EDUCATION / SKILLS/ EXPERIENCE",
                      "Required Documents to Apply", "Special Instructions to Applicants",
                      "Summary of Job Duties", "Knowledge, Skills, and Abilities", "Salary Information",
                      "Institution Name", "Sponsorship Available", "Type of Position", "Expected Start Date")
            label_pattern = "|".join(re.escape(label) for label in labels)
            parts = re.split(rf"(?<=[.!?])\s+(?=[A-Z])|\s+(?=(?:{label_pattern})\s*:)", description)
            for value in parts:
                if value.strip():
                    tag = soup.new_tag("p")
                    tag.string = value.strip()
                    container.append(tag)
    soup.append(container)
    return True


def parse_posting(html, job, url, source_kind="official_posting"):
    """Conservative extraction from rendered public HTML, without LLM guesses."""
    soup = BeautifulSoup(html, "html.parser")
    structured = _append_structured_jobposting(soup)
    for tag in soup(["script", "style", "nav", "footer", "header", "noscript"]):
        tag.decompose()
    text = "\n".join(line.strip() for line in soup.get_text("\n").splitlines() if line.strip())
    lower = text.lower()
    if len(text) < 150 or re.search(r"verify (?:you are|that you are) (?:a )?human|access denied|enable javascript and cookies|checking your browser|unusual traffic|captcha challenge", lower):
        return {"status": "blocked", "reason": "Challenge or insufficient public page text; not bypassed", "identity_verified": False, "fields": empty_fields("blocked"), "text": text}
    if re.search(r"(?:job|position|posting) (?:is |has been )?(?:no longer available|not found|removed|closed)|sorry[^\n]{0,80}job[^\n]{0,40}(?:closed|unavailable)", lower):
        return {"status": "closed_page", "reason": "Page explicitly reports an unavailable posting; original job status retained", "identity_verified": False, "fields": empty_fields("needs_verification"), "text": text}
    headings = " ".join(tag.get_text(" ", strip=True) for tag in soup.find_all(["h1", "h2", "h3", "title"]))
    expected = _tokens(job.get("title_raw"))
    actual = _tokens(headings)
    title_ok = bool(expected) and len(expected & actual) / len(expected) >= .60
    institution_tokens = _tokens(job.get("institution_name") or job.get("institution_raw"))
    institution_ok = bool(institution_tokens & _tokens(text))
    if not title_ok or not institution_ok:
        return {"status": "identity_unverified", "reason": "Posting title/institution not independently matched on the returned page", "identity_verified": False, "fields": empty_fields("needs_verification"), "text": text}
    fields = empty_fields("not_stated")
    lines = text.splitlines()

    def support(name, quote, value=None):
        quote = quote.strip()
        if not quote or quote not in text:
            raise ValueError("Evidence must be a literal span of the captured page text")
        fields[name] = {"status": "supported", "value": value or quote, "quote": quote,
                        "normalized_date": date_in_quote(quote) if name in {"start_date", "review_date", "hard_deadline"} else None}

    # This is the href exposed by the verified employer posting, not a claim
    # that the application form or its login-protected contents were read.
    if source_kind == "official_posting":
        for link in soup.find_all("a", href=True):
            label = link.get_text(" ", strip=True)
            href = urljoin(url, link["href"])
            if re.fullmatch(r"apply(?:\s+(?:now|here|for (?:this )?(?:job|position)))?[!\s]*|apply online|apply (?:for|to) this (?:job|position)", label, re.I) and public_url(href) and not re.search(r"admissions|calstate.edu/apply", href):
                quote = label if label in text else None
                if quote:
                    support("application_url", quote, href)
                    fields["application_url"]["link_basis"] = "Actual apply-link href on the verified employer posting; destination form not read"
                    break

    number = r"(?:\d+(?:\.\d+)?|one|two|three|four|five|six|seven|eight|nine|twelve)"
    research_candidates = []
    from services.faculty_jobs_normalizer import _positive_open_until_filled, infer_track
    for idx, line in enumerate(lines):
        # Adjacent lines are retained verbatim to cover a standalone label.
        span = "\n".join(lines[idx:idx + 3])
        if fields["posting_kind"]["status"] != "supported" and re.search(r"generating an applicant pool|pool will remain|continuous recruitment|future vacancies|future openings|(?:adjunct|instructor|lecturer|applicant) pool posting", line, re.I):
            support("posting_kind", line, "pool")
        if fields["appointment_contract"]["status"] != "supported" and re.search(r"type of position|appointment status|(?:this|the|a|faculty|track) position|position (?:of|is)|(?:this|the|a) appointment", line, re.I) and not re.search(r"faculty (?:includes|members)|tenured and tenure.track faculty|our faculty", line, re.I):
            contract = infer_track(line)
            if contract in {"tenure_track", "tenured", "non_tenure_track"}:
                support("appointment_contract", line, contract)
        if fields["phd_requirement"]["status"] != "supported" and re.fullmatch(r"(?:Required|Basic|Minimum) Qualifications\s*:", line, re.I) and re.search(r"\bPh\.?\s?D\.?|doctorate|doctoral degree|\bDBA\b", span, re.I):
            support("phd_requirement", "\n".join(lines[idx:idx + 2]))
        if fields["phd_requirement"]["status"] != "supported" and re.search(r"\bPh\.?\s?D\.?|doctorate|doctoral degree|\bDBA\b|D\.B\.A\.", line, re.I) and re.search(r"required|must|candidates? (?:will|should|have)|earned|completed|hold|qualifications", line, re.I):
            support("phd_requirement", line)
        if fields["teaching_experience"]["status"] != "supported" and re.search(r"teaching (?:experience|effectiveness|excellence)|experience (?:in )?teaching|effective teaching|(?:ability|willingness)[^\n]{0,60}to teach", line, re.I) and re.search(r"candidates?|applicants?|required|demonstrate|evidence|experience|expected|preference", line, re.I):
            support("teaching_experience", line)
        mode_span = "\n".join(lines[idx:idx + 2]) if re.search(r"filled\s*:\s*$", unicodedata.normalize("NFKC", line), re.I) else line
        if fields["recruitment_mode"]["status"] != "supported" and _positive_open_until_filled(unicodedata.normalize("NFKC", mode_span)):
            support("recruitment_mode", mode_span, "open_until_filled")
        if fields["hard_deadline"]["status"] != "supported" and re.search(r"application deadline|closing date|applications? close|final deadline|final date", line, re.I) and date_in_quote(span):
            # A heading above a review date is not evidence of a hard close.
            if re.search(r"final date|final deadline", line, re.I) or not re.search(r"review|consideration|screening", span, re.I):
                support("hard_deadline", line if date_in_quote(line) else span)
        if fields["teaching_load"]["status"] != "supported":
            if re.search(rf"\b{number}\s+(?:(?:credit|contact|semester)\s+)?(?:courses?|hours?|credits?)\b[^\n]{{0,150}}(?:semester|term|year|annually)|(?:teaching|course)\s+load[^\n]{{0,100}}(?:{number}|\d-\d)|(?:\b\d[-/]\d\b)[^\n]{{0,60}}(?:teaching|load)", line, re.I):
                # Student degree credits are not the faculty's teaching load.
                if re.search(r"teach|load|instruct", line, re.I) and not re.search(r"students (?:must|are required to) (?:complete|take)", line, re.I):
                    support("teaching_load", line)
        if re.search(r"\b(?:research|scholarly|scholarship)\b", line, re.I) and re.search(r"\b(?:candidates?|applicants?|expected|required|demonstrated|evidence of|maintain|maintaining|publish|published|publications|peer.reviewed|productive|potential|record of|conduct|conducting|engage)\b", line, re.I) and not re.search(r"university.*(?:mission|founded)|million|billion|research centers|research areas of|student clubs|faculty members share|should submit|statement of research|research statement", line, re.I) and (len(line) > 100 or re.search(r"^(?:demonstrated|strong|engage|maintain|publish|conduct|an interest|evidence|candidates|applicants)", line, re.I)):
            quote = line
            for fragment in line.split(';'):
                if re.match(r"\s*(?:publish|conduct|maintain|engage)\b", fragment, re.I) and re.search(r"research|scholarly|scholarship", fragment, re.I):
                    quote = fragment.strip()
                    break
            score = 3 * bool(re.search(r"must|expected|required|demonstrated|evidence", quote, re.I)) + 4 * bool(re.search(r"peer.review|publications|research program|high.impact|publish|conduct", quote, re.I))
            research_candidates.append((score, -idx, quote))
        if fields["start_date"]["status"] != "supported":
            if re.search(r"start(?:ing)? (?:date|in|on|january|august|september|fall)|(?:target|anticipated|expected) start|begin(?:ning|s)? (?:during|in|on|date|august|july|september|fall|spring)|effective (?:date|august|july)|appointment[^\n]{0,45}(?:begin|start)|commenc", line, re.I) and re.search(r"\b20\d{2}\b", span):
                support("start_date", line if re.search(r"\b20\d{2}\b", line) else span)
        if fields["review_date"]["status"] != "supported":
            if re.search(r"(?:review|screening) of (?:applications|applicants)|(?:application|applicant) (?:review|screening)|priority (?:consideration|deadline)|(?:full|first) consideration|initial review|first review|(?:next|most recent) review date|review (?:will )?begin", line, re.I) and date_in_quote(span):
                support("review_date", line if date_in_quote(line) else span)
        if fields["materials"]["status"] != "supported":
            if re.search(r"^(?:how to apply|to apply|instructions to applicant|required documents|required application materials|additional application materials|required application|document requirements|application (?:procedure|process|materials|instructions|requirements)|applicant documents)|(?:applicants|candidates) should submit|you should include|completed application will consist|please apply online|please complete the online application|attach the following|following (?:required )?documents", line, re.I):
                block = "\n".join(lines[idx:idx + 22])
                # Stop before unrelated institutional and employment notices.
                end = re.search(r"\n(?:Additional Information|Conditions of Employment|Salary|Compensation|About\b|Equal Opportunity|Reasonable Accommodation|Advertised:|Applications close:|Please Be Advised|The position is open|The University|Stockton University is|A background check|CSU|On September|CONDITIONS|Requests for information|Share this job|Apply on website|Save$|How to Apply:|Job Title:|Department:|Job Details:|Legal Notices|UW is an Equal Opportunity Employer|SUMMARY:|DUTIES & RESPONSIBILITIES:|MINIMUM REQUIREMENTS:)", block, re.I)
                if end:
                    block = block[:end.start()]
                inline_end = re.search(r"\s+(?:Timing:|About WPI:|About the Business School:|Pre-employment Screening Requirements:)", block, re.I)
                if inline_end:
                    block = block[:inline_end.start()]
                if re.search(r"curriculum vitae|\bcv\b|cover letter|letter of (?:interest|application)|teaching statement|statement of (?:teaching|research)", block, re.I):
                    support("materials", block)
    if research_candidates:
        support("research_requirements", max(research_candidates)[2])
    if source_kind == "official_posting" and fields["application_url"]["status"] != "supported" and fields["materials"]["status"] == "supported":
        # Email-based applications still have an official instructions page.
        # Keep its actual instructions; do not invent a separate ATS endpoint.
        support("application_url", fields["materials"]["quote"], url)
        fields["application_url"]["link_basis"] = "Verified employer posting with application instructions; not a separately verified application form"
    if fields["hard_deadline"]["status"] == "supported" and fields["recruitment_mode"]["status"] == "supported":
        fields["hard_deadline"].update(status="needs_verification", conflict="A dated deadline and open-until-filled wording coexist. Do not treat this as a confirmed hard close; inspect the original wording.")
    # Source conflicts are visible, not reconciled by inventing a preferred date.
    title_years = set(re.findall(r"\b20\d{2}\b", job.get("title_raw") or ""))
    start_years = set(re.findall(r"\b20\d{2}\b", fields["start_date"].get("quote") or ""))
    if title_years and start_years and not title_years & start_years:
        fields["start_date"].update(status="needs_verification", conflict="Posting title and body state different start years; both retained without choosing one")
    basis = "embedded schema.org JobPosting and page text" if structured else "page text"
    return {"status": "ok", "reason": f"Title and institution matched; only explicit {basis} extracted", "identity_verified": True, "fields": fields, "text": text}


def import_read(conn, item, raw_observation_id=None):
    fields = item["fields"]
    if set(fields) != set(FIELDS):
        raise ValueError("Requirements snapshot must account for every requested field")
    for value in fields.values():
        if value["status"] == "supported" and (not value.get("quote") or not value.get("value")):
            raise ValueError("Supported requirements need an original quote and a value")
    key = hashlib.sha256(json.dumps({k: item.get(k) for k in ("job_id", "source_url", "captured_at", "content_hash", "parser_version")}, sort_keys=True).encode()).hexdigest()
    cur = conn.execute("""INSERT OR IGNORE INTO job_requirement_reads
        (observation_key,job_id,source_url,final_url,source_kind,captured_at,status,reason,http_status,content_hash,
         parser_version,identity_verified,fields_json,supported_count,review_date,raw_observation_id)
        VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""", (
        key, item["job_id"], item["source_url"], item.get("final_url"), item["source_kind"], item["captured_at"],
        item["status"], item.get("reason"), item.get("http_status"), item.get("content_hash"), item["parser_version"],
        int(item.get("identity_verified", False)), json.dumps(fields, ensure_ascii=False),
        sum(fields[x]["status"] == "supported" for x in REQUIRED_FIELDS),
        fields["review_date"].get("normalized_date") if fields["review_date"]["status"] == "supported" else None,
        raw_observation_id))
    return cur.rowcount


def requirements_for_job(conn, job_id):
    row = conn.execute("SELECT * FROM job_requirement_current WHERE job_id=?", (job_id,)).fetchone()
    latest = conn.execute("SELECT status,captured_at,reason FROM job_requirement_reads WHERE job_id=? ORDER BY captured_at DESC,id DESC LIMIT 1", (job_id,)).fetchone()
    if not row:
        return {"status": "not_read", "fields": empty_fields(), "supported_count": 0, "official_supported_count": 0}
    result = dict(row)
    result["fields"] = json.loads(result.pop("fields_json"))
    result["official_supported_count"] = result["supported_count"] if result["source_kind"] == "official_posting" and result["identity_verified"] else 0
    result["latest_attempt"] = dict(latest) if latest else None
    result["boundary"] = "Requirements are from the dated captured posting, not a live guarantee or an assessment of the candidate. Not stated is not no requirement."
    return result


def timing_for_job(job, requirements):
    """Keep the three timing concepts and observation clocks separate."""
    fields = requirements.get("fields", {})
    official = requirements.get("status") == "ok" and requirements.get("source_kind") == "official_posting" and requirements.get("identity_verified")
    mode = fields.get("recruitment_mode", {})
    hard = fields.get("hard_deadline", {})
    review = fields.get("review_date", {})
    hard_date = hard.get("normalized_date") if hard.get("status") == "supported" else None
    hard_basis = "captured_posting" if hard_date else "unknown"
    if not official and not hard_date and job.get("deadline_mode") == "fixed":
        hard_date, hard_basis = job.get("deadline_date"), "stored_record_needs_verification"
    return {
        "hard_deadline": hard_date, "hard_deadline_basis": hard_basis,
        "hard_deadline_status": hard.get("status", "not_read"),
        "review_date": review.get("normalized_date") if review.get("status") == "supported" else None,
        "recruitment_mode": mode.get("value") if mode.get("status") == "supported" else job.get("deadline_mode") or "unknown",
        "mode_basis": "captured_posting" if mode.get("status") == "supported" else "stored_record_needs_verification",
        "last_verified_at": requirements.get("captured_at") if official else None,
        "last_read_at": requirements.get("captured_at") if requirements.get("status") == "ok" else None,
        "last_attempt_at": (requirements.get("latest_attempt") or {}).get("captured_at"),
        "source_url": requirements.get("source_url"),
        "boundary": "Successful verification means this posting's identity and public text were read at that time, not that it is currently open. Failed attempts never renew verification.",
    }
