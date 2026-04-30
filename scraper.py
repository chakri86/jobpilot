#!/usr/bin/env python3
"""
JobPilot Scraper
Uses Anthropic API + Indeed MCP — the same connector that works in Claude chat.
Requires Anthropic API key with credits (add at console.anthropic.com/settings/billing)
"""
import os, re, json, time, hashlib, logging, requests

LOG = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs", "scraper.log")
os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(level=logging.INFO,
    format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler()])
log = logging.getLogger("scraper")

def _uid(url, title):
    return hashlib.md5(f"{url}{title}".encode()).hexdigest()[:16]

def _dedup(jobs):
    seen, out = set(), []
    for j in jobs:
        key = (j["title"].lower().strip(), j["company"].lower().strip())
        if key not in seen and j["title"].strip():
            seen.add(key); out.append(j)
    return out


def scrape_indeed_mcp(kw: str, loc: str, api_key: str) -> list:
    """
    Call Anthropic API with the Indeed MCP server.
    Claude uses Indeed to search, returns structured job list.
    This is the same mechanism as the Claude chat Indeed connector.
    """
    if not api_key:
        log.warning("No Anthropic API key — cannot search Indeed")
        return []

    log.info(f"  [Indeed] searching '{kw}' in '{loc}'...")

    try:
        resp = requests.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "anthropic-beta": "mcp-client-2025-04-04",
                "Content-Type": "application/json",
            },
            json={
                "model": "claude-sonnet-4-20250514",
                "max_tokens": 4096,
                "mcp_servers": [{
                    "type": "url",
                    "url": "https://mcp.indeed.com/claude/mcp",
                    "name": "indeed",
                }],
                "messages": [{
                    "role": "user",
                    "content": (
                        f'Search Indeed for "{kw}" jobs in "{loc}", United States. '
                        f'Return ONLY a JSON array, no markdown, no explanation. '
                        f'Each item: {{"title":"","company":"","location":"","salary":"","apply_url":"","description":""}}. '
                        f'Only US jobs. Up to 20 results.'
                    )
                }],
            },
            timeout=60,
        )

        if resp.status_code == 400 and "credit" in resp.text.lower():
            log.error("  [Indeed] ✗ No Anthropic credits. Add credits: https://console.anthropic.com/settings/billing")
            return []
        if resp.status_code != 200:
            log.error(f"  [Indeed] ✗ API error {resp.status_code}: {resp.text[:200]}")
            return []

        # Extract text from all content blocks
        text = " ".join(
            b.get("text", "") for b in resp.json().get("content", [])
            if b.get("type") == "text"
        )

        # Parse JSON array from response
        match = re.search(r'\[.*?\]', text, re.DOTALL)
        if not match:
            log.warning("  [Indeed] No JSON array in response")
            return []

        items = json.loads(match.group())
        jobs = []
        for item in items:
            title   = str(item.get("title",       "")).strip()
            company = str(item.get("company",     "")).strip()
            loc_str = str(item.get("location",    loc)).strip()
            salary  = str(item.get("salary",      "")).strip()
            url     = str(item.get("apply_url",   "")).strip()
            desc    = str(item.get("description", "")).strip()[:500]
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

        log.info(f"  [Indeed] ✓ {len(jobs)} jobs found")
        return jobs

    except Exception as e:
        log.error(f"  [Indeed] ✗ Error: {e}")
        return []


def scrape_remotive(kw: str) -> list:
    """Remotive free API — backup source for remote US jobs."""
    jobs = []
    cat_map = {
        "product manager": "product", "program manager": "product",
        "project manager": "project-management", "product": "product",
        "engineer": "software-dev", "developer": "software-dev",
        "designer": "design", "marketing": "marketing", "data": "data",
    }
    try:
        cat = next((v for k, v in cat_map.items() if k in kw.lower()), "product")
        log.info(f"  [Remotive] searching '{kw}'...")
        r = requests.get("https://remotive.com/api/remote-jobs",
                         params={"category": cat, "limit": 100}, timeout=15)
        r.raise_for_status()

        kw_words = [w for w in kw.lower().split() if len(w) > 2]
        non_us   = ["germany","uk ","united kingdom","france","canada","australia",
                    "netherlands","europe","berlin","london","paris","toronto"]

        for item in r.json().get("jobs", []):
            title   = item.get("title",        "").strip()
            company = item.get("company_name", "").strip()
            url     = item.get("url",          "").strip()
            desc    = re.sub(r"<[^>]+>", " ", item.get("description",""))[:500]
            salary  = item.get("salary",       "")
            req_loc = item.get("candidate_required_location", "").lower()

            if not title or not url: continue
            if not all(w in title.lower() for w in kw_words): continue
            if any(x in req_loc for x in non_us): continue

            jobs.append({
                "id": f"remotive_{_uid(url,title)}", "title": title,
                "company": company, "location": "Remote (US)",
                "salary": salary, "description": desc,
                "apply_url": url, "source": "remotive",
            })

        log.info(f"  [Remotive] ✓ {len(jobs)} matching jobs")
    except Exception as e:
        log.error(f"  [Remotive] ✗ Error: {e}")
    return jobs


def scrape_all(kw: str, loc: str, jt: str = "fulltime",
               anthropic_api_key: str = "") -> list:
    all_jobs = []
    # Primary: Indeed via MCP (needs API credits)
    if anthropic_api_key:
        all_jobs.extend(scrape_indeed_mcp(kw, loc, anthropic_api_key))
        time.sleep(2)
    # Backup: Remotive
    all_jobs.extend(scrape_remotive(kw))
    unique = _dedup(all_jobs)
    log.info(f"  Total unique '{kw}' jobs: {len(unique)}")
    return unique
