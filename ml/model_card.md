# Phantom Worlds ML Model Card

- **Model version:** `spherex-dr1-e1e2-v2`
- **Pipeline version:** `phantom-ml-tierb`
- **Data as of:** `2026-11-15T06:51:06Z`
- **Training dataset:** `ml/real_training_dataset.npz` (sha256 `2de6d2bd822725c0...`, `763` spectra)
- **Release gate verdict:** **PUBLISHED**
- **Strict sky-tile disjointness (train / isotonic / conformal / test):** `True`

## 1. Gold-Only Release Gate (`W2 <= 14`)

- Gold test samples (`W2 <= 14`): `93` (Silver excluded: `0`)
- Minimum per-class recall: `0.9048` (threshold `>= 0.80`)
- Expected Calibration Error (ECE): `0.0304` (threshold `<= 0.05`)
- Conformal set coverage: `0.9785` (threshold `>= 0.88`, `conformal_q=0.9153`)

| Class / W2 Bin | Count | Recall / Min Recall | ECE | Coverage | Pass |
|---|---:|---:|---:|---:|---|
| Bin `W2<=12` | 65 | 0.8889 | 0.0431 | 0.9692 | True |
| Bin `12<W2<=13` | 14 | 1.0000 | 0.0051 | 1.0000 | True |
| Bin `13<W2<=14` | 14 | 1.0000 | 0.0353 | 1.0000 | True |
| Bin `W2>14` | 6 | 0.8333 | 0.1148 | 1.0000 | False |

## 2. All-6-Class Held-Out Sky-Tile Diagnostic (Gold + Silver)

- Held-out spectra: `155` | Combined accuracy: `0.8968` | E1-only accuracy: `0.9161` | E2-only accuracy: `0.9419` | E1/E2 agreement: `0.9355`

| Class | Support | Combined Recall | E1 Recall | E2 Recall | Unclassified Rate | Conformal Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Active galaxy or quasar | 17 | 1.0000 | 1.0000 | 1.0000 | 0.0000 | 1.0000 |
| Evolved giant star | 27 | 0.7407 | 0.7407 | 0.8889 | 0.2222 | 0.8519 |
| Galaxy | 18 | 0.8889 | 0.9444 | 0.8889 | 0.0556 | 0.8889 |
| Star | 10 | 0.9000 | 1.0000 | 1.0000 | 0.1000 | 1.0000 |
| Ultracool dwarf | 40 | 0.9500 | 0.9750 | 0.9500 | 0.0250 | 0.9750 |
| Young star with ice or dust | 43 | 0.9070 | 0.9070 | 0.9535 | 0.0465 | 0.9767 |

## 3. Fixed 5 NASA Benchmark Targets

- Real S3 Cube extraction check (`all_passed`): `False`
- Clean reference 102-band check (`all_passed`): `False`

| Target | S3 Cube Pred | S3 Molecule | Ref 102 Pred | Ref Molecule |
|---|---|---|---|---|
| `Barnards_Star` | Unclassified | REFUSED | Star | MEASURED |
| `Eps_Indi_B` | Ultracool dwarf | MEASURED | Ultracool dwarf | MEASURED |
| `WISE_0855` | Unclassified | MEASURED | Unclassified | MEASURED |
| `RW_Aurigae` | Ultracool dwarf | REFUSED | Unclassified | REFUSED |
| `R_Draconis` | Unclassified | REFUSED | Star | REFUSED |

## 4. Ultracool Dwarf Level-2 Subtype & Input Ladder (Tier B)

- Held-out SPIFF UCD subtype count: `40` | Within 2 subtypes: `0.8750` (gate `>= 0.80`) | MAD: `0.54` | Pass: `True`
- Cross-extraction ratio (`our S3 cube / SPIFF ref`, n=`60`): max abs band median deviation `0.0797` (gate `<= 0.10`) | Pass: `True`

| Input Ladder Rung | Features | All-Class Acc | Gold Test Acc |
|---|---:|---:|---:|
| `rung1_e0_molecules_only` | 4 | 0.5226 | 0.5960 |
| `rung2_stage10_band_features` | 12 | 0.9097 | 0.9192 |
| `rung3_all_102_bands` | 90 | 0.9097 | 0.9192 |
| `rung4_bands_plus_stage10_spectrum_alone` | 102 | 0.8968 | 0.9394 |
| `rung5_all_data_with_gaia_parallax` | 102 | 0.8968 | 0.9394 |

## 5. Known Limitations & Honest Framing

- Model estimates are probabilistic (`estimate`) and output `Unclassified` capped at confidence `<= 0.50` whenever Expert 1 templates and Expert 2 gradient-boosted trees disagree.
- S3 All-Sky Cubes use HiPS Order 5 (`~13.98 arcsec/px`), which is ~2.25x coarser than native SPHEREx Level-2 (`~6.2 arcsec/px`) and increases blending for faint or crowded sources (e.g., WISE 0855 at short wavelengths, saturating bright red giants/dwarfs in D1-D4).
- Classes `Star`, `Galaxy`, and `Evolved giant star` rely on `silver` cross-matched Gaia/SIMBAD/ALLWISE labels weighted `0.5x` during fit and excluded from Gold-only release gating.
