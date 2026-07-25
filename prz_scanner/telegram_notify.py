"""Telegram notification module for PRZ Scanner.

Sends scan results (summary text + chart PNGs) to a Telegram group/chat.

Credentials are loaded from .env (TELEGRAM_BOT_TOKEN, TELEGRAM_CHAT_ID),
or can be passed directly to TelegramSender().
"""

import html
import os
import time
from typing import Optional, List
import requests
import pandas as pd

try:
    from dotenv import load_dotenv
    # override=True: .env adalah sumber kebenaran kredensial proyek ini
    # (lihat README). Tanpa ini, env var shell yang sudah ter-set —
    # mis. dari proyek lain — diam-diam MENIMPA .env dan pesan bisa
    # terkirim ke bot/grup yang salah.
    load_dotenv(override=True)
except ImportError:
    pass

from .scanner import StockResult


def _e(val) -> str:
    """HTML-escape a value so it's safe inside Telegram HTML parse_mode.

    Escapes &, <, > — wajib untuk semua nilai dinamis (ticker, angka, dll.)
    agar tidak menyebabkan 400 Bad Request dari Telegram API.
    """
    return html.escape(str(val))


class TelegramSender:
    """Send messages and photos to a Telegram chat via Bot API."""

    BASE_URL = "https://api.telegram.org/bot{token}/{method}"

    def __init__(self, token: Optional[str] = None, chat_id: Optional[str] = None):
        self.token = token or os.environ.get("TELEGRAM_BOT_TOKEN", "")
        self.chat_id = chat_id or os.environ.get("TELEGRAM_CHAT_ID", "")
        if not self.token:
            raise ValueError(
                "Telegram bot token tidak ditemukan. "
                "Set TELEGRAM_BOT_TOKEN di .env atau pass token= ke TelegramSender()."
            )
        if not self.chat_id:
            raise ValueError(
                "Telegram chat_id tidak ditemukan. "
                "Set TELEGRAM_CHAT_ID di .env atau pass chat_id= ke TelegramSender()."
            )

    def _url(self, method: str) -> str:
        return self.BASE_URL.format(token=self.token, method=method)

    def _redact(self, text: str) -> str:
        """Hapus bot token dari string sebelum menyentuh log/stdout.

        URL Bot API memuat token (api.telegram.org/bot<TOKEN>/...), dan pesan
        exception `requests` (HTTPError/ConnectionError/Timeout) menyertakan
        URL lengkap — tanpa redaksi, token asli bocor ke logs/scheduler.log
        dan journalctl di VPS setiap kali Telegram error.
        """
        return text.replace(self.token, "***TOKEN***") if self.token else text

    # Maks pengulangan saat Telegram flood control (HTTP 429).
    _MAX_429_RETRY = 2
    # Batas atas menghormati retry_after agar satu 429 ekstrem tidak
    # memblokir scan terlalu lama.
    _MAX_429_WAIT_S = 90

    def _post(self, method: str, data: dict = None, files=None,
              timeout: int = 30) -> dict:
        """POST to Telegram API.

        - HTTP 429: patuhi parameters.retry_after lalu ulangi (maks
          _MAX_429_RETRY kali) — tanpa ini, sinyal ke-20+ saat hasil scan
          banyak akan drop diam-diam.
        - Semua error dilempar sebagai RuntimeError dengan pesan yang sudah
          di-redact (bebas token), aman untuk di-print pemanggil.
        """
        for attempt in range(self._MAX_429_RETRY + 1):
            try:
                r = requests.post(self._url(method), data=data, files=files,
                                  timeout=timeout)
                if r.status_code == 429 and attempt < self._MAX_429_RETRY:
                    try:
                        wait_s = int(r.json()["parameters"]["retry_after"])
                    except (ValueError, KeyError, TypeError):
                        wait_s = 5
                    wait_s = min(max(wait_s, 1), self._MAX_429_WAIT_S)
                    print(f"  [TG] 429 flood control ({method}), "
                          f"tunggu {wait_s}s lalu ulangi...")
                    time.sleep(wait_s + 1)
                    continue
                r.raise_for_status()
            except requests.RequestException as e:
                # `from None`: putus chain traceback agar URL ber-token pada
                # exception asli tidak ikut tercetak di mana pun.
                raise RuntimeError(
                    f"Telegram {method}: {self._redact(str(e))}") from None
            try:
                resp = r.json()
            except ValueError:
                raise RuntimeError(
                    f"Telegram {method}: respons bukan JSON "
                    f"(HTTP {r.status_code})") from None
            if not resp.get("ok"):
                raise RuntimeError(f"Telegram API error: {resp}")
            return resp

    def send_message(self, text: str, parse_mode: str = "HTML") -> bool:
        """Send a text message. Falls back to plain text if HTML fails (400)."""
        # Attempt 1: with parse_mode (HTML)
        try:
            self._post("sendMessage", data={
                "chat_id": self.chat_id,
                "text": text,
                "parse_mode": parse_mode,
            })
            return True
        except Exception as e:
            err_str = str(e)
            # 400 = parse error in HTML → retry without parse_mode
            if "400" in err_str and parse_mode:
                print(f"  [TG] HTML parse error, retry sebagai plain text...")
                try:
                    # Strip HTML tags for plain text fallback
                    import re
                    plain = re.sub(r"<[^>]+>", "", text)
                    self._post("sendMessage", data={
                        "chat_id": self.chat_id,
                        "text": plain,
                    })
                    return True
                except Exception as e2:
                    print(f"[WARN] Telegram sendMessage gagal (plain): {e2}")
                    return False
            print(f"[WARN] Telegram sendMessage gagal: {e}")
            return False

    def send_photo(self, photo_path: str, caption: str = "",
                   parse_mode: str = "HTML") -> bool:
        """Send a PNG/JPG photo with caption. Falls back to no parse_mode on error."""
        filename = os.path.basename(photo_path)
        # Baca bytes sekali (bukan file handle): retry 429 di _post mengirim
        # ulang body — handle yang sudah terbaca ada di EOF dan attempt kedua
        # akan mengirim foto kosong.
        with open(photo_path, "rb") as f:
            photo_bytes = f.read()
        try:
            self._post("sendPhoto", data={
                "chat_id": self.chat_id,
                "caption": caption[:1024],
                "parse_mode": parse_mode,
            }, files={"photo": (filename, photo_bytes)})
            return True
        except Exception as e:
            err_str = str(e)
            if "400" in err_str and parse_mode:
                # Retry without HTML formatting
                try:
                    import re
                    plain_cap = re.sub(r"<[^>]+>", "", caption)[:1024]
                    self._post("sendPhoto", data={
                        "chat_id": self.chat_id,
                        "caption": plain_cap,
                    }, files={"photo": (filename, photo_bytes)})
                    return True
                except Exception as e2:
                    print(f"[WARN] sendPhoto plain gagal: {e2}")
            print(f"[WARN] Telegram sendPhoto gagal "
                  f"({filename}): {e}")
            return False

    # ------------------------------------------------------------------
    # High-level helpers
    # ------------------------------------------------------------------

    def send_summary(self, df: pd.DataFrame, timeframe: str,
                     total_scanned: int = 0) -> bool:
        """Send scan summary as formatted HTML message."""
        tf_label = {"1d": "Daily", "1wk": "Weekly", "4h": "H4"}.get(
            timeframe, timeframe.upper())

        if df.empty:
            msg = (
                f"<b>PRZ Scanner - {_e(tf_label)}</b>\n"
                f"Tidak ada saham yang mendekati PRZ BUY zone saat ini."
            )
            return self.send_message(msg)

        lines = [
            f"<b>PRZ Scanner - {_e(tf_label)}</b>",
            f"<i>{len(df)} saham mendekati PRZ BUY zone"
            + (f" (dari {_e(total_scanned)} discan)" if total_scanned else "")
            + "</i>",
            "",
        ]

        for _, row in df.iterrows():
            inside = str(row.get("Zone", "")) == "INSIDE"
            valid  = str(row.get("Valid", "")) == "valid"
            dist   = float(row.get("Dist%", 0))

            status_icon = "\U0001f7e2" if inside else "\U0001f7e1"   # 🟢 🟡
            valid_icon  = "\u2705" if valid else "\u26a0\ufe0f"       # ✅ ⚠️
            arrow       = "\U0001f4cd" if inside else "\U0001f53d"    # 📍 🔽

            try:
                prz_lo  = float(row.get("PRZ_low", 0))
                prz_hi  = float(row.get("PRZ_high", 0))
                close   = float(row.get("Close", 0))
                score   = float(row.get("Score", 0))
                tp1     = float(row.get("TP1", 0))
                stop    = float(row.get("Stop", 0))
            except (ValueError, TypeError):
                continue

            lines.append(
                f"{status_icon} <b>{_e(row['Ticker'])}</b> - "
                f"{_e(row['Pattern'])} ({_e(row.get('Tol', ''))}) {valid_icon}\n"
                f"  PRZ: <code>{prz_lo:.0f}-{prz_hi:.0f}</code>  "
                f"Close: <code>{close:.0f}</code>  "
                f"{arrow} <code>{dist:.1f}%</code>\n"
                f"  Score: <code>{score:.0f}</code>  "
                f"TP1: <code>{tp1:.0f}</code>  "
                f"Stop: <code>{stop:.0f}</code>"
            )

        msg = "\n".join(lines)
        if len(msg) > 4000:
            msg = msg[:3950] + "\n\n<i>...truncated</i>"

        return self.send_message(msg)
