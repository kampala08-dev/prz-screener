"""Tipe data untuk lapisan sentimen."""

from dataclasses import dataclass, field
from enum import Enum
from typing import List, Optional


class ConfluenceTag(str, Enum):
    """Hasil penggabungan sinyal harmonic + sentimen."""
    CONFIRM = "CONFIRM"    # harmonic BUY + sentimen positif -> prioritas naik
    NEUTRAL = "NEUTRAL"    # sepi berita / low-confidence -> diteruskan apa adanya
    CONFLICT = "CONFLICT"  # harmonic BUY + berita/disclosure negatif -> hati-hati


@dataclass(frozen=True)
class Headline:
    """Satu item berita/disclosure."""
    title: str
    source: str
    published: str        # ISO date string ("" bila tak diketahui)
    is_disclosure: bool = False   # True = keterbukaan informasi IDX (fakta material)


@dataclass(frozen=True)
class SentimentResult:
    """Skor sentimen satu saham dari MiniMax.

    score: -1.0 (sangat negatif) .. +1.0 (sangat positif); 0 = netral.
    confidence: 0.0 .. 1.0 keyakinan model.
    has_material_event: ada katalis material (rights issue, laba anjlok,
        going concern, dividen, buyback, akuisisi) — biasanya dari disclosure IDX.
    """
    ticker: str
    score: float
    label: str                 # "positive" | "neutral" | "negative"
    confidence: float
    reason: str
    has_material_event: bool = False
    headlines_used: List[Headline] = field(default_factory=list)
    model: str = ""
    error: Optional[str] = None   # terisi bila skoring gagal (result fallback netral)

    @property
    def ok(self) -> bool:
        return self.error is None

    @classmethod
    def empty(cls, ticker: str, error: Optional[str] = None) -> "SentimentResult":
        """Hasil netral aman saat tidak ada berita atau terjadi kegagalan."""
        return cls(ticker=ticker, score=0.0, label="neutral", confidence=0.0,
                   reason="tidak ada berita relevan" if error is None else error,
                   has_material_event=False, error=error)
