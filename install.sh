#!/bin/bash
# ═══════════════════════════════════════════════════════════════
# JobPilot - One Command Install & Update
# ═══════════════════════════════════════════════════════════════
#
# FRESH INSTALL:  curl -sSL https://raw.githubusercontent.com/YOUR_USERNAME/jobpilot/main/install.sh | bash
# OR:             git clone https://github.com/YOUR_USERNAME/jobpilot.git && cd jobpilot && ./install.sh
#
# UPDATE:         cd ~/jobpilot && ./install.sh update
# ═══════════════════════════════════════════════════════════════

set -e
APP_DIR="$HOME/jobpilot"
VENV_DIR="$APP_DIR/venv"
DATA_DIR="$APP_DIR/data"
LOG_DIR="$APP_DIR/logs"

RED='\033[0;31m'; GREEN='\033[0;32m'; BLUE='\033[0;34m'; YELLOW='\033[1;33m'; NC='\033[0m'

print_banner() {
    echo ""
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo -e "${BLUE}  ⚡ JobPilot Installer${NC}"
    echo -e "${BLUE}═══════════════════════════════════════════════${NC}"
    echo ""
}

# ── UPDATE MODE ──
if [ "$1" = "update" ]; then
    echo -e "${YELLOW}🔄 Updating JobPilot...${NC}"
    cd "$APP_DIR"
    git pull origin main
    source "$VENV_DIR/bin/activate"
    pip install -r requirements.txt -q
    sudo systemctl restart jobpilot-gui 2>/dev/null || true
    sudo systemctl restart jobpilot-bot 2>/dev/null || true
    echo -e "${GREEN}✅ Updated! Dashboard restarted.${NC}"
    exit 0
fi

print_banner

# ── STEP 1: System packages ──
echo -e "${BLUE}[1/6]${NC} Installing system packages..."
sudo apt update -qq
sudo apt install -y -qq python3 python3-pip python3-venv git avahi-daemon > /dev/null 2>&1
sudo systemctl enable avahi-daemon > /dev/null 2>&1
sudo systemctl start avahi-daemon > /dev/null 2>&1

# ── STEP 2: Fix hostname ──
echo -e "${BLUE}[2/6]${NC} Setting hostname..."
sudo hostnamectl set-hostname jobpilot 2>/dev/null || true
grep -q "jobpilot" /etc/hosts || sudo sh -c 'echo "127.0.1.1 jobpilot" >> /etc/hosts'

# ── STEP 3: Setup directories ──
echo -e "${BLUE}[3/6]${NC} Setting up project..."
mkdir -p "$DATA_DIR" "$LOG_DIR"

# ── STEP 4: Python environment ──
echo -e "${BLUE}[4/6]${NC} Creating Python environment..."
if [ ! -d "$VENV_DIR" ]; then
    python3 -m venv "$VENV_DIR"
fi
source "$VENV_DIR/bin/activate"
pip install -r "$APP_DIR/requirements.txt" -q

# ── STEP 5: Systemd services ──
echo -e "${BLUE}[5/6]${NC} Creating system services..."

# GUI Dashboard service
sudo tee /etc/systemd/system/jobpilot-gui.service > /dev/null << EOF
[Unit]
Description=JobPilot Web GUI
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python3 $APP_DIR/app.py
Restart=always
RestartSec=10
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Bot service
sudo tee /etc/systemd/system/jobpilot-bot.service > /dev/null << EOF
[Unit]
Description=JobPilot Job Search Bot
After=network-online.target jobpilot-gui.service
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=$VENV_DIR/bin/python3 $APP_DIR/bot.py
Restart=always
RestartSec=60
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
EOF

# Auto-updater (checks for git updates daily at 3am)
sudo tee /etc/systemd/system/jobpilot-update.service > /dev/null << EOF
[Unit]
Description=JobPilot Auto Updater

[Service]
Type=oneshot
User=$USER
WorkingDirectory=$APP_DIR
ExecStart=/bin/bash -c 'cd $APP_DIR && git pull origin main && $VENV_DIR/bin/pip install -r requirements.txt -q && sudo systemctl restart jobpilot-gui && sudo systemctl restart jobpilot-bot'
EOF

sudo tee /etc/systemd/system/jobpilot-update.timer > /dev/null << EOF
[Unit]
Description=Daily JobPilot update check

[Timer]
OnCalendar=*-*-* 03:00:00
Persistent=true

[Install]
WantedBy=timers.target
EOF

sudo systemctl daemon-reload

# ── STEP 6: Start services ──
echo -e "${BLUE}[6/6]${NC} Starting services..."
sudo systemctl enable jobpilot-gui > /dev/null 2>&1
sudo systemctl start jobpilot-gui
sudo systemctl enable jobpilot-update.timer > /dev/null 2>&1
sudo systemctl start jobpilot-update.timer

# Get IP address
IP=$(hostname -I | awk '{print $1}')

echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo -e "${GREEN}  ✅ JobPilot Installed!${NC}"
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
echo ""
echo -e "  🌐 Open your browser:"
echo -e "     ${BLUE}→ http://$IP:5000${NC}"
echo -e "     ${BLUE}→ http://jobpilot.local:5000${NC}"
echo ""
echo -e "  📱 Works on laptop, phone, tablet"
echo -e "     Everything is done through the GUI!"
echo ""
echo -e "  Useful commands:"
echo -e "     ${YELLOW}cd ~/jobpilot && ./install.sh update${NC}  — pull latest"
echo -e "     ${YELLOW}sudo systemctl status jobpilot-gui${NC}   — check status"
echo -e "     ${YELLOW}sudo systemctl restart jobpilot-gui${NC}  — restart"
echo -e "     ${YELLOW}tail -f ~/jobpilot/logs/bot.log${NC}      — watch logs"
echo ""
echo -e "${GREEN}═══════════════════════════════════════════════${NC}"
