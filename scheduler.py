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
import time
import logging
from datetime import datetime, timezone, timedelta

# WIB eksplisit (UTC+7). TIDAK bergantung pada timezone sistem / tzdata —
# banyak container (mis. Railway/Nixpacks) tidak punya database zoneinfo,
# sehingga TZ=Asia/Jakarta diam-diam jatuh ke UTC dan jadwal meleset 7 jam.
# Menghitung WIB dari UTC memastikan 18:00 selalu = 18:00 WIB di mana pun.
WIB = timezone(timedelta(hours=7), "WIB")


def now_wib() -> datetime:
    return datetime.now(timezone.utc).astimezone(WIB)

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
    # Kirim SEMUA pola yang mendekati/di dalam PRZ (permintaan Rio).
    # Tambahkan "--quality" di extra_args untuk kembali ke subset teruji
    # backtest (Crab+Bat conf>=2 — 58% win, +0.16R).
    _run("run_daily.py", "Daily Scan")


def job_weekly():
    # Weekly tetap semua pola: bukti backtest baru mencakup Daily.
    _run("run_weekly.py", "Weekly Scan")


# ── Schedule (WIB eksplisit) ─────────────────────────────────────────────────
# Tiap job: (hari_WIB, jam, menit, fungsi). Monday=0 .. Sunday=6.
JOBS = [
    ({0, 1, 2, 3, 4}, 18, 0, "Daily",  job_daily),   # Senin-Jumat 18:00 WIB
    ({4},             18, 5, "Weekly", job_weekly),  # Jumat 18:05 WIB
]

# ── Main loop ────────────────────────────────────────────────────────────────

if __name__ == "__main__":
    t0 = now_wib()
    log.info("PRZ Scheduler started.")
    log.info(f"  Sekarang   : {t0:%Y-%m-%d %H:%M:%S} WIB "
             f"({datetime.now(timezone.utc):%H:%M} UTC)")
    log.info("  Daily  scan: Senin-Jumat 18:00 WIB")
    log.info("  Weekly scan: Jumat       18:05 WIB")
    log.info(f"  Python: {PYTHON}")
    log.info("Menunggu jadwal (WIB dihitung eksplisit UTC+7)... Ctrl+C untuk stop")

    last_run = {}   # index job -> tanggal WIB terakhir dijalankan
    while True:
        t = now_wib()
        for i, (days, hh, mm, label, fn) in enumerate(JOBS):
            if t.weekday() in days and t.hour == hh and t.minute == mm:
                if last_run.get(i) != t.date():
                    last_run[i] = t.date()   # cegah dobel dalam menit yang sama
                    fn()
        time.sleep(20)   # cek ~3x/menit -> pasti kena menit target
