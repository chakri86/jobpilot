#!/usr/bin/env python3
"""
JobPilot Scraper - Multi-source job fetcher
Supports: Indeed (API+Web), LinkedIn RSS, Google Jobs, ZipRecruiter
"""

import os, sys, sqlite3, json, time, hashlib, logging, requests, re
from datetime import datetime
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
LOG = os.path.join(BASE, "logs", "scraper.log")

os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("scraper")

# Headers to avoid blocking
UA = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    "Accept-Language": "en-US,en;q=0.9",
    "Accept-Encoding": "gzip, deflate",
    "DNT": "1",
    "Connection": "keep-alive",
    "Upgrade-Insecure-Requests": "1"
}

# ═══════════════════════════════════════════════
# INDEED (Direct search - no API key needed)
# ═══════════════════════════════════════════════
def scrape_indeed_web(kw, loc, jt="fulltime"):
    """Scrape Indeed using modern selectors"""
    jobs = []
    try:
        # Indeed's newer job search URL structure
        url = "https://indeed.com/jobs"
        params = {
            "q": kw,
            "l": loc,
            "sort": "date",
            "from": "indeed",
            "vjk": ""
        }
        
        log.info(f"  🔍 Scraping Indeed: {kw} in {loc}")
        r = requests.get(url, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Look for job cards - multiple possible selectors for resilience
        job_cards = soup.find_all("div", class_="job_seen_beacon")
        if not job_cards:
            job_cards = soup.find_all("div", attrs={"data-tnip-id": True})
        if not job_cards:
            job_cards = soup.find_all("ul", class_="jobsearch-ResultsList")[0].find_all("li") if soup.find_all("ul", class_="jobsearch-ResultsList") else []
        
        for card in job_cards[:20]:  # Limit to first 20 per request
            try:
                # Job ID
                jid = card.get("data-jk")
                if not jid:
                    link = card.find("a", class_="jcs-JobTitle")
                    if link and link.get("href"):
                        jid = link["href"].split("jk=")[-1].split("&")[0] if "jk=" in link["href"] else hashlib.md5(str(link["href"]).encode()).hexdigest()[:16]
                if not jid:
                    jid = hashlib.md5((str(card))[:200].encode()).hexdigest()[:16]
                
                # Title
                title_elem = card.find("h2", class_="jobTitle") or card.find("a", class_="jcs-JobTitle")
                title = title_elem.get_text(strip=True) if title_elem else "Unknown"
                
                # Company
                company_elem = card.find("span", class_="companyName") or card.find("span", attrs={"data-testid": "company-name"})
                company = company_elem.get_text(strip=True) if company_elem else ""
                
                # Location
                loc_elem = card.find("div", class_="companyLocation") or card.find("div", attrs={"data-testid": "text-location"})
                location = loc_elem.get_text(strip=True) if loc_elem else loc
                
                # Salary
                salary_elem = card.find("div", class_="salary-snippet-container") or card.find("span", class_="salary-snippet")
                salary = salary_elem.get_text(strip=True) if salary_elem else ""
                
                # Description/Summary
                summary_elem = card.find("ul", class_="jobsearch-JobSnippetList") or card.find("div", class_="job-snippet")
                description = summary_elem.get_text(strip=True) if summary_elem else ""
                
                # Apply URL
                job_link = card.find("a", class_="jcs-JobTitle") or card.find("a", attrs={"data-tnip-id": True})
                if job_link and "href" in job_link.attrs:
                    apply_url = job_link["href"]
                    if not apply_url.startswith("http"):
                        apply_url = f"https://indeed.com{apply_url}"
                else:
                    apply_url = f"https://indeed.com/viewjob?jk={jid}" if jid else ""
                
                if title and company:
                    job_obj = {
                        "id": f"indeed_{jid}",
                        "title": title,
                        "company": company,
                        "location": location,
                        "salary": salary,
                        "description": description[:500],
                        "apply_url": apply_url,
                        "source": "indeed"
                    }
                    jobs.append(job_obj)
                    log.debug(f"    ✓ {title} @ {company}")
            except Exception as e:
                log.debug(f"    Error parsing card: {e}")
                continue
        
        log.info(f"  ✓ Indeed: {len(jobs)} jobs found")
    except requests.exceptions.Timeout:
        log.error(f"  ✗ Indeed: Request timeout")
    except Exception as e:
        log.error(f"  ✗ Indeed error: {e}")
    
    return jobs

# ═══════════════════════════════════════════════
# LINKEDIN RSS FEED
# ═══════════════════════════════════════════════
def scrape_linkedin_rss(kw, loc):
    """Fetch LinkedIn jobs via RSS feed (no auth needed)"""
    jobs = []
    try:
        log.info(f"  🔍 Scraping LinkedIn RSS: {kw} in {loc}")
        
        # LinkedIn RSS feed URL
        kw_encoded = kw.replace(" ", "%20")
        loc_encoded = loc.replace(" ", "%20").replace(",", "%2C")
        
        # Use LinkedIn's RSS feed
        url = f"https://www.linkedin.com/jobs/search/feed/?keywords={kw_encoded}&location={loc_encoded}&sortBy=DD"
        
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        
        import xml.etree.ElementTree as ET
        try:
            root = ET.fromstring(r.text)
            
            for item in root.findall(".//item"):
                try:
                    title_elem = item.find("title")
                    link_elem = item.find("link")
                    
                    if title_elem is None or link_elem is None:
                        continue
                    
                    title = (title_elem.text or "").strip()
                    link = (link_elem.text or "").strip()
                    
                    # LinkedIn titles often have "Company Name" appended
                    company = ""
                    if " at " in title:
                        title, company = title.rsplit(" at ", 1)
                    
                    description_elem = item.find("description")
                    description = (description_elem.text or "")[:500] if description_elem is not None else ""
                    
                    # Generate unique ID
                    job_id = f"li_{hashlib.md5((link + title).encode()).hexdigest()[:16]}"
                    
                    if title and link:
                        job_obj = {
                            "id": job_id,
                            "title": title.strip(),
                            "company": company.strip(),
                            "location": loc,
                            "salary": "",
                            "description": description,
                            "apply_url": link,
                            "source": "linkedin"
                        }
                        jobs.append(job_obj)
                        log.debug(f"    ✓ {title} @ {company}")
                except Exception as e:
                    log.debug(f"    Error parsing LinkedIn item: {e}")
                    continue
        except ET.ParseError:
            log.warning(f"  ⚠ LinkedIn RSS parse error (may not be XML)")
            # Try HTML fallback
            pass
        
        log.info(f"  ✓ LinkedIn: {len(jobs)} jobs found")
    except requests.exceptions.Timeout:
        log.error(f"  ✗ LinkedIn: Request timeout")
    except Exception as e:
        log.error(f"  ✗ LinkedIn error: {e}")
    
    return jobs

# ═══════════════════════════════════════════════
# GOOGLE JOBS (via Indeed partnership data)
# ═══════════════════════════════════════════════
def scrape_google_jobs(kw, loc):
    """Scrape Google Jobs results"""
    jobs = []
    try:
        log.info(f"  🔍 Scraping Google Jobs: {kw} in {loc}")
        
        # Google Jobs search
        url = "https://www.google.com/search"
        params = {
            "q": f"{kw} jobs in {loc}",
            "ibp": "htl;jobs"
        }
        
        r = requests.get(url, params=params, headers=UA, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # Google embeds job data as JSON
        scripts = soup.find_all("script", {"type": "application/ld+json"})
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, dict) and data.get("@type") == "JobPosting":
                    job_obj = {
                        "id": f"gj_{hashlib.md5((data.get('url', '') + data.get('title', '')).encode()).hexdigest()[:16]}",
                        "title": data.get("title", ""),
                        "company": data.get("hiringOrganization", {}).get("name", "") if isinstance(data.get("hiringOrganization"), dict) else "",
                        "location": data.get("jobLocation", {}).get("address", {}).get("addressLocality", "") if isinstance(data.get("jobLocation"), dict) else loc,
                        "salary": "",
                        "description": data.get("description", "")[:500],
                        "apply_url": data.get("url", ""),
                        "source": "google_jobs"
                    }
                    if job_obj["title"] and job_obj["apply_url"]:
                        jobs.append(job_obj)
                        log.debug(f"    ✓ {job_obj['title']} @ {job_obj['company']}")
            except json.JSONDecodeError:
                pass
        
        log.info(f"  ✓ Google Jobs: {len(jobs)} jobs found")
    except Exception as e:
        log.error(f"  ✗ Google Jobs error: {e}")
    
    return jobs

# ═══════════════════════════════════════════════
# ZIPRECRUITER (Public job listings)
# ═══════════════════════════════════════════════
def scrape_ziprecruiter(kw, loc):
    """Scrape ZipRecruiter job listings"""
    jobs = []
    try:
        log.info(f"  🔍 Scraping ZipRecruiter: {kw} in {loc}")
        
        # ZipRecruiter search URL
        kw_encoded = kw.replace(" ", "+")
        loc_encoded = loc.replace(" ", "+")
        
        url = f"https://www.ziprecruiter.com/Jobs/{kw_encoded}/in-{loc_encoded}"
        
        r = requests.get(url, headers=UA, timeout=15)
        r.raise_for_status()
        
        soup = BeautifulSoup(r.text, "html.parser")
        
        # ZipRecruiter job listings
        job_cards = soup.find_all("article", class_="job_result")
        
        for card in job_cards[:20]:
            try:
                # Job ID
                card_id = card.get("data-jobid") or card.get("id") or ""
                
                # Title
                title_elem = card.find("a", class_="job_link") or card.find("h2")
                title = title_elem.get_text(strip=True) if title_elem else ""
                
                # Company
                company_elem = card.find("a", class_="t_emdark")
                company = company_elem.get_text(strip=True) if company_elem else ""
                
                # Location
                loc_elem = card.find("div", class_="job_location")
                location = loc_elem.get_text(strip=True) if loc_elem else loc
                
                # Description
                desc_elem = card.find("div", class_="job_snippet")
                description = desc_elem.get_text(strip=True) if desc_elem else ""
                
                # URL
                link_elem = card.find("a", class_="job_link")
                apply_url = link_elem["href"] if link_elem and "href" in link_elem.attrs else ""
                if apply_url and not apply_url.startswith("http"):
                    apply_url = f"https://www.ziprecruiter.com{apply_url}"
                
                if title and apply_url:
                    job_obj = {
                        "id": f"zr_{card_id or hashlib.md5((title + apply_url).encode()).hexdigest()[:16]}",
                        "title": title,
                        "company": company,
                        "location": location,
                        "salary": "",
                        "description": description[:500],
                        "apply_url": apply_url,
                        "source": "ziprecruiter"
                    }
                    jobs.append(job_obj)
                    log.debug(f"    ✓ {title} @ {company}")
            except Exception as e:
                log.debug(f"    Error parsing ZipRecruiter card: {e}")
                continue
        
        log.info(f"  ✓ ZipRecruiter: {len(jobs)} jobs found")
    except requests.exceptions.Timeout:
        log.error(f"  ✗ ZipRecruiter: Request timeout")
    except Exception as e:
        log.error(f"  ✗ ZipRecruiter error: {e}")
    
    return jobs

# ═══════════════════════════════════════════════
# MAIN EXPORT
# ═══════════════════════════════════════════════
def scrape_all(kw, loc, sources=["indeed", "linkedin", "google_jobs", "ziprecruiter"]):
    """Scrape all enabled sources for a keyword+location"""
    all_jobs = []
    
    if "indeed" in sources:
        all_jobs.extend(scrape_indeed_web(kw, loc))
    
    if "linkedin" in sources:
        all_jobs.extend(scrape_linkedin_rss(kw, loc))
    
    if "google_jobs" in sources:
        all_jobs.extend(scrape_google_jobs(kw, loc))
    
    if "ziprecruiter" in sources:
        all_jobs.extend(scrape_ziprecruiter(kw, loc))
    
    # Deduplicate by title+company
    seen = {}
    unique = []
    for job in all_jobs:
        key = (job["title"].lower(), job["company"].lower())
        if key not in seen:
            seen[key] = True
            unique.append(job)
    
    return unique

if __name__ == "__main__":
    # Test scraper
    test_jobs = scrape_all("Product Manager", "Richardson, TX")
    print(f"\nFound {len(test_jobs)} jobs:")
    for j in test_jobs[:5]:
        print(f"  - {j['title']} @ {j['company']} ({j['source']})")
