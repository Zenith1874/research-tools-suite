"""Bounded, read-only collection to a new staging directory; never writes the DB."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import gzip
import hashlib
import json
import re
from pathlib import Path
import sys
import time
from urllib.parse import urljoin, urlsplit

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
import requests
from bs4 import BeautifulSoup
from services.faculty_jobs_requirements import PARSER_VERSION, empty_fields, parse_posting, public_url
from services.faculty_jobs_sources.base import SourceAdapter

QUERY = {"country": "US", "career_view": "r2_teaching", "scope": "business_school",
         "discipline": "Information Systems / MIS,Management,Organizational Behavior / HR", "limit": 200}


BOARD_HOSTS = ("higheredjobs.com", "insidehighered.com", "chronicle.com", "academiccareers.aisnet.org")
EMPLOYER_ATS_HOSTS = ("myworkdayjobs.com", "pageuppeople.com", "peopleadmin.com", "interfolio.com",
                      "oraclecloud.com", "schooljobs.com", "csucareers.calstate.edu")
CHALLENGE_RE = re.compile(r"verify (?:you are|that you are) (?:a )?human|access denied|enable javascript and cookies|checking your browser|unusual traffic|captcha challenge", re.I)


def employer_links(html, url):
    """Literal application/redirect links, never generated employer URL guesses."""
    soup = BeautifulSoup(html, "html.parser")
    candidates = []
    refresh = soup.find("meta", attrs={"http-equiv": re.compile("^refresh$", re.I)})
    if refresh:
        match = re.search(r"url\s*=\s*['\"]?([^'\"]+)", refresh.get("content", ""), re.I)
        if match:
            candidates.append(urljoin(url, match[1].strip()))
    for a in soup.find_all("a", href=True):
        label = a.get_text(" ", strip=True)
        href = urljoin(url, a["href"])
        if re.search(r"apply|continue to|application|employer.*website", label, re.I) and not a["href"].startswith("#"):
            candidates.append(href)
    return list(dict.fromkeys(u for u in candidates if public_url(u)
        and (u != url) and not re.search(r"admissions|undergraduate.apply|create.account|register", u, re.I)))[:2]


def employer_host(url):
    host = (urlsplit(url).hostname or "").lower()
    return host.endswith(".edu") or any(host == h or host.endswith("." + h) for h in EMPLOYER_ATS_HOSTS)


def posting_url(job, overrides=None):
    """Use a reviewed employer URL or historical employer reading before a board."""
    candidate = (overrides or {}).get(str(job["id"])) or job.get("official_url")
    previous = job.get("requirements") or {}
    if not candidate and previous.get("source_kind") == "official_posting":
        candidate = previous.get("final_url") or previous.get("source_url")
    if candidate:
        host = (urlsplit(candidate).hostname or "").lower()
        kind = "job_board" if any(host == b or host.endswith('.' + b) for b in BOARD_HOSTS) else "official_posting"
        return candidate, kind
    return next((s.get("source_url") for s in job.get("sources", []) if s.get("active")), ""), "job_board"


def collect(output, max_pages=60, timeout=15, overrides=None, manifest=None, jobs=None, query=None, progress=None):
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    (output / "raw").mkdir()
    selected_query = query or QUERY
    if jobs is not None:
        jobs = list(jobs)
    elif manifest:
        frozen = json.loads(Path(manifest).read_text(encoding="utf-8"))
        jobs = frozen["jobs"]
        selected_query = frozen.get("query") or selected_query
        if overrides:
            jobs = [job for job in jobs if str(job["id"]) in overrides]
    else:
        payload = requests.get("http://127.0.0.1:5001/api/faculty-jobs", params=selected_query, timeout=30).json()
        if not payload.get("ok") or payload["pagination"]["has_more"]:
            raise ValueError("Could not freeze the complete bounded priority cohort")
        jobs = payload["jobs"]
    (output / "manifest.json").write_text(json.dumps({"query": selected_query, "captured_at": datetime.now(timezone.utc).isoformat(), "jobs": jobs}, ensure_ascii=False, indent=2), encoding="utf-8")
    adapter = SourceAdapter(timeout=timeout)
    stopped_hosts, cache, reads = set(), {}, []
    pages = 0
    for job in jobs:
        url, kind = posting_url(job, overrides)
        stamp = datetime.now(timezone.utc).isoformat(timespec="seconds")
        item = {"job_id": job["id"], "source_url": url or "", "source_kind": kind, "captured_at": stamp,
                "parser_version": PARSER_VERSION, "status": "not_read", "fields": empty_fields(), "identity_verified": False}
        host = urlsplit(url or "").hostname
        if not public_url(url) or not host or host in {"localhost", "127.0.0.1", "::1"}:
            item["reason"] = "No public posting URL available"
        elif host in stopped_hosts:
            item.update(status="blocked", reason="This host refused an earlier request in the same run; no further attempts", fields=empty_fields("blocked"))
        elif pages >= max_pages and url not in cache:
            item["reason"] = "Declared page budget reached"
        else:
            try:
                if url not in cache:
                    pages += 1
                    time.sleep(1.2)
                    response = adapter.request(url)
                    content_type = response.headers.get("content-type", "").lower()
                    if response.encoding and response.encoding.lower() in {"iso-8859-1", "latin-1"} and "charset=" not in content_type:
                        try:
                            page_text = response.content.decode("utf-8")
                        except UnicodeDecodeError:
                            page_text = response.text
                    else:
                        page_text = response.text
                    cache[url] = (page_text, response.url, response.status_code)
                html, final_url, http_status = cache[url]
                if kind == "job_board" and employer_host(final_url):
                    kind = "official_posting"
                    item["source_kind"] = kind
                    item["requested_url"] = url
                    item["source_url"] = final_url
                raw = html.encode("utf-8")
                digest = hashlib.sha256(raw).hexdigest()
                raw_path = output / "raw" / (digest + ".html.gz")
                if not raw_path.exists():
                    with gzip.open(raw_path, "xb") as handle:
                        handle.write(raw)
                parsed = parse_posting(html, job, final_url, kind)
                item.update({k: v for k, v in parsed.items() if k != "text"})
                item.update(final_url=final_url, http_status=http_status, content_hash=digest, raw_path=str(raw_path.relative_to(output)))
                if parsed["status"] == "blocked" and CHALLENGE_RE.search(parsed.get("text") or ""):
                    stopped_hosts.add(host)
            except Exception as exc:
                message = str(exc)[:500]
                blocked = any(x in message.lower() for x in ("403", "401", "429", "robot", "disallow", "refused"))
                item.update(status="blocked" if blocked else "error", reason=f"{type(exc).__name__}: {message}", fields=empty_fields("blocked" if blocked else "not_read"))
                if blocked:
                    stopped_hosts.add(host)
        reads.append(item)
        with (output / "reads.jsonl").open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(item, ensure_ascii=False) + "\n")
        event = {"job_id": job["id"], "status": item["status"], "source_kind": kind,
                 "supported": [k for k, v in item["fields"].items() if v["status"] == "supported"], "pages": pages}
        if progress:
            progress(event)
        else:
            print(json.dumps(event), flush=True)
        # Follow the application href that a successfully read board actually
        # exposed. A public redirect page may expose one further literal href
        # or meta refresh. Each step consumes the declared page budget.
        pending = employer_links(html, final_url) if kind == "job_board" and item["status"] == "ok" else []
        visited = {url}
        followed = 0
        while pending and followed < 2 and pages < max_pages:
            next_url = pending.pop(0)
            next_host = urlsplit(next_url).hostname
            if next_url in visited or next_host in stopped_hosts:
                continue
            visited.add(next_url)
            followed += 1
            follow = {"job_id": job["id"], "source_url": next_url,
                "source_kind": "official_posting" if employer_host(next_url) else "job_board",
                "captured_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
                "parser_version": PARSER_VERSION, "status": "not_read", "fields": empty_fields(),
                "identity_verified": False, "discovery_parent_url": final_url}
            try:
                pages += 1
                time.sleep(1.2)
                response = adapter.request(next_url)
                content = response.content.decode("utf-8", errors="replace")
                destination = response.url
                follow["source_kind"] = "official_posting" if employer_host(destination) else "job_board"
                if follow["source_kind"] == "official_posting":
                    follow["requested_url"] = next_url
                    follow["source_url"] = destination
                parsed_follow = parse_posting(content, job, destination, follow["source_kind"])
                digest = hashlib.sha256(content.encode("utf-8")).hexdigest()
                raw_path = output / "raw" / (digest + ".html.gz")
                if not raw_path.exists():
                    with gzip.open(raw_path, "xb") as handle:
                        handle.write(content.encode("utf-8"))
                follow.update({k: v for k, v in parsed_follow.items() if k != "text"})
                follow.update(final_url=destination, http_status=response.status_code,
                    content_hash=digest, raw_path=str(raw_path.relative_to(output)))
                challenge = CHALLENGE_RE.search(parsed_follow.get("text") or "")
                if challenge:
                    stopped_hosts.add(next_host)
                if follow["source_kind"] == "job_board" and not challenge:
                    pending.extend(u for u in employer_links(content, destination) if u not in visited)
            except Exception as exc:
                blocked = any(x in str(exc).lower() for x in ("403", "401", "429", "robot", "disallow", "refused"))
                follow.update(status="blocked" if blocked else "error", reason=str(exc)[:500],
                    fields=empty_fields("blocked" if blocked else "not_read"))
                if blocked:
                    stopped_hosts.add(next_host)
            reads.append(follow)
            with (output / "reads.jsonl").open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(follow, ensure_ascii=False) + "\n")
            follow_event = {"job_id": job["id"], "status": follow["status"], "source_kind": follow["source_kind"],
                "discovered_apply_link": True, "pages": pages}
            if progress:
                progress(follow_event)
            else:
                print(json.dumps(follow_event), flush=True)
    summary = {"jobs": len(jobs), "pages_attempted": pages, "status_counts": dict(Counter(x["status"] for x in reads)),
               "max_pages": max_pages, "timeout_seconds": timeout, "stopped_hosts": sorted(stopped_hosts), "parser_version": PARSER_VERSION}
    (output / "collection-summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary), flush=True)
    return {"summary": summary, "reads": reads, "output": str(output)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", required=True)
    parser.add_argument("--max-pages", type=int, default=60)
    parser.add_argument("--timeout", type=int, default=15)
    parser.add_argument("--official-overrides", help="Reviewed job-id to exact official posting URL JSON mapping")
    parser.add_argument("--manifest", help="Frozen cohort; visit only explicitly supplied official overrides, not blocked board URLs")
    parser.add_argument("--career-view", default="r2_teaching", choices=("r2_teaching", "r1", "all"))
    args = parser.parse_args()
    overrides = json.loads(Path(args.official_overrides).read_text(encoding="utf-8")) if args.official_overrides else None
    collect(args.output, min(200, max(0, args.max_pages)), min(15, max(1, args.timeout)), overrides, args.manifest,
            query={**QUERY, "career_view": args.career_view})
