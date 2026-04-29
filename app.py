#!/usr/bin/env python3
"""
JobPilot - AI-Powered Job Automation Dashboard
===============================================
Full web GUI: create profiles, upload resumes, configure alerts.
Run: python3 app.py
Open: http://jobpilot.local:5000
"""

from flask import Flask, render_template_string, request, redirect, jsonify, flash
import os, sqlite3, re, io
from datetime import datetime

BASE = os.path.dirname(os.path.abspath(__file__))
DB_PATH = os.path.join(BASE, "data", "jobs.db")

app = Flask(__name__)
app.secret_key = os.urandom(24).hex()
app.config["MAX_CONTENT_LENGTH"] = 16 * 1024 * 1024  # 16MB max upload

# ═══════════════════════════════════════════════
# DATABASE
# ═══════════════════════════════════════════════
def get_db():
    os.makedirs(os.path.dirname(DB_PATH), exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS profiles (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT NOT NULL, email TEXT, phone TEXT, location TEXT DEFAULT '',
            resume_text TEXT DEFAULT '', skills TEXT DEFAULT '', target_titles TEXT DEFAULT '',
            job_type TEXT DEFAULT 'fulltime', min_salary TEXT DEFAULT '',
            min_score INTEGER DEFAULT 75, check_interval INTEGER DEFAULT 15,
            anthropic_api_key TEXT DEFAULT '',
            email_enabled INTEGER DEFAULT 0, email_sender TEXT DEFAULT '',
            email_password TEXT DEFAULT '', email_receiver TEXT DEFAULT '',
            telegram_enabled INTEGER DEFAULT 0, telegram_bot_token TEXT DEFAULT '',
            telegram_chat_id TEXT DEFAULT '', is_active INTEGER DEFAULT 1,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        CREATE TABLE IF NOT EXISTS job_searches (
            id INTEGER PRIMARY KEY AUTOINCREMENT, profile_id INTEGER,
            keywords TEXT NOT NULL, location TEXT NOT NULL,
            job_type TEXT DEFAULT 'fulltime', is_active INTEGER DEFAULT 1
        );
        CREATE TABLE IF NOT EXISTS jobs (
            id TEXT PRIMARY KEY, profile_id INTEGER, title TEXT NOT NULL,
            company TEXT, location TEXT, salary TEXT, description TEXT,
            apply_url TEXT, source TEXT,
            found_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            match_score INTEGER, match_reasons TEXT, match_missing TEXT,
            match_tip TEXT, resume_tailored TEXT, cover_letter TEXT,
            notified INTEGER DEFAULT 0, applied INTEGER DEFAULT 0,
            applied_at TIMESTAMP, status TEXT DEFAULT 'new', notes TEXT
        );
    """)
    conn.commit()
    conn.close()

init_db()


# ═══════════════════════════════════════════════
# HTML TEMPLATE (complete GUI)
# ═══════════════════════════════════════════════
HTML = """<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"><meta name="viewport" content="width=device-width,initial-scale=1.0">
<title>JobPilot</title>
<style>
@import url('https://fonts.googleapis.com/css2?family=DM+Sans:wght@400;500;600;700&family=Space+Mono:wght@400;700&display=swap');
*{box-sizing:border-box;margin:0;padding:0}
body{font-family:'DM Sans',sans-serif;background:#0a0e17;color:#e2e8f0;min-height:100vh}
a{color:#3b82f6;text-decoration:none}

/* Layout */
.header{padding:16px 24px;border-bottom:1px solid #1e293b;display:flex;align-items:center;justify-content:space-between;background:linear-gradient(180deg,#0f1525,#0a0e17);flex-wrap:wrap;gap:10px}
.logo{font-family:'Space Mono',monospace;font-size:20px;font-weight:700;color:#3b82f6}
.logo-sub{font-size:10px;color:#64748b;letter-spacing:2px;text-transform:uppercase}
.nav{display:flex;gap:3px;background:#111827;border-radius:9px;padding:3px}
.nav a{padding:7px 14px;border-radius:7px;font-size:12px;font-weight:600;color:#94a3b8;transition:all 0.2s}
.nav a.active,.nav a:hover{background:#3b82f6;color:#fff}
.main{max-width:900px;margin:0 auto;padding:20px 24px}

/* Components */
.card{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:22px;margin-bottom:14px}
.card-title{font-size:15px;font-weight:700;margin-bottom:14px;display:flex;align-items:center;gap:8px}
.form-row{display:grid;grid-template-columns:1fr 1fr;gap:10px;margin-bottom:10px}
.form-row.full{grid-template-columns:1fr}
label{font-size:11px;font-weight:600;color:#94a3b8;margin-bottom:4px;display:block;text-transform:uppercase;letter-spacing:0.5px}
input,select,textarea{width:100%;padding:10px 14px;border-radius:8px;border:1px solid #1e293b;background:#0a0e17;color:#e2e8f0;font-size:14px;font-family:'DM Sans',sans-serif;outline:none}
input:focus,textarea:focus,select:focus{border-color:#3b82f6;box-shadow:0 0 0 3px rgba(59,130,246,0.1)}
textarea{resize:vertical;min-height:120px;font-size:13px}
.chk{display:flex;align-items:center;gap:8px;margin-bottom:8px}
.chk input[type=checkbox]{width:auto;accent-color:#3b82f6}
.chk label{margin:0;text-transform:none;font-size:13px}

/* Buttons */
.btn{padding:10px 20px;border-radius:8px;border:none;font-size:13px;font-weight:600;cursor:pointer;font-family:'DM Sans',sans-serif;display:inline-flex;align-items:center;gap:6px;transition:all 0.2s}
.btn-p{background:#3b82f6;color:#fff}.btn-p:hover{background:#2563eb}
.btn-s{background:#1a2236;color:#e2e8f0;border:1px solid #1e293b}
.btn-g{background:#22c55e;color:#fff}
.btn-d{background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.3)}
.btn-sm{padding:6px 12px;font-size:11px}
.btn-grp{display:flex;gap:8px;margin-top:14px;flex-wrap:wrap}

/* Profiles */
.pcard{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:18px;margin-bottom:10px;display:flex;align-items:center;gap:14px;transition:border 0.2s}
.pcard:hover{border-color:#3b82f6}
.avatar{width:48px;height:48px;border-radius:50%;background:linear-gradient(135deg,#3b82f6,#a78bfa);display:flex;align-items:center;justify-content:center;font-size:18px;font-weight:700;color:#fff}
.pname{font-size:15px;font-weight:700}
.pmeta{font-size:12px;color:#94a3b8;margin-top:2px}
.active{background:rgba(34,197,94,0.1);color:#22c55e;font-size:11px;padding:3px 10px;border-radius:6px;font-weight:600}
.paused{background:rgba(245,158,11,0.1);color:#f59e0b;font-size:11px;padding:3px 10px;border-radius:6px;font-weight:600}

/* Stats */
.sgrid{display:grid;grid-template-columns:repeat(auto-fit,minmax(120px,1fr));gap:10px;margin-bottom:16px}
.stat{background:#111827;border:1px solid #1e293b;border-radius:12px;padding:14px}
.sval{font-family:'Space Mono',monospace;font-size:26px;font-weight:700}
.slab{font-size:11px;color:#64748b;margin-top:2px;text-transform:uppercase;letter-spacing:0.5px}

/* Jobs */
.jrow{display:flex;gap:12px;align-items:center;padding:12px 0;border-bottom:1px solid #1e293b}
.jrow:last-child{border-bottom:none}
.sc{width:42px;height:42px;border-radius:50%;display:flex;align-items:center;justify-content:center;font-size:13px;font-weight:700;font-family:'Space Mono',monospace;flex-shrink:0}
.sc-h{background:rgba(34,197,94,0.1);color:#22c55e;border:2px solid #22c55e}
.sc-m{background:rgba(245,158,11,0.1);color:#f59e0b;border:2px solid #f59e0b}
.sc-l{background:rgba(239,68,68,0.1);color:#ef4444;border:2px solid #ef4444}
.sc-n{color:#64748b;border:2px dashed #1e293b;font-size:10px}
.bg{display:inline-flex;padding:2px 8px;border-radius:5px;font-size:10px;font-weight:600}
.bg-g{background:rgba(34,197,94,0.1);color:#22c55e}
.bg-o{background:rgba(245,158,11,0.1);color:#f59e0b}

/* Dropzone */
.dz{border:2px dashed #1e293b;border-radius:10px;padding:30px;text-align:center;cursor:pointer;transition:all 0.2s;background:#0a0e17}
.dz:hover,.dz.over{border-color:#3b82f6;background:rgba(59,130,246,0.05)}

/* Search items */
.si{display:flex;align-items:center;gap:10px;padding:8px 12px;background:#0a0e17;border-radius:8px;margin-bottom:6px}
.si span{flex:1;font-size:13px}

/* Misc */
.alert{padding:12px 16px;border-radius:8px;margin-bottom:14px;font-size:13px}
.alert-success{background:rgba(34,197,94,0.1);color:#22c55e;border:1px solid rgba(34,197,94,0.2)}
.alert-error{background:rgba(239,68,68,0.1);color:#ef4444;border:1px solid rgba(239,68,68,0.2)}
.help{font-size:11px;color:#64748b;margin-top:3px;line-height:1.5}
.empty{text-align:center;padding:40px 20px;color:#64748b}
.funnel-row{display:flex;justify-content:space-between;font-size:12px;margin-bottom:3px}
.funnel-bar{height:6px;background:#0a0e17;border-radius:3px;overflow:hidden;margin-bottom:10px}
.funnel-fill{height:100%;border-radius:3px;transition:width 0.8s}
@media(max-width:600px){.form-row{grid-template-columns:1fr}.header{padding:12px 16px}.main{padding:14px 16px}}
</style>
</head>
<body>
<div class="header">
  <div><div class="logo">⚡ JobPilot</div><div class="logo-sub">AI Job Automation</div></div>
  <div class="nav">
    <a href="/" class="{{ 'active' if page=='home' }}">👥 Profiles</a>
    {% if p %}<a href="/p/{{ p.id }}" class="{{ 'active' if page=='dash' }}">📊 Dashboard</a>{% endif %}
    {% if p %}<a href="/p/{{ p.id }}/jobs" class="{{ 'active' if page=='jobs' }}">💼 Jobs</a>{% endif %}
    {% if p %}<a href="/p/{{ p.id }}/applied" class="{{ 'active' if page=='applied' }}">✅ Applied</a>{% endif %}
  </div>
</div>
<div class="main">
{% with msgs = get_flashed_messages(with_categories=true) %}{% if msgs %}{% for c,m in msgs %}<div class="alert alert-{{ c }}">{{ m }}</div>{% endfor %}{% endif %}{% endwith %}

{% if page == 'home' %}
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px">
  <h2 style="font-size:18px;font-weight:700">👥 Profiles</h2>
  <a href="/new"><button class="btn btn-p">+ New Profile</button></a>
</div>
{% if profiles|length == 0 %}
<div class="empty"><div style="font-size:40px;margin-bottom:8px">👤</div><div style="font-size:15px;font-weight:600">No profiles yet</div>
<a href="/new"><button class="btn btn-p" style="margin-top:14px">+ Create First Profile</button></a></div>
{% else %}{% for pr in profiles %}
<div class="pcard"><div class="avatar">{{ pr.name[0] if pr.name else '?' }}</div>
<div style="flex:1"><div class="pname">{{ pr.name }}</div><div class="pmeta">{{ pr.target_titles or 'No targets' }} · {{ pr.location or 'No location' }}</div></div>
<span class="{{ 'active' if pr.is_active else 'paused' }}">{{ 'Active' if pr.is_active else 'Paused' }}</span>
<a href="/p/{{ pr.id }}"><button class="btn btn-s btn-sm">📊</button></a>
<a href="/p/{{ pr.id }}/edit"><button class="btn btn-s btn-sm">✏️</button></a></div>
{% endfor %}{% endif %}
{% endif %}

{% if page == 'edit' %}
<h2 style="font-size:18px;font-weight:700;margin-bottom:16px">{{ '✏️ Edit' if p else '➕ New Profile' }}</h2>
<form method="POST" action="{{ '/p/' ~ p.id ~ '/save' if p else '/create' }}">
  <div class="card"><div class="card-title">👤 Personal Info</div>
    <div class="form-row"><div><label>Name *</label><input name="name" id="fn" value="{{ p.name if p else '' }}" required></div><div><label>Email</label><input name="email" id="fe" value="{{ p.email if p else '' }}"></div></div>
    <div class="form-row"><div><label>Location</label><input name="location" value="{{ p.location if p else 'Richardson, TX' }}"></div><div><label>Phone</label><input name="phone" id="fp" value="{{ p.phone if p else '' }}"></div></div>
  </div>

  <div class="card"><div class="card-title">🎯 Job Preferences</div>
    <div class="form-row full"><div><label>Target Titles (comma separated)</label><input name="target_titles" value="{{ p.target_titles if p else '' }}" placeholder="Product Manager, Project Manager"></div></div>
    <div class="form-row"><div><label>Skills</label><input name="skills" id="fs" value="{{ p.skills if p else '' }}" placeholder="Agile, Jira, Risk Analysis"></div><div><label>Min Salary</label><input name="min_salary" value="{{ p.min_salary if p else '' }}" placeholder="$60k"></div></div>
    <div class="form-row"><div><label>Job Type</label><select name="job_type"><option value="fulltime" {{ 'selected' if p and p.job_type=='fulltime' }}>Full Time</option><option value="parttime" {{ 'selected' if p and p.job_type=='parttime' }}>Part Time</option><option value="contract" {{ 'selected' if p and p.job_type=='contract' }}>Contract</option></select></div><div><label>Min Match Score</label><input name="min_score" type="number" min="0" max="100" value="{{ p.min_score if p else 75 }}"></div></div>
  </div>

  <div class="card"><div class="card-title">📄 Resume</div>
    <div class="dz" id="dz" ondragover="event.preventDefault();this.classList.add('over')" ondragleave="this.classList.remove('over')" ondrop="handleDrop(event)">
      <div style="font-size:36px;margin-bottom:8px">📎</div>
      <div style="font-size:15px;font-weight:600">Drop your resume here or click to browse</div>
      <div style="font-size:12px;color:#64748b;margin-top:6px">PDF, Word (.docx), or Text files</div>
      <input type="file" id="rf" accept=".pdf,.docx,.doc,.txt" style="display:none" onchange="doUpload(this.files[0])">
    </div>
    <div id="us" style="margin-bottom:10px;font-size:12px;display:none"></div>
    <div class="form-row full"><div><label>Resume Text <span style="font-weight:400;color:#64748b">(auto-filled from upload or paste manually)</span></label><textarea name="resume_text" id="fr" required>{{ p.resume_text if p else '' }}</textarea></div></div>
  </div>

  <div class="card"><div class="card-title">🔑 API Key</div>
    <div class="form-row full"><div><label>Anthropic API Key</label><input name="anthropic_api_key" type="password" value="{{ p.anthropic_api_key if p else '' }}" placeholder="sk-ant-..."><div class="help">Get from <a href="https://console.anthropic.com" target="_blank">console.anthropic.com</a></div></div></div>
  </div>

  <div class="card"><div class="card-title">📧 Email Alerts</div>
    <div class="chk"><input type="checkbox" name="email_enabled" id="ee" {{ 'checked' if p and p.email_enabled }}><label for="ee">Enable email</label></div>
    <div class="form-row"><div><label>Gmail</label><input name="email_sender" value="{{ p.email_sender if p else '' }}"></div><div><label>App Password</label><input name="email_password" type="password" value="{{ p.email_password if p else '' }}"></div></div>
    <div class="form-row full"><div><label>Send to</label><input name="email_receiver" value="{{ p.email_receiver if p else '' }}"></div></div>
  </div>

  <div class="card"><div class="card-title">💬 Telegram</div>
    <div class="chk"><input type="checkbox" name="telegram_enabled" id="te" {{ 'checked' if p and p.telegram_enabled }}><label for="te">Enable Telegram</label></div>
    <div class="form-row"><div><label>Bot Token</label><input name="telegram_bot_token" value="{{ p.telegram_bot_token if p else '' }}"><div class="help">From <a href="https://t.me/BotFather" target="_blank">@BotFather</a> on Telegram</div></div><div><label>Chat ID</label><input name="telegram_chat_id" value="{{ p.telegram_chat_id if p else '' }}"></div></div>
  </div>

  <div class="card"><div class="card-title">⏰ Settings</div>
    <div class="form-row"><div><label>Check Interval (min)</label><input name="check_interval" type="number" min="5" max="120" value="{{ p.check_interval if p else 15 }}"></div><div></div></div>
  </div>

  <div class="btn-grp">
    <button type="submit" class="btn btn-p">💾 {{ 'Save' if p else 'Create Profile' }}</button>
    <a href="/"><button type="button" class="btn btn-s">Cancel</button></a>
    {% if p %}<a href="/p/{{ p.id }}/del" onclick="return confirm('Delete?')"><button type="button" class="btn btn-d">🗑</button></a>{% endif %}
  </div>
</form>

{% if p %}
<div class="card" style="margin-top:20px"><div class="card-title">🔍 Search Locations</div>
{% for s in searches %}<div class="si"><span>🔎 <b>{{ s.keywords }}</b> in {{ s.location }}</span><a href="/s/{{ s.id }}/del"><button class="btn btn-d btn-sm">✕</button></a></div>{% endfor %}
<form method="POST" action="/p/{{ p.id }}/addsearch" style="display:flex;gap:8px;margin-top:10px;flex-wrap:wrap">
<input name="keywords" placeholder="Job title" style="flex:2;min-width:150px" required>
<input name="location" placeholder="City, State" style="flex:1;min-width:120px" required>
<button class="btn btn-p btn-sm">+ Add</button></form></div>
{% endif %}

<script>
document.getElementById('dz').onclick = function() {
  document.getElementById('rf').click();
};

function handleDrop(e) {
  e.preventDefault();
  e.stopPropagation();
  document.getElementById('dz').classList.remove('over');
  if (e.dataTransfer.files.length > 0) {
    doUpload(e.dataTransfer.files[0]);
  }
}

function doUpload(f) {
  if (!f) return;
  var s = document.getElementById('us');
  s.style.display = 'block';
  s.style.color = '#3b82f6';
  s.textContent = '⏳ Parsing ' + f.name + '...';
  
  var d = new FormData();
  d.append('file', f);
  
  fetch('/upload', { method: 'POST', body: d })
    .then(r => r.json())
    .then(res => {
      if (res.ok) {
        s.style.color = '#22c55e';
        s.textContent = '✓ Extracted: ' + (res.name || '?') + ' | ' + (res.email || '?');
        document.getElementById('fr').value = res.text;
        document.getElementById('fn').value = res.name || document.getElementById('fn').value;
        document.getElementById('fe').value = res.email || document.getElementById('fe').value;
        document.getElementById('fp').value = res.phone || document.getElementById('fp').value;
      } else {
        s.style.color = '#ef4444';
        s.textContent = '✗ ' + res.err;
      }
    })
    .catch(e => {
      s.style.color = '#ef4444';
      s.textContent = '✗ Upload error: ' + e.message;
    });
}
</script>
{% endif %}

{% if page == 'dash' and p %}
<div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:16px;flex-wrap:wrap;gap:8px">
  <h2 style="font-size:18px;font-weight:700">📊 {{ p.name }}</h2>
  <div style="display:flex;gap:6px"><form method="POST" action="/p/{{ p.id }}/toggle"><button class="btn {{ 'btn-d' if p.is_active else 'btn-g' }} btn-sm">{{ '⏸ Pause' if p.is_active else '▶ Resume' }}</button></form></div>
</div>
<div class="sgrid">
  <div class="stat"><div class="sval" style="color:#3b82f6">{{ st.total }}</div><div class="slab">Found</div></div>
  <div class="stat"><div class="sval" style="color:#a78bfa">{{ st.scored }}</div><div class="slab">Scored</div></div>
  <div class="stat"><div class="sval" style="color:#22c55e">{{ st.high }}</div><div class="slab">80+</div></div>
  <div class="stat"><div class="sval" style="color:#06b6d4">{{ st.applied }}</div><div class="slab">Applied</div></div>
</div>
{% if st.total > 0 %}
<div class="card"><div class="card-title">📊 Funnel</div>
{% for lbl,cnt,col in [('Found',st.total,'#3b82f6'),('Scored',st.scored,'#a78bfa'),('80+ Match',st.high,'#22c55e'),('Applied',st.applied,'#06b6d4')] %}
<div class="funnel-row"><span style="color:#94a3b8">{{lbl}}</span><span style="color:{{col}};font-family:'Space Mono',monospace">{{cnt}} ({{(cnt/st.total*100)|round|int if st.total else 0}}%)</span></div>
<div class="funnel-bar"><div class="funnel-fill" style="width:{{(cnt/st.total*100)|round|int if st.total else 0}}%;background:{{col}}"></div></div>
{% endfor %}</div>{% endif %}
{% if topj %}<div class="card"><div class="card-title">🏆 Top Matches</div>
{% for j in topj[:10] %}<div class="jrow"><div class="sc {{'sc-h' if j.match_score>=80 else 'sc-m' if j.match_score>=60 else 'sc-l'}}">{{j.match_score}}</div><div style="flex:1"><div style="font-weight:700">{{j.title}}</div><div style="font-size:12px;color:#94a3b8">{{j.company}} · {{j.location}}</div></div></div>
{% endfor %}{% endif %}

{% if page == 'jobs' and p %}
<h2 style="font-size:18px;font-weight:700;margin-bottom:16px">💼 Jobs ({{ jlist|length }})</h2>
{% if jlist|length == 0 %}<div class="empty"><div style="font-size:40px">🔎</div><div style="margin-top:8px">No jobs yet — bot is searching...</div></div>
{% else %}<div class="card">{% for j in jlist %}<div class="jrow">
{% if j.match_score is not none %}<div class="sc {{'sc-h' if j.match_score>=80 else 'sc-m' if j.match_score>=60 else 'sc-l'}}">{{j.match_score}}</div>{% else %}<div class="sc sc-n">?</div>{% endif %}
<div style="flex:1;min-width:0"><div style="font-size:14px;font-weight:700">{{j.title}}{% if j.applied %} <span class="bg bg-g">Applied</span>{% endif %}</div><div style="font-size:12px;color:#94a3b8">{{j.company}} · {{j.location}} <span class="bg bg-o">{{j.source}}</span></div></div>
<div style="display:flex;gap:4px">{% if not j.applied %}<a href="/j/{{j.id}}/apply"><button class="btn btn-g btn-sm">✅</button></a>{% endif %}{% if j.apply_url %}<a href="{{j.apply_url}}" target="_blank"><button class="btn btn-s btn-sm">↗</button></a>{% endif %}</div>
{% endfor %}</div>{% endif %}

{% if page == 'applied' and p %}
<h2 style="font-size:18px;font-weight:700;margin-bottom:16px">✅ Applications ({{ alist|length }})</h2>
{% if alist|length == 0 %}<div class="empty"><div style="font-size:40px">📭</div><div style="margin-top:8px">No applications yet</div></div>
{% else %}<div class="card">{% for j in alist %}<div class="jrow">
{% if j.match_score is not none %}<div class="sc {{'sc-h' if j.match_score>=80 else 'sc-m' if j.match_score>=60 else 'sc-l'}}">{{j.match_score}}</div>{% endif %}
<div style="flex:1"><div style="font-size:14px;font-weight:700">{{j.title}}</div><div style="font-size:12px;color:#94a3b8">{{j.company}} · {{j.applied_at[:10] if j.applied_at else '?'}}</div></div>
<form method="POST" action="/j/{{j.id}}/status"><select name="st" onchange="this.form.submit()" style="width:auto;font-size:11px;padding:4px 8px">{% for s in ['applied','interview','offer','rejected'] %}<option value="{{s}}" {{ 'selected' if j.status==s }}>{{ s|upper }}</option>{% endfor %}</select></form></div>
{% endfor %}</div>{% endif %}
</div></body></html>"""


# ═══════════════════════════════════════════════
# ROUTES
# ═══════════════════════════════════════════════
@app.route("/")
def home():
    c = get_db()
    profiles = [dict(r) for r in c.execute("SELECT * FROM profiles ORDER BY created_at DESC").fetchall()]
    c.close()
    return render_template_string(HTML, page="home", profiles=profiles, p=None)

@app.route("/new")
def new():
    return render_template_string(HTML, page="edit", p=None, profiles=[], searches=[])

@app.route("/create", methods=["POST"])
def create():
    c = get_db(); d = request.form
    cur = c.execute("INSERT INTO profiles (name,email,phone,location,resume_text,skills,target_titles,job_type,min_salary,min_score,check_interval,anthropic_api_key,email_enabled,email_sender,email_password,email_receiver,telegram_enabled,telegram_bot_token,telegram_chat_id) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
        (d.get("name"),d.get("email"),d.get("phone"),d.get("location"),d.get("resume_text"),d.get("skills"),d.get("target_titles"),d.get("job_type","fulltime"),d.get("min_salary"),int(d.get("min_score",75)),int(d.get("check_interval",15)),d.get("anthropic_api_key"),int(bool(d.get("email_enabled"))),d.get("email_sender"),d.get("email_password"),d.get("email_receiver"),int(bool(d.get("telegram_enabled"))),d.get("telegram_bot_token"),d.get("telegram_chat_id")))
    pid = cur.lastrowid
    for t in d.get("target_titles","").split(","):
        t = t.strip()
        if t:
            c.execute("INSERT INTO job_searches (profile_id,keywords,location,job_type) VALUES (?,?,?,?)",(pid,t,d.get("location",""),d.get("job_type","fulltime")))
            if d.get("location","").lower() != "remote":
                c.execute("INSERT INTO job_searches (profile_id,keywords,location,job_type) VALUES (?,?,?,?)",(pid,t,"remote",d.get("job_type","fulltime")))
    c.commit(); c.close()
    flash("Profile created!","success"); return redirect(f"/p/{pid}")

@app.route("/p/<int:pid>/edit")
def edit(pid):
    c = get_db()
    p = c.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone()
    s = [dict(r) for r in c.execute("SELECT * FROM job_searches WHERE profile_id=? AND is_active=1",(pid,)).fetchall()]
    c.close()
    return render_template_string(HTML, page="edit", p=dict(p) if p else None, profiles=[], searches=s)

@app.route("/p/<int:pid>/save", methods=["POST"])
def save(pid):
    c = get_db(); d = request.form
    c.execute("UPDATE profiles SET name=?,email=?,phone=?,location=?,resume_text=?,skills=?,target_titles=?,job_type=?,min_salary=?,min_score=?,check_interval=?,anthropic_api_key=?,email_enabled=?,email_sender=?,email_password=?,email_receiver=?,telegram_enabled=?,telegram_bot_token=?,telegram_chat_id=? WHERE id=?",
        (d.get("name"),d.get("email"),d.get("phone"),d.get("location"),d.get("resume_text"),d.get("skills"),d.get("target_titles"),d.get("job_type","fulltime"),d.get("min_salary"),int(d.get("min_score",75)),int(d.get("check_interval",15)),d.get("anthropic_api_key"),int(bool(d.get("email_enabled"))),d.get("email_sender"),d.get("email_password"),d.get("email_receiver"),int(bool(d.get("telegram_enabled"))),d.get("telegram_bot_token"),d.get("telegram_chat_id"),pid))
    c.commit(); c.close()
    flash("Saved!","success"); return redirect(f"/p/{pid}")

@app.route("/p/<int:pid>/del")
def delete(pid):
    c = get_db()
    c.execute("DELETE FROM job_searches WHERE profile_id=?",(pid,))
    c.execute("DELETE FROM jobs WHERE profile_id=?",(pid,))
    c.execute("DELETE FROM profiles WHERE id=?",(pid,))
    c.commit(); c.close()
    flash("Deleted.","success"); return redirect("/")

@app.route("/p/<int:pid>/toggle", methods=["POST"])
def toggle(pid):
    c = get_db()
    r = c.execute("SELECT is_active FROM profiles WHERE id=?",(pid,)).fetchone()
    c.execute("UPDATE profiles SET is_active=? WHERE id=?",(0 if r and r[0] else 1, pid))
    c.commit(); c.close(); return redirect(f"/p/{pid}")

@app.route("/p/<int:pid>")
def dash(pid):
    c = get_db()
    p = c.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone()
    if not p: return redirect("/")
    st = {"total":c.execute("SELECT COUNT(*) FROM jobs WHERE profile_id=?",(pid,)).fetchone()[0],
          "scored":c.execute("SELECT COUNT(*) FROM jobs WHERE profile_id=? AND match_score IS NOT NULL",(pid,)).fetchone()[0],
          "high":c.execute("SELECT COUNT(*) FROM jobs WHERE profile_id=? AND match_score>=80",(pid,)).fetchone()[0],
          "applied":c.execute("SELECT COUNT(*) FROM jobs WHERE profile_id=? AND applied=1",(pid,)).fetchone()[0]}
    topj = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE profile_id=? AND match_score IS NOT NULL ORDER BY match_score DESC LIMIT 20",(pid,)).fetchall()]
    c.close()
    return render_template_string(HTML, page="dash", p=dict(p), st=st, topj=topj, profiles=[])

@app.route("/p/<int:pid>/jobs")
def jobs(pid):
    c = get_db()
    p = c.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone()
    jlist = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE profile_id=? ORDER BY found_at DESC LIMIT 200",(pid,)).fetchall()]
    c.close()
    return render_template_string(HTML, page="jobs", p=dict(p), jlist=jlist, profiles=[])

@app.route("/p/<int:pid>/applied")
def applied(pid):
    c = get_db()
    p = c.execute("SELECT * FROM profiles WHERE id=?",(pid,)).fetchone()
    alist = [dict(r) for r in c.execute("SELECT * FROM jobs WHERE profile_id=? AND applied=1 ORDER BY applied_at DESC",(pid,)).fetchall()]
    c.close()
    return render_template_string(HTML, page="applied", p=dict(p), alist=alist, profiles=[])

@app.route("/p/<int:pid>/addsearch", methods=["POST"])
def addsearch(pid):
    c = get_db()
    c.execute("INSERT INTO job_searches (profile_id,keywords,location,job_type) VALUES (?,?,?,?)",(pid, request.form["keywords"], request.form["location"], "fulltime"))
    c.commit(); c.close()
    flash("Added!","success"); return redirect(f"/p/{pid}/edit")

@app.route("/s/<int:sid>/del")
def delsearch(sid):
    c = get_db()
    r = c.execute("SELECT profile_id FROM job_searches WHERE id=?",(sid,)).fetchone()
    c.execute("DELETE FROM job_searches WHERE id=?",(sid,))
    c.commit(); c.close()
    return redirect(f"/p/{r[0]}/edit" if r else "/")

@app.route("/j/<jid>/apply")
def japply(jid):
    c = get_db()
    c.execute("UPDATE jobs SET applied=1,applied_at=?,status='applied' WHERE id=?",(datetime.now().isoformat(),jid))
    r = c.execute("SELECT profile_id FROM jobs WHERE id=?",(jid,)).fetchone()
    c.commit(); c.close()
    return redirect(f"/p/{r[0]}/jobs" if r else "/")

@app.route("/j/<jid>/status", methods=["POST"])
def jstatus(jid):
    c = get_db()
    c.execute("UPDATE jobs SET status=? WHERE id=?",(request.form["st"],jid))
    r = c.execute("SELECT profile_id FROM jobs WHERE id=?",(jid,)).fetchone()
    c.commit(); c.close()
    return redirect(f"/p/{r[0]}/applied" if r else "/")

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files: return jsonify(ok=False, err="No file")
    f = request.files["file"]
    fn = (f.filename or "").lower()
    text = name = email = phone = ""
    try:
        if fn.endswith(".txt"):
            text = f.read().decode("utf-8", errors="ignore")
        elif fn.endswith(".pdf"):
            import pdfplumber
            with pdfplumber.open(io.BytesIO(f.read())) as pdf:
                text = "\n\n".join(pg.extract_text() or "" for pg in pdf.pages)
        elif fn.endswith((".docx", ".doc")):
            import docx
            doc = docx.Document(io.BytesIO(f.read()))
            text = "\n".join(p.text for p in doc.paragraphs if p.text.strip())
        else:
            return jsonify(ok=False, err="Use PDF, DOCX, or TXT")
        if not text.strip():
            return jsonify(ok=False, err="No text extracted. File may be scanned.")
        m = re.search(r'[\w.+-]+@[\w-]+\.[\w.]+', text)
        if m: email = m.group()
        m = re.search(r'[\+]?[(]?[0-9]{1,4}[)]?[-\s./0-9]{7,15}', text)
        if m: phone = m.group().strip()
        lines = [l.strip() for l in text.split("\n") if l.strip()]
        if lines and len(lines[0]) < 50 and "@" not in lines[0] and not any(c.isdigit() for c in lines[0]):
            name = lines[0]
        return jsonify(ok=True, text=text.strip(), name=name, email=email, phone=phone)
    except Exception as e:
        return jsonify(ok=False, err=str(e))


if __name__ == "__main__":
    ip = "localhost"
    try:
        import socket
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("8.8.8.8", 80)); ip = s.getsockname()[0]; s.close()
    except: pass
    print(f"\n{'='*60}")
    print(f"  ⚡ JobPilot GUI")
    print(f"  → http://{ip}:5000")
    print(f"  → http://jobpilot.local:5000")
    print(f"{'='*60}\n")
    app.run(host="0.0.0.0", port=5000, debug=False)
