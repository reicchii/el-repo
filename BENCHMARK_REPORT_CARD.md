# Phantom Worlds — 5-Target Benchmark Report Card

Generated 2026-11-14T07:15:39.764289+00:00

This is the **live M1..M3 pipeline output** on the five benchmark targets. It replaces the Step-1 Estimated placeholder numbers.

## 1. Release gates (Section 9)

| Metric | Value | Pass mark | Status |
|---|---|---|---|
| Level-1 balanced accuracy (gold test, S/N>10) | 1.000 | >= 0.8 | ✅ |
| Calibration error (ECE) | 0.0061 | <= 0.05 | ✅ |
| Conformal 90% coverage (empirical, gold test) | 0.941 | 88–92% | ⚠️ |
| Ultracool subtype within 2 | *(needs SPIFF held-out sample — not yet ingested)* | 80% | — |

> [!NOTE]
> Conformal coverage is measured on the synthetic gold test split. Balanced accuracy and ECE are only meaningful for the synthetic corpus; the SPIFF Zenodo / SPLICES ingestion path (`dataset.append_external`) is a stub, so no external-validated numbers are claimed here.

**spectrum_alone**: balanced accuracy 0.993, ECE 0.0207.

## 2. Five-target side-by-side

| Target | Expected (Section 8) | Model (all_data) | e1 | e2 | Conf | Discovery | Novelty | Artefact |
|---|---|---|---|---|---|---|---|---|
| Barnards_Star | Star, cool dwarf, no methane dip | Star (50%) | Star | Galaxy | 99% | U2 | 0 | 0.99 |
| Epsilon_Indi_B | Ultracool dwarf, T type, methane dip | Ultracool dwarf (50%) | Evolved giant star | Ultracool dwarf | 100% | U2 | 77 | 1.00 |
| R_Draconis | Evolved giant, variable (overflow) | Unclassified (49%) | Evolved giant star | Ultracool dwarf | 96% | U4 | 0 | 1.00 |
| RW_Aurigae | Young star, variable (blended pair) | Unclassified (49%) | Evolved giant star | Ultracool dwarf | 94% | U4 | 0 | 1.00 |
| WISE_0855 | Ultracool dwarf Y, or Unclassified with a stated reason | Ultracool dwarf (50%) | Star | Ultracool dwarf | 100% | U1 | 63 | 0.98 |

## 3. Layer-2/3 detail (all_data)

### Barnards_Star

- top class: **Star** (unclassified: False)
- probabilities: {"Star": 0.9901898305632639, "Ultracool dwarf": 0.006354880551188438, "Young star": 0.0, "Evolved giant star": 0.003455288885547653, "Galaxy": 0.0, "Active galaxy or quasar": 0.0}
- conformal set: ['Star']
- deciding bands: ['0.91 µm measured', '0.93 µm measured', '0.95 µm measured']
### Epsilon_Indi_B

- top class: **Ultracool dwarf** (unclassified: False)
- probabilities: {"Star": 0.0, "Ultracool dwarf": 1.0, "Young star": 0.0, "Evolved giant star": 0.0, "Galaxy": 0.0, "Active galaxy or quasar": 0.0}
- conformal set: ['Ultracool dwarf']
- deciding bands: ['3.14 µm measured', '3.22 µm measured', '3.06 µm measured']
### R_Draconis

- top class: **Unclassified** (unclassified: True)
- probabilities: {"Star": 0.0, "Ultracool dwarf": 0.9590551260615833, "Young star": 0.0, "Evolved giant star": 0.033674539964449565, "Galaxy": 0.0, "Active galaxy or quasar": 0.007270333973967219}
- conformal set: []
- deciding bands: ['3.14 µm measured', '3.22 µm measured', '3.31 µm measured']
### RW_Aurigae

- top class: **Unclassified** (unclassified: True)
- probabilities: {"Star": 0.0, "Ultracool dwarf": 0.9381589306482889, "Young star": 0.023703946941756687, "Evolved giant star": 0.03153619467503961, "Galaxy": 0.0, "Active galaxy or quasar": 0.006600927734914819}
- conformal set: []
- deciding bands: ['3.31 µm measured', '3.22 µm measured', '3.14 µm measured']
### WISE_0855

- top class: **Ultracool dwarf** (unclassified: False)
- probabilities: {"Star": 0.0, "Ultracool dwarf": 1.0, "Young star": 0.0, "Evolved giant star": 0.0, "Galaxy": 0.0, "Active galaxy or quasar": 0.0}
- conformal set: ['Ultracool dwarf']
- deciding bands: ['0.76 µm not measured', '0.78 µm not measured', '0.80 µm not measured']
