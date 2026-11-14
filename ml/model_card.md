# Phantom Worlds ML Model Card

- **Model version:** `spherex-dr1-e1e2-v2`
- **Pipeline version:** `phantom-ml-tierb`
- **Data as of:** `2026-11-14T13:49:23Z`
- **Training dataset:** `ml/real_training_dataset.npz` (sha256 `12e73c69316d5a18...`, `695` spectra)
- **Release gate verdict:** **UNPUBLISHED**
- **Strict sky-tile disjointness (train / isotonic / conformal / test):** `True`

## 1. Gold-Only Release Gate (`W2 <= 14`)

- Gold test samples (`W2 <= 14`): `69` (Silver excluded: `0`)
- Minimum per-class recall: `0.5833` (threshold `>= 0.80`)
- Expected Calibration Error (ECE): `0.1071` (threshold `<= 0.05`)
- Conformal set coverage: `0.8986` (threshold `>= 0.88`, `conformal_q=0.8047`)

| Class / W2 Bin | Count | Recall / Min Recall | ECE | Coverage | Pass |
|---|---:|---:|---:|---:|---|
| Bin `W2<=12` | 39 | 0.0000 | 0.1364 | 0.8462 | False |
| Bin `12<W2<=13` | 15 | 0.3333 | 0.0744 | 1.0000 | False |
| Bin `13<W2<=14` | 15 | 0.7500 | 0.1275 | 0.9333 | False |
| Bin `W2>14` | 26 | 0.3077 | 0.2148 | 0.9615 | False |

## 2. All-6-Class Held-Out Sky-Tile Diagnostic (Gold + Silver)

- Held-out spectra: `136` | Combined accuracy: `0.6691` | E1-only accuracy: `0.7059` | E2-only accuracy: `0.8088` | E1/E2 agreement: `0.7574`

| Class | Support | Combined Recall | E1 Recall | E2 Recall | Unclassified Rate | Conformal Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Active galaxy or quasar | 25 | 0.4400 | 0.4400 | 0.8400 | 0.4800 | 0.9200 |
| Evolved giant star | 8 | 0.5000 | 0.6250 | 0.6250 | 0.5000 | 0.8750 |
| Galaxy | 24 | 0.2917 | 0.3333 | 0.5000 | 0.5833 | 0.7500 |
| Star | 9 | 0.8889 | 1.0000 | 0.8889 | 0.1111 | 0.8889 |
| Ultracool dwarf | 40 | 0.9500 | 1.0000 | 0.9500 | 0.0500 | 0.9750 |
| Young star with ice or dust | 30 | 0.7667 | 0.7667 | 0.8667 | 0.1000 | 0.8333 |

## 3. Fixed 5 NASA Benchmark Targets

- Real S3 Cube extraction check (`all_passed`): `False`
- Clean reference 102-band check (`all_passed`): `False`

| Target | S3 Cube Pred | S3 Molecule | Ref 102 Pred | Ref Molecule |
|---|---|---|---|---|
| `Barnards_Star` | Unclassified | REFUSED | Star | MEASURED |
| `Eps_Indi_B` | Ultracool dwarf | MEASURED | Ultracool dwarf | MEASURED |
| `WISE_0855` | Unclassified | MEASURED | Unclassified | MEASURED |
| `RW_Aurigae` | Active galaxy or quasar | REFUSED | Active galaxy or quasar | REFUSED |
| `R_Draconis` | Unclassified | REFUSED | Star | REFUSED |

## 4. Ultracool Dwarf Level-2 Subtype & Input Ladder (Tier B)

- Held-out SPIFF UCD subtype count: `40` | Within 2 subtypes: `0.8750` (gate `>= 0.80`) | MAD: `0.475` | Pass: `True`
- Cross-extraction ratio (`our S3 cube / SPIFF ref`, n=`2`): max abs band median deviation `139.077` (gate `<= 0.10`) | Pass: `False`

| Input Ladder Rung | Features | All-Class Acc | Gold Test Acc |
|---|---:|---:|---:|
| `rung1_e0_molecules_only` | 4 | 0.5735 | 0.6737 |
| `rung2_stage10_band_features` | 12 | 0.7353 | 0.8000 |
| `rung3_all_102_bands` | 90 | 0.7279 | 0.8105 |
| `rung4_bands_plus_stage10_spectrum_alone` | 102 | 0.6691 | 0.7579 |
| `rung5_all_data_with_gaia_parallax` | 102 | 0.6691 | 0.7579 |

## 5. Known Limitations & Honest Framing

- Model estimates are probabilistic (`estimate`) and output `Unclassified` capped at confidence `<= 0.50` whenever Expert 1 templates and Expert 2 gradient-boosted trees disagree.
- S3 All-Sky Cubes use HiPS Order 5 (`~13.98 arcsec/px`), which is ~2.25x coarser than native SPHEREx Level-2 (`~6.2 arcsec/px`) and increases blending for faint or crowded sources (e.g., WISE 0855 at short wavelengths, saturating bright red giants/dwarfs in D1-D4).
- Classes `Star`, `Galaxy`, and `Evolved giant star` rely on `silver` cross-matched Gaia/SIMBAD/ALLWISE labels weighted `0.5x` during fit and excluded from Gold-only release gating.
