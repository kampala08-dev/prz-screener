import argparse
import html
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prz_scanner.config import daily_config
from prz_scanner.data_fetch import fetch_all, fetch_realtime_prices
from prz_scanner.scanner import scan_watchlist
from prz_scanner.chart_render import render_chart
from prz_scanner.summary import build_summary, write_summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="PRZ Harmonic Buy Zone Scanner - Daily (1d) Timeframe",
    )
    p.add_argument("--tickers", nargs="+",
                   help="override watchlist (kode tanpa .JK, contoh: BBCA BMRI)")
    p.add_argument("--depths", nargs="+", type=int,
                   help="zigzag depths (default: 3 5 8 12 20)")
    p.add_argument("--proximity", type=float,
                   help="proximity_pct dalam persen (default 3.0)")
    p.add_argument("--max-dist", type=float,
                   help="max jarak PRZ dari harga persen (default 80)")
    p.add_argument("--prz-maxw", type=float,
                   help="max lebar PRZ persen (default 15)")
    p.add_argument("--tol-strict", type=float)
    p.add_argument("--tol-loose", type=float)
    p.add_argument("--strict-bc", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="BC-projection gate sesuai buku (default ON; --no-strict-bc utk melonggarkan)")
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--output", default=None,
                   help="folder output (default: output/daily)")
    p.add_argument("--telegram", action="store_true",
                   help="kirim hasil ke grup Telegram")
    p.add_argument("--images-only", action="store_true",
                   help="saat --telegram: kirim PNG saja, skip pesan teks summary")
    p.add_argument("--tg-token", default=None, help="override Telegram bot token")
    p.add_argument("--tg-chat", default=None, help="override Telegram chat_id")
    p.add_argument("--cleanup", action="store_true",
                   help="hapus PNG & skip simpan summary ke disk setelah kirim ke Telegram")
    return p.parse_args(argv)


def build_config(args):
    cfg = daily_config()
    if args.tickers:
        cfg.watchlist = [t.strip().upper() for t in args.tickers]
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
    if args.output is not None:
        cfg.output_dir = args.output
    return cfg


def main(argv=None):
    args = parse_args(argv)
    cfg = build_config(args)

    print("=" * 60)
    print("  PRZ Buy Zone Scanner  -  Daily (1d) Timeframe")
    print("=" * 60)
    print(f"  Watchlist  : {len(cfg.watchlist)} ticker(s)")
    print(f"  Depths     : {cfg.depths}")
    print(f"  Proximity  : {cfg.proximity_pct}%")
    print(f"  Max dist   : {cfg.max_dist}%")
    print(f"  Output dir : {cfg.output_dir}")
    tg_mode = "images-only" if args.images_only else ("ON" if args.telegram else "off")
    print(f"  Telegram   : {tg_mode}")
    print("-" * 60)

    print(f"\n[1/4] Fetching {len(cfg.watchlist)} tickers (Daily 1d, 2y history)...")
    data = fetch_all(cfg)
    print(f"      got data for {len(data)} ticker(s)")

    n_tickers = len(data)
    print(f"      Fetching real-time prices ({n_tickers} tickers)...")
    realtime_prices = fetch_realtime_prices(list(data.keys()))
    rt_hit = sum(1 for c in data if c in realtime_prices)
    print(f"      Real-time prices: {rt_hit}/{n_tickers} tickers OK")

    if not data:
        print("[ERROR] Tidak ada data yang berhasil di-fetch.")
        return 1

    print("\n[2/4] Scanning harmonic PRZ buy zones (Daily)...")
    results = scan_watchlist(data, cfg, realtime_prices=realtime_prices)
    print(f"      {len(results)} saham lolos proximity filter")

    print("\n[3/4] Menulis summary...")
    df = build_summary(results, cfg.timeframe)
    if not (args.cleanup and args.telegram):
        csv_path, txt_path = write_summary(df, cfg.output_dir)
        print(f"      -> {csv_path}")
    else:
        print("      (--cleanup aktif: summary tidak disimpan ke disk)")
    if not df.empty:
        print("\n" + df.to_string(index=False) + "\n")
    else:
        print("  (tidak ada saham yang lolos filter)")

    chart_paths = {}
    if not args.no_charts:
        print("[4/4] Render chart PNG...")
        rendered = 0
        for r in results:
            try:
                path = render_chart(r, timeframe=cfg.timeframe,
                                    out_dir=cfg.output_dir)
                chart_paths[r.ticker] = path
                print(f"      -> {path}")
                rendered += 1
            except Exception as e:
                print(f"      [WARN] chart gagal {r.ticker}: {e}")
        print(f"      {rendered} chart(s) saved.")
    else:
        print("[4/4] Chart di-skip (--no-charts)")

    if args.telegram:
        print("\n[TG] Mengirim hasil ke Telegram...")
        try:
            from prz_scanner.telegram_notify import TelegramSender
            import time as _time
            tg = TelegramSender(token=args.tg_token or None, chat_id=args.tg_chat or None)

            # Kirim summary teks (skip jika --images-only)
            if not args.images_only:
                tg.send_summary(df, cfg.timeframe, total_scanned=len(data))
                _time.sleep(0.5)
            else:
                # Header singkat saja
                if not df.empty:
                    tg.send_message(
                        f"<b>PRZ Daily Scan</b> - {len(results)} saham mendekati PRZ BUY zone"
                    )
                    _time.sleep(0.5)

            if df.empty:
                tg.send_message("<b>PRZ Daily Scan</b>\nTidak ada saham yang mendekati PRZ saat ini.")

            sent = 0
            for r in results:
                path = chart_paths.get(r.ticker)
                if not path or not os.path.exists(path):
                    print(f"  [TG] Chart {r.ticker} tidak ada, skip.")
                    continue
                bb = r.best_buy
                last_close = r.realtime_close if r.realtime_close is not None else float(r.df["Close"].iloc[-1])
                valid_str = "\u2705 valid" if bb.valid else "\u26a0\ufe0f invalid"
                inside = bb.prz_lo <= last_close <= bb.prz_hi
                status_disp = "\U0001f4cd INSIDE PRZ" if inside else f"approaching {bb.dist_pct:.1f}% \U0001f53d"
                caption = (
                    f"<b>{html.escape(r.ticker)}</b> | Daily | {html.escape(bb.pattern)} | {valid_str}\n"
                    f"PRZ: <code>{bb.prz_lo:.0f} - {bb.prz_hi:.0f}</code>\n"
                    f"Close: <code>{last_close:.0f}</code> | {status_disp}\n"
                    f"Score: <code>{bb.score:.0f}</code> | TP1: <code>{bb.tp1:.0f}</code> | Stop: <code>{bb.stop:.0f}</code>"
                )
                print(f"  [TG] Mengirim {r.ticker}...")
                ok = tg.send_photo(path, caption)
                if ok:
                    sent += 1
                    if args.cleanup:
                        try:
                            os.remove(path)
                        except OSError:
                            pass
                _time.sleep(1.5)
            print(f"  [TG] {sent} chart(s) terkirim.")
        except Exception as e:
            print(f"  [TG ERROR] {e}")

    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
