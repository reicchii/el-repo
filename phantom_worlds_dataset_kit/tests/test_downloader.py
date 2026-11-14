import io
import os
import sys
import tempfile
import unittest
from unittest.mock import patch

import pandas as pd
from astropy.table import Table

SCRIPTS_DIR = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "scripts")
)
if SCRIPTS_DIR not in sys.path:
    sys.path.insert(0, SCRIPTS_DIR)

import download_real_spherex_gaia as dl  # noqa: E402


class _FakeSearchResult:
    def __init__(self, rows):
        self._table = Table(rows) if rows else Table(names=["obs_collection", "obs_id", "access_url"])

    def to_table(self):
        return self._table


class TestDownloaderCoverageAndValidation(unittest.TestCase):
    def setUp(self):
        if hasattr(dl, "reset_gaia_mirror_state"):
            dl.reset_gaia_mirror_state()

    def tearDown(self):
        if hasattr(dl, "reset_gaia_mirror_state"):
            dl.reset_gaia_mirror_state()

    def test_spherex_collections_include_dr1_qr3_deep_and_cube(self):
        self.assertTrue(hasattr(dl, "SPHEREX_COLLECTIONS"))
        for required in ("spherex_dr1", "spherex_qr3", "spherex_dr1_deep", "spherex_qr3_deep", "spherex_dr1_cube"):
            self.assertIn(required, dl.SPHEREX_COLLECTIONS)

    def test_build_gaia_adql_defaults_to_unbounded_not_top_500(self):
        adql = dl._build_gaia_adql("gaia_dr3_source", 269.452075, 4.693364, 5.0 / 60.0)
        self.assertNotIn("TOP 500", adql.upper())

    def test_query_irsa_spherex_sia_merges_all_collections(self):
        calls = []

        class FakeSIA2:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                calls.append(collection)
                if collection in ("spherex_dr1", "spherex_qr3", "spherex_dr1_cube"):
                    return _FakeSearchResult([
                        {
                            "obs_collection": collection,
                            "obs_id": f"obs_{collection}",
                            "access_url": f"https://irsa.ipac.caltech.edu/{collection}.fits",
                        }
                    ])
                return _FakeSearchResult([])

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "SIA2Service", FakeSIA2):
            df = dl.query_irsa_spherex_sia("TestTarget", 133.79, -7.24, out_dir=tmpdir)
            self.assertEqual(set(calls), set(dl.SPHEREX_COLLECTIONS))
            self.assertEqual(set(df["obs_collection"]), {"spherex_dr1", "spherex_qr3", "spherex_dr1_cube"})
            out_csv = os.path.join(tmpdir, "TestTarget_spherex_frames.csv")
            self.assertTrue(os.path.exists(out_csv))
            saved = pd.read_csv(out_csv)
            self.assertEqual(len(saved), 3)

    def test_fetch_gaia_dr3_patch_falls_back_on_429_and_validates_coords(self):
        attempts = []

        class FakeTAP:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                attempts.append(self.url)
                if "esa.int" in self.url:
                    raise RuntimeError("Rate limit exceeded (HTTP 429)")
                return _FakeSearchResult([
                    {
                        "source_id": 123,
                        "ra": 269.45,
                        "dec": 4.69,
                        "pmra": -801.5,
                        "pmdec": 10362.4,
                        "parallax": 546.9,
                        "phot_g_mean_mag": 8.19,
                        "phot_bp_mean_mag": 9.79,
                        "phot_rp_mean_mag": 6.95,
                        "ruwe": 1.08,
                    }
                ])

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "TAPService", FakeTAP):
            with self.assertRaises(ValueError):
                dl.fetch_gaia_dr3_patch("BadRA", 400.0, 0.0, out_dir=tmpdir)
            with self.assertRaises(ValueError):
                dl.fetch_gaia_dr3_patch("BadDec", 10.0, -95.0, out_dir=tmpdir)
            with self.assertRaises(ValueError):
                dl.fetch_gaia_dr3_patch("BadRadius", 10.0, 0.0, radius_arcmin=0.0, out_dir=tmpdir)
            self.assertEqual(attempts, [])

            df = dl.fetch_gaia_dr3_patch("Barnards_Star", 269.452075, 4.693364, out_dir=tmpdir)
            self.assertEqual(len(df), 1)
            self.assertEqual(len(attempts), 2)
            self.assertIn("irsa.ipac.caltech.edu", attempts[1])

    def test_tap_fallback_and_siav2_produce_identical_schema_and_filter_collections(self):
        self.assertTrue(hasattr(dl, "SPHEREX_CANONICAL_COLUMNS"))
        self.assertIn("cloud_access", dl.SPHEREX_CANONICAL_COLUMNS)

        class FakeSIA2Success:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                if collection == "spherex_dr1":
                    return _FakeSearchResult([
                        {
                            "obs_collection": "spherex_dr1",
                            "obs_id": "2025W19_1B_0116_1",
                            "s_ra": 133.79,
                            "s_dec": -7.24,
                            "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/a.fits",
                            "cloud_access": '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "dr1/level2/a.fits", "region": "us-east-1"}}',
                            "extra_sia_col": "ignore_me",
                        }
                    ])
                return _FakeSearchResult([])

        class FakeSIA2Empty:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                return _FakeSearchResult([])

        tap_queries = []

        class FakeTAPFallback:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                tap_queries.append(query)
                return _FakeSearchResult([
                    {
                        "obs_collection": "spherex_dr1",
                        "obs_id": "2025W19_1B_0116_1",
                        "s_ra": 133.79,
                        "s_dec": -7.24,
                        "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/a.fits",
                        "pt": "POINT",
                        "poly": "POLY",
                    },
                    {
                        "obs_collection": "spherex_dr1",
                        "obs_id": "2025W19_1B_0116_2",
                        "s_ra": 133.80,
                        "s_dec": -7.25,
                        "access_url": "https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=ivo://irsa.ipac/spherex_dr1?2",
                        "pt": "POINT",
                        "poly": "POLY",
                    },
                    {
                        "obs_collection": "spherex_other_excluded",
                        "obs_id": "ignored",
                        "s_ra": 133.80,
                        "s_dec": -7.25,
                        "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/other.fits",
                        "pt": "POINT",
                        "poly": "POLY",
                    },
                ])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(dl.pyvo.dal, "SIA2Service", FakeSIA2Success):
                df_sia = dl.query_irsa_spherex_sia("WISE_0855", 133.79, -7.24, collections=("spherex_dr1",), out_dir=tmpdir)
            with patch.object(dl.pyvo.dal, "SIA2Service", FakeSIA2Empty), patch.object(dl.pyvo.dal, "TAPService", FakeTAPFallback):
                df_tap = dl.query_irsa_spherex_sia("WISE_0855", 133.79, -7.24, collections=("spherex_dr1",), out_dir=tmpdir)

        self.assertEqual(len(tap_queries), 1)
        self.assertIn("obs_collection IN ('spherex_dr1')", tap_queries[0])
        self.assertEqual(list(df_sia.columns), list(dl.SPHEREX_CANONICAL_COLUMNS))
        self.assertEqual(list(df_tap.columns), list(df_sia.columns))
        self.assertEqual(set(df_tap["obs_collection"]), {"spherex_dr1"})
        self.assertEqual(len(df_tap), 2)
        s3_url = dl.resolve_s3_url_from_cloud_access(df_tap.iloc[0]["cloud_access"])
        self.assertEqual(s3_url, "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/a.fits")
        self.assertEqual(df_tap.iloc[1]["cloud_access"], "")

    def test_fetch_gaia_dr3_patch_cools_down_429_mirror_across_sequential_targets(self):
        self.assertTrue(hasattr(dl, "reset_gaia_mirror_state"))
        attempts = []

        class FakeTAP:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                attempts.append(self.url)
                if "esa.int" in self.url:
                    raise RuntimeError("429 Client Error: Too Many Requests")
                return _FakeSearchResult([
                    {
                        "source_id": 123,
                        "ra": 133.7,
                        "dec": -7.2,
                        "pmra": -8118.0,
                        "pmdec": 680.0,
                        "parallax": 438.9,
                        "phot_g_mean_mag": 20.5,
                        "phot_bp_mean_mag": 21.0,
                        "phot_rp_mean_mag": 19.0,
                        "ruwe": 1.1,
                    }
                ])

        dl.reset_gaia_mirror_state()
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "TAPService", FakeTAP):
            dl.fetch_gaia_dr3_patch("Barnards_Star", 269.452075, 4.693364, out_dir=tmpdir)
            dl.fetch_gaia_dr3_patch("WISE_0855", 133.795129, -7.245147, out_dir=tmpdir)
            dl.fetch_gaia_dr3_patch("RW_Aurigae", 76.9565, 30.401417, out_dir=tmpdir)

        esa_hits = [u for u in attempts if "esa.int" in u]
        irsa_hits = [u for u in attempts if "irsa.ipac.caltech.edu" in u]
        self.assertEqual(len(esa_hits), 1, f"Expected ESA 429 mirror to be cooled down after 1st hit, got {attempts}")
        self.assertEqual(len(irsa_hits), 3)

        # Verify _TimeoutSession disables urllib3 retry stalls on HTTP 429
        sess = dl._TimeoutSession(timeout=8)
        adapter = sess.get_adapter("https://gea.esac.esa.int/tap-server/tap")
        self.assertEqual(adapter.max_retries.total, 0)

        # If every mirror is cooled down, still try mirrors ordered by soonest expiry
        now = dl.time.monotonic()
        dl._GAIA_MIRROR_COOLDOWN_UNTIL[dl.GAIA_MIRRORS[0][1]] = now + 200.0
        dl._GAIA_MIRROR_COOLDOWN_UNTIL[dl.GAIA_MIRRORS[1][1]] = now + 50.0
        dl._GAIA_MIRROR_COOLDOWN_UNTIL[dl.GAIA_MIRRORS[2][1]] = now + 100.0
        attempts.clear()
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "TAPService", FakeTAP):
            dl.fetch_gaia_dr3_patch("R_Draconis", 248.167625, 66.754972, out_dir=tmpdir)
        self.assertEqual(attempts, [dl.GAIA_MIRRORS[1][1]])

    def test_archive_queries_propagate_proper_motion_to_target_epoch_and_reject_invalid_motion(self):
        import csv
        import re
        from phantom_worlds.contracts import propagate_position

        csv_path = os.path.join(
            os.path.dirname(__file__), "..", "csv_tables", "nasa_5_test_targets.csv"
        )
        with open(csv_path, encoding="utf-8", newline="") as f:
            csv_targets = {row["name"]: row for row in csv.DictReader(f)}

        self.assertIn("WISE_0855", dl.TARGETS)
        self.assertIsInstance(dl.TARGETS["WISE_0855"], dict)
        expected_map = {
            "Barnards_Star": "Barnard's Star",
            "WISE_0855": "WISE 0855 (W0855-0714)",
            "Epsilon_Indi_B": "Epsilon Indi B (Ba + Bb)",
            "RW_Aurigae": "RW Aurigae",
            "R_Draconis": "R Draconis",
        }
        for key, csv_name in expected_map.items():
            row = csv_targets[csv_name]
            spec = dl.TARGETS[key]
            self.assertAlmostEqual(spec["ra_deg"], float(row["ra_deg_j2000"]), places=6)
            self.assertAlmostEqual(spec["dec_deg"], float(row["dec_deg_j2000"]), places=6)
            self.assertAlmostEqual(spec["pmra_mas_yr"], float(row["pm_ra_mas_yr"]), places=2)
            self.assertAlmostEqual(spec["pmdec_mas_yr"], float(row["pm_dec_mas_yr"]), places=2)

        w0855 = dl.TARGETS["WISE_0855"]
        exp_ra26, exp_dec26 = propagate_position(
            w0855["ra_deg"], w0855["dec_deg"], w0855["pmra_mas_yr"], w0855["pmdec_mas_yr"], 26.0
        )

        seen_gaia_queries = []
        seen_sia_positions = []

        class FakeTAPCapture:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                seen_gaia_queries.append(query)
                return _FakeSearchResult([
                    {
                        "source_id": 5756959491950135168,
                        "ra": 133.719,
                        "dec": -7.215,
                        "pmra": -2.3,
                        "pmdec": -7.3,
                        "parallax": 0.74,
                        "phot_g_mean_mag": 13.87,
                        "phot_bp_mean_mag": 14.5,
                        "phot_rp_mean_mag": 13.0,
                        "ruwe": 1.0,
                    }
                ])

        class FakeSIACapture:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                seen_sia_positions.append(pos)
                if collection == "spherex_dr1":
                    return _FakeSearchResult([
                        {
                            "obs_collection": "spherex_dr1",
                            "obs_id": "2025W19_1B_0116_1",
                            "s_ra": pos[0],
                            "s_dec": pos[1],
                            "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/a.fits",
                        }
                    ])
                return _FakeSearchResult([])

        with tempfile.TemporaryDirectory() as tmpdir, \
                patch.object(dl.pyvo.dal, "TAPService", FakeTAPCapture), \
                patch.object(dl.pyvo.dal, "SIA2Service", FakeSIACapture):
            dl.fetch_gaia_dr3_patch(
                "WISE_0855",
                w0855["ra_deg"],
                w0855["dec_deg"],
                pmra_mas_yr=w0855["pmra_mas_yr"],
                pmdec_mas_yr=w0855["pmdec_mas_yr"],
                epoch_yr=2026.0,
                out_dir=tmpdir,
            )
            dl.query_irsa_spherex_sia(
                "WISE_0855",
                w0855["ra_deg"],
                w0855["dec_deg"],
                pmra_mas_yr=w0855["pmra_mas_yr"],
                pmdec_mas_yr=w0855["pmdec_mas_yr"],
                epoch_yr=2026.0,
                out_dir=tmpdir,
            )

            with self.assertRaises(ValueError):
                dl.fetch_gaia_dr3_patch("BadPM", 133.7, -7.2, pmra_mas_yr=float("nan"), out_dir=tmpdir)
            with self.assertRaises(ValueError):
                dl.fetch_gaia_dr3_patch("BadEpoch", 133.7, -7.2, epoch_yr=3000.0, out_dir=tmpdir)

        m = re.search(r"CIRCLE\('ICRS',\s*([-0-9.]+),\s*([-0-9.]+),\s*([-0-9.]+)\)", seen_gaia_queries[0])
        self.assertIsNotNone(m)
        self.assertAlmostEqual(float(m.group(1)), exp_ra26, places=5)
        self.assertAlmostEqual(float(m.group(2)), exp_dec26, places=5)
        self.assertAlmostEqual(seen_sia_positions[0][0], exp_ra26, places=5)
        self.assertAlmostEqual(seen_sia_positions[0][1], exp_dec26, places=5)

    def test_download_all_targets_forwards_proper_motion_and_epoch(self):
        with tempfile.TemporaryDirectory() as tmpdir, \
             patch.object(dl, "fetch_gaia_dr3_patch", return_value=pd.DataFrame()) as mock_gaia, \
             patch.object(dl, "query_irsa_spherex_sia", return_value=pd.DataFrame()) as mock_sia:
            failures = dl.download_all_targets(epoch_yr=2026.0, out_dir=tmpdir)
        self.assertEqual(failures, [])
        self.assertEqual(mock_gaia.call_count, len(dl.TARGETS))
        self.assertEqual(mock_sia.call_count, len(dl.TARGETS))
        by_name = {call.args[0]: call.kwargs for call in mock_gaia.call_args_list}
        sia_by_name = {call.args[0]: call.kwargs for call in mock_sia.call_args_list}
        self.assertEqual(by_name["WISE_0855"]["pmra_mas_yr"], -8118.0)
        self.assertEqual(by_name["WISE_0855"]["epoch_yr"], 2026.0)
        self.assertEqual(by_name["Barnards_Star"]["pmdec_mas_yr"], 10362.39)
        self.assertEqual(sia_by_name["Barnards_Star"]["pmdec_mas_yr"], 10362.39)
        self.assertEqual(sia_by_name["Barnards_Star"]["epoch_yr"], 2026.0)

    def test_data_real_spherex_frames_conform_to_canonical_20_column_schema(self):
        expected_cols = list(dl.SPHEREX_CANONICAL_COLUMNS)
        self.assertEqual(len(expected_cols), 20)
        for name in dl.TARGETS:
            csv_path = os.path.join(dl.DEFAULT_OUT_DIR, f"{name}_spherex_frames.csv")
            self.assertTrue(os.path.exists(csv_path), f"Missing SPHEREx frames CSV: {csv_path}")
            df = pd.read_csv(csv_path)
            self.assertGreater(len(df), 0, f"Empty SPHEREx frames CSV: {csv_path}")
            self.assertEqual(list(df.columns), expected_cols, f"Schema drift in {csv_path}")
            self.assertTrue(set(df["obs_collection"].dropna()).issubset(set(dl.SPHEREX_COLLECTIONS)))
            non_empty_cloud = [str(v) for v in df["cloud_access"].dropna() if str(v).strip()]
            self.assertGreater(len(non_empty_cloud), 0, f"No cloud_access entries in {csv_path}")
            for raw_ca in non_empty_cloud:
                self.assertTrue(dl.resolve_s3_url_from_cloud_access(raw_ca).startswith("https://"))

    def test_fetch_gaia_dr3_patch_handles_esa_truncation_at_limit_3000(self):
        dl._GAIA_MIRROR_COOLDOWN_UNTIL.clear()
        calls = []

        class FakeTAP:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                calls.append((self.url, query, dict(kwargs)))
                n = 2000 if "esa.int" in self.url else 3000
                rows = [
                    {
                        "source_id": 1000 + i,
                        "ra": 133.79,
                        "dec": -7.24,
                        "pmra": 0.0,
                        "pmdec": 0.0,
                        "parallax": 1.0,
                        "phot_g_mean_mag": 12.0 + (i % 5),
                        "phot_bp_mean_mag": 12.5,
                        "phot_rp_mean_mag": 11.5,
                        "ruwe": 1.0,
                    }
                    for i in range(n)
                ]
                return _FakeSearchResult(rows)

        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "TAPService", FakeTAP):
            df = dl.fetch_gaia_dr3_patch("WISE_0855", 133.79, -7.24, limit=3000, out_dir=tmpdir)

        self.assertEqual(len(df), 3000)
        self.assertEqual(len(calls), 2)
        self.assertIn("esa.int", calls[0][0])
        self.assertNotIn("esa.int", calls[1][0])
        self.assertGreaterEqual(calls[1][2].get("maxrec", 0), 3000)

    def test_query_irsa_spherex_sia_preserves_partial_collections_when_one_fails(self):
        class FakePartialSIA:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                if collection == "spherex_dr1_cube":
                    raise RuntimeError("SIA timeout on cube collection")
                return _FakeSearchResult([
                    {
                        "obs_collection": collection,
                        "obs_id": f"{collection}_id1",
                        "s_ra": pos[0],
                        "s_dec": pos[1],
                        "access_url": f"https://irsa.ipac.caltech.edu/ibe/data/spherex/{collection}/a.fits",
                    }
                ])

        class FailingTAP:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                raise RuntimeError("IRSA TAP down")

        tap_queries = []

        class PartialRecoveryTAP:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                tap_queries.append(query)
                return _FakeSearchResult([
                    {
                        "obs_collection": "spherex_dr1_cube",
                        "obs_id": "cube_from_tap",
                        "s_ra": 133.79,
                        "s_dec": -7.24,
                        "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/cube.fits",
                    }
                ])

        cols = ("spherex_dr1", "spherex_qr3", "spherex_dr1_cube")
        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(dl.pyvo.dal, "SIA2Service", FakePartialSIA), patch.object(dl.pyvo.dal, "TAPService", FailingTAP):
                df_surviving = dl.query_irsa_spherex_sia("WISE_0855", 133.79, -7.24, collections=cols, out_dir=tmpdir)
            self.assertEqual(set(df_surviving["obs_collection"]), {"spherex_dr1", "spherex_qr3"})

            with patch.object(dl.pyvo.dal, "SIA2Service", FakePartialSIA), patch.object(dl.pyvo.dal, "TAPService", PartialRecoveryTAP):
                df_merged = dl.query_irsa_spherex_sia("WISE_0855", 133.79, -7.24, collections=cols, out_dir=tmpdir)
            self.assertEqual(set(df_merged["obs_collection"]), set(cols))
            self.assertEqual(len(tap_queries), 1)
            self.assertIn("spherex_dr1_cube", tap_queries[0])
            self.assertNotIn("spherex_dr1'", tap_queries[0])
            self.assertNotIn("spherex_qr3", tap_queries[0])


class TestDownloaderInputSecurity(unittest.TestCase):
    def test_rejects_path_traversal_target_names_before_io(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "TAPService") as tap_cls:
            for bad_name in ("../escape", "dir/sub", "..\\win", "..", "", "bad name with spaces"):
                with self.assertRaises(ValueError, msg=f"Allowed bad target_name: {bad_name!r}"):
                    dl.fetch_gaia_dr3_patch(bad_name, 133.7, -7.2, out_dir=tmpdir)
                with self.assertRaises(ValueError, msg=f"Allowed bad target_name in SIA: {bad_name!r}"):
                    dl.query_irsa_spherex_sia(bad_name, 133.7, -7.2, out_dir=tmpdir)
            tap_cls.assert_not_called()

    def test_build_gaia_adql_rejects_injection_invalid_coords_and_bad_limits(self):
        for bad_table in ("gaia_source; DROP TABLE", "bad table", "", "123_invalid"):
            with self.assertRaises(ValueError):
                dl._build_gaia_adql(bad_table, 133.7, -7.2, 0.05)

        for bad_limit in (0, -1, True, 999999, "10; --"):
            with self.assertRaises(ValueError):
                dl._build_gaia_adql("gaia_dr3_source", 133.7, -7.2, 0.05, limit=bad_limit)

        with self.assertRaises(ValueError):
            dl._build_gaia_adql("gaia_dr3_source", float("nan"), -7.2, 0.05)
        with self.assertRaises(ValueError):
            dl._build_gaia_adql("gaia_dr3_source", True, -7.2, 0.05)

    def test_query_irsa_spherex_sia_rejects_invalid_collections(self):
        with tempfile.TemporaryDirectory() as tmpdir, patch.object(dl.pyvo.dal, "SIA2Service") as sia_cls, patch.object(dl.pyvo.dal, "TAPService") as tap_cls:
            with self.assertRaises(ValueError):
                dl.query_irsa_spherex_sia("SafeTarget", 133.7, -7.2, collections=[], out_dir=tmpdir)
            with self.assertRaises(ValueError):
                dl.query_irsa_spherex_sia("SafeTarget", 133.7, -7.2, collections=["spherex_dr1;DROP"], out_dir=tmpdir)
            sia_cls.assert_not_called()
            tap_cls.assert_not_called()

    def test_http_range_read_enforces_https_allowlist_and_byte_bounds(self):
        for bad_url in (
            "http://irsa.ipac.caltech.edu/data/SPHEREx/tile.fits",
            "file:///etc/passwd",
            "https://169.254.169.254/latest/meta-data/",
            "https://127.0.0.1/tile.fits",
            "https://evil.example.org/tile.fits",
        ):
            with self.assertRaises(ValueError, msg=f"Accepted unsafe URL: {bad_url}"):
                dl.http_range_read_fits_tile(bad_url, 0, 1023)

        for start, end in ((-1, 10), (100, 50), (0, 100_000_000), (True, 10)):
            with self.assertRaises(ValueError, msg=f"Accepted bad range {(start, end)}"):
                dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", start, end)

        class FakeResp:
            status_code = 206
            headers = {"Content-Length": "10"}

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                return False

            def iter_content(self, chunk_size=65536):
                yield b"FITS_"
                yield b"BYTES"

        with patch.object(dl._TimeoutSession, "get", return_value=FakeResp()) as mock_get:
            out = dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", 0, 9)
            self.assertEqual(out, b"FITS_BYTES")
            mock_get.assert_called_once()
            self.assertFalse(mock_get.call_args.kwargs.get("allow_redirects", True))
            self.assertTrue(mock_get.call_args.kwargs.get("stream", False))

    def test_http_range_read_streams_and_aborts_before_buffering_over_64mib(self):
        one_mib = b"A" * (1024 * 1024)

        class HeaderOversizeResp:
            status_code = 206
            headers = {"Content-Length": str(dl._MAX_RANGE_BYTES + 1)}
            closed = False
            iter_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.close()

            def close(self):
                self.closed = True

            @property
            def content(self):
                raise AssertionError("http_range_read_fits_tile must stream via iter_content, not read .content")

            def iter_content(self, chunk_size=65536):
                self.iter_called = True
                yield one_mib

        hdr_resp = HeaderOversizeResp()
        with patch.object(dl._TimeoutSession, "get", return_value=hdr_resp) as mock_get:
            with self.assertRaises(RuntimeError):
                dl.http_range_read_fits_tile(
                    "https://irsa.ipac.caltech.edu/data/tile.fits", 0, dl._MAX_RANGE_BYTES - 1
                )
            self.assertTrue(mock_get.call_args.kwargs.get("stream", False))
            self.assertFalse(hdr_resp.iter_called)
            self.assertTrue(hdr_resp.closed)

        class ChunkedOversizeResp:
            status_code = 206
            headers = {}
            closed = False
            chunks_yielded = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.close()

            def close(self):
                self.closed = True

            @property
            def content(self):
                raise AssertionError("http_range_read_fits_tile must stream via iter_content, not read .content")

            def iter_content(self, chunk_size=65536):
                for _ in range(80):
                    self.chunks_yielded += 1
                    yield one_mib

        stream_resp = ChunkedOversizeResp()
        with patch.object(dl._TimeoutSession, "get", return_value=stream_resp) as mock_get:
            with self.assertRaises(RuntimeError):
                dl.http_range_read_fits_tile(
                    "https://irsa.ipac.caltech.edu/data/tile.fits", 0, dl._MAX_RANGE_BYTES - 1
                )
            self.assertTrue(mock_get.call_args.kwargs.get("stream", False))
            self.assertEqual(stream_resp.chunks_yielded, 65)
            self.assertTrue(stream_resp.closed)

    def test_timeout_session_rejects_http_and_redirects_and_range_blocks_http_200_bypass(self):
        sess = dl._TimeoutSession(timeout=5)
        self.assertEqual(sess.max_redirects, 0)
        self.assertNotIn("http://", sess.adapters)
        with self.assertRaises(ValueError):
            sess.get("http://irsa.ipac.caltech.edu/SIA")

        sent_urls = []

        def fake_send(request, **kwargs):
            sent_urls.append(request.url)
            resp = dl.requests.Response()
            resp.status_code = 302
            resp.url = request.url
            resp.headers["Location"] = "https://169.254.169.254/latest/meta-data/"
            resp._content = b""
            return resp

        https_adapter = sess.get_adapter("https://irsa.ipac.caltech.edu/SIA")
        with patch.object(https_adapter, "send", side_effect=fake_send):
            with self.assertRaises(dl.requests.TooManyRedirects):
                sess.get("https://irsa.ipac.caltech.edu/SIA")
        self.assertEqual(sent_urls, ["https://irsa.ipac.caltech.edu/SIA"])

        class Http200OffsetResp:
            status_code = 200
            headers = {"Content-Length": "1024"}
            closed = False
            iter_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.closed = True

            def iter_content(self, chunk_size=65536):
                self.iter_called = True
                yield b"X" * 1024

        offset_resp = Http200OffsetResp()
        with patch.object(dl._TimeoutSession, "get", return_value=offset_resp):
            with self.assertRaises(RuntimeError):
                dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", 1024, 2047)
            self.assertFalse(offset_resp.iter_called)
            self.assertTrue(offset_resp.closed)

        class Http200OversizeHdrResp:
            status_code = 200
            headers = {"Content-Length": "5000000"}
            closed = False
            iter_called = False

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.closed = True

            def iter_content(self, chunk_size=65536):
                self.iter_called = True
                yield b"A" * (1024 * 1024)

        hdr200 = Http200OversizeHdrResp()
        with patch.object(dl._TimeoutSession, "get", return_value=hdr200):
            with self.assertRaises(RuntimeError):
                dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", 0, 2879)
            self.assertFalse(hdr200.iter_called)
            self.assertTrue(hdr200.closed)

        class Http200ChunkedResp:
            status_code = 200
            headers = {}
            closed = False
            chunks_yielded = 0

            def __enter__(self):
                return self

            def __exit__(self, exc_type, exc, tb):
                self.closed = True

            def iter_content(self, chunk_size=65536):
                for _ in range(5):
                    self.chunks_yielded += 1
                    yield b"A" * (1024 * 1024)

        chunked200 = Http200ChunkedResp()
        with patch.object(dl._TimeoutSession, "get", return_value=chunked200):
            with self.assertRaises(RuntimeError):
                dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", 0, 2879)
            self.assertEqual(chunked200.chunks_yielded, 1)
            self.assertTrue(chunked200.closed)

    def test_resolve_s3_url_from_real_cloud_access_metadata(self):
        self.assertTrue(hasattr(dl, "resolve_s3_url_from_cloud_access"))
        sample_json = (
            '{"aws": {"bucket_name": "nasa-irsa-spherex", '
            '"key": "dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits", '
            '"region": "us-east-1"}}'
        )
        url = dl.resolve_s3_url_from_cloud_access(sample_json)
        self.assertEqual(
            url,
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/"
            "dr1/level2/2025W19_1B/l2b-v27-2026-197/3/level2_2025W19_1B_0116_1D3_spx_l2b-v27-2026-197.fits",
        )
        dl._validate_fits_url(url)

        for bad in (
            '{"aws": {"bucket_name": "evil-bucket", "key": "x.fits", "region": "us-east-1"}}',
            '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "../secret", "region": "us-east-1"}}',
            '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "x.fits", "region": "eu-west-1"}}',
            '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "x.fits?versionId=1", "region": "us-east-1"}}',
            '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "x.fits#frag", "region": "us-east-1"}}',
            '{"aws": {"bucket_name": "nasa-irsa-spherex", "key": "%2e%2e/secret", "region": "us-east-1"}}',
            "{}",
        ):
            with self.assertRaises(ValueError, msg=f"Accepted unsafe cloud_access: {bad}"):
                dl.resolve_s3_url_from_cloud_access(bad)

        for unsafe_fits_url in (
            "https://attacker-bucket.s3.us-east-1.amazonaws.com/payload.fits",
            "https://evil.s3.amazonaws.com/payload.fits",
            "https://irsa.ipac.caltech.edu:8443/ibe/data/spherex/tile.fits",
            "https://nasa-irsa-spherex.s3.eu-west-1.amazonaws.com/dr1/tile.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/tile.fits?X-Amz-Signature=bad",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/tile.fits\r\nInjected",
        ):
            with self.assertRaises(ValueError, msg=f"Accepted unsafe FITS URL: {unsafe_fits_url}"):
                dl.http_range_read_fits_tile(unsafe_fits_url, 0, 1023)

        self.assertEqual(
            dl._synthesize_cloud_access("https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/tile.fits?bad=1"),
            "",
        )
        self.assertEqual(
            dl._synthesize_cloud_access("https://irsa.ipac.caltech.edu/ibe/data/spherex////dr1/tile.fits"),
            "",
        )
        norm_poison = dl.normalize_spherex_frames_df(
            dl.pd.DataFrame([
                {
                    "obs_collection": "spherex_dr1",
                    "obs_id": "POISON_CA",
                    "access_url": "https://irsa.ipac.caltech.edu/datalink/links/spherex?ID=1",
                    "cloud_access": '{"aws": {"bucket_name": "evil-bucket", "key": "../secret", "region": "us-east-1"}}',
                },
                {
                    "obs_collection": "spherex_dr1",
                    "obs_id": "BAD_FALLBACK_CA",
                    "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/ok.fits",
                    "cloud_access": '{"aws": {"bucket_name": "evil-bucket", "key": "bad.fits", "region": "us-east-1"}}',
                },
            ]),
            collections=("spherex_dr1",),
        )
        self.assertEqual(norm_poison.iloc[0]["cloud_access"], "")
        self.assertEqual(
            dl.resolve_s3_url_from_cloud_access(norm_poison.iloc[1]["cloud_access"]),
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/ok.fits",
        )

        # Fallback builder (_compact_fallback_frames) must reject poisoned cloud_access payloads too.
        from phantom_worlds.contracts import _compact_fallback_frames
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "WISE_0855_spherex_frames.csv")
            with open(csv_path, "w", encoding="utf-8", newline="") as cf:
                cf.write("obs_collection,obs_id,s_ra,s_dec,energy_bandpassname,em_min,em_max,t_min,cloud_access\n")
                cf.write('spherex_dr1,BAD_BKT,133.7,-7.2,D1,0.75,1.1,61000.0,"{""aws"":{""bucket_name"":""evil"",""key"":""dr1/a.fits"",""region"":""us-east-1""}}"\n')
                cf.write('spherex_dr1,BAD_TRAV,133.7,-7.2,D1,0.75,1.1,61000.0,"{""aws"":{""bucket_name"":""nasa-irsa-spherex"",""key"":""../secret"",""region"":""us-east-1""}}"\n')
                cf.write('spherex_dr1,GOOD_CA,133.7,-7.2,D1,0.75,1.1,61000.0,"{""aws"":{""bucket_name"":""nasa-irsa-spherex"",""key"":""dr1/good.fits"",""region"":""us-east-1""}}"\n')
            compact = _compact_fallback_frames(tmpdir, "WISE_0855")
            by_id = {row[1]: row[8] for row in compact}
            self.assertEqual(by_id["BAD_BKT"], "")
            self.assertEqual(by_id["BAD_TRAV"], "")
            self.assertEqual(by_id["GOOD_CA"], "dr1/good.fits")

    def test_s3_allowlist_and_remote_url_security_cross_layer(self):
        import phantom_worlds.api as api_mod

        valid_urls = (
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/valid_1.fits",
            "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/valid_1.fits",
        )
        for ok_url in valid_urls:
            self.assertEqual(dl._validate_fits_url(ok_url), ok_url)
            self.assertEqual(api_mod._safe_remote_url(ok_url), ok_url)

        unsafe_vectors = (
            "http://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits",
            "ftp://irsa.ipac.caltech.edu/ibe/data/a.fits",
            "https://user:pass@nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits",
            "https://irsa.ipac.caltech.edu:443/ibe/data/spherex/a.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com:badport/dr1/a.fits",
            "https://nasa-irsa-spherex.s3-us-west-2.amazonaws.com/dr1/a.fits",
            "https://s3.us-east-1.amazonaws.com/nasa-irsa-spherex/dr1/a.fits",
            "https://nasa-irsa-spherex.s3.amazonaws.com/dr1/a.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1//double.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1\\back.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/../secret.fits",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits#frag",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits?X-Amz-Algorithm=AWS4",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits\x00",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/a.fits ",
            "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com//dr1/a.fits",
            "https://irsa.ipac.caltech.edu/",
            "https://irsa.ipac.caltech.edu/login",
            "https://irsa.ipac.caltech.edu/ibe/data/spherex/../secret.fits",
            "https://irsa.ipac.caltech.edu/ibe/data/spherex/a.fits?redirect=https://evil.example",
            "https://irsa.ipac.caltech.edu/ibe/data/spherex/a.fits#frag",
            "https://irsa.ipac.caltech.edu/%2e%2e/secret.fits",
            "https://irsa.ipac.caltech.edu//ibe/data/spherex/a.fits",
        )
        with patch.object(dl._TimeoutSession, "get") as mock_get:
            for bad_url in unsafe_vectors:
                with self.assertRaises(ValueError, msg=f"downloader accepted unsafe URL: {bad_url!r}"):
                    dl.http_range_read_fits_tile(bad_url, 0, 1023)
                self.assertIsNone(api_mod._safe_remote_url(bad_url), msg=f"api accepted unsafe URL: {bad_url!r}")
            mock_get.assert_not_called()

    def test_http_transport_blocks_trust_env_netrc_proxies_and_secondary_hosts(self):
        import phantom_worlds.api as api_mod

        sessions_to_check = [
            (dl._TimeoutSession(timeout=5), "https://irsa.ipac.caltech.edu/SIA", True),
            (api_mod._LiveIrsaSession(), "https://irsa.ipac.caltech.edu/SIA", False),
        ]
        with tempfile.TemporaryDirectory() as tmpdir:
            netrc_path = os.path.join(tmpdir, ".netrc")
            with open(netrc_path, "w", encoding="utf-8") as f:
                f.write("machine irsa.ipac.caltech.edu login secretuser password secrettok\n")
            with patch.dict(
                os.environ,
                {
                    "HTTP_PROXY": "http://127.0.0.1:8888",
                    "HTTPS_PROXY": "http://127.0.0.1:8888",
                    "ALL_PROXY": "socks5://127.0.0.1:1080",
                    "NETRC": netrc_path,
                },
            ):
                for sess, ok_url, allow_esa in sessions_to_check:
                    with sess:
                        self.assertFalse(sess.trust_env)
                        merged = sess.merge_environment_settings(ok_url, {}, None, None, None)
                        self.assertEqual(merged["proxies"], {})
                        req = dl.requests.Request("GET", ok_url)
                        prep = sess.prepare_request(req)
                        self.assertNotIn("Authorization", prep.headers)

                        for bad_url in (
                            "https://169.254.169.254/latest/meta-data/",
                            "https://evil.example.org/SIA",
                            "https://user:pass@irsa.ipac.caltech.edu/SIA",
                            "https://irsa.ipac.caltech.edu:8443/SIA",
                        ):
                            with self.assertRaises(ValueError, msg=f"Accepted secondary/unsafe host: {bad_url}"):
                                sess.get(bad_url)
                            bad_prep = dl.requests.Request("GET", bad_url).prepare()
                            with self.assertRaises(ValueError, msg=f"send() accepted unsafe host: {bad_url}"):
                                sess.send(bad_prep)

                        if not allow_esa:
                            with self.assertRaises(ValueError):
                                sess.get("https://gea.esac.esa.int/tap-server/tap")

                        # Even if caller tries to mutate max_redirects and pass allow_redirects=True, redirects stay blocked
                        sess.max_redirects = 5
                        sent = []

                        def _redir_send(request, **kwargs):
                            sent.append(request.url)
                            resp = dl.requests.Response()
                            resp.status_code = 302
                            resp.url = request.url
                            resp.headers["Location"] = "https://evil.example.org/steal"
                            resp._content = b""
                            return resp

                        adapter = sess.get_adapter(ok_url)
                        with patch.object(adapter, "send", side_effect=_redir_send):
                            with self.assertRaises(dl.requests.TooManyRedirects):
                                sess.get(ok_url, allow_redirects=True)
                        self.assertEqual(sent, [ok_url])

                # Range reader must use hardened _TimeoutSession (never bare requests.get with trust_env=True).
                captured = {}

                class RangeOkResp:
                    status_code = 206
                    headers = {"Content-Length": "4"}

                    def __enter__(self):
                        return self

                    def __exit__(self, exc_type, exc, tb):
                        pass

                    def iter_content(self, chunk_size=65536):
                        yield b"FITS"

                def _capture_range_send(self_sess, request, **kwargs):
                    captured["trust_env"] = self_sess.trust_env
                    captured["url"] = request.url
                    return RangeOkResp()

                with patch.object(dl.HardenedHTTPSession, "send", autospec=True, side_effect=_capture_range_send):
                    out = dl.http_range_read_fits_tile("https://irsa.ipac.caltech.edu/data/tile.fits", 0, 3)
                    self.assertEqual(out, b"FITS")
                    self.assertFalse(captured["trust_env"])

    def test_http_range_read_runs_through_session_send_with_allow_redirects_false(self):
        # Exercise real Session.send() -> resolve_redirects(..., yield_requests=True) with mocked HTTPAdapter.send.
        from requests.adapters import HTTPAdapter

        seen_kwargs = []

        def _fake_adapter_send(self_adapter, request, **kwargs):
            seen_kwargs.append((request.url, dict(kwargs)))
            resp = dl.requests.Response()
            resp.status_code = 206
            resp.url = request.url
            resp.headers["Content-Length"] = "8"
            resp.raw = io.BytesIO(b"SIMPLE  ")
            resp._content_consumed = False
            resp.request = request
            return resp

        with patch.object(HTTPAdapter, "send", autospec=True, side_effect=_fake_adapter_send):
            out = dl.http_range_read_fits_tile(
                "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/tile.fits",
                0,
                7,
            )
        self.assertEqual(out, b"SIMPLE  ")
        self.assertEqual(len(seen_kwargs), 1)
        self.assertTrue(seen_kwargs[0][1].get("stream"))

        def _redir_adapter_send(self_adapter, request, **kwargs):
            resp = dl.requests.Response()
            resp.status_code = 302
            resp.url = request.url
            resp.headers["Location"] = "https://evil.example.org/steal"
            resp._content = b""
            resp.raw = io.BytesIO(b"")
            resp.request = request
            return resp

        with patch.object(HTTPAdapter, "send", autospec=True, side_effect=_redir_adapter_send):
            with self.assertRaises(dl.requests.TooManyRedirects):
                dl.http_range_read_fits_tile(
                    "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/tile.fits",
                    0,
                    7,
                )

    def test_sia_maxrec_tap_circle_radius_esa_2000_fallback_and_atomic_csv_writes(self):
        sia_kwargs_seen = []
        tap_queries_seen = []

        class FakeSIAEmptyCapture:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, pos, collection=None, **kwargs):
                sia_kwargs_seen.append(dict(kwargs))
                return _FakeSearchResult([])

        class FakeTAPRadiusCapture:
            def __init__(self, url, session=None):
                self.url = url

            def search(self, query, **kwargs):
                tap_queries_seen.append(query)
                return _FakeSearchResult([
                    {
                        "obs_collection": "spherex_dr1",
                        "obs_id": "2025W19_1B_0116_1",
                        "s_ra": 133.79,
                        "s_dec": -7.24,
                        "access_url": "https://irsa.ipac.caltech.edu/ibe/data/spherex/dr1/level2/a.fits",
                    }
                ])

        with tempfile.TemporaryDirectory() as tmpdir:
            with patch.object(dl.pyvo.dal, "SIA2Service", FakeSIAEmptyCapture), patch.object(
                dl.pyvo.dal, "TAPService", FakeTAPRadiusCapture
            ):
                dl.query_irsa_spherex_sia(
                    "WISE_0855",
                    133.79,
                    -7.24,
                    radius_deg=0.08,
                    collections=("spherex_dr1",),
                    out_dir=tmpdir,
                )

            self.assertTrue(sia_kwargs_seen and all("maxrec" in kw and kw["maxrec"] >= 1000 for kw in sia_kwargs_seen))
            self.assertEqual(len(tap_queries_seen), 1)
            self.assertIn("CIRCLE('ICRS'", tap_queries_seen[0])
            self.assertIn("0.08", tap_queries_seen[0])

            # ESA returns 2000 rows while fallback mirrors fail -> must preserve the 2000 ESA rows instead of losing all data
            dl.reset_gaia_mirror_state()

            class FakeESA2000OthersDown:
                def __init__(self, url, session=None):
                    self.url = url

                def search(self, query, **kwargs):
                    if "esa.int" in self.url:
                        return _FakeSearchResult([
                            {
                                "source_id": 2000 + i,
                                "ra": 133.79,
                                "dec": -7.24,
                                "pmra": 0.0,
                                "pmdec": 0.0,
                                "parallax": 1.0,
                                "phot_g_mean_mag": 14.0,
                                "phot_bp_mean_mag": 14.5,
                                "phot_rp_mean_mag": 13.5,
                                "ruwe": 1.0,
                            }
                            for i in range(2000)
                        ])
                    raise RuntimeError("Fallback mirror down")

            with patch.object(dl.pyvo.dal, "TAPService", FakeESA2000OthersDown):
                df_esa = dl.fetch_gaia_dr3_patch("WISE_0855", 133.79, -7.24, limit=3000, out_dir=tmpdir)
            self.assertEqual(len(df_esa), 2000)

            # Atomic write check: existing CSV must not be corrupted if DataFrame.to_csv raises mid-write
            out_csv = os.path.join(tmpdir, "WISE_0855_gaia_dr3.csv")
            with open(out_csv, "w", encoding="utf-8") as f:
                f.write("source_id,ra,dec\nORIGINAL,1.0,2.0\n")

            dl.reset_gaia_mirror_state()
            with patch.object(dl.pyvo.dal, "TAPService", FakeESA2000OthersDown), patch.object(
                pd.DataFrame, "to_csv", side_effect=OSError("Disk full mid-write")
            ):
                with self.assertRaises(RuntimeError):
                    dl.fetch_gaia_dr3_patch("WISE_0855", 133.79, -7.24, limit=100, out_dir=tmpdir)
            with open(out_csv, encoding="utf-8") as f:
                self.assertEqual(f.read(), "source_id,ra,dec\nORIGINAL,1.0,2.0\n")

    def test_load_targets_csv_and_validation_guardrails(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            good_csv = os.path.join(tmpdir, "spiff_sample.csv")
            with open(good_csv, "w", encoding="utf-8-sig") as f:
                f.write(
                    "target_name,RA,Dec,pmra,pmdec,ref_epoch\n"
                    "SPIFF_001,133.795129,-7.245147,-8118.0,680.0,2000.0\n"
                    "SIMBAD_002,269.452075,4.693364,,,2016.0\n"
                    "SPLICES_003,150.125,2.25,NaN,null,\n"
                )
            loaded = dl.load_targets_csv(good_csv)
            self.assertEqual(list(loaded.keys()), ["SPIFF_001", "SIMBAD_002", "SPLICES_003"])
            self.assertAlmostEqual(loaded["SPIFF_001"]["pmra_mas_yr"], -8118.0)
            self.assertEqual(loaded["SPIFF_001"]["ref_epoch_yr"], 2000.0)
            self.assertEqual(loaded["SIMBAD_002"]["pmra_mas_yr"], 0.0)
            self.assertEqual(loaded["SIMBAD_002"]["pmdec_mas_yr"], 0.0)
            self.assertEqual(loaded["SIMBAD_002"]["ref_epoch_yr"], 2016.0)
            self.assertEqual(loaded["SPLICES_003"]["pmra_mas_yr"], 0.0)
            self.assertEqual(loaded["SPLICES_003"]["pmdec_mas_yr"], 0.0)
            self.assertEqual(loaded["SPLICES_003"]["ref_epoch_yr"], 2000.0)

            for bad_csv_name, content in (
                ("bad_traversal.csv", "name,ra,dec\n../evil,10.0,20.0\n"),
                ("bad_spaces.csv", "name,ra,dec\nbad name,10.0,20.0\n"),
                ("bad_dup.csv", "name,ra,dec\nDupStar,10.0,20.0\nDupStar,11.0,21.0\n"),
                ("bad_coords.csv", "name,ra,dec\nBadRA,400.0,20.0\n"),
                ("bad_cols.csv", "name,ra\nMissingDec,10.0\n"),
                ("empty.csv", "name,ra,dec\n"),
            ):
                p = os.path.join(tmpdir, bad_csv_name)
                with open(p, "w", encoding="utf-8") as f:
                    f.write(content)
                with self.assertRaises(ValueError, msg=f"Accepted invalid targets CSV {bad_csv_name}"):
                    dl.load_targets_csv(p)

    def test_download_all_targets_supports_custom_targets_and_resume_skip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            # Target A already has both Gaia & SPHEREx CSVs complete.
            with open(os.path.join(tmpdir, "Done_A_gaia_dr3.csv"), "w", encoding="utf-8") as f:
                f.write("source_id,ra,dec\n1,10.0,20.0\n")
            with open(os.path.join(tmpdir, "Done_A_spherex_frames.csv"), "w", encoding="utf-8") as f:
                f.write(",".join(dl.SPHEREX_CANONICAL_COLUMNS) + "\n")

            # Target B has Gaia complete, SPHEREx empty/0-byte (incomplete) -> resume must skip Gaia, retry SPHEREx.
            with open(os.path.join(tmpdir, "Half_B_gaia_dr3.csv"), "w", encoding="utf-8") as f:
                f.write("source_id,ra,dec\n2,30.0,-10.0\n")
            with open(os.path.join(tmpdir, "Half_B_spherex_frames.csv"), "w", encoding="utf-8") as f:
                f.write("")

            # Target C has neither file -> both Gaia & SPHEREx run.
            custom = {
                "Done_A": {"ra_deg": 10.0, "dec_deg": 20.0, "pmra_mas_yr": 1.0, "pmdec_mas_yr": -2.0, "ref_epoch_yr": 2016.0},
                "Half_B": {"ra_deg": 30.0, "dec_deg": -10.0},
                "New_C": {"ra_deg": 45.0, "dec_deg": 15.0, "ref_epoch_yr": 2015.5},
            }

            with patch.object(dl, "fetch_gaia_dr3_patch", return_value=pd.DataFrame()) as mock_gaia, \
                 patch.object(dl, "query_irsa_spherex_sia", return_value=pd.DataFrame()) as mock_sia, \
                 patch.object(dl.time, "sleep") as mock_sleep:
                failures = dl.download_all_targets(
                    epoch_yr=2026.0,
                    out_dir=tmpdir,
                    targets=custom,
                    resume=True,
                    delay_sec=0.5,
                )

            self.assertEqual(failures, [])
            self.assertEqual([c.args[0] for c in mock_gaia.call_args_list], ["New_C"])
            self.assertEqual([c.args[0] for c in mock_sia.call_args_list], ["Half_B", "New_C"])
            self.assertEqual(mock_gaia.call_args_list[0].kwargs["ref_epoch_yr"], 2015.5)
            # Skipped Done_A must not incur delay sleep; Half_B made a network call before New_C -> 1 sleep.
            mock_sleep.assert_called_once_with(0.5)

            # Direct helper resume=True check (must not hit TAPService / SIA2Service)
            with patch.object(dl.pyvo.dal, "TAPService") as tap_cls, \
                 patch.object(dl.pyvo.dal, "SIA2Service") as sia_cls:
                df_g = dl.fetch_gaia_dr3_patch("Done_A", 10.0, 20.0, out_dir=tmpdir, resume=True)
                df_s = dl.query_irsa_spherex_sia("Done_A", 10.0, 20.0, out_dir=tmpdir, resume=True)
                tap_cls.assert_not_called()
                sia_cls.assert_not_called()
                self.assertEqual(len(df_g), 1)
                self.assertEqual(len(df_s), 0)

    def test_cli_main_supports_targets_csv_single_coord_resume_and_rejects_bad_flags(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            csv_path = os.path.join(tmpdir, "batch.csv")
            with open(csv_path, "w", encoding="utf-8") as f:
                f.write("name,ra_deg,dec_deg,pmra_mas_yr,pmdec_mas_yr\nObj1,10.5,-5.25,12.0,-3.0\n")

            with patch.object(dl, "download_all_targets", return_value=[]) as mock_dl:
                rc = dl.main([
                    "--targets-csv", csv_path,
                    "--out-dir", tmpdir,
                    "--epoch", "2027.0",
                    "--radius-arcmin", "3.0",
                    "--radius-deg", "0.04",
                    "--limit", "250",
                    "--collections", "spherex_dr1", "spherex_qr3",
                    "--resume",
                    "--delay", "0.1",
                ])
                self.assertEqual(rc, 0)
                kwargs = mock_dl.call_args.kwargs
                self.assertEqual(list(kwargs["targets"].keys()), ["Obj1"])
                self.assertEqual(kwargs["epoch_yr"], 2027.0)
                self.assertEqual(kwargs["radius_arcmin"], 3.0)
                self.assertEqual(kwargs["radius_deg"], 0.04)
                self.assertEqual(kwargs["limit"], 250)
                self.assertEqual(kwargs["collections"], ("spherex_dr1", "spherex_qr3"))
                self.assertTrue(kwargs["resume"])
                self.assertEqual(kwargs["delay_sec"], 0.1)

            with patch.object(dl, "download_all_targets", return_value=[]) as mock_dl:
                rc = dl.main(["--ra", "133.795129", "--dec", "-7.245147", "--pmra", "-8118", "--pmdec", "680", "--skip-existing", "--out-dir", tmpdir])
                self.assertEqual(rc, 0)
                targets_arg = mock_dl.call_args.kwargs["targets"]
                self.assertEqual(len(targets_arg), 1)
                auto_name = next(iter(targets_arg))
                dl._validate_target_name(auto_name)
                self.assertTrue(mock_dl.call_args.kwargs["resume"])

            with patch.object(dl, "download_all_targets") as mock_dl:
                for bad_argv in (
                    ["--targets-csv", csv_path, "--ra", "10.0", "--dec", "20.0"],
                    ["--ra", "10.0"],
                    ["--name", "OrphanName"],
                    ["--ra", "10.0", "--dec", "20.0", "--name", "../bad"],
                ):
                    with self.assertRaises(SystemExit, msg=f"Accepted invalid CLI argv: {bad_argv}"):
                        dl.main(bad_argv)
                mock_dl.assert_not_called()

    def test_download_all_targets_workers_and_max_targets_bounds(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            custom = {
                f"Obj_{i}": {"ra_deg": 10.0 + i, "dec_deg": -5.0 + 0.1 * i}
                for i in range(6)
            }

            def fake_gaia(name, *args, **kwargs):
                if name == "Obj_2":
                    raise RuntimeError("Simulated mirror hiccup")
                return pd.DataFrame({"source_id": [1]})

            with patch.object(dl, "fetch_gaia_dr3_patch", side_effect=fake_gaia) as mock_gaia, \
                 patch.object(dl, "query_irsa_spherex_sia", return_value=pd.DataFrame()) as mock_sia:
                failures = dl.download_all_targets(
                    out_dir=tmpdir,
                    targets=custom,
                    workers=3,
                    max_targets=4,
                )

            self.assertEqual(len(failures), 1)
            self.assertEqual(failures[0][0], "Obj_2")
            self.assertEqual(mock_gaia.call_count, 4)
            # Obj_2 failed inside Gaia step, so SPHEREx SIA ran only for the 3 surviving sliced targets.
            self.assertEqual(mock_sia.call_count, 3)

            for bad_workers in (0, -1, 9, True):
                with self.assertRaises(ValueError):
                    dl.download_all_targets(out_dir=tmpdir, targets=custom, workers=bad_workers)
            for bad_max in (0, -2, 50001, False):
                with self.assertRaises(ValueError):
                    dl.download_all_targets(out_dir=tmpdir, targets=custom, max_targets=bad_max)

            with patch.object(dl, "download_all_targets", return_value=[]) as mock_dl:
                rc = dl.main(["--out-dir", tmpdir, "--workers", "4", "--max-targets", "2", "--resume"])
                self.assertEqual(rc, 0)
                self.assertEqual(mock_dl.call_args.kwargs["workers"], 4)
                self.assertEqual(mock_dl.call_args.kwargs["max_targets"], 2)

    def test_safe_output_path_handles_win32_extended_prefix_and_concurrent_makedirs(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            nested = os.path.join(tmpdir, "nested_out")
            # Reproduces Windows Python 3.13 race where realpath(dir) returns D:\... while
            # concurrent realpath(dir/file) returns \\?\D:\... mid-makedirs.
            if os.name == "nt":
                norm_nested = os.path.abspath(nested)
                returns = [norm_nested, "\\\\?\\" + os.path.join(norm_nested, "Obj_gaia_dr3.csv")]
                with patch.object(dl.os.path, "realpath", side_effect=returns):
                    resolved = dl._safe_output_path(nested, "Obj_gaia_dr3.csv")
                self.assertEqual(resolved, os.path.join(norm_nested, "Obj_gaia_dr3.csv"))

            # Still must reject parent traversal even if normalized
            with self.assertRaises(ValueError):
                dl._safe_output_path(nested, "..\\escape.csv" if os.name == "nt" else "../escape.csv")


class TestCuratedMLCatalogBuilder(unittest.TestCase):
    def test_build_curated_catalog_combines_spiff_splices_and_gaia_with_safe_names_and_interleave(self):
        import csv
        import io
        import zipfile
        import build_ml_catalog as bmc

        # Synthetic in-memory SPIFF table zip
        spiff_buf = io.BytesIO()
        with zipfile.ZipFile(spiff_buf, "w") as zf:
            zf.writestr(
                "spiff_tables/spherex_autotype_datasets_fulltable.csv",
                "\n".join([
                    "designation,ra_j2000,dec_j2000,dataset,spiff_autotype,spiff_chi2_r,literature_spectral_type,reference",
                    "CWISE J101438.37-272622.7,10:14:38.37,-27:26:22.8,New Discoveries,T9,1.2,,",
                    "2MASS J03552337+1133437,03:55:23.37,+11:33:43.7,Known,L5,0.9,L5,1",
                    "2MASS J00000001+0000010,00:00:00.10,+00:00:01.0,Known,M2,0.8,M2,1",  # M2 excluded (< M7)
                ]),
            )
        spiff_bytes = spiff_buf.getvalue()

        # Synthetic IRSA Gator IPAC ASCII table for SPLICES (YSO + C AGB + MS Star + near-duplicate coordinate)
        splices_ipac = "\n".join([
            "\\fixlen = T",
            "|          designation|            source_id|         ra|        dec|                pmra|               pmdec|  class_1|  yso_pub|       stype_ml| stype_ml_prob1| varclassgaia|      dist|     angle|",
            "|                 char|                 long|     double|     double|              double|              double|     char|     char|           char|         double|         char|    double|    double|",
            "|                     |                     |        deg|        deg|          mas.yr**-1|          mas.yr**-1|         |         |               |               |             |          |          |",
            "|                 null|                 null|       null|       null|                null|                null|     null|     null|           null|           null|         null|      null|      null|",
            "   J053513.22-052455.4   1892459399566327809   83.805000   -5.415400     1.79e+00    -6.22e-01     YSO_D        4      Class II YSO          0.95           YSO    100.0    200.0",
            "   J192000.00+000000.0   4260000000000000001  290.000000    0.000000     1.10e+00    -2.20e+00      null     null             C AGB          0.92           LPV    120.0    100.0",
            "   J192000.01+000000.1   4260000000000000002  290.000100    0.000100     1.10e+00    -2.20e+00      null     null             C AGB          0.91           LPV    120.1    100.1",
            "   J053510.00-052000.0   1892459399566327999   83.791600   -5.333300     0.50e+00     0.10e+00      null     null           MS Star          0.96          null    130.0     50.0",
        ])

        class FakeResp:
            def __init__(self, status_code=200, text="", content=b""):
                self.status_code = status_code
                self.text = text
                self.content = content
                self.headers = {"Content-Length": str(len(content or text.encode("utf-8")))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_content(self, chunk_size=65536):
                data = self.content or self.text.encode("utf-8")
                for i in range(0, len(data), chunk_size):
                    yield data[i:i + chunk_size]

            def raise_for_status(self):
                if self.status_code >= 400:
                    raise RuntimeError(f"HTTP {self.status_code}")

        class FakeSess:
            def get(self, url, params=None, **kwargs):
                if "zenodo.org" in url:
                    return FakeResp(content=spiff_bytes)
                if "Gator" in url:
                    return FakeResp(text=splices_ipac)
                raise AssertionError(f"Unexpected GET {url}")

            def post(self, url, data=None, **kwargs):
                q = (data or {}).get("QUERY", "")
                if "qso_candidates" in q:
                    return FakeResp(text="source_id,ra,dec,pmra,pmdec,phot_g_mean_mag,redshift_qsoc\n9001,150.1,2.2,0.1,-0.1,17.8,1.42\n")
                if "galaxy_candidates" in q:
                    return FakeResp(text="source_id,ra,dec,pmra,pmdec,phot_g_mean_mag\n9002,210.5,45.2,0.0,0.0,17.9\n")
                if "best_class_name = 'YSO'" in q:
                    return FakeResp(text="source_id,ra,dec,pmra,pmdec,phot_g_mean_mag,best_class_score\n9003,68.2,24.5,2.0,-18.0,14.5,0.96\n")
                if "best_class_name = 'LPV'" in q:
                    return FakeResp(text="source_id,ra,dec,pmra,pmdec,phot_g_mean_mag,best_class_score\n9004,310.2,-12.5,-3.0,-4.0,12.1,0.98\n")
                return FakeResp(text="source_id,ra,dec,pmra,pmdec,phot_g_mean_mag,teff_gspphot\n9005,200.1,35.2,-5.0,3.0,12.8,5600.0\n")

        with tempfile.TemporaryDirectory() as tmpdir:
            out_csv = os.path.join(tmpdir, "curated.csv")
            summary = bmc.build_curated_catalog(
                per_class=2,
                out_csv=out_csv,
                session=FakeSess(),
            )
            self.assertGreaterEqual(sum(summary["class_counts"].values()), 6)
            with open(out_csv, encoding="utf-8", newline="") as f:
                rows = list(csv.DictReader(f))
            # Duplicate C AGB within 10 arcsec collapsed; M2 dwarf filtered out.
            classes = [r["ml_class"] for r in rows]
            self.assertIn("Ultracool dwarf", classes)
            self.assertIn("Young star with ice or dust", classes)
            self.assertIn("Evolved giant star", classes)
            self.assertIn("Star", classes)
            self.assertIn("Active galaxy or quasar", classes)
            self.assertIn("Galaxy", classes)
            # First round of rows must interleave distinct classes instead of clustering one class at top.
            self.assertEqual(len(set(classes[:6])), len(summary["class_counts"]))
            # Must parse directly via download_real_spherex_gaia.load_targets_csv!
            loaded = dl.load_targets_csv(out_csv)
            self.assertEqual(len(loaded), len(rows))
            for name in loaded:
                dl._validate_target_name(name)

    def test_build_ml_catalog_rejects_untrusted_host_and_unsafe_zip(self):
        import io
        import zipfile
        import build_ml_catalog as bmc

        with self.assertRaises(ValueError):
            bmc.fetch_spiff_ultracool_dwarfs(url="https://evil.example/spiff.zip")

        bad_zip = io.BytesIO()
        with zipfile.ZipFile(bad_zip, "w") as zf:
            zf.writestr("../../evil.csv", "a,b\n1,2\n")

        class BadResp:
            status_code = 200
            headers = {"Content-Length": str(len(bad_zip.getvalue()))}

            def __enter__(self):
                return self

            def __exit__(self, *args):
                return False

            def iter_content(self, chunk_size=65536):
                yield bad_zip.getvalue()

            def raise_for_status(self):
                pass

        class BadSess:
            def get(self, url, **kwargs):
                return BadResp()

        with self.assertRaises(ValueError):
            bmc.fetch_spiff_ultracool_dwarfs(session=BadSess())


if __name__ == "__main__":
    unittest.main()
