#!/usr/bin/env python3
"""
JobPilot Bot - Searches, scores, and notifies for all active profiles.
Reads config from the database (set up via GUI).
Now using the new multi-source scraper.
"""

import os, sys, sqlite3, json, time, hashlib, logging, re, smtplib, requests
from datetime import datetime
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

# Import the new scraper
from scraper import scrape_all

BASE = os.path.dirname(os.path.abspath(__file__))
DB = os.path.join(BASE, "data", "jobs.db")
LOG = os.path.join(BASE, "logs", "bot.log")

os.makedirs(os.path.dirname(LOG), exist_ok=True)
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s",
    handlers=[logging.FileHandler(LOG), logging.StreamHandler(sys.stdout)])
log = logging.getLogger("bot")

def db():
    c = sqlite3.connect(DB); c.row_factory = sqlite3.Row; return c

# ── AI Scorer (uses Anthropic Claude) ──
def score_job(api_key, resume, skills, job):
    """Score job match 0-100 using Claude"""
    try:
        prompt = f"""Score this job match from 0-100.

RESUME HIGHLIGHTS:
{resume[:2000]}

SKILLS:
{skills}

JOB POSTING:
Title: {job['title']}
Company: {job['company']}
Location: {job['location']}
Description: {job['description'][:1000]}

Respond with ONLY valid JSON (no markdown, no code fence):
{{
  "score": <0-100>,
  "reasons": ["reason1", "reason2"],
  "missing": ["skill1", "skill2"],
  "tip": "brief tip"
}}"""
        
        r = requests.post("https://api.anthropic.com/v1/messages",
            headers={
                "Content-Type": "application/json",
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01"
            },
            json={
                "model": "claude-opus-4-1-20250805",
                "max_tokens": 256,
                "messages": [{"role": "user", "content": prompt}]
            },
            timeout=30)
        
        if r.status_code == 200:
            txt = r.json()["content"][0]["text"].strip().replace("```json","").replace("```","").strip()
            result = json.loads(txt)
            return result
        elif r.status_code == 429:
            log.warning("Rate limited by Anthropic, waiting 60s...")
            time.sleep(60)
            return score_job(api_key, resume, skills, job)
        else:
            log.error(f"Anthropic error {r.status_code}: {r.text}")
            return None
    except Exception as e:
        log.error(f"Score error: {e}")
        return None

# ── Notifier ──
def notify(profile, job):
    """Send email and/or Telegram notification"""
    msg = f"🎯 Match: {job['match_score']}/100\n{job['title']}\n{job['company']} · {job['location']}\n{job.get('match_reasons','')}\nApply: {job.get('apply_url','')}"
    subj = f"⚡ JobPilot: {job['title']} ({job['match_score']}/100)"
    
    # Email
    if profile.get("email_enabled") and profile.get("email_sender") and profile.get("email_password"):
        try:
            m = MIMEMultipart()
            m["From"] = profile["email_sender"]
            m["To"] = profile.get("email_receiver", profile["email_sender"])
            m["Subject"] = subj
            m.attach(MIMEText(msg, "plain"))
            with smtplib.SMTP("smtp.gmail.com", 587) as s:
                s.starttls()
                s.login(profile["email_sender"], profile["email_password"])
                s.send_message(m)
            log.info(f"  📧 Email sent to {profile.get('email_receiver')}")
        except Exception as e:
            log.error(f"  Email error: {e}")
    
    # Telegram
    if profile.get("telegram_enabled") and profile.get("telegram_bot_token") and profile.get("telegram_chat_id"):
        try:
            requests.post(f"https://api.telegram.org/bot{profile['telegram_bot_token']}/sendMessage",
                json={"chat_id": profile["telegram_chat_id"], "text": msg}, timeout=10)
            log.info(f"  💬 Telegram sent")
        except Exception as e:
            log.error(f"  Telegram error: {e}")

# ── Main Pipeline ──
def run_cycle():
    c = db()
    profiles = [dict(r) for r in c.execute("SELECT * FROM profiles WHERE is_active=1").fetchall()]
    c.close()
    
    if not profiles:
        log.info("No active profiles.")
        return

    log.info(f"{'='*60}")
    log.info(f"🚀 Cycle started at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")

    for p in profiles:
        pid = p["id"]
        log.info(f"👤 {p['name']} (ID: {pid})")
        
        c = db()
        searches = [dict(r) for r in c.execute("SELECT * FROM job_searches WHERE profile_id=? AND is_active=1", (pid,)).fetchall()]
        
        # Fall back to target titles if no searches configured
        if not searches and p.get("target_titles"):
            log.info(f"  ℹ Using target_titles: {p['target_titles']}")
            for t in p["target_titles"].split(","):
                t = t.strip()
                if t:
                    searches.append({
                        "keywords": t,
                        "location": p.get("location", ""),
                        "job_type": p.get("job_type", "fulltime")
                    })

        # Scrape all sources
        new_count = 0
        for s in searches:
            log.info(f"  🔍 Searching: '{s['keywords']}' in {s['location']}")
            
            try:
                # Use new multi-source scraper
                jobs = scrape_all(s["keywords"], s["location"], 
                                 sources=["indeed", "linkedin", "google_jobs", "ziprecruiter"])
                
                for j in jobs:
                    # Check if job already exists
                    existing = c.execute("SELECT 1 FROM jobs WHERE id=?", (j["id"],)).fetchone()
                    if not existing:
                        c.execute(
                            "INSERT OR IGNORE INTO jobs (id,profile_id,title,company,location,salary,description,apply_url,source) VALUES (?,?,?,?,?,?,?,?,?)",
                            (j["id"], pid, j["title"], j["company"], j["location"], j["salary"], j["description"], j["apply_url"], j["source"])
                        )
                        new_count += 1
                
                c.commit()
                log.info(f"    ✓ {len(jobs)} found, {sum(1 for j in jobs if not c.execute('SELECT 1 FROM jobs WHERE id=?', (j['id'],)).fetchone())} new")
            except Exception as e:
                log.error(f"    Error scraping: {e}")
            
            time.sleep(2)  # Be respectful to servers

        log.info(f"  📡 Total new jobs: {new_count}")

        # Score unscored jobs
        if p.get("anthropic_api_key") and p.get("resume_text"):
            log.info(f"  🤖 Scoring jobs...")
            unscored = [dict(r) for r in c.execute(
                "SELECT * FROM jobs WHERE profile_id=? AND match_score IS NULL ORDER BY found_at DESC LIMIT 20",
                (pid,)).fetchall()]
            
            scored_count = 0
            for j in unscored:
                sd = score_job(p["anthropic_api_key"], p["resume_text"], p.get("skills", ""), j)
                if sd:
                    c.execute(
                        "UPDATE jobs SET match_score=?,match_reasons=?,match_missing=?,match_tip=? WHERE id=?",
                        (sd.get("score", 0), ", ".join(sd.get("reasons", [])), ", ".join(sd.get("missing", [])), sd.get("tip", ""), j["id"])
                    )
                    log.info(f"    {j['title']}: {sd.get('score', 0)}/100")
                    scored_count += 1
                time.sleep(1)
            
            c.commit()
            log.info(f"  ✓ Scored {scored_count} jobs")
        else:
            if not p.get("anthropic_api_key"):
                log.warning(f"  ⚠ No Anthropic API key configured")
            if not p.get("resume_text"):
                log.warning(f"  ⚠ No resume text configured")

        # Notify about high matches
        min_sc = p.get("min_score", 75)
        matches = [dict(r) for r in c.execute(
            "SELECT * FROM jobs WHERE profile_id=? AND match_score>=? AND notified=0",
            (pid, min_sc)).fetchall()]
        
        for j in matches:
            notify(p, j)
            c.execute("UPDATE jobs SET notified=1 WHERE id=?", (j["id"],))
        
        c.commit()
        if matches:
            log.info(f"  📧 Notified: {len(matches)} high-match jobs")
        
        c.close()

    log.info(f"✅ Cycle complete\n{'-'*60}")

if __name__ == "__main__":
    log.info("🤖 JobPilot Bot started")
    try:
        while True:
            try:
                run_cycle()
            except KeyboardInterrupt:
                log.info("Stopped by user.")
                break
            except Exception as e:
                log.error(f"Cycle error: {e}", exc_info=True)
            
            # Get next check interval
            c = db()
            intervals = [r[0] for r in c.execute("SELECT check_interval FROM profiles WHERE is_active=1").fetchall()]
            c.close()
            
            wait = min(intervals) if intervals else 15
            log.info(f"💤 Next cycle in {wait} minutes...")
            time.sleep(wait * 60)
    except KeyboardInterrupt:
        log.info("Bot shutdown.")
