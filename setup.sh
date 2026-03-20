#!/usr/bin/env bash
# LinkedIn Scraper — one-time setup
# Usage: bash setup.sh
set -euo pipefail

REPO_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
VENV="$REPO_DIR/venv"
PLIST_NAME="com.frontier.linkedin-worker"
PLIST_DST="$HOME/Library/LaunchAgents/$PLIST_NAME.plist"

# ── Colours ───────────────────────────────────────────────────────────────────
green() { printf "\033[0;32m%s\033[0m\n" "$*"; }
yellow() { printf "\033[0;33m%s\033[0m\n" "$*"; }
red()   { printf "\033[0;31m%s\033[0m\n" "$*"; }
step()  { printf "\n\033[1;34m▶ %s\033[0m\n" "$*"; }

echo ""
green "================================================"
green " LinkedIn Scraper — Setup"
green "================================================"

# ── 1. Python version ─────────────────────────────────────────────────────────
step "Checking Python version"
PYTHON=$(command -v python3.13 || command -v python3.12 || command -v python3.11 || command -v python3 || true)
if [[ -z "$PYTHON" ]]; then
    red "Python 3.11+ not found. Install it from https://www.python.org/downloads/ and re-run."
    exit 1
fi

PY_VER=$("$PYTHON" -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
PY_MAJOR=$(echo "$PY_VER" | cut -d. -f1)
PY_MINOR=$(echo "$PY_VER" | cut -d. -f2)

if [[ "$PY_MAJOR" -lt 3 || ("$PY_MAJOR" -eq 3 && "$PY_MINOR" -lt 11) ]]; then
    red "Python 3.11+ required (found $PY_VER). Please upgrade."
    exit 1
fi
green "  Python $PY_VER — OK"

# ── 2. Virtual environment ────────────────────────────────────────────────────
step "Setting up virtual environment"
if [[ ! -d "$VENV" ]]; then
    "$PYTHON" -m venv "$VENV"
    green "  Created venv at $VENV"
else
    green "  venv already exists — skipping"
fi

PY="$VENV/bin/python"
PIP="$VENV/bin/pip"

# ── 3. Install Python dependencies ───────────────────────────────────────────
step "Installing Python dependencies"
"$PIP" install --upgrade pip --quiet
"$PIP" install -e "$REPO_DIR" --quiet
green "  Dependencies installed"

# ── 4. Install Playwright browser ────────────────────────────────────────────
step "Installing Playwright Chromium"
"$VENV/bin/playwright" install chromium
green "  Chromium installed"

# ── 5. .env file ─────────────────────────────────────────────────────────────
step "Checking .env"
if [[ ! -f "$REPO_DIR/.env" ]]; then
    cp "$REPO_DIR/.env.example" "$REPO_DIR/.env"
    yellow "  Created .env from .env.example"
fi

# Prompt for WORKER_NAME if still placeholder or missing
source <(grep -E '^(WORKER_NAME|NGROK_AUTHTOKEN|NGROK_DOMAIN)=' "$REPO_DIR/.env" 2>/dev/null || true)
if [[ -z "$WORKER_NAME" || "$WORKER_NAME" == "your-name-here" ]]; then
    read -r -p "  Enter a unique name for this machine (e.g. arjun-mbp): " INPUT_NAME
    INPUT_NAME="${INPUT_NAME:-$(whoami)-mac}"
    # Write it into .env (replace or append)
    if grep -q "^WORKER_NAME=" "$REPO_DIR/.env"; then
        sed -i '' "s/^WORKER_NAME=.*/WORKER_NAME=$INPUT_NAME/" "$REPO_DIR/.env"
    else
        echo "WORKER_NAME=$INPUT_NAME" >> "$REPO_DIR/.env"
    fi
    WORKER_NAME="$INPUT_NAME"
fi
green "  Worker name: $WORKER_NAME"

# ── 6. gcloud ADC ─────────────────────────────────────────────────────────────
step "Checking Google Cloud credentials"
if ! command -v gcloud &>/dev/null; then
    yellow "  gcloud not found. Install from https://cloud.google.com/sdk/docs/install"
    yellow "  Then run: gcloud auth application-default login"
elif [[ ! -f "$HOME/.config/gcloud/application_default_credentials.json" ]]; then
    yellow "  No Application Default Credentials found."
    yellow "  Run: gcloud auth application-default login"
    yellow "  Then re-run this script or proceed manually."
else
    green "  gcloud ADC found — OK"
fi

# ── 7. LinkedIn session cookies ───────────────────────────────────────────────
step "LinkedIn session cookies"
if [[ -f "$REPO_DIR/linkedin_storage.json" ]]; then
    green "  linkedin_storage.json already exists — skipping"
    yellow "  If your session expired, run: make cookies"
else
    yellow "  No session file found."
    read -r -p "  Set up LinkedIn cookies now? (y/N): " REPLY
    if [[ "${REPLY,,}" == "y" ]]; then
        "$PY" "$REPO_DIR/save_cookies.py"
    else
        yellow "  Skipping. Run 'make cookies' when ready."
    fi
fi

# ── 8. ngrok config ───────────────────────────────────────────────────────────
step "Setting up ngrok"
NGROK_CFG_DIR="$HOME/.config/ngrok"
NGROK_CFG="$NGROK_CFG_DIR/ngrok.yml"

# Re-read from .env in case it was just created
source <(grep -E '^(NGROK_AUTHTOKEN|NGROK_DOMAIN)=' "$REPO_DIR/.env" 2>/dev/null || true)

if [[ -z "$NGROK_AUTHTOKEN" || "$NGROK_AUTHTOKEN" == "your_ngrok_authtoken_here" ]]; then
    yellow "  NGROK_AUTHTOKEN not set in .env — skipping ngrok config."
    yellow "  Add it later and re-run setup.sh, or run: make ngrok-setup"
else
    mkdir -p "$NGROK_CFG_DIR"
    cat > "$NGROK_CFG" <<NGROK
version: "3"
agent:
  authtoken: $NGROK_AUTHTOKEN

tunnels:
  linkedin-api:
    proto: http
    addr: 8080
    domain: $NGROK_DOMAIN
NGROK
    green "  ngrok config written to $NGROK_CFG"
    green "  Start tunnel with: make ngrok"
fi

# ── 9. launchd worker agent ───────────────────────────────────────────────────
step "Setting up launchd worker (auto-start on login)"
mkdir -p "$HOME/Library/LaunchAgents"

cat > "$PLIST_DST" <<PLIST
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>$PLIST_NAME</string>

    <key>ProgramArguments</key>
    <array>
        <string>$VENV/bin/python</string>
        <string>$REPO_DIR/worker.py</string>
    </array>

    <key>WorkingDirectory</key>
    <string>$REPO_DIR</string>

    <key>RunAtLoad</key>
    <true/>

    <key>KeepAlive</key>
    <true/>

    <key>ThrottleInterval</key>
    <integer>10</integer>

    <key>ProcessType</key>
    <string>Background</string>

    <key>Nice</key>
    <integer>10</integer>

    <key>StandardOutPath</key>
    <string>$REPO_DIR/worker.log</string>

    <key>StandardErrorPath</key>
    <string>$REPO_DIR/worker.error.log</string>

    <key>EnvironmentVariables</key>
    <dict>
        <key>PATH</key>
        <string>/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin</string>
        <key>HOME</key>
        <string>$HOME</string>
    </dict>
</dict>
</plist>
PLIST

# Load (or reload) the agent
launchctl unload "$PLIST_DST" 2>/dev/null || true
launchctl load "$PLIST_DST"
green "  Worker agent installed and started"
green "  Logs: $REPO_DIR/worker.log"

# ── Done ──────────────────────────────────────────────────────────────────────
echo ""
green "================================================"
green " Setup complete!"
green "================================================"
echo ""
echo "  Next steps:"
echo "  1. Fill in .env with your keys (if not done)"
echo "  2. Run 'make cookies' to save your LinkedIn session"
echo "  3. Worker is already running in the background"
echo ""
echo "  Useful commands:"
echo "    make cookies       — refresh LinkedIn session"
echo "    make worker-logs   — tail worker output"
echo "    make worker-stop   — stop the background worker"
echo "    make worker-start  — start it again"
echo ""
