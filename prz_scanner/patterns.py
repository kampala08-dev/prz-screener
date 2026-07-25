"""Harmonic XABCD detection + PRZ + validity.

Originally a 1:1 port of prz.pine `scan()`; now upgraded to follow Scott
Carney's "Harmonic Trading" (Vol. 1/2) definitions — the [BOOK] tags mark
every deliberate deviation from the Pine port:

[BOOK] fixes vs the Pine port
  1. BC-projection gate: Pine gated `bc/ab` (which is the C *retracement*,
     already range-checked) against BC-projection ranges like 1.618-2.618 —
     mathematically dead code (the ranges can never overlap). The book's BC
     projection is the extension of the BC leg needed to REACH D, i.e.
     m = CD/BC. We gate that implied m against each pattern's book range.
  2. Crab BC projection corrected to 2.618-3.618 (was 2.24-3.618).
  3. PRZ = confluence cluster per the book: the XA-derived D anchor plus the
     AB=CD completion (and its pattern alternates) plus the nearest book BC
     projection level — every element that lands within `prz_cluster_tol`%
     of the anchor joins the zone; the cluster count feeds accuracy.
  4. Explicit structure guards (B strictly inside XA; C inside AB..A for
     retracement patterns / beyond A for Shark).
  5. Shark's Extreme Harmonic Impulse leg (bcp = bc/ab) bounded to the
     book's 1.618-2.24 (V3 p.118/120/129: "must be at least a 1.618, can be
     as much as 2.24"). The completion zone is the two-sided 0.886-1.13 of
     the 0X leg. The B-retracement filter 0.382-0.618 on Shark is an
     official Vol.3 element (p.119).

[BOOK-V3] refinements verified against "Harmonic Trading Volume 3:
Reaction vs. Reversal" (page refs = printed page numbers):
  - B-point tolerances are ABSOLUTE percentage points (p.91): +/-3pp for
    Gartley & Butterfly, 5pp for Bat/Crab/Shark ranges (see _B_SPEC).
  - AB=CD alternates per the "AB=CD Type" element (see _ABCD_MULTS).
  - Make-or-break stops per the "Stop Loss" element (see _STOP_XA).
  - Shark TPs: 50%/61.8% retracement of the final leg (p.118).

Book ratio table implemented (D anchor as multiple of XA; bull direction):
  Gartley   B=0.618+/-3pp  C=0.382-0.886  BC 1.13-1.618   D=0.786   SL>1.0XA
  Bat       B=0.382-0.50   C=0.382-0.886  BC 1.618-2.618  D=0.886   SL>1.13XA
  Butterfly B=0.786+/-3pp  C=0.382-0.886  BC 1.618-2.24   D=1.27    SL>1.414XA
  Crab      B=0.382-0.618  C=0.382-0.886  BC 2.618-3.618  D=1.618   SL>2.0XA
  Shark     impulse leg (BC/AB) 1.618-2.24; completion zone 0.886-1.13 of
            XA; B (book 0X-ret at A) 0.382-0.618 (per the book's 0-X-A-B-C
            labelling our X,A,B,C,D = book 0,X,A,B,C).

[DEVIATION] additions (no Pine equivalent), clearly separated:
  - numeric `score` (fidelity/confluence/strictness/sweet-spot)
  - PRZ width guard `prz_maxw`
  - TP1/TP2/TP3 & stop levels for the summary/chart
"""

from dataclasses import dataclass
from typing import List, Optional
import numpy as np

from .zigzag import ZPoint


# ---------------------------------------------------------------------------
# Pine helpers
# ---------------------------------------------------------------------------
def safe_div(a: float, b: float) -> float:
    return a / b if b != 0 else 0.0


def in_r(v: float, ideal: float, t: float) -> bool:
    """Pine inR: v within +/- t% of a single ideal ratio."""
    return ideal * (1 - t / 100) <= v <= ideal * (1 + t / 100)


def in_mm(v: float, lo: float, hi: float, t: float) -> bool:
    """Pine inMM: v within [lo*(1-t%), hi*(1+t%)]."""
    return lo * (1 - t / 100) <= v <= hi * (1 + t / 100)


def bc_gate(v: float, lo: float, hi: float, t: float, strict_bc: bool) -> bool:
    """Pine bcGate: if strict_bc OFF -> always true; else inMM."""
    return (not strict_bc) or in_mm(v, lo, hi, t)


# ---------------------------------------------------------------------------
# Pattern spec table (exactly as in Pine scan()).
#   name, color, B-check, C-check, BC-gate range, D projection k, box r-fraction
# B-check kinds: ("r", ideal) uses inR ; ("mm", lo, hi) uses inMM.
# Shark is special (two-sided PRZ), handled inline.
# ---------------------------------------------------------------------------
@dataclass
class Detection:
    ticker: str
    pattern: str
    color: str
    bull: bool
    depth: int
    is_strict: bool
    # geometry (bar indices into the OHLC arrays + prices)
    xi: int; xP: float
    ai: int; aP: float
    bi: int; bP: float
    ci: int; cP: float
    prz_hi: float
    prz_lo: float
    # ratios
    br: float
    cr: float
    bcp: float
    # [BOOK] implied BC projection (CD/BC) & confluence element count
    bc_proj: float = 0.0
    conf_n: int = 1
    # earliest bar the XABC window was live-knowable (backtest confirmation;
    # -1 when the zigzag was built without with_confirm)
    confirm_bar: int = -1
    # [DEVIATION anti-repaint] False bila pivot C belum punya `depth` bar
    # konfirmasi di kanannya saat scan — C hasil snap-forward ke ekstrem yang
    # masih berkembang. Sinyal seperti ini bisa repaint (C/PRZ/stop bergeser)
    # dan berada DI LUAR populasi trade backtest (yang mengunci entry ke
    # confirm_bar + depth). Diisi scanner live; jalur backtest mengabaikannya.
    c_confirmed: bool = True
    # validity (przStatus): 0 active, 1 confirmed-reversal, 2 invalid, 3 flip
    status: int = 0
    first_touch_idx: int = -1
    end_idx: int = -1
    # [DEVIATION] annotations
    score: float = 0.0
    dist_pct: float = 0.0        # signed % distance of close from PRZ mid
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    stop: float = 0.0

    @property
    def valid(self) -> bool:
        # status 2 = invalid (broke against pattern & never recovered).
        return self.status != 2

    @property
    def prz_mid(self) -> float:
        return (self.prz_hi + self.prz_lo) / 2


# ---------------------------------------------------------------------------
# przStatus — 1:1 port of Pine przStatus (prz.pine lines ~82-133).
# Scans bars AFTER pivot C (startIdx) forward to last bar.
#   returns (status, first_touch_idx, end_idx)
# status: 0 active, 1 confirmed reversal (per pattern dir), 2 invalid, 3 flip.
# ---------------------------------------------------------------------------
def prz_status(high: np.ndarray, low: np.ndarray, close: np.ndarray,
               prz_hi: float, prz_lo: float, is_bull: bool,
               start_idx: int, rev_bars: int) -> tuple:
    n = len(high)
    result = 0
    touched = False
    broke = False
    touch_idx = -1
    first_touch = -1
    end_idx = start_idx

    # Pine scans from the pivot forward to now. start_idx is pivot C's bar.
    for i in range(start_idx + 1, n):
        h = high[i]; l = low[i]; c = close[i]
        if not touched:
            if l <= prz_hi and h >= prz_lo:
                touched = True
                touch_idx = i
                first_touch = i
                end_idx = i
        else:
            if l <= prz_hi and h >= prz_lo:
                end_idx = i
            bars_since = i - touch_idx
            if is_bull:
                if bars_since >= rev_bars and c > prz_hi:
                    result = 3 if broke else 1
                    end_idx = i
                    break
                if c < prz_lo * 0.97:
                    broke = True
                    end_idx = i
            else:
                if bars_since >= rev_bars and c < prz_lo:
                    result = 3 if broke else 1
                    end_idx = i
                    break
                if c > prz_hi * 1.03:
                    broke = True
                    end_idx = i

    if broke and result == 0:
        result = 2
    return result, first_touch, end_idx


# ---------------------------------------------------------------------------
# [DEVIATION] score + targets
# ---------------------------------------------------------------------------
def _power_near(k_used: float) -> float:
    """[DEVIATION] sweet-spot: closeness of the D-projection multiple to the
    0.886-1.13 'power zone'. 1.0 inside, decaying outside."""
    lo, hi = 0.886, 1.13
    if lo <= k_used <= hi:
        return 1.0
    d = (lo - k_used) if k_used < lo else (k_used - hi)
    return max(0.0, 1.0 - d / 0.5)


def _score(det: Detection, ideal_b: float, ideal_c: float, k_used: float,
           prz_width_pct: float, prz_maxw: float) -> float:
    """[DEVIATION] accuracy score 0-100.

    100*(0.42*fidelity + 0.28*confluence + 0.12*strict + 0.06*psy + 0.12*sweet)
      fidelity   : closeness of B/C retracements to the BOOK ideal ratios
      confluence : [BOOK] how many PRZ elements clustered (XA anchor, AB=CD,
                   BC projection) x tightness of the resulting zone
      strict     : strict-tolerance pass bonus
      sweet      : D-projection multiple near the 0.886-1.13 power zone
    """
    fb = max(0.0, 1.0 - abs(det.br - ideal_b) / max(ideal_b, 1e-9))
    fc = max(0.0, 1.0 - abs(det.cr - ideal_c) / max(ideal_c, 1e-9))
    fidelity = (fb + fc) / 2
    level_factor = {1: 0.35, 2: 0.75}.get(det.conf_n, 1.0)  # 3+ -> 1.0
    tightness = max(0.0, 1.0 - prz_width_pct / max(prz_maxw, 1e-9))
    confluence = level_factor * tightness
    strictness = 1.0 if det.is_strict else 0.5
    psy = 0.0  # round-number bonus not in Pine; left neutral
    sweet = _power_near(k_used)
    return 100.0 * (0.42 * fidelity + 0.28 * confluence + 0.12 * strictness
                    + 0.06 * psy + 0.12 * sweet)


def _targets(det: Detection) -> None:
    """TP/SL levels.

    Stop  [BOOK-V3]: the pattern's make-or-break XA multiple beyond A
          (see _STOP_XA), plus a small buffer for the "> level" wording.
    TPs   Shark [BOOK-V3 p.118]: initial objective = 50% retracement of
          the final (CD) leg, secondary 61.8%, full retest of C third —
          "anticipate a reaction to the 50-61.8%" (the 5-0 PRZ test).
          The book's full rule is "the LESSER OF the 50% level or the
          Reciprocal AB=CD"; the reciprocal needs the post-completion
          counter-move, which does not exist at detection time, so the
          50% book minimum is used.
          Other patterns [DEVIATION]: fib multiples of XA from D.
    """
    xa = abs(det.aP - det.xP)
    d = det.prz_mid
    k_stop = _STOP_XA.get(det.pattern, 1.0) + _STOP_BUFFER
    if det.bull:
        det.stop = det.aP - k_stop * xa
        if det.pattern == "Shark":
            leg = det.cP - d
            det.tp1 = d + 0.500 * leg
            det.tp2 = d + 0.618 * leg
            det.tp3 = det.cP
        else:
            det.tp1 = d + 0.382 * xa
            det.tp2 = d + 0.618 * xa
            det.tp3 = d + 1.000 * xa
    else:
        det.stop = det.aP + k_stop * xa
        if det.pattern == "Shark":
            leg = d - det.cP
            det.tp1 = d - 0.500 * leg
            det.tp2 = d - 0.618 * leg
            det.tp3 = det.cP
        else:
            det.tp1 = d - 0.382 * xa
            det.tp2 = d - 0.618 * xa
            det.tp3 = d - 1.000 * xa


# ---------------------------------------------------------------------------
# [BOOK] confluence PRZ helpers
# ---------------------------------------------------------------------------
def _near_pct(v: float, anchor: float, tol_pct: float) -> bool:
    """True if v lies within tol_pct% of anchor (anchor != 0)."""
    return anchor != 0 and abs(v - anchor) / abs(anchor) * 100.0 <= tol_pct


# Book BC-projection fib levels per pattern (used for the confluence cluster).
_BC_LEVELS = {
    "Gartley":   (1.13, 1.27, 1.414, 1.618),
    "Bat":       (1.618, 2.0, 2.24, 2.618),
    "Butterfly": (1.618, 2.0, 2.24),
    "Crab":      (2.618, 3.14, 3.618),
    "Shark":     (1.618, 2.0, 2.24),
}

# [BOOK-V3] AB=CD completion multiples per pattern, from the "AB=CD Type"
# element of each pattern spec in Harmonic Trading Vol.3:
#   Gartley  "AB=CD - 1.27AB=CD"   (V3 p.92)
#   Bat      "AB=CD - 1.618AB=CD"  (V3 p.98)
#   Butterfly"AB=CD - 1.27AB=CD"   (V3 p.113)
#   Crab     "AB=CD - 1.618AB=CD"  (V3 p.104)
_ABCD_MULTS = {
    "Gartley":   (1.0, 1.27),
    "Bat":       (1.0, 1.27, 1.618),
    "Butterfly": (1.0, 1.27),
    "Crab":      (1.0, 1.27, 1.618),
}

# [BOOK-V3] B-point specs (V3 p.91 "B Point Tolerance Classification"):
# tolerances are ABSOLUTE percentage points of the XA retracement, not
# relative percentages. Gartley & Butterfly demand +/-3pp around a precise
# ideal; Bat & Crab (and Shark's 0X-retracement measure, V3 p.119) use 5pp
# on their ranges. The book calls these MAXIMUM tolerances ("become invalid
# above the upper limit", p.91) — hard boundaries, so the loose pass does
# NOT widen them (it only loosens the C-range and BC-gate relative checks).
#   ("point", ideal, pp)  |  ("range", lo, hi, pp)
_B_SPEC = {
    "Gartley":   ("point", 0.618, 0.03),
    "Butterfly": ("point", 0.786, 0.03),
    "Bat":       ("range", 0.382, 0.50, 0.05),
    "Crab":      ("range", 0.382, 0.618, 0.05),
    "Shark":     ("range", 0.382, 0.618, 0.05),
}


def _b_ok(name: str, br: float, is_strict: bool) -> bool:
    """[BOOK-V3] B-point check with absolute-pp tolerance (hard limits —
    identical on strict and loose passes per p.91)."""
    del is_strict  # book: maximum tolerance, never widened
    spec = _B_SPEC[name]
    if spec[0] == "point":
        _, ideal, pp = spec
        return abs(br - ideal) <= pp
    _, lo, hi, pp = spec
    return lo - pp <= br <= hi + pp


# [BOOK-V3] make-or-break stop-loss levels, as XA multiples beyond A, from
# the "Stop Loss" element of each pattern spec (Shark: just beyond the 1.13
# edge of its completion zone):
_STOP_XA = {
    "Gartley":   1.0,     # V3 p.92  "Stop Loss > 1.0"
    "Bat":       1.13,    # V3 p.98  "Stop Loss > 1.13X"
    "Butterfly": 1.414,   # V3 p.113 "Stop Loss > 1.414XA"
    "Crab":      2.0,     # V3 p.104 "Stop Loss > 2.0XA"
    "Shark":     1.13,
}
_STOP_BUFFER = 0.02      # small XA fraction beyond the book level ("> X")

# Book BC-projection gate ranges (min, max) for the implied m = CD/BC.
_BC_GATE = {
    "Gartley":   (1.13, 1.618),
    "Bat":       (1.618, 2.618),
    "Butterfly": (1.618, 2.24),
    "Crab":      (2.618, 3.618),   # [BOOK] fixed: was 2.24-3.618
    "Shark":     (1.618, 2.24),
}


# ---------------------------------------------------------------------------
# Main scan over one zigzag point list.
# Structure follows Pine scan(); ratio/PRZ math follows the book ([BOOK]).
# ---------------------------------------------------------------------------
def scan_points(ticker: str, points: List[ZPoint],
                high: np.ndarray, low: np.ndarray, close: np.ndarray,
                tol_val: float, is_strict: bool, cfg,
                all_windows: bool = False) -> List[Detection]:
    """Scan pivot windows for harmonic patterns.

    all_windows=False (live): only the 4 most recent XABC windows are
    scanned (Pine behaviour — patterns near the right edge).
    all_windows=True (backtest): every consecutive alternating pivot
    quadruple in the list is scanned, so historical patterns that were
    once "the last 4 pivots" are also found.
    """
    dets: List[Detection] = []
    total = len(points)
    if total < 5:
        return dets

    last_close = close[-1]
    if all_windows:
        idx_range = range(0, total - 3)
    else:
        max_w = min(3, total - 4)   # Pine: maxW = min(3, totalP-4)
        idx_range = [total - 4 - w for w in range(0, max_w + 1)]

    for idx in idx_range:
        if idx < 0:
            continue
        # index access (points may be 3- or 4-tuples; see zigzag with_confirm)
        win = (points[idx], points[idx + 1], points[idx + 2], points[idx + 3])
        xP, xi, x_hi = win[0][0], win[0][1], win[0][2]
        aP, ai = win[1][0], win[1][1]
        bP, bi = win[2][0], win[2][1]
        cP, ci = win[3][0], win[3][1]
        # earliest bar the whole XABC window was live-knowable (raw pivot
        # bars when provided; falls back to the pivot bars themselves)
        confirm_bar = max(p[3] if len(p) > 3 else p[1] for p in win)
        bull = not x_hi

        # alternation check (Pine a1,a2,a3)
        t0 = points[idx][2]; t1 = points[idx + 1][2]
        t2 = points[idx + 2][2]; t3 = points[idx + 3][2]
        if not (t0 != t1 and t1 != t2 and t2 != t3):
            continue

        # [GUARD] bar indices wajib monoton naik ketat. Duplikat bar (mis.
        # outside bar degenerate yang lolos sebagai pivot high+low sekaligus)
        # melahirkan leg berdurasi 0 bar — pola sintetis dari satu candle.
        if not (xi < ai < bi < ci):
            continue

        xa = abs(aP - xP)
        ab = abs(bP - aP)
        bc = abs(cP - bP)
        br = safe_div(ab, xa)
        cr = safe_div(bc, ab)
        bcp = safe_div(bc, ab)
        if xa <= 0 or ab <= 0 or bc <= 0:
            continue

        # [BOOK] structure guards — legs must be geometrically coherent:
        #   bull: X low, A high, B strictly inside X..A, C above B.
        #   Retracement patterns additionally need C below A (C = retracement
        #   of AB); Shark needs C beyond A (extension leg).
        if bull:
            legs_ok = aP > xP and xP < bP < aP and cP > bP
            c_retr_ok = cP < aP
            c_ext_ok = cP > aP
        else:
            legs_ok = aP < xP and aP < bP < xP and cP < bP
            c_retr_ok = cP > aP
            c_ext_ok = cP < aP
        if not legs_ok:
            continue

        pe = cfg.patterns_enabled
        sbc = cfg.strict_bc
        cluster_tol = getattr(cfg, "prz_cluster_tol", 3.0)

        def emit(name, color, d_anchor, r, ideal_b, ideal_c, k_used,
                 prz_hi=None, prz_lo=None):
            two_sided = prz_hi is not None      # Shark's 0.886-1.13 zone
            conf_n = 1

            g_lo, g_hi = _BC_GATE[name]
            if two_sided:
                # [BOOK] Shark: the Extreme Harmonic Impulse (bcp = BC/AB,
                # gated 1.618-2.24 by the caller) and the 0X-retracement B
                # point already define the pattern; the completion zone is
                # the 0.886-1.13 confluence of the 0X leg (= code XA). No
                # extra BC-projection reject here — that would double-count
                # the impulse leg the caller already gated.
                conf_n = 2
                d_ref = (prz_hi + prz_lo) / 2
                m_implied = safe_div(abs(cP - d_ref), bc)  # informational
            else:
                d_ref = d_anchor
                # [BOOK] implied BC projection m = CD/BC must sit inside the
                # pattern's book range (replaces the dead bc/ab gate of the
                # Pine port — see module docstring).
                m_implied = safe_div(abs(cP - d_ref), bc)
                if not bc_gate(m_implied, g_lo, g_hi, tol_val, sbc):
                    return

            if not two_sided:
                # [BOOK] confluence cluster around the XA anchor.
                levels = [d_anchor]
                for mult in _ABCD_MULTS.get(name, (1.0,)):
                    d_abcd = cP - mult * ab if bull else cP + mult * ab
                    if _near_pct(d_abcd, d_anchor, cluster_tol):
                        levels.append(d_abcd)
                bc_lvls = _BC_LEVELS[name]
                cand = [cP - m * bc if bull else cP + m * bc for m in bc_lvls]
                d_bc = min(cand, key=lambda v: abs(v - d_anchor))
                if _near_pct(d_bc, d_anchor, cluster_tol):
                    levels.append(d_bc)
                conf_n = len(levels)
                if conf_n == 1:
                    prz_hi_, prz_lo_ = d_anchor + r, d_anchor - r
                else:
                    pad = 0.35 * r
                    prz_hi_, prz_lo_ = max(levels) + pad, min(levels) - pad
            else:
                prz_hi_, prz_lo_ = prz_hi, prz_lo
                bc_lvls = _BC_LEVELS[name]
                cand = [cP - m * bc if bull else cP + m * bc for m in bc_lvls]
                d_bc = min(cand, key=lambda v: abs(v - d_ref))
                if prz_lo_ <= d_bc <= prz_hi_:
                    conf_n = 3

            if prz_lo_ <= 0:
                return
            mid = (prz_hi_ + prz_lo_) / 2
            if abs((mid - last_close) / last_close) * 100 > cfg.max_dist:
                return
            width_pct = (prz_hi_ - prz_lo_) / mid * 100
            if width_pct > cfg.prz_maxw:      # [DEVIATION] width guard
                return
            status, ft, ei = prz_status(high, low, close, prz_hi_, prz_lo_,
                                        bull, ci, cfg.rev_bars)
            det = Detection(
                ticker=ticker, pattern=name, color=color, bull=bull,
                depth=0, is_strict=is_strict,
                xi=xi, xP=xP, ai=ai, aP=aP, bi=bi, bP=bP, ci=ci, cP=cP,
                prz_hi=prz_hi_, prz_lo=prz_lo_, br=br, cr=cr, bcp=bcp,
                bc_proj=m_implied, conf_n=conf_n, confirm_bar=confirm_bar,
                status=status, first_touch_idx=ft, end_idx=ei,
            )
            det.dist_pct = (last_close - mid) / mid * 100
            det.score = _score(det, ideal_b, ideal_c, k_used, width_pct,
                               cfg.prz_maxw)
            _targets(det)
            dets.append(det)

        # ---- GARTLEY [BOOK-V3 p.92]: B=0.618 +/-3pp, D=0.786 XA ----
        if pe["Gartley"] and c_retr_ok and _b_ok("Gartley", br, is_strict) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            gd = aP - 0.786 * xa if bull else aP + 0.786 * xa
            emit("Gartley", "green", gd, xa * 0.03, 0.618, 0.618, 0.786)

        # ---- BAT [BOOK-V3 p.98]: B=0.382-0.50 (+5pp tol), D=0.886 XA ----
        if pe["Bat"] and c_retr_ok and _b_ok("Bat", br, is_strict) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            bd = aP - 0.886 * xa if bull else aP + 0.886 * xa
            emit("Bat", "blue", bd, xa * 0.03, 0.50, 0.618, 0.886)

        # ---- BUTTERFLY [BOOK-V3 p.113]: B=0.786 +/-3pp, D=1.27 XA ----
        if pe["Butterfly"] and c_retr_ok and _b_ok("Butterfly", br, is_strict) \
                and in_mm(cr, 0.382, 0.886, tol_val):
            fd = aP - 1.27 * xa if bull else aP + 1.27 * xa
            emit("Butterfly", "purple", fd, xa * 0.04, 0.786, 0.618, 1.27)

        # ---- CRAB [BOOK-V3 p.104]: B=0.382-0.618 (+5pp), D=1.618 XA ----
        if pe["Crab"] and c_retr_ok and _b_ok("Crab", br, is_strict) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            cd = aP - 1.618 * xa if bull else aP + 1.618 * xa
            emit("Crab", "orange", cd, xa * 0.05, 0.618, 0.618, 1.618)

        # ---- SHARK [BOOK-V3]: Extreme Harmonic Impulse leg 1.618-2.24,  ----
        # ---- completion zone 0.886-1.13 of XA (two-sided)              ----
        # bcp = BC/AB is the "extended AB Extreme Harmonic Impulse Wave"
        # which the book requires to be "at least 1.618 (can be as much as
        # 2.24)" — V3 p.118/120/129, stated three times. (The old Pine port
        # used 1.13-1.618, which is BELOW the book minimum — corrected here.)
        # The 0.382-0.618 B filter is an OFFICIAL V3 element (p.119:
        # "an additional measure at the 0X retracement of a 38.2-61.8%
        # at the A point ... does help to differentiate Shark structures").
        # NOTE anchor leg: V3's prose is internally inconsistent about the
        # completion zone's reference leg ("0B" pp.121/125/129 vs "XA/0X"
        # pp.120/125 vs "0C" p.127). We follow the classic published spec
        # (Vol.2 / Harmonic Analyzer): 0.886-1.13 of the initial 0X leg
        # (= code XA), which V3's own "1.0 XA level" wording also supports.
        if pe["Shark"] and c_ext_ok and _b_ok("Shark", br, is_strict) and \
                in_mm(bcp, 1.618, 2.24, tol_val):
            su = aP - 0.886 * xa if bull else aP + 0.886 * xa
            sl2 = aP - 1.13 * xa if bull else aP + 1.13 * xa
            shi = max(su, sl2); slo = min(su, sl2)
            # ideal_c (jangkar fidelity skor) = 1.929, titik tengah rentang
            # impuls buku 1.618-2.24: V3 memberi RENTANG (tiga kali) tanpa
            # satu nilai ideal, jadi midpoint = jangkar netral. Nilai lama
            # 1.414 (sisa gate Pine 1.13-1.618) berada DI LUAR rentang sah,
            # sehingga SETIAP Shark valid terpenalti fidelity dan makin
            # sesuai buku makin besar penaltinya (cr=2.0 -> fc 0.59) —
            # dedup/top-2 sistematis memilih varian impuls terlemah.
            emit("Shark", "red", None, None, 0.5, 1.929, 1.0,
                 prz_hi=shi, prz_lo=slo)

    return dets
