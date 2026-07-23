"""Build the summary table (CSV + pretty text) of passing stocks."""

import os
from datetime import datetime
from typing import List
import pandas as pd

from .scanner import StockResult


def _safe_write(path: str, write_fn) -> str:
    """Write via write_fn(path). If the file is locked (open in Excel etc.),
    fall back to a timestamped name instead of crashing the whole scan."""
    try:
        write_fn(path)
        return path
    except PermissionError:
        base, ext = os.path.splitext(path)
        alt = f"{base}_{datetime.now():%H%M%S}{ext}"
        write_fn(alt)
        print(f"[WARN] '{path}' terkunci (mungkin terbuka di Excel). "
              f"Disimpan ke '{alt}' sebagai gantinya.")
        return alt


def build_summary(results: List[StockResult], timeframe: str) -> pd.DataFrame:
    rows = []
    for r in results:
        d = r.best_buy
        # Pakai harga real-time jika tersedia, fallback ke candle close historis
        last_close = r.realtime_close if r.realtime_close is not None \
            else float(r.df["Close"].iloc[-1])
        inside = d.prz_lo <= last_close <= d.prz_hi
        gap = 0.0 if inside else (last_close - d.prz_hi) / d.prz_hi * 100

        rows.append({
            "Ticker": r.ticker,
            "Pattern": d.pattern,
            "TF": timeframe,
            "Depth": d.depth,
            "Tol": "strict" if d.is_strict else "loose",
            "PRZ_low": round(d.prz_lo, 2),
            "PRZ_high": round(d.prz_hi, 2),
            "Close": round(last_close, 2),
            "Dist%": round(0.0 if inside else gap, 2),
            "Zone": "INSIDE" if inside else "approaching",
            "Valid": "valid" if d.valid else "invalid",
            "Conf": d.conf_n,
            "Score": round(d.score, 1),
            "TP1": round(d.tp1, 2),
            "TP2": round(d.tp2, 2),
            "TP3": round(d.tp3, 2),
            "Stop": round(d.stop, 2),
        })
    df = pd.DataFrame(rows)
    if not df.empty:
        df = df.sort_values(["Dist%", "Score"], ascending=[True, False])
    return df


def write_summary(df: pd.DataFrame, out_dir: str, suffix: str = "") -> tuple:
    """Write summary to CSV and TXT.

    Args:
        df       : Summary DataFrame from build_summary().
        out_dir  : Output directory (created if missing).
        suffix   : Optional filename suffix, e.g. '_h4' -> 'summary_h4.csv'.
                   Leave empty for the default 'summary.csv'.
    """
    os.makedirs(out_dir, exist_ok=True)
    name = f"summary{suffix}"
    csv_path = os.path.join(out_dir, f"{name}.csv")
    txt_path = os.path.join(out_dir, f"{name}.txt")

    def _csv(p):
        df.to_csv(p, index=False)

    def _txt(p):
        with open(p, "w", encoding="utf-8") as f:
            f.write(df.to_string(index=False) if not df.empty
                    else "No stocks passed the proximity filter.\n")

    csv_path = _safe_write(csv_path, _csv)
    txt_path = _safe_write(txt_path, _txt)
    return csv_path, txt_path

