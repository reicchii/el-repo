# Technical Architecture - Phantom Worlds

## 1. Technology Stack
*   **Frontend (`phantom_worlds/static/`):** Zero-dependency HTML5 Canvas time-series viewer (`index.html`, `viewer.js`, `fallback_data.js`, `styles.css` served from `/` with strict CSP that relaxes `frame-ancestors` only for `?embed=1`) supporting visit blink playback, visit stacks, difference imaging (`V3−V1` / `V2−V1`), RGB composites, URL `?coord=...&fov=...&embed=1` parameters, on-the-fly 102-band spectra + Layer-1 molecule readings, Gaia DR3 overlays, and static Hour-0 cutouts (`hour0_contracts/targets/TGT-01..05`) + offline fallback across all 5 mandatory targets.
*   **Backend & API (Adit):** Python 3.13+, FastAPI (`phantom_worlds/api.py`, `contracts.py`, `ml_pipeline.py`) exposing calibrated patch timeseries (`/api/patch/timeseries`), arbitrary sky-coordinate queries (`/api/sky/timeseries` supporting HMS/DMS, decimal RA/Dec, or target names with optional live IRSA SIAv2 query), and strict Pydantic validation.
*   **Data Engineering (Akbar):** `pyvo`, `requests`, `pandas` (`download_real_spherex_gaia.py`), `numpy` (`contracts.py`), `astropy` (time/table tests). Direct public AWS S3 reads use standard HTTPS Range GETs (neither `s3fs` nor `boto3` is required).
*   **Machine Learning (Adit):** `scikit-learn` (`HistGradientBoostingClassifier`, OOF `LogisticRegression`, held-out `IsotonicRegression`, `IsolationForest` + `numpy` split conformal prediction; `xgboost` remains an optional unbundled Tier B benchmark).

## 2. SPHEREx Data Access & Ingestion Architecture
*   **Implemented (Observed Archive Pipeline):**
    1. **IRSA SIAv2 & ObsCore TAP Discovery:** `query_irsa_spherex_sia` queries IRSA SIAv2 across SPHEREx collections (`spherex_dr1`, `spherex_qr3`, `spherex_dr1_deep`, `spherex_qr3_deep`, `spherex_dr1_cube`) with normalized `spherex.obscore` TAP fallback onto a unified canonical schema (`SPHEREX_CANONICAL_COLUMNS`) carrying `cloud_access` JSON metadata for AWS S3 (`nasa-irsa-spherex`, `us-east-1`).
    2. **Direct Public S3 Layout (Observed MEF):** Level-2 FITS files are Multi-Extension FITS (MEF, ~65.8 MB per file; Primary HDU `NAXIS=0` + `EXTEND=True`, followed by `2040x2040` `float32` `IMAGE` extension plus `FLAGS`/`VARIANCE` extensions) serving anonymous HTTPS `Accept-Ranges: bytes`.
    3. **Validated Byte-Range Access:** `resolve_s3_url_from_cloud_access` and `http_range_read_fits_tile` enforce explicit IRSA/S3 HTTPS allowlists and safe `<= 64 MiB` byte bounds.
    4. **Single-Source Contract Sync:** `python -m phantom_worlds.contracts` (`sync_hour0_contracts`) regenerates `hour0_contracts/sources.json` from canonical `csv_tables/` and `csv_tables/ml_cases_output.csv` from `hour0_contracts/cases.json`.
*   **Planned (Not Yet Implemented):** Automated MEF header/HDU byte-offset WCS cutout slicing and concurrent async S3 Range readers (any `48x` / high-concurrency speedup remains an unbenchmarked design target).

## 3. Data Flow Diagram
```text
[User Browser] (RA/Dec input or Hour-0 Patch Selection)
      |
      v
[FastAPI Backend] --> Serves frozen Hour-0 packs / calibrated stacks (fallback ready)
      |
      +-- [Data Ingestion (Akbar)] --> IRSA SIAv2/TAP (`cloud_access`) -> S3 HTTPS Range GETs
      |                                Gaia DR3 mirrors (ESA / IRSA / ARI) -> J2000 PM propagation
      |                                Generates `pack.bin`, `mask.bin`, `manifest.json`
      |                                `sync_hour0_contracts` keeps JSON <-> CSV synchronized
      |
      v
[ML Pipeline (Adit)]
  - Layer 1: Quality masking (`mask.bin`) + 102-band continuum/optical-depth readings & refusals
  - Layer 2/3: M1 ghost gate + E1/E2 multi-expert combiner + M3 anomaly flags -> `cases.json`
      |
      v
[User Browser] <-- Receives JSONs + calibrated `pack.bin` / `mask.bin`. Renders UI & packets.
```
