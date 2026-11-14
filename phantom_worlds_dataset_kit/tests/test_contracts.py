import csv
import json
import math
import os
import py_compile
import re
import unittest
import numpy as np
from astropy.time import Time

ROOT_DIR = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
CONTRACTS_DIR = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "hour0_contracts")
CSV_DIR = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "csv_tables")
DATA_REAL_DIR = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "scripts", "data_real")
SPEC_PATH = os.path.join(ROOT_DIR, "system_specifications.md")
ML_RESEARCH_PATH = os.path.join(ROOT_DIR, "phantom-worlds-ml-research.md")


class TestPackBinaryContract(unittest.TestCase):
    def setUp(self):
        with open(os.path.join(CONTRACTS_DIR, "manifest.json"), encoding="utf-8") as f:
            self.manifest = json.load(f)
        self.layout = self.manifest["pack_binary_layout"]

    def test_pack_layout_declares_compression_endianness_and_calibration(self):
        for key in ("compression", "endianness", "flux_unit", "flux_scale", "flux_zero", "invalid_u16"):
            self.assertIn(key, self.layout, f"Missing '{key}' in pack_binary_layout")

        self.assertEqual(self.layout["compression"], "none")
        self.assertEqual(self.layout["endianness"], "little")
        self.assertGreater(self.layout["flux_scale"], 0)

        pack_path = os.path.join(CONTRACTS_DIR, self.layout["file"])
        raw = np.fromfile(pack_path, dtype="<u2")
        self.assertEqual(raw.nbytes, self.layout["byte_length"])
        self.assertEqual(raw.size, int(np.prod(self.layout["shape"])))

        # Negative calibrated flux must be representable for PSF-subtraction residuals on valid samples,
        # while invalid_u16 sentinel samples decode cleanly to NaN.
        valid_mask = raw != self.layout["invalid_u16"]
        self.assertTrue(np.any(valid_mask))
        calibrated = raw[valid_mask].astype(np.float64) * self.layout["flux_scale"] + self.layout["flux_zero"]
        self.assertLess(calibrated.min(), 0.0)

    def test_quality_mask_contract_and_binary_file_exist(self):
        self.assertIn("quality_mask_layout", self.manifest)
        mask_layout = self.manifest["quality_mask_layout"]
        self.assertEqual(mask_layout["dtype"], "uint8")
        self.assertEqual(mask_layout["shape"], self.layout["shape"])
        self.assertEqual(mask_layout["compression"], "none")

        flags = mask_layout["flag_bits"]
        self.assertIn("IRSA_REJECTED", flags)
        self.assertIn("OVERFLOW_SATURATED", flags)

        mask_path = os.path.join(CONTRACTS_DIR, mask_layout["file"])
        self.assertTrue(os.path.exists(mask_path), f"Missing {mask_path}")
        mask = np.fromfile(mask_path, dtype=np.uint8)
        self.assertEqual(mask.nbytes, mask_layout["byte_length"])
        self.assertEqual(mask.size, int(np.prod(mask_layout["shape"])))

    def test_system_spec_matches_uncompressed_pack_contract(self):
        with open(SPEC_PATH, encoding="utf-8") as f:
            spec_text = f.read()
        self.assertNotIn("stacked and compressed", spec_text.lower())
        self.assertIn("mask.bin", spec_text)

    def test_all_five_target_manifests_share_identical_schema_and_honest_cutout_origin(self):
        from phantom_worlds.contracts import TARGET_SPECS, load_manifest

        expected_keys = set(self.manifest.keys())
        self.assertIn("cutout_origin", expected_keys)
        self.assertIn("searched_depth_mag_d6", expected_keys)
        self.assertIn("source_exposures", expected_keys)
        self.assertEqual(self.manifest.get("cutout_origin"), "real_spherex_s3_wcs_cutout")

        for tid in TARGET_SPECS:
            m = load_manifest(CONTRACTS_DIR, target_id=tid)
            self.assertEqual(set(m.keys()), expected_keys, f"Schema key mismatch in manifest for {tid}")
            self.assertEqual(
                m.get("cutout_origin"),
                "real_spherex_s3_wcs_cutout",
                f"Dishonest or missing cutout_origin in {tid}",
            )
            self.assertEqual(len(m.get("source_exposures", [])), 18, f"Expected 18 source exposures in {tid}")
            depth = m.get("searched_depth_mag_d6")
            self.assertIsInstance(depth, (int, float), f"Missing searched_depth_mag_d6 in {tid}")
            self.assertTrue(12.0 <= float(depth) <= 22.0, f"Unphysical searched_depth_mag_d6={depth} in {tid}")
            self.assertAlmostEqual(
                m["fov_arcmin"],
                round(m["cutout_size_px"][0] * m["pixel_scale_arcsec"] / 60.0, 4),
                places=4,
            )


class TestMLSpecAndCasesAlignment(unittest.TestCase):
    def setUp(self):
        with open(SPEC_PATH, encoding="utf-8") as f:
            self.spec_text = f.read()
        with open(ML_RESEARCH_PATH, encoding="utf-8") as f:
            self.ml_text = f.read()
        with open(os.path.join(CONTRACTS_DIR, "cases.json"), encoding="utf-8") as f:
            self.cases_doc = json.load(f)
        with open(os.path.join(CSV_DIR, "spherex_102_band_spectra.csv"), encoding="utf-8", newline="") as f:
            self.bands = {row["band_id"]: row for row in csv.DictReader(f)}

    def test_system_spec_aligns_with_ml_research_without_false_scale_claims(self):
        spec_lower = self.spec_text.lower()
        self.assertNotIn("102-band spectra of 1.59 billion gaia", spec_lower)
        self.assertNotIn("false positive $\\le$ 1%", spec_lower)
        self.assertNotIn("false positive <= 1%", spec_lower)
        for required_term in ("E1", "E7", "conformal", "isotonic"):
            self.assertIn(required_term.lower(), spec_lower, f"Missing '{required_term}' from ML research spec")

    def test_ml_research_ultracool_subtype_covers_wise0855_y4(self):
        with open(os.path.join(CSV_DIR, "nasa_5_test_targets.csv"), encoding="utf-8", newline="") as f:
            targets = {row["target_id"]: row for row in csv.DictReader(f)}
        self.assertIn("Y4", targets["TGT-02"]["object_type"])
        self.assertNotIn("subtype L0 to Y1,", self.ml_text)
        self.assertIn("L0 to Y4", self.ml_text)

    def test_cases_json_spectral_bands_and_physics_consistency(self):
        self.assertEqual(self.cases_doc.get("data_origin"), "synthetic_mock_fixture")
        by_id = {c["case_id"]: c for c in self.cases_doc["cases"]}

        # W0855: B086-B102 is D6 thermal/continuum peak with CO 4.67 um dip, not a CH4/CO peak
        w0855 = by_id["CASE-W0855-001"]
        self.assertNotIn("CH4/CO Peak", w0855["deciding_bands"])
        self.assertIn("B086-B102", w0855["deciding_bands"])

        # W1925-002: CH4 3.3 um fundamental dip belongs to D4 bands B062-B063 (B064 is Continuum)
        w1925 = by_id["CASE-W1925-002"]
        ch4_match = re.search(r"(B\d{3})-(B\d{3})", w1925["deciding_bands"])
        self.assertIsNotNone(ch4_match)
        start_num = int(ch4_match.group(1)[1:])
        end_num = int(ch4_match.group(2)[1:])
        start_wl = float(self.bands[ch4_match.group(1)]["wavelength_um"])
        self.assertGreaterEqual(start_wl, 3.15, f"CH4 dip starts too blue at {start_wl} um")
        for bnum in range(start_num, end_num + 1):
            bid = f"B{bnum:03d}"
            self.assertIn("CH4", self.bands[bid]["Molecular_Feature"], f"{bid} is not a CH4 dip band")

        # RWAUR-003: H2O 3.05 um is B059-B060 and CO2 4.26 um is B081-B082
        rwaur3 = by_id["CASE-RWAUR-003"]
        self.assertIn("B059-B060", rwaur3["deciding_bands"])
        self.assertIn("B081-B082", rwaur3["deciding_bands"])

        # RWAUR-004: cannot claim a 0.41 stitch jump while passing M1 & YES physics agreement,
        # nor cite D2/D3 edge jump inside edge_check_d5_d6_delta
        rwaur4 = by_id["CASE-RWAUR-004"]
        self.assertLessEqual(rwaur4["edge_check_d5_d6_delta"], 0.05)
        self.assertNotIn("D2/D3 Edge Jump", rwaur4["deciding_bands"])
        self.assertIn("Young Star", rwaur4["m2_top_class"])
        self.assertIn("Refused", rwaur4["deciding_bands"])

        # W1925-005: Detector D5 starts at B069 (B068 is D4) and blend > 0.3 triggers refusal
        w1925_5 = by_id["CASE-W1925-005"]
        self.assertGreater(w1925_5["blend_share"], 0.3)
        self.assertIn("B069-B085", w1925_5["deciding_bands"])
        self.assertIn("Unclassified", w1925_5["m2_top_class"])

    def test_ml_cases_csv_matches_cases_json_exactly(self):
        with open(os.path.join(CSV_DIR, "ml_cases_output.csv"), encoding="utf-8", newline="") as f:
            csv_rows = list(csv.DictReader(f))
        json_cases = self.cases_doc["cases"]
        self.assertEqual(len(csv_rows), len(json_cases))
        for csv_row, json_row in zip(csv_rows, json_cases):
            self.assertEqual(set(csv_row.keys()), set(json_row.keys()))
            for k, v in json_row.items():
                if v is None:
                    self.assertEqual(csv_row[k], "", msg=f"{json_row['case_id']}.{k}")
                elif isinstance(v, float):
                    self.assertAlmostEqual(float(csv_row[k]), v, places=6, msg=f"{json_row['case_id']}.{k}")
                else:
                    self.assertEqual(csv_row[k], str(v), msg=f"{json_row['case_id']}.{k}")


class TestWISE0855EpochAndRealCatalogContracts(unittest.TestCase):
    def test_shared_url_and_s3_validators_are_unified_across_api_and_downloader(self):
        import sys
        import phantom_worlds.api as api_mod
        import phantom_worlds.contracts as contracts_mod

        scripts_dir = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit", "scripts")
        if scripts_dir not in sys.path:
            sys.path.insert(0, scripts_dir)
        import download_real_spherex_gaia as dl_mod

        self.assertIs(api_mod._safe_remote_url, contracts_mod.safe_remote_url)
        self.assertIs(api_mod._safe_s3_url, contracts_mod.safe_s3_cloud_access_url)
        self.assertIs(dl_mod._validate_fits_url, contracts_mod.validate_remote_url)
        self.assertIs(dl_mod.resolve_s3_url_from_cloud_access, contracts_mod.resolve_s3_cloud_access_url)
        self.assertIs(dl_mod._is_safe_s3_key, contracts_mod.is_safe_s3_key)
        self.assertIs(dl_mod.propagate_position, contracts_mod.propagate_position)

    @staticmethod
    def _propagate(ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, dt_yr):
        from phantom_worlds.contracts import propagate_position

        return propagate_position(ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, dt_yr)

    def test_wise0855_coordinates_propagated_from_j2000_across_contracts(self):
        with open(os.path.join(CSV_DIR, "nasa_5_test_targets.csv"), encoding="utf-8", newline="") as f:
            targets = {row["target_id"]: row for row in csv.DictReader(f)}
        tgt = targets["TGT-02"]
        ra_j2000 = float(tgt["ra_deg_j2000"])
        dec_j2000 = float(tgt["dec_deg_j2000"])
        pmra = float(tgt["pm_ra_mas_yr"])
        pmdec = float(tgt["pm_dec_mas_yr"])

        exp_ra26, exp_dec26 = self._propagate(ra_j2000, dec_j2000, pmra, pmdec, 26.0)

        with open(os.path.join(CONTRACTS_DIR, "sources.json"), encoding="utf-8") as f:
            sources = json.load(f)
        w0855 = sources["target_spectra"]["WISE_0855"]
        tol_deg = 0.5 / 3600.0
        self.assertAlmostEqual(w0855["ra_ep2026_deg"], exp_ra26, delta=tol_deg)
        self.assertAlmostEqual(w0855["dec_ep2026_deg"], exp_dec26, delta=tol_deg)

        with open(os.path.join(CONTRACTS_DIR, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
        self.assertAlmostEqual(manifest["target_j2000_ra_deg"], ra_j2000, delta=1e-6)
        self.assertAlmostEqual(manifest["target_j2000_dec_deg"], dec_j2000, delta=1e-6)
        cosd = math.cos(math.radians(exp_dec26))
        sep_arcmin = math.hypot((exp_ra26 - manifest["center_ra_deg"]) * cosd, exp_dec26 - manifest["center_dec_deg"]) * 60.0
        self.assertLess(sep_arcmin, manifest["fov_arcmin"] / 2.0)

        with open(os.path.join(CONTRACTS_DIR, "cases.json"), encoding="utf-8") as f:
            cases_doc = json.load(f)
        case = next(c for c in cases_doc["cases"] if c["case_id"] == "CASE-W0855-001")
        self.assertAlmostEqual(case["ra_deg"], exp_ra26, delta=tol_deg)
        self.assertAlmostEqual(case["dec_deg"], exp_dec26, delta=tol_deg)

        dt_pred = (Time(case["prediction_epoch"], scale="utc") - Time("J2026.0")).to_value("yr")
        exp_pred_ra, exp_pred_dec = self._propagate(exp_ra26, exp_dec26, pmra, pmdec, dt_pred)
        self.assertAlmostEqual(case["predicted_ra_next_visit"], exp_pred_ra, delta=tol_deg)
        self.assertAlmostEqual(case["predicted_dec_next_visit"], exp_pred_dec, delta=tol_deg)

    def test_wise0855_gaia_patch_and_sources_use_real_gaia_dr3_ids_and_epochs(self):
        real_gaia_path = os.path.join(DATA_REAL_DIR, "WISE_0855_gaia_dr3.csv")
        self.assertTrue(os.path.exists(real_gaia_path), f"Missing {real_gaia_path}")
        with open(real_gaia_path, encoding="utf-8", newline="") as f:
            real_gaia = {str(r["source_id"]): r for r in csv.DictReader(f)}

        with open(os.path.join(CSV_DIR, "gaia_dr3_wise0855_patch.csv"), encoding="utf-8", newline="") as f:
            patch_rows = list(csv.DictReader(f))
        self.assertEqual(len(patch_rows), 25)

        for row in patch_rows:
            sid = str(row["gaia_source_id"])
            self.assertFalse(sid.startswith("3048291049281"), f"Fake Gaia ID found: {sid}")
            self.assertIn(sid, real_gaia, f"Gaia source {sid} missing from real Gaia DR3 patch")
            raw = real_gaia[sid]
            self.assertAlmostEqual(float(row["ra_ep2016_deg"]), float(raw["ra"]), places=5)
            self.assertAlmostEqual(float(row["dec_ep2016_deg"]), float(raw["dec"]), places=5)
            exp_ra26, exp_dec26 = self._propagate(
                float(row["ra_ep2016_deg"]),
                float(row["dec_ep2016_deg"]),
                float(row["pmra_mas_yr"]),
                float(row["pmdec_mas_yr"]),
                10.0,
            )
            self.assertAlmostEqual(float(row["ra_ep2026_deg"]), exp_ra26, delta=1e-5)
            self.assertAlmostEqual(float(row["dec_ep2026_deg"]), exp_dec26, delta=1e-5)

        with open(os.path.join(CONTRACTS_DIR, "sources.json"), encoding="utf-8") as f:
            sources = json.load(f)
        catalog = sources["known_catalog_sources"]
        self.assertEqual(len(catalog), 25)
        for src, csv_row in zip(catalog, patch_rows):
            self.assertEqual(str(src["gaia_source_id"]), str(csv_row["gaia_source_id"]))
            self.assertAlmostEqual(src["ra_ep2026_deg"], float(csv_row["ra_ep2026_deg"]), places=6)
            self.assertAlmostEqual(src["dec_ep2026_deg"], float(csv_row["dec_ep2026_deg"]), places=6)

    def test_sources_json_covers_all_five_targets_and_separates_sky_fields(self):
        with open(os.path.join(CSV_DIR, "nasa_5_test_targets.csv"), encoding="utf-8", newline="") as f:
            targets = {row["target_id"]: row for row in csv.DictReader(f)}
        with open(os.path.join(CSV_DIR, "spherex_102_band_spectra.csv"), encoding="utf-8", newline="") as f:
            spectra_rows = list(csv.DictReader(f))
        with open(os.path.join(CONTRACTS_DIR, "sources.json"), encoding="utf-8") as f:
            sources = json.load(f)

        expected_targets = (
            ("Barnards_Star", "TGT-01", "Barnards_Star_uJy"),
            ("WISE_0855", "TGT-02", "WISE_0855_uJy"),
            ("Epsilon_Indi_B", "TGT-03", "Eps_Indi_B_uJy"),
            ("RW_Aurigae", "TGT-04", "RW_Aurigae_uJy"),
            ("R_Draconis", "TGT-05", "R_Draconis_uJy"),
        )
        self.assertNotEqual(sources.get("field"), "WISE 0855")
        self.assertEqual(sources.get("field"), "multi_target_hour0")
        self.assertEqual(sources.get("primary_cutout_field"), "WISE 0855")
        self.assertEqual(sources.get("catalog_patch_field"), "WISE 0855")

        target_spectra = sources["target_spectra"]
        self.assertEqual(set(target_spectra.keys()), {k for k, _, _ in expected_targets})
        for spec_key, tgt_id, csv_col in expected_targets:
            tgt = targets[tgt_id]
            entry = target_spectra[spec_key]
            self.assertEqual(entry.get("target_id"), tgt_id)
            self.assertEqual(entry.get("field"), tgt["name"])
            exp_ra26, exp_dec26 = self._propagate(
                float(tgt["ra_deg_j2000"]),
                float(tgt["dec_deg_j2000"]),
                float(tgt["pm_ra_mas_yr"]),
                float(tgt["pm_dec_mas_yr"]),
                26.0,
            )
            self.assertAlmostEqual(entry["ra_ep2026_deg"], exp_ra26, delta=1e-5)
            self.assertAlmostEqual(entry["dec_ep2026_deg"], exp_dec26, delta=1e-5)
            self.assertEqual(entry["flux_uJy_102"], [float(r[csv_col]) for r in spectra_rows])

        for cat_entry in sources["known_catalog_sources"]:
            self.assertEqual(cat_entry.get("field"), "WISE 0855")


class TestArchitectureDocsAlignment(unittest.TestCase):
    def test_adr001_and_tech_arch_reflect_real_spherex_access_and_mef_layout(self):
        with open(os.path.join(ROOT_DIR, "architecture_decision_records.md"), encoding="utf-8") as f:
            adr_text = f.read()
        with open(os.path.join(ROOT_DIR, "technical_architecture.md"), encoding="utf-8") as f:
            tech_text = f.read()

        for text in (adr_text, tech_text):
            self.assertNotIn("71.6 MB", text)
            self.assertIn("cloud_access", text)
            self.assertIn("nasa-irsa-spherex", text)
            self.assertIn("Planned", text)

        self.assertIn("MEF", tech_text)
        self.assertNotIn("~0.25 seconds", tech_text)

    def test_docs_and_cases_align_with_actual_ml_export_and_sklearn_stack(self):
        from phantom_worlds.contracts import build_export_packet

        with open(os.path.join(ROOT_DIR, "requirements.txt"), encoding="utf-8") as f:
            req_text = f.read().lower()
        self.assertNotIn("xgboost", req_text)

        for fname in (
            "system_specifications.md",
            "architecture_decision_records.md",
            "technical_architecture.md",
            "phantom-worlds-ml-research.md",
        ):
            with open(os.path.join(ROOT_DIR, fname), encoding="utf-8") as f:
                doc_text = f.read()
            self.assertIn(
                "HistGradientBoostingClassifier",
                doc_text,
                f"{fname} must name the actually implemented HistGradientBoostingClassifier",
            )

        with open(SPEC_PATH, encoding="utf-8") as f:
            spec_text = f.read()
        self.assertIn("Planned", spec_text)
        self.assertIn("2D Canvas", spec_text)
        self.assertIn("phantom_worlds_json_packet_v1", spec_text)

        with open(os.path.join(ROOT_DIR, "phantom-worlds-product-v2.md"), encoding="utf-8") as f:
            prod_text = f.read()
        self.assertIn("Implemented in Hour-0 / Tier A Build", prod_text)

        with open(os.path.join(CONTRACTS_DIR, "cases.json"), encoding="utf-8") as f:
            cases_doc = json.load(f)
        by_id = {c["case_id"]: c for c in cases_doc["cases"]}
        for screened_id in ("CASE-RWAUR-004", "CASE-W1925-005"):
            self.assertEqual(by_id[screened_id].get("m3_novelty_status"), "CONTAMINATION_SCREENED")
            self.assertIsNone(by_id[screened_id].get("m3_weirdness_score"))

        pkt = build_export_packet(by_id["CASE-W0855-001"], data_origin=cases_doc["data_origin"])
        self.assertEqual(pkt.get("export_format"), "phantom_worlds_json_packet_v1")
        self.assertEqual(pkt.get("data_origin"), "synthetic_mock_fixture")
        self.assertIn("m3_novelty_status", pkt["ml_summary"])


class TestProductTierVsCasesAlignment(unittest.TestCase):
    def test_cases_json_distinguishes_tierA_vs_tierB_and_obeys_product_truth_rule_4(self):
        with open(os.path.join(ROOT_DIR, "phantom-worlds-product-v2.md"), encoding="utf-8") as f:
            product_text = f.read()
        self.assertIn("Remove known on two fields (W1925 in the Galactic plane, RW Aurigae off the plane)", product_text)
        self.assertIn("Expected new brown dwarfs in one or two square degrees: about zero", product_text)

        with open(os.path.join(CONTRACTS_DIR, "cases.json"), encoding="utf-8") as f:
            cases_doc = json.load(f)

        self.assertNotEqual(cases_doc.get("pipeline_version"), "v2.0-tierB")
        tier_scope = cases_doc.get("tier_scope", {})
        self.assertIn("tier_a", tier_scope)
        self.assertIn("tier_b", tier_scope)
        self.assertEqual(tier_scope.get("edge_check_status"), "B, conditional")
        self.assertEqual(tier_scope.get("expected_new_brown_dwarfs_per_1_2_sq_deg"), "about zero")

        by_id = {c["case_id"]: c for c in cases_doc["cases"]}
        w0855 = by_id["CASE-W0855-001"]
        self.assertTrue(w0855.get("product_tier", "").startswith("Tier A"))
        self.assertIn("Known Benchmark", w0855["anomaly_class"])
        self.assertNotEqual(w0855["anomaly_class"], "U1 Uncatalogued / Fast Mover")

        w1925_bd = by_id["CASE-W1925-002"]
        self.assertTrue(w1925_bd.get("product_tier", "").startswith("Tier B"))
        self.assertIn("Known", w1925_bd["anomaly_class"])

        for cid in ("CASE-RWAUR-003", "CASE-RWAUR-004", "CASE-W1925-005"):
            self.assertTrue(by_id[cid].get("product_tier", "").startswith("Tier B"), cid)


class TestDocumentationAndResearchHygiene(unittest.TestCase):
    def test_readme_and_rules_file_exist_with_accurate_commands(self):
        readme_path = os.path.join(ROOT_DIR, "README.md")
        agents_path = os.path.join(ROOT_DIR, "AGENTS.md")
        self.assertTrue(os.path.exists(readme_path), "Missing README.md at repository root")
        self.assertTrue(os.path.exists(agents_path), "Missing AGENTS.md rules file at repository root")

        with open(readme_path, encoding="utf-8") as f:
            readme = f.read()
        with open(agents_path, encoding="utf-8") as f:
            agents = f.read()

        for marker in ("phantom_worlds", "phantom_worlds_dataset_kit", "requirements.lock", "pytest"):
            self.assertIn(marker, readme)
        for rule in ("pack.bin", "mask.bin", "requirements.lock", "pytest", "blend_share"):
            self.assertIn(rule, agents)

    def test_no_dead_doc_references_across_root_markdown(self):
        dead_docs = ("02-language.md", "03-the-test.md", "05-methods.md", "07-build-plan.md")
        self.assertTrue(
            os.path.exists(os.path.join(ROOT_DIR, "docs", "decisions.md")),
            "Expected docs/decisions.md to exist in repository",
        )
        for fname in os.listdir(ROOT_DIR):
            if not fname.endswith(".md"):
                continue
            with open(os.path.join(ROOT_DIR, fname), encoding="utf-8") as f:
                content = f.read()
            for dead in dead_docs:
                self.assertNotIn(dead, content, f"Dead reference {dead} found in {fname}")
            self.assertNotIn("](decisions.md)", content, f"Unprefixed link ](decisions.md) found in {fname}")

    def test_research_open_checks_triaged_and_no_raw_to_check_left(self):
        with open(os.path.join(ROOT_DIR, "phantom-worlds-ml-research.md"), encoding="utf-8") as f:
            ml_text = f.read()
        with open(os.path.join(ROOT_DIR, "architecture_decision_records.md"), encoding="utf-8") as f:
            adr_text = f.read()

        self.assertNotIn("[TO CHECK", ml_text)
        self.assertIn("ADR 005", adr_text)
        for k_id in ("K18", "K19", "K20", "K21", "K22", "K23", "K24", "K25", "K26", "K27", "K28"):
            self.assertIn(k_id, ml_text)
            self.assertIn(k_id, adr_text)
            self.assertRegex(
                ml_text,
                rf"{k_id}\b.*\b(VERIFIED|PARTIAL|OPEN)\b",
                f"{k_id} missing structured status in phantom-worlds-ml-research.md",
            )

    def test_sync_hour0_contracts_eliminates_manual_json_csv_drift(self):
        import shutil
        import tempfile
        from phantom_worlds.contracts import build_sources_from_csv, sync_hour0_contracts

        rebuilt = build_sources_from_csv(CSV_DIR)
        with open(os.path.join(CONTRACTS_DIR, "sources.json"), encoding="utf-8") as f:
            checked_in_sources = json.load(f)
        self.assertEqual(rebuilt, checked_in_sources)

        with tempfile.TemporaryDirectory() as tmpdir:
            tmp_contracts = os.path.join(tmpdir, "hour0_contracts")
            tmp_csv = os.path.join(tmpdir, "csv_tables")
            shutil.copytree(CONTRACTS_DIR, tmp_contracts)
            shutil.copytree(CSV_DIR, tmp_csv)

            # Simulate drifted CSV and stale sources.json before running single-source sync
            with open(os.path.join(tmp_csv, "ml_cases_output.csv"), "w", encoding="utf-8") as f:
                f.write("case_id\nSTALE\n")
            with open(os.path.join(tmp_contracts, "sources.json"), "w", encoding="utf-8") as f:
                f.write("{}")

            sync_hour0_contracts(tmp_contracts, tmp_csv)

            with open(os.path.join(tmp_contracts, "cases.json"), encoding="utf-8") as f:
                expected_cases = json.load(f)["cases"]
            with open(os.path.join(tmp_csv, "ml_cases_output.csv"), encoding="utf-8", newline="") as f:
                synced_rows = list(csv.DictReader(f))
            self.assertEqual(len(synced_rows), len(expected_cases))
            self.assertEqual(list(synced_rows[0].keys()), list(expected_cases[0].keys()))
            self.assertEqual(synced_rows[0]["product_tier"], expected_cases[0]["product_tier"])

            with open(os.path.join(tmp_contracts, "sources.json"), encoding="utf-8") as f:
                synced_sources = json.load(f)
            self.assertEqual(synced_sources["known_catalog_sources"], checked_in_sources["known_catalog_sources"])
            self.assertEqual(synced_sources["wavelength_grid_um"], checked_in_sources["wavelength_grid_um"])

    def test_no_ide_leftovers_or_stale_archives_and_all_py_compile(self):
        import tempfile

        stale_zip = os.path.join(ROOT_DIR, "phantom_worlds_dataset_kit.zip")
        self.assertFalse(os.path.exists(stale_zip), f"Stale archive remains: {stale_zip}")

        ide_leftovers = []
        py_files = []
        for walk_root, dirnames, filenames in os.walk(ROOT_DIR):
            dirnames[:] = [d for d in dirnames if d not in {".git", ".pytest_cache", "__pycache__", "data_real"}]
            for fname in filenames:
                fpath = os.path.join(walk_root, fname)
                if "tempCodeRunner" in fname:
                    ide_leftovers.append(fpath)
                if fname.endswith(".py"):
                    py_files.append(fpath)

        self.assertEqual(ide_leftovers, [], f"Leftover IDE temp files found: {ide_leftovers}")
        self.assertGreater(len(py_files), 0)
        with tempfile.TemporaryDirectory() as tmp_dir:
            for idx, py_path in enumerate(py_files):
                cfile = os.path.join(tmp_dir, f"mod_{idx}.pyc")
                py_compile.compile(py_path, cfile=cfile, doraise=True)

    def test_gitignore_protects_caches_temp_artifacts_secrets_and_raw_fits(self):
        gitignore_path = os.path.join(ROOT_DIR, ".gitignore")
        self.assertTrue(os.path.exists(gitignore_path), "Missing .gitignore at repository root")

        with open(gitignore_path, encoding="utf-8") as f:
            lines = {
                line.strip()
                for line in f
                if line.strip() and not line.strip().startswith("#")
            }

        for required_pattern in (
            "__pycache__/",
            "*.py[cod]",
            ".pytest_cache/",
            ".venv/",
            "tempCodeRunnerFile*",
            ".playwright-mcp/",
            ".env",
            "*.pem",
            "*.key",
            "*.p12",
            ".netrc",
            "*.fits",
            "*.zip",
        ):
            self.assertIn(required_pattern, lines, f"Missing '{required_pattern}' in .gitignore")

        # Required datasets/contracts must never be blanket-ignored
        for protected_dir in ("phantom_worlds_dataset_kit/hour0_contracts/", "phantom_worlds_dataset_kit/scripts/data_real/"):
            self.assertNotIn(protected_dir, lines)
            self.assertNotIn("*.csv", lines)


if __name__ == "__main__":
    unittest.main()
