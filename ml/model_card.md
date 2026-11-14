# Phantom Worlds ML Model Card

- **Model version:** `spherex-dr1-e1e2-v1`
- **Pipeline version:** `phantom-ml-slice3`
- **Data as of:** `2026-11-14T11:04:23Z`
- **Training dataset:** `ml/real_training_dataset.npz` (sha256 `38d39fb22fd0cd6b...`, `292` spectra)
- **Release gate verdict:** **UNPUBLISHED**
- **Strict sky-tile disjointness (train / isotonic / conformal / test):** `True`

## 1. Gold-Only Release Gate (`W2 <= 14`)

- Gold test samples (`W2 <= 14`): `33` (Silver excluded: `0`)
- Minimum per-class recall: `0.2000` (threshold `>= 0.80`)
- Expected Calibration Error (ECE): `0.2576` (threshold `<= 0.05`)
- Conformal set coverage: `1.0000` (threshold `>= 0.88`, `conformal_q=1.0000`)

| Class / W2 Bin | Count | Recall / Min Recall | ECE | Coverage | Pass |
|---|---:|---:|---:|---:|---|
| Bin `W2<=12` | 21 | 0.3333 | 0.2857 | 1.0000 | False |
| Bin `12<W2<=13` | 3 | 1.0000 | 0.0000 | 1.0000 | True |
| Bin `13<W2<=14` | 9 | 0.2000 | 0.2778 | 1.0000 | False |
| Bin `W2>14` | 4 | 0.0000 | 0.4528 | 1.0000 | False |

## 2. All-6-Class Held-Out Sky-Tile Diagnostic (Gold + Silver)

- Held-out spectra: `61` | Combined accuracy: `0.5574` | E1-only accuracy: `0.6393` | E2-only accuracy: `0.8361` | E1/E2 agreement: `0.6885`

| Class | Support | Combined Recall | E1 Recall | E2 Recall | Unclassified Rate | Conformal Coverage |
|---|---:|---:|---:|---:|---:|---:|
| Active galaxy or quasar | 6 | 0.1667 | 0.1667 | 0.6667 | 0.6667 | 1.0000 |
| Evolved giant star | 5 | 0.8000 | 1.0000 | 0.8000 | 0.2000 | 1.0000 |
| Galaxy | 8 | 0.3750 | 0.3750 | 0.6250 | 0.5000 | 1.0000 |
| Star | 11 | 0.7273 | 1.0000 | 1.0000 | 0.2727 | 1.0000 |
| Ultracool dwarf | 16 | 0.8125 | 0.8125 | 0.9375 | 0.1250 | 1.0000 |
| Young star with ice or dust | 15 | 0.3333 | 0.4000 | 0.8000 | 0.6000 | 1.0000 |

## 3. Fixed 5 NASA Benchmark Targets

- Real S3 Cube extraction check (`all_passed`): `False`
- Clean reference 102-band check (`all_passed`): `False`

| Target | S3 Cube Pred | S3 Molecule | Ref 102 Pred | Ref Molecule |
|---|---|---|---|---|
| `Barnards_Star` | Unclassified | REFUSED | Unclassified | MEASURED |
| `Eps_Indi_B` | Unclassified | MEASURED | Unclassified | MEASURED |
| `WISE_0855` | Unclassified | MEASURED | Unclassified | MEASURED |
| `RW_Aurigae` | Unclassified | REFUSED | Ultracool dwarf | REFUSED |
| `R_Draconis` | Unclassified | REFUSED | Unclassified | REFUSED |

## 4. Known Limitations & Honest Framing

- Model estimates are probabilistic (`estimate`) and output `Unclassified` capped at confidence `<= 0.50` whenever Expert 1 templates and Expert 2 gradient-boosted trees disagree.
- S3 All-Sky Cubes use HiPS Order 5 (`~13.98 arcsec/px`), which is ~2.25x coarser than native SPHEREx Level-2 (`~6.2 arcsec/px`) and increases blending for faint or crowded sources (e.g., WISE 0855 at short wavelengths, saturating bright red giants/dwarfs in D1-D4).
- Classes `Star`, `Galaxy`, and `Evolved giant star` rely on `silver` cross-matched Gaia/SIMBAD/ALLWISE labels weighted `0.5x` during fit and excluded from Gold-only release gating.
