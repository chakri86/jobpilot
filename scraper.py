#!/usr/bin/env python3
"""
JobPilot Scraper
================
Sources confirmed working on Raspberry Pi 5 ARM64:
  1. Remotive API   — free, no key, remote/US jobs
  2. Arbeitnow API  — free, no key, US/remote jobs
  3. USAJobs.gov    — optional, set USAJOBS_API_KEY env var

jobspy was REMOVED — its tls-client-arm64.so binary is broken on Pi 5.
"""

import os, sys, hashlib, logging, requests, time, re
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
    """Return True if every meaningful word in kw appears in title."""
    words = [w for w in kw.lower().split() if len(w) > 2]
    t = title.lower()
    return all(w in t for w in words)


# ── Source 1: Remotive ────────────────────────────────────────────────────────

_REMOTIVE_CAT = {
    "product manager": "product",
    "product": "product",
    "program manager": "product",
    "project manager": "project-management",
    "engineer": "software-dev",
    "developer": "software-dev",
    "devops": "devops-sysadmin",
    "designer": "design",
    "marketing": "marketing",
    "data": "data",
    "sales": "sales",
    "qa": "qa",
    "customer": "customer-support",
}

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
        log.info(f"  [Remotive] {len(raw)} raw jobs in category, filtering for '{kw}'...")

        for item in raw:
            title   = item.get("title", "").strip()
            company = item.get("company_name", "").strip()
            url     = item.get("url", "").strip()
            desc    = _strip_html(item.get("description", ""))[:500]
            salary  = item.get("salary", "")
            if not title or not url:
                continue
            if not _title_matches(title, kw):
                continue
            jobs.append({
                "id":          f"remotive_{_uid(url, title)}",
                "title":       title,
                "company":     company,
                "location":    "Remote (US)",
                "salary":      salary,
                "description": desc,
                "apply_url":   url,
                "source":      "remotive",
            })

        log.info(f"  [Remotive] {len(jobs)} matching jobs")
    except Exception as e:
        log.error(f"  [Remotive] error: {e}")
    return jobs


# ── Source 2: Arbeitnow ───────────────────────────────────────────────────────

def scrape_arbeitnow(kw: str) -> list:
    jobs = []
    try:
        log.info(f"  [Arbeitnow] kw={kw!r}")
        r = requests.get(
            "https://www.arbeitnow.com/api/job-board-api",
            params={"page": 1},
            timeout=15,
        )
        r.raise_for_status()
        raw = r.json().get("data", [])
        log.info(f"  [Arbeitnow] {len(raw)} raw jobs, filtering for '{kw}'...")

        for item in raw:
            title   = item.get("title", "").strip()
            company = item.get("company_name", "").strip()
            loc     = item.get("location", "Remote")
            url     = item.get("url", "").strip()
            desc    = _strip_html(item.get("description", ""))[:500]
            salary  = str(item.get("salary", ""))
            if not title or not url:
                continue
            if not _title_matches(title, kw):
                continue
            jobs.append({
                "id":          f"arbeitnow_{_uid(url, title)}",
                "title":       title,
                "company":     company,
                "location":    loc,
                "salary":      salary,
                "description": desc,
                "apply_url":   url,
                "source":      "arbeitnow",
            })

        log.info(f"  [Arbeitnow] {len(jobs)} matching jobs")
    except Exception as e:
        log.error(f"  [Arbeitnow] error: {e}")
    return jobs


# ── Source 3: USAJobs.gov ─────────────────────────────────────────────────────

def scrape_usajobs(kw: str, loc: str = "") -> list:
    jobs = []
    try:
        api_key = os.environ.get("USAJOBS_API_KEY", "")
        email   = os.environ.get("USAJOBS_EMAIL", "jobpilot@example.com")
        if not api_key:
            return []
        log.info(f"  [USAJobs] kw={kw!r}")
        params = {"Keyword": kw, "ResultsPerPage": 25, "WhoMayApply": "All"}
        if loc and loc.lower() not in ("remote", "anywhere", "united states", "us", ""):
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
            desc    = pos.get("UserArea", {}).get("Details", {}).get("JobSummary", "")[:500]
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

def scrape_all(kw: str, loc: str, jt: str = "fulltime", sources: list = None) -> list:
    if sources is None:
        sources = ["remotive", "arbeitnow", "usajobs"]
    all_jobs = []
    if "remotive"  in sources: all_jobs.extend(scrape_remotive(kw));       time.sleep(1)
    if "arbeitnow" in sources: all_jobs.extend(scrape_arbeitnow(kw));      time.sleep(1)
    if "usajobs"   in sources: all_jobs.extend(scrape_usajobs(kw, loc))
    unique = _dedup(all_jobs)
    log.info(f"Total unique '{kw}' jobs: {len(unique)}")
    return unique


if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("--kw",  default="Product Manager")
    ap.add_argument("--loc", default="United States")
    args = ap.parse_args()
    results = scrape_all(args.kw, args.loc)
    print(f"\n{'='*60}\n{len(results)} jobs for '{args.kw}':\n{'='*60}")
    for j in results:
        print(f"  [{j['source']:10}] {j['title']} @ {j['company']}")
