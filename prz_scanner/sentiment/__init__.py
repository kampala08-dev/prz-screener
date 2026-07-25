"""Lapisan sentimen (opsional) untuk PRZ Screener.

Terisolasi penuh dari mesin harmonic yang sudah ter-backtest. Aktif hanya
bila `--sentiment` dipakai. Kegagalan apa pun di layer ini (RSS down, LLM
error, WAF IDX) HARUS di-skip tanpa merusak scan harmonic — semua
pemanggilan dibungkus try/except di titik integrasi.

Alur: berita/disclosure per-saham -> skor MiniMax-M3 (JSON) -> confluence
tag (CONFIRM/NEUTRAL/CONFLICT) digabung dengan sinyal harmonic.
"""

from .models import SentimentResult, ConfluenceTag
from .confluence import classify

__all__ = ["SentimentResult", "ConfluenceTag", "classify"]
