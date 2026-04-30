#!/usr/bin/env python3
"""
JobPilot Scraper
================
Real job sources that actually work:
  1. python-jobspy  → scrapes Indeed, LinkedIn, ZipRecruiter, Glassdoor
                      (handles JS rendering, bot-detection, correct selectors)
  2. Remotive API   → free JSON API, no key, great remote/US roles
  3. Arbeitnow API  → free JSON API, no key, many US/remote tech roles
  4. USAJobs.gov    → official federal API (opt-in via env var)

WHY the old Copilot code returned 0 jobs
-----------------------------------------
• Indeed      → blocks HTML scrapers since 2022; CSS classes are JS-rendered
• LinkedIn RSS → feed deprecated and removed in 2021
• Google Jobs → actively blocks crawlers; ld+json not present on search pages
• ZipRecruiter → wrong CSS class names; also JS-rendered
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

# ── Helpers ───────────────────────────────────────────────────────────────────

def _uid(*parts):
    return hashlib.md5("".join(str(p) for p in parts).encode()).hexdigest()[:16]

def _strip_html(text):
    return re.sub(r"<[^>]+>", " ", text or "").strip()

def _dedup(jobs):
    """Deduplicate by lowercase (title, company) pair."""
    seen, out = set(), []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"].strip():
            seen.add(key)
            out.append(j)
    return out


# ── Source 1: python-jobspy ───────────────────────────────────────────────────
# pip install python-jobspy pandas
# Internally scrapes Indeed, LinkedIn, ZipRecruiter, Glassdoor with correct
# selectors and rotating headers — maintained open-source library.

def scrape_jobspy(kw: str, loc: str, jt: str = "fulltime", n: int = 25) -> list:
    jobs = []
    try:
        from jobspy import scrape_jobs

        # jobspy wants "United States" for a national/remote search
        search_loc = "United States" if loc.lower() in ("remote", "anywhere", "") else loc

        jt_map = {
            "fulltime": "fulltime", "parttime": "parttime",
            "contract": "contract", "temporary": "temporary", "any": "fulltime",
        }

        log.info(f"  [jobspy] '{kw}' in '{search_loc}' ({jt})")
        df = scrape_jobs(
            site_name=["indeed", "linkedin", "zip_recruiter", "glassdoor"],
            search_term=kw,
            location=search_loc,
            results_wanted=n,
            hours_old=168,          # 1 week
            country_indeed="USA",
            job_type=jt_map.get(jt.lower(), "fulltime"),
            linkedin_fetch_description=False,   # faster; descriptions come from other sources
            verbose=0,
        )

        if df is None or len(df) == 0:
            log.warning("  [jobspy] returned 0 results (network or rate-limit)")
            return []

        for _, row in df.iterrows():
            try:
                title    = str(row.get("title",    "") or "").strip()
                company  = str(row.get("company",  "") or "").strip()
                location = str(row.get("location", "") or loc).strip()
                url      = str(row.get("job_url",  "") or "").strip()
                source   = str(row.get("site",     "jobspy"))
                desc     = _strip_html(str(row.get("description", "") or ""))[:600]

                # Build salary string
                min_s = row.get("min_amount"); max_s = row.get("max_amount")
                cur   = row.get("currency", "USD") or "USD"
                salary = ""
                if min_s and max_s:
                    salary = f"${int(min_s):,}–${int(max_s):,} {cur}"
                elif min_s:
                    salary = f"${int(min_s):,}+ {cur}"

                if not title or not url:
                    continue

                jobs.append({"id": f"{source}_{_uid(url, title)}", "title": title,
                    "company": company, "location": location, "salary": salary,
                    "description": desc, "apply_url": url, "source": source})
            except Exception as e:
                log.debug(f"    row parse error: {e}")

        log.info(f"  [jobspy] {len(jobs)} jobs")
    except ImportError:
        log.warning("  [jobspy] not installed — run: pip install python-jobspy pandas")
    except Exception as e:
        log.error(f"  [jobspy] error: {e}")
    return jobs


# ── Source 2: Remotive (free remote jobs API) ─────────────────────────────────
# https://remotive.com/api — no key, free forever, great for remote US roles

_REMOTIVE_CAT = {
    "product manager": "product", "product": "product", "program manager": "product",
    "engineer": "software-dev", "developer": "software-dev", "devops": "devops-sysadmin",
    "designer": "design", "marketing": "marketing", "data": "data",
    "finance": "finance-legal", "sales": "sales", "qa": "qa",
    "customer": "customer-support",
}

def scrape_remotive(kw: str) -> list:
    jobs = []
    try:
        cat = next((v for k, v in _REMOTIVE_CAT.items() if k in kw.lower()), "product")
        log.info(f"  [Remotive] cat={cat!r} kw={kw!r}")
        r = requests.get("https://remotive.com/api/remote-jobs",
                         params={"category": cat, "limit": 30, "search": kw}, timeout=15)
        r.raise_for_status()
        # Keyword words that must appear in title (e.g. "product manager" → ["product","manager"])
        kw_words = [w for w in kw.lower().split() if len(w) > 2]

        for item in r.json().get("jobs", []):
            title   = item.get("title",        "").strip()
            company = item.get("company_name", "").strip()
            url     = item.get("url",          "").strip()
            desc    = _strip_html(item.get("description", ""))[:500]
            salary  = item.get("salary", "")
            if not title or not url:
                continue
            # Require ALL keyword words to appear in title (strict match)
            title_lower = title.lower()
            if not all(w in title_lower for w in kw_words):
                continue
            jobs.append({"id": f"remotive_{_uid(url, title)}", "title": title,
                "company": company, "location": "Remote (US)", "salary": salary,
                "description": desc, "apply_url": url, "source": "remotive"})
        log.info(f"  [Remotive] {len(jobs)} jobs")
    except Exception as e:
        log.error(f"  [Remotive] error: {e}")
    return jobs


# ── Source 3: Arbeitnow (free global job board API) ───────────────────────────
# https://www.arbeitnow.com/api — no key, many US/remote roles

def scrape_arbeitnow(kw: str) -> list:
    jobs = []
    try:
        log.info(f"  [Arbeitnow] kw={kw!r}")
        r = requests.get("https://www.arbeitnow.com/api/job-board-api",
                         params={"page": 1, "search": kw}, timeout=15)
        r.raise_for_status()
        for item in r.json().get("data", [])[:30]:
            title   = item.get("title",        "").strip()
            company = item.get("company_name", "").strip()
            loc_str = item.get("location",     "Remote")
            url     = item.get("url",          "").strip()
            desc    = _strip_html(item.get("description", ""))[:500]
            salary  = str(item.get("salary", ""))
            if not title or not url:
                continue
            # Only keep listings that mention the keyword
            if kw.lower() not in title.lower() and kw.lower() not in desc.lower()[:200]:
                continue
            jobs.append({"id": f"arbeitnow_{_uid(url, title)}", "title": title,
                "company": company, "location": loc_str, "salary": salary,
                "description": desc, "apply_url": url, "source": "arbeitnow"})
        log.info(f"  [Arbeitnow] {len(jobs)} jobs")
    except Exception as e:
        log.error(f"  [Arbeitnow] error: {e}")
    return jobs


# ── Source 4: USAJobs.gov (optional, requires free API key) ──────────────────
# Register free at https://developer.usajobs.gov/
# Set env vars: USAJOBS_API_KEY and USAJOBS_EMAIL

def scrape_usajobs(kw: str, loc: str = "") -> list:
    jobs = []
    try:
        api_key = os.environ.get("USAJOBS_API_KEY", "")
        email   = os.environ.get("USAJOBS_EMAIL", "jobpilot@example.com")
        if not api_key:
            return []   # silently skip if no key configured

        log.info(f"  [USAJobs] kw={kw!r}")
        params = {"Keyword": kw, "ResultsPerPage": 25, "WhoMayApply": "All"}
        if loc and loc.lower() not in ("remote", "anywhere", "united states", "us", ""):
            params["LocationName"] = loc

        r = requests.get(
            "https://data.usajobs.gov/api/search",
            headers={"Authorization-Key": api_key, "User-Agent": email, "Host": "data.usajobs.gov"},
            params=params, timeout=15)
        r.raise_for_status()

        for item in r.json().get("SearchResult", {}).get("SearchResultItems", []):
            pos     = item.get("MatchedObjectDescriptor", {})
            title   = pos.get("PositionTitle",           "").strip()
            company = pos.get("OrganizationName",        "").strip()
            locs    = pos.get("PositionLocationDisplay", loc)
            url     = pos.get("PositionURI",             "").strip()
            pay     = (pos.get("PositionRemuneration") or [{}])[0]
            salary  = f"${pay.get('MinimumRange','?')}–${pay.get('MaximumRange','?')}" if pay else ""
            desc    = pos.get("UserArea", {}).get("Details", {}).get("JobSummary", "")[:500]
            if not title or not url:
                continue
            jobs.append({"id": f"usajobs_{_uid(url, title)}", "title": title,
                "company": company, "location": locs, "salary": salary,
                "description": desc, "apply_url": url, "source": "usajobs"})

        log.info(f"  [USAJobs] {len(jobs)} jobs")
    except Exception as e:
        log.error(f"  [USAJobs] error: {e}")
    return jobs


# ── Public API ────────────────────────────────────────────────────────────────

def scrape_all(kw: str, loc: str, jt: str = "fulltime", sources: list = None) -> list:
    """
    Scrape all enabled sources and return a deduplicated list of job dicts.
    Each dict has: id, title, company, location, salary, description, apply_url, source
    """
    if sources is None:
        sources = ["jobspy", "remotive", "arbeitnow", "usajobs"]

    all_jobs = []
    if "jobspy"    in sources: all_jobs.extend(scrape_jobspy(kw, loc, jt));  time.sleep(1)
    if "remotive"  in sources: all_jobs.extend(scrape_remotive(kw));          time.sleep(1)
    if "arbeitnow" in sources: all_jobs.extend(scrape_arbeitnow(kw));         time.sleep(1)
    if "usajobs"   in sources: all_jobs.extend(scrape_usajobs(kw, loc))

    unique = _dedup(all_jobs)
    log.info(f"Total unique jobs for '{kw}' in '{loc}': {len(unique)}")
    return unique


# ── CLI quick-test ────────────────────────────────────────────────────────────
if __name__ == "__main__":
    import argparse
    ap = argparse.ArgumentParser(description="JobPilot scraper CLI test")
    ap.add_argument("--kw",  default="Product Manager", help="job keyword")
    ap.add_argument("--loc", default="United States",   help="location")
    ap.add_argument("--jt",  default="fulltime",        help="job type")
    ap.add_argument("--n",   type=int, default=20,      help="results per source")
    args = ap.parse_args()

    results = scrape_all(args.kw, args.loc, args.jt)
    print(f"\n{'='*65}")
    print(f"  {len(results)} jobs for '{args.kw}' in '{args.loc}'")
    print(f"{'='*65}")
    sources_seen = {}
    for j in results:
        src = j["source"]
        sources_seen[src] = sources_seen.get(src, 0) + 1
        print(f"  [{src:12}] {j['title']} @ {j['company']}")
        if j.get("salary"):
            print(f"               💰 {j['salary']}")
    print(f"\nBy source: {sources_seen}")
