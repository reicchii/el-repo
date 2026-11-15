# Panduan Penggunaan Lengkap — Phantom Worlds

Panduan ini mencakup cara menjalankan aplikasi Web UI + FastAPI, memanggil 24 endpoint REST API, menjalankan inferensi model ML secara langsung dari Python/CLI, mengunduh data arsip SPHEREx/Gaia nyata, melatih ulang model, menjalankan laporan Proof v2, serta mengatasi masalah umum.

---

## 1. Menjalankan Server Web UI & REST API

Aplikasi backend berada di [`phantom_worlds/api.py`](../phantom_worlds/api.py) menggunakan pola factory (`create_app`), sehingga Uvicorn **wajib** dijalankan dengan flag `--factory`:

```bash
python -m uvicorn phantom_worlds.api:create_app --factory --host 127.0.0.1 --port 8000
```

Buka browser dan kunjungi **`http://127.0.0.1:8000/`**.

### Opsi Variabel Lingkungan (Environment Variables)

Backend membaca variabel lingkungan OS secara langsung (tidak memakai auto-loader `python-dotenv`; lihat [`.env.example`](../.env.example)):

| Variabel | Fungsi | Contoh |
|---|---|---|
| `PHANTOM_DISABLE_PREWARM=1` | Menonaktifkan *prewarm* background ML, M1, dan `search_field_sources` saat startup (berguna untuk pengujian cepat / CI / mesin hemat RAM). | `PHANTOM_DISABLE_PREWARM=1` |
| `PHANTOM_EMBED_FRAME_ANCESTORS` | Daftar origin yang diizinkan pada header CSP `frame-ancestors` saat membuka endpoint `/?embed=1` di dalam `<iframe>`. | `"https://huggingface.co https://example.com"` |

> [!TIP]
> **Contoh menyetel env di Windows PowerShell sebelum menyalakan server:**
> ```powershell
> $env:PHANTOM_DISABLE_PREWARM = "1"
> python -m uvicorn phantom_worlds.api:create_app --factory --host 127.0.0.1 --port 8000
> ```
> **Mode Offline / Static Fallback:** Seluruh target uji dan data prakomputasi juga dibundel ke [`phantom_worlds/static/fallback_data.js`](../phantom_worlds/static/fallback_data.js) (`3,861,777` byte), sehingga tampilan dasar antarmuka tetap dapat menunjukkan aset statis meskipun koneksi internet ke IRSA terputus.

---

## 2. Panduan Antarmuka Web UI (`/`)

Setelah membuka `http://127.0.0.1:8000/`, komponen di [`phantom_worlds/static/index.html`](../phantom_worlds/static/index.html) dapat dioperasikan dengan urutan berikut:

1. **Cari Koordinat Langit atau Pilih Benchmark / Bidang Tier B:**
   - Masukkan koordinat ICRS HMS/DMS, derajat desimal `(RA, Dec)`, atau nama target pada kolom input (default: `WISE 0855`), pilih FOV (`2.5'`, `5.0'`, `6.5'`, `12.0'`), dan Epoch (default `2026.0`).
   - Klik **`Load Sky Patch`** untuk memicu pembaruan data lokal, atau **`Query Live IRSA`** untuk meminta arsip SPHEREx SIAv2 langsung dari NASA/IPAC IRSA.
   - Tersedia tombol cepat untuk 5 target Tier A (`Barnard's Star`, `WISE 0855`, `Epsilon Indi B`, `RW Aurigae`, `R Draconis`) dan 2 bidang Tier B (`W1925 Galactic Plane`, `RW Aurigae Field`).
2. **Kontrol Blink, Detektor, dan Pengurangan Bintang Diketahui (`Remove known`):**
   - Pilih salah satu dari 6 detektor SPHEREx **`D1` – `D6`** serta mode tampilan (**`Single frame`**, **`Stack`**, **`Difference`**, atau **`Visits RGB`**).
   - Pada bidang Tier B, gunakan kontrol **`Remove known`** untuk beralih antara **`Image`**, **`Model`** (model PSF Gaia DR3/2MASS/CatWISE2020), **`Residual`** (sisa pengurangan), dan **`Searched depth`**.
   - Atur pemutaran waktu dengan tombol **`Pause`**, penggeser **`Visit`**, **`Stretch`**, **`Play speed`**, serta overlay **`Gaia`**, **`Mask`**, **`Invert`**, **`Follow motion`**, atau sisipkan **`Test source (S/N 5)`**. Hasil tampilan dapat diunduh lewat **`Export PNG`** / **`CSV`**.
3. **Pencarian Spektral (`Search by light`) & Triage (`Signals & Cases`):**
   - Di panel **`Search by light`**, filter kandidat berdasarkan 12 kategori spektral/fisika (termasuk `Ultracool dwarf`, `Young star (YSO)`, `Star`, `Evolved giant`, `Galaxy`, `Active galaxy / QSO`, `Methane dip (3.3 um)`, `H2O ice (3.05 um)`, dll.), ambang `min_snr`, batas `max_blend`, atau `only_unexplained`.
   - Klik kandidat untuk membuka modal **`Identity v2`** (estimasi kelas `spectrum_alone` dan `all_data`, 3 kandidat kelas teratas, skor keanehan `M3`, pembacaan 4 molekul es, serta rasio/status `M1`) atau klik tombol **`Model Card & Gates`** untuk melihat status gerbang rilis langsung dari backend.
   - Gunakan panel **`Signals & Cases`** untuk menyaring dan melakukan triase kasus lokal.
4. **Pencarian Objek Tata Surya & Panel Proof:**
   - Gunakan **`Moving object lookup`** (tombol cepat **`3I/ATLAS`** dan **`Ceres`**) yang memanggil `GET /api/sso` menuju IMCCE/IRSA MOST.
   - Gulir ke panel **`Proof`** untuk meninjau tabel evaluasi Tier A/B terkini, kurva pemulihan injeksi (`D3` & `D6`), tangga fitur input R1–R5, batasan terukur, dan bagian `Next`.

---

## 3. Referensi Endpoint REST API (`24` Endpoint)

Semua 24 endpoint HTTP berikut terverifikasi langsung pada OpenAPI schema `create_app()` di [`phantom_worlds/api.py`](../phantom_worlds/api.py):

### Status, UI Statis & Tier A Viewer

| Method & Path | Parameter (Sumber & Default) | Fungsi |
|---|---|---|
| `GET /` | Query: `embed` (opsional, default `None`) | Menyajikan [`phantom_worlds/static/index.html`](../phantom_worlds/static/index.html). Mode `?embed=1` menerapkan kebijakan header `PHANTOM_EMBED_FRAME_ANCESTORS`. |
| `GET /static/{asset_name}` | Path: `asset_name` (wajib) | Menyajikan hanya aset terizinkan: `viewer.js`, `fallback_data.js`, `styles.css`. |
| `GET /health` | — | Cek kesehatan server & mode kesiapan fallback statis (`schema_version: 1.0.0-hour0`). |
| `GET /api/targets` | Query: `epoch_yr` (`2026.0`) | Daftar 5 target uji NASA dengan koordinat yang dipropagasikan ke `epoch_yr`. |
| `GET /api/patch/manifest` | Query: `target_id` (opsional) | Metadata manifest potongan WCS target (`TGT-01` s.d. `TGT-05`). |
| `GET /api/patch/stack/{detector_id}` | Path: `detector_id` (`D1`..`D6`); Query: `target_id` | Citra stack median berbobot masker untuk satu detektor. |
| `GET /api/patch/timeseries` | Query: `detector` (`D6`), `target_id` | Kubus frame antar-kunjungan, stack, difference, dan bitmask (`mask_overlay`). |
| `GET /api/patch/metrics` | Query: `target_id` | Metrik Tier A target (Gaia alignment RMS, S/N, gerak proper motion). |
| `GET /api/proof/summary` | — | Ringkasan bukti & metrik cepat Tier A. |
| `GET /api/sso` | Query: `name` (wajib), `frame_limit` (`120`) | Ephemeris objek bergerak Tata Surya via IRSA MOST. |
| `GET /api/sky/timeseries` | Query: `coord`, `ra_deg`, `dec_deg`, `fov_arcmin` (`6.5`), `epoch_yr` (`2026.0`), `detector` (`D6`), `live` (`false`), `frame_limit`, `frame_offset` (`0`) | Query potongan langit lengkap + arsip IRSA SIAv2 opsional + sumber Gaia DR3 + spektrum 102 pita. |
| `GET /api/sources` | — | Katalog sumber yang disinkronkan dari `csv_tables/`. |
| `GET /api/cases` | — | Daftar kasus ML/pengamatan awal (`cases.json`). |
| `GET /api/cases/{case_id}/export` | Path: `case_id` (wajib) | Paket ekspor JSON lengkap untuk satu ID kasus. |

### Tier B Bidang Langit, Model ML, Proof v2 & Analisis Spektrum

| Method & Path | Parameter / Payload (Sumber & Default) | Fungsi |
|---|---|---|
| `GET /api/fields` | — | Daftar bidang langit terproses (`w1925` & `rwaur`). |
| `GET /api/field/search` | Query: `field_id` (`all`), `categories`, `min_snr` (`5.0`), `max_blend` (`1.0`), `only_unexplained` (`false`), `sort_by` (`priority`), `limit` (`80`) | Mesin pencarian **Search by light** lintas bidang `w1925` & `rwaur`. |
| `GET /api/proof/report` | — | Muatan JSON lengkap laporan **Proof v2** (`proof/report.json`). |
| `GET /api/field/prediction_check` | — | Status uji prediksi posisi mundur (B7) & prediksi terkunci ke depan. |
| `GET /api/field/searched` | Query: `field_id` (`all`) | Kurva kedalaman deteksi (*searched depth* B8/B9) per bidang & detektor. |
| `GET /api/field/cases` | Query: `field_id` (`all`), `state` (`all`) | Daftar kasus bidang langit Tier B (`182` total kasus di report v2). |
| `GET /api/field/{field_id}/source/{source_id}` | Path: `field_id`, `source_id` | Paket **Identity v2** lengkap + strip spektrum + status Model Card & M1. |
| `GET /api/field/{field_id}/analyze` | Path: `field_id`; Query: `include_skybot` (`false`) | Hasil analisis penuh seluruh kandidat, leftover, mover, M1, & B10 pada bidang. |
| `GET /api/field/{field_id}/remove_known` | Path: `field_id`; Query: `detector` (`D3`), `visit_idx` | Frame citra asli, model PSF Gaia/2MASS, dan citra residual per kunjungan/stack. |
| `POST /api/analyze/spectrum` | Body JSON `SpectrumAnalyzeRequest` | Analisis 102-band spektrum langsung menggunakan model ML terlatih + pembacaan molekul Layer 1. |

### Contoh Request & Output Terverifikasi: `POST /api/analyze/spectrum`

Skema body JSON `SpectrumAnalyzeRequest`:
- `flux_uJy`: *(wajib)* list `float | null` panjang exact **`102`** dalam satuan mikrojansky (`uJy`) pada grid referensi API (`0.7603..4.9824` μm; otomatis di-*resample* ke grid model `0.753..4.988` μm dan dihitung `has_masked_pixels` dari nilai `null`). Minimal `>= 3` nilai finit (`abs <= 1e30`) agar diterima; bila tidak, server mengembalikan HTTP `422`.
- `flux_err_uJy`: *(opsional)* list `float | null` panjang exact `102` (finit non-negatif `<= 1e30`). Bila tidak dikirim, `uncertainty_available` pada pembacaan molekul bernilai `false`.
- `blend_share`: `float` dalam `[0.0, 1.0]` (default `0.0`; `> 0.3` memicu penolakan pembacaan molekul).
- `is_variable`: `bool` (default `false`; `true` memicu penolakan pembacaan molekul dan penyaringan `CONTAMINATION_SCREENED`).
- `parallax_snr`: `float | null` (opsional, default `null`, finit `abs <= 1e12`; nilai `> 5.0` mengaktifkan gerbang paralaks E4 pada cabang `all_data`).

**Contoh Uji via Python / `requests` (mengambil spektrum referensi `Eps_Indi_B` dari CSV proyek):**

```python
import requests
from phantom_worlds.contracts import load_spectra_table

tbl = load_spectra_table()
payload = {
    "flux_uJy": [float(r["Eps_Indi_B_uJy"]) for r in tbl["rows"]],
    "blend_share": 0.05,
    "is_variable": False,
    "parallax_snr": 100.0,
}
resp = requests.post("http://127.0.0.1:8000/api/analyze/spectrum", json=payload, timeout=30)
resp.raise_for_status()
print(resp.json())
```

**Contoh via `curl` (membaca berkas `request.json` hasil penyusunan 102 pita):**

```bash
curl -s -X POST "http://127.0.0.1:8000/api/analyze/spectrum" \
  -H "Content-Type: application/json" \
  --data-binary @request.json
```

**Contoh Output JSON Nyata (`200 OK`, terverifikasi lewat `TestClient` pada `Eps_Indi_B`):**

```json
{
  "molecule_readings": {
    "status": "MEASURED",
    "refusal_reason": null,
    "features": {
      "H2O_ice_3_05": {
        "status": "MEASURED",
        "refusal_reason": null,
        "integrated_tau": 954.500833108423,
        "column_density_cm2": 4.772504165542115e+18,
        "rel_to_h2o_ice_pct": 100.0,
        "median": null,
        "p16": null,
        "p84": null,
        "uncertainty_available": false,
        "uncertainty_reason": "Uncertainties unavailable: flux_err not provided",
        "origin": "Measured"
      },
      "CH4_3_3": {
        "status": "MEASURED",
        "refusal_reason": null,
        "integrated_tau": 1059.517994654372,
        "column_density_cm2": 1.0595179946543718e+20,
        "rel_to_h2o_ice_pct": 2220.0462,
        "uncertainty_available": false
      },
      "CO2_4_26": { "status": "MEASURED", "integrated_tau": -12.517819501398181, "column_density_cm2": 0.0 },
      "CO_4_67": { "status": "MEASURED", "integrated_tau": -8.058969670078213, "column_density_cm2": 0.0 }
    }
  },
  "classification": {
    "spectrum_alone": {
      "top_class": "Ultracool dwarf",
      "confidence": 0.9991,
      "template_class": "Ultracool dwarf",
      "tree_class": "Ultracool dwarf",
      "conformal_set": ["Ultracool dwarf"]
    },
    "all_data": {
      "top_class": "Ultracool dwarf",
      "confidence": 0.9992,
      "parallax_gate_applied": true,
      "conformal_set": ["Ultracool dwarf"]
    },
    "novelty": {
      "status": "NOVEL",
      "weirdness_score": 0.6639
    },
    "model_origin": "real_spherex_dr1_spiff_trained"
  }
}
```

---

## 4. Inferensi Model Langsung via CLI / Skrip Python

Gunakan `get_cached_ml_pipeline()` (untuk auto-load `disk_checkpoint` beserta `evaluation_report.json` dengan fallback aman ke pelatihan live) atau `load_pipeline_checkpoint()` untuk memuat model langsung dari disk tanpa menyalakan server HTTP.

> [!IMPORTANT]
> Pastikan panjang array input sesuai grid model (`pipe.wavelengths`: 102 band dari `0.753` s.d. `4.988` μm). Jika spektrum Anda berasal dari grid panjang gelombang berbeda (misalnya `spherex_102_band_spectra.csv` pada `0.7603..4.9824` μm), lakukan resampling terlebih dahulu dengan `resample_spectrum_to_grid()` sebelum memanggil `pipe.predict_one()`.

```python
import numpy as np
from phantom_worlds.contracts import load_spectra_table
from phantom_worlds.ml_pipeline import compute_molecule_readings
from phantom_worlds.real_ml_data import resample_spectrum_to_grid
from phantom_worlds.tier_b_detectors import get_cached_ml_pipeline

# 1. Auto-load checkpoint ml/spectral_discovery_pipeline.pkl.gz (terverifikasi SHA-256)
bundle = get_cached_ml_pipeline()
pipe = bundle["pipeline"]
print("Load source:", bundle["load_source"], "| Model version:", bundle["model_version"])

# 2. Siapkan spektrum 102-band pada grid model (contoh: Eps_Indi_B)
tbl = load_spectra_table()
wl_in = np.array([float(r["wavelength_um"]) for r in tbl["rows"]], dtype=np.float64)
fl_in = np.array([float(r["Eps_Indi_B_uJy"]) for r in tbl["rows"]], dtype=np.float64)
fl_model_grid = resample_spectrum_to_grid(wl_in, fl_in, pipe.wavelengths)

# 3. Jalankan klasifikasi, pembacaan molekul & estimasi subtipe UCD
pred = pipe.predict_one(fl_model_grid, blend_share=0.05, is_variable=False, parallax_snr=100.0)
mol = compute_molecule_readings(pipe.wavelengths, pipe.bandwidths, fl_model_grid, blend_share=0.05)
ucd = pipe.predict_ucd_subtype(fl_model_grid)

print("Prediksi:", pred["spectrum_alone"]["top_class"], "| Conf:", pred["spectrum_alone"]["confidence"])
print("Molekul:", mol["status"], "| CH4 tau:", mol["features"]["CH4_3_3"]["integrated_tau"])
print("Subtipe UCD:", ucd)
```

---

## 5. Reproduksi Dataset, Training, Proof v2, Kontrak & Tes

### A. Mengunduh Data Nyata & Membangun Katalog Kurasi

Skrip berada di `phantom_worlds_dataset_kit/scripts/`:

```bash
# 1. Unduh data nyata IRSA SPHEREx SIAv2 + Gaia DR3 untuk 5 target uji bawaan
python phantom_worlds_dataset_kit/scripts/download_real_spherex_gaia.py

# 2. Bangun katalog ML kurasi lintas-kelas (~1.446 target di csv_tables/curated_ml_targets.csv)
python phantom_worlds_dataset_kit/scripts/build_ml_catalog.py

# 3. Unduh metadata arsip untuk katalog kurasi (opsional, mendukung --resume)
python phantom_worlds_dataset_kit/scripts/download_real_spherex_gaia.py \
  --targets-csv phantom_worlds_dataset_kit/csv_tables/curated_ml_targets.csv \
  --out-dir phantom_worlds_dataset_kit/scripts/data_ml_curated \
  --workers 4 \
  --resume
```

*(Catatan: `build_ml_catalog.py` menyediakan opsi `--per-class`, `--out-csv`, `--min-sep-arcsec`, `--no-spiff`, `--no-splices`, `--no-gaia`. Sedangkan `download_real_spherex_gaia.py` mendukung pencarian titik kustom via `--ra`, `--dec`, `--name`, `--pmra`, `--pmdec`, `--radius-deg`, `--collections`, `--skip-existing`, `--workers`, `--max-targets`.)*

### B. Membangun Dataset Latih `.npz` & Potongan FITS Nyata S3

```bash
# Membangun potongan FITS S3 Level-2 (HTTP Range) ke hour0_contracts/
python -m phantom_worlds.fits_cutout

# Membangun dataset ML 102-band dari SPHEREx DR1 HiPS5 Cube & SPIFF Zenodo ke ml/real_training_dataset.npz
python -m phantom_worlds.real_ml_data \
  --output-npz ml/real_training_dataset.npz \
  --output-manifest ml/dataset_manifest.json \
  --max-bds 200 \
  --workers 6
```

*(Tambahkan `--no-cache` untuk mengabaikan cache lokal di `data/`).*

### C. Melatih Ulang Model & Mengekspor Checkpoint (`.pkl.gz`)

```bash
python -m ml.train \
  --dataset ml/real_training_dataset.npz \
  --output-dir ml \
  --max-per-class 14 \
  --seed 42 \
  --log-file data/logs/train.log
```

Perintah ini menghasilkan kembali 4 berkas di `ml/`:
- [`ml/spectral_discovery_pipeline.pkl.gz`](../ml/spectral_discovery_pipeline.pkl.gz)
- [`ml/spectral_discovery_pipeline.meta.json`](../ml/spectral_discovery_pipeline.meta.json)
- [`ml/evaluation_report.json`](../ml/evaluation_report.json)
- [`ml/model_card.md`](../ml/model_card.md)

### D. Menjalankan Laporan Proof v2, Kontrak, & Suite Tes

```bash
# Menghasilkan proof/report.json dan proof/report.md (tambahkan --include-skybot untuk query SkyBoT langsung)
python -m proof.run --out-dir proof

# Menyinkronkan Hour-0 JSON/CSV contracts & membangun ulang static/fallback_data.js
python -m phantom_worlds.contracts

# Menjalankan seluruh unit/contract/ML/API test suite
python -m pytest phantom_worlds_dataset_kit/tests -v

# Memeriksa tautan relatif Markdown di berkas terdokumentasi git
python scripts/check-docs.py
```

---

## 6. Pemecahan Masalah (Troubleshooting)

| Gejala / Error | Penyebab | Solusi |
|---|---|---|
| `uvicorn`: `Attribute 'app' not found in module 'phantom_worlds.api'` | `phantom_worlds/api.py` mengekspor fungsi pabrik `create_app()`, bukan variabel `app` tingkat modul. | Selalu sertakan flag `--factory`: `python -m uvicorn phantom_worlds.api:create_app --factory --host 127.0.0.1 --port 8000`. |
| `CheckpointVerificationError` / backend memuat lewat `live_fit` yang lambat (~42 detik) alih-alih `disk_checkpoint` (~0,03 detik) | Versi `scikit-learn`/`numpy` tidak cocok (`!= 1.9.0` / `!= 2.5.1`), `ml/spectral_discovery_pipeline.meta.json` hilang, file `.py`/`.npz` dimodifikasi, atau SHA-256 tidak cocok. | Instal paket dari `requirements.lock` (`pip install -r requirements.lock`), pastikan `.pkl.gz` & `.meta.json` berpasangan di `ml/`, atau latih ulang checkpoint baru dengan `python -m ml.train`. |
| Peringatan atau jeda worker `loky` di Windows saat startup | Pemeriksaan jumlah inti CPU oleh `loky` di Windows dapat melambat/menggantung pada beberapa sistem. | `ml_pipeline.py` dan `tier_b_detectors.py` sudah menyetel `LOKY_MAX_CPU_COUNT="1"` secara default; hindari menimpanya atau jalankan dengan `PHANTOM_DISABLE_PREWARM=1` saat debugging. |
| `CUDA` / GPU tidak terdeteksi | Model memakai `scikit-learn` berbasis CPU dan tidak bergantung pada PyTorch/CUDA. | Abaikan cek GPU; semua inferensi dan pelatihan berjalan murni di CPU. |
| `422 Unprocessable Entity` pada `POST /api/analyze/spectrum` | Panjang `flux_uJy` (atau `flux_err_uJy`) bukan exact `102`, `blend_share` di luar `[0, 1]`, nilai `NaN`/`Inf` mentah di JSON, `flux_err_uJy < 0`, atau kurang dari `3` pita bernilai finit (`non-null`). | Pastikan array spektrum berjumlah `102` elemen, gunakan `null` untuk pita rusak/kosong (bukan `NaN`/string), `flux_err_uJy >= 0`, dan minimal 3 pita finit. |
| `test_b4_methane_benchmark_measured` gagal pada `pytest` | Kegagalan pra-eksis di `test_tier_b_slice3.py:61` (`b4["t_dwarf_total"] = 2 < 5`), sekaligus pada laporan Proof v2 preset *methane dip* (`B4 FAIL`) menghasilkan 17,34% *false match* pada tetangga lapangan (`> 1%`). | Kondisi data/metrik terukur pra-eksis yang didokumentasikan jujur di [`proof/report.md`](../proof/report.md) (bukan bug skrip instalasi). |
| Query langsung IRSA / SkyBoT gagal atau timeout | Jaringan memblokir host eksternal, IRSA sibuk, atau berada di sandbox tanpa akses jaringan. | Gunakan jalur data lokal/offline (`live=false`, tombol bidang `W1925`/`RW Aurigae`, serta target benchmark Hour-0) dan uji host lewat `bash scripts/check-network.sh`. |
