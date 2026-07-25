"""Skor sentimen berita saham memakai MiniMax-M3 (OpenAI-compatible).

Kredensial & model dari environment (.env), JANGAN hardcode:
  MINIMAX_API_KEY   (wajib)
  MINIMAX_MODEL     (default "MiniMax-M3" — model terpintar)
  MINIMAX_BASE_URL  (default "https://api.minimax.io/v1";
                     untuk OpenRouter: "https://openrouter.ai/api/v1"
                     + MINIMAX_MODEL="minimax/minimax-m3")

Output dipaksa berupa JSON via prompt; parsing robust (json.loads + fallback
ekstraksi kurung). Semua kegagalan -> SentimentResult.empty(error=...) yang
netral & aman, tidak pernah melempar ke pemanggil.
"""

import json
import os
import re
from typing import List, Optional

import requests

from .models import Headline, SentimentResult

_DEFAULT_MODEL = "MiniMax-M3"
_DEFAULT_BASE = "https://api.minimax.io/v1"
_TIMEOUT = 40

_SYSTEM = (
    "Anda analis sentimen pasar saham Indonesia (IDX). Nilai sentimen "
    "jangka-pendek sebuah emiten dari judul berita & pengumuman resmi. "
    "Aturan: (1) Bedakan FAKTA MATERIAL dari pengumuman IDX (rights issue, "
    "laba turun/naik signifikan, dividen, buyback, akuisisi, going concern, "
    "suspensi) versus OPINI/berita media biasa — fakta material lebih berbobot. "
    "(2) Fokus dampak ke harga saham, bukan sentimen umum. (3) Jujur soal "
    "ketidakpastian: judul minim konteks -> confidence rendah. "
    "Balas HANYA satu objek JSON valid, tanpa teks lain, dengan skema persis:\n"
    '{"score": <float -1..1>, "label": "positive|neutral|negative", '
    '"confidence": <float 0..1>, "has_material_event": <true|false>, '
    '"reason": "<=140 char Bahasa Indonesia"}'
)


def _extract_json(text: str) -> Optional[dict]:
    text = (text or "").strip()
    # MiniMax-M3 & model reasoning lain membungkus jawaban dengan blok
    # <think>...</think> (bisa berisi kurung {} yang mengacaukan regex) —
    # buang dulu sebelum ekstraksi JSON.
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL).strip()
    # buang pagar markdown ```json ... ``` bila ada
    text = re.sub(r"```(?:json)?", "", text).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    m = re.search(r"\{.*\}", text, re.DOTALL)
    if m:
        try:
            return json.loads(m.group(0))
        except json.JSONDecodeError:
            return None
    return None


def _clamp(v, lo, hi, default=0.0):
    try:
        return max(lo, min(hi, float(v)))
    except (TypeError, ValueError):
        return default


class MiniMaxScorer:
    """Skorer sentimen berbasis MiniMax (atau endpoint OpenAI-compatible)."""

    def __init__(self, api_key: Optional[str] = None, model: Optional[str] = None,
                 base_url: Optional[str] = None):
        self.api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self.model = model or os.environ.get("MINIMAX_MODEL", _DEFAULT_MODEL)
        self.base_url = (base_url or os.environ.get("MINIMAX_BASE_URL",
                                                    _DEFAULT_BASE)).rstrip("/")

    @property
    def configured(self) -> bool:
        return bool(self.api_key)

    def _build_user_msg(self, ticker: str, headlines: List[Headline]) -> str:
        lines = [f"Emiten IDX: {ticker}", "", "Berita & pengumuman terbaru:"]
        for h in headlines:
            tag = "[DISCLOSURE IDX] " if h.is_disclosure else ""
            date = f" ({h.published[:10]})" if h.published else ""
            lines.append(f"- {tag}{h.title}{date} — {h.source}")
        lines.append("")
        lines.append("Berikan skor sentimen JSON sesuai skema.")
        return "\n".join(lines)

    def score(self, ticker: str, headlines: List[Headline]) -> SentimentResult:
        """Skor satu saham. Tanpa berita -> netral (tanpa panggil API)."""
        if not headlines:
            return SentimentResult.empty(ticker)
        if not self.configured:
            return SentimentResult.empty(
                ticker, error="MINIMAX_API_KEY belum diset")

        payload = {
            "model": self.model,
            "messages": [
                {"role": "system", "content": _SYSTEM},
                {"role": "user",
                 "content": self._build_user_msg(ticker, headlines)},
            ],
            "temperature": 0.2,
            # M3 model reasoning: butuh ruang utk blok <think> + JSON akhir
            "max_tokens": 2500,
        }
        headers = {"Authorization": f"Bearer {self.api_key}",
                   "Content-Type": "application/json"}
        try:
            r = requests.post(f"{self.base_url}/chat/completions",
                              json=payload, headers=headers, timeout=_TIMEOUT)
            r.raise_for_status()
            data = r.json()
            content = data["choices"][0]["message"]["content"]
        except (requests.RequestException, KeyError, IndexError, ValueError) as e:
            return SentimentResult.empty(ticker, error=f"LLM error: {e}")

        parsed = _extract_json(content)
        if not parsed:
            return SentimentResult.empty(ticker, error="respons LLM bukan JSON")

        score = _clamp(parsed.get("score", 0.0), -1.0, 1.0)
        label = str(parsed.get("label", "neutral")).lower()
        if label not in ("positive", "neutral", "negative"):
            label = ("positive" if score > 0.2 else
                     "negative" if score < -0.2 else "neutral")
        return SentimentResult(
            ticker=ticker,
            score=score,
            label=label,
            confidence=_clamp(parsed.get("confidence", 0.0), 0.0, 1.0),
            reason=str(parsed.get("reason", ""))[:200],
            has_material_event=bool(parsed.get("has_material_event", False)),
            headlines_used=list(headlines),
            model=self.model,
        )
