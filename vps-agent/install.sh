#!/usr/bin/env bash

# SonicForge VPS Agent — one-shot installer for Ubuntu 22.04 / 24.04 / Debian 12
#
# Usage (run on the VPS as root):
#   curl -fsSL https://raw.githubusercontent.com/<your-fork>/main/vps-agent/install.sh | \
#       AGENT_SECRET="long-random-string" \
#       BOT_REPO_URL="https://github.com/srnw57569m/mu.git" \
#       bash
#
# Or, if you scp'd this folder to the VPS, just:
#   cd vps-agent && AGENT_SECRET=... BOT_REPO_URL=... bash install.sh

set -euo pipefail

if [[ $EUID -ne 0 ]]; then
  echo "Please run as root (use sudo)."; exit 1
fi
if [[ -z "${AGENT_SECRET:-}" ]]; then
  echo "AGENT_SECRET env var is required."; exit 1
fi
if [[ -z "${BOT_REPO_URL:-}" ]]; then
  echo "BOT_REPO_URL env var is required."; exit 1
fi

PORT="${PORT:-8787}"
INSTALL_DIR="/opt/sonicforge-agent"

echo "==> Installing system packages…"
apt-get update -y
apt-get install -y curl git ffmpeg python3 python3-pip python3-venv python3.11 python3.11-venv build-essential ca-certificates


echo "==> Installing Node.js 20…"
if ! command -v node >/dev/null 2>&1; then
  curl -fsSL https://deb.nodesource.com/setup_20.x | bash -
  apt-get install -y nodejs
fi

echo "==> Installing pm2 globally…"
npm install -g pm2

echo "==> Setting up $INSTALL_DIR…"
mkdir -p "$INSTALL_DIR"

# If install.sh was run from inside the vps-agent folder, copy files in.
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
if [[ -f "$SCRIPT_DIR/index.js" ]]; then
  cp "$SCRIPT_DIR/index.js" "$SCRIPT_DIR/package.json" "$INSTALL_DIR/"
else
  echo "==> Downloading agent files from GitHub…"
  RAW_BASE="${RAW_BASE:-}"
  if [[ -z "$RAW_BASE" ]]; then
    echo "RAW_BASE not set. Either run install.sh from inside the vps-agent/ folder, or set RAW_BASE to the raw-content base URL of your fork (e.g. https://raw.githubusercontent.com/you/repo/main/vps-agent)."
    exit 1
  fi
  curl -fsSL "$RAW_BASE/index.js" -o "$INSTALL_DIR/index.js"
  curl -fsSL "$RAW_BASE/package.json" -o "$INSTALL_DIR/package.json"
fi

cd "$INSTALL_DIR"
echo "==> Installing Node deps…"
npm install --omit=dev

echo "==> Writing $INSTALL_DIR/.env…"
cat > "$INSTALL_DIR/.env" <<EOF
AGENT_SECRET=$AGENT_SECRET
BOT_REPO_URL=$BOT_REPO_URL
PORT=$PORT
BOTS_DIR=$INSTALL_DIR/bots
PYTHON=python3
PYTHON_311=python3.11

EOF
chmod 600 "$INSTALL_DIR/.env"
mkdir -p "$INSTALL_DIR/bots"

echo "==> Installing systemd unit…"
cat > /etc/systemd/system/sonicforge-agent.service <<EOF
[Unit]
Description=SonicForge Bot Agent
After=network.target

[Service]
Type=simple
WorkingDirectory=$INSTALL_DIR
EnvironmentFile=$INSTALL_DIR/.env
ExecStart=/usr/bin/node $INSTALL_DIR/index.js
Restart=always
RestartSec=3
User=root

[Install]
WantedBy=multi-user.target
EOF

echo "==> Opening firewall on port $PORT (if ufw is active)…"
if command -v ufw >/dev/null 2>&1 && ufw status | grep -q "Status: active"; then
  ufw allow "$PORT"/tcp || true
fi

systemctl daemon-reload
systemctl enable --now sonicforge-agent
sleep 2

echo
echo "==> Health check:"
curl -fsS "http://127.0.0.1:$PORT/health" || (echo "Agent did not respond — check 'systemctl status sonicforge-agent' and 'journalctl -u sonicforge-agent -n 100'"; exit 1)
echo
echo
echo "Done!  Agent is running on port $PORT."
echo "From your laptop, point the Lovable app at:  http://$(curl -s ifconfig.me):$PORT"
