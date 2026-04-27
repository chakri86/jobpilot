# ⚡ JobPilot

AI-powered job automation bot that runs 24/7 on a Raspberry Pi (or any Linux machine).

## Features
- 🔍 Auto-searches Indeed & LinkedIn every 15 minutes
- 🤖 AI scores each job against your resume (0-100)
- 📧 Instant Email + Telegram alerts for high matches
- 📎 Upload PDF/Word resumes — auto-parsed
- 👥 Multiple profiles (family, friends, different job searches)
- 📊 Web dashboard accessible from any device
- 🔄 Auto-updates from Git daily

## One-Command Install

```bash
git clone https://github.com/YOUR_USERNAME/jobpilot.git ~/jobpilot
cd ~/jobpilot && chmod +x install.sh && ./install.sh
```

## Update

```bash
cd ~/jobpilot && ./install.sh update
```

## Access

Open in any browser: `http://YOUR_PI_IP:5000`

## Requirements
- Raspberry Pi (any model) or any Linux machine
- Python 3.9+
- Anthropic API key (~$3-10/month)

## Project Structure
```
jobpilot/
├── app.py          # Web GUI dashboard
├── bot.py          # Job search/score/notify engine
├── install.sh      # One-command installer
├── requirements.txt
├── data/           # SQLite database (auto-created)
└── logs/           # Log files (auto-created)
```
