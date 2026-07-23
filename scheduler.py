"""PRZ Scanner — Python Scheduler untuk VPS.

Menjalankan scan otomatis setiap hari kerja jam 18:00 WIB:
  - Daily  : Senin-Jumat jam 18:00 WIB
  - Weekly : Jumat jam 18:05 WIB (setelah daily selesai)

Cara jalankan di VPS:
  python scheduler.py

Agar tetap berjalan setelah SSH terputus, gunakan screen/tmux/systemd:
  screen -S prz
  python scheduler.py
  Ctrl+A, D  (detach)

Atau gunakan crontab (lihat crontab.example) untuk alternatif yang lebih ringan.
"""

import subprocess
import sys
import os
import logging
from datetime import datetime

try:
    import schedule
    import time
except ImportError:
    print("[ERROR] Library 'schedule' belum terinstall.")
    print("        Jalankan: pip install schedule")
    sys.exit(1)

# ── Setup logging ────────────────────────────────────────────────────────────

os.makedirs("logs", exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler("logs/scheduler.log", encoding="utf-8"),
        logging.StreamHandler(sys.stdout),
    ],
)
log = logging.getLogger("prz.scheduler")

# ── Runner helper ────────────────────────────────────────────────────────────

PYTHON = sys.executable   # same python env as this script
BASE_DIR = os.path.dirname(os.path.abspath(__file__))


def _run(script: str, label: str, extra_args=()):
    """Run a scanner script as subprocess, stream output to log."""
    log.info(f"{'='*50}")
    log.info(f"START: {label}")
    log.info(f"{'='*50}")
    cmd = [PYTHON, os.path.join(BASE_DIR, script),
           "--telegram", "--images-only", "--cleanup", *extra_args]
    try:
        result = subprocess.run(
            cmd,
            cwd=BASE_DIR,
            capture_output=False,   # output langsung ke terminal/log
            text=True,
        )
        if result.returncode == 0:
            log.info(f"DONE: {label} (exit 0)")
        else:
            log.error(f"FAIL: {label} (exit {result.returncode})")
    except Exception as e:
        log.error(f"ERROR: {label}: {e}")


def job_daily():
    # --quality: subset teruji backtest 5 tahun (Crab+Bat, confluence >=2 —
    # 58% win, +0.16R). Hapus flag ini untuk kembali ke semua pola.
    _run("run_daily.py", "Daily Scan (quality)", extra_args=("--quality",))


def job_weekly():
    # Weekly tetap semua pola: bukti backtest baru mencakup Daily.
    _run("run_weekly.py", "Weekly Scan")


# ── Schedule ─────────────────────────────────────────────────────────────────
# Waktu dalam LOCAL TIME VPS.
# Pastikan timezone VPS = Asia/Jakarta (WIB, UTC+7).
# Cek: timedatectl   atau   date
# Set : sudo timedatectl set-timezone Asia/Jakarta

DAILY_TIME  = "18:00"   # Senin-Jumat
WEEKLY_TIME = "18:05"   # Jumat saja (setelah daily selesai)

schedule.every().monday.at(DAILY_TIME).do(job_daily)
schedule.every().tuesday.at(DAILY_TIME).do(job_daily)
schedule.every().wednesday.at(DAILY_TIME).do(job_daily)
schedule.every().thursday.at(DAILY_TIME).do(job_daily)
schedule.every().friday.at(DAILY_TIME).do(job_daily)
schedule.every().friday.at(WEEKLY_TIME).do(job_weekly)

# ── Main loop ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    log.info("PRZ Scheduler started.")
    log.info(f"  Daily  scan: Senin-Jumat {DAILY_TIME} WIB")
    log.info(f"  Weekly scan: Jumat       {WEEKLY_TIME} WIB")
    log.info(f"  Python: {PYTHON}")
    log.info(f"  Base dir: {BASE_DIR}")
    log.info("Waiting for scheduled jobs... (Ctrl+C to stop)")

    while True:
        schedule.run_pending()
        time.sleep(30)
