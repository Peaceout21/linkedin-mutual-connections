#!/usr/bin/env bash
# Run once on a fresh Ubuntu/Debian VM to set up the project.
# Usage: bash setup_vm.sh

set -e

echo "=== Installing system deps ==="
sudo apt-get update -q
sudo apt-get install -y python3 python3-pip python3-venv curl

echo "=== Installing uv ==="
curl -LsSf https://astral.sh/uv/install.sh | sh
export PATH="$HOME/.local/bin:$PATH"

echo "=== Creating venv + installing Python deps ==="
uv venv
source .venv/bin/activate
uv pip install -e .

echo "=== Installing Playwright Chromium + system deps ==="
playwright install-deps chromium
playwright install chromium

echo ""
echo "=== Done! Next steps ==="
echo ""
echo "1. Copy your .env file from local machine:"
echo "   scp .env user@this-vm:$(pwd)/.env"
echo ""
echo "2. Copy your LinkedIn session cookies from local machine:"
echo "   scp linkedin_storage.json user@this-vm:$(pwd)/linkedin_storage.json"
echo "   (cookies are generated locally via: python save_cookies.py)"
echo ""
echo "3. Run:"
echo "   source .venv/bin/activate"
echo "   python mutual_connections.py --url 'https://www.linkedin.com/in/someprofile/' --save results.json"
