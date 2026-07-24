# Deploy PRZ Screener ke Railway

Scheduler (`scheduler.py`) berjalan sebagai **worker 24/7**: memanggil
`run_daily.py` Senin–Jumat 18:00 WIB dan `run_weekly.py` Jumat 18:05 WIB,
lalu kirim hasil ke Telegram.

`railway.json` di repo sudah mengatur build (Nixpacks + Python 3.11 + git,
karena `tvdatafeed` dipasang dari GitHub) dan start command `python
scheduler.py`. Kamu tinggal membuat project + mengisi 3–4 variabel.

---

## Cara termudah — deploy dari GitHub (tanpa CLI)

1. Buka **railway.com** → login → **New Project** → **Deploy from GitHub repo**.
2. Pilih repo **`kampala08-dev/prz-screener`** (fork ini).
3. Railway otomatis membaca `railway.json` dan build.
4. Buka service → tab **Variables** → tambahkan:

   | Variable | Value | Wajib |
   |----------|-------|:-----:|
   | `TELEGRAM_BOT_TOKEN` | token @PRZHarmonic_Bot (dari @BotFather) | ✅ |
   | `TELEGRAM_CHAT_ID` | `-1004409180438` (channel XAU-Harmonic) | ✅ |
   | `TZ` | `Asia/Jakarta` | ✅ (agar 18:00 = WIB) |
   | `MPLCONFIGDIR` | `/tmp/mpl` | opsional (cache matplotlib) |

   > **PENTING soal `TZ`**: container Railway default UTC. Tanpa
   > `TZ=Asia/Jakarta`, jadwal 18:00 akan jalan jam 18:00 **UTC** = 01:00
   > WIB dini hari. Variabel ini yang membuat jadwalnya benar.

5. **Deploy**. Cek tab **Deployments → Logs**, harus muncul
   `PRZ Scheduler started.` dan `Daily scan: Senin-Jumat 18:00 WIB`.

Selesai. Worker akan idle sampai jam jadwal, lalu scan + kirim otomatis.

---

## Alternatif via CLI (kalau mau)

```bash
railway login                 # buka browser untuk login
railway init                  # atau: railway link  (ke project yg sudah ada)
railway variables --set TELEGRAM_BOT_TOKEN=xxxx \
                   --set TELEGRAM_CHAT_ID=-1004409180438 \
                   --set TZ=Asia/Jakarta
railway up                    # deploy
railway logs                  # verifikasi
```

---

## Catatan

- **Secrets tidak pernah masuk repo**: `.env` di-gitignore, jadi token
  hanya hidup sebagai Railway Variable. Jangan commit token ke mana pun.
- **Biaya**: worker ini menyala 24/7 tapi hampir selalu idle (sleep 30s).
  Ringan, tapi Railway menagih memory-time. Kalau mau lebih hemat, ubah
  ke **Railway Cron**: hapus `startCommand` scheduler, buat service dengan
  `python run_daily.py --telegram --images-only` dan cron `0 11 * * 1-5`
  (11:00 UTC = 18:00 WIB), plus service kedua untuk weekly `5 11 * * 5`.
- **First run manual**: setelah deploy, bisa test tanpa menunggu jadwal —
  di Railway buka service → **⋮ → Restart**, atau via CLI jalankan sekali:
  `railway run python run_daily.py --tickers BBCA BMRI --telegram --images-only`.
