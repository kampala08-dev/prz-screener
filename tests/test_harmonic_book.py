"""Book-accuracy tests for the harmonic scanner (synthetic geometry).

Verifies against Scott Carney's "Harmonic Trading" definitions:
  - ideal Gartley detects with a 3-element confluence PRZ (XA + AB=CD + BC)
  - ideal Bat detects (B=0.382-0.50, D=0.886 XA)
  - Crab BC-projection gate: shallow-C Crab (implied CD/BC > 3.618) is
    rejected when strict_bc is ON, accepted when OFF (regression for the
    dead bc/ab gate of the original Pine port)
  - Shark detects with the two-sided 0.886-1.13 completion zone
  - zigzag snap-to-extreme recovers a spike that the strict symmetric
    window disqualified (twin equal peaks)
  - _pick_top returns at most 2 detections: nearest first, accuracy as
    tie-break, best buy always included

Runnable standalone (`python tests/test_harmonic_book.py`) or via pytest.
"""

import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prz_scanner.config import Config
from prz_scanner.patterns import Detection, scan_points
from prz_scanner.scanner import _pick_top
from prz_scanner.zigzag import compute_zigzag


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _flat_tail_arrays(n: int = 50, close_val: float = 1050.0):
    """OHLC arrays whose tail (used by prz_status) sits flat at close_val,
    far from the test PRZs so status stays 0 (active)."""
    high = np.full(n, close_val + 1.0)
    low = np.full(n, close_val - 1.0)
    close = np.full(n, close_val)
    return high, low, close


def _cfg(**over) -> Config:
    cfg = Config()
    for k, v in over.items():
        setattr(cfg, k, v)
    return cfg


def _names(dets):
    return [d.pattern for d in dets]


# ---------------------------------------------------------------------------
# pattern-ratio tests (points fed directly, bypassing the zigzag)
# ---------------------------------------------------------------------------
def test_ideal_gartley_confluence():
    # X=1000 A=1100 B=1038.2 (0.618) C=1076.4 (0.618 of AB) -> D=0.786 XA
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1038.2, 30, False), (1076.4, 40, True)]
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    g = [d for d in dets if d.pattern == "Gartley" and d.bull]
    assert g, f"ideal Gartley not detected: {_names(dets)}"
    d = g[0]
    # anchor 0.786*XA = 1021.4 must be inside the PRZ
    assert d.prz_lo <= 1021.4 <= d.prz_hi, (d.prz_lo, d.prz_hi)
    # book confluence: XA anchor + AB=CD (1014.6) + BC 1.414 (1022.4)
    assert d.conf_n == 3, f"expected 3-element confluence, got {d.conf_n}"
    assert d.prz_lo <= 1014.6 <= d.prz_hi
    # implied CD/BC inside the book Gartley range 1.13-1.618
    assert 1.13 <= d.bc_proj <= 1.618, d.bc_proj
    assert d.valid


def test_ideal_bat():
    # X=1000 A=1100 B=1055 (0.45) C=1082.81 (0.618 of AB) -> D=0.886 XA
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1055.0, 30, False), (1082.81, 40, True)]
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    b = [d for d in dets if d.pattern == "Bat" and d.bull]
    assert b, f"ideal Bat not detected: {_names(dets)}"
    d = b[0]
    assert d.prz_lo <= 1011.4 <= d.prz_hi        # 0.886 XA anchor
    assert 1.618 <= d.bc_proj <= 2.618, d.bc_proj
    assert d.conf_n >= 2, d.conf_n


def test_crab_bc_gate_rejects_shallow_c():
    """[BOOK] Crab needs BC projection 2.618-3.618 to reach 1.618 XA.
    A shallow C (0.382 of AB) implies CD/BC ~5.2 -> must be rejected with
    strict_bc ON; the old port's dead gate would have let it through."""
    base = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
            (1038.2, 30, False)]                     # B = 0.618 XA
    shallow = base + [(1061.8, 40, True)]            # C = 0.382 of AB
    deep = base + [(1092.95, 40, True)]              # C = 0.886 of AB
    high, low, close = _flat_tail_arrays()

    dets_shallow = scan_points("TST", shallow, high, low, close,
                               tol_val=5.0, is_strict=True, cfg=_cfg())
    assert "Crab" not in _names(dets_shallow), _names(dets_shallow)

    dets_deep = scan_points("TST", deep, high, low, close,
                            tol_val=5.0, is_strict=True, cfg=_cfg())
    crabs = [d for d in dets_deep if d.pattern == "Crab" and d.bull]
    assert crabs, f"deep-C Crab not detected: {_names(dets_deep)}"
    assert 2.618 <= crabs[0].bc_proj <= 3.618, crabs[0].bc_proj

    # gate OFF -> shallow Crab passes again (loosened behaviour)
    dets_off = scan_points("TST", shallow, high, low, close,
                           tol_val=5.0, is_strict=True,
                           cfg=_cfg(strict_bc=False))
    assert "Crab" in _names(dets_off), _names(dets_off)


def test_shark_two_sided_zone():
    # X=1000 A=1100 B=1050 (0.5) C=1115 (ext 1.3 of AB, beyond A)
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1050.0, 30, False), (1115.0, 40, True)]
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    s = [d for d in dets if d.pattern == "Shark" and d.bull]
    assert s, f"Shark not detected: {_names(dets)}"
    d = s[0]
    # completion zone 0.886-1.13 of XA measured from A: [987, 1011.4]
    assert abs(d.prz_lo - 987.0) < 0.5 and abs(d.prz_hi - 1011.4) < 0.5, \
        (d.prz_lo, d.prz_hi)
    assert d.conf_n >= 2


def test_shark_bc_band_overlap_accepts_edge_case():
    """[BOOK] A Shark whose BC projection band (1.618-2.24) overlaps only
    the TOP edge of the 0.886-1.13 completion zone is book-valid and must
    pass the strict gate (the old midpoint-based gate rejected it)."""
    # X=1000 A=1100 B=1061.8 (br=0.382) C=1104.97 (ext 1.13 of AB)
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1061.8, 30, False), (1104.97, 40, True)]
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    s = [d for d in dets if d.pattern == "Shark" and d.bull]
    assert s, f"edge-overlap Shark not detected: {_names(dets)}"


def test_structure_guard_rejects_c_beyond_a_for_gartley():
    """C above A (bull) is an extension, not a retracement — Gartley must
    not fire even if the raw ratios happen to fit."""
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1038.2, 30, False), (1105.0, 40, True)]   # C > A
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    assert "Gartley" not in _names(dets), _names(dets)


# ---------------------------------------------------------------------------
# zigzag snap test
# ---------------------------------------------------------------------------
def test_zigzag_snap_recovers_disqualified_spike():
    """Twin equal peaks (115 @ bars 10,11) disqualify each other under the
    strict symmetric-window test; the detected pivot high of that leg is a
    lesser swing (110 @ bar 16). Snap must re-anchor it to 115 @ bar 10."""
    n = 30
    high = np.full(n, 105.0)
    low = np.full(n, 104.0)
    close = np.full(n, 104.5)
    low[5] = 95.0        # pivot low
    high[10] = 115.0     # true spike (disqualified: twin at 11)
    high[11] = 115.0
    high[16] = 110.0     # lesser swing that DOES qualify as pivot
    low[20] = 94.0       # pivot low

    raw = compute_zigzag(high, low, depth=3, snap=False)
    snapped = compute_zigzag(high, low, depth=3, snap=True)

    raw_highs = [(p, b) for p, b, ih in raw if ih]
    assert (110.0, 16) in raw_highs, raw_highs        # port behaviour
    assert all(p != 115.0 for p, _ in raw_highs)      # spike missed by port

    snap_highs = [(p, b) for p, b, ih in snapped if ih]
    assert (115.0, 10) in snap_highs, snap_highs      # spike recovered

    # ordering + alternation preserved
    bars = [b for _, b, _ in snapped]
    assert bars == sorted(bars) and len(set(bars)) == len(bars)
    dirs = [ih for _, _, ih in snapped]
    assert all(dirs[i] != dirs[i + 1] for i in range(len(dirs) - 1))


# ---------------------------------------------------------------------------
# top-2 selection test
# ---------------------------------------------------------------------------
def _mk_det(prz_lo, prz_hi, score, status=0):
    d = Detection(ticker="T", pattern="Gartley", color="green", bull=True,
                  depth=3, is_strict=True,
                  xi=0, xP=1000.0, ai=1, aP=1100.0, bi=2, bP=1040.0,
                  ci=3, cP=1080.0, prz_hi=prz_hi, prz_lo=prz_lo,
                  br=0.618, cr=0.618, bcp=0.618, status=status)
    d.score = score
    return d


def test_pick_top_two_nearest_highest_accuracy():
    last_close = 1000.0
    d_inside_60 = _mk_det(990, 1010, 60)          # inside, score 60
    d_far_95 = _mk_det(900, 909, 95)              # 10% away, score 95
    d_near_80 = _mk_det(985, 995, 80)             # 0.5% away, score 80
    d_invalid_99 = _mk_det(990, 1010, 99, status=2)   # inside but invalid
    dets = [d_inside_60, d_far_95, d_near_80, d_invalid_99]

    top = _pick_top(dets, best_buy=d_inside_60, last_close=last_close,
                    max_display=2)
    assert len(top) == 2
    # same 2%-bucket -> accuracy decides: d_near_80 outranks d_inside_60
    assert top[0] is d_near_80
    assert d_inside_60 in top                     # best buy always kept
    assert d_invalid_99 not in top                # invalid ranked last
    assert d_far_95 not in top                    # distance dominates score


def test_pick_top_forces_best_buy():
    last_close = 1000.0
    d1 = _mk_det(985, 995, 90)
    d2 = _mk_det(980, 998, 85)
    far_best_buy = _mk_det(880, 890, 40)          # far & weak, but best buy
    top = _pick_top([d1, d2, far_best_buy], best_buy=far_best_buy,
                    last_close=last_close, max_display=2)
    assert len(top) == 2
    assert far_best_buy in top


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
