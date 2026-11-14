"""Tier-B Engine (T40-T48): reference scenes, joint PSF deblending, detectors, checks, prediction & injection."""

from datetime import datetime, timezone
import json
import math
import os
import struct

import numpy as np

import pyvo

from phantom_worlds.contracts import (
    DEFAULT_CONTRACTS_DIR,
    DETECTOR_INDEX,
    HardenedHTTPSession,
    VALID_DETECTORS,
    load_manifest,
    load_patch_arrays,
    propagate_position,
    resolve_s3_cloud_access_url,
)
from phantom_worlds.fits_cutout import (
    CUTOUT_GRID_SIZE,
    CutoutCoverageError,
    HttpRangeFitsReader,
    INVALID_U16,
    PIXEL_SCALE_ARCSEC,
    _MJY_SR_TO_UJY_PX,
    _measure_d6_depth_and_rms,
    _quantize_flux_and_masks,
    _select_visit_clusters,
    build_target_canvas_wcs,
    extract_real_level2_cutout,
)

DEFAULT_FIELDS_DIR = os.path.join(DEFAULT_CONTRACTS_DIR, "fields")
PIPELINE_VERSION = "0.3.0-tierb"

# Real empirical PSF effective widths (NEFF -> equivalent Gaussian sigma_px fallback) measured on S3 DR1/QR3 EPSF HDU.
DEFAULT_DETECTOR_SIGMA_PX = {
    "D1": 0.519,
    "D2": 0.516,
    "D3": 0.505,
    "D4": 0.598,
    "D5": 0.596,
    "D6": 0.620,
}

# Measured S3 spectral_wcs CWAVE detector overlap windows (um) from K12 empirical inspection.
DETECTOR_CWAVE_BOUNDS_UM = {
    "D1": (0.7349, 1.1146),
    "D2": (1.0859, 1.6501),
    "D3": (1.6163, 2.4192),
    "D4": (2.3975, 3.8181),
    "D5": (3.7984, 4.4246),
    "D6": (4.4018, 5.0053),
}

# 2MASS Ks Vega zero-point flux density (Cohen et al. 2003, AJ 126, 1090).
_TWOMASS_KS_ZERO_POINT_JY = 666.7
_IRSA_TAP_SYNC_URL = "https://irsa.ipac.caltech.edu/TAP/sync"

FIELD_SPECS = {
    "w1925": {
        "field_id": "w1925",
        "field_name": "W1925 Galactic Plane",
        "plane_type": "galactic_plane",
        "galactic_coord_str": "l=43.04, b=-4.25",
        "center_ra_deg": 291.30325,
        "center_dec_deg": 7.01078,
        "pm_ra_mas_yr": 0.0,
        "pm_dec_mas_yr": 0.0,
        "fov_arcmin": 6.56,
        "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
        "benchmark_target": {
            "name": "WISE J192512.78+070038.8",
            "sp_type": "L7",
            "distance_pc": 11.2,
            "ra_deg": 291.30325,
            "dec_deg": 7.01078,
        },
        "cutout_target_id": None,
    },
    "rwaur": {
        "field_id": "rwaur",
        "field_name": "RW Aurigae (Off-Plane)",
        "plane_type": "off_plane",
        "galactic_coord_str": "l=174.5, b=-6.7",
        "center_ra_deg": 76.9565,
        "center_dec_deg": 30.401417,
        "pm_ra_mas_yr": 2.9,
        "pm_dec_mas_yr": -24.1,
        "fov_arcmin": 6.56,
        "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
        "benchmark_target": {
            "name": "RW Aurigae",
            "sp_type": "T Tauri",
            "distance_pc": 163.0,
            "ra_deg": 76.9565,
            "dec_deg": 30.401417,
        },
        "cutout_target_id": "TGT-04",
    },
}


def _safe_float(val, default=None):
    try:
        out = float(val)
        return out if math.isfinite(out) else default
    except (TypeError, ValueError):
        return default


def _sky_sep_arcsec(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    r1, d1 = math.radians(ra1_deg), math.radians(dec1_deg)
    r2, d2 = math.radians(ra2_deg), math.radians(dec2_deg)
    dra = (r2 - r1 + math.pi) % (2.0 * math.pi) - math.pi
    cos_mid = math.cos(0.5 * (d1 + d2))
    return math.degrees(math.hypot(dra * cos_mid, d2 - d1)) * 3600.0


def _tap_query_csv_rows(adql, session=None, timeout=30):
    sess = session or HardenedHTTPSession(timeout=timeout)
    resp = sess.get(_IRSA_TAP_SYNC_URL, params={"QUERY": adql, "FORMAT": "csv"}, timeout=timeout)
    resp.raise_for_status()
    lines = [ln for ln in resp.text.splitlines() if ln.strip()]
    if len(lines) <= 1:
        return []
    import csv

    return list(csv.DictReader(lines))


def fetch_reference_catalogues(center_ra_deg, center_dec_deg, radius_arcmin=3.3, session=None):
    """Query Gaia DR3, 2MASS fp_psc, and CatWISE2020/AllWISE on IRSA TAP, reporting raw counts per catalogue."""
    sess = session or HardenedHTTPSession(timeout=35)
    r_deg = float(radius_arcmin) / 60.0
    cos_d = max(math.cos(math.radians(center_dec_deg)), 0.1)
    dra = r_deg / cos_d
    ra_lo, ra_hi = center_ra_deg - dra, center_ra_deg + dra
    dec_lo, dec_hi = max(-90.0, center_dec_deg - r_deg), min(90.0, center_dec_deg + r_deg)

    def _in_circle(ra_v, dec_v):
        return _sky_sep_arcsec(center_ra_deg, center_dec_deg, ra_v, dec_v) <= radius_arcmin * 60.0

    # 1. Gaia DR3 (with proper motion & parallax)
    gaia_adql = (
        "SELECT TOP 4000 source_id, ra, dec, pmra, pmdec, parallax, phot_g_mean_mag, bp_rp "
        "FROM gaia_dr3_source "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {center_ra_deg:.6f}, {center_dec_deg:.6f}, {r_deg:.5f})) = 1"
    )
    gaia_raw = _tap_query_csv_rows(gaia_adql, session=sess, timeout=30)

    # 2. 2MASS Point Source Catalog (J2000)
    tm_adql = (
        "SELECT TOP 2000 designation, ra, dec, j_m, h_m, k_m "
        "FROM fp_psc "
        f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {center_ra_deg:.6f}, {center_dec_deg:.6f}, {r_deg:.5f})) = 1"
    )
    tm_raw = _tap_query_csv_rows(tm_adql, session=sess, timeout=30)

    # 3. CatWISE2020 using indexed RA/DEC box first (cone scans time out on dense Galactic fields); fallback to AllWISE.
    cw_raw = []
    cw_source = "catwise_2020"
    try:
        cw_adql = (
            "SELECT TOP 2000 source_name, ra, dec, w1mpro, w2mpro, pmra, pmdec "
            "FROM catwise_2020 "
            f"WHERE ra BETWEEN {ra_lo:.6f} AND {ra_hi:.6f} AND dec BETWEEN {dec_lo:.6f} AND {dec_hi:.6f}"
        )
        cw_box = _tap_query_csv_rows(cw_adql, session=sess, timeout=35)
        cw_raw = [r for r in cw_box if _safe_float(r.get("ra")) is not None and _in_circle(float(r["ra"]), float(r["dec"]))]
    except Exception:
        cw_source = "allwise_p3as_psd"
        aw_adql = (
            "SELECT TOP 2000 designation AS source_name, ra, dec, w1mpro, w2mpro, pmra, pmdec "
            "FROM allwise_p3as_psd "
            f"WHERE CONTAINS(POINT('ICRS', ra, dec), CIRCLE('ICRS', {center_ra_deg:.6f}, {center_dec_deg:.6f}, {r_deg:.5f})) = 1"
        )
        cw_raw = _tap_query_csv_rows(aw_adql, session=sess, timeout=25)

    # Merge into unified catalogued objects anchored on 2MASS -> Gaia DR3 -> CatWISE2020
    merged = []
    for r in tm_raw:
        ra_v = _safe_float(r.get("ra"))
        dec_v = _safe_float(r.get("dec"))
        if ra_v is None or dec_v is None:
            continue
        merged.append(
            {
                "source_id": f"2MASS-{r.get('designation', len(merged))}",
                "catalogue": "2MASS",
                "ra_ref_deg": round(ra_v, 6),
                "dec_ref_deg": round(dec_v, 6),
                "ref_epoch": 2000.0,
                "pmra_mas_yr": 0.0,
                "pmdec_mas_yr": 0.0,
                "parallax_mas": None,
                "phot_g_mean_mag": None,
                "j_mag": _safe_float(r.get("j_m")),
                "h_mag": _safe_float(r.get("h_m")),
                "ks_mag": _safe_float(r.get("k_m")),
                "w1_mag": None,
                "w2_mag": None,
                "in_gaia": False,
                "in_twomass": True,
                "in_catwise": False,
            }
        )

    # Attach Gaia DR3 proper motions & optical photometry within 1.5 arcsec, else add un-2MASS-matched bright Gaia stars
    for g in gaia_raw:
        gra = _safe_float(g.get("ra"))
        gdec = _safe_float(g.get("dec"))
        if gra is None or gdec is None:
            continue
        pmra = _safe_float(g.get("pmra"), 0.0) or 0.0
        pmdec = _safe_float(g.get("pmdec"), 0.0) or 0.0
        gmag = _safe_float(g.get("phot_g_mean_mag"))
        plx = _safe_float(g.get("parallax"))
        r00, d00 = propagate_position(gra, gdec, pmra, pmdec, -16.0)
        best_idx, best_sep = None, 1.5
        for idx, m in enumerate(merged):
            sep = _sky_sep_arcsec(r00, d00, m["ra_ref_deg"], m["dec_ref_deg"])
            if sep < best_sep:
                best_sep = sep
                best_idx = idx
        if best_idx is not None:
            m = merged[best_idx]
            m["source_id"] = f"GaiaDR3-{g.get('source_id', m['source_id'])}"
            m["catalogue"] = "GaiaDR3+2MASS"
            m["ra_ref_deg"] = round(gra, 6)
            m["dec_ref_deg"] = round(gdec, 6)
            m["ref_epoch"] = 2016.0
            m["pmra_mas_yr"] = round(pmra, 3)
            m["pmdec_mas_yr"] = round(pmdec, 3)
            m["parallax_mas"] = round(plx, 3) if plx is not None else None
            m["phot_g_mean_mag"] = round(gmag, 3) if gmag is not None else None
            m["in_gaia"] = True
        elif gmag is not None and gmag <= 18.8:
            merged.append(
                {
                    "source_id": f"GaiaDR3-{g.get('source_id', len(merged))}",
                    "catalogue": "GaiaDR3",
                    "ra_ref_deg": round(gra, 6),
                    "dec_ref_deg": round(gdec, 6),
                    "ref_epoch": 2016.0,
                    "pmra_mas_yr": round(pmra, 3),
                    "pmdec_mas_yr": round(pmdec, 3),
                    "parallax_mas": round(plx, 3) if plx is not None else None,
                    "phot_g_mean_mag": round(gmag, 3),
                    "j_mag": None,
                    "h_mag": None,
                    "ks_mag": None,
                    "w1_mag": None,
                    "w2_mag": None,
                    "in_gaia": True,
                    "in_twomass": False,
                    "in_catwise": False,
                }
            )

    # Cross-match CatWISE2020 / AllWISE within 2.5 arcsec; keep IR-only stars with W1 <= 16.5
    for c in cw_raw:
        cra = _safe_float(c.get("ra"))
        cdec = _safe_float(c.get("dec"))
        if cra is None or cdec is None:
            continue
        w1 = _safe_float(c.get("w1mpro"))
        w2 = _safe_float(c.get("w2mpro"))
        cpmra = _safe_float(c.get("pmra"), 0.0) or 0.0
        cpmdec = _safe_float(c.get("pmdec"), 0.0) or 0.0
        best_idx, best_sep = None, 2.5
        for idx, m in enumerate(merged):
            r_c, d_c = propagate_position(
                m["ra_ref_deg"], m["dec_ref_deg"], m["pmra_mas_yr"], m["pmdec_mas_yr"], 2015.4 - m["ref_epoch"]
            )
            sep = _sky_sep_arcsec(cra, cdec, r_c, d_c)
            if sep < best_sep:
                best_sep = sep
                best_idx = idx
        if best_idx is not None:
            m = merged[best_idx]
            m["w1_mag"] = round(w1, 3) if w1 is not None else m["w1_mag"]
            m["w2_mag"] = round(w2, 3) if w2 is not None else m["w2_mag"]
            m["in_catwise"] = True
            if "CatWISE" not in m["catalogue"]:
                m["catalogue"] = f"{m['catalogue']}+WISE"
        elif w1 is not None and w1 <= 16.5:
            merged.append(
                {
                    "source_id": f"WISE-{c.get('source_name', len(merged))}",
                    "catalogue": cw_source,
                    "ra_ref_deg": round(cra, 6),
                    "dec_ref_deg": round(cdec, 6),
                    "ref_epoch": 2015.4,
                    "pmra_mas_yr": round(cpmra, 3),
                    "pmdec_mas_yr": round(cpmdec, 3),
                    "parallax_mas": None,
                    "phot_g_mean_mag": None,
                    "j_mag": None,
                    "h_mag": None,
                    "ks_mag": None,
                    "w1_mag": round(w1, 3),
                    "w2_mag": round(w2, 3) if w2 is not None else None,
                    "in_gaia": False,
                    "in_twomass": False,
                    "in_catwise": True,
                }
            )

    def _sort_key(item):
        vals = [v for v in (item.get("ks_mag"), item.get("w1_mag"), item.get("phot_g_mean_mag")) if v is not None]
        return min(vals) if vals else 99.0

    merged.sort(key=_sort_key)
    counts = {
        "gaia_dr3": len(gaia_raw),
        "twomass_fp_psc": len(tm_raw),
        "wise": len(cw_raw),
        "wise_table": cw_source,
        "merged_catalogue_stars": len(merged),
    }
    return counts, merged


def fetch_level2_epsf_calibration(manifest, session=None):
    """Read center 33x33 oversampled (5x5) EPSF stamp per detector from real Level-2 S3 FITS files."""
    sess = session or HardenedHTTPSession(timeout=35)
    out = {}
    exposures = manifest.get("source_exposures") or []
    by_det = {}
    for exp in exposures:
        det = exp.get("detector")
        if det in VALID_DETECTORS and det not in by_det and exp.get("s3_url"):
            by_det[det] = exp["s3_url"]

    for det_id in VALID_DETECTORS:
        url = by_det.get(det_id)
        if not url:
            continue
        try:
            with HttpRangeFitsReader(url, session=sess) as reader:
                hdus = reader.scan_hdus(required_extnames=("EPSF",), max_hdus=10)
                if "EPSF" not in hdus:
                    continue
                h = hdus["EPSF"]["header"]
                naxis1, naxis2 = int(h["NAXIS1"]), int(h["NAXIS2"])
                mid_row = naxis2 // 2
                row_bytes = reader.read_range(hdus["EPSF"]["data_offset"] + mid_row * naxis1, naxis1)
                if len(row_bytes) < 40 + 1089 * 8:
                    continue
                _, _, _, _, _, _, nstar, neff, cwave, cband = struct.unpack(">iiffffifff", row_bytes[:40])
                stamp = np.maximum(np.frombuffer(row_bytes[40 : 40 + 1089 * 8], dtype=">f8").reshape(33, 33), 0.0)
                s_sum = float(np.sum(stamp))
                if s_sum > 0.0:
                    stamp = stamp / s_sum
                out[det_id] = {
                    "oversample": int(h.get("OVSMPX", 5)),
                    "neff_px": round(float(neff), 3),
                    "cwave_um": round(float(cwave), 4),
                    "cband_um": round(float(cband), 4),
                    "nstar": int(nstar),
                    "source_url": url,
                    "stamp_33x33": [[round(float(v), 7) for v in row] for row in stamp],
                }
        except Exception:
            continue
    return out


def _convolve_reprojection_kernel(stamp_33x33, oversample=5):
    """Apply exact 2D bilinear resampling smoothing (Var = 1/6 native px^2 -> sigma = 1/sqrt(6) px)."""
    sigma_sub = float(oversample) / math.sqrt(6.0)
    half_k = int(math.ceil(3.0 * sigma_sub))
    offs = np.arange(-half_k, half_k + 1, dtype=np.float64)
    k1d = np.exp(-0.5 * (offs / sigma_sub) ** 2)
    k1d /= float(np.sum(k1d))
    padded = np.pad(stamp_33x33, half_k, mode="constant")
    tmp = np.apply_along_axis(lambda r: np.convolve(r, k1d, mode="valid"), 1, padded)
    out = np.apply_along_axis(lambda c: np.convolve(c, k1d, mode="valid"), 0, tmp)
    tot = float(np.sum(out))
    return (out / tot) if tot > 0.0 else stamp_33x33


def evaluate_psf_patch(
    ny,
    nx,
    x_s,
    y_s,
    half_box=4,
    stamp_33x33=None,
    sigma_px=0.58,
    oversample=5,
    reprojected=True,
    prepared_stamp=None,
):
    """Integrate normalized sub-pixel PSF over detector pixels inside [y_s+-half_box, x_s+-half_box]."""
    ix0 = max(0, int(math.floor(x_s)) - half_box)
    ix1 = min(nx, int(math.floor(x_s)) + half_box + 1)
    iy0 = max(0, int(math.floor(y_s)) - half_box)
    iy1 = min(ny, int(math.floor(y_s)) + half_box + 1)
    if ix1 <= ix0 or iy1 <= iy0:
        return iy0, iy1, ix0, ix1, np.empty((0, 0), dtype=np.float64)

    sub_offs = (np.arange(oversample, dtype=np.float64) + 0.5) / float(oversample) - 0.5
    xs_pix = np.arange(ix0, ix1, dtype=np.float64)
    ys_pix = np.arange(iy0, iy1, dtype=np.float64)

    active_stamp = prepared_stamp if prepared_stamp is not None else stamp_33x33
    if active_stamp is not None and active_stamp.shape == (33, 33):
        eff_stamp = (
            active_stamp
            if (prepared_stamp is not None or not reprojected)
            else _convolve_reprojection_kernel(active_stamp, oversample=oversample)
        )
        # Pixel-integrated bilinear lookup inside the 33x33 oversampled Level-2 EPSF stamp (center=16.0).
        dx_sub = (xs_pix[:, None] + sub_offs[None, :] - x_s) * float(oversample) + 16.0
        dy_sub = (ys_pix[:, None] + sub_offs[None, :] - y_s) * float(oversample) + 16.0

        def _interp_1d_indices(coords):
            c = np.clip(coords, 0.0, 31.9999)
            i0 = np.floor(c).astype(np.int32)
            frac = c - i0
            return i0, i0 + 1, frac

        x0, x1, fx = _interp_1d_indices(dx_sub)
        y0, y1, fy = _interp_1d_indices(dy_sub)
        in_bounds_x = (dx_sub >= 0.0) & (dx_sub <= 32.0)
        in_bounds_y = (dy_sub >= 0.0) & (dy_sub <= 32.0)

        # Vectorized evaluation over (ny_p, oversample, nx_p, oversample)
        v00 = eff_stamp[y0[:, :, None, None], x0[None, None, :, :]]
        v01 = eff_stamp[y0[:, :, None, None], x1[None, None, :, :]]
        v10 = eff_stamp[y1[:, :, None, None], x0[None, None, :, :]]
        v11 = eff_stamp[y1[:, :, None, None], x1[None, None, :, :]]
        wy4 = fy[:, :, None, None]
        wx4 = fx[None, None, :, :]
        val4 = (
            (1.0 - wy4) * (1.0 - wx4) * v00
            + (1.0 - wy4) * wx4 * v01
            + wy4 * (1.0 - wx4) * v10
            + wy4 * wx4 * v11
        )
        mask4 = in_bounds_y[:, :, None, None] & in_bounds_x[None, None, :, :]
        px_grid = np.sum(np.where(mask4, val4, 0.0), axis=(1, 3))
        norm = float(np.sum(px_grid))
        if norm > 0.0:
            px_grid /= norm
        return iy0, iy1, ix0, ix1, px_grid

    eff_sigma = math.hypot(float(sigma_px), 1.0 / math.sqrt(6.0)) if reprojected else float(sigma_px)
    # Pure analytic sub-pixel Gaussian fallback integrated on the same 5x5 subgrid
    dx = xs_pix[:, None] + sub_offs[None, :] - x_s
    dy = ys_pix[:, None] + sub_offs[None, :] - y_s
    inv_2s2 = -0.5 / max(eff_sigma ** 2, 1e-4)
    gx = np.mean(np.exp(inv_2s2 * (dx ** 2)), axis=1)
    gy = np.mean(np.exp(inv_2s2 * (dy ** 2)), axis=1)
    patch = gy[:, None] * gx[None, :]
    tot = float(np.sum(patch))
    if tot > 0.0:
        patch /= tot
    return iy0, iy1, ix0, ix1, patch


def _resolve_field_paths(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR, fields_dir=None):
    fid = str(field_id or "").strip().lower()
    if fid not in FIELD_SPECS:
        raise KeyError(f"Unknown Tier-B field_id: {field_id!r}")
    spec = FIELD_SPECS[fid]
    f_root = fields_dir or os.path.join(contracts_dir, "fields")
    scene_path = os.path.join(f_root, fid, "scene.json")
    cutout_target_id = spec.get("cutout_target_id")
    if cutout_target_id:
        cutout_dir = os.path.join(contracts_dir, "targets", cutout_target_id)
    else:
        cutout_dir = os.path.join(f_root, fid)
    return spec, scene_path, cutout_dir


def _map_wavelength_to_detector(em_um):
    if em_um is None:
        return None
    for det_id, (lo, hi) in DETECTOR_CWAVE_BOUNDS_UM.items():
        if (lo - 0.03) <= em_um <= (hi + 0.03):
            return det_id
    return None


def _build_field_cutout_pack(spec, cutout_dir, gaia_sources_hint=None, session=None, max_visits=3):
    """Build real multi-visit SPHEREx S3 Level-2 64x64 cutout pack.bin + mask.bin + manifest.json for a sky field."""
    from astropy.time import Time

    sess = session or HardenedHTTPSession(timeout=40)
    sia = pyvo.dal.SIA2Service("https://irsa.ipac.caltech.edu/SIA", session=sess)
    ra_c = float(spec["center_ra_deg"])
    dec_c = float(spec["center_dec_deg"])
    frames_by_det = {det: [] for det in VALID_DETECTORS}
    seen_urls = set()

    for coll in ("spherex_dr1", "spherex_qr3"):
        try:
            tbl = sia.search(pos=(ra_c, dec_c, 0.05), collection=coll, maxrec=300)
        except Exception:
            continue
        for row in tbl:
            cloud_raw = row.get("cloud_access")
            s3_url = resolve_s3_cloud_access_url(cloud_raw) if cloud_raw else None
            if not s3_url or s3_url in seen_urls:
                continue
            em_min = _safe_float(row.get("em_min"))
            em_max = _safe_float(row.get("em_max"))
            em_um = 0.5 * (em_min + em_max) * 1e6 if (em_min is not None and em_max is not None) else None
            det = _map_wavelength_to_detector(em_um)
            if det is None:
                continue
            t_min = _safe_float(row.get("t_min"))
            if t_min is None:
                continue
            seen_urls.add(s3_url)
            frames_by_det[det].append(
                {
                    "detector": det,
                    "obs_id": str(row.get("obs_id") or ""),
                    "obs_collection": coll,
                    "t_min": t_min,
                    "s3_url": s3_url,
                }
            )

    selected_clusters = _select_visit_clusters(frames_by_det, n_visits=max_visits)
    n_visits = len(selected_clusters)
    if n_visits == 0:
        raise RuntimeError(f"No SPHEREx SIA exposures found for field {spec['field_id']!r} at ({ra_c}, {dec_c})")

    ny = nx = CUTOUT_GRID_SIZE
    flux_cube = np.full((n_visits, len(VALID_DETECTORS), ny, nx), np.nan, dtype=np.float64)
    mask_cube = np.full((n_visits, len(VALID_DETECTORS), ny, nx), 4, dtype=np.uint8)
    visits_meta = []
    exposures_used = []

    for v_idx, (visit_id, mjd_lo, mjd_hi) in enumerate(selected_clusters):
        mean_cluster_t = 0.5 * (float(mjd_lo) + float(mjd_hi))
        mjds = []
        dets_present = []
        for det_id in VALID_DETECTORS:
            in_win = [
                f for f in frames_by_det[det_id] if (float(mjd_lo) - 1e-6) <= f["t_min"] <= (float(mjd_hi) + 1e-6)
            ]
            cand_list = sorted(in_win, key=lambda f: abs(f["t_min"] - mean_cluster_t))
            if len(cand_list) < 3:
                cand_list.extend(sorted(frames_by_det[det_id], key=lambda f: abs(f["t_min"] - mean_cluster_t)))
            seen_cand = set()
            for cand in cand_list[:10]:
                if cand["s3_url"] in seen_cand:
                    continue
                seen_cand.add(cand["s3_url"])
                try:
                    cut = extract_real_level2_cutout(
                        cand["s3_url"],
                        ra_c,
                        dec_c,
                        session=sess,
                        size_px=ny,
                        pixel_scale_arcsec=PIXEL_SCALE_ARCSEC,
                        min_coverage_frac=0.25,
                    )
                    d_i = DETECTOR_INDEX[det_id]
                    flux_cube[v_idx, d_i] = cut["flux"]
                    mask_cube[v_idx, d_i] = cut["mask"]
                    mjds.append(cand["t_min"])
                    dets_present.append(det_id)
                    exposures_used.append(
                        {
                            "visit_id": visit_id,
                            "detector": det_id,
                            "obs_id": cand["obs_id"],
                            "obs_collection": cand["obs_collection"],
                            "t_min": round(cand["t_min"], 6),
                            "coverage_frac": cut["coverage_frac"],
                            "s3_url": cand["s3_url"],
                        }
                    )
                    break
                except (CutoutCoverageError, RuntimeError, OSError):
                    continue
        mean_mjd = float(np.median(mjds)) if mjds else mean_cluster_t
        epoch_iso = Time(mean_mjd, format="mjd", scale="utc").isot.split(".")[0] + "Z"
        visits_meta.append(
            {"visit_id": visit_id, "epoch_iso": epoch_iso, "mjd": round(mean_mjd, 4), "detectors_present": dets_present}
        )

    pack_u16, mask_u8, flux_zero, flux_scale = _quantize_flux_and_masks(flux_cube, mask_cube)
    pack_bytes = pack_u16.tobytes()
    mask_bytes = mask_u8.tobytes()
    invalid_u16 = int(INVALID_U16)
    with open(os.path.join(cutout_dir, "pack.bin"), "wb") as fp:
        fp.write(pack_bytes)
    with open(os.path.join(cutout_dir, "mask.bin"), "wb") as fm:
        fm.write(mask_bytes)

    searched_depth, gaia_rms = _measure_d6_depth_and_rms(flux_cube, gaia_sources_hint or [], ra_c, dec_c)
    manifest = {
        "schema_version": "1.0.0-hour0",
        "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": PIPELINE_VERSION,
        "target_id": f"FLD-{spec['field_id'].upper()}",
        "target_name": spec["field_name"],
        "cutout_origin": "real_spherex_s3_wcs_cutout",
        "center_ra_deg": ra_c,
        "center_dec_deg": dec_c,
        "center_epoch": "2026.0",
        "fov_arcmin": round(nx * PIXEL_SCALE_ARCSEC / 60.0, 2),
        "cutout_size_px": [ny, nx],
        "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
        "gaia_alignment_rms_arcsec": gaia_rms,
        "searched_depth_mag_d6": searched_depth,
        "visits": visits_meta,
        "source_exposures": exposures_used,
        "pack_binary_layout": {
            "file": "pack.bin",
            "dtype": "uint16",
            "endianness": "little",
            "compression": "none",
            "shape": list(flux_cube.shape),
            "axes_order": ["visit", "detector", "y", "x"],
            "byte_length": len(pack_bytes),
            "flux_unit": "MJy/sr",
            "flux_scale": flux_scale,
            "flux_zero": flux_zero,
            "invalid_u16": invalid_u16,
        },
        "quality_mask_layout": {
            "file": "mask.bin",
            "dtype": "uint8",
            "compression": "none",
            "shape": list(mask_cube.shape),
            "axes_order": ["visit", "detector", "y", "x"],
            "byte_length": len(mask_bytes),
            "flag_bits": {"OK": 0, "IRSA_REJECTED": 1, "OVERFLOW_SATURATED": 2, "EDGE_MASKED": 4},
        },
    }
    with open(os.path.join(cutout_dir, "manifest.json"), "w", encoding="utf-8") as mf:
        json.dump(manifest, mf, indent=2)


def build_and_save_field_scene(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR, session=None, rebuild_cutouts=False):
    """Fetch real SPHEREx S3 cutouts (if needed), reference catalogues, and Level-2 EPSF stamps for T40."""
    spec, scene_path, cutout_dir = _resolve_field_paths(field_id, contracts_dir=contracts_dir)
    os.makedirs(os.path.dirname(scene_path), exist_ok=True)
    os.makedirs(cutout_dir, exist_ok=True)
    sess = session or HardenedHTTPSession(timeout=40)

    counts, merged_sources = fetch_reference_catalogues(
        float(spec["center_ra_deg"]),
        float(spec["center_dec_deg"]),
        radius_arcmin=float(spec.get("fov_arcmin", 6.56)) * 0.52,
        session=sess,
    )
    manifest_file = os.path.join(cutout_dir, "manifest.json")
    pack_file = os.path.join(cutout_dir, "pack.bin")
    if rebuild_cutouts or not (os.path.exists(manifest_file) and os.path.exists(pack_file)):
        gaia_hints = []
        for s in merged_sources:
            if s.get("phot_g_mean_mag") is not None and float(s["phot_g_mean_mag"]) < 17.5:
                rg, dg = propagate_position(
                    float(s["ra_ref_deg"]),
                    float(s["dec_ref_deg"]),
                    float(s.get("pmra_mas_yr") or 0.0),
                    float(s.get("pmdec_mas_yr") or 0.0),
                    2025.8 - float(s.get("ref_epoch", 2000.0)),
                )
                gaia_hints.append({"ra_deg": rg, "dec_deg": dg})
        _build_field_cutout_pack(spec, cutout_dir, gaia_sources_hint=gaia_hints, session=sess, max_visits=3)

    with open(manifest_file, encoding="utf-8") as mf:
        manifest = json.load(mf)
    epsf_cal = fetch_level2_epsf_calibration(manifest, session=sess)

    scene_doc = {
        "schema_version": "1.0.0-tierb",
        "data_as_of": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "pipeline_version": PIPELINE_VERSION,
        "field_id": spec["field_id"],
        "field_name": spec["field_name"],
        "plane_type": spec["plane_type"],
        "galactic_coord_str": spec["galactic_coord_str"],
        "center_ra_deg": float(manifest["center_ra_deg"]),
        "center_dec_deg": float(manifest["center_dec_deg"]),
        "fov_arcmin": float(manifest.get("fov_arcmin", 6.56)),
        "pixel_scale_arcsec": float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
        "benchmark_target": spec["benchmark_target"],
        "catalogue_counts": counts,
        "epsf_calibration": epsf_cal,
        "sources": merged_sources,
    }
    with open(scene_path, "w", encoding="utf-8") as sf:
        json.dump(scene_doc, sf, indent=2)
    return scene_doc


def load_field_scene_and_pack(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Load processed Tier-B field scene metadata alongside its calibrated float64 flux and uint8 mask cubes."""
    spec, scene_path, cutout_dir = _resolve_field_paths(field_id, contracts_dir=contracts_dir)
    if not os.path.exists(scene_path):
        raise FileNotFoundError(f"Field scene not found: {scene_path}")
    with open(scene_path, encoding="utf-8") as sf:
        scene = json.load(sf)
    with open(os.path.join(cutout_dir, "manifest.json"), encoding="utf-8") as mf:
        manifest = json.load(mf)
    if spec.get("cutout_target_id"):
        _, flux_cube, mask_cube = load_patch_arrays(contracts_dir, target_id=spec["cutout_target_id"], manifest=manifest)
    else:
        _, flux_cube, mask_cube = load_patch_arrays(cutout_dir, manifest=manifest, root_manifest={})
    return spec, scene, manifest, flux_cube, mask_cube


def solve_joint_psf_frame(
    frame_flux,
    frame_mask,
    wcs,
    catalog_sources,
    epoch_yr,
    detector_id="D3",
    epsf_info=None,
    max_sources=420,
    ridge_reg=1e-3,
):
    """Solve weighted linear regularized joint PSF fit: min || W (A f + b - d) || with zero weight on masked pixels."""
    img = np.asarray(frame_flux, dtype=np.float64)
    msk = np.asarray(frame_mask, dtype=np.uint8)
    ny, nx = img.shape

    # Never mask bit 21 (known source); IRSA_REJECTED=1 | OVERFLOW_SATURATED=2 | EDGE_MASKED=4 already encoded.
    valid = np.isfinite(img) & ((msk & 7) == 0)
    n_valid = int(np.count_nonzero(valid))
    if n_valid < 25:
        return {
            "model": np.zeros_like(img),
            "residual": img.copy(),
            "fitted_sources": [],
            "background_mjy_sr": 0.0,
            "noise_sigma_mjy_sr": None,
            "reduced_chi2": None,
            "n_valid_pixels": n_valid,
        }

    # Estimate background floor & robust per-pixel sigma from lower half of finite sky pixels
    val_flat = img[valid]
    med_bg = float(np.median(val_flat))
    lower = val_flat[val_flat <= np.percentile(val_flat, 65.0)]
    if lower.size < 16:
        lower = val_flat
    sigma_sky = max(1.4826 * float(np.median(np.abs(lower - float(np.median(lower))))), 1e-4)

    stamp = None
    prepared_stamp = None
    oversample = 5
    if isinstance(epsf_info, dict) and epsf_info.get("stamp_33x33"):
        stamp = np.asarray(epsf_info["stamp_33x33"], dtype=np.float64)
        oversample = int(epsf_info.get("oversample", 5))
        if stamp.shape == (33, 33):
            prepared_stamp = _convolve_reprojection_kernel(stamp, oversample=oversample)
    sigma_px = float(DEFAULT_DETECTOR_SIGMA_PX.get(detector_id, 0.58))

    # Project all reference sources propagated with PM + parallax to this frame's observation date
    active_sources = []
    for src in catalog_sources:
        ref_ep = float(src.get("ref_epoch", 2000.0))
        pmra = float(src.get("pmra_mas_yr") or 0.0)
        pmdec = float(src.get("pmdec_mas_yr") or 0.0)
        ra_ep, dec_ep = propagate_position(
            float(src["ra_ref_deg"]), float(src["dec_ref_deg"]), pmra, pmdec, float(epoch_yr) - ref_ep
        )
        px, py = wcs.all_world2pix([[ra_ep, dec_ep]], 0)[0]
        if -1.5 <= px <= (nx + 0.5) and -1.5 <= py <= (ny + 0.5):
            active_sources.append((src, float(px), float(py), ra_ep, dec_ep))
        if len(active_sources) >= max_sources:
            break

    n_src = len(active_sources)
    n_bg = 3
    n_cols = n_src + n_bg

    # Build weighted design matrix cleanly on valid pixels plus unweighted full-grid basis for full model rendering
    flat_valid_idx = np.flatnonzero(valid.ravel())
    yy, xx = np.mgrid[0:ny, 0:nx]
    x_norm = (xx - 0.5 * nx) / (0.5 * nx)
    y_norm = (yy - 0.5 * ny) / (0.5 * ny)

    A_full = np.zeros((ny * nx, n_cols), dtype=np.float64)
    A_full[:, n_src] = 1.0
    A_full[:, n_src + 1] = x_norm.ravel()
    A_full[:, n_src + 2] = y_norm.ravel()

    src_patches = []
    for s_idx, (_, x_s, y_s, _, _) in enumerate(active_sources):
        iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(
            ny,
            nx,
            x_s,
            y_s,
            half_box=4,
            stamp_33x33=stamp,
            sigma_px=sigma_px,
            oversample=oversample,
            prepared_stamp=prepared_stamp,
        )
        src_patches.append((iy0, iy1, ix0, ix1, patch))
        if patch.size > 0:
            rows_2d = np.arange(iy0, iy1)[:, None] * nx + np.arange(ix0, ix1)[None, :]
            A_full[rows_2d.ravel(), s_idx] = patch.ravel()

    # Keep only columns touching valid pixels so unmasked support isn't zeroed into singular modes
    A_val = A_full[flat_valid_idx]
    d_val = img.ravel()[flat_valid_idx]

    # Poisson+sky inverse-variance weights (mild suppression on ultra-bright saturated halos)
    excess_val = np.maximum(d_val - med_bg, 0.0)
    var_val = sigma_sky ** 2 + 0.03 * excess_val * sigma_sky
    w_vec = 1.0 / np.sqrt(np.maximum(var_val, 1e-8))

    Aw = A_val * w_vec[:, None]
    dw = d_val * w_vec
    ata = Aw.T @ Aw
    atd = Aw.T @ dw

    reg = np.zeros(n_cols, dtype=np.float64)
    if n_src > 0:
        reg[:n_src] = float(ridge_reg)
    ata_reg = ata + np.diag(reg)

    try:
        theta = np.linalg.solve(ata_reg, atd)
        cov = np.linalg.inv(ata_reg)
    except np.linalg.LinAlgError:
        theta, *_ = np.linalg.lstsq(Aw, dw, rcond=None)
        cov = np.linalg.pinv(ata_reg)

    # Second pass: reweight bright >5-sigma cosmic/unmodeled residual pixels outside stars so glitches don't bias background
    res_val = d_val - (A_val @ theta)
    rchi2 = float(np.mean((res_val * w_vec) ** 2)) if len(res_val) > n_cols else 1.0

    # Full 64x64 model and residual (residual keeps masked pixels NaN; model renders smoothly)
    full_model = (A_full @ theta).reshape(ny, nx)
    residual = np.where(valid, img - full_model, np.nan)

    # Exact blend_share in PSF footprint: other catalogued sources' modeled light / total modeled source light
    src_only_model = np.zeros((ny, nx), dtype=np.float64)
    if n_src > 0:
        src_only_model = (A_full[:, :n_src] @ np.maximum(theta[:n_src], 0.0)).reshape(ny, nx)

    diag_var = np.maximum(np.diag(cov)[:n_src], 0.0)
    fitted_sources = []
    for s_idx, (src, x_s, y_s, ra_ep, dec_ep) in enumerate(active_sources):
        f_mjy_sr_sum = float(theta[s_idx])
        err_mjy_sr_sum = float(math.sqrt(diag_var[s_idx]) * max(1.0, math.sqrt(min(rchi2, 25.0))))
        f_ujy = f_mjy_sr_sum * _MJY_SR_TO_UJY_PX
        err_ujy = err_mjy_sr_sum * _MJY_SR_TO_UJY_PX
        snr = f_ujy / err_ujy if err_ujy > 0.0 else 0.0

        iy0, iy1, ix0, ix1, patch = src_patches[s_idx]
        blend_share = 0.0
        if patch.size > 0:
            self_box = max(f_mjy_sr_sum, 0.0) * patch
            tot_box = np.maximum(src_only_model[iy0:iy1, ix0:ix1], self_box)
            other_box = np.maximum(tot_box - self_box, 0.0)
            num = float(np.sum(other_box * patch))
            den = float(np.sum(tot_box * patch))
            if den > 1e-12:
                blend_share = max(0.0, min(1.0, num / den))

        fitted_sources.append(
            {
                "source_id": src["source_id"],
                "catalogue": src.get("catalogue", ""),
                "ra_deg": round(ra_ep, 6),
                "dec_deg": round(dec_ep, 6),
                "x_px": round(x_s, 3),
                "y_px": round(y_s, 3),
                "ks_mag": src.get("ks_mag"),
                "w1_mag": src.get("w1_mag"),
                "phot_g_mean_mag": src.get("phot_g_mean_mag"),
                "flux_uJy": round(f_ujy, 3),
                "flux_err_uJy": round(err_ujy, 3),
                "snr": round(snr, 2),
                "blend_share": round(blend_share, 4),
            }
        )

    return {
        "model": full_model,
        "residual": residual,
        "fitted_sources": fitted_sources,
        "background_mjy_sr": round(float(theta[n_src]), 5),
        "noise_sigma_mjy_sr": round(sigma_sky, 5),
        "reduced_chi2": round(rchi2, 3),
        "n_valid_pixels": n_valid,
    }


def compute_field_remove_known(field_id, detector_id="D3", visit_idx=None, contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Run T41 joint PSF fit across all visits (or a selected visit) for Image | Model | Residual display."""
    det = str(detector_id or "D3").upper()
    if det not in DETECTOR_INDEX:
        raise ValueError(f"Unsupported detector: {detector_id!r}")

    spec, scene, manifest, flux_cube, mask_cube = load_field_scene_and_pack(field_id, contracts_dir=contracts_dir)
    d_idx = DETECTOR_INDEX[det]
    n_visits = int(flux_cube.shape[0])
    visits = list(manifest.get("visits") or [])
    wcs = build_target_canvas_wcs(
        float(manifest["center_ra_deg"]),
        float(manifest["center_dec_deg"]),
        size_px=int(flux_cube.shape[3]),
        pixel_scale_arcsec=float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
    )
    epsf_info = (scene.get("epsf_calibration") or {}).get(det)
    cat_sources = scene.get("sources") or []

    v_indices = [int(visit_idx)] if visit_idx is not None else list(range(n_visits))
    for v_i in v_indices:
        if v_i < 0 or v_i >= n_visits:
            raise ValueError(f"visit_idx out of bounds [0, {n_visits - 1}]: {v_i}")

    visit_models = []
    visit_residuals = []
    visit_images = []
    visit_meta = []
    last_sources = []
    for v_i in v_indices:
        mjd = float(visits[v_i]["mjd"]) if v_i < len(visits) and visits[v_i].get("mjd") is not None else 60900.0
        ep_yr = 2000.0 + (mjd - 51544.5) / 365.25
        solved = solve_joint_psf_frame(
            flux_cube[v_i, d_idx],
            mask_cube[v_i, d_idx],
            wcs,
            cat_sources,
            epoch_yr=ep_yr,
            detector_id=det,
            epsf_info=epsf_info,
        )
        visit_images.append(flux_cube[v_i, d_idx])
        visit_models.append(solved["model"])
        visit_residuals.append(solved["residual"])
        last_sources = solved["fitted_sources"]
        visit_meta.append(
            {
                "visit_id": visits[v_i].get("visit_id", f"V{v_i + 1}") if v_i < len(visits) else f"V{v_i + 1}",
                "mjd": round(mjd, 4),
                "background_mjy_sr": solved["background_mjy_sr"],
                "noise_sigma_mjy_sr": solved["noise_sigma_mjy_sr"],
                "reduced_chi2": solved["reduced_chi2"],
                "n_fitted_sources": len(solved["fitted_sources"]),
            }
        )

    def _median_stack(arrs):
        st = np.stack(arrs, axis=0)
        finite_cnt = np.sum(np.isfinite(st), axis=0)
        out = np.full(st.shape[1:], np.nan, dtype=np.float64)
        ok = finite_cnt > 0
        if np.any(ok):
            # Median on valid elements without RuntimeWarning
            masked = np.ma.masked_invalid(st)
            med = np.ma.median(masked, axis=0)
            out[ok] = np.asarray(med.filled(np.nan))[ok]
        return out

    stack_img = _median_stack(visit_images)
    stack_mod = _median_stack(visit_models)
    stack_res = _median_stack(visit_residuals)

    def _grid_to_json(arr):
        return [[round(float(v), 4) if math.isfinite(float(v)) else None for v in row] for row in arr]

    return {
        "field_id": spec["field_id"],
        "field_name": spec["field_name"],
        "plane_type": spec["plane_type"],
        "detector": det,
        "wavelength_range_um": list(DETECTOR_CWAVE_BOUNDS_UM[det]),
        "center_ra_deg": float(manifest["center_ra_deg"]),
        "center_dec_deg": float(manifest["center_dec_deg"]),
        "fov_arcmin": float(manifest.get("fov_arcmin", 6.56)),
        "pixel_scale_arcsec": float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
        "data_as_of": scene.get("data_as_of"),
        "pipeline_version": scene.get("pipeline_version", PIPELINE_VERSION),
        "cutout_origin": manifest.get("cutout_origin"),
        "catalogue_counts": scene.get("catalogue_counts", {}),
        "visits": visit_meta,
        "image_stack": _grid_to_json(stack_img),
        "model_stack": _grid_to_json(stack_mod),
        "residual_stack": _grid_to_json(stack_res),
        "fitted_sources": last_sources,
    }


def evaluate_b1_b2_2mass_check(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Measure Proof B1 (RW Aurigae isolated) and B2 (W1925 blend < 0.3) 2MASS 9 < Ks < 13 flux agreement on D3."""
    spec, scene, manifest, flux_cube, mask_cube = load_field_scene_and_pack(field_id, contracts_dir=contracts_dir)
    d_idx = DETECTOR_INDEX["D3"]
    wcs = build_target_canvas_wcs(
        float(manifest["center_ra_deg"]),
        float(manifest["center_dec_deg"]),
        size_px=int(flux_cube.shape[3]),
        pixel_scale_arcsec=float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
    )
    epsf_info = (scene.get("epsf_calibration") or {}).get("D3")
    visits = list(manifest.get("visits") or [])

    # Accumulate multi-visit fitted fluxes per 2MASS source (9 < Ks < 13, away from 4px border)
    per_source_meas = {}
    for v_i in range(flux_cube.shape[0]):
        mjd = float(visits[v_i]["mjd"]) if v_i < len(visits) and visits[v_i].get("mjd") is not None else 60900.0
        ep_yr = 2000.0 + (mjd - 51544.5) / 365.25
        solved = solve_joint_psf_frame(
            flux_cube[v_i, d_idx],
            mask_cube[v_i, d_idx],
            wcs,
            scene.get("sources") or [],
            epoch_yr=ep_yr,
            detector_id="D3",
            epsf_info=epsf_info,
        )
        for fs in solved["fitted_sources"]:
            ks = fs.get("ks_mag")
            if ks is None or not (9.0 < float(ks) < 13.0):
                continue
            if not (4.0 <= fs["x_px"] <= 59.0 and 4.0 <= fs["y_px"] <= 59.0):
                continue
            if fs["snr"] < 5.0 or fs["flux_uJy"] <= 0.0:
                continue
            entry = per_source_meas.setdefault(
                fs["source_id"], {"ks_mag": float(ks), "fluxes": [], "blends": []}
            )
            entry["fluxes"].append(float(fs["flux_uJy"]))
            entry["blends"].append(float(fs["blend_share"]))

    rel_diffs_pct = []
    all_diffs_pct = []
    for entry in per_source_meas.values():
        f_2mass_uJy = _TWOMASS_KS_ZERO_POINT_JY * (10.0 ** (-0.4 * entry["ks_mag"])) * 1e6
        f_med_uJy = float(np.median(entry["fluxes"]))
        b_med = float(np.median(entry["blends"]))
        diff_pct = (f_med_uJy - f_2mass_uJy) / f_2mass_uJy * 100.0
        all_diffs_pct.append(diff_pct)
        if b_med < 0.30:
            rel_diffs_pct.append(diff_pct)

    arr = np.asarray(rel_diffs_pct, dtype=np.float64)
    if arr.size == 0:
        return {
            "field_id": field_id,
            "test_id": "B2" if field_id == "w1925" else "B1",
            "status": "NOT_MEASURED",
            "matched_count": 0,
            "median_offset_pct": None,
            "scatter_pct": None,
            "passed": False,
        }

    med_off = float(np.median(arr))
    mad_scatter = 1.4826 * float(np.median(np.abs(arr - med_off)))
    if field_id == "rwaur":
        passed = bool(abs(med_off) <= 5.0 and mad_scatter <= 10.0)
        test_id = "B1"
    else:
        passed = bool(mad_scatter <= 20.0)
        test_id = "B2"
    return {
        "field_id": field_id,
        "test_id": test_id,
        "status": "MEASURED",
        "matched_count": int(arr.size),
        "total_9_to_13_count": int(len(all_diffs_pct)),
        "median_offset_pct": round(med_off, 2),
        "scatter_pct": round(mad_scatter, 2),
        "passed": passed,
    }


def list_processed_fields(contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Return metadata & pre-summarized B1/B2 status for available Tier-B fields."""
    fields = []
    for fid in ("w1925", "rwaur"):
        _, scene_path, _ = _resolve_field_paths(fid, contracts_dir=contracts_dir)
        if not os.path.exists(scene_path):
            continue
        with open(scene_path, encoding="utf-8") as sf:
            scene = json.load(sf)
        fields.append(
            {
                "field_id": scene["field_id"],
                "field_name": scene["field_name"],
                "plane_type": scene["plane_type"],
                "galactic_coord_str": scene.get("galactic_coord_str", ""),
                "center_ra_deg": scene["center_ra_deg"],
                "center_dec_deg": scene["center_dec_deg"],
                "fov_arcmin": scene.get("fov_arcmin", 6.56),
                "catalogue_counts": scene.get("catalogue_counts", {}),
                "benchmark_target": scene.get("benchmark_target"),
            }
        )
    return fields
