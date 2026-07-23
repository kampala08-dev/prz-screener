"""Unit tests for the walk-forward backtest engine.

Covers the conservative simulation semantics:
  - TP3 rally path with correct R multiple
  - SL path with gap-aware stop fill
  - same-bar TP+SL ambiguity resolved as SL (conservative)
  - PRZ touches BEFORE pattern confirmation are not tradeable
  - gap straight through the zone is skipped (un-fillable)
  - TP1-then-flat exits as a TP1 win at the TP1 level
  - scan_points all_windows finds historical (non-tail) patterns

Runnable standalone (`python tests/test_backtest.py`) or via pytest.
"""

import os
import sys

import numpy as np
import pandas as pd

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prz_scanner.backtest import simulate_trade
from prz_scanner.config import Config
from prz_scanner.patterns import Detection, scan_points


# ---------------------------------------------------------------------------
def _mk_det(**over) -> Detection:
    d = Detection(ticker="T", pattern="Gartley", color="green", bull=True,
                  depth=3, is_strict=True,
                  xi=0, xP=80.0, ai=2, aP=120.0, bi=4, bP=95.0,
                  ci=5, cP=112.0, prz_hi=100.0, prz_lo=95.0,
                  br=0.625, cr=0.68, bcp=0.68)
    d.stop = 90.0
    d.tp1, d.tp2, d.tp3 = 110.0, 120.0, 130.0
    d.conf_n, d.score = 2, 75.0
    for k, v in over.items():
        setattr(d, k, v)
    return d


def _df(bars) -> pd.DataFrame:
    """bars: list of (open, high, low, close)."""
    idx = pd.date_range("2024-01-01", periods=len(bars), freq="D")
    return pd.DataFrame(
        [{"Open": o, "High": h, "Low": l, "Close": c}
         for o, h, l, c in bars], index=idx)


def _flat(n, px=105.0):
    return [(px, px + 1, px - 1, px)] * n


# ---------------------------------------------------------------------------
def test_tp3_path_policy_r_and_envelope():
    bars = _flat(9)                                # bars 0-8 (confirm=8)
    bars += [(104, 105, 98, 103)]                  # 9: touch -> entry 100
    bars += [(103, 111, 99, 110)]                  # 10: tp1
    bars += [(110, 121, 108, 120)]                 # 11: tp2
    bars += [(120, 131, 118, 130)]                 # 12: tp3 terminal
    bars += _flat(3)
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "TP3", t.outcome           # deepest touch (info)
    # FIXED policy: full exit at TP1 on its touch bar (no oracle exits)
    assert t.entry == 100.0 and t.exit_price == 110.0
    assert abs(t.r_mult - 1.0) < 1e-9, t.r_mult
    assert t.entry_idx == 9 and t.exit_idx == 10 and t.bars_held == 1
    # oracle envelope reported separately, never as the headline R
    assert abs(t.r_deepest - 3.0) < 1e-9, t.r_deepest


def test_sl_path_with_gap_fill():
    bars = _flat(9)
    bars += [(104, 105, 98, 103)]                  # 9: entry 100
    bars += [(88, 92, 85, 86)]                     # 10: gap below stop
    bars += _flat(3)
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "SL", t.outcome
    assert t.exit_price == 88.0                    # min(open, stop)
    assert t.r_mult < -1.0                         # gap made it worse than -1R


def test_same_bar_tp_and_sl_is_conservative_sl():
    bars = _flat(9)
    bars += [(104, 111, 89, 95)]                   # 9: touches TP1 AND stop
    bars += _flat(3)
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "SL", t.outcome
    assert t.exit_price == 90.0                    # stop, no gap on entry bar
    assert abs(t.r_mult + 1.0) < 1e-9


def test_touch_before_confirmation_not_tradeable():
    bars = _flat(6)
    bars += [(104, 105, 96, 104)]                  # 6: touch BEFORE confirm(8)
    bars += _flat(10)                              # never touches again
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "NO_ENTRY", t.outcome


def test_gap_through_zone_skipped():
    bars = _flat(9)
    bars += [(92, 94, 88, 90)]                     # 9: opens below prz_lo
    bars += _flat(3)
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "SKIP_GAP", t.outcome


def test_tp1_then_flat_is_tp1_win():
    bars = _flat(9)
    bars += [(104, 105, 98, 103)]                  # 9: entry 100
    bars += [(103, 111, 101, 108)]                 # 10: tp1 touched
    bars += _flat(20)                              # flat to timeout window
    t = simulate_trade(_mk_det(), _df(bars), max_hold=10)
    assert t.outcome == "TP1", t.outcome
    assert t.exit_price == 110.0                   # exits at the TP1 level
    assert t.exit_idx == 10                        # ...on its TOUCH bar
    assert t.bars_held == 1
    assert abs(t.r_mult - 1.0) < 1e-9


def test_entry_bar_high_not_credited_as_tp():
    """The entry bar's high may precede the intrabar fill — a bar that
    opens above the zone, spikes past TP3, dips into the PRZ, then dumps
    to the stop next bar must be an SL, not an instant TP3 win."""
    bars = _flat(9)
    bars += [(104, 133, 98, 120)]                  # 9: high > tp3, touch
    bars += [(95, 96, 85, 86)]                     # 10: stop broken
    bars += _flat(3)
    t = simulate_trade(_mk_det(), _df(bars))
    assert t.outcome == "SL", t.outcome
    assert abs(t.r_mult + 1.0) < 1e-9              # stop 90, no gap


def test_stale_alert_expires():
    """A PRZ touch long after confirmation is not a live trade: with
    entry_window=10 a touch at lag 16 must be EXPIRED."""
    bars = _flat(9)                                # confirm = 8
    bars += _flat(15)                              # bars 9-23: no touch
    bars += [(104, 105, 96, 104)]                  # 24: touch (lag 16)
    bars += _flat(5)
    t = simulate_trade(_mk_det(), _df(bars), entry_window=10)
    assert t.outcome == "EXPIRED", t.outcome


def test_zigzag_confirm_bar_uses_raw_pivot():
    """with_confirm: a snapped-backward pivot must carry the RAW pivot
    bar as its know_bar (live scans could not know the extreme sooner)."""
    from prz_scanner.zigzag import compute_zigzag
    n = 30
    high = np.full(n, 105.0)
    low = np.full(n, 104.0)
    low[5] = 95.0
    high[10] = 115.0     # true spike (twin at 11 -> both disqualified)
    high[11] = 115.0
    high[16] = 110.0     # lesser swing that DOES confirm as the pivot
    low[20] = 94.0
    pts = compute_zigzag(high, low, depth=3, with_confirm=True)
    spike = [p for p in pts if p[2] and p[0] == 115.0]
    assert spike, pts
    price, bar, is_high, know = spike[0]
    assert bar == 10                                # drawn at the extreme
    assert know == 16, know                         # knowable via raw pivot


def test_all_windows_finds_historical_pattern():
    # ideal Gartley at points[1..4] plus 4 later pivots -> the Gartley is
    # no longer within the live tail windows, only all_windows sees it.
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1038.2, 30, False), (1076.4, 40, True),
              (1050.0, 45, False), (1090.0, 50, True),
              (1040.0, 55, False), (1080.0, 60, True)]
    n = 70
    high = np.full(n, 1051.0)
    low = np.full(n, 1049.0)
    close = np.full(n, 1050.0)
    cfg = Config()

    tail = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=cfg)
    assert not any(d.pattern == "Gartley" and d.ci == 40 for d in tail)

    full = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=cfg,
                       all_windows=True)
    assert any(d.pattern == "Gartley" and d.ci == 40 for d in full), \
        [(d.pattern, d.ci) for d in full]


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
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
