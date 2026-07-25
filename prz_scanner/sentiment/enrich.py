"""Orkestrasi enrichment sentimen untuk hasil scan yang sudah lolos.

Dipanggil dari runner SETELAH filter harmonic (hanya ~5-25 saham, bukan
seluruh universe). Setiap saham: fetch berita -> skor MiniMax -> confluence
tag. Kegagalan per-saham di-skip (netral), tak menghentikan yang lain.
"""

import time
from dataclasses import dataclass
from typing import Dict, List, Optional

from .confluence import classify, icon, priority
from .models import ConfluenceTag, SentimentResult
from .news_fetch import fetch_all_news
from .scorer import MiniMaxScorer


@dataclass(frozen=True)
class Enrichment:
    sentiment: SentimentResult
    tag: ConfluenceTag
    reason: str

    @property
    def icon(self) -> str:
        return icon(self.tag)

    @property
    def priority(self) -> int:
        return priority(self.tag)


def enrich_results(results: List, scorer: Optional[MiniMaxScorer] = None,
                   pause: float = 0.4, log=print) -> Dict[str, Enrichment]:
    """{ticker -> Enrichment} untuk tiap StockResult yang punya best_buy.

    `results` = List[StockResult] (dari scanner). Diakses lewat .ticker dan
    .best_buy.bull agar tak meng-import scanner (hindari coupling siklik).
    """
    scorer = scorer or MiniMaxScorer()
    out: Dict[str, Enrichment] = {}
    if not scorer.configured:
        log("      [sentimen] MINIMAX_API_KEY belum diset — layer di-skip.")
        return out

    for r in results:
        ticker = getattr(r, "ticker", None)
        best = getattr(r, "best_buy", None)
        if not ticker or best is None:
            continue
        try:
            heads = fetch_all_news(ticker, pause=0.0)
            sent = scorer.score(ticker, heads)
            tag, reason = classify(sent, is_bull=best.bull)
            out[ticker] = Enrichment(sentiment=sent, tag=tag, reason=reason)
            mark = out[ticker].icon or "•"
            log(f"      [sentimen] {ticker}: {tag.value} {mark} "
                f"(score {sent.score:+.2f}, {len(heads)} berita)")
        except Exception as e:                      # jangan pernah gagalkan scan
            log(f"      [sentimen] {ticker}: SKIP ({e})")
        time.sleep(pause)
    return out
