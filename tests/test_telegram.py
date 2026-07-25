"""Unit test TelegramSender — semua HTTP di-mock, TIDAK memanggil API asli.

Cakupan (dari review 2026-07-25):
  - Redaksi token: pesan error requests memuat URL ber-token; RuntimeError
    dari _post WAJIB bebas token (dulu bocor ke journalctl/scheduler.log).
  - HTTP 429: patuhi parameters.retry_after lalu ulangi; habis retry ->
    send_* return False tanpa raise.
  - Fallback 400 -> plain text tetap bekerja lewat pesan RuntimeError baru.
  - send_photo memakai bytes (bukan handle) agar retry mengirim body utuh.
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from prz_scanner import telegram_notify as tn
from prz_scanner.telegram_notify import TelegramSender

TOKEN = "123456:AAH-rahasia-bot-token"
URL_WITH_TOKEN = f"https://api.telegram.org/bot{TOKEN}/sendMessage"


class FakeResp:
    def __init__(self, status=200, json_data=None):
        self.status_code = status
        self._json = json_data if json_data is not None else {"ok": True}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise tn.requests.exceptions.HTTPError(
                f"{self.status_code} Client Error: X for url: {URL_WITH_TOKEN}")

    def json(self):
        if self._json is None:
            raise ValueError("bukan JSON")
        return self._json


def _sender():
    return TelegramSender(token=TOKEN, chat_id="-100123")


def _seq_post(responses, calls):
    """fake requests.post yang mengembalikan responses berurutan."""
    def post(url, **kwargs):
        calls.append({"url": url, **kwargs})
        return responses[min(len(calls) - 1, len(responses) - 1)]
    return post


# ---------------------------------------------------------------------------
# Redaksi token
# ---------------------------------------------------------------------------
def test_post_error_meredaksi_token(monkeypatch):
    calls = []
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([FakeResp(404, json_data={"ok": False})], calls))
    try:
        _sender()._post("sendMessage", data={})
        raise AssertionError("harus raise RuntimeError")
    except RuntimeError as e:
        msg = str(e)
        assert TOKEN not in msg, "token bocor di pesan error!"
        assert "***TOKEN***" in msg
        assert "404" in msg          # info status tetap ada utk fallback/debug


def test_send_message_gagal_tanpa_membocorkan_token(monkeypatch, capsys=None):
    calls = []
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([FakeResp(401, json_data={"ok": False})], calls))
    ok = _sender().send_message("halo")
    assert ok is False               # 401 bukan 400 -> tidak ada fallback, False


# ---------------------------------------------------------------------------
# HTTP 429 flood control
# ---------------------------------------------------------------------------
def test_429_patuh_retry_after_lalu_sukses(monkeypatch):
    calls, sleeps = [], []
    resp429 = FakeResp(429, json_data={"ok": False,
                                       "parameters": {"retry_after": 3}})
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([resp429, FakeResp(200)], calls))
    monkeypatch.setattr(tn.time, "sleep", lambda s: sleeps.append(s))
    resp = _sender()._post("sendMessage", data={"text": "x"})
    assert resp["ok"] is True
    assert len(calls) == 2           # 429 -> retry -> 200
    assert sleeps == [4]             # retry_after 3 + 1


def test_429_habis_retry_send_message_false(monkeypatch):
    calls, sleeps = [], []
    resp429 = FakeResp(429, json_data={"ok": False,
                                       "parameters": {"retry_after": 1}})
    monkeypatch.setattr(tn.requests, "post", _seq_post([resp429], calls))
    monkeypatch.setattr(tn.time, "sleep", lambda s: sleeps.append(s))
    ok = _sender().send_message("x")
    assert ok is False
    # attempt 0 & 1 retry, attempt 2 raise -> total 3 panggilan HTTP
    assert len(calls) == 1 + tn.TelegramSender._MAX_429_RETRY


def test_429_retry_after_dibatasi_cap(monkeypatch):
    calls, sleeps = [], []
    resp429 = FakeResp(429, json_data={"ok": False,
                                       "parameters": {"retry_after": 3600}})
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([resp429, FakeResp(200)], calls))
    monkeypatch.setattr(tn.time, "sleep", lambda s: sleeps.append(s))
    _sender()._post("sendMessage", data={})
    assert sleeps == [tn.TelegramSender._MAX_429_WAIT_S + 1]


# ---------------------------------------------------------------------------
# Fallback 400 -> plain text (harus tetap jalan dgn pesan RuntimeError baru)
# ---------------------------------------------------------------------------
def test_send_message_400_fallback_plain(monkeypatch):
    calls = []
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([FakeResp(400, json_data={"ok": False}),
                                   FakeResp(200)], calls))
    ok = _sender().send_message("<b>BBRI</b> sinyal")
    assert ok is True
    assert len(calls) == 2
    # attempt kedua: tanpa parse_mode, tag HTML sudah di-strip
    assert "parse_mode" not in calls[1]["data"]
    assert calls[1]["data"]["text"] == "BBRI sinyal"


# ---------------------------------------------------------------------------
# send_photo — bytes utuh saat retry
# ---------------------------------------------------------------------------
def test_send_photo_429_mengirim_ulang_bytes_utuh(monkeypatch):
    calls, sleeps = [], []
    resp429 = FakeResp(429, json_data={"ok": False,
                                       "parameters": {"retry_after": 1}})
    monkeypatch.setattr(tn.requests, "post",
                        _seq_post([resp429, FakeResp(200)], calls))
    monkeypatch.setattr(tn.time, "sleep", lambda s: sleeps.append(s))

    fd, path = tempfile.mkstemp(suffix=".png")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(b"PNG-ISI-CHART")
        ok = _sender().send_photo(path, caption="cap")
        assert ok is True
        assert len(calls) == 2
        # dua-duanya membawa bytes penuh (bukan handle yang sudah EOF)
        for c in calls:
            fname, body = c["files"]["photo"]
            assert body == b"PNG-ISI-CHART"
    finally:
        os.remove(path)


# ---------------------------------------------------------------------------
if __name__ == "__main__":
    # runner ringan tanpa pytest: monkeypatch minimal (pola test_sentiment.py)
    class MP:
        def __init__(self): self._undo = []
        def setattr(self, obj, name, val):
            self._undo.append((obj, name, getattr(obj, name)))
            setattr(obj, name, val)
        def undo(self):
            for o, n, v in reversed(self._undo): setattr(o, n, v)

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
            if "capsys" in params and params["capsys"].default is inspect.Parameter.empty:
                kwargs["capsys"] = None
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
