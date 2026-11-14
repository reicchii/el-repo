import ast
import csv
import json
import math
import os
import re
import sys
import tempfile
import unittest
from unittest import mock

import numpy as np
from fastapi.testclient import TestClient


ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTRACTS_DIR = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "hour0_contracts")
CSV_DIR = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "csv_tables")


def _load_spectra_table():
    path = os.path.join(CSV_DIR, "spherex_102_band_spectra.csv")
    with open(path, encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    wavelengths = np.array([float(r["wavelength_um"]) for r in rows], dtype=np.float64)
    bandwidths = np.array([float(r["bandwidth_um"]) for r in rows], dtype=np.float64)
    targets = {
        "WISE_0855": np.array([float(r["WISE_0855_uJy"]) for r in rows], dtype=np.float64),
        "RW_Aurigae": np.array([float(r["RW_Aurigae_uJy"]) for r in rows], dtype=np.float64),
        "Eps_Indi_B": np.array([float(r["Eps_Indi_B_uJy"]) for r in rows], dtype=np.float64),
        "Barnards_Star": np.array([float(r["Barnards_Star_uJy"]) for r in rows], dtype=np.float64),
        "R_Draconis": np.array([float(r["R_Draconis_uJy"]) for r in rows], dtype=np.float64),
    }
    return wavelengths, bandwidths, targets


class TestDependencyLockfile(unittest.TestCase):
    @staticmethod
    def _read_lock_entries(lock_path):
        with open(lock_path, encoding="utf-8") as f:
            raw_lock = f.read()
        logical = re.sub(r"\\\r?\n\s*", " ", raw_lock).splitlines()
        return [line.strip() for line in logical if line.strip() and not line.strip().startswith("#")]

    def test_requirements_and_pinned_lockfile_exist(self):
        req_path = os.path.join(ROOT_DIR, "requirements.txt")
        lock_path = os.path.join(ROOT_DIR, "requirements.lock")
        self.assertTrue(os.path.exists(req_path), "Missing requirements.txt")
        self.assertTrue(os.path.exists(lock_path), "Missing requirements.lock")

        with open(req_path, encoding="utf-8") as f:
            req_lines = [l.strip() for l in f if l.strip() and not l.strip().startswith("#")]
        lock_entries = self._read_lock_entries(lock_path)

        for core_pkg in ("numpy", "pandas", "astropy", "pyvo", "requests", "urllib3", "scikit-learn", "fastapi", "pytest"):
            self.assertTrue(any(l.lower().startswith(core_pkg) for l in req_lines), f"{core_pkg} missing in requirements.txt")
            self.assertTrue(any(l.lower().startswith(f"{core_pkg}==") for l in lock_entries), f"{core_pkg} not == pinned in requirements.lock")

        pin_pattern = re.compile(r"^[A-Za-z0-9_.-]+==[A-Za-z0-9_.+!-]+(?:\s+--hash=sha256:[0-9a-f]{64})+$")
        for line in lock_entries:
            self.assertRegex(line, pin_pattern, f"Unpinned or unhashed line in lockfile: {line}")

    def test_no_unused_bloat_in_requirements_lock_or_script_pip_install(self):
        import_to_dist = {"sklearn": "scikit-learn"}
        runner_extras = {"pytest", "httpx", "uvicorn"}

        def _third_party_imports(tree, ignore_mods):
            dists = set()
            for node in ast.walk(tree):
                mods = []
                if isinstance(node, ast.Import):
                    mods = [alias.name.split(".")[0] for alias in node.names]
                elif isinstance(node, ast.ImportFrom) and node.module:
                    mods = [node.module.split(".")[0]]
                for mod in mods:
                    if mod not in sys.stdlib_module_names and mod not in ignore_mods:
                        dists.add(import_to_dist.get(mod, mod).lower())
            return dists

        imported_dists = set()
        for subroot in (
            os.path.join(ROOT_DIR, "phantom_worlds"),
            os.path.join(ROOT_DIR, "ml"),
            os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit"),
        ):
            for walk_root, dirnames, filenames in os.walk(subroot):
                dirnames[:] = [d for d in dirnames if d not in {"__pycache__", ".pytest_cache", "data_real"}]
                for fname in filenames:
                    if not fname.endswith(".py"):
                        continue
                    with open(os.path.join(walk_root, fname), encoding="utf-8") as f:
                        tree = ast.parse(f.read(), filename=fname)
                    imported_dists |= _third_party_imports(
                        tree, {"phantom_worlds", "ml", "download_real_spherex_gaia", "build_ml_catalog"}
                    )

        with open(os.path.join(ROOT_DIR, "requirements.txt"), encoding="utf-8") as f:
            req_names = {
                re.split(r"[<>=!~\[]", line.strip(), maxsplit=1)[0].strip().lower()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            }
        self.assertEqual(
            req_names,
            imported_dists | runner_extras,
            f"requirements.txt drifted from actual imports + runtime/test runners: extra={req_names - (imported_dists | runner_extras)}, missing={(imported_dists | runner_extras) - req_names}",
        )

        lock_names = {
            entry.split("==", 1)[0].lower()
            for entry in self._read_lock_entries(os.path.join(ROOT_DIR, "requirements.lock"))
        }
        unused_bloat = {"astroquery", "boto3", "botocore", "s3fs", "s3transfer", "jmespath", "beautifulsoup4", "keyring"}
        self.assertEqual(lock_names & unused_bloat, set(), f"Unused transitive dependencies locked: {lock_names & unused_bloat}")

        script_path = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "scripts", "download_real_spherex_gaia.py")
        with open(script_path, encoding="utf-8") as f:
            script_tree = ast.parse(f.read(), filename="download_real_spherex_gaia.py")
        doc = ast.get_docstring(script_tree) or ""
        pip_match = re.search(r"pip install\s+([^\r\n]+)", doc)
        self.assertIsNotNone(pip_match, "Expected pip install guidance in downloader docstring")
        doc_pkgs = pip_match.group(1).split()
        self.assertEqual(set(doc_pkgs), _third_party_imports(script_tree, {"phantom_worlds"}))

    def test_lockfile_enforces_sha256_hashes_and_non_vulnerable_urllib3(self):
        from importlib import metadata as importlib_metadata

        def _ver_tuple(ver):
            return tuple(int(part) for part in ver.split(".")[:3])

        with open(os.path.join(ROOT_DIR, "requirements.txt"), encoding="utf-8") as f:
            req_text = f.read().lower()
        self.assertIn("urllib3>=2.6.3", req_text)

        entries = self._read_lock_entries(os.path.join(ROOT_DIR, "requirements.lock"))
        self.assertGreaterEqual(len(entries), 40)

        urllib3_ver = next((e.split("==", 1)[1].split()[0] for e in entries if e.lower().startswith("urllib3==")), None)
        self.assertIsNotNone(urllib3_ver)
        self.assertGreaterEqual(_ver_tuple(urllib3_ver), (2, 6, 3))
        self.assertGreaterEqual(_ver_tuple(importlib_metadata.version("urllib3")), (2, 6, 3))


class TestCoreContractsAndCalibration(unittest.TestCase):
    def test_decode_calibrated_pack_handles_negative_residuals_and_quality_masks(self):
        from phantom_worlds.contracts import decode_calibrated_pack, detector_visit_stacks

        manifest = {
            "pack_binary_layout": {
                "dtype": "uint16",
                "endianness": "little",
                "compression": "none",
                "shape": [2, 1, 2, 2],
                "flux_scale": 0.01,
                "flux_zero": -10.0,
                "invalid_u16": 65535,
            },
            "quality_mask_layout": {
                "dtype": "uint8",
                "compression": "none",
                "shape": [2, 1, 2, 2],
                "flag_bits": {"OK": 0, "IRSA_REJECTED": 1, "OVERFLOW_SATURATED": 2, "EDGE_MASKED": 4},
            },
        }
        # Visit 0: [500 (-5.0), 1500 (+5.0), 65535 (invalid), 2000 (+10.0, OVERFLOW bit=2)]
        # Visit 1: [600 (-4.0), 1000 (0.0, IRSA_REJECTED bit=1), 1200 (+2.0), 2000 (+10.0, OVERFLOW bit=2)]
        pack_arr = np.array([[[[500, 1500], [65535, 2000]]], [[[600, 1000], [1200, 2000]]]], dtype="<u2")
        mask_arr = np.array([[[[0, 0], [0, 2]]], [[[0, 1], [0, 2]]]], dtype=np.uint8)

        flux = decode_calibrated_pack(pack_arr.tobytes(), mask_arr.tobytes(), manifest)
        self.assertEqual(flux.shape, (2, 1, 2, 2))
        self.assertAlmostEqual(flux[0, 0, 0, 0], -5.0, places=5)
        self.assertTrue(np.isnan(flux[0, 0, 1, 0]))  # invalid_u16 masked
        self.assertTrue(np.isnan(flux[0, 0, 1, 1]))  # OVERFLOW_SATURATED masked
        self.assertTrue(np.isnan(flux[1, 0, 0, 1]))  # IRSA_REJECTED masked

        stack = detector_visit_stacks(flux)
        self.assertEqual(stack.shape, (1, 2, 2))
        self.assertAlmostEqual(stack[0, 0, 0], -4.5, places=5)
        self.assertAlmostEqual(stack[0, 0, 1], 5.0, places=5)
        self.assertAlmostEqual(stack[0, 1, 0], 2.0, places=5)
        self.assertTrue(np.isnan(stack[0, 1, 1]))

    def test_decode_rejects_mismatched_byte_lengths(self):
        from phantom_worlds.contracts import decode_calibrated_pack, load_manifest

        manifest = load_manifest(CONTRACTS_DIR)
        with self.assertRaises(ValueError):
            decode_calibrated_pack(b"\x00" * 10, b"\x00" * 73728, manifest)

    def test_real_hour0_pack_and_mask_decode_and_astrometric_propagation(self):
        from phantom_worlds.contracts import load_patch_arrays, propagate_position

        manifest, flux, mask = load_patch_arrays(CONTRACTS_DIR)
        self.assertEqual(flux.shape, tuple(manifest["pack_binary_layout"]["shape"]))
        self.assertEqual(mask.shape, tuple(manifest["quality_mask_layout"]["shape"]))
        self.assertLess(float(np.nanmin(flux)), 0.0)

        ra26, dec26 = propagate_position(133.795129, -7.245147, -8118.0, 680.0, 26.0)
        self.assertAlmostEqual(ra26, 133.736027, places=5)
        self.assertAlmostEqual(dec26, -7.240236, places=5)

    def test_decode_calibrated_pack_masks_edge_masked_bit_to_nan(self):
        from phantom_worlds.contracts import decode_calibrated_pack, load_patch_arrays

        manifest = {
            "pack_binary_layout": {
                "dtype": "uint16",
                "endianness": "little",
                "compression": "none",
                "shape": [1, 1, 2, 2],
                "flux_scale": 0.01,
                "flux_zero": -10.0,
                "invalid_u16": 65535,
            },
            "quality_mask_layout": {
                "dtype": "uint8",
                "compression": "none",
                "shape": [1, 1, 2, 2],
                "flag_bits": {"OK": 0, "IRSA_REJECTED": 1, "OVERFLOW_SATURATED": 2, "EDGE_MASKED": 4},
            },
        }
        pack_arr = np.array([[[[1200, 1300], [1400, 1500]]]], dtype="<u2")
        mask_arr = np.array([[[[0, 4], [5, 6]]]], dtype=np.uint8)
        flux = decode_calibrated_pack(pack_arr.tobytes(), mask_arr.tobytes(), manifest)
        self.assertAlmostEqual(flux[0, 0, 0, 0], 2.0, places=5)
        self.assertTrue(np.isnan(flux[0, 0, 0, 1]))  # EDGE_MASKED (bit 4)
        self.assertTrue(np.isnan(flux[0, 0, 1, 0]))  # IRSA_REJECTED | EDGE_MASKED (5)
        self.assertTrue(np.isnan(flux[0, 0, 1, 1]))  # OVERFLOW_SATURATED | EDGE_MASKED (6)

        _, real_flux, real_mask = load_patch_arrays(CONTRACTS_DIR)
        edge_pixels = (real_mask & 4) != 0
        self.assertTrue(np.all(np.isnan(real_flux[edge_pixels])))

    def test_detector_visit_stacks_is_warning_free_without_catch_warnings(self):
        import inspect
        import warnings
        from phantom_worlds.contracts import detector_visit_stacks

        self.assertNotIn("catch_warnings", inspect.getsource(detector_visit_stacks))
        all_nan = np.full((2, 1, 2, 2), np.nan, dtype=np.float64)
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")
            stack = detector_visit_stacks(all_nan)
        self.assertEqual(caught, [])
        self.assertEqual(stack.shape, (1, 2, 2))
        self.assertTrue(np.all(np.isnan(stack)))

    def test_load_patch_arrays_enforces_commonpath_and_bounded_size_before_reading(self):
        import json
        import tempfile
        from unittest import mock
        from phantom_worlds.contracts import load_patch_arrays

        with tempfile.TemporaryDirectory() as tmpdir:
            manifest = {
                "target_id": "TGT-02",
                "pack_binary_layout": {
                    "file": "pack.bin",
                    "dtype": "uint16",
                    "endianness": "little",
                    "compression": "none",
                    "shape": [1, 1, 2, 2],
                    "flux_scale": 0.01,
                    "flux_zero": 0.0,
                    "invalid_u16": 65535,
                },
                "quality_mask_layout": {
                    "file": "mask.bin",
                    "dtype": "uint8",
                    "compression": "none",
                    "shape": [1, 1, 2, 2],
                },
            }
            with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            with open(os.path.join(tmpdir, "pack.bin"), "wb") as fp:
                fp.write(b"\x00" * 16)  # mismatched size (expected 8 bytes)
            with open(os.path.join(tmpdir, "mask.bin"), "wb") as fm:
                fm.write(b"\x00" * 4)

            with self.assertRaisesRegex(ValueError, "size mismatch"):
                load_patch_arrays(tmpdir)

            # Reject oversized manifest claims before attempting any binary open/read.
            manifest["pack_binary_layout"]["shape"] = [10000, 6, 64, 64]
            with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            with self.assertRaisesRegex(ValueError, "out of bounds"):
                load_patch_arrays(tmpdir)

            # Reject path escape via manifest.json file entry.
            manifest["pack_binary_layout"]["shape"] = [1, 1, 2, 2]
            manifest["pack_binary_layout"]["file"] = "../outside.bin"
            with open(os.path.join(tmpdir, "manifest.json"), "w", encoding="utf-8") as f:
                json.dump(manifest, f)
            with self.assertRaisesRegex(ValueError, "escapes base directory"):
                load_patch_arrays(tmpdir)

            # Reject non-positive manifest byte expectations without reading disk.
            manifest["pack_binary_layout"]["file"] = "pack.bin"
            manifest["pack_binary_layout"]["shape"] = [1, 0, 2, 2]
            with mock.patch("builtins.open", side_effect=AssertionError("should validate shape first")):
                with self.assertRaises(ValueError):
                    load_patch_arrays(tmpdir, manifest=manifest)

    def test_decode_rejects_bad_headers_and_propagate_handles_wrap_and_poles(self):
        from phantom_worlds.contracts import decode_calibrated_pack, load_manifest, propagate_position

        manifest = load_manifest(CONTRACTS_DIR)
        bad_comp = json.loads(json.dumps(manifest))
        bad_comp["pack_binary_layout"]["compression"] = "zlib"
        with self.assertRaises(ValueError):
            decode_calibrated_pack(b"\x00", b"\x00", bad_comp)

        bad_end = json.loads(json.dumps(manifest))
        bad_end["pack_binary_layout"]["endianness"] = "big"
        with self.assertRaises(ValueError):
            decode_calibrated_pack(b"\x00", b"\x00", bad_end)

        bad_shape = json.loads(json.dumps(manifest))
        bad_shape["quality_mask_layout"]["shape"] = [1, 1, 1, 1]
        with self.assertRaises(ValueError):
            decode_calibrated_pack(b"\x00", b"\x00", bad_shape)

        # Eastward wrap across 360->0 deg and northern polar clamp at +90 deg
        ra_wrap, dec_ok = propagate_position(359.999, 0.0, 7200.0, 0.0, 1.0)
        self.assertAlmostEqual(ra_wrap, 0.001, places=4)
        self.assertAlmostEqual(dec_ok, 0.0, places=6)

        ra_pole, dec_clamp = propagate_position(10.0, 89.9999, 100.0, 3600.0, 1.0)
        self.assertTrue(0.0 <= ra_pole < 360.0)
        self.assertEqual(dec_clamp, 90.0)

    def test_propagate_position_rejects_nonfinite_and_out_of_range_inputs(self):
        from phantom_worlds.contracts import propagate_position

        for bad_args in (
            (10.0, 0.0, 0.0, float("nan"), 1.0),
            (10.0, 0.0, float("nan"), 0.0, 1.0),
            (float("nan"), 0.0, 0.0, 0.0, 1.0),
            (10.0, float("inf"), 0.0, 0.0, 1.0),
            (10.0, 0.0, 0.0, 0.0, float("inf")),
            (10.0, 91.0, 0.0, 0.0, 1.0),
            (10.0, -91.0, 0.0, 0.0, 1.0),
            (True, 0.0, 0.0, 0.0, 1.0),
        ):
            with self.assertRaises(ValueError, msg=f"propagate_position accepted invalid args {bad_args!r}"):
                propagate_position(*bad_args)


class TestMLPipelineLayer1To3(unittest.TestCase):
    def test_molecule_readings_measure_ice_dips_and_refuse_blended_or_variable(self):
        from phantom_worlds.ml_pipeline import compute_molecule_readings

        wl, bw, spectra = _load_spectra_table()
        # RW Aurigae fixture spectrum has clear 3.05 um H2O and 4.26 um CO2 dips
        rw_clean = compute_molecule_readings(
            wl,
            bw,
            spectra["RW_Aurigae"],
            flux_err=spectra["RW_Aurigae"] * 0.03,
            blend_share=0.10,
            is_variable=False,
            rng_seed=42,
        )
        self.assertEqual(rw_clean["status"], "MEASURED")
        self.assertGreater(rw_clean["features"]["H2O_ice_3_05"]["integrated_tau"], 0.0)
        self.assertGreater(rw_clean["features"]["CO2_4_26"]["integrated_tau"], 0.0)
        self.assertLessEqual(
            rw_clean["features"]["H2O_ice_3_05"]["p16"],
            rw_clean["features"]["H2O_ice_3_05"]["p84"],
        )

        blended = compute_molecule_readings(wl, bw, spectra["RW_Aurigae"], blend_share=0.62, is_variable=False)
        self.assertEqual(blended["status"], "REFUSED")
        self.assertIn("blend_share", blended["refusal_reason"])

        variable = compute_molecule_readings(wl, bw, spectra["RW_Aurigae"], blend_share=0.10, is_variable=True)
        self.assertEqual(variable["status"], "REFUSED")
        self.assertIn("variable", variable["refusal_reason"])

        too_few = compute_molecule_readings(
            wl[:2], bw[:2], spectra["RW_Aurigae"][:2], blend_share=0.10, is_variable=False
        )
        self.assertEqual(too_few["status"], "REFUSED")

    def test_classifier_combiner_gates_disagreement_cap_and_conformal_sets(self):
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline

        wl, bw, spectra = _load_spectra_table()
        rng = np.random.default_rng(7)
        base_classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Evolved giant star": spectra["R_Draconis"],
        }
        X_train, y_train = [], []
        for label, base in base_classes.items():
            for _ in range(18):
                scale = rng.uniform(0.7, 1.3)
                noise = rng.normal(0.0, 0.02 * np.maximum(base, 0.2))
                X_train.append(np.maximum(base * scale + noise, 0.01))
                y_train.append(label)

        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=base_classes, random_state=7)
        pipe.fit(np.array(X_train), np.array(y_train), blend_shares=np.full(len(y_train), 0.08))

        pred = pipe.predict_one(spectra["RW_Aurigae"], blend_share=0.10, parallax_snr=10.0)
        self.assertIn("spectrum_alone", pred)
        self.assertIn("all_data", pred)
        self.assertEqual(pred["all_data"]["top_class"], "Young star with ice or dust")
        self.assertGreaterEqual(len(pred["all_data"]["conformal_set"]), 1)
        self.assertEqual(pred["novelty"]["status"], "OK")

        # Contamination screen runs BEFORE novelty flagging
        contaminated = pipe.predict_one(spectra["WISE_0855"] * 50.0, blend_share=0.65, is_variable=True)
        self.assertEqual(contaminated["novelty"]["status"], "CONTAMINATION_SCREENED")

        # Disagreement rule: when E1 template and E2 trees disagree, confidence <= 0.50 -> Unclassified
        with mock.patch.object(pipe, "_predict_template_class", return_value=("Galaxy", {})):
            with mock.patch.object(
                pipe,
                "_predict_tree_probs",
                return_value={
                    "Star": 0.90,
                    "Ultracool dwarf": 0.04,
                    "Young star with ice or dust": 0.03,
                    "Evolved giant star": 0.03,
                },
            ):
                disagreed = pipe.predict_one(spectra["Barnards_Star"], blend_share=0.05)
                self.assertLessEqual(disagreed["all_data"]["confidence"], 0.50)
                self.assertEqual(disagreed["all_data"]["top_class"], "Unclassified")

    def test_masked_nan_bands_do_not_bias_chi2_or_trigger_false_novelty(self):
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline

        wl, bw, spectra = _load_spectra_table()
        rng = np.random.default_rng(11)
        base_classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Evolved giant star": spectra["R_Draconis"],
        }
        X_train, y_train = [], []
        for label, base in base_classes.items():
            for _ in range(18):
                scale = rng.uniform(0.7, 1.3)
                noise = rng.normal(0.0, 0.02 * np.maximum(base, 0.2))
                X_train.append(np.maximum(base * scale + noise, 0.01))
                y_train.append(label)

        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=base_classes, random_state=11)
        pipe.fit(np.array(X_train), np.array(y_train), blend_shares=np.full(len(y_train), 0.05))

        star_masked = spectra["Barnards_Star"].copy()
        star_masked[:20] = np.nan

        chi2_star = pipe._reduced_chi2(pipe._normalize(star_masked), pipe.template_library["Star"])
        self.assertLess(chi2_star, 0.1)

        pred = pipe.predict_one(star_masked, blend_share=0.05, parallax_snr=10.0)
        self.assertEqual(pred["spectrum_alone"]["template_class"], "Star")
        self.assertNotEqual(pred["novelty"]["status"], "NOVEL")

        mostly_masked = np.full_like(spectra["Barnards_Star"], np.nan)
        mostly_masked[:2] = [100.0, 95.0]
        pred_sparse = pipe.predict_one(mostly_masked, blend_share=0.05)
        self.assertEqual(pred_sparse["all_data"]["top_class"], "Unclassified")
        self.assertEqual(pred_sparse["novelty"]["status"], "CONTAMINATION_SCREENED")

    def test_molecule_readings_refuse_per_feature_under_3_bands_and_recover_wise0855_co(self):
        from phantom_worlds.ml_pipeline import MOLECULE_WINDOWS, compute_molecule_readings

        wl, bw, spectra = _load_spectra_table()
        for feat_name, (lo, hi) in MOLECULE_WINDOWS.items():
            band_count = int(np.count_nonzero((wl >= lo) & (wl <= hi)))
            self.assertGreaterEqual(band_count, 3, f"{feat_name} covers only {band_count} bands")

        rw_partial = spectra["RW_Aurigae"].copy()
        co2_idx = np.where((wl >= 4.18) & (wl <= 4.35))[0]
        rw_partial[co2_idx[2:]] = np.nan  # leave only 2 valid positive bands in CO2_4_26
        res_partial = compute_molecule_readings(wl, bw, rw_partial, rng_seed=0)
        self.assertEqual(res_partial["status"], "MEASURED")
        self.assertEqual(res_partial["features"]["CO2_4_26"]["status"], "REFUSED")
        self.assertIsNone(res_partial["features"]["CO2_4_26"]["integrated_tau"])
        self.assertIn("3", res_partial["features"]["CO2_4_26"]["refusal_reason"])
        self.assertGreater(res_partial["features"]["H2O_ice_3_05"]["integrated_tau"], 0.0)
        self.assertGreater(res_partial["features"]["CO_4_67"]["integrated_tau"], 0.0)

        sparse_windows = np.array([2.60, 2.95, 3.05, 4.95])
        sparse_bw = np.full(4, 0.08)
        sparse_flux = np.array([100.0, 90.0, 85.0, 110.0])
        res_all_sparse = compute_molecule_readings(sparse_windows, sparse_bw, sparse_flux, rng_seed=0)
        self.assertEqual(res_all_sparse["status"], "REFUSED")
        self.assertIn("3", res_all_sparse["refusal_reason"])

        wise_res = compute_molecule_readings(wl, bw, spectra["WISE_0855"], rng_seed=0)
        self.assertEqual(wise_res["status"], "MEASURED")
        self.assertGreater(wise_res["features"]["CO_4_67"]["integrated_tau"], 0.0)
        self.assertGreater(wise_res["features"]["CH4_3_3"]["integrated_tau"], 0.0)

        eps_err = np.maximum(0.05 * spectra["Eps_Indi_B"], 0.2)
        eps_res = compute_molecule_readings(wl, bw, spectra["Eps_Indi_B"], flux_err=eps_err, rng_seed=0)
        barnard_res = compute_molecule_readings(wl, bw, spectra["Barnards_Star"], rng_seed=0)
        self.assertGreater(eps_res["features"]["CH4_3_3"]["p16"], 0.0)
        self.assertLessEqual(barnard_res["features"]["CH4_3_3"]["integrated_tau"], 0.0)

    def test_pipeline_no_parallax_leak_in_spectrum_alone_heldout_isotonic_and_e1_e2_separation(self):
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline

        wl, bw, spectra = _load_spectra_table()
        galaxy_tmpl = 40.0 + 30.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 2
        classes_5 = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Evolved giant star": spectra["R_Draconis"],
            "Galaxy": galaxy_tmpl,
        }
        rng = np.random.default_rng(17)
        X_train, y_train = [], []
        for label, base in classes_5.items():
            for _ in range(20):
                scale = rng.uniform(0.7, 1.3)
                noise = rng.normal(0.0, 0.02 * np.maximum(base, 0.2))
                X_train.append(np.maximum(base * scale + noise, 0.01))
                y_train.append(label)

        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=classes_5, random_state=17)
        pipe.fit(np.array(X_train), np.array(y_train), blend_shares=np.full(len(y_train), 0.05))

        # E2 boosted trees must use spectral bands only (no E1 chi2 features leaked into E2)
        self.assertEqual(pipe.tree_model.n_features_in_, len(wl))
        # Isotonic calibration + disjoint held-out conformal calibration split
        self.assertTrue(getattr(pipe, "calibrators_", None))
        self.assertGreater(getattr(pipe, "calibration_size_", 0), 0)
        self.assertLess(pipe.calibration_size_, len(y_train))

        # High parallax SNR must zero Galaxy only in all_data, never inside spectrum_alone
        pred_gal = pipe.predict_one(galaxy_tmpl * 1.1, blend_share=0.05, parallax_snr=10.0)
        self.assertEqual(pred_gal["spectrum_alone"]["top_class"], "Galaxy")
        self.assertIn("Galaxy", pred_gal["spectrum_alone"]["conformal_set"])
        self.assertTrue(pred_gal["all_data"]["parallax_gate_applied"])
        self.assertNotEqual(pred_gal["all_data"]["top_class"], "Galaxy")
        self.assertNotIn("Galaxy", pred_gal["all_data"]["conformal_set"])

        # Disagreement check must compare E1 (template) vs raw E2 (trees), not blended meta probs
        orig_meta_predict = pipe.meta_combiner.predict_proba
        pipe.meta_combiner.predict_proba = lambda _x: np.array(
            [[0.95 if c == "Star" else 0.0125 for c in pipe.meta_combiner.classes_]]
        )
        orig_tree_probs = pipe._predict_tree_probs
        pipe._predict_tree_probs = lambda _f: {
            c: (0.85 if c == "Young star with ice or dust" else 0.0375) for c in pipe.classes_
        }
        try:
            pred_disagree = pipe.predict_one(spectra["Barnards_Star"], blend_share=0.05)
        finally:
            pipe.meta_combiner.predict_proba = orig_meta_predict
            pipe._predict_tree_probs = orig_tree_probs

        self.assertLessEqual(pred_disagree["spectrum_alone"]["confidence"], 0.50)
        self.assertEqual(pred_disagree["spectrum_alone"]["top_class"], "Unclassified")

    def test_molecule_readings_withhold_missing_error_bars_and_reject_corrupt_inputs(self):
        from phantom_worlds.ml_pipeline import compute_molecule_readings

        wl, bw, spectra = _load_spectra_table()
        rw = spectra["RW_Aurigae"]

        # Without flux_err, never fabricate zero-width p16 == integrated_tau == p84 intervals
        no_err = compute_molecule_readings(wl, bw, rw, flux_err=None, blend_share=0.30, is_variable=False)
        self.assertEqual(no_err["status"], "MEASURED")
        h2o = no_err["features"]["H2O_ice_3_05"]
        self.assertIsNotNone(h2o["integrated_tau"])
        self.assertFalse(h2o["uncertainty_available"])
        self.assertIsNone(h2o["median"])
        self.assertIsNone(h2o["p16"])
        self.assertIsNone(h2o["p84"])

        # Exact blend_share boundary (> 0.3 refused, == 0.30 permitted)
        over_blend = compute_molecule_readings(wl, bw, rw, blend_share=0.301, is_variable=False)
        self.assertEqual(over_blend["status"], "REFUSED")

        # Invalid flux_err shapes or negative/non-finite errors on valid bands must raise ValueError
        with self.assertRaises(ValueError):
            compute_molecule_readings(wl, bw, rw, flux_err=np.ones(10))

        bad_neg_err = np.full_like(rw, 0.5)
        bad_neg_err[10] = -0.1
        with self.assertRaises(ValueError):
            compute_molecule_readings(wl, bw, rw, flux_err=bad_neg_err)

        bad_nan_err = np.full_like(rw, 0.5)
        bad_nan_err[20] = np.nan
        with self.assertRaises(ValueError):
            compute_molecule_readings(wl, bw, rw, flux_err=bad_nan_err)

        for kw in ({"blend_share": -0.05}, {"blend_share": 1.2}, {"blend_share": float("nan")}, {"n_draws": 0}):
            with self.assertRaises(ValueError):
                compute_molecule_readings(wl, bw, rw, **kw)

        # Already-masked flux bands with NaN errors and negative PSF-subtracted residuals are handled cleanly
        masked_pair_fl = rw.copy()
        masked_pair_err = rw * 0.03
        co2_idx = np.where((wl >= 4.18) & (wl <= 4.35))[0]
        masked_pair_fl[co2_idx[:2]] = -1.5  # negative PSF-subtracted residuals
        masked_pair_fl[co2_idx[2:]] = np.nan
        masked_pair_err[co2_idx[2:]] = np.nan  # NaN error on already-masked band is allowed
        res_clean_mask = compute_molecule_readings(wl, bw, masked_pair_fl, flux_err=masked_pair_err, rng_seed=0)
        self.assertEqual(res_clean_mask["status"], "MEASURED")
        self.assertEqual(res_clean_mask["features"]["CO2_4_26"]["status"], "REFUSED")
        self.assertTrue(res_clean_mask["features"]["H2O_ice_3_05"]["uncertainty_available"])

    def test_pipeline_error_paths_parallax_boundary_contamination_and_out_of_taxonomy_novelty(self):
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline

        wl, bw, spectra = _load_spectra_table()
        agn_tmpl = 25.0 + 90.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 3
        classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Active galaxy or quasar": agn_tmpl,
        }

        unfitted = SpectralDiscoveryPipeline(wl, bw, template_library=classes, random_state=5)
        with self.assertRaises(RuntimeError):
            unfitted.predict_one(spectra["Barnards_Star"])
        with self.assertRaises(ValueError):
            unfitted.fit(np.vstack([spectra["Barnards_Star"]] * 2), np.array(["Star", "Star"]))

        rng = np.random.default_rng(23)
        X_train, y_train = [], []
        for label, base in classes.items():
            for _ in range(20):
                scale = rng.uniform(0.7, 1.3)
                noise = rng.normal(0.0, 0.02 * np.maximum(base, 0.2))
                X_train.append(np.maximum(base * scale + noise, 0.01))
                y_train.append(label)

        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=classes, random_state=23)
        pipe.fit(np.array(X_train), np.array(y_train), blend_shares=np.full(len(y_train), 0.05))

        # Parallax boundary: <= 5.0 inactive; > 5.0 zeros AGN/Galaxy strictly inside all_data
        at_thresh = pipe.predict_one(agn_tmpl * 1.1, blend_share=0.05, parallax_snr=5.0)
        self.assertFalse(at_thresh["all_data"]["parallax_gate_applied"])
        self.assertEqual(at_thresh["all_data"]["top_class"], "Active galaxy or quasar")

        above_thresh = pipe.predict_one(agn_tmpl * 1.1, blend_share=0.05, parallax_snr=5.1)
        self.assertTrue(above_thresh["all_data"]["parallax_gate_applied"])
        self.assertEqual(above_thresh["spectrum_alone"]["top_class"], "Active galaxy or quasar")
        self.assertNotEqual(above_thresh["all_data"]["top_class"], "Active galaxy or quasar")
        self.assertNotIn("Active galaxy or quasar", above_thresh["all_data"]["conformal_set"])

        # Each contamination flag triggers CONTAMINATION_SCREENED with None weirdness_score
        for kw in ({"blend_share": 0.31}, {"is_variable": True}, {"has_masked_pixels": True}):
            screened = pipe.predict_one(spectra["WISE_0855"], **kw)
            self.assertEqual(screened["novelty"]["status"], "CONTAMINATION_SCREENED", msg=f"Failed for {kw}")
            self.assertIsNone(screened["novelty"]["weirdness_score"])

        # Out-of-taxonomy high-residual spike triggers NOVEL on clean input
        exotic = np.where((wl > 2.5) & (wl < 2.9), 5000.0, 1.0)
        novel_pred = pipe.predict_one(exotic, blend_share=0.05, is_variable=False, has_masked_pixels=False)
        self.assertEqual(novel_pred["novelty"]["status"], "NOVEL")
        self.assertIsNotNone(novel_pred["novelty"]["weirdness_score"])

    def test_ml_pipeline_parallax_conformal_iforest_log_warnings_and_barnard_continuum(self):
        import warnings
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline, compute_molecule_readings

        wl, bw, spectra = _load_spectra_table()
        gal_tmpl = 40.0 + 30.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 2
        classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Galaxy": gal_tmpl,
        }
        rng = np.random.default_rng(31)
        X_tr, y_tr = [], []
        for label, base in classes.items():
            for _ in range(18):
                X_tr.append(
                    np.maximum(base * rng.uniform(0.7, 1.3) + rng.normal(0.0, 0.02 * np.maximum(base, 0.2)), 0.01)
                )
                y_tr.append(label)

        # 1. Zero RuntimeWarnings on log(<=0), NaNs during fit/predict, and zero-sum isotonic rows
        neg_zero_star = spectra["Barnards_Star"].copy()
        neg_zero_star[5] = 0.0
        neg_zero_star[6] = -2.5
        neg_zero_star[7] = np.nan
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            pipe = SpectralDiscoveryPipeline(wl, bw, template_library=classes, random_state=31)
            pipe.fit(np.array(X_tr), np.array(y_tr), blend_shares=np.full(len(y_tr), 0.05))
            _ = pipe.predict_one(neg_zero_star, blend_share=0.05)
            zero_cal = {cls: type("_Z", (), {"predict": staticmethod(lambda x: np.zeros_like(x))})() for cls in pipe.classes_}
            raw_probe = np.array([[0.7, 0.2, 0.05, 0.05]], dtype=np.float64)
            with mock.patch.object(pipe, "calibrators_", zero_cal):
                iso_out = pipe._apply_isotonic(raw_probe)
            np.testing.assert_allclose(iso_out, raw_probe)
        log_warnings = [w for w in caught if "log" in str(w.message) or "divide" in str(w.message)]
        self.assertEqual(log_warnings, [], msg=f"Unexpected warnings: {[str(w.message) for w in log_warnings]}")

        # All non-positive flux should refuse classification cleanly
        all_neg = np.full_like(spectra["Barnards_Star"], -1.0)
        neg_pred = pipe.predict_one(all_neg, blend_share=0.05, parallax_snr=10.0)
        self.assertEqual(neg_pred["spectrum_alone"]["top_class"], "Unclassified")
        self.assertEqual(neg_pred["spectrum_alone"]["tree_class"], "Unclassified")
        self.assertEqual(neg_pred["novelty"]["status"], "CONTAMINATION_SCREENED")

        # 2. Parallax gate must NOT inflate low pre-gate probabilities into all_data conformal_set
        pipe.conformal_q_ = 0.85  # pre-gate conformal inclusion requires p >= 0.149
        class_order = list(pipe.meta_combiner.classes_)
        fake_raw = np.array(
            [
                [
                    0.90 if c == "Galaxy" else (0.05 if c == "Star" else (0.03 if c == "Ultracool dwarf" else 0.02))
                    for c in class_order
                ]
            ]
        )
        with (
            mock.patch.object(pipe.meta_combiner, "predict_proba", return_value=fake_raw),
            mock.patch.object(pipe, "_apply_isotonic", side_effect=lambda x: x),
            mock.patch.object(pipe, "_predict_template_class", return_value=("Galaxy", {c: 0.5 for c in classes})),
        ):
            gated = pipe.predict_one(gal_tmpl, blend_share=0.05, parallax_snr=10.0)
        self.assertEqual(gated["spectrum_alone"]["conformal_set"], ["Galaxy"])
        self.assertEqual(gated["all_data"]["conformal_set"], [])
        self.assertEqual(gated["all_data"]["top_class"], "Unclassified")
        self.assertLessEqual(gated["all_data"]["confidence"], 0.10)

        # 3. IsolationForest outlier (predict == -1) must trigger NOVEL even if chi2 <= 3 and conformal_set non-empty
        star_raw = np.array([[0.96 if c == "Star" else 0.0133 for c in class_order]])
        with (
            mock.patch.object(pipe.meta_combiner, "predict_proba", return_value=star_raw),
            mock.patch.object(pipe, "_apply_isotonic", side_effect=lambda x: x),
            mock.patch.object(pipe, "_predict_template_class", return_value=("Star", {c: 0.4 for c in classes})),
            mock.patch.object(
                pipe,
                "_predict_tree_probs",
                return_value={c: (0.96 if c == "Star" else 0.0133) for c in pipe.classes_},
            ),
            mock.patch.object(pipe.novelty_forest, "predict", return_value=np.array([-1])),
        ):
            iforest_out = pipe.predict_one(spectra["WISE_0855"], blend_share=0.05)
        self.assertEqual(iforest_out["novelty"]["status"], "NOVEL")

        # 4. Continuum fallback must not misclassify blue-masked Barnards_Star as a flat brown dwarf or cubic blowup
        bs_no_blue = spectra["Barnards_Star"].copy()
        bs_no_blue[(wl >= 2.53) & (wl <= 2.72)] = np.nan
        res_no_blue = compute_molecule_readings(wl, bw, bs_no_blue, rng_seed=0)
        self.assertGreater(res_no_blue["features"]["H2O_ice_3_05"]["integrated_tau"], -65.0)
        self.assertLess(res_no_blue["features"]["CO2_4_26"]["integrated_tau"], 5.5)

        bs_no_red_anchor = spectra["Barnards_Star"].copy()
        bs_no_red_anchor[wl >= 4.45] = np.nan
        res_no_red = compute_molecule_readings(wl, bw, bs_no_red_anchor, rng_seed=0)
        self.assertGreater(res_no_red["features"]["CO2_4_26"]["integrated_tau"], -10.0)

        wise_clean = compute_molecule_readings(wl, bw, spectra["WISE_0855"], rng_seed=0)
        self.assertGreater(wise_clean["features"]["CO_4_67"]["integrated_tau"], 0.0)
        self.assertGreater(wise_clean["features"]["CH4_3_3"]["integrated_tau"], 0.0)

    def test_ml_pipeline_release_gate_recall_ece_conformal_leave_one_out_and_masked_bands(self):
        import warnings
        from phantom_worlds.ml_pipeline import (
            SpectralDiscoveryPipeline,
            evaluate_cross_extraction_ratio,
            evaluate_fixed_targets,
            split_by_sky_tile,
        )

        wl, bw, spectra = _load_spectra_table()
        # Use all 5 real SPHEREx 102-band spectra from spherex_102_band_spectra.csv + extragalactic template
        agn_tmpl = 25.0 + 90.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 3
        classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": [spectra["Eps_Indi_B"], spectra["WISE_0855"]],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Evolved giant star": spectra["R_Draconis"],
            "Active galaxy or quasar": agn_tmpl,
        }
        rng = np.random.default_rng(77)

        # Build a sky-tiled dataset with Gold & Silver label grades and W2 brightness bins
        # (W2<=12, 12<W2<=13, 13<W2<=14 high-SNR bins, plus faint noisy W2>14 bin that must be shown as failing)
        X_all, y_all, tiles_all, grades_all, w2_all = [], [], [], [], []
        w2_bins_cycle = [11.4, 12.5, 13.5, 11.8, 12.7, 13.6]
        for tile_idx in range(15):
            tile_id = f"TILE_{tile_idx:02d}"
            for label, base_entry in classes.items():
                variants = base_entry if isinstance(base_entry, list) else [base_entry]
                for sample_i in range(4):
                    w2_mag = w2_bins_cycle[(tile_idx + sample_i) % len(w2_bins_cycle)]
                    # SNR ~ 50 at W2=11.5, SNR ~ 12 at W2=13.6
                    sigma = 0.02 * (10.0 ** (0.2 * (w2_mag - 11.5)))
                    scale = rng.uniform(0.65, 1.35)
                    slope = 1.0 + rng.uniform(-0.14, 0.14) * ((wl - 2.8) / 2.2)
                    base_vec = variants[1] if (len(variants) > 1 and sample_i == 3) else variants[0]
                    noise = rng.normal(0.0, sigma * np.maximum(base_vec * scale, 0.25))
                    X_all.append(np.maximum(base_vec * scale * slope + noise, 0.01))
                    y_all.append(label)
                    tiles_all.append(tile_id)
                    grades_all.append("Silver" if sample_i == 2 else "Gold")
                    w2_all.append(w2_mag)

        X_all = np.asarray(X_all, dtype=np.float64)
        y_all = np.asarray(y_all)
        tiles_all = np.asarray(tiles_all)
        grades_all = np.asarray(grades_all)
        w2_all = np.asarray(w2_all, dtype=np.float64)

        # 1. Sky-tile split (60% train, 20% calibrate, 20% test) with zero tile overlap and Gold-only test set
        split = split_by_sky_tile(tiles_all, y_all, label_grades=grades_all, random_state=77)
        tr_tiles = set(tiles_all[split["train_idx"]].tolist())
        cal_tiles = set(tiles_all[split["cal_idx"]].tolist())
        te_tiles = set(tiles_all[split["test_idx"]].tolist())
        self.assertEqual(tr_tiles & cal_tiles, set(), "Sky-tile leakage between train and calibration splits")
        self.assertEqual(tr_tiles & te_tiles, set(), "Sky-tile leakage between train and test splits")
        self.assertEqual(cal_tiles & te_tiles, set(), "Sky-tile leakage between calibration and test splits")
        self.assertTrue(all(g == "Gold" for g in grades_all[split["test_idx"]]), "Silver labels leaked into Gold-only test split")

        fit_mask = np.concatenate([split["train_idx"], split["cal_idx"]])
        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=classes, random_state=77)
        pipe.fit(
            X_all[fit_mask],
            y_all[fit_mask],
            blend_shares=np.full(len(fit_mask), 0.05),
            sky_tiles=tiles_all[fit_mask],
            label_grades=grades_all[fit_mask],
        )
        self.assertEqual(pipe.silver_weight_applied_, 0.5)

        # Append faint low-SNR W2>14 rows (plus a Silver row that must be ignored by test pass marks) to test split
        X_te_gold = X_all[split["test_idx"]]
        y_te_gold = y_all[split["test_idx"]]
        w2_te_gold = w2_all[split["test_idx"]]
        grades_te = ["Gold"] * len(y_te_gold)

        faint_X, faint_y, faint_w2, faint_grades = [], [], [], []
        for label in classes:
            for _ in range(4):
                # Extreme noise at W2=15.8 (SNR < 2) so W2>14 bin genuinely fails recall gate
                faint_X.append(rng.uniform(1.0, 500.0, size=len(wl)))
                faint_y.append(label)
                faint_w2.append(15.8)
                faint_grades.append("Gold")
        # Add corrupted Silver rows at W2=11.5: must be excluded from Gold test pass-mark calculation
        for label in classes:
            faint_X.append(rng.uniform(1.0, 500.0, size=len(wl)))
            faint_y.append(label)
            faint_w2.append(11.5)
            faint_grades.append("Silver")

        X_eval = np.vstack([X_te_gold, np.asarray(faint_X)])
        y_eval = np.concatenate([y_te_gold, np.asarray(faint_y)])
        w2_eval = np.concatenate([w2_te_gold, np.asarray(faint_w2)])
        grades_eval = np.concatenate([ np.asarray(grades_te), np.asarray(faint_grades)])

        gate_report = pipe.evaluate_release_gates(X_eval, y_eval, w2_mags=w2_eval, label_grades=grades_eval)
        self.assertEqual(gate_report["excluded_silver_count"], len(classes))
        self.assertEqual(gate_report["release_status"], "PUBLISHED")
        for cls, rec in gate_report["high_snr_gold"]["per_class_recall"].items():
            self.assertGreaterEqual(rec, 0.80, msg=f"High-SNR Gold recall below 0.80 for {cls}: {rec}")
        self.assertLessEqual(gate_report["high_snr_gold"]["ece"], 0.05)
        self.assertGreaterEqual(gate_report["high_snr_gold"]["conformal_coverage"], 0.88)

        for bright_bin in ("W2<=12", "12<W2<=13", "13<W2<=14"):
            self.assertIn(bright_bin, gate_report["brightness_bins"])
            self.assertTrue(gate_report["brightness_bins"][bright_bin]["passed"], msg=f"{bright_bin} failed: {gate_report['brightness_bins'][bright_bin]}")
        # Faint bin (W2>14) must be reported and honestly flagged as failing
        self.assertFalse(gate_report["brightness_bins"]["W2>14"]["passed"])

        # When a high-SNR bin fails, release_status must switch to UNPUBLISHED
        bad_y = y_te_gold.copy()
        bad_y[:] = "Star"
        failed_gate = pipe.evaluate_release_gates(X_te_gold, bad_y, w2_mags=w2_te_gold)
        self.assertEqual(failed_gate["release_status"], "UNPUBLISHED")

        # 2. Multi-detector outage robustness (D1 0:17 and D5 68:85 NaN-masked, zero warnings)
        X_masked = X_te_gold.copy()
        X_masked[:, 0:17] = np.nan
        X_masked[:, 68:85] = np.nan
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always", RuntimeWarning)
            preds_masked = [pipe.predict_one(row, has_masked_pixels=True)["spectrum_alone"] for row in X_masked]
        log_warns = [w for w in caught if "log" in str(w.message) or "divide" in str(w.message)]
        self.assertEqual(log_warns, [])
        for cls in classes:
            idx = [i for i, yy in enumerate(y_te_gold) if yy == cls]
            masked_rec = sum(preds_masked[i]["top_class"] == cls for i in idx) / len(idx)
            self.assertGreaterEqual(masked_rec, 0.80, msg=f"Masked recall below 0.80 for {cls}: {masked_rec}")

        # 3. Leave-one-type-out novelty/unclassified check
        sub_classes = {k: v for k, v in classes.items() if k != "Active galaxy or quasar"}
        keep_tr = y_all[fit_mask] != "Active galaxy or quasar"
        pipe_loo = SpectralDiscoveryPipeline(wl, bw, template_library=sub_classes, random_state=77)
        pipe_loo.fit(X_all[fit_mask][keep_tr], y_all[fit_mask][keep_tr], blend_shares=np.full(int(np.sum(keep_tr)), 0.05))
        loo_rows = X_te_gold[y_te_gold == "Active galaxy or quasar"]
        loo_flagged = sum(
            (r["spectrum_alone"]["top_class"] == "Unclassified" or r["novelty"]["status"] == "NOVEL")
            for r in (pipe_loo.predict_one(row, blend_share=0.05) for row in loo_rows)
        )
        self.assertGreaterEqual(loo_flagged / len(loo_rows), 0.80)

        # 4. Cross-extraction band-by-band median ratio check (ml-research.md §5.H.5 & §9: within 10% per band)
        ref_spiff = np.vstack([spectra["Eps_Indi_B"] * rng.uniform(0.8, 1.2) for _ in range(100)])
        our_extr = ref_spiff * rng.normal(1.01, 0.03, size=ref_spiff.shape)
        cx_ok = evaluate_cross_extraction_ratio(our_extr, ref_spiff)
        self.assertTrue(cx_ok["passed"])
        self.assertLessEqual(cx_ok["max_abs_deviation"], 0.10)
        cx_bad = evaluate_cross_extraction_ratio(our_extr * 1.25, ref_spiff)
        self.assertFalse(cx_bad["passed"])

        # 5. Fixed 5 NASA test targets expectation check (ml-research.md §5.H.6 & §8 table)
        fixed_report = evaluate_fixed_targets(wl, bw, spectra, pipe)
        self.assertTrue(fixed_report["all_passed"], msg=f"Fixed target check failed: {fixed_report}")
        self.assertEqual(fixed_report["targets"]["Barnards_Star"]["top_class"], "Star")
        self.assertEqual(fixed_report["targets"]["Eps_Indi_B"]["top_class"], "Ultracool dwarf")
        self.assertIn(fixed_report["targets"]["WISE_0855"]["top_class"], ("Ultracool dwarf", "Unclassified"))
        self.assertEqual(fixed_report["targets"]["RW_Aurigae"]["molecule_status"], "REFUSED")
        self.assertEqual(fixed_report["targets"]["R_Draconis"]["molecule_status"], "REFUSED")

    def test_ml_pipeline_e4_continuity_log_continuum_disjoint_shoulders_mc_scale_and_iforest_nan(self):
        from phantom_worlds.ml_pipeline import (
            CONTINUUM_WINDOWS,
            CO_SHOULDER_WINDOWS,
            MOLECULE_WINDOWS,
            SpectralDiscoveryPipeline,
            _in_windows,
            compute_molecule_readings,
        )

        wl, bw, spectra = _load_spectra_table()

        # 3C: B053 (2.5235 um) must lie in CONTINUUM_WINDOWS; CO shoulders must not overlap CO_4_67
        self.assertTrue(bool(_in_windows(np.array([2.5235]), CONTINUUM_WINDOWS)[0]))
        co_lo, co_hi = MOLECULE_WINDOWS["CO_4_67"]
        for sh_lo, sh_hi in CO_SHOULDER_WINDOWS:
            self.assertTrue(
                sh_hi <= co_lo or sh_lo >= co_hi,
                msg=f"CO shoulder ({sh_lo}, {sh_hi}) overlaps CO_4_67 ({co_lo}, {co_hi})",
            )

        # 3B: Reddened RW_Aurigae (F(3.9)/F(2.6) > 5) must NOT trigger brown-dwarf flat continuum hijack
        rw = spectra["RW_Aurigae"]
        rw_red = rw * np.exp(-3.0 * (2.6 / wl) ** 1.7)
        res_red = compute_molecule_readings(wl, bw, rw_red, rng_seed=0)
        self.assertEqual(res_red["status"], "MEASURED")
        self.assertLess(res_red["features"]["H2O_ice_3_05"]["integrated_tau"], 220.0)
        self.assertGreater(res_red["features"]["H2O_ice_3_05"]["integrated_tau"], 80.0)
        self.assertGreater(res_red["features"]["CO2_4_26"]["integrated_tau"], 10.0)
        self.assertLess(res_red["features"]["CH4_3_3"]["integrated_tau"], 30.0)

        # 3D: Low-SNR noisy feature MC redraws must bracket point estimate without 1e-6 blowup and be scale-invariant
        faint_fl = rw * 0.02
        ch4_mask = (wl >= 3.20) & (wl <= 3.65)
        faint_fl[ch4_mask] = 0.35
        faint_err = 0.05 * faint_fl
        faint_err[ch4_mask] = 0.45
        faint_res = compute_molecule_readings(wl, bw, faint_fl, flux_err=faint_err, rng_seed=0)
        ch4_f = faint_res["features"]["CH4_3_3"]
        self.assertLessEqual(ch4_f["p16"], ch4_f["integrated_tau"])
        self.assertLessEqual(ch4_f["integrated_tau"], ch4_f["p84"])
        self.assertLess(abs(ch4_f["median"] - ch4_f["integrated_tau"]) / abs(ch4_f["integrated_tau"]), 0.20)

        scaled_res = compute_molecule_readings(wl, bw, faint_fl * 1e-4, flux_err=faint_err * 1e-4, rng_seed=0)
        ch4_s = scaled_res["features"]["CH4_3_3"]
        self.assertAlmostEqual(ch4_s["integrated_tau"], ch4_f["integrated_tau"], places=3)
        self.assertAlmostEqual(ch4_s["median"], ch4_f["median"], places=3)
        self.assertAlmostEqual(ch4_s["p16"], ch4_f["p16"], places=3)

        # 3A + 3E: E4 allowed-class experts, continuity across surviving=0.50, and IForest screening on unflagged NaNs
        gal_tmpl = 40.0 + 30.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 2
        classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": rw,
            "Galaxy": gal_tmpl,
        }
        rng = np.random.default_rng(41)
        X_tr, y_tr = [], []
        for label, base in classes.items():
            for _ in range(18):
                X_tr.append(
                    np.maximum(base * rng.uniform(0.75, 1.25) + rng.normal(0.0, 0.02 * np.maximum(base, 0.2)), 0.01)
                )
                y_tr.append(label)
        pipe = SpectralDiscoveryPipeline(wl, bw, template_library=classes, random_state=41)
        pipe.fit(np.array(X_tr), np.array(y_tr), blend_shares=np.full(len(y_tr), 0.05))
        class_order = list(pipe.meta_combiner.classes_)

        # 3E: Unflagged NaN bands (has_masked_pixels=False) must still trigger CONTAMINATION_SCREENED
        unflagged_nan = spectra["Barnards_Star"].copy()
        unflagged_nan[:10] = np.nan
        nan_pred = pipe.predict_one(unflagged_nan, blend_share=0.05, has_masked_pixels=False)
        self.assertEqual(nan_pred["novelty"]["status"], "CONTAMINATION_SCREENED")
        self.assertIsNone(nan_pred["novelty"]["weirdness_score"])

        # 3A(i): E4 must compare allowed Galactic experts, not raw E1/E2 extragalactic winner
        probs_e4 = np.array(
            [
                [
                    0.35 if c == "Galaxy" else (0.58 if c == "Star" else (0.04 if c == "Ultracool dwarf" else 0.03))
                    for c in class_order
                ]
            ]
        )
        chi2_e4 = {"Galaxy": 0.40, "Star": 0.45, "Ultracool dwarf": 8.0, "Young star with ice or dust": 9.0}
        tree_e4 = {"Galaxy": 0.48, "Star": 0.46, "Ultracool dwarf": 0.03, "Young star with ice or dust": 0.03}
        with (
            mock.patch.object(pipe.meta_combiner, "predict_proba", return_value=probs_e4),
            mock.patch.object(pipe, "_apply_isotonic", side_effect=lambda x: x),
            mock.patch.object(pipe, "_predict_template_class", return_value=("Galaxy", chi2_e4)),
            mock.patch.object(pipe, "_predict_tree_probs", return_value=tree_e4),
        ):
            res_e4 = pipe.predict_one(spectra["Barnards_Star"], blend_share=0.05, parallax_snr=10.0)
        self.assertEqual(res_e4["all_data"]["top_class"], "Star")
        self.assertGreater(res_e4["all_data"]["confidence"], 0.50)

        # 3A(ii): Continuous transition across surviving == 0.50 (no >0.40 threshold cliff)
        def run_at_gal(gal_p, star_p):
            row = np.array(
                [
                    [
                        gal_p
                        if c == "Galaxy"
                        else (star_p if c == "Star" else (0.05 if c == "Ultracool dwarf" else max(0.0, 1.0 - gal_p - star_p - 0.05)))
                        for c in class_order
                    ]
                ]
            )
            with (
                mock.patch.object(pipe.meta_combiner, "predict_proba", return_value=row),
                mock.patch.object(pipe, "_apply_isotonic", side_effect=lambda x: x),
                mock.patch.object(pipe, "_predict_template_class", return_value=("Star", {c: (0.4 if c == "Star" else 5.0) for c in classes})),
                mock.patch.object(pipe, "_predict_tree_probs", return_value={c: (0.9 if c == "Star" else 0.03) for c in classes}),
            ):
                return pipe.predict_one(spectra["Barnards_Star"], blend_share=0.05, parallax_snr=10.0)

        above_half = run_at_gal(0.49, 0.44)  # surviving = 0.51
        below_half = run_at_gal(0.51, 0.42)  # surviving = 0.49
        self.assertLess(abs(above_half["all_data"]["confidence"] - below_half["all_data"]["confidence"]), 0.05)


class TestFastAPIBackend(unittest.TestCase):
    def setUp(self):
        from phantom_worlds.api import create_app

        self.client = TestClient(create_app())

    def test_health_targets_manifest_and_sources_endpoints(self):
        r_health = self.client.get("/health")
        self.assertEqual(r_health.status_code, 200)
        self.assertEqual(r_health.json()["status"], "ok")

        r_targets = self.client.get("/api/targets", params={"epoch_yr": 2026.0})
        self.assertEqual(r_targets.status_code, 200)
        targets = {t["target_id"]: t for t in r_targets.json()["targets"]}
        self.assertEqual(len(targets), 5)
        self.assertAlmostEqual(targets["TGT-02"]["ra_deg_at_epoch"], 133.736027, places=4)

        r_manifest = self.client.get("/api/patch/manifest")
        self.assertEqual(r_manifest.status_code, 200)
        self.assertEqual(r_manifest.json()["target_id"], "TGT-02")

        r_sources = self.client.get("/api/sources")
        self.assertEqual(r_sources.status_code, 200)
        self.assertEqual(len(r_sources.json()["wavelength_grid_um"]), 102)

    def test_detector_stack_and_case_export_security_validation(self):
        r_stack = self.client.get("/api/patch/stack/D6")
        self.assertEqual(r_stack.status_code, 200)
        payload = r_stack.json()
        self.assertEqual(payload["detector"], "D6")
        self.assertEqual(payload["shape"], [64, 64])
        self.assertGreaterEqual(payload["masked_pixels"], 0)
        self.assertLess(payload["masked_pixels"], 64 * 64)

        # Invalid detector must be rejected strictly
        r_bad_det = self.client.get("/api/patch/stack/D99")
        self.assertEqual(r_bad_det.status_code, 422)

        r_cases = self.client.get("/api/cases")
        self.assertEqual(r_cases.status_code, 200)
        self.assertEqual(r_cases.json()["data_origin"], "synthetic_mock_fixture")

        r_export = self.client.get("/api/cases/CASE-W0855-001/export")
        self.assertEqual(r_export.status_code, 200)
        exp_json = r_export.json()
        self.assertTrue(exp_json["requires_human_submission"])
        self.assertIn("Backyard Worlds", exp_json["export_target"])

        # Non-existent or path-traversal case IDs rejected cleanly
        self.assertEqual(self.client.get("/api/cases/NO-SUCH-CASE/export").status_code, 404)
        self.assertIn(self.client.get("/api/cases/..%2F..%2Fetc/export").status_code, (404, 422))

    def test_analyze_spectrum_endpoint_validates_bounds_and_runs_readings(self):
        _, _, spectra = _load_spectra_table()
        ok_req = {
            "flux_uJy": spectra["RW_Aurigae"].tolist(),
            "blend_share": 0.12,
            "is_variable": False,
        }
        r_ok = self.client.post("/api/analyze/spectrum", json=ok_req)
        self.assertEqual(r_ok.status_code, 200)
        body = r_ok.json()
        self.assertEqual(body["molecule_readings"]["status"], "MEASURED")
        h2o = body["molecule_readings"]["features"]["H2O_ice_3_05"]
        self.assertGreater(h2o["integrated_tau"], 0.0)
        self.assertFalse(h2o["uncertainty_available"])
        self.assertIsNone(h2o["p16"])

        r_err = self.client.post(
            "/api/analyze/spectrum",
            json={**ok_req, "flux_err_uJy": (spectra["RW_Aurigae"] * 0.03).tolist()},
        )
        self.assertEqual(r_err.status_code, 200)
        h2o_err = r_err.json()["molecule_readings"]["features"]["H2O_ice_3_05"]
        self.assertTrue(h2o_err["uncertainty_available"])
        self.assertLessEqual(h2o_err["p16"], h2o_err["p84"])

        # Negative flux_err_uJy -> 422
        r_bad_err = self.client.post(
            "/api/analyze/spectrum",
            json={**ok_req, "flux_err_uJy": [-1.0] + [1.0] * 101},
        )
        self.assertEqual(r_bad_err.status_code, 422)

        # Bad spectrum length -> 422
        r_short = self.client.post("/api/analyze/spectrum", json={"flux_uJy": [1.0, 2.0], "blend_share": 0.1})
        self.assertEqual(r_short.status_code, 422)

        # Bad blend_share > 1 -> 422
        r_bad_blend = self.client.post(
            "/api/analyze/spectrum",
            json={"flux_uJy": spectra["RW_Aurigae"].tolist(), "blend_share": 1.5},
        )
        self.assertEqual(r_bad_blend.status_code, 422)

    def test_web_ui_root_and_static_assets_served_with_security_headers(self):
        r_ui = self.client.get("/")
        self.assertEqual(r_ui.status_code, 200)
        self.assertIn("text/html", r_ui.headers.get("content-type", ""))
        self.assertEqual(r_ui.headers.get("x-content-type-options"), "nosniff")
        self.assertIn("default-src 'self'", r_ui.headers.get("content-security-policy", ""))
        html = r_ui.text
        self.assertIn("Phantom Worlds", html)
        self.assertIn("<canvas", html)
        self.assertIn("/static/viewer.js", html)

        r_js = self.client.get("/static/viewer.js")
        self.assertEqual(r_js.status_code, 200)
        r_css = self.client.get("/static/styles.css")
        self.assertEqual(r_css.status_code, 200)
        self.assertIn(self.client.get("/static/..%2F..%2Fetc/passwd").status_code, (404, 422))
        self.assertEqual(self.client.get("/static/unknown.js").status_code, 404)

    def test_patch_timeseries_endpoint_returns_calibrated_visit_frames_stack_and_difference(self):
        r_ts = self.client.get("/api/patch/timeseries", params={"detector": "D6"})
        self.assertEqual(r_ts.status_code, 200)
        body = r_ts.json()
        self.assertEqual(body["detector"], "D6")
        self.assertEqual(len(body["visits"]), 3)
        self.assertEqual(len(body["frames_by_visit"]), 3)
        self.assertEqual(len(body["frames_by_visit"][0]), 64)
        self.assertEqual(len(body["frames_by_visit"][0][0]), 64)
        self.assertEqual(len(body["stack"]), 64)
        self.assertEqual(len(body["difference"]), 64)
        self.assertGreaterEqual(body["wavelength_range_um"][0], 4.35)
        v1 = np.array(body["frames_by_visit"][0], dtype=np.float64)
        v3 = np.array(body["frames_by_visit"][-1], dtype=np.float64)
        diff = np.array(body["difference"], dtype=np.float64)
        self.assertTrue(np.allclose(diff, v3 - v1, atol=2e-4, equal_nan=True))
        self.assertEqual(self.client.get("/api/patch/timeseries", params={"detector": "D99"}).status_code, 422)

    def test_arbitrary_sky_coordinates_timeseries_and_live_validation(self):
        # 1. Arbitrary empty sky patch offline -> clean 200 with zero frames
        r_arb = self.client.get(
            "/api/sky/timeseries",
            params={"ra_deg": 180.0, "dec_deg": 45.0, "fov_arcmin": 5.0, "detector": "D6"},
        )
        self.assertEqual(r_arb.status_code, 200)
        arb = r_arb.json()
        self.assertAlmostEqual(arb["query"]["ra_deg"], 180.0, places=5)
        self.assertAlmostEqual(arb["query"]["dec_deg"], 45.0, places=5)
        self.assertEqual(arb["frames"], [])
        self.assertIsNone(arb["patch_timeseries"])

        # 2. Sexagesimal WISE 0855 query -> matches local real frames, Gaia overlay, and Hour-0 cube
        r_sex = self.client.get(
            "/api/sky/timeseries",
            params={"coord": "08h55m10.831s -07d14m42.53s", "fov_arcmin": 6.5, "detector": "D6"},
        )
        self.assertEqual(r_sex.status_code, 200)
        w0855 = r_sex.json()
        self.assertAlmostEqual(w0855["query"]["ra_deg"], 133.795129, places=3)
        self.assertGreater(len(w0855["frames"]), 50)
        self.assertGreater(len(w0855["gaia_sources"]), 0)
        self.assertIsNotNone(w0855["patch_timeseries"])

        # 3. Target by name -> Barnard's Star resolves epoch-2026 frames cleanly
        r_name = self.client.get(
            "/api/sky/timeseries",
            params={"coord": "Barnard's Star", "fov_arcmin": 5.0, "epoch_yr": 2026.0},
        )
        self.assertEqual(r_name.status_code, 200)
        barnard = r_name.json()
        self.assertEqual(barnard["matched_target"]["target_id"], "TGT-01")
        self.assertGreater(len(barnard["frames"]), 50)

        # 4. Invalid inputs rejected with 422
        for bad_params in (
            {"ra_deg": 400.0, "dec_deg": 0.0},
            {"ra_deg": 10.0, "dec_deg": -95.0},
            {"ra_deg": 180.0, "dec_deg": 45.0, "fov_arcmin": 90.0},
            {"coord": "not_a_real_target_or_coord"},
        ):
            self.assertEqual(self.client.get("/api/sky/timeseries", params=bad_params).status_code, 422)

        # 5. Live fallback mode for arbitrary sky coordinates (mocked remote fetcher)
        import phantom_worlds.api as api_mod

        fake_live_frames = [
            {
                "obs_collection": "spherex_dr1",
                "obs_id": "LIVE_FRAME_001",
                "s_ra": 180.0,
                "s_dec": 45.0,
                "t_min": 61000.0,
                "t_max": 61000.01,
                "energy_bandpassname": "D6",
                "em_min": 4.4e-6,
                "em_max": 5.0e-6,
                "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/live.fits",
                "cloud_access": "",
            }
        ]
        with mock.patch.object(api_mod, "_fetch_live_sky_data", return_value=(fake_live_frames, [], [])) as mock_live:
            r_live = self.client.get(
                "/api/sky/timeseries",
                params={"ra_deg": 180.0, "dec_deg": 45.0, "fov_arcmin": 5.0, "live": "true"},
            )
        self.assertEqual(r_live.status_code, 200)
        mock_live.assert_called_once()
        self.assertEqual(len(r_live.json()["frames"]), 1)
        self.assertEqual(r_live.json()["frames"][0]["obs_id"], "LIVE_FRAME_001")

    def test_patch_stack_caches_binary_load_and_computes_single_detector_only(self):
        import phantom_worlds.api as api_mod
        import phantom_worlds.contracts as contracts_mod

        with (
            mock.patch.object(api_mod, "load_patch_arrays", wraps=contracts_mod.load_patch_arrays) as spy_load,
            mock.patch.object(
                api_mod, "detector_visit_stacks", wraps=contracts_mod.detector_visit_stacks
            ) as spy_stacks,
        ):
            local_client = TestClient(api_mod.create_app())
            r1 = local_client.get("/api/patch/stack/D6")
            r2 = local_client.get("/api/patch/stack/D6")
            r3 = local_client.get("/api/patch/stack/D5")
            r4 = local_client.get("/api/patch/timeseries", params={"detector": "D6"})

        for resp in (r1, r2, r3, r4):
            self.assertEqual(resp.status_code, 200)
        self.assertEqual(r1.json(), r2.json())
        self.assertEqual(spy_load.call_count, 1)
        self.assertEqual(spy_stacks.call_count, 2)
        called_detectors = [call.kwargs.get("detector_id") for call in spy_stacks.call_args_list]
        self.assertEqual(called_detectors, ["D6", "D5"])

    def test_sky_timeseries_rejects_arbitrary_s3_buckets_regions_ports_and_keys(self):
        import phantom_worlds.api as api_mod

        evil_live_frames = [
            {
                "obs_collection": "spherex_dr1",
                "obs_id": "EVIL_BUCKET",
                "s_ra": 180.0,
                "s_dec": 45.0,
                "t_min": 61000.0,
                "t_max": 61000.01,
                "energy_bandpassname": "D6",
                "em_min": 4.4e-6,
                "em_max": 5.0e-6,
                "access_url": "https://attacker-bucket.s3.us-east-1.amazonaws.com/evil.fits",
                "s3_fits_url": api_mod._safe_s3_url(
                    '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "dr1/a.fits?bad=1", "region": "us-east-1"}}'
                ),
            },
            {
                "obs_collection": "spherex_dr1",
                "obs_id": "WRONG_REGION",
                "s_ra": 180.0,
                "s_dec": 45.0,
                "t_min": 61001.0,
                "t_max": 61001.01,
                "energy_bandpassname": "D6",
                "em_min": 4.4e-6,
                "em_max": 5.0e-6,
                "access_url": "https://user@irsa.ipac.caltech.edu/ibe/data/spherex/a.fits",
                "s3_fits_url": api_mod._safe_s3_url(
                    '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "dr1/a.fits", "region": "eu-west-1"}}'
                ),
            },
        ]
        # Verify server-side URL allowlist helper directly too
        self.assertIsNone(api_mod._safe_s3_url('{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "a.fits", "region": "ap-south-1"}}'))
        self.assertIsNone(api_mod._safe_s3_url('{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "a.fits#frag", "region": "us-east-1"}}'))
        self.assertEqual(evil_live_frames[0]["s3_fits_url"], None)
        self.assertEqual(evil_live_frames[1]["s3_fits_url"], None)

        # Ensure live ingestion filters unsafe access_url from SIA tables
        from astropy.table import Table

        fake_tbl = Table(
            {
                "obs_id": ["EVIL_ACCESS", "EVIL_PORT", "GOOD_S3"],
                "s_ra": [180.0, 180.0, 180.0],
                "s_dec": [45.0, 45.0, 45.0],
                "access_url": [
                    "https://attacker-bucket.s3.us-east-1.amazonaws.com/x.fits",
                    "https://irsa.ipac.caltech.edu:8443/ibe/data/spherex/x.fits",
                    "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/good.fits",
                ],
                "cloud_access": ["", "", ""],
            }
        )

        class FakeSIA:
            def __init__(self, url, session=None):
                pass

            def search(self, *args, **kwargs):
                return type("R", (), {"to_table": lambda self: fake_tbl})()

        with mock.patch.object(api_mod.pyvo.dal, "SIA2Service", FakeSIA):
            frames, _, _ = api_mod._fetch_live_sky_data(180.0, 45.0, 0.05)

        by_id = {f["obs_id"]: f for f in frames}
        self.assertIsNone(by_id["EVIL_ACCESS"]["access_url"])
        self.assertIsNone(by_id["EVIL_PORT"]["access_url"])
        self.assertEqual(
            by_id["GOOD_S3"]["access_url"],
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/good.fits",
        )

    def test_live_irsa_enforces_timeout_session_maxrec_all_collections_and_near_target(self):
        import requests
        import phantom_worlds.api as api_mod
        from astropy.table import Table

        seen_sessions = []
        seen_searches = []
        fake_tbl = Table(
            {
                "obs_id": ["LIVE_CUBE_01"],
                "s_ra": [123.4],
                "s_dec": [22.5],
                "access_url": ["https://irsa.ipac.caltech.edu/ibe/data/spherex/cube.fits"],
                "cloud_access": [""],
            }
        )

        class SpySIA:
            def __init__(self, url, session=None):
                seen_sessions.append(session)

            def search(self, *args, **kwargs):
                seen_searches.append(dict(kwargs))
                return type("R", (), {"to_table": lambda self: fake_tbl})()

        with mock.patch.object(api_mod.pyvo.dal, "SIA2Service", SpySIA):
            frames, _, warnings_list = api_mod._fetch_live_sky_data(123.4, 22.5, 0.05)

        self.assertEqual(warnings_list, [])
        self.assertEqual(len(seen_sessions), 1)
        sess = seen_sessions[0]
        self.assertEqual(sess.max_redirects, 0)
        self.assertNotIn("http://", sess.adapters)
        with self.assertRaises(ValueError):
            sess.get("http://irsa.ipac.caltech.edu/SIA")
        captured_kwargs = {}

        def fake_super_send(req, **kwargs):
            captured_kwargs.update(kwargs)
            resp = requests.Response()
            resp.status_code = 200
            resp._content = b""
            return resp

        https_adapter = sess.get_adapter("https://irsa.ipac.caltech.edu/SIA")
        with mock.patch.object(https_adapter, "send", side_effect=fake_super_send):
            sess.get("https://irsa.ipac.caltech.edu/SIA")
        self.assertIsNotNone(captured_kwargs.get("timeout"))

        self.assertEqual(
            [s.get("collection") for s in seen_searches],
            ["spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep", "spherex_dr1_cube"],
        )
        self.assertTrue(all(s.get("maxrec") == 100 for s in seen_searches))
        self.assertEqual(len(frames), 5)

        # Near a preset target (WISE 0855), live=true must STILL query IRSA and preserve local Gaia/patch
        live_deep = [
            {
                "obs_collection": "spherex_dr1_deep",
                "obs_id": "LIVE_WISE_DEEP_001",
                "s_ra": 133.795129,
                "s_dec": -7.245147,
                "energy_bandpassname": "D6",
                "em_min": 4.4e-6,
                "em_max": 5.0e-6,
                "t_min": 61050.0,
                "t_max": 61050.01,
                "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/deep_wise.fits",
                "s3_fits_url": None,
            }
        ]
        fresh_client = TestClient(api_mod.create_app())
        with mock.patch.object(api_mod, "_fetch_live_sky_data", return_value=(live_deep, [], [])) as mock_live:
            r_wise_live = fresh_client.get(
                "/api/sky/timeseries",
                params={"coord": "WISE 0855", "fov_arcmin": 6.5, "detector": "D6", "live": "true"},
            )
        self.assertEqual(r_wise_live.status_code, 200)
        mock_live.assert_called_once()
        body_wise = r_wise_live.json()
        self.assertIn("LIVE_WISE_DEEP_001", [f["obs_id"] for f in body_wise["frames"]])
        self.assertGreater(len(body_wise["frames"]), 50)
        self.assertGreater(len(body_wise["gaia_sources"]), 0)
        self.assertIsNotNone(body_wise["patch_timeseries"])
        self.assertIn("live", body_wise["source_mode"])

        # Failed live query near WISE 0855 preserves local data and surfaces warning
        fresh_client2 = TestClient(api_mod.create_app())
        with mock.patch.object(
            api_mod, "_fetch_live_sky_data", return_value=([], [], ["Live IRSA query failed."])
        ):
            r_wise_fail = fresh_client2.get(
                "/api/sky/timeseries",
                params={"coord": "WISE 0855", "fov_arcmin": 6.5, "live": "true"},
            )
        self.assertEqual(r_wise_fail.status_code, 200)
        fail_body = r_wise_fail.json()
        self.assertGreater(len(fail_body["frames"]), 50)
        self.assertGreater(len(fail_body["gaia_sources"]), 0)
        self.assertEqual(fail_body["warnings"], ["Live IRSA query failed."])

        # TTL cache coalesces identical live coordinate requests on the same app instance
        seen_searches.clear()
        fresh_client3 = TestClient(api_mod.create_app())
        with mock.patch.object(api_mod.pyvo.dal, "SIA2Service", SpySIA):
            r_c1 = fresh_client3.get("/api/sky/timeseries", params={"ra_deg": 123.4, "dec_deg": 22.5, "live": "true"})
            r_c2 = fresh_client3.get("/api/sky/timeseries", params={"ra_deg": 123.4, "dec_deg": 22.5, "live": "true"})
        self.assertEqual(r_c1.status_code, 200)
        self.assertEqual(r_c2.status_code, 200)
        self.assertEqual(len(seen_searches), 5)

    def test_sky_timeseries_live_uses_epoch_coords_preserves_detectors_and_resists_dos(self):
        from concurrent.futures import ThreadPoolExecutor
        import time
        import phantom_worlds.api as api_mod
        from phantom_worlds.contracts import propagate_position

        # 1. live=true for high-PM target must query epoch-propagated coords, NOT J2000, and vary cache key with epoch
        exp26_ra, exp26_dec = propagate_position(133.795129, -7.245147, -8118.0, 680.0, 26.0)
        exp50_ra, exp50_dec = propagate_position(133.795129, -7.245147, -8118.0, 680.0, 50.0)
        seen_coords = []

        def fake_live(ra, dec, radius_deg):
            seen_coords.append((ra, dec, radius_deg))
            return (
                [
                    {
                        "obs_collection": "spherex_dr1",
                        "obs_id": "2025W19_1B_0116_1",
                        "s_ra": ra,
                        "s_dec": dec,
                        "energy_bandpassname": "SPHEREx-D6",
                        "em_min": 4.4115e-06,
                        "em_max": 5.004e-06,
                        "t_min": 60800.0,
                        "t_max": 60800.01,
                        "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/d6.fits",
                        "s3_fits_url": None,
                    }
                ],
                [],
                [],
            )

        local_client = TestClient(api_mod.create_app())
        with mock.patch.object(api_mod, "_fetch_live_sky_data", side_effect=fake_live):
            r26 = local_client.get("/api/sky/timeseries", params={"coord": "WISE 0855", "epoch_yr": 2026.0, "live": "true"})
            r50 = local_client.get("/api/sky/timeseries", params={"coord": "WISE 0855", "epoch_yr": 2050.0, "live": "true"})

        self.assertEqual(r26.status_code, 200)
        self.assertEqual(r50.status_code, 200)
        self.assertEqual(len(seen_coords), 2)
        self.assertAlmostEqual(seen_coords[0][0], exp26_ra, places=5)
        self.assertAlmostEqual(seen_coords[0][1], exp26_dec, places=5)
        self.assertAlmostEqual(seen_coords[1][0], exp50_ra, places=5)
        self.assertAlmostEqual(seen_coords[1][1], exp50_dec, places=5)

        # 2. Live/local dedup on shared obs_id must preserve distinct detector bands (e.g. SPHEREx-D3 + D6)
        matching_0116 = [
            fr for fr in r26.json()["frames"]
            if fr.get("obs_collection") == "spherex_dr1" and fr.get("obs_id") == "2025W19_1B_0116_1"
        ]
        bands_0116 = {fr.get("energy_bandpassname") for fr in matching_0116}
        self.assertEqual(bands_0116, {"SPHEREx-D3", "SPHEREx-D6"}, f"Detector dropped by dedup: {matching_0116}")

        # 3. Semaphore saturation must fail fast without blocking workers for 2s
        acquired = []
        for _ in range(4):
            self.assertTrue(api_mod._LIVE_IRSA_SEMAPHORE.acquire(blocking=False))
            acquired.append(True)
        try:
            t0 = time.monotonic()
            frames_busy, _, warns_busy = api_mod._fetch_live_sky_data(180.0, 45.0, 0.05)
            elapsed = time.monotonic() - t0
        finally:
            for _ in acquired:
                api_mod._LIVE_IRSA_SEMAPHORE.release()
        self.assertEqual(frames_busy, [])
        self.assertEqual(warns_busy, ["Live IRSA archive query busy; showing local results only."])
        self.assertLess(elapsed, 0.3, f"Semaphore acquire blocked FastAPI worker too long: {elapsed:.2f}s")

        # 4. Cache eviction must use bounded LRU (not clear-all wipeout) + coalesce concurrent bursts
        call_counts = {}

        def _counting_live(ra, dec, radius_deg):
            key = (round(ra, 4), round(dec, 4))
            call_counts[key] = call_counts.get(key, 0) + 1
            if key == (12.34, 22.0):
                time.sleep(0.05)
            return ([], [], [])

        burst_client = TestClient(api_mod.create_app())
        with mock.patch.object(api_mod, "_fetch_live_sky_data", side_effect=_counting_live):
            # Hot entry A
            self.assertEqual(burst_client.get("/api/sky/timeseries", params={"ra_deg": 10.0, "dec_deg": 10.0, "live": "true"}).status_code, 200)
            # Fill 64 distinct keys while touching hot entry A near the end so LRU keeps A alive past 64 fillers
            for idx in range(64):
                if idx == 60:
                    self.assertEqual(burst_client.get("/api/sky/timeseries", params={"ra_deg": 10.0, "dec_deg": 10.0, "live": "true"}).status_code, 200)
                self.assertEqual(
                    burst_client.get("/api/sky/timeseries", params={"ra_deg": 20.0 + idx * 0.2, "dec_deg": 10.0, "live": "true"}).status_code,
                    200,
                )
            # Hot entry A must STILL be warm in LRU cache
            self.assertEqual(burst_client.get("/api/sky/timeseries", params={"ra_deg": 10.0, "dec_deg": 10.0, "live": "true"}).status_code, 200)
            self.assertEqual(call_counts[(10.0, 10.0)], 1, "Live cache wipeout evicted hot entry A")

            # Concurrent identical misses must coalesce rather than stampeding upstream
            with ThreadPoolExecutor(max_workers=6) as pool:
                futs = [
                    pool.submit(burst_client.get, "/api/sky/timeseries", params={"ra_deg": 12.34, "dec_deg": 22.0, "live": "true"})
                    for _ in range(6)
                ]
                for fut in futs:
                    self.assertEqual(fut.result().status_code, 200)
            self.assertEqual(call_counts[(12.34, 22.0)], 1, "Thundering herd triggered duplicate live fetches")

    def test_viewer_js_geometry_labels_urls_and_async_race(self):
        import shutil
        import subprocess
        import textwrap

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not found on PATH")

        viewer_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "viewer.js")
        harness = textwrap.dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            function runScenario(viewerCode, searchStr, fetchImpl) {
              function makeEl(id, extra = {}) {
                const listeners = {};
                const el = {
                  id,
                  value: "",
                  checked: false,
                  disabled: false,
                  max: "2",
                  min: "0",
                  textContent: "",
                  options: [],
                  children: [],
                  dataset: {},
                  classList: {
                    _set: new Set(),
                    toggle(c, on) { if (on === undefined ? !this._set.has(c) : on) this._set.add(c); else this._set.delete(c); },
                    add(c) { this._set.add(c); },
                    contains(c) { return this._set.has(c); },
                  },
                  attributes: {},
                  setAttribute(k, v) { this.attributes[k] = String(v); },
                  addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
                  trigger(ev, e = { preventDefault() {} }) { (listeners[ev] || []).forEach((fn) => fn(e)); },
                  append(...nodes) { this.children.push(...nodes); },
                  appendChild(n) { this.children.push(n); if (this.options) this.options.push(n); return n; },
                  replaceChildren(...nodes) { this.children = [...nodes]; },
                  getBoundingClientRect() { return { left: 0, top: 0, width: 512, height: 512 }; },
                  ...extra,
                };
                return el;
              }

              const drawLog = { skyArcs: [], skyLines: [], skyRects: [], skyTexts: [] };
              function makeCtx(log) {
                let path = [];
                return {
                  fillStyle: "",
                  strokeStyle: "",
                  lineWidth: 1,
                  font: "",
                  imageSmoothingEnabled: false,
                  setLineDash() {},
                  fillRect() {},
                  strokeRect(x, y, w, h) { if (log) log.skyRects.push({ x, y, w, h }); },
                  fillText(t, x, y) { if (log) log.skyTexts.push({ t: String(t), x, y }); },
                  createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
                  putImageData() {},
                  drawImage() {},
                  beginPath() { path = []; },
                  moveTo(x, y) { path.push(["M", x, y]); },
                  lineTo(x, y) { path.push(["L", x, y]); },
                  arc(x, y, r) { if (log) log.skyArcs.push({ x, y, r }); },
                  stroke() {
                    if (log && path.length >= 2) {
                      for (let i = 0; i + 1 < path.length; i += 2) {
                        if (path[i][0] === "M" && path[i + 1][0] === "L") {
                          log.skyLines.push({ x1: path[i][1], y1: path[i][2], x2: path[i + 1][1], y2: path[i + 1][2], stroke: this.strokeStyle });
                        }
                      }
                    }
                  },
                };
              }

              const skyCtx = makeCtx(drawLog);
              const byId = {
                "sky-query-form": makeEl("sky-query-form"),
                "coord-input": makeEl("coord-input", { value: "WISE 0855" }),
                "fov-select": makeEl("fov-select", {
                  value: "6.5",
                  options: ["2.5", "5.0", "6.5", "12.0"].map((v) => ({ value: v, textContent: v })),
                }),
                "epoch-input": makeEl("epoch-input", { value: "2026" }),
                "live-toggle": makeEl("live-toggle", { checked: false }),
                "mode-badge": makeEl("mode-badge"),
                "status-banner": makeEl("status-banner"),
                "sky-canvas": makeEl("sky-canvas", { width: 512, height: 512, getContext: () => skyCtx }),
                "spectrum-canvas": makeEl("spectrum-canvas", { width: 512, height: 240, getContext: () => makeCtx(null) }),
                "matrix-canvas": makeEl("matrix-canvas", { width: 512, height: 240, getContext: () => makeCtx(null) }),
                "play-toggle": makeEl("play-toggle"),
                "visit-scrubber": makeEl("visit-scrubber", { value: "0", max: "2" }),
                "visit-label": makeEl("visit-label"),
                "stretch-select": makeEl("stretch-select", { value: "asinh" }),
                "gaia-overlay-toggle": makeEl("gaia-overlay-toggle", { checked: true }),
                "mask-overlay-toggle": makeEl("mask-overlay-toggle", { checked: true }),
                "pixel-readout": makeEl("pixel-readout"),
                "molecule-list": makeEl("molecule-list"),
                "frames-tbody": makeEl("frames-tbody"),
                "frames-heading": makeEl("frames-heading"),
                "spectrum-heading": makeEl("spectrum-heading"),
                "copy-url-btn": makeEl("copy-url-btn"),
              };

              const modeBtns = ["play", "stack", "difference", "rgb"].map((m) => makeEl("m-" + m, { dataset: { mode: m } }));
              const detBtns = ["D1", "D2", "D3", "D4", "D5", "D6"].map((d) => makeEl("d-" + d, { dataset: { det: d } }));
              const presetBtns = ["Slow Target", "Fast Target"].map((c) => makeEl("p-" + c, { dataset: { coord: c } }));

              const historyUrls = [];
              const intervals = [];
              const document = {
                body: { classList: makeEl("body").classList },
                getElementById(id) { return byId[id] || null; },
                querySelectorAll(sel) {
                  if (sel === ".mode-btn") return modeBtns;
                  if (sel === ".det-btn") return detBtns;
                  if (sel === ".preset-btn") return presetBtns;
                  return [];
                },
                createElement(tag) {
                  if (tag === "canvas") return makeEl("tmp-canvas", { width: 64, height: 64, getContext: () => makeCtx(null) });
                  return makeEl(tag);
                },
              };
              const window = {
                location: { search: searchStr, pathname: "/", href: "http://127.0.0.1/" + searchStr },
                history: { replaceState(_s, _t, u) { historyUrls.push(u); window.location.href = "http://127.0.0.1" + u; } },
                setInterval(fn, ms) { const id = intervals.length + 1; intervals.push({ id, fn, ms, cleared: false }); return id; },
                clearInterval(id) { const item = intervals.find((x) => x.id === id); if (item) item.cleared = true; },
              };
              const ctx = {
                window, document, fetch: fetchImpl,
                URL, URLSearchParams, AbortController, Uint8ClampedArray,
                navigator: {}, console, Math, Number, String, Boolean, Array, Object, Set, JSON,
              };
              vm.runInNewContext(viewerCode, ctx);
              return { byId, modeBtns, detBtns, presetBtns, drawLog, historyUrls, intervals };
            }

            (async () => {
              const code = fs.readFileSync(process.argv[1], "utf8");

              // 1. RA 0/360 wraparound + live=true + custom FOV + patch_timeseries=null loop guard
              const fetchCallsA = [];
              const envA = runScenario(code, "?coord=359.995,+0.0&fov=3&live=true", async (url) => {
                fetchCallsA.push(url);
                return {
                  ok: true, status: 200,
                  async json() {
                    return {
                      query: { ra_deg: 359.995, dec_deg: 0.0, ra_deg_at_epoch: 359.995, dec_deg_at_epoch: 0.0, fov_arcmin: 3.0, epoch_yr: 2026.0, detector: "D6" },
                      source_mode: "live_irsa_siav2",
                      matched_target: null,
                      patch_timeseries: null,
                      frames: [
                        { obs_collection: "spherex_dr1", obs_id: "BAD_S3", s3_fits_url: "https://nasa-irsa-spherex.s3.eu-west-1.amazonaws.com/x.fits" },
                        { obs_collection: "spherex_dr1", obs_id: "GOOD_S3", s3_fits_url: "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/good.fits" },
                      ],
                      gaia_sources: [{ source_id: "G1", ra_deg: 0.005, dec_deg: 0.0 }],
                      spectrum_102: null,
                      warnings: [],
                    };
                  },
                };
              });
              await new Promise((r) => setTimeout(r, 20));
              const rows = envA.byId["frames-tbody"].children;
              assert.strictEqual(rows.length, 2);
              assert.strictEqual(rows[0].children[5].textContent, "-", "Unsafe S3 region must not render clickable link");
              assert.strictEqual(rows[1].children[5].children[0].href, "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/good.fits");
              assert(fetchCallsA[0].includes("live=true"), "live=true URL param ignored in initial fetch: " + fetchCallsA[0]);
              assert.strictEqual(envA.byId["live-toggle"].checked, true, "#live-toggle not synced from URL");
              assert.strictEqual(String(Number(envA.byId["fov-select"].value)), "3", "#fov-select not synced for custom FOV=3");
              assert.strictEqual(envA.byId["visit-scrubber"].max, "0", "scrubber.max must be 0 when patch_timeseries is null");
              assert(envA.drawLog.skyArcs.some((a) => a.x > 50 && a.x < 450 && Math.abs(a.y - 256) < 2), "Gaia star across RA 0/360 wraparound was not plotted on canvas");
              const rectBefore = envA.drawLog.skyArcs.length;
              envA.intervals.forEach((it) => { if (!it.cleared) it.fn(); });
              assert.strictEqual(envA.drawLog.skyArcs.length, rectBefore, "Timer loop should not redraw static footprint when nVisits <= 1");

              // 2. Reticle/FOV offset & 2-visit dynamic Difference/RGB fallback labels
              const envB = runScenario(code, "?coord=WISE+0855&fov=2.5", async () => ({
                ok: true, status: 200,
                async json() {
                  return {
                    query: { ra_deg: 133.815, dec_deg: -7.245, ra_deg_at_epoch: 133.795, dec_deg_at_epoch: -7.245, fov_arcmin: 2.5, epoch_yr: 2026.0, detector: "D6" },
                    source_mode: "hour0_calibrated_pack",
                    matched_target: { target_id: "TGT-02", name: "WISE 0855", ra_deg_at_epoch: 133.795, dec_deg_at_epoch: -7.245 },
                    patch_timeseries: {
                      center_ra_deg: 133.795, center_dec_deg: -7.245, fov_arcmin: 6.5,
                      visits: [{ visit_id: "V1", epoch_iso: "2026-01-01T00:00:00Z" }, { visit_id: "V2", epoch_iso: "2026-02-01T00:00:00Z" }],
                      frames_by_visit: [[[1, 2], [3, 4]], [[2, 3], [4, 5]]],
                      stack: [[1.5, 2.5], [3.5, 4.5]],
                      difference: [[1, 1], [1, 1]],
                      mask_overlay: [[0, 0], [0, 0]],
                    },
                    frames: [], gaia_sources: [], spectrum_102: null, warnings: [],
                  };
                },
              }));
              await new Promise((r) => setTimeout(r, 20));
              const queryCross = envB.drawLog.skyLines.find((ln) => Math.abs(ln.x1 - ln.x2) === 0 && ln.x1 < 220 && ln.x1 > 100);
              assert(queryCross, "Query reticle was not projected to query offset when query != cutout center: " + JSON.stringify(envB.drawLog.skyLines));
              assert(envB.drawLog.skyRects.some((r) => Math.abs(r.w - (2.5 / 6.5) * 512) < 5), "User FOV box missing when query fov != cutout fov");
              envB.modeBtns.find((b) => b.dataset.mode === "difference").trigger("click");
              assert.strictEqual(envB.byId["visit-label"].textContent, "V2 − V1", "Difference label hardcoded instead of V2 − V1: " + envB.byId["visit-label"].textContent);
              envB.modeBtns.find((b) => b.dataset.mode === "rgb").trigger("click");
              assert(!envB.byId["visit-label"].textContent.includes("V1/V2/V3"), "RGB label lied when visits < 3: " + envB.byId["visit-label"].textContent);

              // 3. Async race (AbortController + seq guard) + non-OK spectrum analysis error card
              let resolveSlow;
              const abortSignals = [];
              const envC = runScenario(code, "?coord=Initial", async (url, opts = {}) => {
                if (url.includes("/api/analyze/spectrum")) {
                  return { ok: false, status: 500, async json() { return { detail: "boom" }; } };
                }
                if (url.includes("Slow+Target") || url.includes("Slow%20Target")) {
                  abortSignals.push(opts.signal);
                  return new Promise((res) => { resolveSlow = res; });
                }
                if (url.includes("Fast+Target") || url.includes("Fast%20Target")) {
                  return {
                    ok: true, status: 200,
                    async json() {
                      return {
                        query: { ra_deg: 10, dec_deg: 20, ra_deg_at_epoch: 10, dec_deg_at_epoch: 20, fov_arcmin: 6.5, epoch_yr: 2026, detector: "D6" },
                        source_mode: "local_archive",
                        matched_target: { target_id: "TGT-01", name: "Fast Target" },
                        patch_timeseries: null, frames: [], gaia_sources: [],
                        spectrum_102: { label: "Fast Target", wavelength_um: Array.from({ length: 102 }, (_, i) => 0.75 + i * 0.04), flux_uJy: Array(102).fill(10.0) },
                        warnings: [],
                      };
                    },
                  };
                }
                return {
                  ok: true, status: 200,
                  async json() {
                    return { query: { ra_deg: 0, dec_deg: 0, fov_arcmin: 6.5 }, frames: [], gaia_sources: [], warnings: [], patch_timeseries: null };
                  },
                };
              });
              await new Promise((r) => setTimeout(r, 15));
              envC.presetBtns[0].trigger("click");
              envC.presetBtns[1].trigger("click");
              await new Promise((r) => setTimeout(r, 20));
              assert(abortSignals[0] && abortSignals[0].aborted, "Superseded in-flight fetch was not aborted via AbortController");
              resolveSlow({
                ok: true, status: 200,
                async json() {
                  return {
                    query: { ra_deg: 1, dec_deg: 1, fov_arcmin: 6.5 },
                    matched_target: { target_id: "TGT-99", name: "Slow Target" },
                    frames: [], gaia_sources: [], warnings: [], patch_timeseries: null,
                  };
                },
              });
              await new Promise((r) => setTimeout(r, 20));
              assert(envC.byId["status-banner"].textContent.includes("Fast Target"), "Stale response overwrote newer Fast Target state: " + envC.byId["status-banner"].textContent);
              assert(envC.byId["molecule-list"].children.length > 0, "#molecule-list silently left empty on HTTP 500 from /api/analyze/spectrum");
            })().catch((err) => { console.error(err); process.exit(1); });
            """
        ).strip()

        proc = subprocess.run(
            [node_bin, "-e", harness, viewer_js_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=f"viewer.js checks failed:\n{proc.stderr}\n{proc.stdout}")

        index_html = open(os.path.join(ROOT_DIR, "phantom_worlds", "static", "index.html"), encoding="utf-8").read()
        self.assertNotIn("V3−V1", index_html)

    def test_all_five_targets_have_cutouts_and_static_fallback_works_offline(self):
        import shutil
        import subprocess
        import textwrap
        from phantom_worlds.contracts import load_patch_arrays, load_targets

        # 1. All 5 mandatory targets must have calibrated Hour-0 cutouts and API timeseries
        targets_by_id = {row["target_id"]: row for row in load_targets(CSV_DIR)}
        for tid in ("TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"):
            manifest, flux, mask = load_patch_arrays(CONTRACTS_DIR, target_id=tid)
            self.assertEqual(manifest["target_id"], tid)
            self.assertEqual(flux.shape, (3, 6, 64, 64))
            self.assertEqual(mask.shape, (3, 6, 64, 64))
            self.assertAlmostEqual(
                float(manifest["target_j2000_ra_deg"]),
                float(targets_by_id[tid]["ra_deg_j2000"]),
                places=4,
            )
            self.assertTrue(np.any(np.isfinite(flux)))
            resp = self.client.get(
                "/api/sky/timeseries",
                params={"coord": targets_by_id[tid]["name"], "detector": "D6"},
            )
            self.assertEqual(resp.status_code, 200)
            body = resp.json()
            self.assertEqual(body["source_mode"], "hour0_calibrated_pack", msg=tid)
            self.assertIsNotNone(body["patch_timeseries"], msg=tid)
            self.assertEqual(len(body["patch_timeseries"]["frames_by_visit"]), 3)

        # Saturation bitmask should mask peak core pixels to NaN on bright saturated targets (Barnard's Star & R Draconis)
        _, flux_bs, mask_bs = load_patch_arrays(CONTRACTS_DIR, target_id="TGT-01")
        self.assertGreater(int(np.count_nonzero((mask_bs[:, :3, :, :] & 2) != 0)), 0)
        self.assertTrue(np.all(np.isnan(flux_bs[(mask_bs & 7) != 0])))

        # 2. Static fallback bundle must be served & integrated in HTML, and viewer.js must run all 5 targets with API down
        r_fb = self.client.get("/static/fallback_data.js")
        self.assertEqual(r_fb.status_code, 200)
        index_html = open(os.path.join(ROOT_DIR, "phantom_worlds", "static", "index.html"), encoding="utf-8").read()
        self.assertIn("/static/fallback_data.js", index_html)

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not found on PATH")

        fallback_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "fallback_data.js")
        viewer_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "viewer.js")
        offline_harness = textwrap.dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            function makeEl(id, extra = {}) {
              const listeners = {};
              return {
                id,
                value: "",
                checked: false,
                disabled: false,
                max: "2",
                min: "0",
                textContent: "",
                options: [],
                children: [],
                dataset: {},
                classList: {
                  _set: new Set(),
                  toggle(c, on) { if (on === undefined ? !this._set.has(c) : on) this._set.add(c); else this._set.delete(c); },
                  add(c) { this._set.add(c); },
                  contains(c) { return this._set.has(c); },
                },
                attributes: {},
                setAttribute(k, v) { this.attributes[k] = String(v); },
                addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
                trigger(ev, e = { preventDefault() {} }) { (listeners[ev] || []).forEach((fn) => fn(e)); },
                append(...nodes) { this.children.push(...nodes); },
                appendChild(n) { this.children.push(n); if (this.options) this.options.push(n); return n; },
                replaceChildren(...nodes) { this.children = [...nodes]; },
                getBoundingClientRect() { return { left: 0, top: 0, width: 512, height: 512 }; },
                ...extra,
              };
            }

            const drawLog = { skyArcs: [], skyTexts: [], putImages: 0 };
            function makeCtx(isSky) {
              return {
                fillStyle: "",
                strokeStyle: "",
                lineWidth: 1,
                font: "",
                imageSmoothingEnabled: false,
                setLineDash() {},
                fillRect() {},
                strokeRect() {},
                fillText(t, x, y) { if (isSky) drawLog.skyTexts.push(String(t)); },
                createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
                putImageData() { if (isSky) drawLog.putImages += 1; },
                drawImage() { if (isSky) drawLog.putImages += 1; },
                beginPath() {},
                moveTo() {},
                lineTo() {},
                arc(x, y, r) { if (isSky) drawLog.skyArcs.push({ x, y, r }); },
                stroke() {},
              };
            }

            const targetNames = ["Barnard's Star", "WISE 0855", "Epsilon Indi B", "RW Aurigae", "R Draconis"];
            const byId = {
              "sky-query-form": makeEl("sky-query-form"),
              "coord-input": makeEl("coord-input", { value: "WISE 0855" }),
              "fov-select": makeEl("fov-select", {
                value: "6.5",
                options: ["2.5", "5.0", "6.5", "12.0"].map((v) => ({ value: v, textContent: v })),
              }),
              "epoch-input": makeEl("epoch-input", { value: "2026" }),
              "live-toggle": makeEl("live-toggle", { checked: false }),
              "mode-badge": makeEl("mode-badge"),
              "status-banner": makeEl("status-banner"),
              "sky-canvas": makeEl("sky-canvas", { width: 512, height: 512, getContext: () => makeCtx(true) }),
              "spectrum-canvas": makeEl("spectrum-canvas", { width: 640, height: 190, getContext: () => makeCtx(false) }),
              "matrix-canvas": makeEl("matrix-canvas", { width: 640, height: 150, getContext: () => makeCtx(false) }),
              "play-toggle": makeEl("play-toggle"),
              "visit-scrubber": makeEl("visit-scrubber", { value: "0", max: "2" }),
              "visit-label": makeEl("visit-label"),
              "stretch-select": makeEl("stretch-select", { value: "asinh" }),
              "gaia-overlay-toggle": makeEl("gaia-overlay-toggle", { checked: true }),
              "mask-overlay-toggle": makeEl("mask-overlay-toggle", { checked: true }),
              "pixel-readout": makeEl("pixel-readout"),
              "molecule-list": makeEl("molecule-list"),
              "frames-tbody": makeEl("frames-tbody"),
              "frames-heading": makeEl("frames-heading"),
              "spectrum-heading": makeEl("spectrum-heading"),
              "copy-url-btn": makeEl("copy-url-btn"),
            };
            const modeBtns = ["play", "stack", "difference", "rgb"].map((m) => makeEl("m-" + m, { dataset: { mode: m } }));
            const detBtns = ["D1", "D2", "D3", "D4", "D5", "D6"].map((d) => makeEl("d-" + d, { dataset: { det: d } }));
            const presetBtns = targetNames.map((c) => makeEl("p-" + c, { dataset: { coord: c } }));

            const window = {
              location: { search: "", pathname: "/", href: "http://127.0.0.1/" },
              history: { replaceState() {} },
              setInterval() { return 1; },
              clearInterval() {},
            };
            const document = {
              body: { classList: makeEl("body").classList },
              getElementById(id) { return byId[id] || null; },
              querySelectorAll(sel) {
                if (sel === ".mode-btn") return modeBtns;
                if (sel === ".det-btn") return detBtns;
                if (sel === ".preset-btn") return presetBtns;
                return [];
              },
              createElement(tag) {
                if (tag === "canvas") return makeEl("tmp-canvas", { width: 64, height: 64, getContext: () => makeCtx(false) });
                return makeEl(tag);
              },
            };
            const ctx = {
              window,
              document,
              globalThis: null,
              fetch: async () => { throw new TypeError("Failed to fetch"); },
              URL, URLSearchParams, AbortController, Uint8ClampedArray, Uint8Array, Uint16Array, DataView, atob,
              navigator: {}, console, Math, Number, String, Boolean, Array, Object, Set, JSON,
            };
            ctx.globalThis = ctx;

            const fbCode = fs.readFileSync(process.argv[1], "utf8");
            const viewerCode = fs.readFileSync(process.argv[2], "utf8");
            vm.runInNewContext(fbCode, ctx);
            vm.runInNewContext(viewerCode, ctx);

            (async () => {
              await new Promise((r) => setTimeout(r, 25));
              for (const btn of presetBtns) {
                drawLog.skyTexts.length = 0;
                drawLog.putImages = 0;
                drawLog.skyArcs.length = 0;
                btn.trigger("click");
                await new Promise((r) => setTimeout(r, 20));
                assert(byId["mode-badge"].textContent.includes("static"), "Mode badge not switched to static fallback for " + btn.dataset.coord + ": " + byId["mode-badge"].textContent);
                assert(drawLog.putImages > 0, "No static pack.bin pixel image drawn offline for " + btn.dataset.coord);
                assert(!drawLog.skyTexts.some((t) => t.includes("No local pack.bin")), "Missing cutout fallback text for " + btn.dataset.coord);
                assert(byId["frames-tbody"].children.length > 0, "No static fallback frames for " + btn.dataset.coord);
                assert(byId["molecule-list"].children.length > 0, "No offline molecule readings rendered for " + btn.dataset.coord);
              }
              detBtns[0].trigger("click");
              await new Promise((r) => setTimeout(r, 20));
              assert(byId["status-banner"].textContent.includes("Barnard") || byId["status-banner"].textContent.includes("R Draconis") || drawLog.putImages > 0);

              // Uncovered arbitrary coordinates offline should degrade cleanly to Sky Footprint
              byId["coord-input"].value = "180.0, 45.0";
              byId["sky-query-form"].trigger("submit", { preventDefault() {} });
              await new Promise((r) => setTimeout(r, 20));
              assert.strictEqual(byId["visit-label"].textContent, "Sky Footprint");
              assert(byId["mode-badge"].textContent.includes("static"), "Uncovered offline mode badge must reflect static fallback");
            })().catch((err) => { console.error(err); process.exit(1); });
            """
        ).strip()

        proc = subprocess.run(
            [node_bin, "-e", offline_harness, fallback_js_path, viewer_js_path],
            capture_output=True,
            text=True,
            timeout=15,
        )
        self.assertEqual(proc.returncode, 0, msg=f"Offline static fallback checks failed:\n{proc.stderr}\n{proc.stdout}")

    def test_embed_mode_relaxes_csp_frame_ancestors_without_weakening_default(self):
        # Default root page must keep strict same-origin framing to prevent clickjacking.
        r_default = self.client.get("/")
        self.assertEqual(r_default.status_code, 200)
        csp_default = r_default.headers.get("content-security-policy", "")
        self.assertIn("frame-ancestors 'self'", csp_default)
        self.assertIn("script-src 'self'", csp_default)

        # Malformed or non-1 embed values must NOT relax frame-ancestors or inject CSP directives.
        for bad_embed in ("0", "true", "1;script-src 'unsafe-inline'"):
            r_bad = self.client.get("/", params={"embed": bad_embed})
            self.assertEqual(r_bad.status_code, 200)
            csp_bad = r_bad.headers.get("content-security-policy", "")
            self.assertIn("frame-ancestors 'self'", csp_bad)
            self.assertNotIn("unsafe-inline", csp_bad)

        # ?embed=1 must allow only explicit allowlisted HTTPS portals & local dev iframes (NEVER bare https: wildcard).
        r_embed = self.client.get("/", params={"coord": "Barnard's Star", "embed": "1"})
        self.assertEqual(r_embed.status_code, 200)
        self.assertEqual(r_embed.headers.get("x-content-type-options"), "nosniff")
        csp_embed = r_embed.headers.get("content-security-policy", "")
        self.assertIn("default-src 'self'", csp_embed)
        self.assertIn("script-src 'self'", csp_embed)
        self.assertIn("object-src 'none'", csp_embed)
        self.assertIn("base-uri 'self'", csp_embed)
        self.assertNotIn("frame-ancestors 'self';", csp_embed)
        self.assertNotIn("frame-ancestors *", csp_embed)
        self.assertNotRegex(csp_embed, r"(?:^|\s)https?:(?:\s|$|;)")
        self.assertNotRegex(csp_embed, r"(?:^|\s)https?://\*(?:\s|$|;)")
        self.assertIn("https://*.nasa.gov", csp_embed)

        # Operator-configured embed origins must reject bare https:, wildcards, or CSP directive breakouts.
        import phantom_worlds.api as api_mod
        for bad_ancestor in ("https:", "*", "https://*;script-src 'unsafe-inline'", "http://evil.example.com"):
            with self.assertRaises(ValueError):
                api_mod.create_app(embed_frame_ancestors=[bad_ancestor])
        custom_client = TestClient(api_mod.create_app(embed_frame_ancestors=["https://portal.example.org"]))
        csp_custom = custom_client.get("/", params={"embed": "1"}).headers.get("content-security-policy", "")
        self.assertIn("https://portal.example.org", csp_custom)
        self.assertNotRegex(csp_custom, r"(?:^|\s)https?:(?:\s|$|;)")

    def test_sky_timeseries_preserves_newest_qr3_epochs_and_tightens_coordinate_matching(self):
        # 1. Local target queries must NOT truncate at 300 ascending and drop newest spherex_qr3 / qr3_deep epochs.
        expected = {
            "Epsilon Indi B": (487, {"spherex_qr3": 120}, 61310.0),
            "R Draconis": (2588, {"spherex_qr3_deep": 749, "spherex_qr3": 127}, 61300.0),
            "Barnard's Star": (387, {"spherex_qr3": 129}, 61300.0),
            "RW Aurigae": (343, {"spherex_qr3": 114}, 61290.0),
        }
        for name, (total_count, min_cols, min_newest_mjd) in expected.items():
            resp = self.client.get("/api/sky/timeseries", params={"coord": name, "fov_arcmin": 6.5})
            self.assertEqual(resp.status_code, 200, msg=name)
            frames = resp.json()["frames"]
            self.assertEqual(len(frames), total_count, msg=f"{name} frame count dropped")
            self.assertGreaterEqual(frames[0]["t_min"], min_newest_mjd, msg=f"{name} newest epoch not first")
            for col_name, expected_cnt in min_cols.items():
                actual_cnt = sum(1 for fr in frames if fr.get("obs_collection") == col_name)
                self.assertEqual(actual_cnt, expected_cnt, msg=f"{name} missing {col_name}")

        # 2. Coordinate matching must respect half-FOV and cutout half-width (not max(fov_arcmin, 6.5)).
        wise_j2000_ra, wise_j2000_dec = 133.795129, -7.245147
        barnard_j2000_ra, barnard_j2000_dec = 269.452083, 4.693361

        # 4.0' away from WISE 0855 at default 6.5' FOV (half-FOV = 3.25') must NOT falsely match TGT-02
        offset_4_ra = wise_j2000_ra + (4.0 / 60.0) / math.cos(math.radians(wise_j2000_dec))
        r_4 = self.client.get("/api/sky/timeseries", params={"ra_deg": offset_4_ra, "dec_deg": wise_j2000_dec, "fov_arcmin": 6.5})
        self.assertEqual(r_4.status_code, 200)
        b_4 = r_4.json()
        self.assertIsNone(b_4["matched_target"])
        self.assertIsNone(b_4["patch_timeseries"])
        self.assertEqual(b_4["frames"], [])

        # 1.5' away from Barnard's Star at narrow 1.0' FOV (half-FOV = 0.5') must NOT falsely match TGT-01
        offset_15_ra = barnard_j2000_ra + (1.5 / 60.0) / math.cos(math.radians(barnard_j2000_dec))
        r_15 = self.client.get("/api/sky/timeseries", params={"ra_deg": offset_15_ra, "dec_deg": barnard_j2000_dec, "fov_arcmin": 1.0})
        self.assertEqual(r_15.status_code, 200)
        self.assertIsNone(r_15.json()["matched_target"])
        self.assertIsNone(r_15.json()["patch_timeseries"])

        # 10.0' away from Barnard's Star at wide 30.0' FOV (> 3.25' cutout half-width) must NOT match TGT-01
        r_10 = self.client.get("/api/sky/timeseries", params={"ra_deg": barnard_j2000_ra, "dec_deg": barnard_j2000_dec + 10.0 / 60.0, "fov_arcmin": 30.0})
        self.assertEqual(r_10.status_code, 200)
        self.assertIsNone(r_10.json()["matched_target"])
        self.assertIsNone(r_10.json()["patch_timeseries"])

        # Exact J2000 coordinate of WISE 0855 with narrow 0.5' FOV MUST still match TGT-02
        r_exact = self.client.get("/api/sky/timeseries", params={"ra_deg": wise_j2000_ra, "dec_deg": wise_j2000_dec, "fov_arcmin": 0.5})
        self.assertEqual(r_exact.status_code, 200)
        self.assertEqual(r_exact.json()["matched_target"]["target_id"], "TGT-02")

    def test_analyze_spectrum_prevents_http500_and_targets_carry_real_blend_err_and_variable_refusal(self):
        import phantom_worlds.api as api_mod

        safe_client = TestClient(api_mod.create_app(), raise_server_exceptions=False)

        # 1. Extreme valid IEEE floats must never trigger unhandled HTTP 500 JSON/overflow crashes
        for bad_payload in (
            {"flux_uJy": [1e308] * 102},
            {"flux_uJy": [100.0] * 102, "flux_err_uJy": [1e308] * 102},
        ):
            r_ext = safe_client.post("/api/analyze/spectrum", json=bad_payload)
            self.assertEqual(r_ext.status_code, 422, msg=f"Expected 422 instead of {r_ext.status_code}")

        # Large dynamic range within physical/finite bounds must return 200 with strictly finite values
        r_dyn = safe_client.post(
            "/api/analyze/spectrum",
            json={"flux_uJy": [1e25] * 50 + [1e-12] * 52, "flux_err_uJy": [1e23] * 50 + [1e-13] * 52},
        )
        self.assertEqual(r_dyn.status_code, 200)
        self.assertIn(r_dyn.json()["molecule_readings"]["status"], ("MEASURED", "REFUSED"))

        # 2. All 5 targets must expose per-target blend_share (not uniform 0.08) + finite flux_err_uJy
        blend_by_name = {}
        for name in ("Barnard's Star", "WISE 0855", "Epsilon Indi B", "RW Aurigae", "R Draconis"):
            r_t = safe_client.get("/api/sky/timeseries", params={"coord": name})
            self.assertEqual(r_t.status_code, 200)
            spec = r_t.json()["spectrum_102"]
            blend_by_name[name] = spec["blend_share"]
            self.assertIn("flux_err_uJy", spec, msg=f"{name} missing flux_err_uJy")
            self.assertEqual(len(spec["flux_err_uJy"]), 102)
            self.assertTrue(all(math.isfinite(v) and v > 0.0 for v in spec["flux_err_uJy"]))
            self.assertTrue(spec.get("flux_err_origin"))

        self.assertGreater(len(set(blend_by_name.values())), 2)
        self.assertGreater(blend_by_name["Epsilon Indi B"], 0.08)
        self.assertGreater(blend_by_name["RW Aurigae"], 0.08)
        self.assertLess(blend_by_name["Barnard's Star"], 0.08)

        # 3. Variable targets (RW Aurigae & R Draconis) must propagate is_variable=True and refuse molecule readings per AGENTS.md
        for var_name in ("RW Aurigae", "R Draconis"):
            r_var = safe_client.get("/api/sky/timeseries", params={"coord": var_name})
            var_spec = r_var.json()["spectrum_102"]
            self.assertTrue(var_spec["target_is_variable"], msg=var_name)
            self.assertTrue(var_spec["is_variable"], msg=var_name)
            r_var_mol = safe_client.post(
                "/api/analyze/spectrum",
                json={
                    "flux_uJy": var_spec["flux_uJy"],
                    "flux_err_uJy": var_spec["flux_err_uJy"],
                    "blend_share": var_spec["blend_share"],
                    "is_variable": var_spec["is_variable"],
                },
            )
            self.assertEqual(r_var_mol.status_code, 200)
            mr_var = r_var_mol.json()["molecule_readings"]
            self.assertEqual(mr_var["status"], "REFUSED", msg=var_name)
            self.assertIn("variable", mr_var["refusal_reason"].lower(), msg=var_name)

        # Static fallback offline molecule readings must also enforce refusal for variable targets
        with open(os.path.join(ROOT_DIR, "phantom_worlds", "static", "fallback_data.js"), encoding="utf-8") as fb_file:
            fb_raw = fb_file.read()
        fb_json = json.loads(fb_raw.split("=", 1)[1].strip().rstrip(";"))
        for tid in ("TGT-04", "TGT-05"):
            tgt_fb = fb_json["targets"][tid]
            self.assertTrue(tgt_fb["spectrum_102"]["is_variable"], msg=tid)
            self.assertEqual(tgt_fb["molecule_readings"]["status"], "REFUSED", msg=tid)
            self.assertIn("variable", tgt_fb["molecule_readings"]["refusal_reason"].lower(), msg=tid)

    def test_local_gaia_sources_keeps_mag_zero_first_under_limit(self):
        from phantom_worlds.api import _load_local_gaia_sources

        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "Dummy_gaia_dr3.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as f:
                f.write("source_id,ra,dec,pmra,pmdec,phot_g_mean_mag\n")
                for i in range(1, 11):
                    f.write(f"{i},180.0,0.0,0.0,0.0,{10.0 + i}\n")
                f.write("100,180.0,0.0,0.0,0.0,0.0\n")

            out = _load_local_gaia_sources(tmpdir, "Dummy", 180.0, 0.0, 5.0, 2026.0, limit=5)

        self.assertEqual(len(out), 5)
        self.assertEqual(out[0]["source_id"], "100")
        self.assertEqual(out[0]["phot_g_mean_mag"], 0.0)

    def test_live_irsa_redirects_semaphore_partial_failures_and_empty_mode(self):
        import requests
        import phantom_worlds.api as api_mod
        from astropy.table import Table

        # 1. _LiveIrsaSession must reject HTTP 302 redirects without following SSRF target
        with api_mod._LiveIrsaSession() as sess:
            sent = []

            def fake_redirect(request, **kwargs):
                sent.append(request.url)
                resp = requests.Response()
                resp.status_code = 302
                resp.url = request.url
                resp.headers["Location"] = "https://169.254.169.254/latest/meta-data/"
                resp._content = b""
                return resp

            adapter = sess.get_adapter("https://irsa.ipac.caltech.edu/SIA")
            with mock.patch.object(adapter, "send", side_effect=fake_redirect):
                with self.assertRaises(requests.TooManyRedirects):
                    sess.get("https://irsa.ipac.caltech.edu/SIA")
            self.assertEqual(sent, ["https://irsa.ipac.caltech.edu/SIA"])

        # 2. Saturated semaphore must fail fast with warning
        with mock.patch.object(api_mod._LIVE_IRSA_SEMAPHORE, "acquire", return_value=False):
            frames_busy, gaia_busy, warns_busy = api_mod._fetch_live_sky_data(180.0, 45.0, 0.05)
        self.assertEqual((frames_busy, gaia_busy), ([], []))
        self.assertEqual(warns_busy, ["Live IRSA archive query busy; showing local results only."])

        # 3. Partial collection timeouts + masked floats + unsafe URLs + clean semaphore release
        class PartialSIA:
            def __init__(self, url, session=None):
                pass

            def search(self, pos, collection=None, **kwargs):
                if collection in ("spherex_qr3", "spherex_dr1_cube"):
                    raise TimeoutError(f"Simulated timeout on {collection}")
                if collection == "spherex_dr1":
                    tbl = Table(
                        {
                            "obs_id": ["PARTIAL_OK"],
                            "s_ra": np.ma.masked_array([999.0], mask=[True]),
                            "s_dec": [45.0],
                            "access_url": ["http://irsa.ipac.caltech.edu/insecure.fits"],
                            "cloud_access": ['{"aws":{"bucket_name":"nasa-irsa-spherex","key":"../secret","region":"us-east-1"}}'],
                        }
                    )
                else:
                    tbl = Table(
                        {
                            "obs_id": [f"SURVIVED_{collection}"],
                            "s_ra": [180.0],
                            "s_dec": [45.0],
                            "access_url": ["https://irsa.ipac.caltech.edu/ibe/data/spherex/ok.fits"],
                            "cloud_access": ['{"aws":{"bucket_name":"nasa-irsa-spherex","key":"dr1/ok.fits","region":"us-east-1"}}'],
                        }
                    )
                return type("R", (), {"to_table": lambda self, t=tbl: t})()

        with mock.patch.object(api_mod.pyvo.dal, "SIA2Service", PartialSIA):
            frames_p, _, warns_p = api_mod._fetch_live_sky_data(180.0, 45.0, 0.05)
        self.assertEqual(len(frames_p), 3)
        by_id = {f["obs_id"]: f for f in frames_p}
        self.assertIsNone(by_id["PARTIAL_OK"]["s_ra"])
        self.assertIsNone(by_id["PARTIAL_OK"]["access_url"])
        self.assertIsNone(by_id["PARTIAL_OK"]["s3_fits_url"])
        self.assertEqual(
            by_id["SURVIVED_spherex_dr1_deep"]["s3_fits_url"],
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/ok.fits",
        )
        self.assertTrue(any("2/5 collections" in w for w in warns_p))
        self.assertTrue(api_mod._LIVE_IRSA_SEMAPHORE.acquire(blocking=False))
        api_mod._LIVE_IRSA_SEMAPHORE.release()

        # 4. Constructor error releases semaphore and returns total-failure warning
        class BrokenSIA:
            def __init__(self, url, session=None):
                raise RuntimeError("DNS failure")

        with mock.patch.object(api_mod.pyvo.dal, "SIA2Service", BrokenSIA):
            frames_err, _, warns_err = api_mod._fetch_live_sky_data(180.0, 45.0, 0.05)
        self.assertEqual(frames_err, [])
        self.assertEqual(warns_err, ["Live IRSA archive query failed; showing local results only."])
        self.assertTrue(api_mod._LIVE_IRSA_SEMAPHORE.acquire(blocking=False))
        api_mod._LIVE_IRSA_SEMAPHORE.release()

        # 5. End-to-end live_irsa_empty when arbitrary sky coordinate has 0 remote/local frames
        fresh_client = TestClient(api_mod.create_app())
        with mock.patch.object(api_mod, "_fetch_live_sky_data", return_value=([], [], [])):
            r_empty = fresh_client.get(
                "/api/sky/timeseries",
                params={"ra_deg": 175.0, "dec_deg": 35.0, "live": "true"},
            )
        self.assertEqual(r_empty.status_code, 200)
        empty_json = r_empty.json()
        self.assertEqual(empty_json["source_mode"], "live_irsa_empty")
        self.assertEqual(empty_json["frames"], [])
        self.assertEqual(empty_json["gaia_sources"], [])

    def test_viewer_js_playback_hover_controls_embed_and_copy_url(self):
        import shutil
        import subprocess
        import textwrap

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not found on PATH")

        viewer_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "viewer.js")
        harness = textwrap.dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            function makeEl(id, extra = {}) {
              const listeners = {};
              return {
                id, value: "", checked: false, disabled: false, max: "2", min: "0",
                textContent: "", options: [], children: [], dataset: {},
                classList: {
                  _set: new Set(),
                  toggle(c, on) { if (on === undefined ? !this._set.has(c) : on) this._set.add(c); else this._set.delete(c); },
                  add(c) { this._set.add(c); },
                  contains(c) { return this._set.has(c); },
                },
                attributes: {},
                setAttribute(k, v) { this.attributes[k] = String(v); },
                addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
                trigger(ev, e = { preventDefault() {} }) { (listeners[ev] || []).forEach((fn) => fn(e)); },
                append(...nodes) { this.children.push(...nodes); },
                appendChild(n) { this.children.push(n); if (this.options) this.options.push(n); return n; },
                replaceChildren(...nodes) { this.children = [...nodes]; },
                getBoundingClientRect() { return { left: 0, top: 0, width: 512, height: 512 }; },
                ...extra,
              };
            }

            function makeCtx() {
              return {
                fillStyle: "", strokeStyle: "", lineWidth: 1, font: "", imageSmoothingEnabled: false,
                setLineDash() {}, fillRect() {}, strokeRect() {}, fillText() {},
                createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
                putImageData() {}, drawImage() {}, beginPath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {},
              };
            }

            const byId = {
              "sky-query-form": makeEl("sky-query-form"),
              "coord-input": makeEl("coord-input", { value: "RW Aurigae" }),
              "fov-select": makeEl("fov-select", { value: "6.5", options: ["2.5", "6.5", "12.0"].map((v) => ({ value: v, textContent: v })) }),
              "epoch-input": makeEl("epoch-input", { value: "2026" }),
              "live-toggle": makeEl("live-toggle", { checked: false }),
              "mode-badge": makeEl("mode-badge"),
              "status-banner": makeEl("status-banner"),
              "sky-canvas": makeEl("sky-canvas", { width: 512, height: 512, getContext: () => makeCtx() }),
              "spectrum-canvas": makeEl("spectrum-canvas", { width: 512, height: 240, getContext: () => makeCtx() }),
              "matrix-canvas": makeEl("matrix-canvas", { width: 512, height: 240, getContext: () => makeCtx() }),
              "play-toggle": makeEl("play-toggle"),
              "visit-scrubber": makeEl("visit-scrubber", { value: "0", max: "2" }),
              "visit-label": makeEl("visit-label"),
              "stretch-select": makeEl("stretch-select", { value: "asinh" }),
              "gaia-overlay-toggle": makeEl("gaia-overlay-toggle", { checked: true }),
              "mask-overlay-toggle": makeEl("mask-overlay-toggle", { checked: true }),
              "pixel-readout": makeEl("pixel-readout"),
              "molecule-list": makeEl("molecule-list"),
              "frames-tbody": makeEl("frames-tbody"),
              "frames-heading": makeEl("frames-heading"),
              "spectrum-heading": makeEl("spectrum-heading"),
              "copy-url-btn": makeEl("copy-url-btn"),
            };
            const modeBtns = ["play", "stack", "difference", "rgb"].map((m) => makeEl("m-" + m, { dataset: { mode: m } }));
            const detBtns = ["D1", "D2", "D3", "D4", "D5", "D6"].map((d) => makeEl("d-" + d, { dataset: { det: d } }));
            const presetBtns = [];
            const intervals = [];
            const copied = [];
            const fetchUrls = [];
            const analyzePayloads = [];
            const searchStr = "?coord=RW+Aurigae&embed=1&stretch=linear&gaia=0&mask=0&mode=stack";
            const window = {
              location: { search: searchStr, pathname: "/", href: "http://127.0.0.1/" + searchStr },
              history: { replaceState(_s, _t, u) { window.location.href = "http://127.0.0.1" + u; } },
              setInterval(fn, ms) { const item = { fn, ms }; intervals.push(item); return intervals.length; },
              clearInterval() {},
            };
            const document = {
              body: { classList: makeEl("body").classList },
              getElementById(id) { return byId[id] || null; },
              querySelectorAll(sel) { return sel === ".mode-btn" ? modeBtns : (sel === ".det-btn" ? detBtns : presetBtns); },
              createElement(tag) { return tag === "canvas" ? makeEl("c", { width: 2, height: 2, getContext: () => makeCtx() }) : makeEl(tag); },
            };

            const ctx = {
              window, document,
              URL, URLSearchParams, AbortController, Uint8ClampedArray,
              navigator: { clipboard: { async writeText(txt) { copied.push(txt); } } },
              console, Math, Number, String, Boolean, Array, Object, Set, JSON,
              async fetch(url, opts = {}) {
                fetchUrls.push(String(url));
                if (String(url).includes("/api/analyze/spectrum")) {
                  analyzePayloads.push(JSON.parse(opts.body));
                  return {
                    ok: true, status: 200,
                    async json() {
                      return {
                        molecule_readings: {
                          status: "MEASURED",
                          features: {
                            H2O_ice_3_05: { status: "MEASURED", integrated_tau: 0.42, uncertainty_available: true, p16: 0.37, p84: 0.47 },
                            CO2_4_26: { status: "MEASURED", integrated_tau: 0.18, uncertainty_available: false, p16: null, p84: null },
                            CH4_3_3: { status: "REFUSED", refusal_reason: "Fewer than 3 bands" },
                          },
                        },
                      };
                    },
                  };
                }
                return {
                  ok: true, status: 200,
                  async json() {
                    return {
                      query: { ra_deg: 76.9565, dec_deg: 30.4014, fov_arcmin: Number(byId["fov-select"].value), epoch_yr: Number(byId["epoch-input"].value), detector: "D6" },
                      source_mode: "hour0_calibrated_pack",
                      matched_target: { target_id: "TGT-04", name: "RW Aurigae", ra_deg_at_epoch: 76.9565, dec_deg_at_epoch: 30.4014 },
                      patch_timeseries: {
                        center_ra_deg: 76.9565, center_dec_deg: 30.4014, fov_arcmin: 6.5,
                        visits: [
                          { visit_id: "V1", epoch_iso: "2026-01-01T00:00:00Z" },
                          { visit_id: "V2", epoch_iso: "2026-02-01T00:00:00Z" },
                          { visit_id: "V3", epoch_iso: "2026-03-01T00:00:00Z" },
                        ],
                        frames_by_visit: [
                          [[1.0, 2.0], [3.0, null]],
                          [[4.0, null], [6.0, 7.0]],
                          [[8.0, 9.0], [10.0, 11.0]],
                        ],
                        stack: [[4.33, 5.5], [6.33, 9.0]],
                        difference: [[7.0, 7.0], [7.0, 11.0]],
                        mask_overlay: [[0, 1], [0, 4]],
                      },
                      frames: [
                        { obs_id: "BAD_CTL", s_ra: 76.9, s_dec: 30.4, s3_fits_url: "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits\\n" },
                        { obs_id: "BAD_USER", s_ra: 76.9, s_dec: 30.4, s3_fits_url: "https://u@nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits" },
                        { obs_id: "GOOD_IRSA", s_ra: 76.9, s_dec: 30.4, access_url: "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/a.fits" },
                        { obs_id: "BAD_S3_SLASH", s_ra: 76.9, s_dec: 30.4, s3_fits_url: "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com//dr1/a.fits" },
                        { obs_id: "BAD_IRSA_QUERY", s_ra: 76.9, s_dec: 30.4, access_url: "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/a.fits?redirect=https://evil.example" },
                        { obs_id: "BAD_IRSA_TRAV", s_ra: 76.9, s_dec: 30.4, access_url: "https://irsa.ipac.caltech.edu/ibe/data/spherex/../secret.fits" },
                        { obs_id: "BAD_IRSA_PAGE", s_ra: 76.9, s_dec: 30.4, access_url: "https://irsa.ipac.caltech.edu/login" },
                      ],
                      gaia_sources: [],
                      spectrum_102: {
                        label: "RW Aurigae",
                        wavelength_um: Array.from({ length: 102 }, (_, i) => 0.75 + i * 0.04),
                        flux_uJy: Array(102).fill(25.0),
                        flux_err_uJy: Array(102).fill(0.8),
                        blend_share: 0.15,
                        is_variable: true,
                        target_is_variable: true,
                        spectrum_epoch_mode: "multi_visit_composite",
                      },
                      warnings: [],
                    };
                  },
                };
              },
            };

            vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
            (async () => {
              await new Promise((r) => setTimeout(r, 25));

              // 1. Embed mode & URL param sync + online molecule cards
              assert(document.body.classList.contains("embed-mode"), "embed=1 did not add body.embed-mode");
              assert.strictEqual(byId["stretch-select"].value, "linear");
              assert.strictEqual(byId["gaia-overlay-toggle"].checked, false);
              assert.strictEqual(byId["mask-overlay-toggle"].checked, false);
              assert.strictEqual(byId["visit-label"].textContent, "Mean Stack");
              assert.strictEqual(modeBtns.find((b) => b.dataset.mode === "stack").attributes["aria-pressed"], "true");
              assert(analyzePayloads.length >= 1 && analyzePayloads[0].is_variable === true, "viewer.js bypassed target_is_variable flag");
              const molText = byId["molecule-list"].children.map((c) => c.children.map((x) => x.textContent).join(": ")).join(" | ");
              assert(!molText.includes("Single-Visit Mode"), "Legacy Single-Visit Mode bypass banner should not appear: " + molText);
              assert(molText.includes("tau=0.420 ± 0.050"), "Missing H2O tau±err: " + molText);
              assert(molText.includes("tau=0.180 (no flux_err)"), "Missing no flux_err label: " + molText);
              assert(molText.includes("Fewer than 3 bands"), "Missing refused feature note: " + molText);

              // S3/URL XSS/injection filtering on frame table links
              const frameRows = byId["frames-tbody"].children;
              assert.strictEqual(frameRows[0].children[5].textContent, "-", "Control char URL should be rejected");
              assert.strictEqual(frameRows[1].children[5].textContent, "-", "Userinfo URL should be rejected");
              assert.strictEqual(frameRows[2].children[5].children[0].textContent, "IRSA FITS");
              assert.strictEqual(frameRows[3].children[5].textContent, "-", "Leading double-slash S3 URL should be rejected");
              assert.strictEqual(frameRows[4].children[5].textContent, "-", "IRSA query redirect URL should be rejected");
              assert.strictEqual(frameRows[5].children[5].textContent, "-", "IRSA traversal URL should be rejected");
              assert.strictEqual(frameRows[6].children[5].textContent, "-", "Non-FITS IRSA path should be rejected");

              // 2. Hover readout in stack, play (normal + masked null), and 3-visit RGB mode
              byId["sky-canvas"].trigger("mousemove", { clientX: 10, clientY: 10 });
              assert(byId["pixel-readout"].textContent.includes("4.330 rel | Mask bits: 0"), byId["pixel-readout"].textContent);
              modeBtns.find((b) => b.dataset.mode === "play").trigger("click");
              assert.strictEqual(byId["visit-label"].textContent, "V1 (2026-01-01)");
              byId["sky-canvas"].trigger("mousemove", { clientX: 400, clientY: 400 });
              assert(byId["pixel-readout"].textContent.includes("MASKED (NaN) | Mask bits: 4"), byId["pixel-readout"].textContent);
              modeBtns.find((b) => b.dataset.mode === "rgb").trigger("click");
              assert.strictEqual(byId["visit-label"].textContent, "RGB (V1/V2/V3)");
              byId["sky-canvas"].trigger("mousemove", { clientX: 400, clientY: 10 });
              assert(byId["pixel-readout"].textContent.includes("RGB Flux: 2.00/NaN/9.00 rel | Mask bits: 1"), byId["pixel-readout"].textContent);

              // 3. Playback timer + play-toggle + scrubber interaction
              modeBtns.find((b) => b.dataset.mode === "play").trigger("click");
              byId["play-toggle"].trigger("click"); // pause
              assert.strictEqual(byId["play-toggle"].textContent, "Play");
              intervals[0].fn();
              assert.strictEqual(byId["visit-scrubber"].value, "0");
              byId["play-toggle"].trigger("click"); // resume
              assert.strictEqual(byId["play-toggle"].textContent, "Pause");
              intervals[0].fn();
              assert.strictEqual(byId["visit-label"].textContent, "V2 (2026-02-01)");
              byId["visit-scrubber"].value = "2";
              byId["visit-scrubber"].trigger("input");
              assert.strictEqual(byId["play-toggle"].textContent, "Play");
              assert.strictEqual(byId["visit-label"].textContent, "V3 (2026-03-01)");

              // 4. Form submit, stretch/overlay toggles, & copy URL button
              byId["stretch-select"].value = "asinh";
              byId["stretch-select"].trigger("change");
              byId["fov-select"].value = "12.0";
              byId["epoch-input"].value = "2027.5";
              byId["sky-query-form"].trigger("submit", { preventDefault() {} });
              await new Promise((r) => setTimeout(r, 20));
              assert(fetchUrls.some((u) => u.includes("fov_arcmin=12") && u.includes("epoch_yr=2027.5")), "Updated FOV/epoch not sent in fetch");
              await byId["copy-url-btn"].trigger("click");
              await new Promise((r) => setTimeout(r, 10));
              assert.strictEqual(copied.length, 1);
              assert(copied[0].includes("embed=1") && copied[0].includes("stretch=asinh"), "Copied URL out of sync: " + copied[0]);
              assert(byId["status-banner"].textContent.includes("Share URL copied"), byId["status-banner"].textContent);
            })().catch((err) => { console.error(err); process.exit(1); });
            """
        ).strip()

        proc = subprocess.run([node_bin, "-e", harness, viewer_js_path], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, msg=f"viewer.js extended UI checks failed:\n{proc.stderr}\n{proc.stdout}")

    def test_app_caches_disk_reads_across_repeated_requests(self):
        import builtins
        import phantom_worlds.api as api_mod

        local_client = TestClient(api_mod.create_app())
        opened = []
        real_open = builtins.open

        def spying_open(file, *args, **kwargs):
            if isinstance(file, (str, os.PathLike)):
                opened.append(os.path.basename(os.fspath(file)))
            return real_open(file, *args, **kwargs)

        with mock.patch.object(builtins, "open", side_effect=spying_open):
            for _ in range(2):
                self.assertEqual(local_client.get("/").status_code, 200)
                self.assertEqual(local_client.get("/health").status_code, 200)
                self.assertEqual(local_client.get("/api/patch/manifest").status_code, 200)
                self.assertEqual(local_client.get("/api/patch/manifest", params={"target_id": "TGT-05"}).status_code, 200)
                self.assertEqual(local_client.get("/api/sources").status_code, 200)
                self.assertEqual(local_client.get("/api/cases").status_code, 200)
                self.assertEqual(local_client.get("/api/cases/CASE-W0855-001/export").status_code, 200)
            r1 = local_client.get("/api/sky/timeseries", params={"coord": "R Draconis", "epoch_yr": 2026.0, "detector": "D6"})
            r2 = local_client.get("/api/sky/timeseries", params={"coord": "R Draconis", "epoch_yr": 2027.0, "detector": "D6"})
            self.assertEqual(r1.status_code, 200)
            self.assertEqual(r2.status_code, 200)
            self.assertEqual(len(r1.json()["frames"]), 2588)
            self.assertGreater(len(r2.json()["gaia_sources"]), 0)

        self.assertLessEqual(opened.count("index.html"), 1)
        self.assertLessEqual(opened.count("sources.json"), 1)
        self.assertLessEqual(opened.count("cases.json"), 1)
        self.assertLessEqual(opened.count("manifest.json"), 2)
        self.assertLessEqual(opened.count("R_Draconis_spherex_frames.csv"), 1)
        self.assertLessEqual(opened.count("R_Draconis_gaia_dr3.csv"), 1)

    def test_csp_includes_form_action_self_in_default_and_embed_modes(self):
        for params in (None, {"embed": "1"}):
            resp = self.client.get("/", params=params)
            self.assertEqual(resp.status_code, 200)
            csp = resp.headers.get("content-security-policy", "")
            self.assertIn("form-action 'self'", csp)

    def test_all_cutouts_match_pixel_scale_fov_and_canvas_astrometry(self):
        import shutil
        import subprocess
        import textwrap
        from datetime import datetime
        from phantom_worlds.contracts import load_patch_arrays, load_targets, propagate_position

        targets_by_id = {row["target_id"]: row for row in load_targets(CSV_DIR)}

        def _expected_canvas_px(ra_deg, dec_deg, manifest):
            nx = int(manifest["cutout_size_px"][0])
            ny = int(manifest["cutout_size_px"][1])
            cra = float(manifest["center_ra_deg"])
            cdec = float(manifest["center_dec_deg"])
            fov = float(manifest["fov_arcmin"])
            cosd = max(math.cos(math.radians(cdec)), 1e-6)
            d_ra = ((ra_deg - cra + 540.0) % 360.0) - 180.0
            dx_arcmin = d_ra * cosd * 60.0
            dy_arcmin = (dec_deg - cdec) * 60.0
            return (nx - 1) / 2.0 - dx_arcmin * (nx / fov), (ny - 1) / 2.0 - dy_arcmin * (ny / fov)

        def _centroid(plane, ex, ey, half_box=3):
            x0, x1 = max(0, int(round(ex)) - half_box), min(plane.shape[1], int(round(ex)) + half_box + 1)
            y0, y1 = max(0, int(round(ey)) - half_box), min(plane.shape[0], int(round(ey)) + half_box + 1)
            sub = np.nan_to_num(plane[y0:y1, x0:x1] - float(np.nanmedian(plane)), nan=0.0)
            w = np.clip(sub, 0.0, None)
            yy, xx = np.mgrid[y0:y1, x0:x1]
            return float((xx * w).sum() / w.sum()), float((yy * w).sum() / w.sum())

        for tid in ("TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"):
            manifest, flux, _ = load_patch_arrays(CONTRACTS_DIR, target_id=tid)
            nx = int(manifest["cutout_size_px"][0])
            pix_scale = float(manifest["pixel_scale_arcsec"])
            expected_fov = nx * pix_scale / 60.0
            self.assertAlmostEqual(float(manifest["fov_arcmin"]), expected_fov, places=4, msg=f"{tid} FOV scale drift")

            # Non-saturated real target fields align to Gaia DR3 field stars sub-arcsecond (< 1.0");
            # bright saturated cores (TGT-05 R Draconis, 377 overflow px) carry larger centroid scatter.
            gaia_rms = manifest.get("gaia_alignment_rms_arcsec")
            self.assertIsNotNone(gaia_rms, msg=f"Missing gaia_alignment_rms_arcsec in {tid}")
            if tid != "TGT-05":
                self.assertLessEqual(float(gaia_rms), 1.0, msg=f"{tid} Gaia RMS={gaia_rms} arcsec")

            row = targets_by_id[tid]
            ra0, dec0 = float(row["ra_deg_j2000"]), float(row["dec_deg_j2000"])
            pmra, pmdec = float(row["pm_ra_mas_yr"]), float(row["pm_dec_mas_yr"])
            # High-SNR unsaturated mover TGT-03 (Epsilon Indi B) tracks PM across V1->V2->V3 in D6
            if tid == "TGT-03":
                for vi, visit in enumerate(manifest["visits"]):
                    dt_str = visit["epoch_iso"].replace("Z", "+00:00")
                    dt = datetime.fromisoformat(dt_str)
                    yr_len = 366.0 if (dt.year % 4 == 0 and (dt.year % 100 != 0 or dt.year % 400 == 0)) else 365.0
                    epoch_yr = dt.year + (dt.timetuple().tm_yday - 1 + dt.hour / 24.0) / yr_len
                    r_v, d_v = propagate_position(ra0, dec0, pmra, pmdec, epoch_yr - 2000.0)
                    ex, ey = _expected_canvas_px(r_v, d_v, manifest)
                    cx, cy = _centroid(flux[vi, 5], ex, ey)
                    sep_arcsec = math.hypot(cx - ex, cy - ey) * pix_scale
                    self.assertLessEqual(sep_arcsec, 2.0, msg=f"{tid} {visit['visit_id']} offset={sep_arcsec:.2f} arcsec")

        node_bin = shutil.which("node")
        if node_bin:
            viewer_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "viewer.js")
            check_js = textwrap.dedent(
                """
                const assert = require("assert");
                const fs = require("fs");
                const vm = require("vm");
                function makeEl(id, extra = {}) {
                  const ls = {};
                  return {
                    id, value: "", checked: false, disabled: false, max: "2", min: "0",
                    textContent: "", options: [], children: [], dataset: {},
                    classList: { toggle() {}, add() {}, contains: () => false },
                    attributes: {}, setAttribute(k, v) { this.attributes[k] = String(v); },
                    addEventListener(ev, fn) { (ls[ev] = ls[ev] || []).push(fn); },
                    append() {}, appendChild(n) { return n; }, replaceChildren() {},
                    getBoundingClientRect() { return { left: 0, top: 0, width: 512, height: 512 }; },
                    ...extra,
                  };
                }
                const rects = [];
                const arcs = [];
                function makeCtx(track) {
                  return {
                    fillStyle: "", strokeStyle: "", lineWidth: 1, font: "", imageSmoothingEnabled: false,
                    setLineDash() {}, fillRect() {}, fillText() {}, putImageData() {}, drawImage() {},
                    strokeRect(x, y, w, h) { if (track) rects.push({ x, y, w, h, stroke: this.strokeStyle }); },
                    createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
                    beginPath() {}, moveTo() {}, lineTo() {},
                    arc(x, y, r) { if (track) arcs.push({ x, y, r, stroke: this.strokeStyle }); },
                    stroke() {},
                  };
                }
                const byId = {
                  "sky-query-form": makeEl("sky-query-form"),
                  "coord-input": makeEl("coord-input", { value: "RW Aurigae" }),
                  "fov-select": makeEl("fov-select", { value: "6.5", options: ["2.5", "5.0", "6.5", "12.0"].map((v) => ({ value: v })) }),
                  "epoch-input": makeEl("epoch-input", { value: "2026" }),
                  "live-toggle": makeEl("live-toggle", { checked: false }),
                  "mode-badge": makeEl("mode-badge"),
                  "status-banner": makeEl("status-banner"),
                  "sky-canvas": makeEl("sky-canvas", { width: 512, height: 512, getContext: () => makeCtx(true) }),
                  "spectrum-canvas": makeEl("spectrum-canvas", { width: 512, height: 240, getContext: () => makeCtx(false) }),
                  "matrix-canvas": makeEl("matrix-canvas", { width: 512, height: 240, getContext: () => makeCtx(false) }),
                  "play-toggle": makeEl("play-toggle"),
                  "visit-scrubber": makeEl("visit-scrubber", { value: "0", max: "2" }),
                  "visit-label": makeEl("visit-label"),
                  "stretch-select": makeEl("stretch-select", { value: "asinh" }),
                  "gaia-overlay-toggle": makeEl("gaia-overlay-toggle", { checked: true }),
                  "mask-overlay-toggle": makeEl("mask-overlay-toggle", { checked: true }),
                  "pixel-readout": makeEl("pixel-readout"),
                  "molecule-list": makeEl("molecule-list"),
                  "frames-tbody": makeEl("frames-tbody"),
                  "frames-heading": makeEl("frames-heading"),
                  "spectrum-heading": makeEl("spectrum-heading"),
                  "copy-url-btn": makeEl("copy-url-btn"),
                };
                const document = {
                  body: { classList: makeEl("b").classList },
                  getElementById: (id) => byId[id] || null,
                  querySelectorAll: () => [],
                  createElement: (tag) => tag === "canvas" ? makeEl("c", { width: 64, height: 64, getContext: () => makeCtx(false) }) : makeEl(tag),
                };
                const window = {
                  location: { search: "", pathname: "/", href: "http://127.0.0.1/" },
                  history: { replaceState() {} }, setInterval() { return 1; }, clearInterval() {},
                };
                const ctx = {
                  window, document, URL, URLSearchParams, AbortController, Uint8ClampedArray,
                  navigator: {}, console, Math, Number, String, Boolean, Array, Object, Set, JSON,
                  async fetch(url) {
                    if (String(url).includes("/api/analyze/spectrum")) {
                      return { ok: true, status: 200, async json() { return { molecule_readings: { status: "REFUSED", features: {} } }; } };
                    }
                    const g = Array.from({ length: 64 }, () => Array(64).fill(0));
                    g[31][31] = g[31][32] = g[32][31] = g[32][32] = 50.0;
                    return {
                      ok: true, status: 200,
                      async json() {
                        return {
                          query: { ra_deg: 76.9565, dec_deg: 30.4014, ra_deg_at_epoch: 76.9565, dec_deg_at_epoch: 30.4014, fov_arcmin: 6.5, epoch_yr: 2026.0, detector: "D6" },
                          source_mode: "hour0_calibrated_pack",
                          matched_target: { target_id: "TGT-04", name: "RW Aurigae", ra_deg_at_epoch: 76.9565, dec_deg_at_epoch: 30.4014 },
                          patch_timeseries: {
                            center_ra_deg: 76.9565, center_dec_deg: 30.4014, fov_arcmin: 6.56,
                            visits: [{ visit_id: "V1", epoch_iso: "2026-01-01T00:00:00Z" }],
                            frames_by_visit: [g], stack: g, difference: g,
                            mask_overlay: Array.from({ length: 64 }, () => Array(64).fill(0)),
                          },
                          frames: [],
                          gaia_sources: [
                            { ra_deg: 76.9565, dec_deg: 30.4014, phot_g_mean_mag: 14.0 },
                            {
                              // Pixel index (px=20, py=44) under center_px=31.5 -> canvas center ((20+0.5)*8, (44+0.5)*8) = (164, 356)
                              ra_deg: 76.9565 + ((31.5 - 20.0) * (6.56 / 64.0)) / (60.0 * Math.cos((30.4014 * Math.PI) / 180.0)),
                              dec_deg: 30.4014 + ((31.5 - 44.0) * (6.56 / 64.0)) / 60.0,
                              phot_g_mean_mag: 15.0,
                            },
                          ],
                          spectrum_102: { label: "RW Aurigae", wavelength_um: Array(102).fill(2.5), flux_uJy: Array(102).fill(1.0) },
                          warnings: [],
                        };
                      },
                    };
                  },
                };
                vm.runInNewContext(fs.readFileSync(process.argv[1], "utf8"), ctx);
                (async () => {
                  await new Promise((r) => setTimeout(r, 25));
                  assert(arcs.some((a) => Math.abs(a.x - 256) < 0.01 && Math.abs(a.y - 256) < 0.01), "Reticle not centered at 256,256");
                  assert(arcs.some((a) => Math.abs(a.x - 164) < 0.01 && Math.abs(a.y - 356) < 0.01), "Off-center Gaia star not aligned to pixel center (164,356): " + JSON.stringify(arcs));
                  assert(!rects.some((r) => r.stroke === "#facc15"), "Spurious default FOV box drawn for 6.5 vs 6.56: " + JSON.stringify(rects));
                })().catch((e) => { console.error(e); process.exit(1); });
                """
            ).strip()
            proc = subprocess.run([node_bin, "-e", check_js, viewer_js_path], capture_output=True, text=True, timeout=15)
            self.assertEqual(proc.returncode, 0, msg=f"viewer.js astrometry/FOV check failed:\n{proc.stderr}\n{proc.stdout}")

    def test_viewer_js_hover_nan_guards_coord_parser_and_ui_interactions(self):
        import shutil
        import subprocess
        import textwrap

        node_bin = shutil.which("node")
        if not node_bin:
            self.skipTest("Node.js binary not found on PATH")

        viewer_js_path = os.path.join(ROOT_DIR, "phantom_worlds", "static", "viewer.js")
        harness = textwrap.dedent(
            """
            const assert = require("assert");
            const fs = require("fs");
            const vm = require("vm");

            const unhandled = [];
            process.on("unhandledRejection", (err) => unhandled.push(err));

            function makeEl(id, extra = {}) {
              const listeners = {};
              return {
                id, value: "", checked: false, disabled: false, max: "2", min: "0",
                textContent: "", options: [], children: [], dataset: {},
                classList: {
                  _set: new Set(),
                  toggle(c, on) { if (on === undefined ? !this._set.has(c) : on) this._set.add(c); else this._set.delete(c); },
                  add(c) { this._set.add(c); },
                  contains(c) { return this._set.has(c); },
                },
                attributes: {},
                setAttribute(k, v) { this.attributes[k] = String(v); },
                addEventListener(ev, fn) { (listeners[ev] = listeners[ev] || []).push(fn); },
                trigger(ev, e = { preventDefault() {} }) { (listeners[ev] || []).forEach((fn) => fn(e)); },
                append(...nodes) { this.children.push(...nodes); },
                appendChild(n) { this.children.push(n); if (this.options) this.options.push(n); return n; },
                replaceChildren(...nodes) { this.children = [...nodes]; },
                getBoundingClientRect() { return { left: 0, top: 0, width: 512, height: 512 }; },
                ...extra,
              };
            }

            function makeCtx() {
              return {
                fillStyle: "", strokeStyle: "", lineWidth: 1, font: "", imageSmoothingEnabled: false,
                setLineDash() {}, fillRect() {}, strokeRect() {}, fillText() {},
                createImageData(w, h) { return { width: w, height: h, data: new Uint8ClampedArray(w * h * 4) }; },
                putImageData() {}, drawImage() {}, beginPath() {}, moveTo() {}, lineTo() {}, arc() {}, stroke() {},
              };
            }

            function runHarness(viewerCode, searchStr, opts = {}) {
              let canvasRect = { left: 0, top: 0, width: 512, height: 512 };
              const byId = {
                "sky-query-form": makeEl("sky-query-form"),
                "coord-input": makeEl("coord-input", { value: "Barnard's Star" }),
                "fov-select": makeEl("fov-select", { value: "6.5", options: ["2.5", "6.5", "12.0"].map((v) => ({ value: v, textContent: v })) }),
                "epoch-input": makeEl("epoch-input", { value: "2026" }),
                "live-toggle": makeEl("live-toggle", { checked: false }),
                "mode-badge": makeEl("mode-badge"),
                "status-banner": makeEl("status-banner"),
                "sky-canvas": makeEl("sky-canvas", {
                  width: 512, height: 512,
                  getContext: () => makeCtx(),
                  getBoundingClientRect: () => canvasRect,
                }),
                "spectrum-canvas": makeEl("spectrum-canvas", { width: 512, height: 240, getContext: () => makeCtx() }),
                "matrix-canvas": makeEl("matrix-canvas", { width: 512, height: 240, getContext: () => makeCtx() }),
                "play-toggle": makeEl("play-toggle"),
                "visit-scrubber": makeEl("visit-scrubber", { value: "0", max: "2" }),
                "visit-label": makeEl("visit-label"),
                "stretch-select": makeEl("stretch-select", { value: "asinh" }),
                "gaia-overlay-toggle": makeEl("gaia-overlay-toggle", { checked: true }),
                "mask-overlay-toggle": makeEl("mask-overlay-toggle", { checked: true }),
                "pixel-readout": makeEl("pixel-readout"),
                "molecule-list": makeEl("molecule-list"),
                "frames-tbody": makeEl("frames-tbody"),
                "frames-heading": makeEl("frames-heading"),
                "spectrum-heading": makeEl("spectrum-heading"),
                "copy-url-btn": makeEl("copy-url-btn"),
              };
              const modeBtns = ["play", "stack", "difference", "rgb"].map((m) => makeEl("m-" + m, { dataset: { mode: m } }));
              const detBtns = ["D1", "D2", "D3", "D4", "D5", "D6"].map((d) => makeEl("d-" + d, { dataset: { det: d } }));
              const intervals = [];
              const fetchUrls = [];
              const window = {
                location: { search: searchStr, pathname: "/", href: "http://127.0.0.1/" + searchStr },
                history: { replaceState(_s, _t, u) { window.location.href = "http://127.0.0.1" + u; } },
                setInterval(fn, ms) { const item = { fn, ms }; intervals.push(item); return intervals.length; },
                clearInterval() {},
              };
              const document = {
                body: { classList: makeEl("body").classList },
                getElementById(id) { return byId[id] || null; },
                querySelectorAll(sel) { return sel === ".mode-btn" ? modeBtns : (sel === ".det-btn" ? detBtns : []); },
                createElement(tag) { return tag === "canvas" ? makeEl("c", { width: 2, height: 2, getContext: () => makeCtx() }) : makeEl(tag); },
              };
              const fallbackBundle = opts.offline ? {
                targets: {
                  "TGT-02": {
                    target_id: "TGT-02",
                    name: "WISE 0855",
                    aliases: ["wise 0855", "wise0855"],
                    ra_deg_j2000: 133.8134,
                    dec_deg_j2000: -7.2451,
                    pm_ra_mas_yr: -8051.0,
                    pm_dec_mas_yr: 676.0,
                    frames: [],
                    gaia_sources: [],
                    spectrum_102: { label: "WISE 0855", wavelength_um: Array(102).fill(2.0), flux_uJy: Array(102).fill(1.0) },
                  },
                },
              } : null;

              const ctx = {
                window, document,
                globalThis: { __PHANTOM_STATIC_FALLBACK__: fallbackBundle },
                URL, URLSearchParams, AbortController, Uint8ClampedArray,
                navigator: opts.navigator || {},
                console, Math, Number, String, Boolean, Array, Object, Set, JSON,
                async fetch(url) {
                  fetchUrls.push(String(url));
                  if (opts.offline) throw new Error("API offline");
                  if (String(url).includes("/api/analyze/spectrum")) {
                    return { ok: true, status: 200, async json() { return { molecule_readings: { status: "REFUSED", features: {} } }; } };
                  }
                  const tsPayload = opts.badTs ? {
                    center_ra_deg: 76.9565, center_dec_deg: 30.4014, fov_arcmin: 6.5,
                    visits: [
                      { visit_id: "V1", epoch_iso: "2026-01-01T00:00:00Z" },
                      { visit_id: "V2", epoch_iso: "2026-02-01T00:00:00Z" },
                      { visit_id: "V3", epoch_iso: "2026-03-01T00:00:00Z" },
                    ],
                    frames_by_visit: [
                      [[NaN, undefined], [3.0, null]],
                      [[4.0, NaN], [6.0, 7.0]],
                      [[8.0, 9.0]],
                    ],
                    stack: null,
                    difference: [[1.0]],
                    mask_overlay: [[1, 0]],
                  } : {
                    center_ra_deg: 76.9565, center_dec_deg: 30.4014, fov_arcmin: 6.5,
                    visits: [
                      { visit_id: "V1", epoch_iso: "2026-01-01T00:00:00Z" },
                      { visit_id: "V2", epoch_iso: "2026-02-01T00:00:00Z" },
                      { visit_id: "V3", epoch_iso: "2026-03-01T00:00:00Z" },
                    ],
                    frames_by_visit: [
                      [[1.0, 2.0], [3.0, 4.0]],
                      [[2.0, 3.0], [4.0, 5.0]],
                      [[3.0, 4.0], [5.0, 6.0]],
                    ],
                    stack: [[2.0, 3.0], [4.0, 5.0]],
                    difference: [[2.0, 2.0], [2.0, 2.0]],
                    mask_overlay: [[0, 0], [0, 0]],
                  };
                  return {
                    ok: true, status: 200,
                    async json() {
                      return {
                        query: { ra_deg: 76.9565, dec_deg: 30.4014, fov_arcmin: Number(byId["fov-select"].value), epoch_yr: Number(byId["epoch-input"].value), detector: "D6" },
                        source_mode: "hour0_calibrated_pack",
                        matched_target: { target_id: "TGT-04", name: "RW Aurigae", ra_deg_at_epoch: 76.9565, dec_deg_at_epoch: 30.4014 },
                        patch_timeseries: tsPayload,
                        frames: [], gaia_sources: [],
                        spectrum_102: { label: "RW Aurigae", wavelength_um: Array(102).fill(2.5), flux_uJy: Array(102).fill(1.0) },
                        warnings: [],
                      };
                    },
                  };
                },
              };
              vm.runInNewContext(viewerCode, ctx);
              return { byId, modeBtns, intervals, fetchUrls, window, setRect: (r) => { canvasRect = r; } };
            }

            (async () => {
              const code = fs.readFileSync(process.argv[1], "utf8");

              // 1. Hover NaN / zero-rect / missing stack & row guards
              const envHover = runHarness(code, "?coord=RW+Aurigae&mode=stack", { badTs: true });
              await new Promise((r) => setTimeout(r, 20));
              envHover.setRect({ left: 0, top: 0, width: 0, height: 0 });
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 0, clientY: 0 });
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 50, clientY: 50 });
              assert.strictEqual(envHover.byId["pixel-readout"].textContent, "");

              envHover.setRect({ left: 0, top: 0, width: 512, height: 512 });
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 10, clientY: 10 });
              assert(envHover.byId["pixel-readout"].textContent.includes("MASKED (NaN)"), "Missing stack should format MASKED (NaN): " + envHover.byId["pixel-readout"].textContent);
              envHover.modeBtns.find((b) => b.dataset.mode === "play").trigger("click");
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 10, clientY: 10 });
              assert(envHover.byId["pixel-readout"].textContent.includes("MASKED (NaN) | Mask bits: 1"), "NaN pixel failed: " + envHover.byId["pixel-readout"].textContent);
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 400, clientY: 10 });
              assert(envHover.byId["pixel-readout"].textContent.includes("MASKED (NaN) | Mask bits: 0"), "undefined pixel failed: " + envHover.byId["pixel-readout"].textContent);
              envHover.modeBtns.find((b) => b.dataset.mode === "rgb").trigger("click");
              envHover.byId["sky-canvas"].trigger("mousemove", { clientX: 400, clientY: 400 });
              assert(envHover.byId["pixel-readout"].textContent.includes("RGB Flux: NaN/7.00/NaN rel | Mask bits: 0"), "RGB missing/undefined row failed: " + envHover.byId["pixel-readout"].textContent);

              // 2. Sexagesimal, decimal, strict numeric & form-name URL parsers
              const envUrlStrict = runHarness(code, "?coord=%20%20&fov=12abc&epoch=2050xyz");
              await new Promise((r) => setTimeout(r, 20));
              assert.strictEqual(envUrlStrict.byId["coord-input"].value, "WISE 0855");
              assert.strictEqual(envUrlStrict.byId["fov-select"].value, "6.5");
              assert.strictEqual(envUrlStrict.byId["epoch-input"].value, "2026");

              const envFormParams = runHarness(code, "?coord=RW+Aurigae&fov_arcmin=12.0&epoch_yr=2027.5");
              await new Promise((r) => setTimeout(r, 20));
              assert.strictEqual(envFormParams.byId["fov-select"].value, "12.0");
              assert.strictEqual(envFormParams.byId["epoch-input"].value, "2027.5");
              assert(envFormParams.fetchUrls[0].includes("fov_arcmin=12") && envFormParams.fetchUrls[0].includes("epoch_yr=2027.5"), envFormParams.fetchUrls[0]);

              const envOffline = runHarness(code, "?coord=08h%2055m%2010.831s%20-07d%2014m%2042.53s", { offline: true });
              await new Promise((r) => setTimeout(r, 20));
              assert(envOffline.byId["status-banner"].textContent.includes("WISE 0855"), "Spaced hms/dms failed: " + envOffline.byId["status-banner"].textContent);

              for (const goodCoord of ["269.452 , 4.693", "269.452\\t4.693"]) {
                envOffline.byId["coord-input"].value = goodCoord;
                envOffline.byId["sky-query-form"].trigger("submit", { preventDefault() {} });
                await new Promise((r) => setTimeout(r, 15));
                assert(envOffline.byId["status-banner"].textContent.includes("RA 269.45200"), goodCoord + " failed: " + envOffline.byId["status-banner"].textContent);
              }

              for (const badCoord of ["00:99:99 +10:00:00", "12h00m00s +10d99m99s", "24:01:00 +00:00:00", "00:00:00 -90:00:01", "12.5h 00m 00s +10d 00m 00s", "   "]) {
                envOffline.byId["coord-input"].value = badCoord;
                envOffline.byId["sky-query-form"].trigger("submit", { preventDefault() {} });
                await new Promise((r) => setTimeout(r, 15));
                assert(envOffline.byId["status-banner"].classList.contains("error"), "Invalid input silently accepted: " + badCoord);
              }

              // 3. Scrubber/Play from non-play mode, fov/live change listeners, copy URL sync & error handling
              const envUI = runHarness(code, "?coord=RW+Aurigae&mode=stack", {
                navigator: { clipboard: { async writeText() { throw new Error("Permission denied"); } } },
              });
              await new Promise((r) => setTimeout(r, 20));
              assert.strictEqual(envUI.byId["visit-label"].textContent, "Mean Stack");
              assert.strictEqual(envUI.byId["play-toggle"].textContent, "Play");

              envUI.byId["visit-scrubber"].value = "2";
              envUI.byId["visit-scrubber"].trigger("input");
              assert.strictEqual(envUI.byId["visit-label"].textContent, "V3 (2026-03-01)", "Scrubber from stack mode stayed stuck: " + envUI.byId["visit-label"].textContent);

              envUI.modeBtns.find((b) => b.dataset.mode === "stack").trigger("click");
              assert.strictEqual(envUI.byId["visit-label"].textContent, "Mean Stack");
              envUI.byId["play-toggle"].trigger("click");
              assert.strictEqual(envUI.byId["play-toggle"].textContent, "Pause");
              assert.notStrictEqual(envUI.byId["visit-label"].textContent, "Mean Stack", "play-toggle from stack mode stayed frozen on Mean Stack");

              const beforeFovFetch = envUI.fetchUrls.length;
              envUI.byId["fov-select"].value = "12.0";
              envUI.byId["fov-select"].trigger("change");
              await new Promise((r) => setTimeout(r, 15));
              assert(envUI.fetchUrls.slice(beforeFovFetch).some((u) => u.includes("/api/sky/timeseries") && u.includes("fov_arcmin=12")), "fov-select change did not re-query: " + JSON.stringify(envUI.fetchUrls.slice(beforeFovFetch)));

              const beforeLiveFetch = envUI.fetchUrls.length;
              envUI.byId["live-toggle"].checked = true;
              envUI.byId["live-toggle"].trigger("change");
              await new Promise((r) => setTimeout(r, 15));
              assert(envUI.fetchUrls.slice(beforeLiveFetch).some((u) => u.includes("/api/sky/timeseries") && u.includes("live=true")), "live-toggle change did not re-query: " + JSON.stringify(envUI.fetchUrls.slice(beforeLiveFetch)));

              envUI.byId["epoch-input"].value = "2028.5";
              envUI.byId["copy-url-btn"].trigger("click");
              await new Promise((r) => setTimeout(r, 20));
              assert(envUI.window.location.href.includes("epoch=2028.5"), "copy-url-btn did not sync edited epoch: " + envUI.window.location.href);
              assert(envUI.byId["status-banner"].classList.contains("error"), "Clipboard failure did not set warning/error status");
              assert.strictEqual(unhandled.length, 0, "Unhandled promise rejection on clipboard error: " + unhandled.map(String).join("; "));

              const envNoClip = runHarness(code, "?coord=RW+Aurigae");
              await new Promise((r) => setTimeout(r, 20));
              envNoClip.byId["copy-url-btn"].trigger("click");
              await new Promise((r) => setTimeout(r, 15));
              assert(envNoClip.byId["status-banner"].textContent.includes("Clipboard API unavailable"), envNoClip.byId["status-banner"].textContent);
            })().catch((err) => { console.error(err); process.exit(1); });
            """
        ).strip()

        proc = subprocess.run([node_bin, "-e", harness, viewer_js_path], capture_output=True, text=True, timeout=15)
        self.assertEqual(proc.returncode, 0, msg=f"viewer.js hover/parser/UI checks failed:\n{proc.stderr}\n{proc.stdout}")

    def test_analyze_spectrum_accepts_null_bands_and_returns_m2_m3_and_paginated_frames(self):
        _, _, spectra = _load_spectra_table()
        rw_flux = [None, None] + spectra["RW_Aurigae"][2:].tolist()
        rw_err = [None, None] + (spectra["RW_Aurigae"][2:] * 0.03).tolist()
        r_null = self.client.post(
            "/api/analyze/spectrum",
            json={
                "flux_uJy": rw_flux,
                "flux_err_uJy": rw_err,
                "blend_share": 0.12,
                "is_variable": False,
                "parallax_snr": 8.5,
            },
        )
        self.assertEqual(r_null.status_code, 200, msg=r_null.text)
        body = r_null.json()
        self.assertEqual(body["molecule_readings"]["status"], "MEASURED")
        self.assertIn("classification", body)
        cls_out = body["classification"]
        self.assertIn("spectrum_alone", cls_out)
        self.assertIn("all_data", cls_out)
        self.assertIn("novelty", cls_out)
        self.assertEqual(cls_out.get("model_origin"), "real_spherex_dr1_spiff_trained")
        self.assertTrue(cls_out["all_data"]["parallax_gate_applied"])
        self.assertEqual(cls_out["novelty"]["status"], "CONTAMINATION_SCREENED")

        # Complete finite 102-band spectra align across the ~0.007 um S3/CSV boundary without false CONTAMINATION_SCREENED.
        r_full = self.client.post(
            "/api/analyze/spectrum",
            json={
                "flux_uJy": spectra["RW_Aurigae"].tolist(),
                "flux_err_uJy": (spectra["RW_Aurigae"] * 0.03).tolist(),
                "blend_share": 0.12,
                "is_variable": False,
            },
        )
        self.assertEqual(r_full.status_code, 200)
        full_cls = r_full.json()["classification"]
        self.assertEqual(full_cls.get("model_origin"), "real_spherex_dr1_spiff_trained")
        self.assertIn(full_cls["novelty"]["status"], ("OK", "NOVEL"))

        # Explicit dataset_npz_path=None preserves explicit Hour-0 bootstrap fallback for custom/offline test harnesses.
        import phantom_worlds.api as api_mod

        fallback_client = TestClient(api_mod.create_app(dataset_npz_path=None))
        r_fb = fallback_client.post(
            "/api/analyze/spectrum",
            json={"flux_uJy": spectra["Barnards_Star"].tolist(), "blend_share": 0.02, "is_variable": False},
        )
        self.assertEqual(r_fb.status_code, 200)
        self.assertEqual(r_fb.json()["classification"].get("model_origin"), "hour0_reference_template_bootstrap")

        # Fewer than 3 finite bands must be rejected with HTTP 422
        r_sparse = self.client.post(
            "/api/analyze/spectrum",
            json={"flux_uJy": [10.0, 12.0] + [None] * 100},
        )
        self.assertEqual(r_sparse.status_code, 422)

        # Optional frame_limit & total_matching_frames on /api/sky/timeseries
        r_paged = self.client.get(
            "/api/sky/timeseries",
            params={"coord": "R Draconis", "frame_limit": 120, "frame_offset": 0},
        )
        self.assertEqual(r_paged.status_code, 200)
        paged = r_paged.json()
        self.assertEqual(len(paged["frames"]), 120)
        self.assertEqual(paged["total_matching_frames"], 2588)

        # WISE 0855 Gaia overlay carries CatWISE W1/W2 magnitudes for matched patch stars
        r_w0855 = self.client.get("/api/sky/timeseries", params={"coord": "WISE 0855", "fov_arcmin": 6.5})
        self.assertEqual(r_w0855.status_code, 200)
        gaia_w0855 = r_w0855.json()["gaia_sources"]
        self.assertTrue(any(s.get("catwise_w1_mag") is not None and s.get("catwise_w2_mag") is not None for s in gaia_w0855))

    def test_ml_pipeline_wavelength_sort_molecule_indices_flux_err_chi2_and_column_density(self):
        from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline, compute_molecule_readings

        wl, bw, spectra = _load_spectra_table()
        rw_res = compute_molecule_readings(wl, bw, spectra["RW_Aurigae"], include_trace_ices=True, rng_seed=0)
        self.assertEqual(rw_res["status"], "MEASURED")
        h2o = rw_res["features"]["H2O_ice_3_05"]
        co2 = rw_res["features"]["CO2_4_26"]
        self.assertGreater(h2o.get("column_density_cm2") or 0.0, 1e16)
        self.assertEqual(h2o.get("rel_to_h2o_ice_pct"), 100.0)
        self.assertGreater(co2.get("column_density_cm2") or 0.0, 1e15)
        self.assertGreater(co2.get("rel_to_h2o_ice_pct") or 0.0, 0.0)
        # Narrow trace ices (< 3 SPHEREx channels) must be included when requested and refused under the 3-band rule
        for trace_key in ("13CO2_4_38", "XCN_4_62", "OCS_4_91"):
            self.assertIn(trace_key, rw_res["features"])
            self.assertEqual(rw_res["features"][trace_key]["status"], "REFUSED")

        # _spectral_colors must sort by wavelength and preserve length == len(wl)
        base_classes = {
            "Star": spectra["Barnards_Star"],
            "Ultracool dwarf": spectra["Eps_Indi_B"],
            "Young star with ice or dust": spectra["RW_Aurigae"],
            "Galaxy": np.full_like(wl, 50.0),
        }
        pipe_asc = SpectralDiscoveryPipeline(wl, bw, template_library=base_classes, random_state=7)
        pipe_desc = SpectralDiscoveryPipeline(
            wl[::-1],
            bw[::-1],
            template_library={k: v[::-1] for k, v in base_classes.items()},
            random_state=7,
        )
        c_asc = pipe_asc._spectral_colors(spectra["RW_Aurigae"])
        c_desc = pipe_desc._spectral_colors(spectra["RW_Aurigae"][::-1])
        self.assertEqual(len(c_asc), len(wl))
        np.testing.assert_allclose(c_asc, c_desc, rtol=1e-12, atol=1e-12)

        # _reduced_chi2 must respect supplied flux_err
        norm_star = pipe_asc._normalize(spectra["Barnards_Star"])
        perturbed = norm_star.copy()
        perturbed[10:18] += 0.8
        chi2_default = pipe_asc._reduced_chi2(perturbed, pipe_asc.template_library["Star"])
        large_err = np.full_like(perturbed, 0.05)
        large_err[10:18] = 5.0
        chi2_weighted = pipe_asc._reduced_chi2(perturbed, pipe_asc.template_library["Star"], norm_err=large_err)
        self.assertLess(chi2_weighted, chi2_default)


if __name__ == "__main__":
    unittest.main()
