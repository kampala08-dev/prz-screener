"""Ambil berita & disclosure per-saham IDX untuk di-skor.

Dua sumber (keduanya gratis, tanpa API key, terverifikasi live saat riset):
  - Google News RSS per-emiten -> cakupan berita luas (judul bhs Indonesia)
  - IDX Keterbukaan Informasi (GetAnnouncement) -> disclosure resmi/material

DESAIN AMAN: setiap fetcher dibungkus try/except + timeout dan mengembalikan
list kosong bila gagal (RSS down, WAF IDX, dll) — TIDAK pernah melempar ke
pemanggil, sehingga kegagalan berita tak merusak scan harmonic.
"""

import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from typing import List
from urllib.parse import quote

import requests

from .models import Headline

_UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
       "(KHTML, like Gecko) Chrome/125.0 Safari/537.36")
_TIMEOUT = 12


def _recent(published_iso: str, days: int) -> bool:
    """True bila tanggal (ISO) dalam `days` terakhir; True bila tak diketahui."""
    if not published_iso:
        return True
    try:
        dt = datetime.fromisoformat(published_iso)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt >= datetime.now(timezone.utc) - timedelta(days=days)
    except (ValueError, TypeError):
        return True


def fetch_google_news(ticker: str, days: int = 7, limit: int = 10) -> List[Headline]:
    """Judul berita Google News untuk `ticker` (kode 4-huruf IDX)."""
    q = quote(f'"{ticker}" saham')
    url = (f"https://news.google.com/rss/search?q={q}"
           f"&hl=id&gl=ID&ceid=ID:id")
    try:
        r = requests.get(url, headers={"User-Agent": _UA}, timeout=_TIMEOUT)
        r.raise_for_status()
        root = ET.fromstring(r.content)
    except (requests.RequestException, ET.ParseError):
        return []

    out: List[Headline] = []
    for item in root.iter("item"):
        title = (item.findtext("title") or "").strip()
        if not title:
            continue
        pub_raw = item.findtext("pubDate") or ""
        pub_iso = ""
        if pub_raw:
            try:
                pub_iso = parsedate_to_datetime(pub_raw).astimezone(
                    timezone.utc).isoformat()
            except (ValueError, TypeError):
                pub_iso = ""
        src_el = item.find("source")
        source = (src_el.text.strip() if src_el is not None and src_el.text
                  else "Google News")
        if not _recent(pub_iso, days):
            continue
        out.append(Headline(title=title, source=source, published=pub_iso,
                            is_disclosure=False))
        if len(out) >= limit:
            break
    return out


def fetch_idx_announcements(ticker: str, days: int = 30,
                            limit: int = 8) -> List[Headline]:
    """Disclosure resmi IDX (fakta material). Best-effort: endpoint internal,
    bisa kena WAF/berubah -> gagal = list kosong (di-skip)."""
    url = ("https://www.idx.co.id/primary/ListedCompany/GetAnnouncement"
           f"?kodeEmiten={ticker}&indexFrom=1&pageSize={limit}"
           "&dateFrom=&dateTo=&lang=id&keyword=")
    headers = {
        "User-Agent": _UA,
        "Referer": "https://www.idx.co.id/id/perusahaan-tercatat/keterbukaan-informasi/",
        "Accept": "application/json, text/plain, */*",
    }
    try:
        r = requests.get(url, headers=headers, timeout=_TIMEOUT)
        r.raise_for_status()
        data = r.json()
    except (requests.RequestException, ValueError):
        return []

    # Skema JSON IDX bisa berubah; cari list secara defensif.
    rows = None
    if isinstance(data, dict):
        for key in ("Replies", "Items", "items", "data", "Results", "results"):
            if isinstance(data.get(key), list):
                rows = data[key]
                break
    elif isinstance(data, list):
        rows = data
    if not rows:
        return []

    out: List[Headline] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        # Struktur IDX: tiap Reply membungkus {"pengumuman": {...}}.
        rec = row.get("pengumuman") if isinstance(row.get("pengumuman"), dict) else row
        title = ""
        for k in ("JudulPengumuman", "Title", "title", "Judul", "Perihal"):
            if rec.get(k):
                title = str(rec[k]).strip()
                break
        if not title:
            continue
        pub_iso = ""
        for k in ("TglPengumuman", "PublishDate", "Date", "date", "TanggalPengumuman"):
            if rec.get(k):
                raw = str(rec[k])
                try:
                    pub_iso = datetime.fromisoformat(
                        raw.replace("Z", "+00:00")[:25]).isoformat()
                except (ValueError, TypeError):
                    pub_iso = ""
                break
        if not _recent(pub_iso, days):
            continue
        out.append(Headline(title=title, source="IDX Disclosure",
                            published=pub_iso, is_disclosure=True))
        if len(out) >= limit:
            break
    return out


def fetch_all_news(ticker: str, pause: float = 0.0) -> List[Headline]:
    """Gabungan disclosure IDX (didahulukan, bobot material) + berita Google.
    Selalu mengembalikan list (mungkin kosong); tak pernah melempar."""
    heads: List[Headline] = []
    try:
        heads.extend(fetch_idx_announcements(ticker))
    except Exception:
        pass
    if pause:
        time.sleep(pause)
    try:
        heads.extend(fetch_google_news(ticker))
    except Exception:
        pass
    return heads
