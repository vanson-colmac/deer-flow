#!/bin/bash
# Marketior Deploy Script
# Run on VPS after rclone sync from Google Drive
# Usage: cd ~/marketior && bash deploy.sh

set -e
echo "=========================================="
echo "  Marketior Deployment"
echo "=========================================="

MARKETIOR_DIR="$HOME/marketior"
cd "$MARKETIOR_DIR"

# 1. Install system deps
echo ""
echo "[1/7] Installing system dependencies..."
sudo apt update -qq
sudo apt install -y -qq python3-venv python3-pip certbot python3-certbot-apache

# 2. Setup Python environment
echo ""
echo "[2/7] Setting up Python environment..."
cd "$MARKETIOR_DIR/backend"
if [ ! -d ".venv" ]; then
    python3 -m venv .venv
fi
source .venv/bin/activate
pip install -q uv
uv sync --all-packages 2>&1 | tail -3

# 3. Install frontend dependencies
echo ""
echo "[3/7] Installing frontend dependencies..."
cd "$MARKETIOR_DIR/frontend"
if command -v pnpm &> /dev/null; then
    pnpm install --frozen-lockfile 2>&1 | tail -3
else
    npm install -g pnpm
    pnpm install --frozen-lockfile 2>&1 | tail -3
fi

# 4. Build frontend for production
echo ""
echo "[4/7] Building frontend (this may take a few minutes)..."
NODE_OPTIONS=--max-old-space-size=256 npx next build 2>&1 | tail -5

# 5. Install systemd services
echo ""
echo "[5/7] Installing systemd services..."
sudo cp "$MARKETIOR_DIR/marketior.service" /etc/systemd/system/
sudo cp "$MARKETIOR_DIR/marketior-frontend.service" /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable marketior marketior-frontend
sudo systemctl restart marketior
sleep 3
sudo systemctl restart marketior-frontend

# 6. Setup Apache
echo ""
echo "[6/7] Configuring Apache..."
sudo a2enmod proxy proxy_http proxy_wstunnel rewrite headers ssl 2>/dev/null || true
sudo cp "$MARKETIOR_DIR/ai.marketior.com.conf" /etc/apache2/sites-available/
sudo a2ensite ai.marketior.com.conf 2>/dev/null || true
sudo systemctl reload apache2

# 7. Setup SSL (skip if cert already exists)
echo ""
echo "[7/7] Setting up SSL..."
if [ ! -d "/etc/letsencrypt/live/ai.marketior.com" ]; then
    sudo certbot --apache -d ai.marketior.com --non-interactive --agree-tos --register-unsafely-without-email || echo "⚠ SSL setup failed - make sure DNS A record points to this server"
else
    echo "SSL certificate already exists"
fi

# 8. Setup cron for data backup
echo ""
echo "Setting up backup cron..."
(crontab -l 2>/dev/null | grep -v "marketior"; cat <<'EOF'
# Marketior data backup to Google Drive (every 15 min)
*/15 * * * * rclone sync /home/market/marketior/memory.json hermes-gdrive:marketior/memory.json 2>/dev/null
*/15 * * * * rclone sync /home/market/marketior/.marketior/ hermes-gdrive:marketior/.marketior/ 2>/dev/null
# Marketior config backup (daily at 3am)
0 3 * * * rclone sync /home/market/marketior/config.yaml hermes-gdrive:marketior/config.yaml 2>/dev/null
0 3 * * * rclone sync /home/market/marketior/.env hermes-gdrive:marketior/.env 2>/dev/null
0 3 * * * rclone sync /home/market/marketior/skills/ hermes-gdrive:marketior/skills/ 2>/dev/null
EOF
) | crontab -

echo ""
echo "=========================================="
echo "  ✅ Marketior is deployed!"
echo "=========================================="
echo ""
echo "  🌐 https://ai.marketior.com"
echo ""
echo "  Services:"
echo "    Gateway:  systemctl status marketior"
echo "    Frontend: systemctl status marketior-frontend"
echo ""
echo "  RAM Usage:"
systemctl show marketior --property=MemoryCurrent 2>/dev/null || true
systemctl show marketior-frontend --property=MemoryCurrent 2>/dev/null || true
echo ""
