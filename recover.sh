#!/bin/bash
# Marketior Recovery Script
# Run on ANY fresh Debian/Ubuntu VPS with rclone configured
# Usage: bash recover.sh

set -e
echo "=========================================="
echo "  Marketior Recovery from Google Drive"
echo "=========================================="

# Check rclone
if ! command -v rclone &> /dev/null; then
    echo "ERROR: rclone is not installed. Install it first:"
    echo "  curl https://rclone.org/install.sh | sudo bash"
    exit 1
fi

# Check remote
if ! rclone listremotes | grep -q "hermes-gdrive:"; then
    echo "ERROR: hermes-gdrive: remote not configured. Run: rclone config"
    exit 1
fi

# Sync from Google Drive
echo "[1/2] Syncing from Google Drive..."
rclone sync hermes-gdrive:marketior/ ~/marketior/ --progress

# Run deploy
echo "[2/2] Running deployment..."
cd ~/marketior
bash deploy.sh

echo ""
echo "✅ Recovery complete! Marketior is live at https://ai.marketior.com"
