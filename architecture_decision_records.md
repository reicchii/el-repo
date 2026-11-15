# Architecture Decision Records (ADR)

## ADR 001: IRSA SIAv2/TAP Metadata Discovery + Direct Public S3 HTTP Range Reads

* **Context:** NASA points users to IRSA services, where bulk IRSA cutout queues bottleneck concurrent requests. Querying IRSA SIAv2/TAP returns both direct IRSA IBE FITS URLs and public AWS Open Data pointers (`cloud_access` for bucket `nasa-irsa-spherex`, region `us-east-1`). Observed SPHEREx Level-2 FITS files are Multi-Extension FITS (MEF, ~65.8 MB, Primary HDU `NAXIS=0` followed by `IMAGE` `2040x2040` `float32` plus `FLAGS`/`VARIANCE` HDUs) that support anonymous HTTPS `Accept-Ranges: bytes` (HTTP 206).

* **Decision:** Discover frame footprints via IRSA SIAv2/TAP (`download_real_spherex_gaia.py`), resolve `cloud_access` pointers to validated HTTPS S3 URLs (`resolve_s3_url_from_cloud_access`), and fetch localized headers/byte ranges via HTTP 206 (`http_range_read_fits_tile`) without `boto3` credentials. Offline/demo reliability continues to rely on static Hour-0 packs (`ADR 003`).

* **Consequences:**

  * *Implemented:* Authenticated-free IRSA SIAv2/TAP catalog discovery, validated HTTPS S3 URL resolution from `cloud_access`, and guarded HTTP 206 single-range fetching (`<= 64 MiB`).

  * *Planned (Not Yet Implemented):* Automated MEF header/HDU byte-offset WCS slicer and concurrent async range readers (any `48x` / `~0.25s` speedup claim remains an unbenchmarked design goal until implemented and measured).

## ADR 002: Tabular Boosted Trees (`scikit-learn HistGradientBoostingClassifier`) vs. Deep Learning for M1/M2

* **Context:** We need to classify 102-band spectral arrays with NaN-masked detector gaps while keeping dependencies lightweight (`requirements.txt` excludes `xgboost`, `lightgbm`, and `shap`). Deep learning (CNNs/Transformers) requires larger curated training sets.

* **Decision:** Implement the active Hour-0 tree branch (`E2`) using **`scikit-learn`'s NaN-native `HistGradientBoostingClassifier`** paired with analytical template reduced-$\chi^2$ (`E1`), a `parallax_snr > 5.0` physical gate (`E4`), out-of-fold `LogisticRegression` stacking, held-out `IsotonicRegression`, 90% split conformal prediction sets, and `IsolationForest` (`M3` after contamination screening) inside `phantom_worlds/ml_pipeline.py`. Keep `XGBoost`/`LightGBM`/`SHAP` and runtime `deciding_bands` / trained `M1` ghost classifiers as optional Tier B enhancements.

* **Consequences:**

  * *Implemented:* Zero extra binary ML wheels beyond `scikit-learn`; handles `NaN`-masked bands natively without zero-imputation; enforces calibration and agreement caps cleanly.

  * *Planned / Trade-off:* Standalone trained `M1` `p_real` classifier, runtime per-object `deciding_bands` feature attributions, and multi-benchmark `XGBoost` comparisons (`ml-research.md` §13.2) remain Tier B work.

## ADR 003: Static Data Fallback (The "Zero-Downtime" Demo)

* **Context:** Live demos during hackathons often fail due to server crashes or API rate limits.

* **Decision:** The frontend must be able to run offline using pre-packaged mock data for the 5 NASA targets (compiled by Tata on Saturday 09:00).

* **Consequences:** If the backend API crashes during judging, the static frontend hosted on Cloudflare will still perfectly demonstrate the 5 mandatory targets.

## ADR 004: Strict Sub-Pixel Alignment via Gaia DR3

* **Context:** Targets like Barnard's Star move \~1.7 pixels/year. SPHEREx pixels are huge (6.15 arcseconds).

* **Decision:** We will mandate Gaia DR3 registration. Every frame will be upsampled and aligned to Gaia with an error limit of $\le$ 1.0 arcsecond.

* **Consequences:** Essential for the "Difference Dipoles" feature to work without generating false motion artifacts.

---

### ADR 005: Verification Ledger for Research & External Dependency Checks (K18–K28)
* **Date:** 2026-11-14
* **Context:** `phantom-worlds-ml-research.md` accumulated open verification items (`K18–K28`) and inline unresolved markers while referencing unbundled early sprint planning notes.
* **Decision (Verified vs Deferred Triage):** Record every empirically checked item here and defer only unexecuted heavy multi-tile runtime benchmarks explicitly to Tier B:
  * **K18 (`VERIFIED`):** Zenodo record `10.5281/zenodo.19051216` (`SPIFF`) contains 17 payload files (~6.3 GB incl. `00_README.txt`, `spiff_zenodo_manifest.csv`, `spiff_templates_hybrid_csv.zip` with 47 members / 79.4 KB, and `spiff_tables.zip`); Zenodo data license is `CC-BY-4.0`, and `github.com/jgagneastro/SPIFF` code license is `MIT`.
  * **K19 (`OPEN — Tier B`):** arXiv `2604.26771` (`SUDA`, 1,675 ultracool dwarfs, 57 templates, 700–3,000 K) and `2609.02167` (14 NMF galaxy/AGN templates) are confirmed on arXiv; direct VizieR/Zenodo downloadable table URLs remain to be pulled prior to Tier B template ingestion.
  * **K20 (`PARTIAL`):** IRSA `splices_colDescriptions.html` confirms `STYPE_ML` (`char`: Machine Learning Source Class), `STYPE_ML_PROB1` (`double`: Stage 1), and `STYPE_ML_PROB2` (`double`: Stage 2); live IRSA TAP query for distinct `STYPE_ML` enum values timed out at 20s and remains queued.
  * **K21 (`VERIFIED`):** IRSA Spectrophotometry Tool docs (`sp.html`) document a limit of **20 sources per run**, **2 concurrent jobs max**, and runtime `1.67 * N_images + 50` s (`0.000463 * N_images + 0.013` hr), with no batch REST API; bulk extraction (>20 sources) uses IRSA SIAv2 + S3 Level-2 cutouts.
  * **K22 (`OPEN — Tier B Benchmark`):** Comparing 50 sources between 300 MB all-sky cube tiles and per-frame forced photometry (release gate: median ratio within 10% per band) requires downloading multi-tile cubes at Tier B runtime.
  * **K23 (`VERIFIED Ref / Pending Constant Table`):** Gibb et al. (2004, *ApJS* 151, 35–73) defines `N = \int \tau_\nu d\nu / A` (~`2.0e-16` H2O 3.0 um, `1.0–1.2e-16` CO2 4.27 um, `1.1–1.7e-17 cm/molecule` CO 4.67 um); `phantom_worlds/ml_pipeline.py` emits optical depth `tau` only until exact ice-mixture $A$-values and LRS corrections are frozen.
  * **K24 (`VERIFIED Route`):** ESA Gaia DR3 TAP (`https://gea.esac.esa.int/tap-server/tap`, table `gaiadr3.gaia_source` with `classprob_dsc_combmod_*` and `has_xp_sampled`) plus DataLink/`xp_sampled_mean_spectrum` serve probabilities and low-res BP/RP spectra (rate-limited HTTP 429 on unauthenticated burst probe; IRSA TAP Gaia mirror succeeded cleanly for patch tables).
  * **K25 (`VERIFIED`):** TabPFN v2 supports up to **10,000 rows** and **500 features**; PyPI `tabpfn` code declares `Apache-2.0` and v2 weights carry Apache-2.0 with attribution, whereas v2.5+ weights have commercial restrictions.
  * **K26 (`VERIFIED`):** Published UCD subtype-to-$T_\text{eff}$ calibrations are Kirkpatrick et al. (2021) (L/T/Y 20-pc census) and Sanghi et al. (2023, *ApJ* 959, 63, M6–T9 polynomial relation), noting the ~1,100–1,300 K L/T transition plateau.
  * **K27 (`VERIFIED`):** Spectroscopic galaxy/quasar gold labels are queryable via IVOA TAP from **VizieR TAP** (`"VII/294/catalog"` / Milliquas v8) and **SDSS DR16Q/DR18** / **DESI** via VizieR or NOIRLab TAP.
  * **K28 (`VERIFIED`):** PyPI/GitHub checks show `xcavation` (`1.1.0`) = **MIT**, `SPIFF` code = **MIT** (data `CC-BY-4.0`), `mapie` (`1.6.0`, API changed vs `0.x`) = **BSD-3-Clause**, while `spxquery` (`0.4.1`) declares **no SPDX license metadata** on PyPI (`do NOT vendor/import` without repository license confirmation).
  * **Installed `scikit-learn 1.9.0` & Foundation Models (`VERIFIED`):** Local verification confirms `RandomForestClassifier` and `ExtraTreesClassifier` in `scikit-learn==1.9.0` support `NaN` natively; arXiv abstracts confirm `AION-1` (`2510.17960`) and `SpecCLIP` (`2507.01939`) exclude SPHEREx spectrophotometry.
* **Consequences:** All unbundled legacy planning note references are retired in favor of this workspace's real contracts, ADRs, and test suite.


### ADR 006: Tier-B Residual Engine, Real S3 Level-2 WCS Cutouts & Hash-Verified Pipeline Checkpoint

**Status**: Implemented (2026-11-15)  
**Supersedes**: Planned status notes in ADR 001 (static S/N cutout note) and ADR 002 (Tier-B M1/SPIFF/input-ladder roadmap items)

**Decision**:
1. Replace synthetic Tier-A placeholder patches with real SPHEREx S3 Level-2 WCS cutouts (`phantom_worlds/fits_cutout.py`) and implement the full Tier-B processing and verification stack across `phantom_worlds/tier_b_engine.py`, `phantom_worlds/tier_b_detectors.py`, `phantom_worlds/tier_b_proof.py`, and `proof/run.py`:
   - Crowded-field PSF subtraction using Gaia DR3 + 2MASS + CatWISE2020 positions propagated to frame epochs (`W1925` Galactic Plane and `RW Aurigae` off-plane fields).
   - Multi-band mover/leftover detection with H2RG mirrored crosstalk and quadrant optical-ghost vetting, paired with an in-memory calibrated `RandomForestClassifier` (`M1`, 160 trees, passing Proof B6 at `0.9048` recall @ 1% FPR).
   - Spectral discovery dataset (`ml/real_training_dataset.npz`, `763` SPHEREx DR1 + SPIFF + SPLICES + Gaia/SIMBAD/ALLWISE spectra, including `47` SPIFF ultracool dwarf hybrid templates), Tier-B UCD Level-2 subtyping (`B11`), S3-vs-SPIFF cross-extraction check (`B12`), Input Ladder Rungs 1–5 (`B13`), and Proof v2 report generation (`proof/report.json`, `proof/report.md`: `10 PASS, 3 FAIL, 0 NOT_MEASURED`).
2. Persist the trained Layer 1–3 spectral ensemble (`SpectralDiscoveryPipeline` + `e1_templates`) from `ml/train.py` to `ml/spectral_discovery_pipeline.pkl.gz` (`1,844,039` bytes) alongside a hash-verified metadata sidecar `ml/spectral_discovery_pipeline.meta.json` using Python stdlib `gzip` + `pickle` (`HIGHEST_PROTOCOL`) with atomic temp-file writes (`os.replace`) and `realpath`/`commonpath` containment checks.
3. Require `get_cached_ml_pipeline()` in `phantom_worlds/tier_b_detectors.py` (`load_pipeline_checkpoint`) to verify exact `model_version`, `max_per_class`, `random_state`, `sklearn_version`, `numpy_version`, source `code_sha256`, `dataset_sha256`, and `hmac.compare_digest` over `checkpoint_sha256` before calling `pickle.loads`, transparently falling back to `train_from_real_dataset` on mismatch or absence.

**Consequences**:
- Cold backend startup for ML inference drops from `~41.9s` (`live_fit`) to `~0.03s` (`disk_checkpoint`) without adding external serialization dependencies (`joblib`/`skops`) or triggering NumPy 2.5 `DeprecationWarning`s.
- Because Python `pickle` is unsafe against arbitrary untrusted payloads, checkpoints are scoped strictly to local verified builds matching pinned `scikit-learn==1.9.0` and `numpy==2.5.1`; public consumers must call the FastAPI HTTP endpoints rather than ingesting untrusted `.pkl.gz` files.
- See also the detailed Indonesian technical model card in [`docs/MODEL_CARD.md`](docs/MODEL_CARD.md), usage guide in [`docs/USAGE.md`](docs/USAGE.md), and chronological project decisions in [`docs/decisions.md`](docs/decisions.md).
