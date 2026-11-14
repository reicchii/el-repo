# Phantom Worlds — Proof Report v2

- **Run at (UTC):** `2026-11-14T17:28:29Z`
- **Data as of:** `2026-11-14T13:49:23Z`
- **Pipeline version:** `0.3.0-tierb`
- **Tier B summary:** 8 PASS, 5 FAIL, 0 NOT_MEASURED (out of 13)

## Tier A Target Checks

| Target | Gaia RMS | D6 S/N | Motion | Residual | Note |
|---|---|---|---|---|---|
| Barnard's Star | 0.284" | 2201.53 | 12.873"/yr | 2.484"/yr | Motion residual 2.484"/yr (pass <= 1.0), saturated detectors: D1, D2, D3, D4, D5, D6 |
| WISE 0855 (W0855-0714) | 0.198" | -1.48 | Not measured | not measured | D6 median S/N -1.48, D1-D4 max S/N 4.51 |
| Epsilon Indi B (Ba + Bb) | 0.578" | 130.39 | 4.208"/yr | 0.563"/yr | Motion residual 0.563"/yr on D5 (pass <= 1.5) |
| RW Aurigae | 0.856" | 2984.86 | 2.083"/yr | 2.082"/yr | Saturated detectors excluded: D1, D2, D3, D4, D5, D6 |
| R Draconis | 4.488" | 288.87 | Not measured | not measured | Core saturated on 3-visit cutout; full 222-date NEP light curve required for period test |

## Tier B Tests (B1–B13)

| ID | Target | Pass mark | Measured | Status | Reason |
|---|---|---|---|---|---|
| B1 | RW Aurigae field | median <= 5%, scatter <= 10% | median 3.5%, scatter 10.62% (n=7) | **FAIL** | Scatter 10.62% exceeds 10% ceiling |
| B2 | W1925 field | scatter <= 20% | scatter 19.24% (median -6.72%, n=47) | **PASS** | Crowded Galactic-plane deblended photometry within 20% |
| B3 | RW Aurigae field | 80% or more | recovery 80.0% (8/10) | **PASS** | Planted PSF mover tracks recovered >= 80% on real rwaur D3 background |
| B4 | Benchmark list + field neighbours | >= 80% found, <= 1% neighbour false match | recall 100.0% (6/6), FP 6.56% (44/671) | **FAIL** | Threshold not met |
| B5 | Type model (gold > S/N 10) | recall >= 0.80, ECE <= 0.05, cov 88-92% | min recall 0.5833, ECE 0.1071, coverage 0.8986 (UNPUBLISHED) | **FAIL** | Gate failed -> model stays UNPUBLISHED, panel surfaces readings & E1/E2 cap |
| B6 | Model M1 | 0.90 or more | recall 0.9048 at 1% FPR (score thresh 0.5) | **PASS** | Calibrated RF artefact discriminator above 0.90 recall |
| B7 | Movers among test targets | predicted <= 2 sigma, stay excluded > 3 sigma | held 1/3 (clean unsaturated 1/1) | **FAIL** | TGT-01:failed; TGT-02:not_observed; TGT-03:held |
| B8 | RW Aurigae & W1925 fields | published as measured | RW Aur D3 13.5/17.25 / D6 13.5/15.91 AB; W1925 D3 14.5/15.05 / D6 15.5/15.94 AB | **PASS** | Measured 90% mover recovery reaches 13.50 AB mag (50%: 15.91 AB mag) off-plane (RW Aur D6) and 15.50 AB mag (50%: 15.94 AB mag) in the Galactic plane (W1925 D6); D3 50% crowding loss 2.2 mag (17.25 AB mag off-plane vs 15.05 AB mag Galactic plane) across motions 0.03–8.0"/hr. Field-size limit: each SPHEREx cutout covers 6.56' (394"); a 500 AU distant planet shifts ~800" (~130 px) in 6 months via parallax, exceeding one cutout unless cross-tile links are run. |
| B9 | SMDET-1 crowding regime | published as measured (expected: not detected) | detected=False (19.0 AB rate 0.0, W1925 D6 50%/90% 15.94/15.5) | **PASS** | Published as measured: 19.0 AB mag recovery 0.0% vs W1925 D6 50%/90% depth 15.94/15.5 AB mag |
| B10 | Edge check | 1% or less | rate 0.0% (0/19) | **PASS** | Within 1% false-flag budget |
| B11 | Ultracool dwarf subtype | >= 80% within 2 subtypes | 87.5% (MAD 0.475 subtypes, n=40) | **PASS** | Meets >= 80% within 2 subtypes gate |
| B12 | Cross-extraction | median ratio within 10% per band | max abs ratio dev 139.077 across 94 bands (n=2) | **FAIL** | Band ratio offsets exceed 10% at noisy detector edges (published honestly) |
| B13 | Type model input ladder | published as measured | R1 mols 0.6737 -> R2 feat 0.8 -> R3 102b 0.8105 -> R4 spec 0.7579 -> R5 +Gaia 0.7579 | **PASS** | All five rungs measured on strict sky-tile held-out gold test split |

## Retrospective Prediction Check (T46 / B7)

| Target | Det | Status | Pred Sep | Stay Sep | 1-sigma |
|---|---|---|---|---|---|
| Barnard's Star | D6 | failed | 8.882" | 12.974" | 0.62" |
| WISE 0855 (W0855-0714) | D6 | not_observed | n/a | n/a | 1.246" |
| Epsilon Indi B (Ba + Bb) | D5 | held | 2.179" | 4.174" | 1.623" |

## Stated Limits (Section 13.4)

- Depth: SPHEREx four-survey goal is 17.8-18.8 AB mag (3.8-5.0 um, Bock et al. 2025). Our single-visit field recovery (B8, D6 90%/50%) reaches 13.50 AB mag/15.91 AB mag in RW Aurigae and 15.50 AB mag/15.94 AB mag in W1925.
- Crowding: Near the Galactic plane crowding costs ~1.5 mag (SMDET-1, arXiv:2608.00046). In D3 (1.6-2.4 um) RW Aur 50% reaches 17.25 AB mag vs 15.05 AB mag in W1925, while RW Aur's bright central YSO halo caps field-wide D6 90% completeness at 13.50 AB mag, with blended ks<0.3 photometry scatter 19.24% (B2).
- Measured 90% mover recovery reaches 13.50 AB mag (50%: 15.91 AB mag) off-plane (RW Aur D6) and 15.50 AB mag (50%: 15.94 AB mag) in the Galactic plane (W1925 D6); D3 50% crowding loss 2.2 mag (17.25 AB mag off-plane vs 15.05 AB mag Galactic plane) across motions 0.03–8.0"/hr. Field-size limit: each SPHEREx cutout covers 6.56' (394"); a 500 AU distant planet shifts ~800" (~130 px) in 6 months via parallax, exceeding one cutout unless cross-tile links are run.
- Classification honesty: Class percentages are calibrated on our test fields only. An estimate is a follow-up suggestion and confirms nothing; disagreement between E1 templates and E2 trees caps confidence at <= 50% (Unclassified).
- Molecule readings: Values report measured feature strengths and integrated optical depths (integrated_tau). Composition percentages are shown only for ice species relative to water ice.
- Input ladder (B13): Molecule readings alone give 0.6737 gold test accuracy; full 12 band features reach 0.8, 102 bands 0.8105, and Gaia parallax coverage is 0.5515.

## Credits (Section 13.5)

- **NASA SPHEREx DR1 & Quick Release (QR2, QR3) Spectral Images via IRSA**: IRSA SPHEREx Archive; QR2 DOI 10.26131/IRSA652; QR3 DOI 10.26131/IRSA662; Bock et al. 2025; Akeson et al. 2025 (arXiv:2511.15823).
- **Crowding & Sub-stellar Literature**: SMDET-1 crowding depth benchmark (arXiv:2608.00046); Faherty et al. 2018; WISE 0855 & Barnard's Star reference astrometry.
- **Reference Surveys & Archives**: Gaia DR3 (ESA), 2MASS (IPAC/UMass), CatWISE2020, unWISE, Spitzer GLIMPSE, SIMBAD, VizieR (CDS), AAVSO VSX, IMCCE SkyBoT.
- **Inspiration & Viewer Heritage**: WiseView (byw.tools), Backyard Worlds: Planet 9, The Rogue Worlds Project, Aladin Lite (CDS), IRSA forced photometry.
- **ML Training Libraries & Python Stack (Permissive Licences)**: SPIFF library (DOI 10.5281/zenodo.19051216, CC BY 4.0, Gagne et al. 2026); UltracoolSheet (DOI 10.5281/zenodo.4169084, CC BY 4.0); SPLICES (DOI 10.26131/IRSA554, Ashby et al. 2023); DESI DR1 (CC BY 4.0); Euclid; Astropy, photutils, scikit-learn, SciPy, NumPy, FastAPI.

## Next

- C1-C5 Community review workflow, pinned sky evidence notes & Brier forecast scoring (Tier C).
- C6-C7 All-sky spectral cube slices & interactive Draw-the-Light spectral sketch matching.
- C8-C13 Saved search recipes, GCNS 3D neighbourhood map & Indonesian localization.
