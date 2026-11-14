"""Offline unit tests for phantom_worlds.real_ml_data (HEALPix, Zenodo SPIFF, S3 Cube Range extractor)."""

import io
import math
import os
import tempfile
import unittest
import zipfile

from astropy.io import fits
import numpy as np

from phantom_worlds.fits_cutout import validate_remote_url
from phantom_worlds.real_ml_data import (
    _SPECTRAL_CHANNELS_DTYPE,
    ALLOWED_ML_DATA_HOSTS,
    _flambda_to_ujy,
    _estimate_w2_mag_from_spectrum,
    ang2pix_nest,
    ang2pix_nest32,
    extract_cube_tile_spectra,
    load_spiff_hybrid_templates,
    load_spiff_known_bd_spectra,
    s3_cube_url_for_ipix,
)


class _RangeByteResponse:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content
        self.headers = {"Content-Length": str(len(content))}

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False


class _FakeRangeSession:
    def __init__(self, payload_by_url):
        self.payload_by_url = payload_by_url
        self.requests = []

    def get(self, url, headers=None, **kwargs):
        self.requests.append((url, dict(headers or {}), dict(kwargs)))
        raw = self.payload_by_url[url]
        rng = (headers or {}).get("Range")
        if rng and rng.startswith("bytes="):
            lo_s, hi_s = rng[len("bytes=") :].split("-", 1)
            lo = int(lo_s)
            hi = min(int(hi_s), len(raw) - 1)
            return _RangeByteResponse(206, raw[lo : hi + 1])
        return _RangeByteResponse(200, raw)


def _build_synthetic_cube_bytes(nx=32, ny=32, nchan=8, ra_c=83.75, dec_c=-5.0):
    wl = np.linspace(1.0, 4.5, nchan, dtype=">f4")
    bw = np.full(nchan, 0.25, dtype=">f4")

    img = np.full((nchan, ny, nx), 1.0, dtype=">f4")
    nhits = np.full((nchan, ny, nx), 4, dtype=">i4")
    flags = np.zeros((nchan, ny, nx), dtype=">i4")

    # Place point source at center pixel (16, 16) with unmasked bit 21 (SOURCE) & bit 12 (FULLSAMPLE) on planes 0..5.
    cy, cx = 16, 16
    img[:6, cy, cx] = 10.0  # net = +9.0 MJy/sr above background=1.0
    flags[:6, cy, cx] = (1 << 21) | (1 << 12)
    # Plane 6: missing sample (NHITS == 0 at source center) -> must become NaN.
    img[6, cy, cx] = 10.0
    nhits[6, cy, cx] = 0
    # Plane 7: IRSA rejected bit 0 (TRANSIENT) at source center -> must become NaN.
    img[7, cy, cx] = 10.0
    flags[7, cy, cx] = 1 << 0

    hdu0 = fits.PrimaryHDU()
    hdu_img = fits.ImageHDU(data=img, name="IMAGE")
    hdu_img.header["CTYPE1"] = "RA---TAN"
    hdu_img.header["CTYPE2"] = "DEC--TAN"
    hdu_img.header["CTYPE3"] = "WAVE-TAB"
    hdu_img.header["CRVAL1"] = ra_c
    hdu_img.header["CRVAL2"] = dec_c
    hdu_img.header["CRPIX1"] = float(cx + 1)
    hdu_img.header["CRPIX2"] = float(cy + 1)
    hdu_img.header["CDELT1"] = -14.0 / 3600.0
    hdu_img.header["CDELT2"] = 14.0 / 3600.0
    hdu_img.header["RADESYS"] = "ICRS"
    hdu_img.header["BUNIT"] = "MJy/sr"

    hdu_nh = fits.ImageHDU(data=nhits, name="NHITS")
    hdu_fl = fits.ImageHDU(data=flags, name="FLAGS")

    sc_table = np.zeros(nchan, dtype=_SPECTRAL_CHANNELS_DTYPE)
    sc_table["DETECTOR"] = 1
    sc_table["SUBCHAN"] = np.arange(1, nchan + 1, dtype=">i2")
    sc_table["WAVELENGTH"] = wl
    sc_table["WL_MIN"] = wl - 0.1
    sc_table["WL_MAX"] = wl + 0.1
    sc_table["R"] = 42.0
    sc_table["R_STD"] = 1.0
    sc_table["BANDWIDTH"] = bw
    hdu_sc = fits.BinTableHDU(data=sc_table, name="SPECTRAL_CHANNELS")

    buf = io.BytesIO()
    fits.HDUList([hdu0, hdu_img, hdu_nh, hdu_fl, hdu_sc]).writeto(buf)
    raw = buf.getvalue()
    # Compute true pixel area in sr for a 14"/px TAN projection.
    pix_area_sr = ((14.0 / 3600.0) * math.pi / 180.0) ** 2
    return raw, wl.astype(np.float64), bw.astype(np.float64), pix_area_sr


class RealMLDataTests(unittest.TestCase):
    def test_ang2pix_nest32_matches_known_spherex_cubes(self):
        expected = [
            (269.452075, 4.693365, 7945, "Dir0"),
            (133.786245, -7.244372, 10226, "Dir10000"),
            (331.077167, -56.790500, 11391, "Dir10000"),
            (76.956529, 30.401440, 277, "Dir0"),
            (248.155875, 66.703167, 2928, "Dir0"),
            (189.0, 62.0, 2786, "Dir0"),
        ]
        for ra, dec, exp_pix, exp_dir in expected:
            got = ang2pix_nest32(ra, dec)
            if exp_pix != 2786:  # First 5 verified directly from real data_real/*_spherex_frames.csv
                self.assertEqual(got, exp_pix)
            url = s3_cube_url_for_ipix(got)
            self.assertIn(exp_dir, url)
            self.assertTrue(url.startswith("https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/hips5_cube/"))

        h8_a = ang2pix_nest(256, 83.75, -5.0)
        h8_b = ang2pix_nest(256, 84.20, -5.4)
        self.assertNotEqual(h8_a, h8_b)
        with self.assertRaises(ValueError):
            ang2pix_nest(30, 0.0, 0.0)

    def test_spiff_archive_loading_and_flux_unit_conversion(self):
        # Analytic check: 1e-16 W/m^2/um at 2.0 um == 4.0 * 1e-16 * 3.33564095e17 = 133.425638 uJy
        got_ujy = float(_flambda_to_ujy(2.0, 1e-16))
        self.assertAlmostEqual(got_ujy, 133.425638079, places=4)
        # W2 zero point check: 171.787 Jy == 171787000 uJy -> W2 = 0.0
        wl_grid = np.linspace(0.8, 4.9, 20)
        flat_zp = np.full(20, 171.787e6)
        self.assertAlmostEqual(_estimate_w2_mag_from_spectrum(wl_grid, flat_zp), 0.0, places=3)

        with tempfile.TemporaryDirectory() as tmpdir:
            tables_zip = os.path.join(tmpdir, "spiff_tables.zip")
            tmpl_zip = os.path.join(tmpdir, "spiff_templates_hybrid_csv.zip")
            bds_zip = os.path.join(tmpdir, "spiff_known_bds_binned_csv.zip")

            with zipfile.ZipFile(tables_zip, "w") as zf:
                zf.writestr(
                    "spiff_tables/spherex_autotype_datasets_fulltable.csv",
                    "designation,ra_j2000,dec_j2000,dataset,spiff_autotype,spiff_chi2_r\n"
                    "2MASS_J0001+0000,00:01:00.00,+00:00:00.0,Known,T6,1.2\n",
                )
            with zipfile.ZipFile(tmpl_zip, "w") as zf:
                rows = ["WAVELENGTH_MICRONS , FLUX_FLAMBDA , FLUX_FLAMBDA_UNC"]
                for w in np.linspace(1.1, 4.9, 30):
                    rows.append(f"{w:.6f}, 1e-16, 1e-17")
                zf.writestr("spiff_templates/hybrid_csv/T6_spherex_standard.csv", "\n".join(rows))
            with zipfile.ZipFile(bds_zip, "w") as zf:
                rows = ["wavelength_um,flux_flambda_w_m2_um,flux_error"]
                for w in np.linspace(0.75, 4.95, 40):
                    rows.append(f"{w:.6f},1e-16,5e-18")
                zf.writestr(
                    "known_bds/csv/2MASS_J0001+0000_moca_oid_1_spt_T6_spherex_spectrum.csv",
                    "\n".join(rows),
                )

            paths = {
                "spiff_tables.zip": tables_zip,
                "spiff_templates_hybrid_csv.zip": tmpl_zip,
                "spiff_known_bds_binned_csv.zip": bds_zip,
            }
            dst_wl = np.linspace(0.8, 4.9, 30)
            tmpls = load_spiff_hybrid_templates(paths, dst_wl)
            self.assertEqual(len(tmpls), 1)
            self.assertTrue(np.isnan(tmpls[0][0]))  # < 1.1 um clipped cleanly to NaN
            self.assertTrue(np.isfinite(tmpls[0][-1]))

            bds = load_spiff_known_bd_spectra(paths, dst_wl)
            self.assertEqual(len(bds), 1)
            self.assertEqual(bds[0]["ml_class"], "Ultracool dwarf")
            self.assertEqual(bds[0]["label_grade"], "gold")
            self.assertTrue(bds[0]["sky_tile"].startswith("h8_"))
            self.assertAlmostEqual(bds[0]["ra_deg"], 0.25, places=4)
            self.assertGreater(np.nanmedian(bds[0]["flux_ujy"]), 100.0)

    def test_cube_range_extractor_masks_nhits0_and_irsa_rejected_keeps_source_bit21(self):
        raw, exp_wl, exp_bw, pix_sr = _build_synthetic_cube_bytes()
        url = s3_cube_url_for_ipix(5701)
        fake_sess = _FakeRangeSession({url: raw})
        targets = [{"target_name": "TEST_YSO", "ra_deg": 83.75, "dec_deg": -5.0, "pmra": 0.0, "pmdec": 0.0, "ref_epoch": 2026.0}]

        with tempfile.TemporaryDirectory() as tmpdir:
            wl_um, bw_um, extracted, got_url, bytes_read = extract_cube_tile_spectra(
                5701, targets, session=fake_sess, url=url, cache_dir=tmpdir, max_workers=1
            )
            self.assertEqual(got_url, url)
            self.assertGreater(bytes_read, 0)
            self.assertTrue(np.allclose(wl_um, exp_wl, atol=1e-4))
            self.assertIn("TEST_YSO", extracted)
            fl = extracted["TEST_YSO"]["flux_ujy"]
            self.assertEqual(len(fl), 8)
            expected_net_ujy = 9.0 * pix_sr * 1e12
            # Planes 0..5 keep source bit 21 & 12 unmasked and recover exact injected point-source net flux.
            for k in range(6):
                self.assertTrue(np.isfinite(fl[k]))
                self.assertAlmostEqual(fl[k], expected_net_ujy, delta=0.05 * expected_net_ujy)
            # Plane 6 (NHITS == 0) and Plane 7 (IRSA_REJECTED bit 0) must be NaN.
            self.assertTrue(np.isnan(fl[6]))
            self.assertTrue(np.isnan(fl[7]))
            # Verify serialized npz loads with allow_pickle=False.
            npz_path = os.path.join(tmpdir, "Npix5701_spectra.npz")
            with np.load(npz_path, allow_pickle=False) as loaded:
                self.assertIn("flux_ujy", loaded.files)

    def test_zenodo_and_s3_url_allowlist_blocks_untrusted_hosts(self):
        with self.assertRaises(ValueError):
            validate_remote_url("http://zenodo.org/api/records/19051216/files/spiff_tables.zip/content", allowed_hosts=ALLOWED_ML_DATA_HOSTS)
        with self.assertRaises(ValueError):
            validate_remote_url("https://evil.example.com/Npix5701_cube.fits", allowed_hosts=ALLOWED_ML_DATA_HOSTS)
        with self.assertRaises(ValueError):
            validate_remote_url("https://169.254.169.254/latest/meta-data", allowed_hosts=ALLOWED_ML_DATA_HOSTS)
        with self.assertRaises(ValueError):
            s3_cube_url_for_ipix(99999)


if __name__ == "__main__":
    unittest.main()
