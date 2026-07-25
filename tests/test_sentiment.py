"""Unit test lapisan sentimen — semua di-mock, TIDAK memanggil API/HTTP asli.

Cakupan:
  - confluence.classify: BUY+neg=CONFLICT, BUY+pos=CONFIRM, no-news=NEUTRAL,
    low-conf=NEUTRAL, disclosure material negatif=CONFLICT
  - scorer: parsing JSON MiniMax (bersih & kotor), no-headlines skip API,
    error API -> netral fallback
  - news_fetch: parsing Google News RSS (mock XML), recency filter
  - enrich_results: skip aman saat scorer tak terkonfigurasi
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prz_scanner.sentiment import scorer as scorer_mod
from prz_scanner.sentiment import news_fetch as news_mod
from prz_scanner.sentiment.confluence import classify
from prz_scanner.sentiment.enrich import enrich_results
from prz_scanner.sentiment.models import (ConfluenceTag, Headline,
                                          SentimentResult)
from prz_scanner.sentiment.scorer import MiniMaxScorer


# ---------------------------------------------------------------------------
class FakeResp:
    def __init__(self, json_data=None, content=b"", status_ok=True):
        self._json = json_data
        self.content = content
        self._ok = status_ok

    def raise_for_status(self):
        if not self._ok:
            raise news_mod.requests.RequestException("HTTP error")

    def json(self):
        if self._json is None:
            raise ValueError("no json")
        return self._json


def _sent(score, conf=0.8, material=False, label="neutral"):
    return SentimentResult(ticker="X", score=score, label=label, confidence=conf,
                           reason="r", has_material_event=material,
                           headlines_used=[Headline("h", "s", "")])


# ---------------------------------------------------------------------------
# confluence
# ---------------------------------------------------------------------------
def test_confluence_buy_positive_is_confirm():
    tag, _ = classify(_sent(0.6), is_bull=True)
    assert tag == ConfluenceTag.CONFIRM


def test_confluence_buy_negative_is_conflict():
    tag, _ = classify(_sent(-0.6), is_bull=True)
    assert tag == ConfluenceTag.CONFLICT


def test_confluence_buy_mild_is_neutral():
    tag, _ = classify(_sent(0.1), is_bull=True)
    assert tag == ConfluenceTag.NEUTRAL


def test_confluence_no_news_is_neutral():
    tag, reason = classify(SentimentResult.empty("X"), is_bull=True)
    assert tag == ConfluenceTag.NEUTRAL and "sepi" in reason


def test_confluence_low_confidence_is_neutral():
    tag, _ = classify(_sent(0.6, conf=0.1), is_bull=True)
    assert tag == ConfluenceTag.NEUTRAL


def test_confluence_material_negative_overrides_mild_score():
    # score cuma -0.1 (tidak lewat ambang) TAPI ada disclosure material negatif
    tag, _ = classify(_sent(-0.1, material=True), is_bull=True)
    assert tag == ConfluenceTag.CONFLICT


def test_confluence_none_safe():
    tag, _ = classify(None, is_bull=True)
    assert tag == ConfluenceTag.NEUTRAL


# ---------------------------------------------------------------------------
# scorer
# ---------------------------------------------------------------------------
def test_scorer_parses_clean_json(monkeypatch):
    body = {"choices": [{"message": {"content":
            '{"score": -0.7, "label": "negative", "confidence": 0.9, '
            '"has_material_event": true, "reason": "rights issue"}'}}]}
    monkeypatch.setattr(scorer_mod.requests, "post",
                        lambda *a, **k: FakeResp(json_data=body))
    s = MiniMaxScorer(api_key="test").score("BBRI", [Headline("x", "y", "")])
    assert s.ok and s.score == -0.7 and s.label == "negative"
    assert s.has_material_event is True


def test_scorer_extracts_json_from_noisy_text(monkeypatch):
    body = {"choices": [{"message": {"content":
            'Berikut analisisnya:\n{"score": 0.5, "label": "positive", '
            '"confidence": 0.7, "has_material_event": false, "reason": "buyback"} selesai'}}]}
    monkeypatch.setattr(scorer_mod.requests, "post",
                        lambda *a, **k: FakeResp(json_data=body))
    s = MiniMaxScorer(api_key="test").score("X", [Headline("x", "y", "")])
    assert s.ok and s.score == 0.5 and s.label == "positive"


def test_scorer_strips_reasoning_think_block(monkeypatch):
    # MiniMax-M3 (reasoning) membungkus dgn <think>...</think> sebelum JSON.
    body = {"choices": [{"message": {"content":
            "<think>Berita positif: buyback & laba naik.</think>\n"
            '{"score": 0.8, "label": "positive", "confidence": 0.9, '
            '"has_material_event": true, "reason": "buyback + laba"}'}}]}
    monkeypatch.setattr(scorer_mod.requests, "post",
                        lambda *a, **k: FakeResp(json_data=body))
    s = MiniMaxScorer(api_key="test").score("X", [Headline("x", "y", "")])
    assert s.ok and s.score == 0.8 and s.label == "positive"


def test_scorer_think_block_with_braces(monkeypatch):
    # kasus jebakan: blok think berisi {} yang bisa merusak regex naif
    body = {"choices": [{"message": {"content":
            '<think>Formatnya {"score": ...}. Berita negatif.</think>'
            '{"score": -0.6, "label": "negative", "confidence": 0.8, '
            '"has_material_event": false, "reason": "rugi"}'}}]}
    monkeypatch.setattr(scorer_mod.requests, "post",
                        lambda *a, **k: FakeResp(json_data=body))
    s = MiniMaxScorer(api_key="test").score("X", [Headline("x", "y", "")])
    assert s.ok and s.score == -0.6 and s.label == "negative"


def test_scorer_no_headlines_skips_api(monkeypatch):
    def boom(*a, **k):
        raise AssertionError("API tidak boleh dipanggil tanpa berita")
    monkeypatch.setattr(scorer_mod.requests, "post", boom)
    s = MiniMaxScorer(api_key="test").score("X", [])
    assert s.score == 0.0 and s.label == "neutral"


def test_scorer_api_error_returns_neutral(monkeypatch):
    def boom(*a, **k):
        raise scorer_mod.requests.RequestException("timeout")
    monkeypatch.setattr(scorer_mod.requests, "post", boom)
    s = MiniMaxScorer(api_key="test").score("X", [Headline("x", "y", "")])
    assert not s.ok and s.score == 0.0 and "LLM error" in (s.error or "")


def test_scorer_not_configured():
    s = MiniMaxScorer(api_key="").score("X", [Headline("x", "y", "")])
    assert not s.ok and "MINIMAX_API_KEY" in (s.error or "")


# ---------------------------------------------------------------------------
# news_fetch
# ---------------------------------------------------------------------------
_RSS = b"""<?xml version="1.0"?><rss><channel>
<item><title>BBRI cetak laba naik 10%</title>
<pubDate>Wed, 22 Jul 2026 10:00:00 GMT</pubDate>
<source url="x">Kontan</source></item>
<item><title>Berita lama BBRI</title>
<pubDate>Wed, 01 Jan 2020 10:00:00 GMT</pubDate>
<source url="x">Bisnis</source></item>
</channel></rss>"""


def test_google_news_parses_and_filters_recency(monkeypatch):
    monkeypatch.setattr(news_mod.requests, "get",
                        lambda *a, **k: FakeResp(content=_RSS))
    heads = news_mod.fetch_google_news("BBRI", days=7)
    titles = [h.title for h in heads]
    assert "BBRI cetak laba naik 10%" in titles
    assert "Berita lama BBRI" not in titles     # 2020 -> tersaring
    assert heads[0].source == "Kontan"


def test_google_news_http_fail_returns_empty(monkeypatch):
    def boom(*a, **k):
        raise news_mod.requests.RequestException("down")
    monkeypatch.setattr(news_mod.requests, "get", boom)
    assert news_mod.fetch_google_news("BBRI") == []


def test_idx_announcements_unwraps_nested_pengumuman(monkeypatch):
    # struktur asli IDX: {"Replies":[{"pengumuman": {JudulPengumuman, TglPengumuman}}]}
    body = {"Replies": [
        {"pengumuman": {"JudulPengumuman": "Rencana Buyback Saham",
                        "TglPengumuman": "2026-07-15T15:39:51"}},
        {"pengumuman": {"JudulPengumuman": "Transaksi Afiliasi",
                        "TglPengumuman": "2026-07-02T10:00:00"}},
    ]}
    monkeypatch.setattr(news_mod.requests, "get",
                        lambda *a, **k: FakeResp(json_data=body))
    heads = news_mod.fetch_idx_announcements("BBRI", days=365)
    assert len(heads) == 2
    assert heads[0].title == "Rencana Buyback Saham"
    assert heads[0].is_disclosure is True        # ditandai disclosure material


# ---------------------------------------------------------------------------
# enrich
# ---------------------------------------------------------------------------
class _FakeResult:
    def __init__(self, ticker):
        self.ticker = ticker
        self.best_buy = type("D", (), {"bull": True})()


def test_enrich_skips_when_not_configured(capsys):
    out = enrich_results([_FakeResult("BBRI")], scorer=MiniMaxScorer(api_key=""))
    assert out == {}                              # tak ada key -> skip aman


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # runner ringan tanpa pytest: sediakan monkeypatch minimal
    class MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)
        def undo(self):
            for o, n, v in reversed(self._undo): setattr(o, n, v)

    class Cap:
        pass

    import inspect
    tests = [(k, v) for k, v in sorted(globals().items())
             if k.startswith("test_") and callable(v)]
    failed = 0
    for name, fn in tests:
        mp = MP()
        try:
            params = inspect.signature(fn).parameters
            kwargs = {}
            if "monkeypatch" in params: kwargs["monkeypatch"] = mp
            if "capsys" in params: kwargs["capsys"] = Cap()
            fn(**kwargs)
            print(f"  PASS  {name}")
        except AssertionError as e:
            failed += 1
            print(f"  FAIL  {name}: {e}")
        except Exception as e:
            failed += 1
            print(f"  ERROR {name}: {type(e).__name__}: {e}")
        finally:
            mp.undo()
    print(f"\n{len(tests) - failed}/{len(tests)} passed")
    sys.exit(1 if failed else 0)
