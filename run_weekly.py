import argparse
import html
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from prz_scanner.config import weekly_config
from prz_scanner.data_fetch import fetch_all, fetch_realtime_prices
from prz_scanner.scanner import scan_watchlist, filter_results, QUALITY_PATTERNS, QUALITY_MIN_CONF
from prz_scanner.chart_render import render_chart
from prz_scanner.summary import build_summary, write_summary


def parse_args(argv=None):
    p = argparse.ArgumentParser(
        description="PRZ Harmonic Buy Zone Scanner - Weekly (1wk) Timeframe",
    )
    p.add_argument("--tickers", nargs="+")
    p.add_argument("--depths", nargs="+", type=int)
    p.add_argument("--period", default=None)
    p.add_argument("--proximity", type=float)
    p.add_argument("--max-dist", type=float)
    p.add_argument("--prz-maxw", type=float)
    p.add_argument("--tol-strict", type=float)
    p.add_argument("--tol-loose", type=float)
    p.add_argument("--strict-bc", action=argparse.BooleanOptionalAction,
                   default=True,
                   help="BC-projection gate sesuai buku (default ON; --no-strict-bc utk melonggarkan)")
    p.add_argument("--only", nargs="+", metavar="POLA",
                   help="hanya pola tertentu (mis: --only Crab Bat)")
    p.add_argument("--min-conf", type=int, default=0,
                   help="minimal jumlah elemen confluence PRZ (default 0)")
    p.add_argument("--quality", action="store_true",
                   help="preset subset teruji backtest: --only Crab Bat --min-conf 2")
    p.add_argument("--no-charts", action="store_true")
    p.add_argument("--output", default=None)
    p.add_argument("--telegram", action="store_true",
                   help="kirim hasil ke grup Telegram")
    p.add_argument("--images-only", action="store_true",
                   help="saat --telegram: kirim PNG saja, skip pesan teks summary")
    p.add_argument("--tg-token", default=None)
    p.add_argument("--tg-chat", default=None)
    # WAJIB ada: scheduler.py selalu meneruskan --cleanup ke semua runner.
    # Body main() membaca args.cleanup — tanpa definisi ini, argparse exit 2
    # (flag tak dikenal) dan weekly scan tidak pernah jalan dari scheduler.
    p.add_argument("--cleanup", action="store_true",
                   help="hapus PNG & skip simpan summary ke disk setelah kirim ke Telegram")
    return p.parse_args(argv)


def build_config(args):
    cfg = weekly_config()
    if args.tickers:
        cfg.watchlist = [t.strip().upper() for t in args.tickers]
    if args.depths:
        cfg.depths = args.depths
    if args.period is not None:
        cfg.period_weekly = args.period
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
    print("  PRZ Buy Zone Scanner  -  Weekly (1wk) Timeframe")
    print("=" * 60)
    print(f"  Watchlist  : {len(cfg.watchlist)} ticker(s)")
    print(f"  Depths     : {cfg.depths}")
    print(f"  Period     : {cfg.period_weekly}")
    print(f"  Proximity  : {cfg.proximity_pct}%")
    print(f"  Max dist   : {cfg.max_dist}%")
    print(f"  Output dir : {cfg.output_dir}")
    tg_mode = "images-only" if args.images_only else ("ON" if args.telegram else "off")
    print(f"  Telegram   : {tg_mode}")
    print("-" * 60)

    print(f"\n[1/4] Fetching {len(cfg.watchlist)} tickers (Weekly 1wk, {cfg.period_weekly})...")
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

    print("\n[2/4] Scanning harmonic PRZ buy zones (Weekly)...")
    results = scan_watchlist(data, cfg, realtime_prices=realtime_prices)
    print(f"      {len(results)} saham lolos proximity filter")

    # [DEVIATION] filter kualitas sinyal (subset teruji backtest)
    only = args.only
    min_conf = args.min_conf
    if args.quality:
        only = only or list(QUALITY_PATTERNS)
        min_conf = max(min_conf, QUALITY_MIN_CONF)
    if only or min_conf:
        before = len(results)
        results = filter_results(results, only=only, min_conf=min_conf)
        print(f"      filter kualitas ({'+'.join(only) if only else 'semua'}, "
              f"conf>={min_conf}): {before} -> {len(results)} saham")

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

    tg_failed_total = False
    if args.telegram:
        print("\n[TG] Mengirim hasil ke Telegram...")
        try:
            from prz_scanner.telegram_notify import TelegramSender
            import time as _time
            tg = TelegramSender(token=args.tg_token or None, chat_id=args.tg_chat or None)

            if not args.images_only:
                tg.send_summary(df, cfg.timeframe, total_scanned=len(data))
                _time.sleep(0.5)
            else:
                if not df.empty:
                    tg.send_message(
                        f"<b>PRZ Weekly Scan</b> - {len(results)} saham mendekati PRZ BUY zone"
                    )
                    _time.sleep(0.5)

            if df.empty:
                tg.send_message("<b>PRZ Weekly Scan</b>\nTidak ada saham yang mendekati PRZ saat ini.")

            sent = 0
            attempted = 0
            for r in results:
                path = chart_paths.get(r.ticker)
                if not path or not os.path.exists(path):
                    print(f"  [TG] Chart {r.ticker} tidak ada, skip.")
                    continue
                attempted += 1
                bb = r.best_buy
                last_close = r.realtime_close if r.realtime_close is not None else float(r.df["Close"].iloc[-1])
                valid_str = "\u2705 valid" if bb.valid else "\u26a0\ufe0f invalid"
                inside = bb.prz_lo <= last_close <= bb.prz_hi
                status_disp = "\U0001f4cd INSIDE PRZ" if inside else f"approaching {bb.dist_pct:.1f}% \U0001f53d"
                # [anti-repaint] lihat run_daily.py — peringatan C belum
                # terkonfirmasi (pola bisa repaint, di luar populasi backtest)
                unconf_line = ""
                if not bb.c_confirmed:
                    unconf_line = ("\n⏳ <i>C belum terkonfirmasi — "
                                   "bisa repaint, di luar populasi backtest</i>")
                caption = (
                    f"<b>{html.escape(r.ticker)}</b> | Weekly | {html.escape(bb.pattern)} | {valid_str}\n"
                    f"PRZ: <code>{bb.prz_lo:.0f} - {bb.prz_hi:.0f}</code>\n"
                    f"Close: <code>{last_close:.0f}</code> | {status_disp}\n"
                    f"Score: <code>{bb.score:.0f}</code> | TP1: <code>{bb.tp1:.0f}</code> | Stop: <code>{bb.stop:.0f}</code>"
                    f"{unconf_line}"
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
            tg_failed_total = attempted > 0 and sent == 0
        except Exception as e:
            print(f"  [TG ERROR] {e}")
            tg_failed_total = True

    if tg_failed_total:
        # Kegagalan kirim TOTAL tidak boleh diam-diam exit 0 — scheduler
        # mencatat "FAIL (exit 3)" di journalctl sehingga terlihat.
        print("\n[EXIT] Telegram gagal total -> exit 3")
        return 3
    print("\nDone.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
