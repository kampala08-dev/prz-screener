#!/bin/bash
# PRZ Scanner - VPS Setup Script
# ================================
# Teruji: Ubuntu 22.04/24.04, Debian 11/12 (Tencent Cloud Lighthouse dll).
# Jalankan di VPS:  bash setup_vps.sh
#
# Script ini:
#   1. Install system dependencies (python3, venv, git, build tools)
#   2. Clone / update repo (dari fork kampala08-dev)
#   3. Buat venv + install Python dependencies
#   4. Setup .env dari .env.example
#   5. Set timezone WIB (Asia/Jakarta)
#   6. Buat folder logs/ & output/
#   7. Pasang systemd service (auto-start saat boot + auto-restart)
#   8. Tampilkan langkah terakhir

set -e

# Repo: fork yang terpelihara (berisi semua perbaikan). Ganti bila perlu.
REPO_URL="https://github.com/kampala08-dev/prz-screener.git"
REPO_DIR="$HOME/prz-screener"
SERVICE_USER="$(whoami)"

echo "========================================"
echo "  PRZ Scanner - VPS Setup"
echo "========================================"

# 1. System dependencies
echo "[1/8] Install system dependencies..."
sudo apt-get update -qq
sudo apt-get install -y python3 python3-pip python3-venv git \
    build-essential pkg-config libfreetype6-dev

# 2. Clone or update repo
if [ -d "$REPO_DIR/.git" ]; then
    echo "[2/8] Repo sudah ada, pull latest..."
    cd "$REPO_DIR" && git pull --ff-only origin main
else
    echo "[2/8] Clone repo dari $REPO_URL ..."
    git clone "$REPO_URL" "$REPO_DIR"
fi
cd "$REPO_DIR"

# 3. Python venv + dependencies
echo "[3/8] Buat virtualenv & install dependencies..."
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip -q
pip install -r requirements.txt -q
echo "      Dependencies terpasang."

# 4. .env setup
echo "[4/8] Setup .env..."
if [ ! -f .env ]; then
    cp .env.example .env
    echo "      .env dibuat dari .env.example — WAJIB diedit (token & chat id)."
else
    echo "      .env sudah ada, skip."
fi

# 5. Timezone (VPS punya tzdata; scheduler juga hitung WIB eksplisit)
echo "[5/8] Set timezone Asia/Jakarta (WIB)..."
sudo timedatectl set-timezone Asia/Jakarta || true
echo "      Timezone: $(cat /etc/timezone 2>/dev/null || date +%Z)"

# 6. Folders
echo "[6/8] Buat folder logs/ & output/..."
mkdir -p logs output/daily output/weekly output/h4

# 7. systemd service (auto-start + auto-restart)
echo "[7/8] Pasang systemd service prz-screener..."
sudo tee /etc/systemd/system/prz-screener.service > /dev/null <<SERVICE
[Unit]
Description=PRZ Screener Scheduler (scan harian -> Telegram)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$SERVICE_USER
WorkingDirectory=$REPO_DIR
ExecStart=$REPO_DIR/venv/bin/python $REPO_DIR/scheduler.py
Restart=always
RestartSec=30
Environment=PYTHONUNBUFFERED=1

[Install]
WantedBy=multi-user.target
SERVICE
sudo systemctl daemon-reload
echo "      Service terpasang (belum di-start — isi .env dulu)."

# 8. Langkah terakhir
echo ""
echo "[8/8] Setup selesai!"
echo "========================================"
echo "  LANGKAH TERAKHIR"
echo "========================================"
echo ""
echo "  1) Isi kredensial Telegram:"
echo "       nano $REPO_DIR/.env"
echo "     (TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID=-1004409180438)"
echo ""
echo "  2) Tes manual dulu (pastikan TradingView jalan dari IP VPS):"
echo "       cd $REPO_DIR && source venv/bin/activate"
echo "       python run_daily.py --tickers BBCA BMRI --telegram --images-only"
echo ""
echo "  3) Nyalakan scheduler 24/7 (auto-start saat boot):"
echo "       sudo systemctl enable --now prz-screener"
echo ""
echo "  Cek status / log:"
echo "       systemctl status prz-screener"
echo "       journalctl -u prz-screener -f"
echo ""
echo "  (Scheduler kirim scan Senin-Jumat 18:00 WIB, Weekly Jumat 18:05 WIB.)"
echo ""
