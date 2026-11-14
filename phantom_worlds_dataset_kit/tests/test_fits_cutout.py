from io import BytesIO
import csv
import json
import os
import tempfile
import unittest

from astropy.io import fits
from astropy.wcs import WCS
import numpy as np

from phantom_worlds.contracts import TARGET_SPECS, _project_sky_to_px, decode_calibrated_pack, load_patch_arrays, propagate_position
from phantom_worlds.fits_cutout import (
    CUTOUT_FOV_ARCMIN,
    CUTOUT_GRID_SIZE,
    CutoutCoverageError,
    MASK_EDGE,
    MASK_IRSA_REJECTED,
    MASK_OK,
    MASK_OVERFLOW_SATURATED,
    build_real_target_cutouts,
    extract_real_level2_cutout,
)


def _build_mock_spherex_level2_fits_bytes(
    center_ra=133.736027,
    center_dec=-7.240236,
    pa_deg=32.0,
    shape=(160, 160),
    star_offset_arcmin=(1.2, 0.9),
):
    ny, nx = shape
    w = WCS(naxis=2)
    scale = 6.15 / 3600.0
    theta = np.deg2rad(pa_deg)
    c, s = np.cos(theta), np.sin(theta)
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [center_ra, center_dec]
    w.wcs.crpix = [nx / 2.0 + 0.5, ny / 2.0 + 0.5]
    w.wcs.cd = np.array([[-scale * c, scale * s], [scale * s, scale * c]])

    # Star world position offset in arcmin (dx_east, dy_north)
    cosd = np.cos(np.deg2rad(center_dec))
    star_ra = center_ra + (star_offset_arcmin[0] / 60.0) / cosd
    star_dec = center_dec + (star_offset_arcmin[1] / 60.0)
    star_px, star_py = w.all_world2pix([[star_ra, star_dec]], 0)[0]

    yy, xx = np.mgrid[0:ny, 0:nx]
    zodi = 14.5 + 0.02 * yy - 0.01 * xx
    sky = 0.25 + 120.0 * np.exp(-0.5 * ((xx - star_px) ** 2 + (yy - star_py) ** 2) / 0.85**2)
    image = (sky + zodi).astype(np.float32)

    flags = np.zeros((ny, nx), dtype=np.int32)
    # Bit 21 (SOURCE) and bit 12 (FULLSAMPLE) on the star MUST stay unmasked!
    flags[(xx - star_px) ** 2 + (yy - star_py) ** 2 <= 9.0] |= (1 << 21) | (1 << 12)
    # Place one HOT rejected pixel (bit 10) and one OVERFLOW pixel (bit 1) near center-left
    rej_ra = center_ra - (1.0 / 60.0) / cosd
    rej_dec = center_dec
    rx, ry = w.all_world2pix([[rej_ra, rej_dec]], 0)[0]
    rix, riy = int(round(rx)), int(round(ry))
    flags[riy, rix] |= 1 << 10  # HOT -> IRSA_REJECTED

    ovf_ra = center_ra
    ovf_dec = center_dec - (1.0 / 60.0)
    ox, oy = w.all_world2pix([[ovf_ra, ovf_dec]], 0)[0]
    oix, oiy = int(round(ox)), int(round(oy))
    flags[oiy, oix] |= 1 << 1  # OVERFLOW -> OVERFLOW_SATURATED

    hdr = w.to_header()
    hdr["BUNIT"] = "MJy / sr"
    primary = fits.PrimaryHDU()
    hdu_img = fits.ImageHDU(data=image, header=hdr, name="IMAGE")
    # Real SPHEREx Level-2 FLAGS is row-tiled RICE_1 BINTABLE
    hdu_flg = fits.CompImageHDU(data=flags, compression_type="RICE_1", tile_shape=(1, nx), name="FLAGS")
    hdu_var = fits.ImageHDU(data=np.ones((ny, nx), dtype=np.float32), name="VARIANCE")
    hdu_zod = fits.ImageHDU(data=zodi.astype(np.float32), name="ZODI")

    buf = BytesIO()
    fits.HDUList([primary, hdu_img, hdu_flg, hdu_var, hdu_zod]).writeto(buf)
    return buf.getvalue(), (star_ra, star_dec), (rej_ra, rej_dec), (ovf_ra, ovf_dec)


class _FakeRangeResponse:
    def __init__(self, status_code, content):
        self.status_code = status_code
        self.content = content

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")


class _RangeOnlySession:
    """In-memory byte-range server recording every byte requested."""

    def __init__(self, blob):
        self.blob = blob
        self.requests = []
        self.bytes_served = 0

    def get(self, url, headers=None, timeout=None):
        rng = (headers or {}).get("Range", "")
        if not rng.startswith("bytes="):
            raise AssertionError("Expected HTTP Range header")
        s_str, e_str = rng.replace("bytes=", "", 1).split("-", 1)
        start, end = int(s_str), min(int(e_str), len(self.blob) - 1)
        chunk = self.blob[start : end + 1]
        self.requests.append((url, start, end))
        self.bytes_served += len(chunk)
        return _FakeRangeResponse(206, chunk)


class TestFitsCutoutEngine(unittest.TestCase):
    def test_range_reader_extracts_rice1_flags_subtracts_zodi_and_aligns_canvas_with_viewer(self):
        center_ra, center_dec = 133.736027, -7.240236
        blob, (star_ra, star_dec), (rej_ra, rej_dec), (ovf_ra, ovf_dec) = _build_mock_spherex_level2_fits_bytes(
            center_ra=center_ra,
            center_dec=center_dec,
            pa_deg=37.0,
            shape=(180, 180),
            star_offset_arcmin=(1.2, 0.9),
        )
        sess = _RangeOnlySession(blob)
        s3_url = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/mock_d6.fits"

        out = extract_real_level2_cutout(s3_url, center_ra, center_dec, session=sess)
        flux = out["flux"]
        mask = out["mask"]

        self.assertEqual(flux.shape, (CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE))
        self.assertEqual(mask.shape, (CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE))
        # Confirm Range reads pulled strictly less than the full FITS file
        self.assertLess(sess.bytes_served, len(blob))

        # Star has bit 21 (SOURCE) and bit 12 (FULLSAMPLE) -> MUST remain unmasked and peak at projected pixel
        exp_x, exp_y = _project_sky_to_px(star_ra, star_dec, center_ra, center_dec, CUTOUT_FOV_ARCMIN, CUTOUT_GRID_SIZE)
        peak_y, peak_x = np.unravel_index(np.nanargmax(flux), flux.shape)
        self.assertLess(abs(peak_x - exp_x), 1.5)
        self.assertLess(abs(peak_y - exp_y), 1.5)
        self.assertGreater(flux[peak_y, peak_x], 80.0)  # net after ZODI subtraction (star=120, sky=0.25)
        self.assertEqual(int(mask[peak_y, peak_x]), MASK_OK)

        # Sky floor after ZODI subtraction should be ~0.25 MJy/sr (NOT ~14.75!)
        self.assertAlmostEqual(float(np.nanmedian(flux)), 0.25, delta=0.1)

        # Bit 10 HOT pixel must be masked as MASK_IRSA_REJECTED near expected projected location
        rx, ry = _project_sky_to_px(rej_ra, rej_dec, center_ra, center_dec, CUTOUT_FOV_ARCMIN, CUTOUT_GRID_SIZE)
        rej_patch = mask[max(0, int(ry) - 1) : int(ry) + 2, max(0, int(rx) - 1) : int(rx) + 2]
        self.assertTrue(np.any((rej_patch & MASK_IRSA_REJECTED) != 0))

        # Bit 1 OVERFLOW pixel must be masked as MASK_OVERFLOW_SATURATED
        ox, oy = _project_sky_to_px(ovf_ra, ovf_dec, center_ra, center_dec, CUTOUT_FOV_ARCMIN, CUTOUT_GRID_SIZE)
        ovf_patch = mask[max(0, int(oy) - 1) : int(oy) + 2, max(0, int(ox) - 1) : int(ox) + 2]
        self.assertTrue(np.any((ovf_patch & MASK_OVERFLOW_SATURATED) != 0))

        # Edge-mask check & uint16 quantization round-trip
        self.assertFalse(np.any(mask == MASK_EDGE))  # full 180x180 rotated cutout covers 64x64 completely

    def test_off_target_exposure_raises_coverage_error_and_host_allowlist_blocks_evil_url(self):
        blob, _, _, _ = _build_mock_spherex_level2_fits_bytes(center_ra=10.0, center_dec=10.0, shape=(100, 100))
        sess = _RangeOnlySession(blob)
        s3_url = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/level2/far.fits"
        with self.assertRaises(CutoutCoverageError):
            extract_real_level2_cutout(s3_url, 133.7, -7.2, session=sess)

        with self.assertRaises(ValueError):
            extract_real_level2_cutout(
                "https://irsa.ipac.caltech.edu/cgi-bin/Cutouts?locstr=bad",
                10.0,
                10.0,
                session=sess,
            )

    def test_build_real_target_cutouts_end_to_end_with_mocked_s3_and_bitmask_roundtrip(self):
        csv_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "csv_tables"
        )
        # Build 5 synthetic FITS streams centered on each target J2026 epoch position
        fits_by_url = {}
        from phantom_worlds.contracts import load_targets

        targets = {r["target_id"]: r for r in load_targets(csv_dir)}
        with tempfile.TemporaryDirectory() as tmpdir:
            data_real_dir = os.path.join(tmpdir, "data_real")
            contracts_dir = os.path.join(tmpdir, "hour0_contracts")
            static_dir = os.path.join(tmpdir, "static")
            data_manifest = os.path.join(tmpdir, "data", "manifest.csv")
            os.makedirs(data_real_dir, exist_ok=True)

            for tid, spec in TARGET_SPECS.items():
                tgt = targets[tid]
                ra26, dec26 = propagate_position(
                    float(tgt["ra_deg_j2000"]),
                    float(tgt["dec_deg_j2000"]),
                    float(tgt["pm_ra_mas_yr"]),
                    float(tgt["pm_dec_mas_yr"]),
                    26.0,
                )
                blob, _, _, _ = _build_mock_spherex_level2_fits_bytes(center_ra=ra26, center_dec=dec26)
                slug = spec["slug"]
                frames_path = os.path.join(data_real_dir, f"{slug}_spherex_frames.csv")
                with open(frames_path, "w", encoding="utf-8", newline="") as f:
                    writer = csv.DictWriter(
                        f,
                        fieldnames=["obs_collection", "obs_id", "s_ra", "s_dec", "energy_bandpassname", "t_min", "cloud_access"],
                    )
                    writer.writeheader()
                    for v_idx, mjd in enumerate((60800.0, 60980.0, 61160.0), 1):
                        for det_num in range(1, 7):
                            key = f"dr1/level2/mock/{slug}_v{v_idx}_D{det_num}.fits"
                            url = f"https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/{key}"
                            fits_by_url[url] = blob
                            writer.writerow(
                                {
                                    "obs_collection": "spherex_dr1",
                                    "obs_id": f"{slug}_obs_{v_idx}_D{det_num}",
                                    "s_ra": f"{ra26:.6f}",
                                    "s_dec": f"{dec26:.6f}",
                                    "energy_bandpassname": f"SPHEREx-D{det_num}",
                                    "t_min": f"{mjd:.4f}",
                                    "cloud_access": json.dumps(
                                        {"aws": {"bucket_name": "nasa-irsa-spherex", "key": key, "region": "us-east-1"}}
                                    ),
                                }
                            )

            class _RoutingRangeSession:
                def get(self, url, headers=None, timeout=None):
                    blob = fits_by_url[url]
                    rng = (headers or {}).get("Range", "")
                    s_str, e_str = rng.replace("bytes=", "", 1).split("-", 1)
                    start, end = int(s_str), min(int(e_str), len(blob) - 1)
                    return _FakeRangeResponse(206, blob[start : end + 1])

                def close(self):
                    pass

            # Write dummy sources.json so build_static_fallback_js succeeds
            os.makedirs(contracts_dir, exist_ok=True)
            with open(os.path.join(contracts_dir, "sources.json"), "w", encoding="utf-8") as sf:
                json.dump({"target_spectra": {}, "known_catalog_sources": []}, sf)

            summaries = build_real_target_cutouts(
                contracts_dir=contracts_dir,
                csv_dir=csv_dir,
                data_real_dir=data_real_dir,
                static_dir=static_dir,
                data_manifest_path=data_manifest,
                session_factory=_RoutingRangeSession,
                max_workers=2,
            )
            self.assertEqual(set(summaries.keys()), set(TARGET_SPECS.keys()))
            for tid in TARGET_SPECS:
                manifest, flux, mask = load_patch_arrays(contracts_dir=contracts_dir, target_id=tid)
                self.assertEqual(manifest["cutout_origin"], "real_spherex_s3_wcs_cutout")
                self.assertEqual(len(manifest["source_exposures"]), 18)
                self.assertEqual(flux.shape, (3, 6, 64, 64))
                self.assertGreater(float(np.nanmax(flux)), 80.0)
                self.assertTrue(np.all(np.isnan(flux[mask != MASK_OK])))
            self.assertTrue(os.path.exists(data_manifest))
            self.assertTrue(os.path.exists(os.path.join(static_dir, "fallback_data.js")))


if __name__ == "__main__":
    unittest.main()
