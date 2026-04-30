#!/usr/bin/env python3
"""
JobPilot Scraper — ARM64 Raspberry Pi 5 compatible
====================================================
Sources:
  1. Indeed      — via Anthropic API + Indeed MCP (requires Anthropic API key)
  2. Remotive    — free REST API, US remote jobs, no key needed
  3. USAJobs.gov — free, US federal jobs (optional, set USAJOBS_API_KEY)

Removed:
  - jobspy    : tls-client-arm64.so binary is broken on Pi 5
  - Arbeitnow : European job board — was returning Germany/UK jobs
"""

import os, sys, hashlib, logging, requests, time, re, json
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
LOG  = os.path.join(BASE, "logs", "scraper.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("scraper")

def _uid(*parts):
    return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()[:16]

def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()

def _dedup(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"].strip():
            seen.add(key)
            out.append(j)
    return out

def _title_matches(title, kw):
    """All meaningful words in kw must appear in title."""
    words = [w for w in kw.lower().split() if len(w) > 2]
    t = title.lower()
    return all(w in t for w in words)


# ── Source 1: Indeed via Anthropic API + Indeed MCP ──────────────────────────
# Requires a valid Anthropic API key with credits.
# Uses the Indeed MCP server so Claude searches Indeed on your behalf.

def scrape_indeed(kw: str, loc: str, api_key: str) -> list:
    jobs = []
    try:
        if not api_key:
            return []

        log.info(f"  [Indeed] kw={kw!r} loc={loc!r}")

        prompt = f"""Search Indeed for "{kw}" jobs in "{loc}" USA.
Return ONLY a JSON array (no markdown) of up to 20 jobs, each with:
{{"title":"","company":"","location":"","salary":"","apply_url":"","description":""}}
Only include jobs located in the United States."""

        r = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "tools": [],
                "mcp_servers": [
                    {"type": "url", "url": "https://mcp.indeed.com/claude/mcp", "name": "indeed"}
                ],
                "messages": [{"role": "user", "content": prompt}],
            },
            timeout=60,
        )

        if r.status_code == 400 and "credit" in r.text:
            log.warning("  [Indeed] No Anthropic credits — add credits at console.anthropic.com/settings/billing")
            return []

        if r.status_code != 200:
            log.error(f"  [Indeed] API error {r.status_code}")
            return []

        text = ""
        for block in r.json().get("content", []):
            if block.get("type") == "text":
                text += block.get("text", "")

        # Extract JSON array from response
        match = re.search(r'\[.*\]', text, re.DOTALL)
        if not match:
            log.warning("  [Indeed] No JSON array in response")
            return []

        items = json.loads(match.group())
        for item in items:
            title   = str(item.get("title",   "")).strip()
            company = str(item.get("company", "")).strip()
            loc_str = str(item.get("location","")).strip()
            url     = str(item.get("apply_url","")).strip()
            salary  = str(item.get("salary",  "")).strip()
            desc    = str(item.get("description","")).strip()[:500]
            if not title or not url:
                continue
            jobs.append({
                "id":          f"indeed_{_uid(url, title)}",
                "title":       title,
                "company":     company,
                "location":    loc_str,
                "salary":      salary,
                "description": desc,
                "apply_url":   url,
                "source":      "indeed",
            })

        log.info(f"  [Indeed] {len(jobs)} jobs")
    except Exception as e:
        log.error(f"  [Indeed] error: {e}")
    return jobs


# ── Source 2: Remotive (US remote jobs, free API) ─────────────────────────────

_REMOTIVE_CAT = {
    "product manager":  "product",
    "program manager":  "product",
    "project manager":  "project-management",
    "product":          "product",
    "engineer":         "software-dev",
    "developer":        "software-dev",
    "devops":           "devops-sysadmin",
    "designer":         "design",
    "marketing":        "marketing",
    "data":             "data",
    "sales":            "sales",
    "qa":               "qa",
    "customer":         "customer-support",
}

# US location keywords — skip jobs that require being in other countries
_NON_US = ["germany","uk","united kingdom","france","canada","australia",
           "netherlands","spain","india","brazil","europe","berlin",
           "london","paris","toronto","sydney","amsterdam","remote - germany"]

def scrape_remotive(kw: str) -> list:
    jobs = []
    try:
        cat = next((v for k, v in _REMOTIVE_CAT.items() if k in kw.lower()), "product")
        log.info(f"  [Remotive] kw={kw!r} cat={cat}")

        r = requests.get(
            "https://remotive.com/api/remote-jobs",
            params={"category": cat, "limit": 100},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get("jobs", [])
        log.info(f"  [Remotive] {len(raw)} raw jobs, filtering...")

        for item in raw:
            title      = item.get("title",                    "").strip()
            company    = item.get("company_name",             "").strip()
            url        = item.get("url",                      "").strip()
            desc       = _strip_html(item.get("description",  ""))[:500]
            salary     = item.get("salary",                   "")
            # candidate_required_location tells us where the candidate must be
            req_loc    = item.get("candidate_required_location", "").lower()

            if not title or not url:
                continue

            # Skip if title doesn't match keyword
            if not _title_matches(title, kw):
                continue

            # Skip if job explicitly requires being in a non-US location
            if req_loc and not any(x in req_loc for x in ["us", "usa", "united states", "worldwide", "anywhere", "remote", ""]):
                if any(x in req_loc for x in _NON_US):
                    continue

            jobs.append({
                "id":          f"remotive_{_uid(url, title)}",
                "title":       title,
                "company":     company,
                "location":    "Remote (US)" if not req_loc else f"Remote ({req_loc.upper()})",
                "salary":      salary,
                "description": desc,
                "apply_url":   url,
                "source":      "remotive",
            })

        log.info(f"  [Remotive] {len(jobs)} US-matching jobs")
    except Exception as e:
        log.error(f"  [Remotive] error: {e}")
    return jobs


# ── Source 3: USAJobs.gov (optional, US federal jobs) ────────────────────────

def scrape_usajobs(kw: str, loc: str = "") -> list:
    jobs = []
    try:
        api_key = os.environ.get("USAJOBS_API_KEY", "")
        email   = os.environ.get("USAJOBS_EMAIL", "jobpilot@example.com")
        if not api_key:
            return []

        log.info(f"  [USAJobs] kw={kw!r}")
        params = {"Keyword": kw, "ResultsPerPage": 25, "WhoMayApply": "All"}
        if loc and loc.lower() not in ("remote","anywhere","united states","us",""):
            params["LocationName"] = loc

        r = requests.get(
            "https://data.usajobs.gov/api/search",
            headers={"Authorization-Key": api_key, "User-Agent": email, "Host": "data.usajobs.gov"},
            params=params, timeout=15,
        )
        r.raise_for_status()

        for item in r.json().get("SearchResult", {}).get("SearchResultItems", []):
            pos     = item.get("MatchedObjectDescriptor", {})
            title   = pos.get("PositionTitle", "").strip()
            company = pos.get("OrganizationName", "").strip()
            locs    = pos.get("PositionLocationDisplay", loc)
            url     = pos.get("PositionURI", "").strip()
            pay     = (pos.get("PositionRemuneration") or [{}])[0]
            salary  = f"${pay.get('MinimumRange','?')}–${pay.get('MaximumRange','?')}" if pay else ""
            desc    = pos.get("UserArea",{}).get("Details",{}).get("JobSummary","")[:500]
            if not title or not url:
                continue
            jobs.append({
                "id":          f"usajobs_{_uid(url, title)}",
                "title":       title,
                "company":     company,
                "location":    locs,
                "salary":      salary,
                "description": desc,
                "apply_url":   url,
                "source":      "usajobs",
            })

        log.info(f"  [USAJobs] {len(jobs)} jobs")
    except Exception as e:
        log.error(f"  [USAJobs] error: {e}")
    return jobs


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_all(kw: str, loc: str, jt: str = "fulltime",
               sources: list = None, anthropic_api_key: str = "") -> list:
    """
    Returns deduplicated list of job dicts.
    Pass anthropic_api_key to enable Indeed source.
    """
    if sources is None:
        sources = ["indeed", "remotive", "usajobs"]

    all_jobs = []
    if "indeed"   in sources and anthropic_api_key:
        all_jobs.extend(scrape_indeed(kw, loc, anthropic_api_key)); time.sleep(1)
    if "remotive" in sources:
        all_jobs.extend(scrape_remotive(kw));                        time.sleep(1)
    if "usajobs"  in sources:
        all_jobs.extend(scrape_usajobs(kw, loc))

    unique = _dedup(all_jobs)
    log.info(f"Total unique '{kw}' US jobs: {len(unique)}")
    return unique


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw",  default="Product Manager")
    ap.add_argument("--loc", default="United States")
    ap.add_argument("--key", default="", help="Anthropic API key for Indeed source")
    args = ap.parse_args()
    results = scrape_all(args.kw, args.loc, anthropic_api_key=args.key)
    print(f"\n{'='*60}\n{len(results)} jobs for '{args.kw}':\n{'='*60}")
    for j in results:
        print(f"  [{j['source']:10}] {j['title']} @ {j['company']} — {j['location']}")
