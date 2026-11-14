# System Specifications - Phantom Worlds

## 1. Data Sources & Archives
*   **Primary:** NASA/IPAC SPHEREx Level-2 archives (`spherex_dr1`, `spherex_qr3`, `spherex_dr1_deep`, `spherex_qr3_deep`, `spherex_dr1_cube`).
*   **Astrometric Baseline:** Gaia DR3 (for sub-pixel alignment < 1.0").
*   **Historical/Overlay:** CatWISE, WISE imagery.
*   **Validation Ground Truth:** Known T/Y dwarf list, AAVSO R Draconis light curves.

## 2. The "Hour-0" Data Contracts
To allow parallel work between Akbar (Data), Adit (Backend/ML), and Tata (Frontend), these JSON/Binary files are frozen as contracts:
1.  `manifest.json`: Metadata for the requested sky patch (coordinates, available dates, detector coverage, binary packing & calibration parameters).
2.  `pack.bin`: Uncompressed little-endian `uint16` image arrays `[visit, detector, y, x]` calibrated linearly via `flux = raw * flux_scale + flux_zero` (`flux_scale` and `flux_zero` in `manifest.json`, reserving `invalid_u16` for missing samples) for fast HTML5 2D Canvas (implemented in `viewer.js`) or WebGL rendering.
3.  `mask.bin`: Companion uncompressed `uint8` bitmask (`[visit, detector, y, x]`) carrying IRSA-rejected (`1`), overflow/saturated (`2`), and edge (`4`) pixel flags per `quality_mask_layout` in `manifest.json`.
4.  `sources.json`: List of identified sources in the frame, including Gaia matches, coordinates, and extracted 102-band arrays.
5.  `cases.json`: synthetic Hour-0 mock contract fixtures matching `ml_cases_output.csv` (with `tier_scope` / `product_tier` aligned to `phantom-worlds-product-v2.md` Tier A known targets, Tier B two-field checks, and Truth Rule #4 benchmark recovery rather than blind new brown dwarf claims).

## 3. Machine Learning Pipeline (Adit's Domain, aligned with `phantom-worlds-ml-research.md`)
### Phase 0: Layer 1 Readings & Preprocessing
*   **Quality Masking & Joint PSF Subtraction:** Mask pixels flagged in `mask.bin` (IRSA-rejected / overflow / edge) and subtract known Gaia sources from calibrated `pack.bin` flux using SPHEREx's provided detector PSF (handling negative residuals via linear `flux_zero` offset).
*   **Feature & Molecule Readings:** Extract calibrated 102-band spectra with errors (`Spectrum alone`) plus physical indices, integrated optical depths/errors (200-redraw percentiles), proper motion/parallax, visit variability, and `blend_share`. Refuse molecule abundance/depth readings when flagged variable, `blend_share > 0.3`, or `< 3` bands cover the feature.

### Phase 1: M1 - Real or Artefact (Ghost Check)
*   **Implemented (`phantom_worlds/ml_pipeline.py`):** Deterministic contamination pre-screening (`blend_share > 0.3`, `is_variable`, `has_masked_pixels`, unflagged non-finite/non-positive spectral color defects, or `< 3` valid positive bands) gates novelty checks to `CONTAMINATION_SCREENED` before downstream novelty scoring.
*   **Planned (Tier B):** Standalone trained M1 classifier (`XGBoost`/`LightGBM` candidate on multi-visit shape variance, pixel variance matrix, and `mask.bin` flags) emitting runtime `p_real` (currently `p_real` appears only in synthetic mock fixtures in `cases.json`).

### Phase 2: M2 - Layer 2/3 Multi-Expert Classifier & Combiner
*   **Implemented (`SpectralDiscoveryPipeline` in `phantom_worlds/ml_pipeline.py`):** Level-1 classifier combining `E1` analytical template $\chi^2$ match, `E2` NaN-native `HistGradientBoostingClassifier` (`scikit-learn`) spectral-color trees, and continuous `E4` parallax gate (`parallax_snr > 5.0` excluded from `Spectrum alone`, applied only inside `All data` across allowed Galactic `E1`/`E2` classes without a threshold cliff) fused in Layer 3 via out-of-fold stacked `LogisticRegression`, held-out `IsotonicRegression`, 90% split conformal prediction sets, and the `<= 0.50` (`Unclassified`) disagreement cap when `E1` and `E2` disagree.
*   **Planned (Tier B/C):** 47 SPIFF hybrid Level-2 subtype templates (`L0`–`Y4`), optional `XGBoost` benchmark swap, `E3` spectrum network/autoencoder, `E5` Gaia DR3/SIMBAD/SPLICES catalogue expert, `E6` multi-visit/NEOWISE variability expert, `E7` sky/brightness prior, and runtime `deciding_bands` / confidence-interval resampling inside `predict_one` (`compute_molecule_readings` already performs 200-redraw resampling).
*   **Validation Pass Marks (Gold-only 60/20/20 sky-tile split, reported per W2 brightness bin):** Level-1 recall $\ge$ 0.80 per type (`SNR > 10`), calibration error $\le$ 0.05, conformal 90% set coverage `88%–92%`, ultracool dwarf subtype within 2 subtypes for `80%` of held-out gold sample, and cross-extraction median ratio within `10%` per band.

### Phase 3: M3 - Novelty & Anomaly Detector
*   **Contamination Screen First (Implemented):** Rule out `blend_share > 0.3`, multi-visit variability, masked/ghost pixels before flagging novelty (`CONTAMINATION_SCREENED`, `weirdness_score: None`); D5/D6 spacecraft glow suppression remains a Tier B frame-level refinement.
*   **Algorithm:** Residual $\chi^2 > 3$ against best template, unsupervised `IsolationForest` (`weirdness_score`), and empty conformal sets (`ml_pipeline.py` implements all three on 102-band spectral features; multi-survey catalogue novelty features and taxonomy U1–U4 router labels remain Planned / fixture-level; Note: Gaia DR3's `1.59 billion` figure refers to Gaia `classprob_dsc_combmod_*` catalogue classifications, not 102-band SPHEREx spectra).
*   **Output:** `weirdness_score` (`None` when screened). Taxonomy flags U1 (Uncatalogued), U2 (Untyped), U3 (Wrong Label), U4 (New Behavior).

## 4. Output Generation (Hendro's Domain)
*   **Implemented (`build_export_packet` / `GET /api/cases/{case_id}/export`):** Generates a unified human-initiated JSON evidence packet (`export_format: "phantom_worlds_json_packet_v1"`, `requires_human_submission: True`, `data_origin`, epoch-propagated `astrometry`, and `ml_summary` incl. `m3_novelty_status`).
*   **Planned (Tier B/C Format-Specific Exporters):**
    *   **Cold Brown Dwarfs:** Generate vector data packet formatted for Backyard Worlds.
    *   **Variable Stars/Discs:** Generate AAVSO VSX text dossier.
    *   **Solar System Objects:** Generate MPC ADES PSV/XML export format (2-night astrometry).