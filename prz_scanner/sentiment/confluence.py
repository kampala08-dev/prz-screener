"""Gabungkan sinyal harmonic (primer) dengan sentimen (konteks/filter).

PRINSIP: harmonic adalah pemicu utama; sentimen TIDAK PERNAH memicu BUY
sendiri. Ia hanya menaikkan prioritas (CONFIRM) atau memberi rambu
(CONFLICT). Disclosure material IDX (fakta) lebih berbobot dari berita opini.
"""

from typing import Optional, Tuple

from .models import ConfluenceTag, SentimentResult

# Ambang (bisa dilonggarkan lewat argumen).
POS_THR = 0.30      # score di atas ini = positif
NEG_THR = -0.30     # score di bawah ini = negatif
MIN_CONF = 0.35     # di bawah ini -> anggap NEUTRAL (model tak yakin)

_ICON = {ConfluenceTag.CONFIRM: "✅", ConfluenceTag.NEUTRAL: "",
         ConfluenceTag.CONFLICT: "⚠️"}


def classify(sentiment: Optional[SentimentResult], is_bull: bool = True,
             pos_thr: float = POS_THR, neg_thr: float = NEG_THR,
             min_conf: float = MIN_CONF) -> Tuple[ConfluenceTag, str]:
    """Kembalikan (tag, reason). Aman terhadap sentiment None/kosong/gagal."""
    if sentiment is None or not sentiment.ok or not sentiment.headlines_used:
        return ConfluenceTag.NEUTRAL, "sepi berita"
    if sentiment.confidence < min_conf and not sentiment.has_material_event:
        return ConfluenceTag.NEUTRAL, f"low-conf ({sentiment.label})"

    s = sentiment.score
    material_neg = sentiment.has_material_event and s < 0
    material_pos = sentiment.has_material_event and s > 0

    if is_bull:
        # Untuk BUY: berita/disclosure negatif = konflik (jangan beli ke berita jelek)
        if s <= neg_thr or material_neg:
            return ConfluenceTag.CONFLICT, sentiment.reason or "berita negatif"
        if s >= pos_thr or material_pos:
            return ConfluenceTag.CONFIRM, sentiment.reason or "berita positif"
        return ConfluenceTag.NEUTRAL, sentiment.reason or sentiment.label
    else:
        # Mirror untuk sinyal SELL (jarang dipakai di screener BUY).
        if s >= pos_thr or material_pos:
            return ConfluenceTag.CONFLICT, sentiment.reason or "berita positif"
        if s <= neg_thr or material_neg:
            return ConfluenceTag.CONFIRM, sentiment.reason or "berita negatif"
        return ConfluenceTag.NEUTRAL, sentiment.reason or sentiment.label


def icon(tag: ConfluenceTag) -> str:
    return _ICON.get(tag, "")


def priority(tag: ConfluenceTag) -> int:
    """Untuk pengurutan: CONFIRM di atas, CONFLICT di bawah."""
    return {ConfluenceTag.CONFIRM: 0, ConfluenceTag.NEUTRAL: 1,
            ConfluenceTag.CONFLICT: 2}.get(tag, 1)
