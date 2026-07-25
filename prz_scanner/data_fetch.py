"""TradingView (tvDatafeed) wrapper for PRZ Scanner.

Menggantikan yfinance karena Yahoo Finance secara permanen memblokir IP
dari Cloud/VPS providers (AWS, Tencent, DigitalOcean, dll).

TradingView tidak memblokir VPS dan datanya jauh lebih bersih:
  - Daily  ('1d') -> native 1D
  - Weekly ('1wk') -> native 1W
  - '4h' -> native 4H! (Tidak perlu lagi resample manual dari 60m)
"""

import time
import random
import logging
from typing import Dict, Optional
import pandas as pd

# tvDatafeed dari GitHub, DI-PIN ke commit di requirements.txt. Sengaja
# TANPA auto-pip-install saat import: proses produksi (VPS, env berisi
# bot token & API key) tidak boleh mengeksekusi installer dari jaringan —
# fork yang berubah/ter-compromise = eksekusi kode arbitrer di jalur scan
# (supply-chain risk, temuan audit 2026-07-25). Bila hilang: fail cepat
# dengan instruksi jelas.
try:
    from tvDatafeed import TvDatafeed, Interval
except ImportError as e:
    raise ImportError(
        "tvDatafeed belum terpasang. Jalankan: pip install -r requirements.txt"
    ) from e

# Suppress tvDatafeed's "nologin" warnings
logging.getLogger("tvDatafeed.main").setLevel(logging.CRITICAL)

from .config import Config

_TV = None

def _get_tv():
    global _TV
    if _TV is None:
        try:
            _TV = TvDatafeed()
        except Exception as e:
            print(f"[FATAL] Gagal inisialisasi TvDatafeed: {e}")
    return _TV


def _normalize(df: pd.DataFrame) -> Optional[pd.DataFrame]:
    """Ensure columns Open/High/Low/Close/Volume and drop NaN rows."""
    if df is None or df.empty:
        return None
    # tvDatafeed returns lowercase columns: symbol, open, high, low, close, volume
    df = df.rename(columns={
        "open": "Open",
        "high": "High",
        "low": "Low",
        "close": "Close",
        "volume": "Volume"
    })
    need = ["Open", "High", "Low", "Close", "Volume"]
    if not all(c in df.columns for c in need):
        return None
    df = df[need].dropna(how="any")
    return df if len(df) > 0 else None


def fetch_one(code: str, cfg: Config, retries: int = 3) -> Optional[pd.DataFrame]:
    """Fetch a single ticker's OHLC from TradingView."""
    tv = _get_tv()
    if tv is None:
        return None

    # Mapping timeframe ke TradingView args
    # Kita cukup menggunakan n_bars untuk menentukan seberapa jauh ke belakang
    if cfg.timeframe == "1d":
        interval = Interval.in_daily
        # ~2 tahun trading days; backtest dapat menaikkan via n_bars_daily
        n_bars = getattr(cfg, "n_bars_daily", 500)
    elif cfg.timeframe == "1wk":
        interval = Interval.in_weekly
        n_bars = 260  # ~5 tahun (52 mgg * 5)
    else:  # "4h"
        interval = Interval.in_4_hour
        n_bars = 500  # ~500 bar 4H cukup untuk zigzag depth 20

    for attempt in range(retries):
        try:
            df = tv.get_hist(symbol=code, exchange="IDX", interval=interval, n_bars=n_bars)
            res = _normalize(df)
            if res is not None:
                return res
                
            # Jika hasil kosong/None (sering karena rate-limit sesaat), tunggu sejenak lalu coba lagi
            if attempt < retries - 1:
                time.sleep(1.5 + random.uniform(0, 1.0))
        except Exception as e:
            if attempt < retries - 1:
                time.sleep(1.5 + random.uniform(0, 1.0))
            else:
                print(f"[WARN] fetch failed {code}: {e}")
                
    return None


def fetch_all(cfg: Config, pause: float = 0.2) -> Dict[str, pd.DataFrame]:
    """Fetch every ticker in the watchlist. Skips failures."""
    out: Dict[str, pd.DataFrame] = {}
    for code in cfg.watchlist:
        df = fetch_one(code, cfg)
        if df is not None and len(df) >= 40:
            out[code] = df
        else:
            print(f"[SKIP] {code}: no/insufficient data")
        
        # TradingView sangat ramah, pause 0.2s sudah cukup
        time.sleep(pause + random.uniform(0, 0.2))
    return out


def fetch_realtime_prices(codes: list, pause: float = 0.0) -> Dict[str, float]:
    """Fetch latest traded price for each ticker.
    
    Karena TradingView tidak punya endpoint batch untuk nologin, kita akan
    fetch 1 bar terakhir untuk timeframe Daily. Ini lebih aman dari Yahoo.
    """
    tv = _get_tv()
    if tv is None or not codes:
        return {}

    prices: Dict[str, float] = {}
    for code in codes:
        try:
            df = tv.get_hist(symbol=code, exchange="IDX", interval=Interval.in_daily, n_bars=1)
            if df is not None and not df.empty and "close" in df.columns:
                prices[code] = float(df["close"].iloc[-1])
        except Exception:
            pass
        # Tidur sangat singkat agar batch tidak terlalu lama
        time.sleep(0.05)

    return prices
