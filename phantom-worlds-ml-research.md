# 10. Machine learning: what the data support, every option, and the design we build

Written 13 Nov 2026 (triaged and verified 14 Nov 2026 against archive docs and `architecture_decision_records.md` ADR 005) after reading the resource pages, the SPHEREx Explanatory Supplement v2.1 and the 2026 papers that use real SPHEREx spectra. Section 12 lists every source. Confirmed items carry `[VERIFIED]`, remaining runtime archive checks carry `[OPEN]`/`[PARTIAL]`, and unverified recollections without a cited paper carry `[FROM MEMORY]`.

This document supersedes early ML stage notes (consolidated into `system_specifications.md` §3). Older documents say M2 and M3. M2 is the type model described here. M3 is the isolation forest inside the novelty checks.

## 1. Short answer

1. The product goal stands: read a spectrum, report what it contains, combine it with other surveys, and state the most likely object type with a confidence. The tool reports. People decide.
2. One part of the goal changes. A full composition such as "40% CO2, 20% NO" is a quantity SPHEREx data do not contain. Section 3 explains why and gives the readings that are measurable. One real percentage survives: for ices, each molecule as a percentage of water ice.
3. Published results on SPHEREx spectra show that accuracy is limited first by signal and blending, second by label quality, third by which other surveys are added. Model size comes fourth. In the one study that compared them, a learned spectrum encoder changed star purity by about one point, and adding image data changed it by about 25 points (section 2, fact 9).
4. So the "heavy" part of our system is the fusion: several independent experts, each reading one kind of evidence, joined by a calibrated combiner. A large neural spectrum model is on the roadmap with the conditions it needs (section 10).
5. The active Hour-0 implementation (`phantom_worlds/ml_pipeline.py`) uses `scikit-learn` (`HistGradientBoostingClassifier`, out-of-fold `LogisticRegression`, held-out `IsotonicRegression`, and `IsolationForest`) to avoid extra unbundled binary wheels in `requirements.txt`, while `XGBoost` and `LightGBM` remain planned offline benchmark candidates (Section 13).
6. Labelled SPHEREx spectra exist today. The largest set is 6,003 ultracool dwarf spectra with 47 subtype templates. This makes a trained model possible this weekend.

## 2. Facts that set the limits

| # | Fact | Source |
|---|---|---|
| 1 | A source's spectrum is a set of single-exposure measurements, each at its own wavelength, taken over days to weeks. The 102 bands are a binning of these. Exposures of one target can span 5 to 40 days. A target gets at least 408 measurements over four surveys | Supplement, Melnick 2026 |
| 2 | Resolving power is 35 to 41 below 3.8 µm and 112 to 128 from 3.8 to 5.0 µm | Supplement |
| 3 | Official photometry is forced PSF photometry at a fixed position with a 3% systematic error added. Independent teams use larger floors: 3% visit to visit with calibration within 3% (bands 1 to 4) and 5% (bands 5 and 6), or an 8% floor on absolute flux | Supplement, Rustamkulov 2026, Gagné 2026 |
| 4 | Depth per exposure at 5σ is about 19.5 AB below 3.8 µm and 17.5 to 18.5 AB above. Signal to noise per band reaches about 10 at W2 = 14.0. The ice team requires W2 brighter than 11.96 to reach 50 per band in bands 5 and 6 | Rustamkulov 2026, Gagné 2026, Melnick 2026 |
| 5 | Pixels are 6.15″, so neighbours blend. Of 1,327 known brown dwarfs with W2 ≤ 14.0, 81.2% gave a clean match, 8.6% were typed slightly early, and 7.6% were low quality, mostly from background sources and blends. Some percentages in that paper do not add up, so treat them as approximate | Gagné 2026 |
| 6 | Template matching recovers the spectral type of ultracool dwarfs with a median absolute deviation of 1.5 subtypes | Gagné 2026 |
| 7 | Atmosphere model grids fit real brown dwarf spectra poorly. Reduced χ² is 10 or more for most high-signal spectra. Fitted gravity for one L1 dwarf spans three orders of magnitude across grids. Fitted temperature moves by 100 to 200 K between grids. A second team finds gravity off by a median 1.05 dex between 1,700 and 2,500 K | Rustamkulov 2026, SUDA 2026 |
| 8 | The SPHEREx ice team does not split a spectrum into ice mixtures. It measures the integrated optical depth of each feature. Its reasons: mixture fits are not unique, features beyond 5 µm are often needed, and grain assumptions add large uncertainty. Narrow CO and CO2 features read low at this resolution and need a correction | Melnick 2026 |
| 9 | Star against galaxy, on simulated SPHEREx spectra. Boosted trees on the 102 normalised bands: stellar completeness 0.977, purity 0.682. Trees on a learned spectrum embedding: 0.973 and 0.692. Trees on an image embedding aligned with the spectrum: 0.983 and 0.931 | arXiv 2607.20797 |
| 10 | Galaxy, narrow-line active galaxy, broad-line active galaxy, on real spectra with 14 empirical templates: accuracy 81.3% in the deep field and 72.9% at all-sky depth | arXiv 2609.02167 |
| 11 | About 22% of the ice target list is flagged variable from NEOWISE and Gaia. A spectrum built from exposures on different dates can show false features for a variable source | Melnick 2026 |
| 12 | The main infrared band of nitric oxide (NO) is at 5.3 µm, outside the SPHEREx range of 0.75 to 5.0 µm. Its overtone near 2.7 µm is about 27 times weaker (2.8 against 76 in the same units). Water also absorbs near 2.7 µm `[FROM MEMORY]` | Breeze and Ferriso 1964 |

## 3. Molecules: what can be measured

A SPHEREx spectrum shows a molecule as a dip or a bump at a known wavelength. The size of that feature is measurable with an error. Turning feature sizes into a complete percentage breakdown fails for four reasons.

1. Most of the mass of a star, brown dwarf or gas cloud is hydrogen and helium, which leave no usable feature in this range. The molecules we see are trace species.
2. Many molecules have no band between 0.75 and 5.0 µm. NO is one (fact 12).
3. Going from feature size to amount needs a physical model. For brown dwarfs the models misfit the data (fact 7). For ices the mixture is not unique (fact 8).
4. At a resolving power of 35 to 130, narrow features are diluted and neighbouring features merge.

The teams that built SPHEREx face the same limits and report feature strengths. We do the same, and we label every value with its origin.

### What we report, by kind of object

| Kind of object | Features in range | Reading we show | Origin label |
|---|---|---|---|
| Ice in front of a star or around a young star | H2O 3.05 µm, CO2 4.27, 13CO2 4.38, XCN 4.62, CO 4.67, OCS 4.91 | Integrated optical depth with error per feature. Column density using a stated laboratory band strength. Each molecule as a percentage of water ice | Measured for depth. Estimated for column density and percentage |
| Brown dwarf or cool star | CH4 3.20 to 3.65 µm, CO2 4.18 to 4.35, CO 4.55 to 4.80, each against the 3.70 to 4.14 window. Water bands | Index in magnitudes with error. Spectral type from templates. Temperature only as a range taken from the type | Measured for index. Estimated for type and temperature |
| Comet coma | CO2 gas near 4.26 µm, water near 2.7, CO near 4.67 | Band flux above the dust continuum with error, per date. Production rate is a stretch item and needs a coma model | Measured |
| Galaxy or nebula | 3.28 µm emission from carbon-ring molecules, hydrogen lines near 1.875 and 4.05 µm | Line or band flux with error. Redshift when lines allow | Measured |
| Asteroid | Broad band near 3 µm from hydrated minerals `[FROM MEMORY]` | Band depth against the continuum. Rotation changes brightness between exposures, so correct with the light curve first | Measured |

### The percentage we can show

For ice sightlines: `N(molecule) / N(H2O) × 100`, with `N = integrated optical depth / band strength`. Ice astronomers publish abundances this way. The interface line reads, for example, `Carbon dioxide ice: [value]% of water ice, ± [error], Estimated`. Band strengths come from Gibb et al. (2004, ApJS 151, 35–73) `[VERIFIED K23 reference: e.g. H2O 3.0 µm ~2.0e-16, CO2 4.27 µm ~1.0–1.2e-16, CO 4.67 µm ~1.1–1.7e-17 cm molecule^-1; freeze exact constant table + low-res correction in Tier B before emitting N]`. Apply the low-resolution correction to CO and CO2 or state that it is not applied.

For every other kind of object the panel shows feature strength with error and a detection significance, and no composition percentage.

### Method for molecule readings

1. Continuum: fit a third-degree polynomial through the clean windows the ice team uses, 2.53 to 2.72, 3.80 to 4.02 and 4.90 to 5.01 µm, for ice sightlines. For brown dwarfs use the 3.70 to 4.14 µm window as the reference, as in Rustamkulov 2026. *(Implemented in `phantom_worlds/ml_pipeline.py` `compute_molecule_readings` as a scale-invariant `deg <= 2` log-flux polynomial over `((2.50, 2.72), (3.80, 4.02), (4.90, 5.01))` µm—widening `2.53 -> 2.50` to retain `B053` at `2.5235` µm and avoiding flat brown-dwarf hijacks on reddened YSO sightlines—paired with disjoint `CO_4_67` shoulders `((4.38, 4.545), (4.805, 4.92))` µm.)*
2. Optional upgrade: Gaussian-process regression for the continuum (scikit-learn), which the ice team uses as one of four fitters. It returns an error on the continuum.
3. Optical depth per band: `τ = ln(continuum / flux)`. Integrate over the feature in wavenumber.
4. Error: redraw the spectrum 200 times within its errors and repeat steps 1 to 3. Report the median and the 16th to 84th percentile range.
5. Refuse the reading when the source is flagged variable, when the blend share is above 0.3, or when fewer than three bands cover the feature. Say which reason applied.

## 4. Object types and labels

### Types

Two levels. Level 1 always runs. Level 2 runs only where labelled spectra exist.

| Level 1 | Level 2 |
|---|---|
| Star | temperature class from Gaia when available |
| Ultracool dwarf (brown dwarf or very low-mass star) | subtype L0 to Y4 (Y2+ via template/literature fallback such as WISE 0855 Y4, or Unclassified if unsupported), plus young and subdwarf flags |
| Young star with ice or dust | none yet |
| Evolved giant star | none yet |
| Galaxy | none yet |
| Active galaxy or quasar | narrow-line, broad-line `[OPEN K19 — Ren et al. 2609.02167 14-template method verified on arXiv; extract public table files in Tier B]` |
| Solar-system object | name from ephemeris. No model needed |
| Unclassified | shown when no type reaches 50% |

Artefact is decided earlier by model M1 and the machine checks, so the type model only sees signals that passed.

### Label sources

| Type | Source | Size | Grade |
|---|---|---|---|
| Ultracool dwarf with subtype | SPIFF library: reduced SPHEREx spectra with literature types, plus templates for 47 subtypes. Zenodo `10.5281/zenodo.19051216` and mocadb.ca | 6,003 spectra | Gold |
| Ultracool dwarf with temperature | SUDA atlas, 57 templates from about 700 to 3,000 K | 1,675 objects `[OPEN K19 — arXiv 2604.26771 verified; extract public template table URLs in Tier B]` | Gold |
| Young star, evolved giant, active galaxy, main-sequence star | SPLICES columns `CLASS_1`, `YSO_PUB`, `STYPE_ML`, `STYPE_ML_PROB1`, `STYPE_ML_PROB2` | 633,814 sources above 90% probability, 56% young stars, 40% evolved giants | Silver for `STYPE_ML`, gold where `YSO_PUB` cites a publication |
| Star, white dwarf, binary, quasar, galaxy | Gaia DR3 classifier probabilities (`classprob_dsc_combmod_*`), quasar and galaxy candidate tables | 1.59 billion classified, 6.6 million quasar candidates, 4.8 million galaxy candidates | Silver |
| Star with spectral type, galaxy, quasar | SIMBAD object types plus spectroscopic TAP catalogues `[VERIFIED K27: SDSS DR16Q/DR18, DESI, and Milliquas v8 ("VII/294/catalog") via VizieR/NOIRLab TAP]` | varies | Gold when from spectroscopy |
| Variable star class | Gaia variability class, also carried in SPLICES as `VarClassGaia` | varies | Silver |
| Solar-system object | IRSA Moving Object Search Tool | by ephemeris | Exact |

Gold means a person or a spectrograph set the label. Silver means another model set it. Rules:
- The test set is gold only.
- Silver labels train the model at half weight and never count toward a pass mark.
- Record the label source per row so a result can be traced.

### Where training spectra come from

| Route | What it gives | Cost | Status |
|---|---|---|---|
| SPIFF Zenodo package | 6,003 ultracool dwarf spectra snapshot (`10.5281/zenodo.19051216`) | one download | ready `[VERIFIED K18: 17 files / ~6.3 GB incl. 47 hybrid templates (~79 KB); data CC-BY-4.0, code MIT]` |
| IRSA Spectrophotometry Tool | Spectra for a list of positions, computed on IRSA's servers with the pipeline's method | a person uploads positions in the browser and downloads results | `[VERIFIED K21: max 20 sources/run, 2 concurrent jobs max, runtime ~ 1.67*N_img+50 s; bulk >20 uses SIAv2+S3 cutouts]` |
| All-sky cube tiles | Small-aperture spectra for every labelled source inside a tile. One tile is about 300 MB | 10 to 20 tiles `[ESTIMATE]` | display grade. Compare against per-frame spectra for the same sources before use (check K22) |
| Our own extraction (stages 7 and 9) | Science-grade spectra with our errors | hundreds of cutouts per source | only for the processed fields and the test targets |

A person can run the first three on Friday, since downloading data is allowed before the start.

## 5. Every option, stage by stage

Verdicts: **Build** is in the weekend plan. **If time** is a stretch task. **Later** is after the hackathon. **Skip** has a stated reason.

### A. Getting the spectrum

| Option | Notes | Verdict |
|---|---|---|
| Aperture sum (as in xcavation and the Source Discovery Tool, radii 3 to 5 px) | Simple. Wrong in crowds | Build as quick look only |
| PSF-weighted sum at a fixed position | Our stage 7 | Build |
| PSF fit with the position free and shifted by proper motion per exposure | The SPIFF method. Needed for movers. Position freedom helps when coordinates are stale, as with WISE 0855 | Build inside the along-track mode |
| Joint fit of every catalogued source in the cutout | Our stage 9, the same idea as the official pipeline. Best in crowds | Build for processed fields |
| Learned deblending network | No truth set to train on this weekend | Skip |

### B. Representing the spectrum

| Option | Notes | Verdict |
|---|---|---|
| 102 bands divided by their mean, with errors and a coverage mask | The baseline. Within one point of learned embeddings in fact 9 | Build |
| Physical indices and slopes (stage 10, section 3) | Each has an error and a meaning a user can read | Build |
| Non-negative matrix factorisation or PCA coefficients | Used for the galaxy and active galaxy templates. Weights handle missing bands | If time |
| Autoencoder latent (1D convolutional, 6 numbers, error-weighted loss) | Published design reaches χ² per band of about 1.18. Its reconstruction error doubles as a novelty score | If time |
| Masked transformer over the native measurements (wavelength, bandwidth, flux, error, date as one token each) | Fits the instrument: no binning, gaps are natural, date carries variability. Needs on the order of 100,000 spectra and GPU days `[ESTIMATE]` | Later |
| Pretrained astronomy foundation models (AION-1, SpecCLIP, AstroCLIP) for the spectrum | Checked abstracts `[VERIFIED]`: AION-1 (2510.17960) pretrains on Legacy/HSC/SDSS/DESI/Gaia; SpecCLIP (2507.01939) pretrains on LAMOST/Gaia XP; neither includes SPHEREx spectrophotometry | Skip for spectra. AstroCLIP's image encoder is usable for the image branch later |

### C. Deciding the type

| Option | Notes | Verdict |
|---|---|---|
| Template χ² fit, dropping the worst 5 bands, scale solved analytically | The SPIFF method. Works with few examples. Returns residuals a person can inspect | Build |
| Nearest neighbours in the labelled library | Cheap check on the template result | If time |
| Gradient-boosted trees (`HistGradientBoostingClassifier` implemented in Hour-0; `XGBoost`/`LightGBM` as Tier B benchmarks) on spectral features (plus indices/surveys in Tier B) | Handles `NaN`-masked values natively. Library names and alternatives are in section 13. The classifier family used in the published star and galaxy study | Build (`scikit-learn` active; `XGBoost` benchmark later) |
| TabPFN | Strong on small tables. Code is `Apache-2.0`; version 2 weights carry Apache-2.0 with attribution (later versions are non-commercial/restricted) and cap at `[VERIFIED K25: 10,000 rows, 500 features]` | If time |
| Small neural network on the bands (MLP or 1D convolutional) | Useful as a second, different model for the ensemble | If time |
| Transformer classifier | Comes with option B's transformer | Later |
| Two-level classifier | Level 1 by trees. Level 2 for ultracool dwarfs by template | Build |
| Stacked ensemble: logistic regression over out-of-fold outputs of the members above | Often scores above each single member and keeps calibration simple. Keep it only if the test score says so | Build when two members exist |

### D. Physical parameters

| Option | Notes | Verdict |
|---|---|---|
| Spectral type from templates, temperature range from the type | Empirical, so it avoids the model misfit in fact 7 `[VERIFIED K26: Kirkpatrick et al. 2021 (L/T/Y census) & Sanghi et al. 2023 (ApJ 959, 63, M6–T9 polynomial)]` | Build |
| Ice optical depths and ratios (section 3) | The ice team's own quantities | Build |
| χ² fit to public model grids (Sonora Elf Owl, Sonora Diamondback, ATMO2020) | Show as a model comparison with the reduced χ² and the spread between grids. Never as a single answer | If time |
| Data-driven model trained on labelled spectra (The Cannon approach) with SUDA labels | Works at this resolution in published tests. Inherits the label errors | Later |
| Neural posterior estimation trained on simulated spectra | Fast and published for brown dwarfs with JWST data. When simulations misfit real data, the posteriors come out too narrow. That is our case today | Later |

### E. Adding other surveys

What each survey adds:

| Survey | Adds |
|---|---|
| Gaia DR3 | Parallax, so distance. Proper motion. G, BP, RP brightness. Classifier probabilities. Low-resolution spectra from 330 to 1,050 nm for most sources brighter than G 17.6, which overlap SPHEREx band 1. Variability class |
| 2MASS | J, H, Ks from 1997 to 2001, a second epoch more than 20 years back |
| CatWISE2020, AllWISE | W1 and W2 with proper motions, W3 and W4 for dust |
| NEOWISE time series | Brightness changes over more than 10 years |
| ZTF | Optical light curves in the north |
| Euclid, in the deep fields | Sharp images for shape, and near-infrared spectra |
| Sky position | Galactic latitude, dust, and cloud membership from SPLICES |
| Moving Object Search Tool | Whether a known solar-system object was there at that time |
| SIMBAD | An existing type, when one exists |

Derived values with direct physical meaning:
- Absolute magnitude from parallax: `M = m + 5 log10(parallax in arcsec) + 5`.
- Tangential speed: `4.74 × proper motion (arcsec/yr) / parallax (arcsec)` km/s.
- Reduced proper motion when parallax is missing.
- A flag per survey for "no detection", which is evidence in itself for faint red objects.

Ways to combine:

| Option | Notes | Verdict |
|---|---|---|
| Physical gates | Parallax above 5σ means the object is inside our galaxy, so galaxy and quasar are excluded. A known solar-system object at the frame time settles the type. Gates outrank every model | Build |
| One table of all features into the trees | Missing entries stay empty | Build |
| Bayes combination: class prior by sky zone and brightness times the spectrum result | Corrects for labels that over-represent bright, well-studied objects | Build |
| Stacking with a meta-learner | Same as in C | Build when two members exist |
| Contrastive alignment of spectrum and image embeddings | The method behind the 25-point gain in fact 9, shown on simulated data | Later |
| One multimodal transformer | Needs far more paired data than we can assemble | Later |

### F. Confidence

| Option | Notes | Verdict |
|---|---|---|
| Isotonic calibration on a held-out split | Already in the plan | Build |
| Conformal prediction sets per class | A few lines of code. Output is the set of types that contains the truth 90% of the time. An empty set means no known type fits. This matches a tool that reports and leaves the decision to people | Build |
| Resampling within errors: redraw the spectrum 100 times and reclassify | Gives the confidence range we agreed to show | Build |
| Prior correction by sky zone and brightness | See E | Build |
| Deep ensembles | Only with neural members | If time |
| Bayesian neural networks | Costly, and calibration still needs checking afterwards | Skip |

### G. Finding what fits no type

| Option | Notes | Verdict |
|---|---|---|
| Residual χ² after the best template | SPIFF flags reduced χ² above 3 with a 10% error floor | Build |
| Isolation forest on the features | Already in the plan as M3 | Build |
| Empty conformal set | Comes free with F. In a 2026 study of transient spectra, 40% of out-of-taxonomy inputs got an empty set at the loosest setting | Build |
| Autoencoder reconstruction error | Comes with B's autoencoder | If time |

Before a spectrum is called unusual, rule out the ordinary causes in this order: blend share above 0.3, variability between visits, flagged or ghost pixels, spacecraft glow in detectors 5 and 6. In the SPIFF sample, most low-quality matches came from background sources and blends.

### H. Checking the result

1. Split by sky tile, 60% train, 20% calibrate, 20% test.
2. Test on gold labels only.
3. Report every score per brightness bin: W2 up to 12, 12 to 13, 13 to 14, fainter than 14.
4. Leave one type out of training, then confirm its members land in Unclassified or are flagged unusual.
5. Cross-extraction: for 100 SPIFF sources, compare our spectrum with theirs band by band. Report the median ratio.
6. Fixed cases: the five test targets, with the expected readings written down before the model runs (section 8).

## 6. The design

Three layers. Each layer's output is stored, so every number on screen can be traced.

**Layer 1. Readings.** No learning. Spectrum with errors, molecule readings (section 3), measured motion, distance and absolute magnitude from parallax, variability between visits, blend share. These are shown whether or not any model runs.

**Layer 2. Experts.** Each answers one question from one kind of evidence and can abstain.

| Expert | Input | Output |
|---|---|---|
| E1 Template match | binned spectrum | best three templates, reduced χ², residual per band |
| E2 Spectrum trees (`HistGradientBoostingClassifier` active; `XGBoost` benchmark planned) | NaN-native spectral color features (indices/surveys planned) | probability per type |
| E3 Spectrum network (If time) | bands with errors | probability per type, reconstruction error |
| E4 Motion and distance | parallax, proper motion, absolute magnitudes | probability per type, gates |
| E5 Catalogue | Gaia classifier, SIMBAD type, SPLICES class | probability per type, origin Catalogue |
| E6 Variability | SPHEREx visits, NEOWISE, Gaia class | variable or steady, amplitude |
| E7 Sky prior | Galactic latitude, dust, cloud membership, brightness | prior per type |

**Layer 3. Combiner.**
1. Apply the physical gates.
2. Combine expert outputs with a stacked logistic regression trained on out-of-fold predictions.
3. Calibrate, then build the conformal set and the resampled range.
4. Run the novelty checks from G.
5. Write the explanation: the deciding bands, which expert moved the result most, what is missing, and which observation would settle it.

Two results are stored for every source:
- **Spectrum alone**: E1 to E3 only.
- **All data**: every expert.

Showing both tells the user what SPHEREx adds and what the other surveys add. A disagreement between the spectrum result and the catalogue type is the mismatch signal of stage 11.

Rule carried over from stage 13: when the template and the trees disagree on the top type, the shown confidence is capped at 50%.

## 7. On screen

Follow the evidence wording rules in `phantom-worlds-product-v2.md` (§Truth Rules) and lines 280–284 below. The Identity panel gains three blocks. The numbers below only show the layout.

```
Molecule readings
Methane dip, 3.3 µm        0.42 mag ± 0.05    Measured    8σ
Carbon dioxide, 4.3 µm     0.18 mag ± 0.06    Measured    3σ
Carbon monoxide, 4.7 µm    not detected       Measured    under 2σ

Most likely type
Probably an ultracool dwarf, T type     78%  (range 70 to 85)
Also possible: reddened background star 14%
Spectrum alone 61%.  With Gaia and WISE 78%.
Deciding bands: 3.3 µm measured, 4.3 µm measured, 1.6 µm not measured

What would settle it
A second visit with motion measured. Next SPHEREx pass: [date window].
```

Wording rules:
- The panel never states a type as fact. It uses the confidence words from the language document.
- Every reading shows its origin: Measured, Catalogue, Estimated or Assumed.
- A refused reading states its reason, for example `Not measured: the source varies between visits`.
- For ice sightlines the molecule block adds the line `[value]% of water ice`.

## 8. Build order for the weekend

These break down the weekend ML tasks (formerly sprint task T43). Hours are estimates.

Friday, downloads only:
- SPIFF Zenodo package and its templates.
- SPLICES file, 3.1 GB.
- A list of label positions per type. If check K21 passes, a person runs them through the IRSA Spectrophotometry Tool.
- 10 to 20 all-sky cube tiles that hold the most labelled sources `[ESTIMATE]`.

| Task | What | Check | Hours |
|---|---|---|---|
| T43a | Label table with source and grade per row | counts per type and grade reported | 1 |
| T43b | Training spectra: ingest SPIFF, extract the rest, cross-extraction check | median ratio per band within 10% for bright isolated sources | 3 |
| T43c | Molecule readings with resampled errors and refusal reasons | methane dip significant for Epsilon Indi B, absent for Barnard's Star | 2 |
| T43d | E1 template match with SPIFF templates and per-type medians | subtype within 2 of the literature for 80% of a held-out SPIFF sample | 2 |
| T43e | Survey features, gates, E2 trees, E4, E7 | release gate values reported per brightness bin | 3 |
| T43f | Stacking, calibration, conformal sets, resampled ranges, both stored results | coverage of the 90% sets between 88% and 92% on the test split | 2 |
| T43g | Novelty checks with the contamination screens first | a left-out type is flagged at the stated rate | 1 |
| T43h (stretch) | E3 autoencoder member, added to the stack | only kept if the test score improves | 3 |
| T43i (stretch) | Model grid comparison for ultracool dwarfs | spread between grids shown beside the best fit | 3 |

Expected readings for the five test targets, to write down before the model runs:

| Target | Expected | Known difficulty |
|---|---|---|
| Barnard's Star | Star, cool dwarf, no methane dip | very bright, check for overflow |
| Epsilon Indi B | Ultracool dwarf, T type, methane dip | glare from Epsilon Indi A |
| WISE 0855 | Ultracool dwarf, Y type, or Unclassified with a stated reason | detected only in detectors 5 and 6, spacecraft glow at the same wavelengths |
| RW Aurigae | Young star, variable | blended pair, changes between visits |
| R Draconis | Evolved giant, variable | overflow in many bands |

If the model gives a different answer for a target, the panel shows the model's answer and the catalogue type side by side. That is the honest outcome and it is useful to a judge.

## 9. Pass marks

The M2/M3 release gate (mirrored in `system_specifications.md` §3) includes:

- Level 1 recall 0.80 or more per type on gold labels above signal to noise 10.
- Calibration error 0.05 or less.
- Conformal 90% sets cover between 88% and 92% on the test split.
- Ultracool dwarf subtype within 2 subtypes for 80% of the held-out sample. The published scatter is 1.5 subtypes.
- Cross-extraction median ratio within 10% per band.
- Every score reported per brightness bin. A bin that fails is shown as failing.

A version that fails stays unpublished and the panel shows readings with no type.

Reference points from published work, so a judge can compare: 81.2% clean matches for known brown dwarfs with W2 ≤ 14.0, and 72.9% three-way accuracy for galaxies and active galaxies at all-sky depth.

## 10. Later, after the hackathon

1. **Self-supervised spectrum transformer.** Pretrain by masking parts of the native measurements for 100,000 or more sources, then fine-tune on the labels. Condition to start: a bulk source of spectra, either the SPHEREx team's High Reliability Source Catalog or our own extraction at scale.
2. **Alignment with other data.** Contrastive training between SPHEREx spectra, Gaia low-resolution spectra and survey image cutouts.
3. **Review labels feed training.** A case that reviewers settle becomes a gold label, weighted by reviewer agreement. This joins the community part of the product to the model.
4. **Posterior estimation for cold brown dwarfs**, once model grids fit the 4 to 5 µm region. Run coverage tests on real spectra before showing any posterior.
5. **Ice catalogue comparison.** The SPHEREx ice catalogue of about 10 million sources is due after the fourth survey in 2027. Compare our optical depths against it.
6. **Asteroid classes** once the SPHEREx Solar System Object Catalog is public.

## 11. Verification & Open Checks Ledger (K18–K28)

Answers and empirical evidence are recorded in `architecture_decision_records.md` (ADR 005).

- [x] K18 `VERIFIED`: SPIFF Zenodo package (`10.5281/zenodo.19051216`) contains 17 files (~6.3 GB incl. `00_README.txt`, `spiff_zenodo_manifest.csv`, `spiff_templates_hybrid_csv.zip` with 47 members / 79.4 KB, and `spiff_tables.zip`); data license is `CC-BY-4.0`, GitHub code (`jgagneastro/SPIFF`) is `MIT`.
- [ ] K19 `OPEN`: `arXiv:2604.26771` (`SUDA`, 1,675 UCDs, 57 templates, 700–3,000 K) and `arXiv:2609.02167` (14 NMF galaxy/AGN templates) are public preprints; direct VizieR/Zenodo template file URLs remain queued for Tier B ingestion.
- [~] K20 `PARTIAL`: IRSA `splices_colDescriptions.html` confirms `STYPE_ML` (`char`: Machine Learning Source Class), `STYPE_ML_PROB1` (`double`: Stage 1 probability), and `STYPE_ML_PROB2` (`double`: Stage 2 probability); live IRSA TAP query for distinct `STYPE_ML` enum values timed out at 20 s.
- [x] K21 `VERIFIED`: IRSA Spectrophotometry Tool (`sp.html`) enforces a 20-source batch limit, max 2 concurrent jobs, and estimated runtime `1.67 * N_images + 50` s (`0.000463 * N_images + 0.013` hr), with no headless batch API; >20 sources run via IRSA SIAv2 + S3 Level-2 cutouts.
- [ ] K22 `OPEN`: All-sky cube spectra vs per-frame spectra across 50 sources (acceptance gate: median ratio within 10% per band) deferred to Tier B multi-tile runtime benchmark.
- [x] K23 `VERIFIED` (ref): Gibb et al. (2004, *ApJS* 151, 35–73) laboratory ice band-strengths (~`2.0e-16` H2O 3.0 µm, `1.0–1.2e-16` CO2 4.27 µm, `1.1–1.7e-17 cm molecule^-1` CO 4.67 µm); exact mixture constant table + LRS correction to be frozen in Tier B (`ml_pipeline.py` emits optical depth `tau` only for now).
- [x] K24 `VERIFIED`: ESA Gaia DR3 TAP (`https://gea.esac.esa.int/tap-server/tap`, table `gaiadr3.gaia_source` with `classprob_dsc_combmod_*` and `has_xp_sampled`) plus DataLink/`xp_sampled_mean_spectrum` (rate-limited HTTP 429 on unauthenticated burst probe; IRSA TAP Gaia mirror succeeded for patch tables).
- [x] K25 `VERIFIED`: TabPFN v2 supports up to 10,000 rows and 500 features; PyPI package declares `Apache-2.0` and v2 weights carry Apache-2.0 with attribution (v2.5+ weights carry commercial restrictions).
- [x] K26 `VERIFIED`: Ultracool dwarf subtype-to-$T_{\text{eff}}$ calibrations use Kirkpatrick et al. (2021) (20-pc L/T/Y census) and Sanghi et al. (2023, *ApJ* 959, 63, M6–T9 polynomial relation).
- [x] K27 `VERIFIED`: Spectroscopic galaxy/quasar gold labels via IVOA TAP: Milliquas v8 (`"VII/294/catalog"`) on VizieR TAP and SDSS DR16Q/DR18 / DESI via VizieR or NOIRLab TAP.
- [x] K28 `VERIFIED`: PyPI/GitHub checks confirm `xcavation` (`1.1.0`) = `MIT`, `SPIFF` = `MIT` (code) / `CC-BY-4.0` (data), `mapie` (`1.6.0`) = `BSD-3-Clause`, while `spxquery` (`0.4.1`) declares no SPDX license metadata on PyPI (do not vendor/import without repo license confirmation).

## 12. Sources

SPHEREx data and tools
- Explanatory Supplement v2.1: https://irsa.ipac.caltech.edu/data/SPHEREx/docs/SPHEREx_Expsupp.pdf
- Spectrophotometry Tool help: https://irsa.ipac.caltech.edu/onlinehelp/spherex/spherex/sp.html
- SPLICES: https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/ and columns https://irsa.ipac.caltech.edu/data/SPHEREx/SPLICES/gator_docs/splices_colDescriptions.html
- Tutorials index: https://caltech-ipac.github.io/irsa-tutorials/
- Gaia DR3 release page: https://esdcdoi.esac.esa.int/doi/html/data/astronomy/gaia/DR3.html

Papers on real SPHEREx spectra
- Gagné et al. 2026, SPIFF pipeline and ultracool dwarf library: https://arxiv.org/abs/2604.22012 , code https://github.com/jgagneastro/SPIFF , data https://doi.org/10.5281/zenodo.19051216 and https://mocadb.ca
- Rustamkulov et al. 2026, 37 brown dwarfs against model grids: https://arxiv.org/abs/2607.00543
- Tu et al. 2026, SUDA atlas: https://arxiv.org/abs/2604.26771
- Melnick et al. 2026, ice investigation overview: https://arxiv.org/abs/2603.22135
- Hora et al. 2026, ice and emission maps: https://arxiv.org/abs/2603.12390
- Ren et al. 2026, galaxy and active galaxy templates: https://arxiv.org/abs/2609.02167
- Comet 3I/ATLAS with SPHEREx: https://arxiv.org/abs/2508.15469

Methods
- Spectrum and image contrastive learning for star and galaxy separation (simulated SPHEREx): https://arxiv.org/abs/2607.20797
- Photometric redshift with autoencoders and simulation-based inference: https://arxiv.org/abs/2603.24668
- Typing ultracool dwarfs from 2MASS and WISE with machine learning: https://arxiv.org/abs/2605.20146
- The Cannon at low resolution: https://arxiv.org/abs/2203.13829
- Neural posterior estimation for atmospheric retrieval: https://arxiv.org/abs/2301.06575
- Conformal prediction with anomaly awareness for spectra (ASTRANet): https://arxiv.org/abs/2607.08044
- Conformal inference for open-set and imbalanced classes: https://arxiv.org/abs/2510.13037
- TabPFN: https://pypi.org/project/tabpfn and https://doi.org/10.1038/s41586-024-08328-6
- Foundation models: AION-1 https://arxiv.org/abs/2510.17960 , SpecCLIP https://arxiv.org/abs/2507.01939
- Improved Gaia classifier: https://arxiv.org/abs/2405.01340
- Asteroid rotation correction for SPHEREx: https://arxiv.org/abs/2602.08037
- Model grids: Sonora Elf Owl https://zenodo.org/records/15150881 , Sonora Diamondback https://zenodo.org/records/12735103
- NO band strengths: https://doi.org/10.1063/1.1725743
- Packages: xcavation https://pypi.org/project/xcavation/ , spxquery https://pypi.org/project/spxquery/

## 13. Model shortlist with library names

For each job: the first pick, what it does in plain words, and the alternatives worth testing against it. External package licences verified in Section 11 (`K28`) and `architecture_decision_records.md` (ADR 005); confirm any new library's PyPI/repo licence before adding it to `requirements.txt`.

### 13.1 First picks

| Job | Implemented Core / Planned Pick | Library call | In plain words |
|---|---|---|---|
| Type from the spectrum (and survey data in Tier B) | `HistGradientBoostingClassifier` (implemented); `XGBoost` (planned benchmark) | `sklearn.ensemble.HistGradientBoostingClassifier` active; `xgboost.XGBClassifier` not in `requirements.txt` | Builds gradient-boosted decision trees that handle `NaN` values directly without zero-imputation (`XGBoost` kept as optional Tier B comparison) |
| Second opinion on the type | Template match (implemented) | `numpy`, written by us | Takes the normalized template of each known type, scales it to the object ignoring masked bands, and measures reduced χ². Smallest mismatch wins |
| Merge the opinions | Logistic regression stacking (implemented) | `sklearn.linear_model.LogisticRegression` on out-of-fold predictions (`StratifiedKFold`) | Learns how much to trust `E1` vs `E2` for each type, then outputs one probability per type |
| Make percentages honest | Isotonic calibration (implemented) | `sklearn.isotonic.IsotonicRegression` on held-out split (`CalibratedClassifierCV` optional) | Fits one-vs-rest isotonic curves strictly on the held-out calibration split so reported confidences are honest |
| List every plausible type | Split conformal prediction (implemented) | custom quantile rule in `numpy`, written by us | Uses the held-out conformal split (`calibration_size_`) to find the 90% threshold and output plausible types |
| Flag objects that fit no type | Contamination screen + Isolation forest (implemented) | `sklearn.ensemble.IsolationForest` | Rules out `blend_share > 0.3`, variability, and masked spectra first (`CONTAMINATION_SCREENED`), then scores anomalies |
| Real object or image artefact (`M1`) | Contamination screen (implemented); classifier (planned) | `xgboost.XGBClassifier` (planned Tier B; unimplemented in `ml_pipeline.py`) | Runtime `M1` pixel-artefact classifier is not implemented yet; `cases.json` `m1_p_real` holds synthetic fixtures |
| Molecule readings | Polynomial continuum fit + 200-redraw errors (implemented) | `numpy.polyfit` (`compute_molecule_readings`) | Draws continuum baselines, integrates optical depth τ with CO-shoulder fit, and refuses polluted features |
| Which bands decided the result | Planned Tier B explainer | `shap.TreeExplainer` (not in `requirements.txt`) | Per-object band attribution is planned for Tier B (`cases.json` `deciding_bands` are illustrative mock strings) |

### 13.2 Worth testing, in order of expected gain

**Inputs come first.** Test the same model on three input sets before testing other models: bands only, bands plus indices, bands plus indices plus survey data. Published results suggest the choice of inputs moves the score more than the choice of model (section 2, fact 9).

| Job | Alternative | Library call | Why it might win | Watch out for |
|---|---|---|---|---|
| Type model | LightGBM | `lightgbm.LGBMClassifier` | Same family as XGBoost, grows trees differently, often faster | Overfits small data unless `num_leaves` and `min_child_samples` are limited |
| Type model | CatBoost | `catboost.CatBoostClassifier` | Same family, good results with default settings | Slower to train |
| Type model | scikit-learn histogram boosting | `sklearn.ensemble.HistGradientBoostingClassifier` | Same family, no extra install | Fewer tuning options |
| Type model | Random forest and extra trees | `sklearn.ensemble.RandomForestClassifier`, `ExtraTreesClassifier` | Simple, hard to overfit, a good sanity check | `[VERIFIED on installed scikit-learn 1.9.0: both handle NaN inputs natively without imputation]` |
| Type model | TabPFN, version 2 weights | `tabpfn.TabPFNClassifier` | A pretrained network for small tables. No tuning. `[VERIFIED K25: <= 10,000 rows, <= 500 features]` | Needs a GPU to be fast. Only version 2 weights fit our Apache-2.0 licence |
| Type model | Small neural network | `sklearn.neural_network.MLPClassifier` or PyTorch | Learns smooth shapes across neighbouring bands | Needs scaled inputs and filled cells. Usually behind trees on small tables |
| Type model | 1D convolutional network or autoencoder | PyTorch | Reads the spectrum as a curve, so it can use the order of the bands. Reconstruction error doubles as a novelty score | Needs more labelled spectra than we have for most types |
| Type model | Logistic regression | `sklearn.linear_model.LogisticRegression` | The baseline every other model must beat | None. Always run it |
| Second opinion | Nearest neighbours in the library | `sklearn.neighbors.KNeighborsClassifier` | Uses individual labelled spectra, so it keeps rare variants that an average hides | Slow on large libraries, sensitive to noisy bands |
| Second opinion | Component templates | `sklearn.decomposition.NMF` | A few building-block spectra per type can fit mixed objects | Needs complete spectra with no empty bands |
| Merge | Plain average of probabilities | `numpy.mean` | Nothing to overfit | Ignores which model is better for which type |
| Merge | Best single model, no merge | none | Simplest to explain | Loses the disagreement signal |
| Calibration | Sigmoid scaling | `CalibratedClassifierCV(method="sigmoid")` | Steadier than isotonic when the held-out set is small | Less flexible |
| Calibration | Temperature scaling | a few lines, written by us | One number to fit, standard for neural networks | Only for models that output logits |
| Plausible types | MAPIE | `mapie` | A maintained conformal library with adaptive sets | `[VERIFIED PyPI mapie==1.6.0 BSD-3-Clause: 1.x broke 0.x MapieClassifier -> SplitConformalClassifier API; keep our custom numpy sets]` |
| Unusual objects | Local outlier factor | `sklearn.neighbors.LocalOutlierFactor(novelty=True)` | Finds objects that sit in thin regions near dense groups | Sensitive to the neighbour count |
| Unusual objects | One-class SVM | `sklearn.svm.OneClassSVM` | A learned boundary around normal objects | Slow, needs scaled inputs |
| Unusual objects | Template residual χ² | written by us | Direct and readable: the best known type still fits badly | Blends and variables also fit badly, so screen those first |
| Real or artefact | Small convolutional network on the image cutout | PyTorch | Sees the shape of the source in pixels. Transient surveys use this approach `[FROM MEMORY]` | Needs thousands of labelled cutouts. Stretch only |
| Molecule readings | Gaussian-process continuum | `sklearn.gaussian_process.GaussianProcessRegressor` | Gives an error on the baseline itself. The SPHEREx ice team uses it | Slower, needs a sensible kernel |
| Settings search | Optuna | `optuna` | Finds good tree settings automatically | Tune on the calibrate split only, never on the test split |

### 13.3 How the winner is chosen

1. Every candidate uses the same split by sky tile and the same gold test set.
2. Scores, in this order: balanced accuracy (the mean of per-type recall), log loss, calibration error.
3. Choose on the calibrate split. Run the test split once, at the end, for the reported numbers.
4. A more complex model replaces a simpler one only if it gains more than one point of balanced accuracy and the gain holds in every brightness bin.
5. Estimate the noise first: resample the test set 200 times and note how much the baseline score moves. Treat a gain smaller than that movement as zero.
6. Rare types: use class weights (`sample_weight` or `class_weight="balanced"`). Report each type's recall on its own.

Starting settings for XGBoost on a few thousand rows `[ESTIMATE, tune from here]`: 300 to 600 trees, depth 4 to 6, learning rate 0.05, row and column sampling 0.8, early stopping on the calibrate split.
