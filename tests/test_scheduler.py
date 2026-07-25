"""Unit test scheduler — jendela due + kontrak flag scheduler<->runner.

Latar: bug produksi nyata (review 2026-07-25):
  1. scheduler meneruskan --cleanup ke run_weekly.py yang parser-nya tidak
     mendefinisikan flag itu -> argparse exit 2 -> weekly TIDAK PERNAH jalan.
  2. Loop lama mencocokkan menit-eksak (t.minute == mm) sementara job daily
     17:00 blocking >5 menit -> weekly Jumat 17:05 selalu terlewat (starved).

Test di sini mengunci dua kontrak itu agar tidak regresi.
"""

import os
import sys
from datetime import datetime, timedelta

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import scheduler


def _day(weekday_target: int) -> datetime:
    """Tanggal pertama di 2026 dengan weekday tertentu (Mon=0..Sun=6), WIB."""
    d = datetime(2026, 1, 1, tzinfo=scheduler.WIB)
    while d.weekday() != weekday_target:
        d += timedelta(days=1)
    return d


FRI = _day(4)
SAT = _day(5)


# ---------------------------------------------------------------------------
# is_due — jendela due + grace
# ---------------------------------------------------------------------------
def test_due_pada_menit_eksak():
    t = FRI.replace(hour=17, minute=5)
    assert scheduler.is_due(t, {4}, 17, 5, None)


def test_due_dalam_grace_setelah_daily_blocking():
    # Kasus starvation produksi: daily 17:00 selesai 17:25 -> weekly 17:05
    # harus TETAP due saat loop bebas kembali.
    t = FRI.replace(hour=17, minute=25)
    assert scheduler.is_due(t, {4}, 17, 5, None)


def test_due_tepat_di_batas_grace():
    t = FRI.replace(hour=17, minute=5) + scheduler.GRACE
    assert scheduler.is_due(t, {4}, 17, 5, None)


def test_tidak_due_lewat_grace():
    t = FRI.replace(hour=17, minute=5) + scheduler.GRACE + timedelta(minutes=1)
    assert not scheduler.is_due(t, {4}, 17, 5, None)


def test_tidak_due_hari_salah():
    t = SAT.replace(hour=17, minute=5)
    assert not scheduler.is_due(t, {4}, 17, 5, None)


def test_tidak_due_sebelum_jadwal():
    t = FRI.replace(hour=17, minute=4)
    assert not scheduler.is_due(t, {4}, 17, 5, None)


def test_dedup_sudah_jalan_hari_ini():
    t = FRI.replace(hour=17, minute=25)
    assert not scheduler.is_due(t, {4}, 17, 5, t.date())


def test_due_lagi_minggu_berikutnya():
    t = FRI.replace(hour=17, minute=5)
    last = (t - timedelta(days=7)).date()
    assert scheduler.is_due(t, {4}, 17, 5, last)


def test_grace_cukup_untuk_durasi_daily_realistis():
    # Daily full-universe ~20-30 menit; grace wajib >= 60 menit agar weekly
    # 17:05 tidak pernah starved oleh daily 17:00.
    assert scheduler.GRACE >= timedelta(minutes=60)


def test_jobs_schedule_sesuai_kontrak():
    jobs = [(frozenset(days), hh, mm, label)
            for days, hh, mm, label, _fn in scheduler.JOBS]
    assert (frozenset({0, 1, 2, 3, 4}), 12, 0, "Daily") in jobs
    assert (frozenset({0, 1, 2, 3, 4}), 17, 0, "Daily") in jobs
    assert (frozenset({4}), 17, 5, "Weekly") in jobs


# ---------------------------------------------------------------------------
# Kontrak flag: scheduler._run selalu kirim --telegram --images-only --cleanup
# ke SEMUA runner -> parser tiap runner WAJIB menerimanya tanpa exit 2.
# ---------------------------------------------------------------------------
_SCHEDULER_FLAGS = ["--telegram", "--images-only", "--cleanup"]


def test_run_daily_menerima_flag_scheduler():
    import run_daily
    a = run_daily.parse_args(_SCHEDULER_FLAGS + ["--sentiment"])
    assert a.telegram and a.images_only and a.cleanup and a.sentiment


def test_run_weekly_menerima_flag_scheduler():
    # Regresi CRITICAL: --cleanup dulu tidak terdefinisi -> argparse exit 2,
    # weekly scan mati total setiap Jumat.
    import run_weekly
    a = run_weekly.parse_args(_SCHEDULER_FLAGS)
    assert a.telegram and a.images_only and a.cleanup


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        try:
            fn()
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
