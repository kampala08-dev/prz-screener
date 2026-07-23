"""Backtest runner untuk strategi PRZ Harmonic BUY.

Usage:
    python run_backtest.py                          # semua saham, ~5 tahun
    python run_backtest.py --tickers BBCA BMRI      # subset
    python run_backtest.py --bars 750 --max-hold 40
"""

import argparse
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prz_scanner.config import daily_config
from prz_scanner.data_fetch import fetch_all
from prz_scanner.backtest import backtest_universe, summarize


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="Backtest PRZ Harmonic BUY (Daily)")
    p.add_argument("--tickers", nargs="+",
                   help="override watchlist (tanpa .JK)")
    p.add_argument("--bars", type=int, default=1250,
                   help="jumlah bar daily yang di-fetch (default 1250 ~ 5 tahun)")
    p.add_argument("--max-hold", type=int, default=60,
                   help="maks bar menahan posisi sebelum TIMEOUT (default 60)")
    p.add_argument("--entry-window", type=int, default=60,
                   help="maks bar menunggu sentuhan PRZ setelah konfirmasi (default 60)")
    p.add_argument("--include-sell", action="store_true",
                   help="ikutkan pola bearish (default: BUY saja)")
    p.add_argument("--output", default="output/backtest",
                   help="folder output (default: output/backtest)")
    return p.parse_args(argv)


def main(argv=None):
    args = parse_args(argv)
    cfg = daily_config()
    if args.tickers:
        cfg.watchlist = [t.strip().upper() for t in args.tickers]
    cfg.n_bars_daily = args.bars

    print("=" * 62)
    print("  PRZ Harmonic BUY Backtest  -  Daily")
    print("=" * 62)
    print(f"  Watchlist : {len(cfg.watchlist)} ticker(s)")
    print(f"  History   : {args.bars} bar (~{args.bars / 250:.1f} tahun)")
    print(f"  Max hold  : {args.max_hold} bar")
    print(f"  Entry win : {args.entry_window} bar setelah konfirmasi")
    print(f"  Arah      : {'BUY+SELL' if args.include_sell else 'BUY only'}")
    print("-" * 62)

    print(f"\n[1/3] Fetching {len(cfg.watchlist)} tickers...")
    data = fetch_all(cfg)
    print(f"      got data for {len(data)} ticker(s)")
    if not data:
        print("[ERROR] tidak ada data.")
        return 1

    print("\n[2/3] Menjalankan backtest...")
    trades = backtest_universe(data, cfg, max_hold=args.max_hold,
                               bull_only=not args.include_sell,
                               entry_window=args.entry_window)
    print(f"      {len(trades)} deteksi historis diproses")

    print("\n[3/3] Agregasi & simpan hasil...")
    summary = summarize(trades)
    os.makedirs(args.output, exist_ok=True)

    tdf = summary.get("trades")
    if tdf is not None and not tdf.empty:
        csv_path = os.path.join(args.output, "trades.csv")
        tdf.to_csv(csv_path, index=False)
        print(f"      -> {csv_path}")

    lines = []
    print("")
    print("  CATATAN: R = kebijakan tetap exit di TP1 (avg_R_tp1);")
    print("  avg_R_env = batas atas oracle, BUKAN hasil yang dapat direplikasi.")
    print("  Win rate absolut optimistis krn survivorship universe 2026;")
    print("  perbandingan RELATIF antar pola/conf lebih dapat dipercaya.")
    for name in ("overall", "by_pattern", "by_conf", "by_score",
                 "by_tol", "by_year", "excluded"):
        tbl = summary.get(name)
        if tbl is None or tbl.empty:
            continue
        header = f"\n===== {name.upper()} ====="
        body = tbl.to_string()
        print(header)
        print(body)
        lines.append(header)
        lines.append(body)

    txt_path = os.path.join(args.output, "summary.txt")
    with open(txt_path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"\n      -> {txt_path}")
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
