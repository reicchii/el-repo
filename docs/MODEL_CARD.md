# Model Card & Detail Teknis ML — Phantom Worlds

Dokumen ini merangkum seluruh artefak model terlatih, arsitektur algoritma, format input, label kelas, hasil evaluasi terverifikasi, serta batasan ilmiah dan keamanan pada sistem Machine Learning **Phantom Worlds** (NASA Space Apps Challenge 2026 — Challenge 12, *"Planet X and SPHEREx"*).

> [!NOTE]
> Seluruh angka, nama berkas, hash SHA-256, dan metrik di dokumen ini diambil langsung dari artefak nyata pada repositori (`ml/spectral_discovery_pipeline.meta.json`, `ml/dataset_manifest.json`, `ml/evaluation_report.json`, `ml/model_card.md`, `proof/report.json`, serta kode sumber `phantom_worlds/ml_pipeline.py` dan `phantom_worlds/tier_b_detectors.py`) per `2026-11-15T06:54:10Z`. Ringkasan otomatis versi bahasa Inggris juga tersedia di [`ml/model_card.md`](../ml/model_card.md).

---

## 1. Daftar Artefak Model & Dataset

Semua model berjalan penuh di **CPU** menggunakan `scikit-learn==1.9.0` dan `numpy==2.5.1` tanpa memerlukan GPU atau CUDA.

| Artefak / Lokasi | Ukuran / Format | Peran & Cara Pemuatan |
|---|---|---|
| [`ml/spectral_discovery_pipeline.pkl.gz`](../ml/spectral_discovery_pipeline.pkl.gz) | `1,844,039` byte (~1,76 MiB), Gzip + Python `pickle` (`HIGHEST_PROTOCOL`) | Checkpoint terkompresi berisi `SpectralDiscoveryPipeline` (`spherex-dr1-e1e2-v2`) dan kamus `e1_templates` (14 template × 6 kelas). Dimuat otomatis oleh backend via `load_pipeline_checkpoint()` / `get_cached_ml_pipeline()`. |
| [`ml/spectral_discovery_pipeline.meta.json`](../ml/spectral_discovery_pipeline.meta.json) | `620` byte, JSON | Sidecar integritas yang menyimpan `model_version`, `checkpoint_sha256`, `dataset_sha256`, `code_sha256`, `max_per_class`, `random_state`, serta pin versi `sklearn_version` & `numpy_version`. |
| [`ml/real_training_dataset.npz`](../ml/real_training_dataset.npz) | `1,316,379` byte, ZIP/NPZ NumPy | Dataset latih/kalibrasi/uji nyata (`763` spektra 102 pita dari SPHEREx DR1 + SPIFF + SPLICES + Gaia/SIMBAD/ALLWISE, termasuk `47` template hibrida SPIFF dan 5 spektra benchmark). |
| [`ml/dataset_manifest.json`](../ml/dataset_manifest.json) | `1,397` byte, JSON | Ringkasan komposisi `gold`/`silver` dan jumlah petak langit unik (`unique_h8_tiles`) untuk tiap kelas pada dataset `.npz`. |
| [`ml/evaluation_report.json`](../ml/evaluation_report.json) | `12,009` byte, JSON | Laporan evaluasi lengkap (Release Gate, bin magnitudo W2, diagnostik 6 kelas, UCD Level-2, Input Ladder R1–R5, Cross-Extraction, dan 5 target uji tetap). |
| [`ml/model_card.md`](../ml/model_card.md) | `3,809` byte, Markdown | Model card terformat yang dihasilkan otomatis oleh [`ml/train.py`](../ml/train.py). |
| **Model M1 In-Memory** (`phantom_worlds/tier_b_detectors.py`) | Dihitung di RAM saat startup / analisis (`m1-rf-tierb-v1`) | `RandomForestClassifier(n_estimators=160, max_depth=8, min_samples_leaf=2)` untuk diskriminasi kandidat nyata vs artefak (halo bintang terang, crosstalk 64-px H2RG, ghost optik, kosmik 1-px/linear) dengan `12` fitur morfologi PSF pada ambang `<= 1%` FPR. Tidak diekspor ke `.pkl.gz`. |

### Provenance & Checksum Checkpoint (`ml/spectral_discovery_pipeline.meta.json`)

- **`model_version`:** `spherex-dr1-e1e2-v2`
- **`pipeline_version`:** `phantom-ml-tierb` (ML) / `0.3.0-tierb` (Engine & Proof v2)
- **`data_as_of`:** `2026-11-15T06:51:06Z`
- **`release_status`:** `PUBLISHED`
- **`checkpoint_sha256`:** `bcbe95a85020a0288e7f7c45424e957019ca2b165bbe94b049203b3e7ebdf89d`
- **`dataset_sha256`:** `2de6d2bd822725c08f741b79079487859c29a82ae56f2dcad458589ead0c6221`
- **`code_sha256.ml_pipeline.py`:** `e5eb5dd30cda93e9fd5e974a72f261fd34cef9e3eecfb4acdf653885a7031887`
- **`code_sha256.real_ml_data.py`:** `f223972bae7871051b3622418f1204db61ce9f45c263a53208f6d2260b4dfc32`
- **`max_per_class`:** `14` | **`random_state`:** `42` | **`sklearn_version`:** `1.9.0` | **`numpy_version`:** `2.5.1`

---

## 2. Arsitektur Model & Alur Sains (`SpectralDiscoveryPipeline`)

Kode utama berada pada kelas [`SpectralDiscoveryPipeline`](../phantom_worlds/ml_pipeline.py) yang menyusun 3 lapisan inferensi secara berurutan tanpa kebocoran data (*zero-leakage* per petak langit HEALPix Order 8):

1. **Layer 1 — Pembacaan Molekul Fisik (`compute_molecule_readings`)**
   - Mengukur 4 pita es & molekul utama pada rentang inframerah SPHEREx: `H2O_ice_3_05`, `CH4_3_3`, `CO2_4_26`, dan `CO_4_67`.
   - Kontinum lokal dicocokkan dengan regresi linear (`deg=1`) di luar jendela penyerapan (`CONTINUUM_WINDOWS`, atau `CO_SHOULDER_WINDOWS` khusus `CO_4_67`), lalu menghitung `integrated_tau`, `column_density_cm2`, `rel_to_h2o_ice_pct`, serta ketidakpastian `p16` / `p50` / `p84` melalui 200 draw Monte Carlo.
   - **Aturan Penolakan Ketat (`status: "REFUSED"`):** Pengukuran kedalaman optik dan densitas kolom ditolak otomatis dengan alasan eksplisit apabila `is_variable=True`, `blend_share > 0.3`, atau cakupan `< 3` pita valid di jendela fitur.
2. **Layer 2a — Expert 1 (`E1`: Template $\chi^2_{\text{red}}$ + Cosine kNN)**
   - Membandingkan spektrum ternormalisasi dengan `14` varian template per kelas (total 84 template yang dibentuk hanya dari subset `train_core` plus 47 template hibrida SPIFF untuk `Ultracool dwarf`) via `_reduced_chi2` dengan penalti cakupan untuk spektrum yang terpotong gap.
   - Skor jarak template digabung dengan `KNeighborsClassifier(n_neighbors<=9, metric="cosine", weights="distance")` dengan bobot `e1_knn_weight=0.12`.
3. **Layer 2b — Expert 2 (`E2`: NaN-Native `HistGradientBoostingClassifier`)**
   - Hyperparameter: `max_iter=150`, `max_depth=5`, `min_samples_leaf=4`, `l2_regularization=0.8`, `max_features=0.25`, `learning_rate=0.05`, `class_weight="balanced"`.
   - **Ekstraksi Fitur (`_extract_features` / `_spectral_colors`):** Spektrum fluks diurutkan berdasarkan panjang gelombang dan diubah menjadi `log(flux)`. Celah sempit (`<= 3` pita hilang) dijembatani secara linear (`_bridge_narrow_log_gaps`). Untuk vektor panjang `n=102`, dibangun `84` perbedaan warna spektral lebar (`log_fl[k:] - log_fl[:n-k]`, `k = min(18, n // 4) = 18`) ditambah `18` fitur lokal: level median relatif 6 pita detektor SPHEREx (`D1`–`D6`), kemiringan NIR/MIR & indeks serapan fisik CO/H2O/CH4, serta kekuatan fitur 4 molekul terhadap kontinum (`total = 102` fitur).
   - **Augmentasi Gap Detektor:** Saat pelatihan, `_augment_masked_training` menyimulasikan blok detektor `NaN` dan masker tepi/tengah berbobot `0.50x`, sedangkan label `silver` diberi bobot sampel `0.5x`.
4. **Layer 2c — Expert 4 (`E4`: Gerbang Paralaks Gaia)**
   - Bila `parallax_snr > 5.0` diberikan, cabang `all_data` menerapkan gerbang prior fisik (*parallax gate*) untuk menaikkan probabilitas kelas bintang dekat dan menekan kelas ekstragalaktik (`Galaxy`, `Active galaxy or quasar`).
5. **Layer 3 — Stacking, Kalibrasi, Conformal, Konsistensi, & Kebaruan (`M3`)**
   - **Meta-Combiner:** Out-of-fold `LogisticRegression(C=5.0)` menggabungkan matriks probabilitas `E1` (6 kelas) dan `E2` (6 kelas).
   - **Kalibrasi & Conformal:** Probabilitas mentah dikalibrasi oleh `IsotonicRegression` per kelas pada split `isotonic` (`91` spektra), lalu disesuaikan dengan `_PowerCalibrator` (`temperature_inv = 1.2`, terklip pada `[0.65, 1.20]`). Set conformal prediktif 90% dihitung menggunakan split `conformal` (`86` spektra) dengan kuantil terukur `conformal_q = 0.9153`.
   - **Aturan Ketidaksepakatan (`Unclassified <= 0.50`):** Jika kelas puncak `E1` (`template_class`) berbeda dengan `E2` (`tree_class`), output `top_class` dipaksa menjadi **`Unclassified`** dengan probabilitas tertinggi dibatasi **`<= 0.50`**.
   - **Deteksi Kebaruan (`M3`):** Sebelum memanggil `IsolationForest(contamination=0.05)`, objek yang memiliki `is_variable=True` atau `has_masked_pixels=True` disaring terlebih dahulu sebagai `CONTAMINATION_SCREENED`.
6. **Regresor Subtipe UCD Level-2 (`predict_ucd_subtype`)**
   - Menggunakan `HistGradientBoostingRegressor` yang dilatih pada objek `Ultracool dwarf` dengan label subtipe SPIFF untuk memperkirakan `spectral_index` numerik dan label spektral (`M*`, `L*`, `T*`, `Y*`).

---

## 3. Spesifikasi Input & Label Kelas

### Format & Dimensi Input Model

| Konteks Pemanggilan | Dimensi & Panjang Gelombang | Satuan & Penanganan Nilai Hilang | Parameter Konteks Tambahan |
|---|---|---|---|
| **Inferensi Langsung Python** (`SpectralDiscoveryPipeline.predict_one`) | `flux` 1D panjang **`102`** pada grid `SPECTRAL_CHANNELS` kubus DR1: **`0.753` – `4.988` μm** | Satuan fluks spektral **`uJy`** (`float64`). Nilai `NaN` / non-positif diperbolehkan untuk pita rusak/kosong; minimal **`>= 3`** pita bernilai finit positif. | `flux_err` (`102`, opsional), `blend_share` (`float`, default `0.0`), `is_variable` (`bool`, default `False`), `has_masked_pixels` (`bool`), `parallax_snr` (`float`, default `0.0`). |
| **HTTP Endpoint** (`POST /api/analyze/spectrum`) | Array `flux_uJy` panjang **exact `102`** pada grid referensi API **`0.7603` – `4.9824` μm** | Elemen bertipe `float \| null` (satuan **`uJy`**). Backend meresampling otomatis ke grid model `0.753–4.988` μm via `_align_spectrum_to_model_grid` dan menghitung `has_masked_pixels` otomatis dari elemen `null`/`NaN` (minimal `>= 3` pita finit). | `flux_err_uJy` (opsional, `102` float/null), `blend_share` (`0.0..1.0`, default `0.0`), `is_variable` (`bool`, default `false`), `parallax_snr` (`float \| null`, default `null`). |
| **Model M1 Artefak (`tier_b_detectors.py`)** | Vektor 1D panjang **`12`** (`_build_m1_feature_vector`) | Fitur skalar float bersih (dihasilkan internal saat analisis bidang langit `W1925` & `rwaur`) | `snr`, `psf_corr`, `frac_1px`, `conc_3x3_5x5`, `elongation`, `frac_masked_3x3`, `n_visits_det`, `n_dets_det`, `min_sat_or_bright_px`, `spike_axis_score`, `ghost_xtalk_score`, `edge_px_dist`. |

### Daftar Label Kelas & Komposisi Dataset (`763` Spektra)

Total `763` spektra dipartisi dengan pemisahan petak langit **HEALPix Order 8 (`nside=256`, ~0,23°)** tanpa irisan antar-split (`strict_tile_disjointness: true`):
- `train_core`: **`431`** spektra | `isotonic`: **`91`** spektra | `conformal`: **`86`** spektra | `test_all_classes`: **`155`** spektra (subset test berlabel Gold `test_gold`: **`99`** spektra, terdiri atas `93` ber-`W2 <= 14` dan `6` ber-`W2 > 14`).

| Label Kelas (`classes`) | Total | Gold | Silver (Bobot `0.5x`) | Petak HEALPix-8 Unik | Support Test (`test_all_classes=155`) |
|---|---:|---:|---:|---:|---:|
| `Ultracool dwarf` | 200 | 200 | 0 | 200 | 40 |
| `Young star with ice or dust` | 194 | 185 | 9 | 53 | 43 |
| `Evolved giant star` | 139 | 0 | 139 | 130 | 27 |
| `Galaxy` | 86 | 0 | 86 | 85 | 18 |
| `Active galaxy or quasar` | 85 | 85 | 0 | 85 | 17 |
| `Star` | 59 | 0 | 59 | 50 | 10 |
| **`Unclassified`** *(label penolakan)* | — | — | — | — | Dikeluarkan otomatis bila `E1 != E2` (`confidence <= 0.50`) |

---

## 4. Hasil Evaluasi Terverifikasi

### A. Release Gate Utama — Gold High-S/N (`W2 <= 14`, `n = 93`)

Status gerbang rilis dari `ml/evaluation_report.json`: **`PUBLISHED`** (seluruh metrik Gold `W2 <= 14` lolos ambang batas).

| Metrik Release Gate | Nilai Terukur | Syarat Ambang | Status |
|---|---:|---:|---|
| Jumlah sampel uji Gold (`W2 <= 14`) | `93` (`0` Silver) | Gold only | — |
| Minimum Per-Class Recall | **`0.9048`** (`Active galaxy or quasar`: `1.0000`, `Ultracool dwarf`: `0.9706`, `Young star with ice or dust`: `0.9048`) | `>= 0.80` | **PASS** |
| Expected Calibration Error (`ECE`) | **`0.0304`** | `<= 0.05` | **PASS** |
| Cakupan Set Conformal (`conformal_q = 0.9153`) | **`0.9785`** (97,85%) | `>= 0.88` | **PASS** |

#### Evaluasi per Bin Magnitudo `W2`

| Bin Magnitudo `W2` | Jumlah (`n`) | Min Recall | ECE | Conformal Coverage | Status Bin |
|---|---:|---:|---:|---:|---|
| `W2 <= 12` | 65 | 0.8889 | 0.0431 | 0.9692 | `True` (PASS) |
| `12 < W2 <= 13` | 14 | 1.0000 | 0.0051 | 1.0000 | `True` (PASS) |
| `13 < W2 <= 14` | 14 | 1.0000 | 0.0353 | 1.0000 | `True` (PASS) |
| `W2 > 14` *(redup, di luar gerbang `W2 <= 14`)* | 6 (`Ultracool dwarf` saja) | 0.8333 | 0.1148 | 1.0000 | `False` (`ECE > 0.05`) |

---

### B. Diagnostik Uji Held-Out 6 Kelas (Gold + Silver, `n = 155`)

- **Akurasi Gabungan (`spectrum_alone`):** **`0.8968`** (89,68%) | **E1 Saja (`template`):** **`0.9161`** | **E2 Saja (`tree`):** **`0.9419`** | **Tingkat Kesepakatan E1 & E2:** **`0.9355`** (93,55%).

| Kelas | Support | Combined Recall | E1 Recall | E2 Recall | Unclassified Rate | Conformal Coverage |
|---|---:|---:|---:|---:|---:|---:|
| `Active galaxy or quasar` | 17 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| `Ultracool dwarf` | 40 | 0.9500 | 0.9750 | 0.9500 | 0.0250 | 0.9750 |
| `Young star with ice or dust` | 43 | 0.9070 | 0.9070 | 0.9535 | 0.0465 | 0.9767 |
| `Star` *(silver)* | 10 | 0.9000 | 1.0000 | 1.0000 | 0.1000 | 1.0000 |
| `Galaxy` *(silver)* | 18 | 0.8889 | 0.9444 | 0.8889 | 0.0556 | 0.8889 |
| `Evolved giant star` *(silver)* | 27 | 0.7407 | 0.7407 | 0.8889 | 0.2222 | 0.8519 |

---

### C. Evaluasi Khusus Tier B: Subtipe UCD, Cross-Extraction, Input Ladder & Target Tetap

1. **Prediksi Subtipe Ultracool Dwarf (`ucd_subtype_evaluation`, `n = 40`):**
   - Akurasi dalam `<= 2` subtipe: **`0.875`** (87,5%, ambang `>= 0.80` -> **PASS**)
   - `mad_subtypes`: **`0.54`** | `mae_subtypes`: **`0.8758`**
2. **Cross-Extraction Ratio (`cross_extraction_ratio`, S3 Cube vs SPIFF Ref):**
   - Jumlah objek cocok: **`60`** sumber | Pita valid: **`92`** pita
   - Deviasi absolut maksimum median rasio per pita: **`0.0797`** (ambang `<= 0.10` -> **PASS**)
3. **Tangga Fitur Input (`input_ladder` — Proof `B13`):**

| Rung Fitur Input | Jumlah Fitur | Akurasi Test Semua Kelas (`n=155`) | Akurasi Test Gold (`n=99`) |
|---|---:|---:|---:|
| `rung1_e0_molecules_only` | 4 | 0.5226 | 0.5960 |
| `rung2_stage10_band_features` | 12 | 0.9097 | 0.9192 |
| `rung3_all_102_bands` | 90 | 0.9097 | 0.9192 |
| `rung4_bands_plus_stage10_spectrum_alone` | 102 | 0.8968 | 0.9394 |
| `rung5_all_data_with_gaia_parallax` (`parallax` terukur `0.0645`) | 102 | 0.8968 | 0.9394 |

4. **5 Target Benchmark NASA Tetap (`fixed_targets_cube` vs `fixed_targets_reference`):**

| Target Slug | Prediksi S3 Cube | Status Molekul Cube | Prediksi Ref 102-Band | Status Molekul Ref |
|---|---|---|---|---|
| `Barnards_Star` | `Unclassified` *(saturasi/crowding di kubus kasar S3)* | `REFUSED` | `Star` (`PASS`) | `MEASURED` (`ch4_tau = -6.42`) |
| `Eps_Indi_B` | `Ultracool dwarf` (`PASS`) | `MEASURED` (`ch4_tau = 487.66`) | `Ultracool dwarf` (`PASS`) | `MEASURED` (`ch4_tau = 1043.99`) |
| `WISE_0855` | `Unclassified` | `MEASURED` (`ch4_tau = 44.53`) | `Unclassified` (`PASS`) | `MEASURED` (`ch4_tau = 1000.76`) |
| `RW_Aurigae` | `Ultracool dwarf` | `REFUSED` *(variabel)* | `Unclassified` (`PASS`) | `REFUSED` *(variabel)* |
| `R_Draconis` | `Unclassified` (`PASS`) | `REFUSED` *(variabel)* | `Star` | `REFUSED` *(variabel)* |

---

### D. Ringkasan Proof v2 Sistem Penuh (`proof/report.json`, `2026-11-15T06:54:10Z`)

Total uji Tier B: **`10 PASS, 3 FAIL, 0 NOT_MEASURED`** (`13` uji, `pipeline_version: 0.3.0-tierb`, `182` total kasus di `cases_summary`).

- **Lulus (`PASS`):**
  - `B2`: Fotometri deblended bidang ramai Galactic Plane `W1925` (`blend < 0.3`): scatter `19.24% <= 20%` (`n=47`).
  - `B3`: Pemulihan moving PSF sintetis pada background nyata `rwaur` D3: `80.0%` (`8/10 >= 80%`).
  - `B5`: Gerbang rilis Type Model Gold `W2 <= 14`: `min recall 0.9048`, `ECE 0.0304`, `coverage 0.9785` (`PUBLISHED`).
  - `B6`: Model M1 (`RandomForestClassifier`): `recall 0.9048` pada ambang false-positive `1%` (`score thresh 0.5`).
  - `B8`: Kedalaman injeksi-pemulihan bergerak (`0.03–8.0"/hr`): 90%/50% `RW Aur` D3 `13.5/17.25`, D6 `13.5/15.91` AB mag; `W1925` D3 `14.5/15.05`, D6 `15.5/15.94` AB mag.
  - `B9`: Upaya deteksi `19.0 AB mag` di regime Galactic Plane (`SMDET-1`): terukur `0.0%` (`detected=False`, sesuai harapan jujur).
  - `B10`: Tingkat false-flag pemeriksaan tepi pita pada bintang stabil: `0.0%` (`0/19 <= 1%`).
  - `B11`: Subtipe UCD Level-2: `87.5%` dalam 2 subtipe (`MAD 0.54`, `n=40`).
  - `B12`: Cross-extraction rasio S3 cube vs SPIFF: deviasi maks `0.0797 <= 0.10` (`n=60`).
  - `B13`: Input ladder R1–R5 terukur penuh pada test split terisolasi petak langit.
- **Belum Lulus (`FAIL`) — Tercatat Jujur Tanpa Pelonggaran Ambang:**
  - `B1` (`RW Aurigae`): Synthetic `Ks` vs 2MASS menghasilkan median `3.5%`, tetapi scatter **`10.62%`** sedikit melewati batas `<= 10%` (`n=7`).
  - `B4` (*Methane dip preset*): Recall T-dwarf benchmark `100.0% (2/2)`, namun tingkat kecocokan palsu tetangga lapangan mencapai **`17.34% (128/738)`** melewati batas `<= 1%` (dan di `test_tier_b_slice3.py`, uji `test_b4_methane_benchmark_measured` gagal pada assertion `t_dwarf_total = 2 < 5`).
  - `B7` (*Retro motion check*): Hanya `1/3` target bergerak lolos keseluruhan (`TGT-03 Epsilon Indi B` lolos `2.18" <= 3.25"`; `TGT-01 Barnard's Star` gagal karena saturasi inti di Level-2; `TGT-02 WISE 0855` tidak terdeteksi `S/N -1.48` di frame D6 kunjungan V3).

---

## 5. Batasan Ilmiah, Kejujuran Bahasa & Keamanan Model

1. **Kejujuran Istilah (Wajib Dipertahankan di UI & API):**
   - Setiap output model adalah **estimasi (`estimate`)** untuk memprioritaskan tinjauan manusia — **jangan pernah** melabelinya sebagai *"confirmed"*, *"discovered"*, atau *"verified"*.
   - Pembacaan molekul melaporkan kekuatan fitur & kedalaman optik terintegrasi (`integrated_tau`). Persentase komposisi hanya ditampilkan untuk spesies es terhadap es air (`rel_to_h2o_ice_pct`).
   - Kelas `Star`, `Galaxy`, dan `Evolved giant star` mengandalkan label cross-match `silver` berbobot `0.5x` dan dikecualikan dari gerbang rilis Gold.
2. **Keterbatasan Resolusi Spasial & Kedalaman:**
   - Kubus all-sky S3 HiPS Order 5 memiliki ukuran piksel `~13.98"/px` (~2,25× lebih kasar dari Level-2 `~6.2"/px`), sehingga objek redup/berdekatan di bidang ramai atau bintang sangat terang (`D1`–`D4` pada Barnard's Star / R Draconis) rentan mengalami *blending* atau saturasi.
   - Setiap potongan SPHEREx mencakup `6.56'` (`394"`); planet jauh (~500 AU) bergeser ~800" (~130 px) dalam 6 bulan akibat paralaks, melebihi satu potongan tunggal kecuali dihubungkan lintas-petak (*cross-tile*).
3. **Batas Keamanan Distribusi & Deserialisasi (`pickle`):**
   - **Peringatan Keamanan:** Berkas [`ml/spectral_discovery_pipeline.pkl.gz`](../ml/spectral_discovery_pipeline.pkl.gz) disimpan menggunakan format Python `pickle` terkompresi `gzip`. Secara fundamental, `pickle` dapat mengeksekusi kode arbitrer jika seseorang memanipulasi muatan `.pkl.gz` dari sumber yang tidak dipercaya.
   - **Mitigasi Lokal:** `load_pipeline_checkpoint()` memvalidasi kesesuaian `model_version`, `max_per_class`, `random_state`, `sklearn_version == 1.9.0`, `numpy_version == 2.5.1`, hash sumber `code_sha256` + `dataset_sha256`, serta verifikasi konstan waktu `hmac.compare_digest` terhadap `checkpoint_sha256` dari sidecar [`ml/spectral_discovery_pipeline.meta.json`](../ml/spectral_discovery_pipeline.meta.json) dan penjagaan direktori `os.path.commonpath` sebelum memanggil `pickle.loads`.
   - **Rekomendasi Publikasi ke Pengguna Akhir:** Jangan mendistribusikan file `.pkl.gz` sebagai paket eksekusi terbuka untuk pengguna yang tidak memahami risiko versi/keamanan `pickle`. Ekspos layanan prediksi publik melalui endpoint HTTP FastAPI (`POST /api/analyze/spectrum` & antarmuka Web UI) atau sertakan selalu verifikasi hash SHA-256 + lingkungan `requirements.lock` untuk pemakaian riset lokal yang terkontrol.
