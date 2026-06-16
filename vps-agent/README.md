# SonicForge VPS Agent

Tiny Node service that lives on your Ubuntu VPS and runs your music bots as `pm2` processes. The Lovable app calls it over HTTP with a shared secret.

## 1. One-line install on the VPS

SSH into your fresh VPS as root, then:

```bash
# Generate a long random shared secret first (do this once, save it):
openssl rand -hex 32

# Copy the vps-agent folder to the server (one option):
#   scp -r vps-agent root@YOUR_VPS_IP:/root/
# Then:
cd /root/vps-agent
AGENT_SECRET="paste-the-secret-from-above" \
BOT_REPO_URL="https://github.com/srnw57569m/mu.git" \
bash install.sh
```

At the end it prints `http://<your-ip>:8787` — that's the URL the Lovable app will call.

## 2. Tell the Lovable app where to reach it

In the Lovable project, add two secrets:

- `VPS_AGENT_URL` — e.g. `http://203.0.113.42:8787`
- `VPS_AGENT_SECRET` — the same long random string you used above

## 3. Done

- Creating a bot in the dashboard → deploys it to the VPS (fresh `git clone` of the template + `config.json` injected).
- Start / Stop / Restart buttons → real `pm2` commands.
- Live console + CPU/RAM stats → real numbers from `pm2`.

## Maintenance

- View agent logs: `journalctl -u sonicforge-agent -f`
- Restart the agent: `systemctl restart sonicforge-agent`
- List running bots: `pm2 list`
- Bot folders live in `/opt/sonicforge-agent/bots/<botId>/`