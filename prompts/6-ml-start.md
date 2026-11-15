# Prompt 6: start the ML lane

Your lane is ML. Read docs/PROJECT-CONTEXT.md section 9 in full, and docs/DATA-LINKS.md sections 6, 7, 11 and 12.

Work in this order, one pull request per task:

1. T01-M. Scaffold engine/phantom/ml/ and ml/. Download by script, into data/, everything in docs/DATA-LINKS.md section 12 rows 1 to 4. Record each file in data/manifest.csv with size, checksum and source URL. Resolve K18 (read the SPIFF README and tables, record the CSV columns) and K20 (SPLICES class values from the release notes).
2. Pick the cube tiles. Count SPLICES rows per order-5 tile to choose the star-forming field. Run the DESI tile count query after checking K29. Record the chosen tiles in docs/decisions.md.
3. T43a. Build the label table: one row per source with type, label source and grade. Gold for testing, silver at half weight. Report counts per type and grade.
4. T43b. Training spectra. Ingest SPIFF. Extract cube spectra for labelled sources. Run the two checks in section 9.4: cube against our own single-frame spectra for 20 bright isolated stars (K22), and QR2 against DR1 for sources in both.
5. T42 and T43c. Features and molecule readings with resampled errors and refusal reasons.
6. T43d to T43g. Template match, XGBoost feature trees (E0, molecule readings alone) and spectrum trees (E2), the other experts, the input ladder of section 9.11, stacking, calibration, conformal sets, the three stored results, feature contributions, deciding bands, novelty checks.
7. T45-M1. Real-or-artefact model from injections and flagged artefacts.
8. Write a model card per model in ml/ and publish only models that pass section 9.9.

Choose models by section 9.11: first picks, then the alternatives in its test list, scored on the calibrate split, test split run once at the end. Report every score per brightness bin.
