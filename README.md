# PRZ Scanner — Harmonic Pattern Buy Zone Scanner

Scanner Python untuk mendeteksi pola harmonic XABCD (Gartley, Bat, Butterfly, Crab, Shark) yang mendekati **PRZ (Potential Reversal Zone) arah BUY** pada saham-saham IDX, dengan pengiriman otomatis ke **Telegram** dalam bentuk chart PNG.

## Fitur

- ✅ Deteksi 5 pola harmonic: Gartley, Bat, Butterfly, Crab, Shark
- ✅ 3 timeframe: **Daily**, **Weekly**, **H4**
- ✅ Multi-depth zigzag (3, 5, 8, 12, 20)
- ✅ Output chart PNG per saham yang lolos
- ✅ Kirim hasil ke **grup Telegram** otomatis
- ✅ Scheduler otomatis jam **18:00 WIB** di VPS

---

## Instalasi Lokal

```bash
git clone https://github.com/xavyeerx/prz-screener.git
cd prz-screener

pip install -r requirements.txt

# Setup credentials Telegram
cp .env.example .env
nano .env   # isi TELEGRAM_BOT_TOKEN & TELEGRAM_CHAT_ID
```

---

## Cara Pakai (Manual)

```bash
# Daily scan — full watchlist, kirim ke Telegram (PNG only)
python run_daily.py --telegram --images-only

# Weekly scan
python run_weekly.py --telegram --images-only

# H4 scan
python run_h4.py --telegram --images-only

# Test dengan beberapa ticker saja
python run_daily.py --tickers BBCA BMRI TLKM --telegram --images-only

# Tanpa Telegram (hanya simpan ke output/)
python run_daily.py
```

### Opsi CLI

| Flag | Keterangan |
|------|-----------|
| `--tickers A B C` | Override watchlist |
| `--telegram` | Kirim ke Telegram |
| `--images-only` | Hanya kirim PNG, skip pesan teks summary |
| `--no-charts` | Skip render chart (lebih cepat) |
| `--proximity 3` | Ambang "mendekati PRZ" dalam % (default 3) |
| `--max-dist 80` | Max jarak PRZ dari harga (default 80%) |
| `--period 5y` | Periode history (khusus `run_weekly.py`) |

---

## Setup VPS (Auto-Schedule Jam 18:00 WIB)

### 1. Install otomatis

```bash
bash setup_vps.sh
```

Script ini akan: install dependencies, clone repo, setup .env, set timezone WIB, buat folder.

### 2. Edit `.env`

```bash
nano .env
```

```
TELEGRAM_BOT_TOKEN=your_bot_token_here
TELEGRAM_CHAT_ID=-1001234567890
```

### 3a. Jalankan via Python Scheduler (Recommended)

```bash
source venv/bin/activate
screen -S prz
python scheduler.py
# Ctrl+A, D untuk detach
```

Jadwal otomatis:
- **Daily**: Senin–Jumat jam 18:00 WIB
- **Weekly**: Jumat jam 18:05 WIB

### 3b. Alternatif: Cron

```bash
crontab -e
```

Tambahkan (lihat `crontab.example` untuk detail):

```
0 18 * * 1-5 cd ~/prz-screener && ~/prz-screener/venv/bin/python run_daily.py --telegram --images-only >> logs/daily.log 2>&1
5 18 * * 5   cd ~/prz-screener && ~/prz-screener/venv/bin/python run_weekly.py --telegram --images-only >> logs/weekly.log 2>&1
```

---

## Struktur Project

```
prz-screener/
├── run_daily.py          # Runner Daily (1d)
├── run_weekly.py         # Runner Weekly (1wk)
├── run_h4.py             # Runner H4 (4-hour)
├── scheduler.py          # Auto-scheduler untuk VPS
├── setup_vps.sh          # Installer VPS (Ubuntu/Debian)
├── crontab.example       # Contoh konfigurasi cron
├── .env.example          # Template credentials
├── requirements.txt
├── prz_scanner/
│   ├── config.py         # Konfigurasi & universe saham
│   ├── data_fetch.py     # yfinance wrapper (Daily/Weekly/H4)
│   ├── zigzag.py         # Deteksi pivot multi-depth
│   ├── patterns.py       # Deteksi XABCD + PRZ calc + scoring
│   ├── scanner.py        # Filter proximity + ranking
│   ├── chart_render.py   # Render chart PNG (mplfinance)
│   ├── summary.py        # Export CSV/TXT
│   └── telegram_notify.py # Kirim ke Telegram Bot API
└── logs/                 # Log output scheduler
```

---

## Konfigurasi Watchlist

Edit `prz_scanner/config.py`, bagian `UNIVERSE`:

```python
UNIVERSE: List[str] = [
    "BBCA", "BMRI", "TLKM",  # tambah/hapus sesuai kebutuhan
    ...
]
```

---

## Timeframe Comparison

| | Daily | Weekly | H4 |
|--|--|--|--|
| Script | `run_daily.py` | `run_weekly.py` | `run_h4.py` |
| Timeframe | `1d` | `1wk` | `4h` (resample) |
| History | 2 tahun | 5 tahun | ~2 tahun |
| Depths | 3,5,8,12,20 | 3,5,8,12,20 | 3,5,8,12 |
| Output | `output/daily/` | `output/weekly/` | `output/h4/` |

---

## Pola Harmonic yang Dideteksi

Rasio mengikuti buku *Harmonic Trading* (Scott Carney):

| Pattern | B (XA) | BC Projection | D (XA) |
|---------|--------|---------------|--------|
| Gartley | 0.618 | 1.13–1.618 | 0.786 |
| Bat | 0.382–0.50 | 1.618–2.618 | 0.886 |
| Butterfly | 0.786 | 1.618–2.24 | 1.27 |
| Crab | 0.382–0.618 | 2.618–3.618 | 1.618 |
| Shark | 0.382–0.618 | 1.618–2.24 | 0.886–1.13 (zona dua sisi) |

Basis port dari Pine Script "Harmonic PRZ Scanner v9" (TradingView),
di-upgrade sesuai buku:

- **PRZ = confluence cluster** — anchor proyeksi XA + completion AB=CD
  (termasuk alternate 1.27/1.618) + level proyeksi BC terdekat yang jatuh
  dalam `prz_cluster_tol` (3%). Kolom **Conf** di summary = jumlah elemen
  yang berkumpul (3 = PRZ klasik 3-elemen ala buku).
- **Gate proyeksi BC** memvalidasi CD/BC implied terhadap range buku
  (default ON; matikan dengan `--no-strict-bc`).
- **Zigzag snap-to-extreme** — pivot di-re-anchor ke wick paling ekstrem
  di leg-nya, sehingga garis XABCD selalu menempel di swing high/low sejati.
- **Chart menampilkan maksimal 2 pola** — yang terdekat ke harga dengan
  akurasi tertinggi (best buy selalu ikut), lengkap dengan huruf X-A-B-C-D,
  label rasio tiap leg, dan proyeksi D. Chart otomatis di-crop ke area pola.

---

## Catatan Teknis

- Data H4: yfinance tidak support `4h` native → fetch `60m` lalu resample
- Data Weekly: native `1wk` yfinance, history 5 tahun
- Intraday history yfinance dibatasi ~730 hari untuk `60m`
- Rate limit: ada `sleep(0.4s)` antar-request untuk scan banyak ticker
