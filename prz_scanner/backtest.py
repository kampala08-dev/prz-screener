"""Walk-forward backtest for the harmonic PRZ BUY strategy.

Methodology (no-lookahead discipline; hardened after adversarial review):
  - Patterns are detected over the FULL history via scan_points
    all_windows=True (every historical XABC pivot quadruple), using the
    exact same [BOOK-V3] rules as the live scanner.
  - Confirmation: confirm_idx = det.confirm_bar + depth, where
    confirm_bar is the max RAW pivot bar of the XABC window (zigzag
    with_confirm=True). This prevents the snap-to-extreme pass — which
    can move a pivot's bar BACKWARD to an extreme that never confirmed
    as a pivot — from making patterns "knowable" earlier than any live
    scan of the prefix could have known them.
  - Entry: the first bar after confirm_idx, WITHIN entry_window bars,
    whose low touches the PRZ (bull). Fill = min(open, prz_hi); a bar
    gapping straight through the zone (open < prz_lo) is skipped as
    un-fillable; a touch after the window is EXPIRED (a live trader
    would not act on a months-old alert).
  - Exit simulation is CONSERVATIVE:
      * On the ENTRY bar only the stop is evaluated — the bar's high may
        precede the intrabar fill, so no TP credit is given for it.
      * On any later bar where both a TP and the stop are touched, the
        stop is assumed to hit first. Stops fill at min(open, stop).
  - outcome = deepest TP touched before SL/timeout (TP3 > TP2 > TP1;
    informational). r_mult however is a FIXED implementable policy:
    exit the full position at the TP1 limit (wins exit at tp1 on the
    tp1-touch bar; SL at the stop fill; TIMEOUT at the last close).
    r_deepest additionally reports the deepest-TP envelope — an upper
    bound, NOT an achievable ensemble result (per-trade oracle).
  - det.status / first_touch (prz_status) are NOT used — they are
    computed over future data and would leak.

Known residual limitations (disclosed, not fixable from available data):
  - SURVIVORSHIP/SELECTION: the universe is today's IDX liquidity
    ranking backtested into the past; delisted/dead tickers are absent
    and multi-year winners over-represented. Absolute win rates are
    optimistic; RELATIVE comparisons (pattern vs pattern, conf vs conf)
    are far more trustworthy. See the by_year table.
  - REPAINT FOLDING: the single-pass zigzag folds away some pivots that
    a live prefix scan once showed (merge of same-direction extremes),
    so the trade list is the survivor set of a repainting indicator;
    direction of the bias is mixed. A full expanding-prefix simulation
    would be needed to eliminate it.
"""

from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np
import pandas as pd

from .config import Config
from .patterns import Detection, scan_points
from .zigzag import compute_zigzag


# ---------------------------------------------------------------------------
@dataclass
class Trade:
    ticker: str
    pattern: str
    bull: bool
    depth: int
    is_strict: bool
    conf_n: int
    score: float
    ci: int
    confirm_idx: int
    entry_idx: int = -1
    entry: float = 0.0
    stop: float = 0.0
    tp1: float = 0.0
    tp2: float = 0.0
    tp3: float = 0.0
    # SL/TP1/TP2/TP3/TIMEOUT/OPEN/NO_ENTRY/SKIP_GAP/EXPIRED
    outcome: str = "NO_ENTRY"
    exit_idx: int = -1
    exit_price: float = 0.0
    r_mult: float = 0.0        # FIXED policy: full exit at TP1 limit
    r_deepest: float = 0.0     # oracle envelope (informational only)
    bars_held: int = 0
    entry_lag: int = 0         # bars from confirmation to entry
    prz_lo: float = 0.0
    prz_hi: float = 0.0
    entry_date: str = ""
    exit_date: str = ""


# ---------------------------------------------------------------------------
def _bt_config(base: Optional[Config] = None) -> Config:
    """Backtest config: identical detection rules, but the 'now'-relative
    filters (max_dist from current close) neutralised."""
    cfg = base or Config()
    cfg.max_dist = 1e9        # distance-to-now is meaningless historically
    return cfg


def _dedup_bt(dets: List[Detection]) -> List[Detection]:
    """Collapse the same historical zone found via multiple depth/tol
    passes: same pattern+direction, PRZ mids within 1.5% AND C pivots
    within 10 bars. Keeps the highest score."""
    out: List[Detection] = []
    for d in sorted(dets, key=lambda x: -x.score):
        dup = any(
            k.pattern == d.pattern and k.bull == d.bull
            and abs(k.ci - d.ci) <= 10
            and k.prz_mid != 0
            and abs(k.prz_mid - d.prz_mid) / abs(k.prz_mid) * 100 < 1.5
            for k in out
        )
        if not dup:
            out.append(d)
    return out


def find_historical_patterns(ticker: str, df: pd.DataFrame,
                             cfg: Config) -> List[Detection]:
    """All historical detections (deduped) using live-scanner rules."""
    high = df["High"].to_numpy(dtype=float)
    low = df["Low"].to_numpy(dtype=float)
    close = df["Close"].to_numpy(dtype=float)

    dets: List[Detection] = []
    tol_passes = []
    if cfg.enable_strict:
        tol_passes.append((cfg.tol_strict, True))
    if cfg.enable_loose:
        tol_passes.append((cfg.tol_loose, False))

    for depth in cfg.depths:
        pts = compute_zigzag(high, low, depth, max_points=10 ** 9,
                             with_confirm=True)
        for tol_val, is_strict in tol_passes:
            found = scan_points(ticker, pts, high, low, close,
                                tol_val, is_strict, cfg, all_windows=True)
            for d in found:
                d.depth = depth
            dets.extend(found)
    return _dedup_bt(dets)


# ---------------------------------------------------------------------------
def simulate_trade(det: Detection, df: pd.DataFrame,
                   max_hold: int = 60, entry_window: int = 60) -> Trade:
    """Simulate one BUY (or SELL mirror) trade for a detection.

    See the module docstring for the full (hardened) methodology.
    """
    o = df["Open"].to_numpy(dtype=float)
    h = df["High"].to_numpy(dtype=float)
    l = df["Low"].to_numpy(dtype=float)
    c = df["Close"].to_numpy(dtype=float)
    n = len(df)
    dates = df.index

    know = det.confirm_bar if det.confirm_bar >= 0 else det.ci
    t = Trade(ticker=det.ticker, pattern=det.pattern, bull=det.bull,
              depth=det.depth, is_strict=det.is_strict, conf_n=det.conf_n,
              score=det.score, ci=det.ci, confirm_idx=know + det.depth,
              stop=det.stop, tp1=det.tp1, tp2=det.tp2, tp3=det.tp3,
              prz_lo=det.prz_lo, prz_hi=det.prz_hi)

    if t.confirm_idx >= n - 1:
        return t                      # too fresh to ever enter (NO_ENTRY)

    # ---- entry: first PRZ touch after confirmation, within the window ----
    entry_idx = -1
    fill = 0.0
    limit = min(n, t.confirm_idx + 1 + entry_window)
    for i in range(t.confirm_idx + 1, limit):
        if det.bull:
            if l[i] <= det.prz_hi:
                fill = min(o[i], det.prz_hi)
                if fill < det.prz_lo:       # gapped through the zone
                    t.outcome = "SKIP_GAP"
                    return t
                entry_idx = i
                break
        else:
            if h[i] >= det.prz_lo:
                fill = max(o[i], det.prz_lo)
                if fill > det.prz_hi:
                    t.outcome = "SKIP_GAP"
                    return t
                entry_idx = i
                break
    if entry_idx < 0:
        # window fully elapsed in-data -> stale alert; else data ran out
        t.outcome = "EXPIRED" if limit < n else "NO_ENTRY"
        return t

    t.entry_idx = entry_idx
    t.entry = fill
    t.entry_lag = entry_idx - t.confirm_idx
    t.entry_date = str(dates[entry_idx])[:10]
    risk = (t.entry - det.stop) if det.bull else (det.stop - t.entry)
    if risk <= 0:
        t.outcome = "SKIP_GAP"        # filled at/through the stop level
        return t

    # ---- walk forward: conservative SL-first; entry bar = SL check only ----
    deepest = 0
    tp1_idx = -1
    end = min(n, entry_idx + max_hold + 1)
    terminal = False
    for j in range(entry_idx, end):
        if det.bull:
            if l[j] <= det.stop:      # SL first on ambiguous bars
                t.exit_idx = j
                t.exit_price = min(o[j], det.stop) if j > entry_idx else det.stop
                t.outcome = f"TP{deepest}" if deepest else "SL"
                terminal = True
                break
            if j == entry_idx:
                continue              # no TP credit on the entry bar
            if h[j] >= det.tp1 and tp1_idx < 0:
                tp1_idx = j
            if h[j] >= det.tp3:
                deepest = 3
                t.exit_idx = j
                t.outcome = "TP3"
                terminal = True
                break
            if h[j] >= det.tp2:
                deepest = max(deepest, 2)
            elif h[j] >= det.tp1:
                deepest = max(deepest, 1)
        else:
            if h[j] >= det.stop:
                t.exit_idx = j
                t.exit_price = max(o[j], det.stop) if j > entry_idx else det.stop
                t.outcome = f"TP{deepest}" if deepest else "SL"
                terminal = True
                break
            if j == entry_idx:
                continue
            if l[j] <= det.tp1 and tp1_idx < 0:
                tp1_idx = j
            if l[j] <= det.tp3:
                deepest = 3
                t.exit_idx = j
                t.outcome = "TP3"
                terminal = True
                break
            if l[j] <= det.tp2:
                deepest = max(deepest, 2)
            elif l[j] <= det.tp1:
                deepest = max(deepest, 1)
    if not terminal:
        # neither SL nor TP3 terminal within the window
        j = end - 1
        if deepest:
            t.outcome = f"TP{deepest}"          # TP reached, never stopped
        elif end == n and n - entry_idx <= max_hold:
            t.outcome = "OPEN"        # ran out of data, not of patience
        else:
            t.outcome = "TIMEOUT"
        t.exit_idx = j
        t.exit_price = c[j]

    # ---- FIXED TP1-limit policy: wins exit at tp1 on its touch bar ----
    is_win = t.outcome in ("TP1", "TP2", "TP3")
    if is_win:
        t.exit_price = det.tp1
        if tp1_idx >= 0:
            t.exit_idx = tp1_idx

    t.exit_date = str(dates[t.exit_idx])[:10] if t.exit_idx >= 0 else ""
    t.bars_held = max(0, t.exit_idx - entry_idx)
    move = (t.exit_price - t.entry) if det.bull else (t.entry - t.exit_price)
    t.r_mult = move / risk

    # oracle envelope (informational): exit at the deepest TP touched
    if is_win:
        tp_lvl = {1: det.tp1, 2: det.tp2, 3: det.tp3}[deepest]
        env = (tp_lvl - t.entry) if det.bull else (t.entry - tp_lvl)
        t.r_deepest = env / risk
    else:
        t.r_deepest = t.r_mult
    return t


# ---------------------------------------------------------------------------
def backtest_ticker(ticker: str, df: pd.DataFrame, cfg: Config,
                    max_hold: int = 60, bull_only: bool = True,
                    entry_window: int = 60) -> List[Trade]:
    dets = find_historical_patterns(ticker, df, cfg)
    if bull_only:
        dets = [d for d in dets if d.bull]
    trades = [simulate_trade(d, df, max_hold=max_hold,
                             entry_window=entry_window) for d in dets]
    return trades


def backtest_universe(data: Dict[str, pd.DataFrame], cfg: Optional[Config],
                      max_hold: int = 60, bull_only: bool = True,
                      entry_window: int = 60) -> List[Trade]:
    cfg = _bt_config(cfg)
    all_trades: List[Trade] = []
    for tkr, df in data.items():
        try:
            all_trades.extend(
                backtest_ticker(tkr, df, cfg, max_hold, bull_only,
                                entry_window))
        except Exception as e:      # keep the run alive; report the ticker
            print(f"[WARN] backtest failed {tkr}: {e}")
    return all_trades


# ---------------------------------------------------------------------------
_EXECUTED = ("SL", "TP1", "TP2", "TP3", "TIMEOUT")


def summarize(trades: List[Trade]) -> Dict[str, pd.DataFrame]:
    """Aggregate metrics. Win = TP1+ reached before SL. OPEN/NO_ENTRY/
    SKIP_GAP excluded from win-rate math (reported separately)."""
    rows = [vars(t) for t in trades]
    df = pd.DataFrame(rows)
    out: Dict[str, pd.DataFrame] = {}
    if df.empty:
        return {"overall": df}

    ex = df[df["outcome"].isin(_EXECUTED)].copy()
    ex["win"] = ex["outcome"].isin(("TP1", "TP2", "TP3"))
    ex["score_bucket"] = (ex["score"] // 10 * 10).astype(int)

    def agg(g: pd.DataFrame) -> pd.Series:
        n = len(g)
        return pd.Series({
            "trades": n,
            "win_rate_%": round(100 * g["win"].mean(), 1) if n else 0.0,
            "tp1_%": round(100 * (g["outcome"] == "TP1").mean(), 1),
            "tp2_%": round(100 * (g["outcome"] == "TP2").mean(), 1),
            "tp3_%": round(100 * (g["outcome"] == "TP3").mean(), 1),
            "sl_%": round(100 * (g["outcome"] == "SL").mean(), 1),
            "timeout_%": round(100 * (g["outcome"] == "TIMEOUT").mean(), 1),
            "avg_R_tp1": round(g["r_mult"].mean(), 3),
            "avg_R_env": round(g["r_deepest"].mean(), 3),
            "median_bars": g["bars_held"].median(),
        })

    def by(frame: pd.DataFrame, key) -> pd.DataFrame:
        # version-proof groupby-aggregate (no DataFrameGroupBy.apply)
        return pd.DataFrame(
            {k: agg(g) for k, g in frame.groupby(key)}).T.sort_index()

    out["overall"] = agg(ex).to_frame("ALL").T
    out["by_pattern"] = by(ex, "pattern")
    out["by_conf"] = by(ex, "conf_n")
    out["by_score"] = by(ex, "score_bucket")
    out["by_tol"] = by(
        ex, ex["is_strict"].map({True: "strict", False: "loose"}))
    # per-year view — recent years suffer least from the today's-universe
    # survivorship bias (see module docstring)
    out["by_year"] = by(ex, ex["entry_date"].str[:4])
    out["excluded"] = df[~df["outcome"].isin(_EXECUTED)]["outcome"] \
        .value_counts().to_frame("count")
    out["trades"] = df
    return out
