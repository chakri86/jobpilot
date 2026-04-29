#!/bin/bash
# ── JobPilot — one-command deploy to Raspberry Pi 5 ──────────────────────────
# Usage (from your laptop):  ./deploy.sh
set -e

PI="avkc@192.168.0.249"

echo "╔══════════════════════════════════════════╗"
echo "║  ⚡ JobPilot  →  Raspberry Pi 5 Deploy   ║"
echo "╚══════════════════════════════════════════╝"

# ── 1. Push latest code ───────────────────────────────────────────────────────
echo ""
echo "📤 Pushing to GitHub..."
cd "$(dirname "$0")"
git add -A
git commit -m "chore: deploy $(date '+%Y-%m-%d %H:%M')" 2>/dev/null || echo "  (nothing new to commit)"
git push origin main
echo "  ✓ Pushed"

# ── 2. Deploy on Pi ───────────────────────────────────────────────────────────
echo ""
echo "🍓 Deploying on Pi ($PI)..."
ssh "$PI" bash << 'REMOTE'
set -e

# Install Docker if missing
if ! command -v docker &>/dev/null; then
  echo "Installing Docker..."
  curl -fsSL https://get.docker.com | sh
  sudo usermod -aG docker "$USER"
  echo "✓ Docker installed — re-run this script once (group change needs new shell)"
  exit 0
fi

# Install Docker Compose plugin if missing
if ! docker compose version &>/dev/null 2>&1; then
  sudo apt-get update -qq
  sudo apt-get install -y -qq docker-compose-plugin
fi

# Clone or pull repo
if [ ! -d "$HOME/jobpilot" ]; then
  git clone https://github.com/chakri86/jobpilot.git "$HOME/jobpilot"
else
  cd "$HOME/jobpilot" && git pull --ff-only
fi

cd "$HOME/jobpilot"
mkdir -p data logs monitoring

# Stop old containers
docker compose down --remove-orphans 2>/dev/null || true

# Build + start (ARM64 native build, ~3-5 min first time)
echo "Building images..."
docker compose build --no-cache
docker compose up -d

# Health check
echo "Waiting for app..."
sleep 20
if curl -sf http://localhost:5000/health > /dev/null; then
  IP=$(hostname -I | awk '{print $1}')
  echo ""
  echo "════════════════════════════════════════════"
  echo "  ✅  JobPilot is live!"
  echo ""
  echo "  Dashboard  →  http://$IP:5000"
  echo "  Grafana    →  http://$IP:3000  (admin / admin)"
  echo "  Prometheus →  http://$IP:9090"
  echo "  Uptime     →  http://$IP:3001"
  echo "════════════════════════════════════════════"
else
  echo "⚠ Health check failed — last 40 lines of app log:"
  docker compose logs --tail=40 jobpilot-app
  exit 1
fi

docker compose ps
REMOTE
