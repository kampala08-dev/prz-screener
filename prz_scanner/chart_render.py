"""Render a candlestick chart per passing stock with PRZ overlays.

[DEVIATION] Display policy (chart neatness):
  - Only the top `max_display` (default 2) patterns are drawn — the
    nearest-to-price, highest-accuracy picks from scanner._pick_top —
    instead of every deduped detection (which cluttered charts badly).
  - Each pattern draws its full X-A-B-C-D geometry: solid legs to C, a
    dashed projection C→D into extended right-margin space, a D marker at
    the PRZ mid, and the XB/AC helper diagonals of the classic harmonic
    triangle drawing.
  - Leg ratio labels (B retracement of XA, C retracement of AB, D as a
    multiple of XA) are annotated like TradingView's harmonic tools.
  - TP/SL lines are drawn for the best buy only.
"""

import os
from datetime import datetime
from typing import List, Optional

import numpy as np
import pandas as pd
import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import mplfinance as mpf

from .patterns import Detection
from .scanner import StockResult


_PATTERN_COLOR = {
    "Gartley": "#2ca02c", "Bat": "#1f77b4", "Butterfly": "#9467bd",
    "Crab": "#ff7f0e", "Shark": "#d62728",
}


def _clip(idx: int, n: int) -> int:
    return max(0, min(idx, n - 1))


def _leg_label(ax, x0, y0, x1, y1, text, color):
    """Small ratio annotation at the midpoint of a leg."""
    ax.annotate(text, xy=((x0 + x1) / 2, (y0 + y1) / 2),
                xytext=(0, 3), textcoords="offset points",
                ha="center", va="bottom", fontsize=6, color=color,
                alpha=0.95,
                bbox=dict(boxstyle="round,pad=0.12", fc="white",
                          ec="none", alpha=0.55))


def render_chart(res: StockResult, *, timeframe: str, out_dir: str) -> str:
    """Render and save the chart PNG. Returns the file path."""
    df = res.df
    n = len(df)

    show = res.top_dets if res.top_dets else res.all_dets
    best = res.best_buy if res.best_buy is not None else (
        show[0] if show else None)

    # [DEVIATION] crop to the pattern region: long histories squeeze the
    # XABCD legs into a corner. Start a context margin before the earliest
    # X of the displayed patterns so the drawing is large and readable.
    if show:
        first_xi = min(_clip(d.xi, n) for d in show)
        ctx = max(15, int((n - first_xi) * 0.25))
        start = max(0, first_xi - ctx)
    else:
        start = 0

    dfp = df.iloc[start:].copy()
    dfp.index = pd.to_datetime(dfp.index)
    m = len(dfp)

    def bx(i: int) -> int:
        """Map a full-history bar index to cropped-chart coordinates."""
        return _clip(i - start, m)

    fig, axes = mpf.plot(
        dfp, type="candle", style="charles", volume=False,
        returnfig=True, figsize=(14, 8),
        title=f"{res.ticker}  {timeframe}",
        datetime_format="%Y-%m", xrotation=0,
    )
    ax = axes[0]

    # Extended right margin so the D projection & labels have room.
    pad = max(4, int(m * 0.07))
    ax.set_xlim(-1, m - 1 + pad)
    x_d = m - 1 + pad * 0.45          # x position of the projected D point
    x_lbl = m - 1 + pad * 0.95        # right-edge anchor for PRZ labels

    def draw(det: Detection, emphasize: bool):
        color = _PATTERN_COLOR.get(det.pattern, "gray")
        xs = [bx(det.xi), bx(det.ai), bx(det.bi), bx(det.ci)]
        ys = [det.xP, det.aP, det.bP, det.cP]
        lw = 1.8 if emphasize else 1.0
        alpha = 1.0 if emphasize else 0.55
        d_mid = det.prz_mid

        # Shaded pattern triangles (TradingView harmonic look):
        # X-A-B and B-C-D filled translucent so the shape pops out.
        fill_alpha = 0.16 if emphasize else 0.07
        ax.fill([xs[0], xs[1], xs[2]], [ys[0], ys[1], ys[2]],
                color=color, alpha=fill_alpha, lw=0, zorder=1)
        ax.fill([xs[2], xs[3], x_d], [ys[2], ys[3], d_mid],
                color=color, alpha=fill_alpha, lw=0, zorder=1)

        ax.plot(xs, ys, color=color, lw=lw, alpha=alpha,
                solid_capstyle="round")
        # XB / AC helper dashed lines (harmonic triangle look)
        ax.plot([xs[0], xs[2]], [ys[0], ys[2]], color=color, lw=0.6,
                ls=":", alpha=alpha * 0.6)
        ax.plot([xs[1], xs[3]], [ys[1], ys[3]], color=color, lw=0.6,
                ls=":", alpha=alpha * 0.6)

        # Projected D leg: dashed C -> D (PRZ mid), with a point marker.
        ax.plot([xs[3], x_d], [ys[3], d_mid], color=color, lw=lw * 0.8,
                ls="--", alpha=alpha, dash_capstyle="round")
        ax.plot([x_d], [d_mid], marker="o", ms=4, color=color, alpha=alpha)
        # CB helper diagonal into D (B -> D) completes the triangle.
        ax.plot([xs[2], x_d], [ys[2], d_mid], color=color, lw=0.6,
                ls=":", alpha=alpha * 0.6)

        # Point letters
        letters = ["X", "A", "B", "C"]
        for (px, py, lt) in zip(xs, ys, letters):
            va = "bottom" if py >= d_mid else "top"
            ax.annotate(lt, xy=(px, py), xytext=(0, 4 if va == "bottom" else -4),
                        textcoords="offset points", ha="center", va=va,
                        fontsize=7, fontweight="bold", color=color,
                        alpha=min(1.0, alpha + 0.2))
        ax.annotate("D", xy=(x_d, d_mid), xytext=(0, -8),
                    textcoords="offset points", ha="center", va="top",
                    fontsize=7, fontweight="bold", color=color,
                    alpha=min(1.0, alpha + 0.2))

        # Leg ratio labels: B ret of XA, C ret of AB, D multiple of XA.
        xa = abs(det.aP - det.xP)
        k_d = abs(det.aP - d_mid) / xa if xa > 0 else 0.0
        _leg_label(ax, xs[1], ys[1], xs[2], ys[2], f"{det.br:.3f}", color)
        _leg_label(ax, xs[2], ys[2], xs[3], ys[3], f"{det.cr:.3f}", color)
        _leg_label(ax, xs[3], ys[3], x_d, d_mid, f"{k_d:.3f}", color)

        # PRZ box from C to the extended right edge
        left = bx(det.ci)
        span = m - 1 + pad
        box_alpha = 0.16 if emphasize else 0.08
        ax.axhspan(det.prz_lo, det.prz_hi,
                   xmin=(left + 1) / (span + 1), xmax=1.0,
                   color=color, alpha=box_alpha, zorder=0)

        arrow = "▲BUY" if det.bull else "▼SELL"
        status_txt = {0: "active", 1: "reversal✓", 2: "INVALID",
                      3: "FLIP⚠"}.get(det.status, "")
        star = "★" if det.is_strict else "☆"
        lbl = (f"{star}{arrow} {det.pattern} "
               f"{det.prz_lo:.0f}-{det.prz_hi:.0f} "
               f"[{status_txt}] ×{det.conf_n} {det.score:.0f}pts")
        ax.annotate(lbl, xy=(x_lbl, det.prz_hi),
                    xytext=(-4, 2), textcoords="offset points",
                    ha="right", va="bottom", fontsize=7,
                    color="white",
                    bbox=dict(boxstyle="round,pad=0.2", fc=color,
                              ec="none", alpha=0.9 if emphasize else 0.55))

    # Draw de-emphasized first so the emphasized one sits on top.
    for d in sorted(show, key=lambda d: 1 if d is best else 0):
        draw(d, emphasize=(d is best))

    # TP/SL lines for best buy
    bb = res.best_buy
    if bb is not None:
        for lvl, name, c in [(bb.tp1, "TP1", "#2ca02c"),
                             (bb.tp2, "TP2", "#2ca02c"),
                             (bb.tp3, "TP3", "#2ca02c"),
                             (bb.stop, "SL", "#d62728")]:
            ax.axhline(lvl, color=c, lw=0.8, ls="--", alpha=0.7)
            ax.annotate(f"{name} {lvl:.0f}", xy=(0, lvl),
                        xytext=(2, 1), textcoords="offset points",
                        fontsize=6, color=c, va="bottom")

    os.makedirs(out_dir, exist_ok=True)
    date = datetime.now().strftime("%Y%m%d")
    path = os.path.join(out_dir, f"{res.ticker}_{timeframe}_{date}.png")
    fig.savefig(path, dpi=110, bbox_inches="tight")
    plt.close(fig)
    return path
