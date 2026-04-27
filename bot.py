#!/usr/bin/env python3
"""
JobPilot Bot - Searches, scores, and notifies for all active profiles.
Reads config from the database (set up via GUI).
"""

import os, sys, sqlite3, json, time, hashlib, logging, re, smtplib, requests
import xml.etree.ElementTree as ET
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from bs4 import BeautifulSoup

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "jobs.db")
LOG = os.path.join(BASE, "logs", "bot.log")

os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("bot")

UA = {"User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/120.0.0.0 Safari/537.36"}

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

# ── Scraper ──
def scrape_indeed(kw, loc, jt=""):
    jobs = []
    try:
        p = {"q": kw, "l": loc, "sort": "date", "fromage": "1"}
        if jt: p["jt"] = jt
        r = requests.get("https://www.indeed.com/jobs", params=p, headers=UA, timeout=30)
        if r.status_code == 200:
            soup = BeautifulSoup(r.text, "html.parser")
            for card in (soup.find_all("div", class_="job_seen_beacon") or soup.find_all("div", {"data-jk": True})):
                try:
                    jk = card.get("data-jk", "")
                    if not jk:
                        a = card.find("a", {"data-jk": True})
                        jk = a.get("data-jk", "") if a else ""
                    if not jk:
                        h = card.find("h2")
                        jk = hashlib.md5(h.get_text(strip=True).encode()).hexdigest()[:16] if h else None
                    if not jk: continue
                    title = (card.find("h2") or card.find("a", class_="jcs-JobTitle"))
                    co = card.find("span", {"data-testid": "company-name"}) or card.find("span", class_="companyName")
                    lo = card.find("div", {"data-testid": "text-location"}) or card.find("div", class_="companyLocation")
                    sal = card.find("div", class_="salary-snippet-container")
                    sn = card.find("div", class_="job-snippet") or card.find("ul", style=True)
                    jobs.append({"id": f"indeed_{jk}", "title": title.get_text(strip=True) if title else "?",
                        "company": co.get_text(strip=True) if co else "", "location": lo.get_text(strip=True) if lo else "",
                        "salary": sal.get_text(strip=True) if sal else "", "description": sn.get_text(strip=True) if sn else "",
                        "apply_url": f"https://www.indeed.com/viewjob?jk={jk}", "source": "indeed"})
                except: pass
    except Exception as e: log.error(f"Indeed: {e}")
    return jobs

def scrape_linkedin(kw, loc):
    jobs = []
    try:
        url = f"https://www.linkedin.com/jobs/search/feed/?keywords={kw.replace(' ','%20')}&location={loc.replace(' ','%20')}&sortBy=DD"
        r = requests.get(url, headers=UA, timeout=30)
        if r.status_code == 200:
            root = ET.fromstring(r.text)
            for item in root.findall(".//item"):
                t, l = item.find("title"), item.find("link")
                if t is not None and l is not None:
                    tt, ll = t.text or "", l.text or ""
                    co = ""
                    if " at " in tt: tt, co = tt.rsplit(" at ", 1)
                    d = item.find("description")
                    jobs.append({"id": f"li_{hashlib.md5(ll.encode()).hexdigest()[:16]}", "title": tt.strip(),
                        "company": co.strip(), "location": loc, "salary": "",
                        "description": (d.text or "")[:500] if d is not None else "", "apply_url": ll, "source": "linkedin"})
    except: pass
    return jobs

# ── AI Scorer ──
def score_job(api_key, resume, skills, job):
    try:
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={"Content-Type": "application/json", "x-api-key": api_key, "anthropic-version": "2023-06-01"},
            json={"model": "claude-sonnet-4-20250514", "max_tokens": 512,
                "messages": [{"role": "user", "content": f"Score job match 0-100.\nRESUME: {resume[:2000]}\nSKILLS: {skills}\nJOB: {job['title']} at {job['company']}: {job['description'][:500]}\nJSON only: {{\"score\":N,\"reasons\":[\"r1\"],\"missing\":[\"m1\"],\"tip\":\"t\"}}"}]},
            timeout=60)
        if r.status_code == 200:
            txt = r.json()["content"][0]["text"].strip().replace("```json","").replace("```","").strip()
            return json.loads(txt)
        elif r.status_code == 429:
            time.sleep(30); return score_job(api_key, resume, skills, job)
    except Exception as e: log.error(f"Score error: {e}")
    return None

# ── Notifier ──
def notify(profile, job):
    msg = f"🎯 Match: {job['match_score']}/100\n{job['title']}\n{job['company']} · {job['location']}\n{job.get('match_reasons','')}\nApply: {job.get('apply_url','')}"
    subj = f"⚡ JobPilot: {job['title']} ({job['match_score']}/100)"
    if profile.get("email_enabled") and profile.get("email_sender") and profile.get("email_password"):
        try:
            m = MIMEMultipart(); m["From"] = profile["email_sender"]; m["To"] = profile.get("email_receiver", profile["email_sender"]); m["Subject"] = subj
            m.attach(MIMEText(msg, "plain"))
            with smtplib.SMTP("smtp.gmail.com", 587) as s: s.starttls(); s.login(profile["email_sender"], profile["email_password"]); s.send_message(m)
            log.info(f"  📧 Email sent")
        except Exception as e: log.error(f"  Email: {e}")
    if profile.get("telegram_enabled") and profile.get("telegram_bot_token") and profile.get("telegram_chat_id"):
        try:
            requests.post(f"https://api.telegram.org/bot{profile['telegram_bot_token']}/sendMessage",
                json={"chat_id": profile["telegram_chat_id"], "text": msg}, timeout=10)
            log.info(f"  💬 Telegram sent")
        except Exception as e: log.error(f"  Telegram: {e}")

# ── Main Pipeline ──
def run_cycle():
    c = db()
    profiles = [dict(r) for r in c.execute("SELECT * FROM profiles WHERE is_active=1").fetchall()]
    c.close()
    if not profiles: log.info("No active profiles."); return

    log.info(f"{'='*50}")
    log.info(f"🚀 Cycle: {len(profiles)} profiles at {datetime.now().strftime('%H:%M')}")

    for p in profiles:
        pid = p["id"]
        log.info(f"👤 {p['name']}")
        c = db()
        searches = [dict(r) for r in c.execute("SELECT * FROM job_searches WHERE profile_id=? AND is_active=1", (pid,)).fetchall()]
        if not searches and p.get("target_titles"):
            for t in p["target_titles"].split(","):
                t = t.strip()
                if t: searches.append({"keywords": t, "location": p.get("location",""), "job_type": p.get("job_type","fulltime")})

        # Scrape
        new_count = 0
        for s in searches:
            for j in scrape_indeed(s["keywords"], s["location"], s.get("job_type","")):
                if not c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone():
                    c.execute("INSERT OR IGNORE INTO jobs (id,profile_id,title,company,location,salary,description,apply_url,source) VALUES (?,?,?,?,?,?,?,?,?)",
                        (j["id"],pid,j["title"],j["company"],j["location"],j["salary"],j["description"],j["apply_url"],j["source"]))
                    new_count += 1
            for j in scrape_linkedin(s["keywords"], s["location"]):
                if not c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone():
                    c.execute("INSERT OR IGNORE INTO jobs (id,profile_id,title,company,location,salary,description,apply_url,source) VALUES (?,?,?,?,?,?,?,?,?)",
                        (j["id"],pid,j["title"],j["company"],j["location"],j["salary"],j["description"],j["apply_url"],j["source"]))
                    new_count += 1
            time.sleep(3)
        c.commit()
        log.info(f"  📡 {new_count} new jobs")

        # Score
        if p.get("anthropic_api_key") and p.get("resume_text"):
            unscored = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE profile_id=? AND match_score IS NULL ORDER BY found_at DESC LIMIT 20", (pid,)).fetchall()]
            for j in unscored:
                sd = score_job(p["anthropic_api_key"], p["resume_text"], p.get("skills",""), j)
                if sd:
                    c.execute("UPDATE jobs SET match_score=?,match_reasons=?,match_missing=?,match_tip=? WHERE id=?",
                        (sd.get("score",0), ", ".join(sd.get("reasons",[])), ", ".join(sd.get("missing",[])), sd.get("tip",""), j["id"]))
                    log.info(f"  🤖 {j['title']}: {sd.get('score',0)}/100")
                time.sleep(2)
            c.commit()

        # Notify
        min_sc = p.get("min_score", 75)
        matches = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE profile_id=? AND match_score>=? AND notified=0", (pid, min_sc)).fetchall()]
        for j in matches:
            notify(p, j)
            c.execute("UPDATE jobs SET notified=1 WHERE id=?", (j["id"],))
        c.commit()
        if matches: log.info(f"  📧 Notified: {len(matches)} matches")
        c.close()

    log.info(f"✅ Done\n{'-'*50}")


if __name__ == "__main__":
    log.info("🤖 JobPilot Bot started")
    while True:
        try:
            run_cycle()
        except KeyboardInterrupt:
            log.info("Stopped."); break
        except Exception as e:
            log.error(f"Error: {e}")
        c = db()
        intervals = [r[0] for r in c.execute("SELECT check_interval FROM profiles WHERE is_active=1").fetchall()]
        c.close()
        wait = min(intervals) if intervals else 15
        log.info(f"💤 Next in {wait}min...")
        time.sleep(wait * 60)
