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
    # [BOOK-V3] confluence: XA anchor + AB=CD (1014.6) + BC 1.414 (1022.4)
    # -> 3 elemen. 1.27AB=CD (997.9) berada DI LUAR make-or-break Gartley
    # (1.0*XA = 1000, di bawah X) sehingga BUKAN elemen PRZ yang sah dan
    # dikeluarkan dari cluster (fix review 2026-07-26).
    assert d.conf_n == 3, f"expected 3-element confluence, got {d.conf_n}"
    assert d.prz_lo <= 1014.6 <= d.prz_hi
    assert d.prz_lo > d.stop, (d.prz_lo, d.stop)
    # implied CD/BC inside the book Gartley range 1.13-1.618
    assert 1.13 <= d.bc_proj <= 1.618, d.bc_proj
    # [BOOK-V3 p.92] stop just beyond 1.0 XA: A - 1.02*XA = 998
    assert abs(d.stop - 998.0) < 0.01, d.stop
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
    # [BOOK-V3 p.98] stop just beyond 1.13 XA: A - 1.15*XA = 985
    assert abs(d.stop - 985.0) < 0.01, d.stop


def test_crab_bc_gate_rejects_shallow_c():
    """[BOOK] Crab needs BC projection 2.618-3.618 to reach 1.618 XA.
    A shallow C (0.382 of AB) implies CD/BC ~5.2 -> must be rejected with
    strict_bc ON; the old port's dead gate would have let it through."""
    base = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
            (1038.2, 30, False)]                     # B = 0.618 XA
    # C = 0.382039 of AB (1061.81): tepat DI ATAS batas bawah buku 0.382.
    # (1061.8 menghasilkan 0.38187 — di bawah batas keras; dulu lolos hanya
    # karena tol 5% yang kini dihapus.)
    shallow = base + [(1061.81, 40, True)]
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
    # X=1000 A=1100 B=1050 (br=0.50) C=1150 (impulse bcp=2.0, beyond A)
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1050.0, 30, False), (1150.0, 40, True)]
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
    # [BOOK-V3] impulse leg bcp = BC/AB must be within 1.618-2.24
    assert 1.618 <= d.bcp <= 2.24, d.bcp


def test_shark_impulse_leg_gate():
    """[BOOK-V3 p.118/120/129] The Extreme Harmonic Impulse (bcp = BC/AB)
    must be 1.618-2.24. Below (weak) and above (over-extended, e.g. the
    GIAA case at 3.875) are both rejected."""
    high, low, close = _flat_tail_arrays()

    def shark_bcp(bcp_target):
        # X=1000 A=1100 (XA=100) B=1050 (AB=50) C=1050+bcp*50
        cP = 1050.0 + bcp_target * 50.0
        pts = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
               (1050.0, 30, False), (cP, 40, True)]
        dets = scan_points("TST", pts, high, low, close,
                           tol_val=5.0, is_strict=True, cfg=_cfg())
        return any(d.pattern == "Shark" and d.bull for d in dets)

    assert not shark_bcp(1.30), "impulse 1.30 (below 1.618) must be rejected"
    assert shark_bcp(1.80), "impulse 1.80 (in 1.618-2.24) must be detected"
    assert not shark_bcp(3.00), "impulse 3.00 (above 2.24) must be rejected"


def test_shark_impulse_gate_is_hard_no_tolerance():
    """Batas impuls Shark KERAS: buku menyebut 1.618-2.24 tiga kali tanpa
    kualifikasi toleransi. Dulu pass loose (tol 10%) meloloskan sampai
    2.464 — kasus LPPF live: impuls 2.419 terkirim sebagai sinyal."""
    high, low, close = _flat_tail_arrays()

    def shark(bcp_target, tol, strict):
        cP = 1050.0 + bcp_target * 50.0
        pts = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
               (1050.0, 30, False), (cP, 40, True)]
        dets = scan_points("TST", pts, high, low, close,
                           tol_val=tol, is_strict=strict, cfg=_cfg())
        return any(d.pattern == "Shark" and d.bull for d in dets)

    assert not shark(2.419, 10.0, False), "kasus LPPF harus DITOLAK di loose"
    assert not shark(2.30, 5.0, True)
    assert shark(2.20, 10.0, False)          # dalam rentang buku -> tetap lolos


def test_c_range_hard_book_bounds():
    """Rentang C 0.382-0.886 = elemen definisi pola, batas KERAS di kedua
    pass. Dulu tol 5%/10% meloloskan C=0.915 (kasus PANI Crab, pass
    strict!) dan 0.946 (PANI Bat SELL, loose)."""
    high, low, close = _flat_tail_arrays()

    def crab_c(cr_target, tol, strict):
        # X=1000 A=1100 B=1038.2 (0.618) C = B + cr*AB
        cP = 1038.2 + cr_target * 61.8
        pts = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
               (1038.2, 30, False), (cP, 40, True)]
        dets = scan_points("TST", pts, high, low, close,
                           tol_val=tol, is_strict=strict, cfg=_cfg())
        return any(d.pattern == "Crab" and d.bull for d in dets)

    assert not crab_c(0.915, 5.0, True), "C=0.915 harus ditolak (strict)"
    assert not crab_c(0.915, 10.0, False), "C=0.915 harus ditolak (loose)"
    assert crab_c(0.886, 5.0, True)          # tepat di batas buku -> sah


def test_prz_cluster_never_beyond_stop():
    """Geometri TUGU asli (X=1175 A=1330 B=1230 C=1300): level 1.27*AB=CD
    jatuh di ~1.04*XA — melewati make-or-break Gartley 1.0*XA — dan dulu
    menyeret prz_lo (1171) MENEMBUS stop (1172). Level di luar make-or-break
    kini dikeluarkan dari cluster dan zona di-clamp."""
    pts = [(1332.0, 2, True), (1175.0, 10, False), (1330.0, 20, True),
           (1230.0, 30, False), (1300.0, 40, True)]
    high, low, close = _flat_tail_arrays(close_val=1250.0)
    dets = scan_points("TST", pts, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    g = [d for d in dets if d.pattern == "Gartley" and d.bull]
    assert g, _names(dets)
    d = g[0]
    assert d.prz_lo > d.stop, f"zona menembus stop: prz_lo={d.prz_lo} stop={d.stop}"
    # anchor buku tetap di dalam zona
    assert d.prz_lo <= 1330.0 - 0.786 * 155.0 <= d.prz_hi


def test_structure_guard_rejects_c_beyond_a_for_gartley():
    """C above A (bull) is an extension, not a retracement — Gartley must
    not fire even if the raw ratios happen to fit."""
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1038.2, 30, False), (1105.0, 40, True)]   # C > A
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    assert "Gartley" not in _names(dets), _names(dets)


def test_b_point_absolute_pp_tolerance():
    """[BOOK-V3 p.91] Gartley B tolerance is +/-3 percentage points
    (0.588-0.648) and is a HARD maximum ("become invalid above the upper
    limit"): br=0.66 must fail BOTH passes; br=0.64 (inside) passes."""
    high, low, close = _flat_tail_arrays()

    # br = 0.66 -> B = 1034: invalid on strict AND loose
    bad = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
           (1034.0, 30, False), (1074.79, 40, True)]
    strict = scan_points("TST", bad, high, low, close,
                         tol_val=5.0, is_strict=True, cfg=_cfg())
    assert "Gartley" not in _names(strict), _names(strict)
    loose = scan_points("TST", bad, high, low, close,
                        tol_val=10.0, is_strict=False, cfg=_cfg())
    assert "Gartley" not in _names(loose), _names(loose)

    # br = 0.64 -> B = 1036 (inside 0.588-0.648): valid; C = 0.618 of AB
    ok = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
          (1036.0, 30, False), (1075.55, 40, True)]
    dets = scan_points("TST", ok, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    assert "Gartley" in _names(dets), _names(dets)


def test_shark_targets_from_cd_leg():
    """[BOOK-V3 p.118] Shark TP1/TP2 = 50%/61.8% retracement of the final
    leg (C -> D zone mid), TP3 = full retest of C."""
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1050.0, 30, False), (1150.0, 40, True)]  # impulse bcp=2.0
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    d = [x for x in dets if x.pattern == "Shark" and x.bull][0]
    leg = d.cP - d.prz_mid
    assert abs(d.tp1 - (d.prz_mid + 0.5 * leg)) < 1e-6
    assert abs(d.tp2 - (d.prz_mid + 0.618 * leg)) < 1e-6
    assert abs(d.tp3 - d.cP) < 1e-6
    # stop just beyond the 1.13 XA zone edge: A - 1.15*XA = 985
    assert abs(d.stop - 985.0) < 0.01, d.stop


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


def test_filter_results_quality_subset():
    """--quality: hanya best_buy Crab/Bat dengan conf>=2 yang lolos."""
    from prz_scanner.scanner import (StockResult, filter_results,
                                     QUALITY_PATTERNS, QUALITY_MIN_CONF)

    def _res(pattern, conf):
        d = _mk_det(990, 1010, 70)
        d.pattern, d.conf_n = pattern, conf
        return StockResult(ticker=pattern, df=None, all_dets=[d],
                           best_buy=d, passed=True, top_dets=[d])

    results = [_res("Crab", 3), _res("Bat", 2), _res("Bat", 1),
               _res("Gartley", 4), _res("Shark", 3)]
    out = filter_results(results, only=list(QUALITY_PATTERNS),
                         min_conf=QUALITY_MIN_CONF)
    kept = {r.ticker for r in out}
    assert kept == {"Crab", "Bat"}, kept          # Bat conf1 & non-CrabBat out
    assert all(r.best_buy.conf_n >= 2 for r in out)
    # tanpa filter -> semua lolos
    assert len(filter_results(results)) == 5


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
# audit 2026-07-25: outside bar, guard bar monoton, Shark ideal_c,
# penanda C belum terkonfirmasi
# ---------------------------------------------------------------------------
def test_outside_bar_emits_single_pivot():
    """Outside bar yang mendominasi KEDUA jendela +/-depth dulu diemit
    sebagai pivot high DAN low pada bar yang sama (dua `if` terpisah) ->
    duplikat bar & leg XABCD berdurasi 0. Kini emit SATU yang beralternasi
    dengan pivot terakhir."""
    n = 30
    base_h = np.full(n, 105.0)
    base_l = np.full(n, 104.0)

    # kasus 1: pivot sebelumnya LOW -> outside bar diemit sebagai HIGH
    h1, l1 = base_h.copy(), base_l.copy()
    l1[5] = 95.0                     # pivot low
    h1[12], l1[12] = 120.0, 93.0     # outside bar (dominasi bars 9-15)
    l1[18] = 94.0                    # pivot low berikutnya
    h1[24] = 119.0                   # pivot high berikutnya
    pts = compute_zigzag(h1, l1, depth=3, snap=False)
    bars = [b for _, b, _ in pts]
    assert len(set(bars)) == len(bars), f"duplikat bar: {bars}"
    at12 = [(p, ih) for p, b, ih in pts if b == 12]
    assert at12 == [(120.0, True)], at12

    # kasus 2: pivot sebelumnya HIGH -> outside bar diemit sebagai LOW
    h2, l2 = base_h.copy(), base_l.copy()
    h2[5] = 118.0
    h2[12], l2[12] = 120.0, 93.0
    h2[18] = 119.0
    l2[24] = 94.0
    pts2 = compute_zigzag(h2, l2, depth=3, snap=False)
    bars2 = [b for _, b, _ in pts2]
    assert len(set(bars2)) == len(bars2), f"duplikat bar: {bars2}"
    at12b = [(p, ih) for p, b, ih in pts2 if b == 12]
    assert at12b == [(93.0, False)], at12b


def test_scan_points_rejects_nonmonotonic_bars():
    """[GUARD] Window dengan bar tidak monoton naik ketat (A dan B pada bar
    yang sama — artefak outside bar) tidak boleh menghasilkan deteksi,
    meski rasio harganya membentuk Bat ideal."""
    points = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
              (1055.0, 20, False), (1082.81, 40, True)]   # bi == ai
    high, low, close = _flat_tail_arrays()
    dets = scan_points("TST", points, high, low, close,
                       tol_val=5.0, is_strict=True, cfg=_cfg())
    assert dets == [], _names(dets)


def test_shark_score_prefers_book_center_impulse():
    """ideal_c Shark = 1.929 (titik tengah rentang buku 1.618-2.24).
    Impuls dekat tengah rentang wajib skor tertinggi; jangkar lama 1.414
    (di luar rentang sah) membalik urutan — makin sesuai buku makin
    terpenalti."""
    high, low, close = _flat_tail_arrays()

    def shark_score(bcp_target):
        cP = 1050.0 + bcp_target * 50.0
        pts = [(1101.0, 2, True), (1000.0, 10, False), (1100.0, 20, True),
               (1050.0, 30, False), (cP, 40, True)]
        dets = scan_points("TST", pts, high, low, close,
                           tol_val=5.0, is_strict=True, cfg=_cfg())
        s = [d for d in dets if d.pattern == "Shark" and d.bull]
        assert s, f"Shark bcp={bcp_target} harus terdeteksi"
        return s[0].score

    assert shark_score(2.0) > shark_score(1.65)
    assert shark_score(2.0) > shark_score(2.20)


def test_live_scan_flags_unconfirmed_c():
    """[anti-repaint] scan_stock menandai c_confirmed=False bila pivot C
    hasil snap-forward belum punya `depth` bar konfirmasi di kanannya —
    kelas sinyal yang bisa repaint & berada di luar populasi backtest."""
    import pandas as pd
    from prz_scanner.scanner import scan_stock

    def _mk_df(n):
        high = np.full(n, 1052.0)
        low = np.full(n, 1048.0)
        close = np.full(n, 1050.0)
        high[4] = 1055.0      # pivot pembuka (agar total pivot >= 5)
        low[10] = 1000.0      # X
        high[20] = 1100.0     # A
        low[30] = 1038.2      # B = 0.618 XA -> Gartley
        high[36] = 1070.0     # C sementara (raw pivot terkonfirmasi)
        high[43] = 1076.4     # higher-high = 0.618 dari AB (bar TETAP 43;
        return pd.DataFrame({  # n yang menentukan sudah/belum konfirmasi
            "High": high, "Low": low, "Close": close})

    cfg = _cfg(depths=[3], proximity_pct=25.0)

    # n=45: ekstrem di bar 43 belum punya 3 bar kanan -> snap-forward
    # memindahkan C ke sana -> WAJIB ditandai belum terkonfirmasi
    res = scan_stock("TST", _mk_df(45), cfg)
    assert res.passed and res.best_buy is not None
    assert res.best_buy.c_confirmed is False, vars(res.best_buy)

    # n=50: ekstrem yang sama kini punya >=3 bar kanan -> terkonfirmasi
    res2 = scan_stock("TST", _mk_df(50), cfg)
    assert res2.passed and res2.best_buy is not None
    assert res2.best_buy.c_confirmed is True, vars(res2.best_buy)


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
