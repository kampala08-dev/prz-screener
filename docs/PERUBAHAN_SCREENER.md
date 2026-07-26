# Ringkasan Perbaikan & Perubahan PRZ Screener

**Periode:** 23 Juli 2026
**Referensi utama:** Scott Carney — *Harmonic Trading Volume 3: Reaction vs. Reversal*
(nomor halaman = halaman cetak buku)

Dokumen ini merangkum seluruh perbaikan dan perubahan yang dilakukan pada
screener, dari kondisi awal (port 1:1 Pine Script) hingga tersertifikasi
sesuai teks buku Volume 3.

---

## 1. Bug yang Ditemukan & Diperbaiki

### 1.1 Gate proyeksi BC mati total (bug paling serius)
- **Masalah:** kode lama meng-gate `bc/ab` — yaitu *retracement C* yang
  sudah dicek di range 0.382–0.886 — terhadap range proyeksi BC
  (mis. 1.618–2.618). Kedua range mustahil tumpang tindih, sehingga gate
  **tidak pernah bisa lolos**. Inilah alasan `strict_bc` default OFF di
  Pine aslinya.
- **Perbaikan:** yang di-gate sekarang adalah **CD/BC implied** (proyeksi
  BC yang dibutuhkan untuk mencapai D) — sesuai definisi buku — dan gate
  aktif secara default. Bisa dimatikan dengan `--no-strict-bc`.

### 1.2 Range BC Crab salah
- **Masalah:** kode memakai 2.24–3.618.
- **Perbaikan:** **2.618–3.618** sesuai buku (V3 h.104).

### 1.3 Zigzag bisa melewatkan puncak/lembah sejati
- **Masalah:** deteksi pivot memakai perbandingan strict `>` pada window
  simetris, sehingga *twin peaks/troughs* yang berjarak ≤ `depth` bar
  saling mendiskualifikasi — garis pola bisa menempel di swing yang bukan
  ekstrem sebenarnya.
- **Perbaikan:** pass **snap-to-extreme** — setiap pivot di-re-anchor ke
  wick paling ekstrem di leg-nya (interval antar pivot tetangga), diproses
  kiri-ke-kanan sehingga urutan bar dan alternasi high/low terjaga.

### 1.4 Chart berantakan
- **Masalah:** chart menggambar SEMUA deteksi (bisa 10+ box PRZ per
  saham), pola terjepit kecil karena history 2 tahun ditampilkan penuh.
- **Perbaikan:** lihat bagian 4.

---

## 2. Kalkulasi Disesuaikan dengan Buku (Volume 3)

Seluruh angka diverifikasi langsung terhadap teks PDF *Harmonic Trading
Volume 3* — oleh audit manual + 2 auditor AI independen.

### 2.1 Tabel rasio final

| Pattern | B (XA) | Tol. B | AB=CD Type | Proyeksi BC | D (XA) | Stop | Hal. |
|---------|--------|--------|------------|-------------|--------|------|------|
| Gartley | 0.618 | ±3pp | 1.0–1.27 | 1.13–1.618 | 0.786 | >1.0 XA | 92 |
| Bat | 0.382–0.50 | ±5pp | 1.0–1.618 | 1.618–2.618 | 0.886 | >1.13 XA | 98 |
| Butterfly | 0.786 | ±3pp | 1.0–1.27 | 1.618–2.24 | 1.27 | >1.414 XA | 113 |
| Crab | 0.382–0.618 | ±5pp | 1.0–1.618 | 2.618–3.618 | 1.618 | >2.0 XA | 104 |
| Shark | 0.382–0.618¹ | ±5pp | — | 1.618–2.24 (band) | 0.886–1.13 (dua sisi) | >1.13 XA | 118–120 |

¹ *"0X retracement at the A point"* (h.119) — elemen resmi V3, bukan
filter tambahan.

### 2.2 Toleransi B point absolut (h.91)
- Toleransi B point buku adalah **poin persentase absolut**, bukan persen
  relatif: Gartley/Butterfly ±3pp (0.588–0.648 / 0.756–0.816),
  Bat/Crab/Shark ±5pp pada range-nya.
- Buku menyebutnya *maximum tolerance* (*"become invalid above the upper
  limit"*) → diimplementasikan sebagai **hard limit** yang TIDAK
  dilebarkan di pass loose. Pass loose hanya melonggarkan cek range C dan
  gate BC.

### 2.3 PRZ = confluence cluster (konsep inti buku)
PRZ tidak lagi box tetap ±3–5% XA, melainkan **cluster** dari elemen yang
berkumpul dalam `prz_cluster_tol` (default 3%):
1. **Anchor proyeksi XA** (mis. 0.786·XA untuk Gartley) — selalu ada
2. **Completion AB=CD** + alternate sesuai "AB=CD Type" tiap pola
   (Gartley 1.0–1.27; Bat & Crab 1.0–1.618; Butterfly 1.0–1.27)
3. **Level proyeksi BC terdekat** dari deret fib pola tsb.

Jumlah elemen yang berkumpul = kolom **Conf** di summary (3–4 = PRZ
klasik multi-elemen ala buku; makin tinggi makin kuat).

### 2.4 Shark dua sisi + band overlap
- Zona completion 0.886–1.13 dari leg 0X (dua sisi) dipertahankan.
- Gate BC Shark kini menerima **overlap band** 1.618–2.24 dengan zona di
  titik mana pun (bukan hanya titik tengah) — sesuai h.120.
- Leg ekstensi (AB→C) dibatasi 1.13–1.618.
- Catatan: teks V3 sendiri tidak konsisten menyebut leg acuan zona
  ("0B" vs "XA/0X" vs "0C") — kode mengikuti spec klasik **0X**, yang juga
  didukung penyebutan "1.0 XA level" di V3.

### 2.5 Stop loss per pola (elemen "Stop Loss" tiap spec)
Dulu generik (`prz_lo − 0.10·XA`), sekarang **make-or-break level buku**:
Gartley >1.0 XA · Bat >1.13 · Butterfly >1.414 · Crab >2.0 · Shark >1.13
(+ buffer kecil 0.02·XA untuk kata *"beyond"*).

### 2.6 Target profit Shark (h.118)
TP1/TP2 = retracement **50% / 61.8% dari leg akhir** (reaksi menuju PRZ
pola 5-0), TP3 = retest penuh titik C. (Aturan penuh buku "lesser of 50%
atau Reciprocal AB=CD" tidak bisa dihitung saat deteksi karena butuh leg
pembalikan yang belum terbentuk — 50% adalah minimum resmi buku.)

### 2.7 Structure guards
Validasi geometri eksplisit: B harus di dalam X–A; C harus retracement
(di dalam A) untuk Gartley/Bat/Butterfly/Crab, atau ekstensi (melampaui A)
untuk Shark; alternasi arah pivot diverifikasi.

### 2.8 Skoring akurasi
Skor 0–100 memakai rasio ideal buku + menghargai jumlah confluence:
fidelity rasio B/C (42%) · confluence × ketatnya zona (28%) · pass strict
(12%) · sweet-spot proyeksi D (12%).

---

## 3. Seleksi Pola: Top-2 Terdekat & Terakurat

- Chart hanya menampilkan **maksimal 2 pola**: ranking berdasarkan jarak
  ke harga (bucket 2%), skor akurasi sebagai penentu seri, valid sebelum
  invalid. Best buy selalu ditampilkan.
- **Dedup lintas depth** diperketat: deteksi sama-pola yang mid PRZ-nya
  berjarak < 1.5% dianggap satu zona (ambil skor tertinggi).

---

## 4. Tampilan Chart Baru

- **Arsiran pola** — dua segitiga (X-A-B dan B-C-D) diisi warna transparan
  ala tool harmonic TradingView; pola utama lebih pekat, pola kedua tipis
- **Auto-crop ke area pola** — chart dipotong mulai sedikit sebelum titik
  X sehingga pola besar dan terbaca
- **Huruf X-A-B-C-D** di tiap titik pivot
- **Label rasio di tiap leg** (retracement B, retracement C, multiple D)
- **Garis proyeksi C→D putus-putus** + marker titik D di zona PRZ
- Label PRZ menampilkan status, jumlah confluence (×N), dan skor
- Garis TP1/TP2/TP3/SL untuk best buy

---

## 5. Perubahan Konfigurasi & CLI

| Item | Dulu | Sekarang |
|------|------|----------|
| `strict_bc` | OFF (gate-nya memang mati) | **ON** (gate CD/BC benar); `--no-strict-bc` untuk melonggarkan |
| Toleransi B point | relatif 5%/10% | absolut ±3pp/±5pp, hard limit |
| `prz_cluster_tol` | — | baru: 3% (toleransi elemen confluence) |
| `max_display` | — (semua digambar) | baru: 2 pola per chart |
| Kolom summary | — | baru: **Conf** (jumlah elemen PRZ) |
| Stop/TP | generik | per pola sesuai buku |

---

## 6. Pengujian & Verifikasi

- **11 unit test geometri sintetis** (`tests/test_harmonic_book.py`):
  Gartley ideal (confluence ×4), Bat ideal, regresi gate Crab
  (shallow-C ditolak / deep-C diterima / gate-off diterima), Shark zona
  dua sisi, Shark band-overlap edge case, toleransi-pp B point (hard
  limit), TP Shark dari leg CD, structure guard, snap zigzag, seleksi
  top-2 (×2). **Semua lolos.**
- **Review adversarial 19 agen** (3 reviewer × verifikasi 2 skeptik per
  temuan): 1 temuan dikonfirmasi & ditindaklanjuti, 7 terbantahkan.
- **Audit silang 2 auditor independen** terhadap teks PDF V3: seluruh
  tabel angka diverifikasi cocok per halaman; 3 temuan ditindaklanjuti
  (hard limit toleransi B, dokumentasi ambiguitas leg Shark, dokumentasi
  keterbatasan Reciprocal AB=CD).
- **Live test**: scan penuh 368 ticker berjalan bersih (17 lolos filter
  default), kirim Telegram OK.

---

## 7. Dampak Perilaku yang Perlu Diketahui

1. **Jumlah deteksi berkurang** dibanding versi lama — disengaja: gate BC
   kini benar-benar aktif dan toleransi B mengikat. Sinyal lebih sedikit
   tapi lebih sesuai definisi buku.
2. Pola yang dulu lolos lewat toleransi longgar (contoh nyata: Bat UNVR
   dengan B di luar ±5pp) kini **tertolak — memang tidak valid menurut
   buku**.
3. Level stop umumnya **lebih lebar** (mengikuti make-or-break buku,
   mis. Crab >2.0 XA) — sesuaikan ukuran posisi.
4. Kolom **Conf** bisa dipakai sebagai filter kualitas manual: prioritas
   Conf ≥ 3.

---

## 8. File yang Berubah

| File | Perubahan |
|------|-----------|
| `prz_scanner/patterns.py` | Rasio & gate V3, confluence PRZ, structure guards, stop/TP buku, skoring |
| `prz_scanner/zigzag.py` | Snap-to-extreme pivot |
| `prz_scanner/scanner.py` | Dedup mid-PRZ, seleksi top-2 |
| `prz_scanner/chart_render.py` | Arsiran, crop, huruf, label rasio, proyeksi D |
| `prz_scanner/config.py` | `strict_bc=True`, `prz_cluster_tol`, `max_display` |
| `prz_scanner/summary.py` | Kolom Conf |
| `run_daily.py` / `run_weekly.py` / `run_h4.py` / `prz_scanner/main.py` | Flag `--strict-bc/--no-strict-bc` |
| `tests/test_harmonic_book.py` | Baru — 11 test |
| `README.md` | Tabel rasio V3 + dokumentasi fitur |

---

## 9. Audit Multi-Agen & Hotfix Produksi (25 Juli 2026)

Review menyeluruh 73 agen (6 dimensi + verifikasi adversarial 2 suara per
temuan): 33 kandidat → 19 terkonfirmasi. Diperbaiki dalam dua batch:

### 9.1 Batch 1 — produksi (CRITICAL/HIGH)
- **Weekly scan mati total**: scheduler meneruskan `--cleanup` yang tidak
  didefinisikan parser `run_weekly.py` (argparse exit 2, senyap) — flag
  ditambahkan + test kontrak scheduler↔runner.
- **Weekly starved**: loop menit-eksak vs job daily blocking >5 menit —
  diganti `is_due()` jendela `[jadwal, jadwal+120mnt]` + dedup harian.
- **Bot token bocor ke log** via URL dalam pesan exception `requests` —
  kini di-redact (`***TOKEN***`) di satu titik (`_post`).
- **HTTP 429 drop diam-diam** (fallback hanya cocok "400") — kini patuhi
  `parameters.retry_after` (maks 2 retry, cap 90 dtk); `send_photo`
  mengirim bytes agar retry membawa body utuh.
- `chmod 600 .env` + hardening systemd minimal di `setup_vps.sh`.

### 9.2 Batch 2 — akurasi sinyal
- **Penanda anti-repaint** ⏳: scan live kini memakai `with_confirm=True`;
  `Detection.c_confirmed=False` bila pivot C belum punya `depth` bar
  konfirmasi (snap-forward ke ekstrem yang masih berkembang). Caption
  Telegram menampilkan peringatan "C belum terkonfirmasi — bisa repaint,
  di luar populasi backtest". Sinyal tetap dikirim (disclosure, bukan
  suppress).
- **Outside bar**: bar yang lolos tes pivot high DAN low sekaligus kini
  emit SATU pivot yang beralternasi (dulu dua pivot di bar sama → pola
  leg durasi-0). Ditambah guard `xi<ai<bi<ci` di `scan_points`.
- **Shark ideal_c 1.414 → 1.929** (titik tengah rentang impuls buku
  1.618–2.24; nilai lama di luar rentang sah sehingga setiap Shark valid
  terpenalti dan varian paling-sesuai-buku justru terbuang saat dedup).
- **Dedup backtest earliest-confirm**: varian zona yang dipertahankan =
  konfirmasi paling awal (yang pertama bisa di-trade live), bukan skor
  tertinggi (seleksi memakai informasi masa depan).

### 9.3 Angka backtest pasca-fix (re-run penuh, 362 saham × 5 th)
Subset quality **Crab+Bat conf≥2: 58.0% win, +0.161R (362 trades)** —
praktis identik dengan sebelum fix dedup (58.2%, +0.163R): edge nyata,
bukan artefak bias seleksi. Per pola: Crab 64.4%, Bat 53.2%; stabil
55–64% di 2021–2025 (terlemah 2026: 50.8%). Shark tetap terlemah (34.5%).

Test suite: 40 → **64** (scheduler 12, telegram 7, harmonic +4, backtest +1).

### 9.4 Batch 3 — robustness & supply chain
- **Error sentimen tidak lagi tersamar "sepi berita"**: kegagalan skoring
  (key invalid, JSON rusak, timeout) kini ber-reason `skor gagal: <error>`
  dan tampil `[GAGAL: ...]` di log; respons MiniMax HTTP-200 dengan error
  `base_resp` (mis. 1004 key invalid) dideteksi eksplisit.
- **Anti prompt-injection**: judul/sumber berita disanitasi (`_clean_title`
  — newline & tag `[DISCLOSURE IDX]` palsu dibuang, panjang dibatasi);
  system prompt menegaskan tag disclosure hanya sah dari sistem.
- **Respons reasoning terpotong**: blok `<think>` tanpa penutup dibuang
  seluruhnya — draft JSON di dalam reasoning tak pernah dipakai sebagai
  jawaban.
- **Exit code kegagalan Telegram**: run_daily/run_weekly/run_h4 kini
  `exit 3` bila pengiriman gagal total — scheduler mencatat FAIL di
  journalctl (dulu selalu exit 0, kegagalan tak terlihat).
- **run_h4 paritas scheduler**: `--images-only` ditambahkan, `--cleanup`
  benar-benar dipakai (dulu no-op), `sent` hanya dihitung saat kirim
  sukses. Test kontrak flag kini mencakup ketiga runner.
- **Supply chain**: `tvdatafeed` di-pin ke commit tervalidasi
  (`e6f6aaa`); auto-`pip install` saat import di `data_fetch.py` DIHAPUS
  (eksekusi installer dari jaringan di proses ber-secret = vektor RCE).
- **crontab.example**: pakai python venv (bukan `python3` sistem yang
  ImportError senyap) + jadwal disamakan (12:00/17:00, Jumat 17:05).

Test suite: 64 → **69** (sentimen +4, kontrak run_h4 +1).

---

## 10. Review Eksternal (Guru) — Pengetatan Gate ke Batas Buku (26 Juli 2026)

Kritik guru Rio: "rasio-rasionya tidak memenuhi syarat PRZ" pada chart
BBNI/TUGU/LPPF/RMKE/PANI. Diverifikasi dengan menghitung ulang rasio
internal tiap deteksi (bukan dari pembacaan chart). Vonis:

**Guru BENAR (3):**
- LPPF Shark: impuls BC/AB = 2.419 > 2.24 — lolos karena pass loose
  melebarkan gate 10% (2.464). Gate impuls kini KERAS → LPPF ditolak.
- PANI Crab: C = 0.915 > 0.886 lolos di pass STRICT (tol 5% = 0.930);
  PANI Bat SELL: C = 0.946 lolos loose. Rentang C 0.382-0.886 kini
  batas KERAS di kedua pass (prinsip yang sama dgn B-point p.91).
- Efek berantai TUGU (bug yang terungkap): level cluster 1.27·AB=CD di
  ~1.04·XA — melewati make-or-break Gartley 1.0·XA — menyeret prz_lo
  (1171) MENEMBUS stop (1172). Level di luar make-or-break kini
  dikeluarkan dari cluster + zona di-clamp.

**Bukan pelanggaran (2):**
- B-point 0.542/0.645/0.526: sah menurut toleransi buku sendiri
  (V3 p.91: ±3pp point-B, ±5pp range-B).
- "D tidak di rasio buku": label chart lama menulis TENGAH zona cluster
  (mis. Bat terbaca 0.834) padahal anchor buku (0.886) selalu berada di
  dalam zona. Titik D & label kini digambar DI ANCHOR buku; Shark tetap
  tengah zona dua-sisi.

**Backtest populasi murni-buku (re-run penuh):**
Crab+Bat conf≥2: 56.4% win, +0.133R (289 trades) vs 58.0%/+0.161R/362
sebelum pengetatan. 73 trade pinggir-toleransi yang terbuang menang ~64%
— pengetatan menukar sedikit expectancy historis demi kepatuhan rasio
buku (selisih dalam noise, SE ~2.9pp). Crab justru naik (65.9%); Shark
murni-buku makin lemah (29.4%, 68% kena SL) — konsisten: Shark bukan
pola trigger. Test suite: 69 → 72.
