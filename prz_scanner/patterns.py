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
  5. Shark's extension leg (bc/ab) bounded to the book's 1.13-1.618 (with
     the same tolerance widening as every other ratio check), and its BC
     gate accepts any overlap of the 1.618-2.24 projection band with the
     0.886-1.13 completion zone. The B-retracement filter 0.382-0.618 on
     Shark is a [PINE] carry-over quality filter, not a book ratio.

Book ratio table implemented (D anchor as multiple of XA; bull direction):
  Gartley   B=0.618  C=0.382-0.886  BC proj 1.13-1.618   D=0.786  AB=CD
  Bat       B=0.382-0.50            BC proj 1.618-2.618  D=0.886  AB=CD/1.27
  Butterfly B=0.786                 BC proj 1.618-2.24   D=1.27   AB=CD/1.27
  Crab      B=0.382-0.618           BC proj 2.618-3.618  D=1.618  1.27/1.618
  Shark     ext leg 1.13-1.618 of AB; completion zone 0.886-1.13 of XA,
            BC proj 1.618-2.24 (per the book's 0-X-A-B-C labelling our
            X,A,B,C,D correspond to the book's 0,X,A,B,C).

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
    """[DEVIATION] Fib-based TP/SL off the XA leg from D (PRZ mid)."""
    xa = abs(det.aP - det.xP)
    d = det.prz_mid
    if det.bull:
        det.tp1 = d + 0.382 * xa
        det.tp2 = d + 0.618 * xa
        det.tp3 = d + 1.000 * xa
        det.stop = det.prz_lo - 0.10 * xa
    else:
        det.tp1 = d - 0.382 * xa
        det.tp2 = d - 0.618 * xa
        det.tp3 = d - 1.000 * xa
        det.stop = det.prz_hi + 0.10 * xa


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

# Book AB=CD completion multiples per pattern (1.0 = classic AB=CD;
# alternates per Carney: Bat/Butterfly 1.27, Crab 1.27 & 1.618).
_ABCD_MULTS = {
    "Gartley":   (1.0,),
    "Bat":       (1.0, 1.27),
    "Butterfly": (1.0, 1.27),
    "Crab":      (1.27, 1.618),
}

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
                tol_val: float, is_strict: bool, cfg) -> List[Detection]:
    dets: List[Detection] = []
    total = len(points)
    if total < 5:
        return dets

    last_close = close[-1]
    max_w = min(3, total - 4)   # Pine: maxW = min(3, totalP-4)

    for w in range(0, max_w + 1):
        idx = total - 4 - w
        if idx < 0:
            continue
        xP, xi, x_hi = points[idx]
        aP, ai, _ = points[idx + 1]
        bP, bi, _ = points[idx + 2]
        cP, ci, _ = points[idx + 3]
        bull = not x_hi

        # alternation check (Pine a1,a2,a3)
        t0 = points[idx][2]; t1 = points[idx + 1][2]
        t2 = points[idx + 2][2]; t3 = points[idx + 3][2]
        if not (t0 != t1 and t1 != t2 and t2 != t3):
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
                # [BOOK] Shark: completion zone is already the confluence of
                # the 0.886 and 1.13 levels of XA (book's 0X). Count them,
                # plus the BC projection if it lands inside the zone.
                conf_n = 2
                d_ref = (prz_hi + prz_lo) / 2
                # [BOOK] two-sided gate: the pattern is valid when the BC
                # projection band (1.618-2.24 of BC from C) OVERLAPS the
                # completion zone anywhere — not just at its midpoint.
                lo_t = g_lo * (1 - tol_val / 100)
                hi_t = g_hi * (1 + tol_val / 100)
                if bull:
                    band_lo, band_hi = cP - hi_t * bc, cP - lo_t * bc
                else:
                    band_lo, band_hi = cP + lo_t * bc, cP + hi_t * bc
                if sbc and not (band_lo <= prz_hi and band_hi >= prz_lo):
                    return
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
                bc_proj=m_implied, conf_n=conf_n,
                status=status, first_touch_idx=ft, end_idx=ei,
            )
            det.dist_pct = (last_close - mid) / mid * 100
            det.score = _score(det, ideal_b, ideal_c, k_used, width_pct,
                               cfg.prz_maxw)
            _targets(det)
            dets.append(det)

        # ---- GARTLEY [BOOK]: B=0.618, C=0.382-0.886, D=0.786 XA ----
        if pe["Gartley"] and c_retr_ok and in_r(br, 0.618, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            gd = aP - 0.786 * xa if bull else aP + 0.786 * xa
            emit("Gartley", "green", gd, xa * 0.03, 0.618, 0.618, 0.786)

        # ---- BAT [BOOK]: B=0.382-0.50 (ideal 0.50), D=0.886 XA ----
        if pe["Bat"] and c_retr_ok and in_mm(br, 0.382, 0.50, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            bd = aP - 0.886 * xa if bull else aP + 0.886 * xa
            emit("Bat", "blue", bd, xa * 0.03, 0.50, 0.618, 0.886)

        # ---- BUTTERFLY [BOOK]: B=0.786, D=1.27 XA ----
        if pe["Butterfly"] and c_retr_ok and in_r(br, 0.786, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            fd = aP - 1.27 * xa if bull else aP + 1.27 * xa
            emit("Butterfly", "purple", fd, xa * 0.04, 0.786, 0.618, 1.27)

        # ---- CRAB [BOOK]: B=0.382-0.618 (ideal 0.618), D=1.618 XA ----
        if pe["Crab"] and c_retr_ok and in_mm(br, 0.382, 0.618, tol_val) and \
                in_mm(cr, 0.382, 0.886, tol_val):
            cd = aP - 1.618 * xa if bull else aP + 1.618 * xa
            emit("Crab", "orange", cd, xa * 0.05, 0.618, 0.618, 1.618)

        # ---- SHARK [BOOK]: ext leg 1.13-1.618 of AB,               ----
        # ---- completion zone 0.886-1.13 of XA (two-sided)          ----
        # NOTE: the B-retracement filter 0.382-0.618 is a [PINE] quality
        # filter carried over from the port — Carney's Shark leaves this
        # leg unconstrained. Kept deliberately to suppress degenerate
        # geometries; it is NOT a book ratio.
        if pe["Shark"] and c_ext_ok and in_mm(br, 0.382, 0.618, tol_val) and \
                in_mm(bcp, 1.13, 1.618, tol_val):
            su = aP - 0.886 * xa if bull else aP + 0.886 * xa
            sl2 = aP - 1.13 * xa if bull else aP + 1.13 * xa
            shi = max(su, sl2); slo = min(su, sl2)
            emit("Shark", "red", None, None, 0.5, 1.414, 1.0,
                 prz_hi=shi, prz_lo=slo)

    return dets
