# Machine-learning datasets

This directory owns reproducible preparation of the Phantom Worlds ML datasets.
Raw downloads and generated datasets belong in the ignored `data/` directory.

The delivery includes source checksums and citations, spectra with wavelengths,
units, uncertainties and coverage masks, labels with evidence and grade, survey
matches with epochs and match distances, spatially grouped splits, and a quality
report. Download completion alone does not establish training readiness.

Preparation follows T01-M, T43a and T43b. It begins with SPIFF and UltracoolSheet,
then SPLICES, field selection, DR1 cube tiles, per-field catalogue queries and
calibration products. Cube and QR2/DR1 calibration checks gate mixed-release
training. Gold labels alone enter reported evaluation; silver labels train at
half weight. The five showcase targets are reserved scientific checks.

The final report must identify missing classes, ambiguous matches, unavailable
sources and unpassed calibration checks. It must not silently substitute model
labels for spectroscopic truth or invent uncertainties for cube spectra.
