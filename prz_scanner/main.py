"""CLI entrypoint for the PRZ Buy Zone Scanner.

Usage:
    python -m prz_scanner.main                     # scan LQ45 daily
    python -m prz_scanner.main --timeframe 4h
    python -m prz_scanner.main --tickers BBCA BMRI TLKM
    python -m prz_scanner.main --proximity 5 --max-dist 60 --no-charts
"""

import argparse
import sys

from .config import Config
from .data_fetch import fetch_all
from .scanner import scan_watchlist
from .chart_render import render_chart
from .summary import build_summary, write_summary


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(description="PRZ Harmonic Buy Zone Scanner (LQ45)")
    p.add_argument("--timeframe", choices=["1d", "1wk", "4h"], default="1d")
    p.add_argument("--tickers", nargs="+", help="override watchlist (codes w/o .JK)")
    p.add_argument("--depths", nargs="+", type=int)
    p.add_argument("--proximity", type=float, help="proximity_pct (default 3.0)")
    p.add_argument("--max-dist", type=float, help="max PRZ distance %% (default 80)")
    p.add_argument("--prz-maxw", type=float, help="max PRZ width %% (default 15)")
    p.add_argument("--tol-strict", type=float)
    p.add_argument("--tol-loose", type=float)
    p.add_argument("--strict-bc", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="book BC-projection gate (default ON; --no-strict-bc disables)")
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--output", default="output")
    return p.parse_args(argv)


def build_config(args: argparse.Namespace) -> Config:
    cfg = Config()
    cfg.timeframe = args.timeframe
    if args.tickers:
        cfg.watchlist = [t.upper() for t in args.tickers]
    if args.depths:
        cfg.depths = args.depths
    if args.proximity is not None:
        cfg.proximity_pct = args.proximity
    if args.max_dist is not None:
        cfg.max_dist = args.max_dist
    if args.prz_maxw is not None:
        cfg.prz_maxw = args.prz_maxw
    if args.tol_strict is not None:
        cfg.tol_strict = args.tol_strict
    if args.tol_loose is not None:
        cfg.tol_loose = args.tol_loose
    cfg.strict_bc = args.strict_bc
    cfg.output_dir = args.output
    return cfg


def main(argv=None) -> int:
    args = parse_args(argv)
    cfg = build_config(args)

    print(f"[1/4] Fetching {len(cfg.watchlist)} tickers ({cfg.timeframe})...")
    data = fetch_all(cfg)
    print(f"      got data for {len(data)} tickers")

    print("[2/4] Scanning for harmonic PRZ buy zones...")
    results = scan_watchlist(data, cfg)
    print(f"      {len(results)} stocks passed the proximity filter")

    print("[3/4] Writing summary...")
    df = build_summary(results, cfg.timeframe)
    csv_path, txt_path = write_summary(df, cfg.output_dir)
    print(f"      -> {csv_path}")
    if not df.empty:
        print("\n" + df.to_string(index=False) + "\n")

    if not args.no_charts:
        print("[4/4] Rendering charts...")
        for r in results:
            try:
                path = render_chart(r, timeframe=cfg.timeframe,
                                    out_dir=cfg.output_dir)
                print(f"      -> {path}")
            except Exception as e:
                print(f"      [WARN] chart failed {r.ticker}: {e}")
    else:
        print("[4/4] Charts skipped (--no-charts)")

    print("Done.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
