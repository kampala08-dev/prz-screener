"""Scan the watchlist, apply the BUY proximity filter, pick best per stock.

Filter (PRD §5 — [DEVIATION] proximity concept, not in Pine):
  A stock PASSES if it has >=1 BULLISH pattern whose PRZ is either
    (a) already containing close (prz_lo <= close <= prz_hi), OR
    (b) close is ABOVE the PRZ within proximity_pct heading down toward it
        i.e. 0 < (close - prz_hi)/prz_hi*100 <= proximity_pct
  Valid/invalid is reported but NOT a pass condition.

Best-pattern selection per stock (Pine f_pickBest priority):
  1. valid > invalid   2. closer to price   3. XABCD (all are here)   4. score.

Chart display ([DEVIATION]): only the top `cfg.max_display` (default 2)
patterns are drawn — ranked nearest-to-price first, highest accuracy score
as tie-break, valid before invalid; the best buy is always included. This
replaces the old draw-everything behaviour that cluttered charts.
"""

from dataclasses import dataclass
from typing import Dict, List, Optional
import numpy as np
import pandas as pd

from .config import Config
from .patterns import Detection, scan_points
from .zigzag import compute_zigzag


@dataclass
class StockResult:
    ticker: str
    df: pd.DataFrame
    all_dets: List[Detection]      # every deduped detection (buy+sell)
    best_buy: Optional[Detection]  # ranked best bullish for summary
    passed: bool
    realtime_close: Optional[float] = None  # harga real-time (5m delayed), None jika tidak tersedia
    top_dets: List[Detection] = None  # nearest+highest-accuracy picks for chart


# Two detections of the same pattern/direction whose PRZ mids sit within
# this % of each other are considered the same zone (across depth passes).
_DEDUP_MID_PCT = 1.5


def _dedup(dets: List[Detection]) -> List[Detection]:
    """Collapse near-identical detections (same pattern/dir with PRZ mids
    within _DEDUP_MID_PCT%) across depth+tolerance passes, keeping the
    highest-scoring one. Greedy over score-descending order."""
    out: List[Detection] = []
    for d in sorted(dets, key=lambda x: -x.score):
        dup = any(
            k.pattern == d.pattern and k.bull == d.bull
            and abs(k.prz_mid - d.prz_mid) / abs(k.prz_mid) * 100 < _DEDUP_MID_PCT
            for k in out if k.prz_mid != 0
        )
        if not dup:
            out.append(d)
    return out


def _dist_to_prz(d: Detection, last_close: float) -> float:
    """Unsigned % gap between price and the PRZ (0 when inside)."""
    if d.prz_lo <= last_close <= d.prz_hi:
        return 0.0
    if last_close > d.prz_hi:
        return (last_close - d.prz_hi) / d.prz_hi * 100
    return (d.prz_lo - last_close) / max(last_close, 1e-9) * 100


def _pick_top(dets: List[Detection], best_buy: Optional[Detection],
              last_close: float, max_display: int) -> List[Detection]:
    """[DEVIATION] Chart picks: the `max_display` nearest patterns, using
    accuracy score to break near-ties (2%-wide distance buckets), valid
    before invalid. The best buy is always kept."""
    def rank(d: Detection):
        return (0 if d.valid else 1,
                round(_dist_to_prz(d, last_close) / 2.0),
                -d.score)
    top = sorted(dets, key=rank)[:max_display]
    if best_buy is not None and best_buy not in top:
        top = [best_buy] + top[:max_display - 1]
    return top


def scan_stock(ticker: str, df: pd.DataFrame, cfg: Config,
               realtime_price: Optional[float] = None) -> StockResult:
    """Scan one stock. realtime_price overrides last candle close for proximity
    check & display — pattern detection always uses the full historical array."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)
    # Pakai harga real-time untuk proximity & display jika tersedia.
    # Pattern detection (zigzag, XABCD) tetap pakai seluruh array historis.
    last_close = realtime_price if realtime_price is not None else close[-1]

    dets: List[Detection] = []
    tol_passes = []
    if cfg.enable_strict:
        tol_passes.append((cfg.tol_strict, True))
    if cfg.enable_loose:
        tol_passes.append((cfg.tol_loose, False))

    for depth in cfg.depths:
        pts = compute_zigzag(high, low, depth)
        for tol_val, is_strict in tol_passes:
            found = scan_points(ticker, pts, high, low, close,
                                tol_val, is_strict, cfg)
            for d in found:
                d.depth = depth
            dets.extend(found)

    dets = _dedup(dets)

    # ---- proximity filter on BULLISH detections ----
    def prox_ok(d: Detection) -> bool:
        if not d.bull:
            return False
        if d.prz_lo <= last_close <= d.prz_hi:
            return True  # inside PRZ
        # above PRZ, heading down toward it, within proximity_pct
        if last_close > d.prz_hi:
            gap = (last_close - d.prz_hi) / d.prz_hi * 100
            return gap <= cfg.proximity_pct
        return False

    buy_candidates = [d for d in dets if prox_ok(d)]
    passed = len(buy_candidates) > 0

    best_buy = None
    if buy_candidates:
        # Pine f_pickBest: valid first, then nearest to price, then score.
        def rank(d: Detection):
            inside = d.prz_lo <= last_close <= d.prz_hi
            dist = 0.0 if inside else abs(last_close - d.prz_hi) / d.prz_hi
            return (0 if d.valid else 1, dist, -d.score)
        best_buy = sorted(buy_candidates, key=rank)[0]

    top_dets = _pick_top(dets, best_buy, last_close,
                         getattr(cfg, "max_display", 2))

    return StockResult(ticker=ticker, df=df, all_dets=dets,
                       best_buy=best_buy, passed=passed,
                       realtime_close=realtime_price, top_dets=top_dets)


# Backtest-proven signal subset (5y walk-forward, 362 saham; lihat
# docs/PERUBAHAN_SCREENER.md): Crab 63.9% & Bat 53.8% win; gabungan
# dengan confluence >=2 -> 58.2% win, +0.163R (bertahan di 2024+).
QUALITY_PATTERNS = ("Crab", "Bat")
QUALITY_MIN_CONF = 2


def filter_results(results: List["StockResult"],
                   only: Optional[List[str]] = None,
                   min_conf: int = 0) -> List["StockResult"]:
    """[DEVIATION] Signal-quality filter on scan results (post-scan).

    Keeps a stock only if its best_buy pattern is in `only` (case-
    insensitive; None = all patterns) AND its confluence count >= min_conf.
    Charts/summary/Telegram then show only the filtered set.
    """
    allowed = {p.lower() for p in only} if only else None
    out = []
    for r in results:
        d = r.best_buy
        if d is None:
            continue
        if allowed is not None and d.pattern.lower() not in allowed:
            continue
        if d.conf_n < min_conf:
            continue
        out.append(r)
    return out


def scan_watchlist(data: Dict[str, pd.DataFrame], cfg: Config,
                   realtime_prices: Dict[str, float] = None) -> List[StockResult]:
    """Scan all tickers. realtime_prices dict {ticker -> price} overrides
    last candle close for proximity check and display."""
    if realtime_prices is None:
        realtime_prices = {}
    results = []
    for ticker, df in data.items():
        try:
            rt_price = realtime_prices.get(ticker)
            res = scan_stock(ticker, df, cfg, realtime_price=rt_price)
            if res.passed:
                results.append(res)
        except Exception as e:
            print(f"[WARN] scan failed {ticker}: {e}")
    # order: inside-PRZ first, then nearest, then score
    def order(r: StockResult):
        d = r.best_buy
        return (abs(d.dist_pct), -d.score)
    results.sort(key=order)
    return results
