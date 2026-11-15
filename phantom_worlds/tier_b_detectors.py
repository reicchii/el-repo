"""Tier-B Detectors, Machine Checks, Crosstalk/Ghost Screen, M1 Artefact Classifier & Search/Identity v2 (T44-T45b, M1, T51-T52)."""

import json
import math
import os
import threading

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np
from sklearn.ensemble import RandomForestClassifier

from phantom_worlds.contracts import (
    ALLOWED_CATALOG_HOSTS,
    DEFAULT_CONTRACTS_DIR,
    DETECTOR_INDEX,
    HardenedHTTPSession,
    VALID_DETECTORS,
)
from phantom_worlds.fits_cutout import PIXEL_SCALE_ARCSEC, _MJY_SR_TO_UJY_PX, build_target_canvas_wcs
from phantom_worlds.ml_pipeline import (
    DEFAULT_PIPELINE_MODEL_VERSION,
    compute_molecule_readings,
    load_pipeline_checkpoint,
    train_from_real_dataset,
)
from phantom_worlds.real_ml_data import (
    DEFAULT_ML_DIR,
    build_balanced_e1_templates,
    load_real_training_dataset,
)
from phantom_worlds.tier_b_engine import (
    DEFAULT_DETECTOR_SIGMA_PX,
    DETECTOR_CWAVE_BOUNDS_UM,
    _convolve_reprojection_kernel,
    compute_field_remove_known,
    evaluate_psf_patch,
    list_processed_fields,
    load_field_scene_and_pack,
    solve_joint_psf_frame,
)

# Real H2RG detector crosstalk geometry from S3 dr1/xtalk_class1 & dr1/xtalk_class2 (32 channels x 64 px)
XTALK_CHANNEL_WIDTH_PX = 64
XTALK_MAX_COUPLING = 0.0105

SEARCH_CATEGORY_FILTERS = [
    {"id": "ultracool_dwarf", "label": "Ultracool dwarf"},
    {"id": "yso", "label": "Young star (YSO)"},
    {"id": "star", "label": "Star"},
    {"id": "evolved_giant", "label": "Evolved giant"},
    {"id": "galaxy", "label": "Galaxy"},
    {"id": "agn_quasar", "label": "Active galaxy / QSO"},
    {"id": "methane_dip", "label": "Methane dip (3.3 um)"},
    {"id": "water_ice", "label": "H2O ice (3.05 um)"},
    {"id": "co2_ice", "label": "CO2 ice (4.27 um)"},
    {"id": "co_ice", "label": "CO ice (4.67 um)"},
    {"id": "moving_source", "label": "Moving"},
    {"id": "variable_source", "label": "Variable"},
]

_IMCCE_SKYBOT_URL = "https://ssp.imcce.fr/webservices/skybot/api/conesearch.php"

_CACHE_LOCK = threading.Lock()
_ML_BUILD_LOCK = threading.Lock()
_M1_BUILD_LOCK = threading.Lock()
_FIELD_BUILD_LOCKS = {}
_TRAINED_PIPE_CACHE = {}
_M1_CACHE = {}
_FIELD_ANALYSIS_CACHE = {}


def _get_field_build_lock(cache_key):
    with _CACHE_LOCK:
        lock = _FIELD_BUILD_LOCKS.get(cache_key)
        if lock is None:
            lock = threading.Lock()
            _FIELD_BUILD_LOCKS[cache_key] = lock
        return lock


def get_cached_ml_pipeline(dataset_path=None):
    """Return cached SpectralDiscoveryPipeline + evaluation metadata for single-process reuse."""
    d_path = os.path.abspath(dataset_path or os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz"))
    with _CACHE_LOCK:
        cached = _TRAINED_PIPE_CACHE.get(d_path)
        if cached is not None:
            return cached
    with _ML_BUILD_LOCK:
        with _CACHE_LOCK:
            cached = _TRAINED_PIPE_CACHE.get(d_path)
            if cached is not None:
                return cached
        loaded = load_pipeline_checkpoint(
            d_path,
            model_version=DEFAULT_PIPELINE_MODEL_VERSION,
            max_per_class=14,
            random_state=42,
        )
        if loaded is not None:
            pipe_obj = loaded["pipeline"]
            e1_templates = loaded["e1_templates"]
            load_source = "disk_checkpoint"
        else:
            dataset = load_real_training_dataset(d_path)
            fit_res = train_from_real_dataset(dataset, build_balanced_e1_templates, max_per_class=14, random_state=42)
            pipe_obj = fit_res["pipeline"]
            e1_templates = fit_res["e1_templates"]
            load_source = "live_fit"
        eval_report_path = os.path.join(os.path.dirname(d_path), "evaluation_report.json")
        eval_report = {}
        if os.path.exists(eval_report_path):
            with open(eval_report_path, encoding="utf-8") as ef:
                eval_report = json.load(ef)
        out = {
            "pipeline": pipe_obj,
            "e1_templates": e1_templates,
            "evaluation_report": eval_report,
            "model_version": eval_report.get("model_version", DEFAULT_PIPELINE_MODEL_VERSION),
            "load_source": load_source,
        }
        with _CACHE_LOCK:
            _TRAINED_PIPE_CACHE[d_path] = out
        return out


def _hms_to_deg(hms_str):
    parts = [float(p) for p in str(hms_str).strip().split()]
    if len(parts) != 3:
        return None
    return (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0) * 15.0


def _dms_to_deg(dms_str):
    s = str(dms_str).strip()
    sign = -1.0 if s.startswith("-") else 1.0
    parts = [abs(float(p)) for p in s.replace("+", "").replace("-", "").split()]
    if len(parts) != 3:
        return None
    return sign * (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0)


def query_skybot_conesearch(ra_deg, dec_deg, mjd, radius_deg=0.08, session=None):
    """Query IMCCE SkyBoT for known Solar System objects near (ra_deg, dec_deg) at MJD."""
    jd = float(mjd) + 2400000.5
    own = session is None
    sess = session or HardenedHTTPSession(timeout=20, allowed_hosts=ALLOWED_CATALOG_HOSTS)
    try:
        resp = sess.get(
            _IMCCE_SKYBOT_URL,
            params={
                "-ep": f"{jd:.5f}",
                "-ra": f"{float(ra_deg):.6f}",
                "-dec": f"{float(dec_deg):.6f}",
                "-rd": f"{float(radius_deg):.4f}",
                "-mime": "json",
                "-out": "basic",
            },
            timeout=20,
        )
        if resp.status_code != 200:
            return []
        txt = (resp.text or "").lstrip()
        if not txt.startswith("["):
            return []
        raw_rows = json.loads(txt)
        out = []
        for row in raw_rows:
            if not isinstance(row, dict):
                continue
            r_deg = _hms_to_deg(row.get("RA (hms)"))
            d_deg = _dms_to_deg(row.get("DEC (dms)"))
            if r_deg is None or d_deg is None:
                continue
            out.append(
                {
                    "name": str(row.get("Name") or row.get("Num") or "UnknownSSO"),
                    "num": row.get("Num"),
                    "dyn_class": str(row.get("Class") or ""),
                    "ra_deg": r_deg,
                    "dec_deg": d_deg,
                    "vmag": row.get("VMag (mag)"),
                    "sep_arcsec": row.get("d (arcsec)"),
                    "dra_arcsec_hr": row.get("dRA (arcsec/h)"),
                    "ddec_arcsec_hr": row.get("dDEC (arcsec/h)"),
                }
            )
        return out
    except Exception:
        return []
    finally:
        if own:
            sess.close()


def _sky_sep_arcsec(ra1, dec1, ra2, dec2):
    r1, d1 = math.radians(ra1), math.radians(dec1)
    r2, d2 = math.radians(ra2), math.radians(dec2)
    dra = (r2 - r1 + math.pi) % (2.0 * math.pi) - math.pi
    return math.degrees(math.hypot(dra * math.cos(0.5 * (d1 + d2)), d2 - d1)) * 3600.0


def _grid_stats(grid):
    arr = np.asarray(grid, dtype=np.float64)
    fin = arr[np.isfinite(arr)]
    if fin.size < 16:
        return 0.0, 1e-4
    med = float(np.median(fin))
    mad = float(np.median(np.abs(fin - med)))
    return med, max(1.4826 * mad, 1e-4)


def _evaluate_psf_stamp_corr_and_conc(grid, mask_grid, x_px, y_px, bg_med, sigma_px=0.58):
    """Measure local 5x5 PSF correlation, 1px concentration (cosmic-spike discriminator), elongation & masked fraction."""
    arr = np.asarray(grid, dtype=np.float64)
    msk = np.asarray(mask_grid, dtype=np.uint8)
    ny, nx = arr.shape
    ix, iy = int(round(x_px)), int(round(y_px))
    if not (0 <= ix < nx and 0 <= iy < ny):
        return None

    x0, x1 = max(0, ix - 2), min(nx, ix + 3)
    y0, y1 = max(0, iy - 2), min(ny, iy + 3)
    sub = arr[y0:y1, x0:x1] - bg_med
    sub_msk = msk[y0:y1, x0:x1]
    valid = np.isfinite(sub) & ((sub_msk & 7) == 0)

    x30, x31 = max(0, ix - 1), min(nx, ix + 2)
    y30, y31 = max(0, iy - 1), min(ny, iy + 2)
    m3 = msk[y30:y31, x30:x31]
    frac_masked_3x3 = float(np.mean((m3 & 7) != 0)) if m3.size > 0 else 1.0

    if int(np.count_nonzero(valid)) < 9:
        return None

    ty0, ty1, tx0, tx1, tmpl = evaluate_psf_patch(ny, nx, x_px, y_px, half_box=3, sigma_px=sigma_px)
    sy0, sy1 = y0 - ty0, y1 - ty0
    sx0, sx1 = x0 - tx0, x1 - tx0
    if sy0 < 0 or sx0 < 0 or sy1 > tmpl.shape[0] or sx1 > tmpl.shape[1]:
        return None
    t_sub = tmpl[sy0:sy1, sx0:sx1]
    if t_sub.shape != sub.shape:
        return None

    sv = np.maximum(sub[valid], 0.0)
    tv = t_sub[valid]
    sv_c = sv - float(np.mean(sv))
    tv_c = tv - float(np.mean(tv))
    denom = float(np.linalg.norm(sv_c) * np.linalg.norm(tv_c))
    psf_corr = float(np.dot(sv_c, tv_c) / denom) if denom > 1e-12 else 0.0

    # PSF flux via matched filter
    t_norm2 = max(float(np.dot(tv, tv)), 1e-12)
    flux_sum_mjy = float(np.dot(sub[valid], tv) / t_norm2)

    sub3 = np.maximum(arr[y30:y31, x30:x31] - bg_med, 0.0)
    v3 = np.isfinite(sub3) & ((m3 & 7) == 0)
    sum3 = float(np.sum(sub3[v3])) if np.any(v3) else 0.0
    sum5 = float(np.sum(sv))
    center_val = float(max(0.0, arr[iy, ix] - bg_med)) if (np.isfinite(arr[iy, ix]) and (msk[iy, ix] & 7) == 0) else 0.0
    frac_1px = center_val / max(sum3, 1e-9)
    conc_3x3_5x5 = sum3 / max(sum5, 1e-9)

    # Second moments on positive 5x5 pixels to catch linear cosmic streaks
    yy, xx = np.mgrid[y0:y1, x0:x1]
    pos = np.where(valid & (sub > 0.0), sub, 0.0)
    wt = float(np.sum(pos))
    if wt > 1e-9:
        mx = float(np.sum(pos * xx) / wt)
        my = float(np.sum(pos * yy) / wt)
        vxx = float(np.sum(pos * ((xx - mx) ** 2)) / wt) + 0.05
        vyy = float(np.sum(pos * ((yy - my) ** 2)) / wt) + 0.05
        vxy = float(np.sum(pos * (xx - mx) * (yy - my)) / wt)
        tr = vxx + vyy
        det_term = math.sqrt(max((vxx - vyy) ** 2 + 4.0 * vxy * vxy, 0.0))
        l1 = 0.5 * (tr + det_term)
        l2 = max(0.5 * (tr - det_term), 1e-4)
        elong = math.sqrt(l1 / l2)
    else:
        elong = 1.0

    return {
        "psf_corr": round(psf_corr, 4),
        "frac_1px": round(frac_1px, 4),
        "conc_3x3_5x5": round(conc_3x3_5x5, 4),
        "elongation": round(elong, 3),
        "frac_masked_3x3": round(frac_masked_3x3, 4),
        "flux_mjy_sr_sum": round(flux_sum_mjy, 4),
        "edge_px_dist": int(min(ix, iy, nx - 1 - ix, ny - 1 - iy)),
    }


def evaluate_crosstalk_ghost_risk(
    x_px,
    y_px,
    cand_peak_mjy_sr,
    mask_grid,
    bright_anchors,
):
    """Assess T45b bright-star halo, diffraction spike, H2RG 64-px channel crosstalk & optical ghost risk."""
    ny, nx = mask_grid.shape
    sat_yx = np.argwhere((mask_grid & 2) != 0)

    min_sat_dist = 99.0
    if sat_yx.size > 0:
        dists = np.hypot(sat_yx[:, 1] - x_px, sat_yx[:, 0] - y_px)
        min_sat_dist = float(np.min(dists))

    min_bright_dist = min_sat_dist
    spike_score = 0.0
    ghost_score = 0.0
    reasons = []

    for b_x, b_y, b_peak in bright_anchors:
        dx = float(x_px) - float(b_x)
        dy = float(y_px) - float(b_y)
        dist = math.hypot(dx, dy)
        if dist < 1.2:
            # Coincident with the bright star center itself (not an offset artefact)
            continue
        min_bright_dist = min(min_bright_dist, dist)
        flux_ratio = abs(float(cand_peak_mjy_sr)) / max(float(b_peak), 1e-3)

        # 1. Saturated / very bright star inner halo (PSF wings / spider residuals inside 3 px)
        if dist < 3.0 and flux_ratio < 0.08:
            spike_score = max(spike_score, 1.0 - dist / 3.0)
            reasons.append(f"bright-star halo ({dist:.1f} px from bright/saturated core)")

        # 2. Orthogonal detector diffraction spike axis within 14 px
        if dist <= 14.0 and (abs(dx) <= 1.25 or abs(dy) <= 1.25) and flux_ratio < 0.05:
            spike_score = max(spike_score, 0.85)
            reasons.append("diffraction crosshair axis near bright star")

        # 3. H2RG 32x64-px channel crosstalk offset / mirrored intra-channel Ghost (observed dr1/xtalk_class1/2 <= 1.05% typical, <=3% extreme)
        ch_mod_x = abs(dx) % XTALK_CHANNEL_WIDTH_PX
        same_or_adj_ch = min(ch_mod_x, XTALK_CHANNEL_WIDTH_PX - ch_mod_x) <= 2.0
        ch_mirror_x = abs(((float(b_x) % XTALK_CHANNEL_WIDTH_PX) + (float(x_px) % XTALK_CHANNEL_WIDTH_PX)) - XTALK_CHANNEL_WIDTH_PX) <= 2.2
        if abs(dx) >= 4.0 and abs(dy) <= 2.0 and (same_or_adj_ch or ch_mirror_x) and flux_ratio <= 0.03:
            ghost_score = max(ghost_score, 0.92)
            reasons.append("H2RG 64-px readout channel crosstalk offset")

        # 4. Bright-star optical ghost reflection annulus (4–11 px radial or quadrant-symmetric ghost at <= 2.5% peak)
        sym_dist = math.hypot(float(x_px) - (nx - 1.0 - float(b_x)), float(y_px) - (ny - 1.0 - float(b_y)))
        if ((3.2 <= dist <= 11.5) or sym_dist <= 2.2) and flux_ratio <= 0.025 and b_peak >= 20.0:
            ghost_score = max(ghost_score, 0.88 if sym_dist <= 2.2 else 0.72)
            reasons.append("low-amplitude optical ghost near bright star")

    if min_sat_dist < 2.8:
        spike_score = max(spike_score, 0.90)
        reasons.append(f"adjacent to OVERFLOW_SATURATED pixel ({min_sat_dist:.1f} px)")

    return {
        "min_sat_or_bright_px": round(min_bright_dist, 2),
        "spike_axis_score": round(spike_score, 3),
        "ghost_xtalk_score": round(ghost_score, 3),
        "saturated_halo_clear": spike_score < 0.50 and min_sat_dist >= 2.8,
        "crosstalk_ghost_clear": ghost_score < 0.65,
        "reasons": sorted(set(reasons)),
    }


def evaluate_band_edge_check(flux_by_det, err_by_det, is_variable=False, field_ref_log_steps=None):
    """Conditional T44/B10 spectral edge check across measured DETECTOR_CWAVE_BOUNDS_UM boundaries."""
    pairs = list(zip(VALID_DETECTORS[:-1], VALID_DETECTORS[1:]))
    worst_z = 0.0
    worst_pair = None
    worst_log_step = 0.0

    for d_a, d_b in pairs:
        fa, ea = flux_by_det.get(d_a), err_by_det.get(d_a)
        fb, eb = flux_by_det.get(d_b), err_by_det.get(d_b)
        if fa is None or fb is None or ea is None or eb is None:
            continue
        if fa <= 0.0 or fb <= 0.0 or ea <= 0.0 or eb <= 0.0:
            continue
        if (fa / ea) < 5.0 or (fb / eb) < 5.0:
            continue
        log_step = math.log10(fb / fa)
        # Normal stars can have intrinsic J-H-Ks-W1 slopes; compare against measured field reference spread when present
        ref_list = (field_ref_log_steps or {}).get(f"{d_a}-{d_b}")
        if ref_list and len(ref_list) >= 8:
            med_r = float(np.median(ref_list))
            mad_r = max(1.4826 * float(np.median(np.abs(np.asarray(ref_list) - med_r))), 0.14)
            z_step = abs(log_step - med_r) / mad_r
        else:
            # Propagate relative flux variance cleanly in log10 space
            sig_log = max(0.4343 * math.hypot(ea / fa, eb / fb), 0.12)
            z_step = abs(log_step) / sig_log
        if abs(log_step) > 0.70 and z_step > worst_z:
            worst_z = z_step
            worst_log_step = log_step
            worst_pair = f"{d_a}-{d_b}"

    # Conditional gate for B10 (<= 1% false flags on steady stars): refuse EDGE_DROP_FLAG when explained by variability or small z
    edge_flagged = bool(not is_variable and worst_pair is not None and worst_z > 5.0 and abs(worst_log_step) > 0.75)
    boundary_um = None
    if worst_pair:
        da, db = worst_pair.split("-")
        boundary_um = [DETECTOR_CWAVE_BOUNDS_UM[da][1], DETECTOR_CWAVE_BOUNDS_UM[db][0]]
    return {
        "status": "EDGE_DROP_FLAG" if edge_flagged else ("EXPLAINED_VARIABLE" if (is_variable and worst_pair) else "OK"),
        "flagged": edge_flagged,
        "worst_boundary": worst_pair,
        "overlap_cwave_um": boundary_um,
        "max_z_step": round(worst_z, 2),
        "log10_ratio": round(worst_log_step, 3),
    }


def _build_m1_feature_vector(
    snr,
    psf_corr,
    frac_1px,
    conc_3x3_5x5,
    elongation,
    frac_masked_3x3,
    n_visits_det,
    n_dets_det,
    min_sat_or_bright_px,
    spike_axis_score,
    ghost_xtalk_score,
    edge_px_dist,
):
    return [
        float(min(max(snr, 0.0), 200.0)),
        float(psf_corr),
        float(frac_1px),
        float(conc_3x3_5x5),
        float(min(elongation, 10.0)),
        float(frac_masked_3x3),
        float(n_visits_det),
        float(n_dets_det),
        float(min(min_sat_or_bright_px, 32.0)),
        float(spike_axis_score),
        float(ghost_xtalk_score),
        float(min(edge_px_dist, 32)),
    ]


def train_and_calibrate_m1_classifier(contracts_dir=DEFAULT_CONTRACTS_DIR, force_rebuild=False, random_state=42):
    """Train M1 real-or-artefact RF classifier on real cutouts + injected PSFs vs glitches/halos/ghosts (B6 <=1% FPR)."""
    key = os.path.abspath(contracts_dir)
    if not force_rebuild:
        with _CACHE_LOCK:
            cached = _M1_CACHE.get(key)
            if cached is not None:
                return cached
    with _M1_BUILD_LOCK:
        if not force_rebuild:
            with _CACHE_LOCK:
                cached = _M1_CACHE.get(key)
                if cached is not None:
                    return cached
        out = _train_and_calibrate_m1_uncached(contracts_dir=contracts_dir, random_state=random_state)
        with _CACHE_LOCK:
            _M1_CACHE[key] = out
        return out


def _train_and_calibrate_m1_uncached(contracts_dir=DEFAULT_CONTRACTS_DIR, random_state=42):
    """Fit and spatially calibrate the M1 real-or-artefact RF classifier without cache locking."""

    rng = np.random.default_rng(random_state)
    feats, labels, regions = [], [], []
    ny = nx = 64

    for fid in ("w1925", "rwaur"):
        try:
            spec, scene, manifest, flux_cube, mask_cube = load_field_scene_and_pack(fid, contracts_dir=contracts_dir)
        except FileNotFoundError:
            continue
        wcs = build_target_canvas_wcs(
            float(manifest["center_ra_deg"]),
            float(manifest["center_dec_deg"]),
            size_px=nx,
            pixel_scale_arcsec=float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
        )
        d3_idx = DETECTOR_INDEX["D3"]
        d3_img = np.asarray(np.ma.median(np.ma.masked_invalid(flux_cube[:, d3_idx]), axis=0).filled(np.nan))
        d3_msk = np.bitwise_or.reduce(mask_cube[:, d3_idx], axis=0)
        med_bg, sig_sky = _grid_stats(d3_img)
        epsf = (scene.get("epsf_calibration") or {}).get("D3")
        stamp = np.asarray(epsf["stamp_33x33"], dtype=np.float64) if (epsf and epsf.get("stamp_33x33")) else None
        prep = _convolve_reprojection_kernel(stamp, oversample=5) if stamp is not None else None

        # Collect bright/saturated anchors on this cutout
        bright_anchors = []
        solved_v0 = solve_joint_psf_frame(
            flux_cube[0, d3_idx], mask_cube[0, d3_idx], wcs, scene.get("sources") or [], 2025.8, "D3", epsf_info=epsf
        )
        for s in solved_v0["fitted_sources"]:
            if (s.get("ks_mag") is not None and float(s["ks_mag"]) < 10.5) or s["flux_uJy"] > 50000.0:
                bx = float(s["x_px"])
                by = float(s["y_px"])
                ix, iy = int(round(bx)), int(round(by))
                if 0 <= ix < nx and 0 <= iy < ny:
                    pk = float(d3_img[iy, ix]) if np.isfinite(d3_img[iy, ix]) else 20.0
                    bright_anchors.append((bx, by, max(pk, 10.0)))

        # Positives (y=1): held-out + real clean stars & injected PSF sources on real cutout noise background
        resid0 = solved_v0["residual"]
        med_res0, _ = _grid_stats(resid0)
        clean_sites = np.argwhere(
            np.isfinite(resid0) & ((d3_msk & 7) == 0) & (np.abs(resid0 - med_res0) < 3.0 * sig_sky)
        )
        # Keep strictly 5 <= y, x <= 58 for clean injection
        clean_sites = clean_sites[(clean_sites[:, 0] >= 5) & (clean_sites[:, 0] <= 58) & (clean_sites[:, 1] >= 5) & (clean_sites[:, 1] <= 58)]
        if len(clean_sites) > 90:
            pick = rng.choice(len(clean_sites), size=90, replace=False)
            inj_coords = clean_sites[pick]
        else:
            inj_coords = clean_sites

        for cy, cx in inj_coords:
            xp = float(cx) + float(rng.uniform(-0.4, 0.4))
            yp = float(cy) + float(rng.uniform(-0.4, 0.4))
            is_mover = bool(rng.random() < 0.25)
            snr_inj = float(rng.uniform(5.8, 35.0))
            peak_amp = snr_inj * sig_sky
            iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(
                ny, nx, xp, yp, half_box=3, stamp_33x33=stamp, sigma_px=DEFAULT_DETECTOR_SIGMA_PX["D3"], prepared_stamp=prep
            )
            if patch.size == 0 or np.max(patch) <= 0.0:
                continue
            canvas = d3_img.copy()
            flux_tot = peak_amp / float(np.max(patch))
            canvas[iy0:iy1, ix0:ix1] += flux_tot * patch
            info = _evaluate_psf_stamp_corr_and_conc(canvas, d3_msk, xp, yp, med_bg)
            if info is None:
                continue
            cg = evaluate_crosstalk_ghost_risk(xp, yp, peak_amp, d3_msk, bright_anchors)
            if not cg["saturated_halo_clear"] or not cg["crosstalk_ghost_clear"]:
                continue
            feats.append(
                _build_m1_feature_vector(
                    snr=snr_inj,
                    psf_corr=info["psf_corr"],
                    frac_1px=info["frac_1px"],
                    conc_3x3_5x5=info["conc_3x3_5x5"],
                    elongation=info["elongation"],
                    frac_masked_3x3=info["frac_masked_3x3"],
                    n_visits_det=(1 if is_mover else int(rng.integers(2, 4))),
                    n_dets_det=(int(rng.integers(2, 5)) if is_mover else int(rng.integers(2, 7))),
                    min_sat_or_bright_px=cg["min_sat_or_bright_px"],
                    spike_axis_score=cg["spike_axis_score"],
                    ghost_xtalk_score=cg["ghost_xtalk_score"],
                    edge_px_dist=info["edge_px_dist"],
                )
            )
            labels.append(1)
            regions.append("left" if xp < 32.0 else "right")

        # Negatives (y=0): cosmic single-pixel spikes, linear cosmic streaks, masked edge pixels, halos, and H2RG crosstalk/ghosts
        for idx_n in range(95):
            xp = float(rng.uniform(4.0, 59.0))
            yp = float(rng.uniform(4.0, 59.0))
            kind = idx_n % 5
            canvas = np.full((ny, nx), med_bg, dtype=np.float64) + rng.normal(0.0, sig_sky, size=(ny, nx))
            msk_syn = d3_msk.copy()
            amp = float(rng.uniform(6.0, 45.0)) * sig_sky
            nv, nd = 1, 1
            if kind == 0:
                # 1-px hot pixel / unflagged single-frame cosmic hit
                canvas[int(round(yp)), int(round(xp))] += amp
            elif kind == 1:
                # Linear cosmic-ray streak across 4 pixels
                for k in range(-1, 3):
                    canvas[int(round(yp)), min(nx - 1, max(0, int(round(xp)) + k))] += amp * (0.9 - 0.1 * abs(k))
                nv = 1 if rng.random() < 0.85 else 2
            elif kind == 2:
                # Cutout border / heavily IRSA-masked defect
                xp = float(rng.choice([1.0, 62.0]))
                yp = float(rng.uniform(3.0, 60.0))
                msk_syn[int(yp) - 1 : int(yp) + 2, max(0, int(xp) - 1) : min(nx, int(xp) + 2)] |= 1
                canvas[int(round(yp)), int(round(xp))] += amp
                nv = 2
            elif kind == 3 and bright_anchors:
                # Diffraction halo around a real saturated / bright star
                bx, by, b_pk = bright_anchors[idx_n % len(bright_anchors)]
                ang = float(rng.choice([0.0, 0.5 * math.pi, math.pi]))
                dist_b = float(rng.uniform(1.6, 2.7))
                xp = float(np.clip(bx + dist_b * math.cos(ang), 3.0, 60.0))
                yp = float(np.clip(by + dist_b * math.sin(ang), 3.0, 60.0))
                iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(ny, nx, xp, yp, half_box=2, sigma_px=0.65)
                if patch.size > 0:
                    canvas[iy0:iy1, ix0:ix1] += (min(amp, 0.03 * b_pk) / max(float(np.max(patch)), 1e-6)) * patch
                nv, nd = 2, 2
            else:
                # Bright-star H2RG 64-px channel ghost / optical ghost mirror
                bx, by, b_pk = bright_anchors[idx_n % max(len(bright_anchors), 1)] if bright_anchors else (20.0, 20.0, 60.0)
                if bright_anchors:
                    xp = float(np.clip((nx - 1.0 - bx) + rng.uniform(-0.8, 0.8), 4.0, 59.0))
                    yp = float(np.clip((ny - 1.0 - by) + rng.uniform(-0.8, 0.8), 4.0, 59.0))
                    amp = min(amp, 0.02 * max(b_pk, 30.0))
                iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(ny, nx, xp, yp, half_box=2, sigma_px=0.7)
                if patch.size > 0:
                    canvas[iy0:iy1, ix0:ix1] += (amp / max(float(np.max(patch)), 1e-6)) * patch
                nv, nd = 2, 2

            info = _evaluate_psf_stamp_corr_and_conc(canvas, msk_syn, xp, yp, med_bg)
            if info is None:
                continue
            cg = evaluate_crosstalk_ghost_risk(xp, yp, amp, msk_syn, bright_anchors)
            feats.append(
                _build_m1_feature_vector(
                    snr=amp / sig_sky,
                    psf_corr=info["psf_corr"],
                    frac_1px=info["frac_1px"],
                    conc_3x3_5x5=info["conc_3x3_5x5"],
                    elongation=info["elongation"],
                    frac_masked_3x3=info["frac_masked_3x3"],
                    n_visits_det=nv,
                    n_dets_det=nd,
                    min_sat_or_bright_px=cg["min_sat_or_bright_px"],
                    spike_axis_score=cg["spike_axis_score"],
                    ghost_xtalk_score=cg["ghost_xtalk_score"],
                    edge_px_dist=info["edge_px_dist"],
                )
            )
            labels.append(0)
            regions.append("left" if xp < 32.0 else "right")

    X = np.asarray(feats, dtype=np.float64)
    y = np.asarray(labels, dtype=np.int32)
    reg_arr = np.asarray(regions)
    if X.ndim != 2 or X.shape[0] < 4 or np.unique(y).size < 2:
        out = {
            "model": None,
            "p_threshold_1pct_fpr": 0.75,
            "val_false_pass_rate": None,
            "b6_recall_at_1pct_fpr": None,
            "n_train": 0,
            "n_val": 0,
            "n_val_pos": 0,
            "n_val_neg": 0,
            "status": "NOT_MEASURED",
            "model_version": "m1-rf-tierb-v1",
        }
        return out
    # Strict spatial left/right split so threshold calibration & recall never leak validation samples
    tr_idx = np.flatnonzero(reg_arr == "left")
    va_idx = np.flatnonzero(reg_arr == "right")
    if tr_idx.size < 20 or va_idx.size < 20:
        half = len(y) // 2
        tr_idx = np.arange(0, half)
        va_idx = np.arange(half, len(y))

    clf = RandomForestClassifier(n_estimators=120, max_depth=8, min_samples_leaf=2, random_state=random_state)
    clf.fit(X[tr_idx], y[tr_idx])
    va_probs = clf.predict_proba(X[va_idx])[:, 1]
    va_neg = va_probs[y[va_idx] == 0]
    va_pos = va_probs[y[va_idx] == 1]

    # Select threshold enforcing false-pass rate <= 1.0% on held-out spatial validation artefacts
    if va_neg.size > 0:
        sorted_neg = np.sort(va_neg)[::-1]
        max_fp = int(math.floor(0.01 * va_neg.size))
        if max_fp <= 0:
            p_thresh = float(min(0.99, float(sorted_neg[0]) + 1e-4))
        else:
            p_thresh = float(sorted_neg[max_fp])
        p_thresh = max(0.50, min(0.99, p_thresh))
        val_fpr = float(np.mean(va_neg >= p_thresh))
    else:
        p_thresh = 0.75
        val_fpr = 0.0

    b6_recall = float(np.mean(va_pos >= p_thresh)) if va_pos.size > 0 else 0.0

    # Refit final production M1 forest on full dataset using calibrated threshold
    prod_clf = RandomForestClassifier(n_estimators=160, max_depth=8, min_samples_leaf=2, random_state=random_state)
    prod_clf.fit(X, y)

    out = {
        "model": prod_clf,
        "p_threshold_1pct_fpr": round(p_thresh, 4),
        "val_false_pass_rate": round(val_fpr, 4),
        "b6_recall_at_1pct_fpr": round(b6_recall, 4),
        "n_train": int(tr_idx.size),
        "n_val": int(va_idx.size),
        "n_val_pos": int(va_pos.size),
        "n_val_neg": int(va_neg.size),
        "model_version": "m1-rf-tierb-v1",
    }
    return out


def score_m1_candidate(m1_bundle, feat_vec, checks):
    """Score real-or-artefact probability, suppressing any explicit optical ghost / crosstalk / saturated halo fail."""
    if m1_bundle.get("model") is None:
        return 0.0, False
    p_raw = float(m1_bundle["model"].predict_proba(np.asarray([feat_vec], dtype=np.float64))[0, 1])
    if not checks["crosstalk_ghost_clear"] or not checks["saturated_halo_clear"] or not checks["mask_bit_clean"]:
        p_eff = min(p_raw, 0.15)
    else:
        p_eff = p_raw
    passed = bool(p_eff >= float(m1_bundle["p_threshold_1pct_fpr"]))
    return round(p_eff, 4), passed


def detect_moving_candidates(flux_cube, mask_cube, model_cube, wcs, visits, detector_id="D3", bright_anchors=()):
    """T44 moving-source detector: find PSF residual peaks absent at that pixel in other epochs and link tracks."""
    d_idx = DETECTOR_INDEX[detector_id]
    n_v = int(flux_cube.shape[0])
    if n_v < 2:
        return []
    ny, nx = flux_cube.shape[2], flux_cube.shape[3]
    res_visits = [
        np.where(np.isfinite(flux_cube[v, d_idx]) & ((mask_cube[v, d_idx] & 7) == 0), flux_cube[v, d_idx] - model_cube[v], np.nan)
        for v in range(n_v)
    ]
    sat_yx = np.argwhere((np.bitwise_or.reduce(mask_cube[:, d_idx], axis=0) & 2) != 0)

    # Collect transient peaks per visit (present in visit v, absent at same pixel in >=1 other visit)
    ep_peaks = []
    for v_i in range(n_v):
        rv = res_visits[v_i]
        med_v, sig_v = _grid_stats(rv)
        other_vals = [res_visits[u] for u in range(n_v) if u != v_i]
        other_med = np.asarray(np.ma.median(np.ma.masked_invalid(np.stack(other_vals, axis=0)), axis=0).filled(np.nan))
        other_med_val, other_sig = _grid_stats(other_med)
        peak_map = np.where(np.isfinite(rv), (rv - med_v) / sig_v, -999.0)
        cand_yx = np.argwhere(peak_map > 4.8)
        visited = np.zeros((ny, nx), dtype=bool)
        for cy, cx in cand_yx[np.argsort(peak_map[cand_yx[:, 0], cand_yx[:, 1]])[::-1]]:
            if visited[cy, cx] or not (2 <= cy < ny - 2 and 2 <= cx < nx - 2):
                continue
            visited[max(0, cy - 2) : min(ny, cy + 3), max(0, cx - 2) : min(nx, cx + 3)] = True
            if sat_yx.size > 0 and float(np.min(np.hypot(sat_yx[:, 1] - cx, sat_yx[:, 0] - cy))) < 2.5:
                continue
            if any(math.hypot(cx - bx, cy - by) <= 2.2 for bx, by, _ in bright_anchors):
                continue
            if np.isfinite(other_med[cy, cx]) and abs(other_med[cy, cx] - other_med_val) > 2.8 * other_sig:
                # Persistent leftover at the same pixel across visits (handled by leftover detector, not mover)
                continue
            info = _evaluate_psf_stamp_corr_and_conc(rv, mask_cube[v_i, d_idx], float(cx), float(cy), med_v)
            if not info or info["psf_corr"] < 0.45 or info["frac_1px"] > 0.85 or info["flux_mjy_sr_sum"] <= 0.0:
                continue
            ep_peaks.append(
                {
                    "visit_idx": v_i,
                    "mjd": float(visits[v_i].get("mjd", 60900.0)) if v_i < len(visits) else 60900.0 + v_i,
                    "x_px": float(cx),
                    "y_px": float(cy),
                    "snr": float(peak_map[cy, cx]),
                    "flux_mjy_sr_sum": info["flux_mjy_sr_sum"],
                    "info": info,
                }
            )

    # Link single-epoch transients across visits and deduplicate near-identical endpoints
    used = set()
    tracks = []
    emitted_xy = []
    for i, pi in enumerate(ep_peaks):
        if i in used:
            continue
        best_j = None
        best_score = -1.0
        for j, pj in enumerate(ep_peaks):
            if j == i or j in used or pj["visit_idx"] <= pi["visit_idx"]:
                continue
            dt_hr = (pj["mjd"] - pi["mjd"]) * 24.0
            dist_px = math.hypot(pj["x_px"] - pi["x_px"], pj["y_px"] - pi["y_px"])
            if dt_hr <= 0.05 or dist_px < 0.5:
                continue
            speed_arcsec_hr = dist_px * PIXEL_SCALE_ARCSEC / dt_hr
            # Accept realistic main-belt/TNO/PM rates (0.02"/hr to 120"/hr; also multi-month shifts in cutout)
            if 0.02 <= speed_arcsec_hr <= 120.0 or (dt_hr <= 48.0 and 1.0 <= dist_px <= 45.0):
                sc = pi["snr"] + pj["snr"]
                if sc > best_score:
                    best_score = sc
                    best_j = j

        if best_j is not None:
            pj = ep_peaks[best_j]
            used.add(i)
            used.add(best_j)
            if any(math.hypot(pj["x_px"] - ex, pj["y_px"] - ey) <= 2.5 for ex, ey in emitted_xy):
                continue
            emitted_xy.append((pj["x_px"], pj["y_px"]))
            ra0, dec0 = wcs.all_pix2world([[pi["x_px"], pi["y_px"]]], 0)[0]
            ra1, dec1 = wcs.all_pix2world([[pj["x_px"], pj["y_px"]]], 0)[0]
            dt_hr = max((pj["mjd"] - pi["mjd"]) * 24.0, 0.1)
            tracks.append(
                {
                    "linked_visits": [pi["visit_idx"], pj["visit_idx"]],
                    "x_px": pj["x_px"],
                    "y_px": pj["y_px"],
                    "ra_deg": float(ra1),
                    "dec_deg": float(dec1),
                    "prev_ra_deg": float(ra0),
                    "prev_dec_deg": float(dec0),
                    "snr": round(max(pi["snr"], pj["snr"]), 2),
                    "flux_uJy": round(pj["flux_mjy_sr_sum"] * _MJY_SR_TO_UJY_PX, 2),
                    "rate_arcsec_hr": round(_sky_sep_arcsec(ra0, dec0, ra1, dec1) / dt_hr, 3),
                    "mjd": pj["mjd"],
                    "info": pj["info"],
                }
            )
    return tracks


def _collect_field_6band_and_residuals(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Run joint-PSF decomposition across D1..D6 for all visits of field_id cleanly via solve_joint_psf_frame."""
    spec, scene, manifest, flux_cube, mask_cube = load_field_scene_and_pack(field_id, contracts_dir=contracts_dir)
    ny, nx = flux_cube.shape[2], flux_cube.shape[3]
    wcs = build_target_canvas_wcs(
        float(manifest["center_ra_deg"]),
        float(manifest["center_dec_deg"]),
        size_px=nx,
        pixel_scale_arcsec=float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC)),
    )
    visits = list(manifest.get("visits") or [])
    n_v = int(flux_cube.shape[0])
    cat_sources = scene.get("sources") or []
    src_by_id = {s["source_id"]: s for s in cat_sources}

    per_src = {}
    det_stacks = {}
    bright_anchors_by_det = {}

    for det_id in VALID_DETECTORS:
        d_idx = DETECTOR_INDEX[det_id]
        epsf_info = (scene.get("epsf_calibration") or {}).get(det_id)
        mod_visits, res_visits = [], []
        anchors = []
        for v_i in range(n_v):
            mjd = float(visits[v_i]["mjd"]) if v_i < len(visits) and visits[v_i].get("mjd") is not None else 60900.0
            ep_yr = 2000.0 + (mjd - 51544.5) / 365.25
            solved = solve_joint_psf_frame(
                flux_cube[v_i, d_idx], mask_cube[v_i, d_idx], wcs, cat_sources, ep_yr, det_id, epsf_info=epsf_info
            )
            mod_visits.append(solved["model"])
            res_visits.append(solved["residual"])
            for fs in solved["fitted_sources"]:
                entry = per_src.setdefault(
                    fs["source_id"],
                    {
                        "meta": src_by_id.get(fs["source_id"], {}),
                        "ra_deg": fs["ra_deg"],
                        "dec_deg": fs["dec_deg"],
                        "x_px": fs["x_px"],
                        "y_px": fs["y_px"],
                        "by_det": {},
                    },
                )
                det_map = entry["by_det"].setdefault(det_id, [])
                det_map.append(fs)
                if v_i == 0 and ((fs.get("ks_mag") is not None and float(fs["ks_mag"]) < 10.5) or fs["flux_uJy"] > 50000.0):
                    ix, iy = int(round(fs["x_px"])), int(round(fs["y_px"]))
                    pk = float(flux_cube[0, d_idx, iy, ix]) if (0 <= ix < nx and 0 <= iy < ny and np.isfinite(flux_cube[0, d_idx, iy, ix])) else 20.0
                    anchors.append((fs["x_px"], fs["y_px"], max(pk, 10.0)))

        res_arr = np.ma.masked_invalid(np.stack(res_visits, axis=0))
        img_arr = np.ma.masked_invalid(flux_cube[:, d_idx])
        mod_arr = np.stack(mod_visits, axis=0)
        det_stacks[det_id] = {
            "res_visits": res_visits,
            "mod_visits": mod_visits,
            "res_stack": np.asarray(np.ma.median(res_arr, axis=0).filled(np.nan)),
            "img_stack": np.asarray(np.ma.median(img_arr, axis=0).filled(np.nan)),
            "mod_stack": np.median(mod_arr, axis=0),
            "mask_or": np.bitwise_or.reduce(mask_cube[:, d_idx], axis=0),
            "cwave_um": float((epsf_info or {}).get("cwave_um") or sum(DETECTOR_CWAVE_BOUNDS_UM[det_id]) * 0.5),
        }
        bright_anchors_by_det[det_id] = anchors

    return {
        "spec": spec,
        "scene": scene,
        "manifest": manifest,
        "flux_cube": flux_cube,
        "mask_cube": mask_cube,
        "wcs": wcs,
        "visits": visits,
        "per_src": per_src,
        "det_stacks": det_stacks,
        "bright_anchors": bright_anchors_by_det,
    }


def analyze_field_candidates(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR, include_skybot=False):
    """Run T44 detectors, T45b machine/crosstalk checks, M1 p_real, and T45 Identity v2 for one field."""
    cache_key = (os.path.abspath(contracts_dir), field_id, bool(include_skybot))
    with _CACHE_LOCK:
        cached = _FIELD_ANALYSIS_CACHE.get(cache_key)
        if cached is not None:
            return cached
    field_lock = _get_field_build_lock(cache_key)
    with field_lock:
        with _CACHE_LOCK:
            cached = _FIELD_ANALYSIS_CACHE.get(cache_key)
            if cached is not None:
                return cached
        result = _analyze_field_candidates_uncached(
            field_id=field_id,
            contracts_dir=contracts_dir,
            include_skybot=include_skybot,
        )
        with _CACHE_LOCK:
            _FIELD_ANALYSIS_CACHE[cache_key] = result
        return result


def _analyze_field_candidates_uncached(field_id, contracts_dir=DEFAULT_CONTRACTS_DIR, include_skybot=False):
    """Compute T44 detectors, T45b machine/crosstalk checks, M1 p_real, and Identity v2 for one field."""

    ml_bundle = get_cached_ml_pipeline()
    pipe = ml_bundle["pipeline"]
    wl_grid = np.asarray(pipe.wavelengths, dtype=np.float64)
    bw_grid = np.full_like(wl_grid, 0.04)
    m1_bundle = train_and_calibrate_m1_classifier(contracts_dir=contracts_dir)

    raw = _collect_field_6band_and_residuals(field_id, contracts_dir=contracts_dir)
    spec = raw["spec"]
    scene = raw["scene"]
    manifest = raw["manifest"]
    wcs = raw["wcs"]
    visits = raw["visits"]
    det_stacks = raw["det_stacks"]
    bright_anchors_d3 = raw["bright_anchors"]["D3"]

    skybot_rows = []
    if include_skybot and visits:
        for v in visits:
            skybot_rows.extend(
                query_skybot_conesearch(float(manifest["center_ra_deg"]), float(manifest["center_dec_deg"]), v["mjd"], radius_deg=0.07)
            )

    # First pass across steady bright catalogued stars to establish B10 empirical adjacent-band step scatter
    ref_steps = {f"{da}-{db}": [] for da, db in zip(VALID_DETECTORS[:-1], VALID_DETECTORS[1:])}
    src_summaries = []
    for sid, sdata in raw["per_src"].items():
        flux_by_det, err_by_det, snr_by_det, blends, var_chi2_list = {}, {}, {}, [], []
        n_clean_dets = 0
        max_visits_clean = 0
        for det_id in VALID_DETECTORS:
            obs_list = sdata["by_det"].get(det_id) or []
            good = [o for o in obs_list if o["snr"] > 0 and o["flux_err_uJy"] > 0]
            if not good:
                continue
            fls = np.asarray([o["flux_uJy"] for o in good], dtype=np.float64)
            ers = np.asarray([max(o["flux_err_uJy"], 1e-3) for o in good], dtype=np.float64)
            blends.extend([float(o["blend_share"]) for o in good])
            snr_by_det[det_id] = float(np.median([o["snr"] for o in good]))
            inv_v = 1.0 / (ers ** 2)
            w_mean = float(np.sum(fls * inv_v) / max(float(np.sum(inv_v)), 1e-12))
            w_err = 1.0 / math.sqrt(max(float(np.sum(inv_v)), 1e-12))
            flux_by_det[det_id] = w_mean
            err_by_det[det_id] = w_err
            if w_mean > 0 and (w_mean / w_err) >= 4.0:
                n_clean_dets += 1
            max_visits_clean = max(max_visits_clean, len(good))
            if len(good) >= 2 and float(np.min([o["snr"] for o in good])) >= 5.0 and float(np.median([o["blend_share"] for o in good])) < 0.45:
                chi2_r = float(np.sum(((fls - w_mean) / ers) ** 2)) / max(len(good) - 1, 1)
                amp_ratio = float(np.max(fls) / max(float(np.min(fls)), 1e-3))
                var_chi2_list.append((chi2_r, amp_ratio))

        blend_med = float(np.median(blends)) if blends else 0.0
        max_chi2 = max([c for c, _ in var_chi2_list], default=0.0)
        max_amp = max([a for _, a in var_chi2_list], default=1.0)
        is_var = bool(max_chi2 >= 5.0 and max_amp >= 1.15)
        max_snr = max(snr_by_det.values(), default=0.0)

        if not is_var and blend_med < 0.30 and max_snr >= 8.0:
            for da, db in zip(VALID_DETECTORS[:-1], VALID_DETECTORS[1:]):
                fa, fb = flux_by_det.get(da), flux_by_det.get(db)
                if fa and fb and fa > 0 and fb > 0 and snr_by_det.get(da, 0) >= 5.0 and snr_by_det.get(db, 0) >= 5.0:
                    ref_steps[f"{da}-{db}"].append(math.log10(fb / fa))

        src_summaries.append(
            {
                "source_id": sid,
                "sdata": sdata,
                "flux_by_det": flux_by_det,
                "err_by_det": err_by_det,
                "snr_by_det": snr_by_det,
                "blend_med": blend_med,
                "max_chi2": max_chi2,
                "is_variable": is_var,
                "max_snr": max_snr,
                "n_clean_dets": n_clean_dets,
                "max_visits_clean": max_visits_clean,
            }
        )

    records = []
    d3_st = det_stacks["D3"]
    bg_d3, sig_d3 = _grid_stats(d3_st["img_stack"])

    # Score catalogued sources (T45 Identity v2 + Edge check + M1)
    for item in src_summaries:
        if item["max_snr"] < 4.5 and not item["is_variable"]:
            continue
        meta = item["sdata"]["meta"]
        xp = float(item["sdata"]["x_px"])
        yp = float(item["sdata"]["y_px"])
        ra_d = float(item["sdata"]["ra_deg"])
        dec_d = float(item["sdata"]["dec_deg"])
        edge_info = evaluate_band_edge_check(
            item["flux_by_det"], item["err_by_det"], is_variable=item["is_variable"], field_ref_log_steps=ref_steps
        )
        plx = meta.get("parallax_mas")
        plx_snr = max(0.0, float(plx) / 0.2) if (plx is not None and float(plx) > 0) else 0.0

        # Populate ONLY the measured D1..D6 wavelengths onto the 102-channel grid; unmeasured remain NaN (no hallucinated bands)
        fl_102 = np.full(len(wl_grid), np.nan, dtype=np.float64)
        fe_102 = np.full(len(wl_grid), np.nan, dtype=np.float64)
        deciding_bands = []
        measured_6 = []
        for det_id in VALID_DETECTORS:
            cw = det_stacks[det_id]["cwave_um"]
            fv = item["flux_by_det"].get(det_id)
            ev = item["err_by_det"].get(det_id)
            is_meas = fv is not None and ev is not None and fv > 0 and math.isfinite(fv)
            deciding_bands.append(
                {
                    "detector": det_id,
                    "cwave_um": round(cw, 4),
                    "status": "MEASURED" if is_meas else "NOT_MEASURED",
                    "flux_uJy": round(float(fv), 2) if fv is not None and math.isfinite(fv) else None,
                    "flux_err_uJy": round(float(ev), 2) if ev is not None and math.isfinite(ev) else None,
                }
            )
            if is_meas:
                idx = int(np.argmin(np.abs(wl_grid - cw)))
                fl_102[idx] = float(fv)
                fe_102[idx] = float(ev)
                measured_6.append({"band": det_id, "wavelength_um": round(cw, 4), "flux_uJy": round(float(fv), 2), "err_uJy": round(float(ev), 2)})

        # Check D3 image stamp quality for M1 + crosstalk/ghost checks
        stamp_info = _evaluate_psf_stamp_corr_and_conc(d3_st["img_stack"], d3_st["mask_or"], xp, yp, bg_d3)
        ix, iy = int(round(xp)), int(round(yp))
        pk_d3 = float(d3_st["img_stack"][iy, ix]) if (0 <= ix < 64 and 0 <= iy < 64 and np.isfinite(d3_st["img_stack"][iy, ix])) else item["max_snr"] * sig_d3
        cg = evaluate_crosstalk_ghost_risk(xp, yp, pk_d3, d3_st["mask_or"], bright_anchors_d3)
        checks = {
            "psflike_shape": bool(stamp_info and stamp_info["psf_corr"] >= 0.45 and stamp_info["frac_1px"] <= 0.85),
            "multi_exposure_repeat": bool(item["max_visits_clean"] >= 2 or item["n_clean_dets"] >= 2),
            "saturated_halo_clear": cg["saturated_halo_clear"],
            "crosstalk_ghost_clear": cg["crosstalk_ghost_clear"],
            "mask_bit_clean": bool(stamp_info is None or stamp_info["frac_masked_3x3"] < 0.35),
            "catalogue_skybot_status": f"Matches {meta.get('catalogue', 'Catalogue')}",
        }
        fvec = _build_m1_feature_vector(
            snr=item["max_snr"],
            psf_corr=(stamp_info["psf_corr"] if stamp_info else 0.7),
            frac_1px=(stamp_info["frac_1px"] if stamp_info else 0.4),
            conc_3x3_5x5=(stamp_info["conc_3x3_5x5"] if stamp_info else 0.75),
            elongation=(stamp_info["elongation"] if stamp_info else 1.2),
            frac_masked_3x3=(stamp_info["frac_masked_3x3"] if stamp_info else 0.0),
            n_visits_det=item["max_visits_clean"],
            n_dets_det=item["n_clean_dets"],
            min_sat_or_bright_px=cg["min_sat_or_bright_px"],
            spike_axis_score=cg["spike_axis_score"],
            ghost_xtalk_score=cg["ghost_xtalk_score"],
            edge_px_dist=(stamp_info["edge_px_dist"] if stamp_info else 10),
        )
        p_real, m1_pass = score_m1_candidate(m1_bundle, fvec, checks)

        pred = pipe.predict_one(
            fl_102,
            blend_share=item["blend_med"],
            is_variable=item["is_variable"],
            has_masked_pixels=not checks["mask_bit_clean"],
            parallax_snr=plx_snr,
            flux_err=fe_102,
        )
        mols = compute_molecule_readings(
            wl_grid, bw_grid, fl_102, flux_err=fe_102, blend_share=item["blend_med"], is_variable=item["is_variable"]
        )
        weird = pred["novelty"].get("weirdness_score") or 0.0
        unexplained = max(weird, 1.0 - float(pred["all_data"].get("confidence") or 0.0), 0.75 if item["is_variable"] else 0.15)
        priority = round(min(item["max_snr"], 120.0) * p_real * unexplained, 3)

        # Build honest top-3 reference template class comparison from E1 chi2 scores
        top3 = _compute_top3_classes(pipe, fl_102, fe_102)
        det_class = "Variable source" if item["is_variable"] else "Catalogued source"
        records.append(
            {
                "source_id": item["source_id"],
                "field_id": field_id,
                "field_name": spec["field_name"],
                "kind": det_class,
                "detector_hit": "variable" if item["is_variable"] else ("edge" if edge_info["flagged"] else "catalogue"),
                "ra_deg": ra_d,
                "dec_deg": dec_d,
                "x_px": xp,
                "y_px": yp,
                "snr": round(item["max_snr"], 2),
                "blend_share": round(item["blend_med"], 4),
                "is_variable": item["is_variable"],
                "chi2_red": round(item["max_chi2"], 2),
                "p_real": p_real,
                "m1_passed_1pct_fpr": m1_pass,
                "priority": priority,
                "unexplained_score": round(unexplained, 3),
                "machine_checks": checks,
                "crosstalk_ghost_reasons": cg["reasons"],
                "edge_check": edge_info,
                "estimate_spectrum_alone": pred["spectrum_alone"],
                "estimate_all_data": pred["all_data"],
                "top_3_classes": top3,
                "novelty": pred["novelty"],
                "molecules": mols,
                "measured_6band": measured_6,
                "deciding_bands": deciding_bands,
                "spectral_sampling": f"{len(measured_6)}/6 broadband detectors ({len(measured_6)}/102 channels; LVF narrow bands unmeasured)",
                "motion_mas_yr": {
                    "pmra_mas_yr": meta.get("pmra_mas_yr"),
                    "pmdec_mas_yr": meta.get("pmdec_mas_yr"),
                    "parallax_mas": plx,
                },
                "epochs": {
                    "2MASS_J2000": {"j_mag": meta.get("j_mag"), "h_mag": meta.get("h_mag"), "ks_mag": meta.get("ks_mag")},
                    "WISE_2015": {"w1_mag": meta.get("w1_mag"), "w2_mag": meta.get("w2_mag")},
                    "GaiaDR3_2016": {"g_mag": meta.get("phot_g_mean_mag")},
                    "SPHEREx_2025_2026": [v.get("epoch_iso") for v in visits],
                },
                "data_origin": "tier_b_real_spherex_field_analysis",
                "model_version": ml_bundle["model_version"],
            }
        )

    catalog_xy = [(float(r["x_px"]), float(r["y_px"])) for r in records]
    # Scan persistent & moving leftover residual peaks on D3
    leftovers = _detect_leftover_and_mover_signals(
        field_id,
        spec,
        manifest,
        raw["flux_cube"],
        raw["mask_cube"],
        det_stacks,
        wcs,
        visits,
        skybot_rows,
        bright_anchors_d3,
        catalog_xy,
        m1_bundle,
        pipe,
        wl_grid,
        bw_grid,
        ml_bundle["model_version"],
    )
    records.extend(leftovers)
    records.sort(key=lambda r: float(r.get("priority") or 0.0), reverse=True)

    result = {
        "field_id": field_id,
        "field_name": spec["field_name"],
        "data_as_of": scene.get("data_as_of"),
        "pipeline_version": scene.get("pipeline_version"),
        "model_version": ml_bundle["model_version"],
        "m1_calibration": {k: v for k, v in m1_bundle.items() if k != "model"},
        "b10_steady_edge_stats": _compute_b10_rate(records),
        "skybot_matches": skybot_rows,
        "records": records,
    }
    return result


def _compute_b10_rate(records):
    steady = [r for r in records if r["kind"] == "Catalogued source" and not r["is_variable"] and r["snr"] >= 8.0 and r["blend_share"] < 0.30]
    if not steady:
        return {"test_id": "B10", "status": "NOT_MEASURED", "steady_count": 0, "false_flag_rate": 0.0, "passed": False}
    flagged = sum(1 for r in steady if r["edge_check"]["flagged"])
    rate = round(flagged / len(steady), 4)
    return {
        "test_id": "B10",
        "status": "MEASURED",
        "steady_count": len(steady),
        "flagged_count": flagged,
        "false_flag_rate": rate,
        "passed": bool(rate <= 0.01),
    }


def _compute_top3_classes(pipe, fl_102, fe_102):
    fl = np.asarray(fl_102, dtype=np.float64)
    fin = np.isfinite(fl)
    if int(np.count_nonzero(fin & (fl > 0))) < 3:
        return []
    denom = max(float(np.mean(np.abs(fl[fin]))), 1e-6)
    norm_fl = fl / denom
    norm_err = (np.asarray(fe_102, dtype=np.float64) / denom) if fe_102 is not None else None
    _, chi2_map = pipe._predict_template_class(norm_fl, norm_err=norm_err)
    e1_probs = pipe._template_probs(min(chi2_map, key=chi2_map.get), chi2_map)
    feat = pipe._extract_features(fl.reshape(1, -1))[0]
    tree_probs = pipe._predict_tree_probs(feat)
    wl_list = [round(float(w), 4) for w in pipe.wavelengths]

    items = []
    for idx_c, cls in enumerate(pipe.template_variants_.keys()):
        p_comb = 0.5 * (float(e1_probs[idx_c]) + float(tree_probs.get(cls, 0.0)))
        tmpls = pipe.template_variants_[cls]
        best_t = min(tmpls, key=lambda t: pipe._reduced_chi2(norm_fl, t, norm_err=norm_err))
        items.append(
            {
                "class_name": str(cls),
                "score": round(p_comb, 4),
                "chi2_red": round(float(chi2_map.get(cls, 99.0)), 3) if math.isfinite(chi2_map.get(cls, 99.0)) else None,
                "strip_wavelength_um": wl_list,
                "strip_norm_flux": [round(float(v), 4) if math.isfinite(v) else None for v in best_t],
            }
        )
    items.sort(key=lambda it: it["score"], reverse=True)
    return items[:3]


def _detect_leftover_and_mover_signals(
    field_id,
    spec,
    manifest,
    flux_cube,
    mask_cube,
    det_stacks,
    wcs,
    visits,
    skybot_rows,
    bright_anchors_d3,
    catalog_xy,
    m1_bundle,
    pipe,
    wl_grid,
    bw_grid,
    model_version,
):
    out = []
    d3_st = det_stacks["D3"]
    tracks = detect_moving_candidates(flux_cube, mask_cube, d3_st["mod_visits"], wcs, visits, "D3", bright_anchors_d3)
    for t_i, tr in enumerate(tracks):
        info = tr["info"]
        cg = evaluate_crosstalk_ghost_risk(tr["x_px"], tr["y_px"], info["flux_mjy_sr_sum"], d3_st["mask_or"], bright_anchors_d3)
        near_cat = any(math.hypot(tr["x_px"] - sx, tr["y_px"] - sy) <= 1.2 for sx, sy in catalog_xy)
        if near_cat and cg["saturated_halo_clear"] and cg["crosstalk_ghost_clear"]:
            continue
        matched_sso = None
        for sso in skybot_rows:
            if _sky_sep_arcsec(tr["ra_deg"], tr["dec_deg"], sso["ra_deg"], sso["dec_deg"]) <= 12.0:
                matched_sso = sso["name"]
                break
        is_clean = bool(cg["saturated_halo_clear"] and cg["crosstalk_ghost_clear"] and info["frac_masked_3x3"] < 0.35)
        checks = {
            "psflike_shape": bool(info["psf_corr"] >= 0.45 and info["frac_1px"] <= 0.85),
            "multi_exposure_repeat": True,
            "saturated_halo_clear": cg["saturated_halo_clear"],
            "crosstalk_ghost_clear": cg["crosstalk_ghost_clear"],
            "mask_bit_clean": bool(info["frac_masked_3x3"] < 0.35),
            "catalogue_skybot_status": f"Known moving object ({matched_sso})" if matched_sso else ("Artefact risk flagged" if not is_clean else "Unlisted moving track"),
        }
        fvec = _build_m1_feature_vector(
            snr=tr["snr"],
            psf_corr=info["psf_corr"],
            frac_1px=info["frac_1px"],
            conc_3x3_5x5=info["conc_3x3_5x5"],
            elongation=info["elongation"],
            frac_masked_3x3=info["frac_masked_3x3"],
            n_visits_det=len(tr["linked_visits"]),
            n_dets_det=2,
            min_sat_or_bright_px=cg["min_sat_or_bright_px"],
            spike_axis_score=cg["spike_axis_score"],
            ghost_xtalk_score=cg["ghost_xtalk_score"],
            edge_px_dist=info["edge_px_dist"],
        )
        p_real, m1_pass = score_m1_candidate(m1_bundle, fvec, checks)
        unexp = 0.2 if matched_sso else (0.15 if not is_clean else 0.95)
        out.append(
            {
                "source_id": f"{field_id.upper()}-MOVER-{t_i + 1}",
                "field_id": field_id,
                "field_name": spec["field_name"],
                "kind": "Moving candidate" if is_clean else "Flagged artefact",
                "detector_hit": "mover" if is_clean else "artefact",
                "ra_deg": round(tr["ra_deg"], 6),
                "dec_deg": round(tr["dec_deg"], 6),
                "x_px": round(tr["x_px"], 2),
                "y_px": round(tr["y_px"], 2),
                "snr": tr["snr"],
                "blend_share": 0.0,
                "is_variable": False,
                "chi2_red": None,
                "p_real": p_real,
                "m1_passed_1pct_fpr": m1_pass,
                "priority": round(min(tr["snr"], 120.0) * p_real * unexp, 3),
                "unexplained_score": unexp,
                "machine_checks": checks,
                "crosstalk_ghost_reasons": cg["reasons"],
                "edge_check": {"status": "NOT_MEASURED", "flagged": False},
                "estimate_spectrum_alone": {"top_class": "Unclassified", "confidence": 0.0, "template_class": "Unclassified", "tree_class": "Unclassified", "conformal_set": []},
                "estimate_all_data": {"top_class": "Unclassified", "confidence": 0.0, "parallax_gate_applied": False, "conformal_set": []},
                "top_3_classes": [],
                "novelty": {"status": "MOVING_TRACK" if is_clean else "ARTEFACT_FLAGGED", "weirdness_score": round(unexp, 3)},
                "molecules": {},
                "measured_6band": [{"band": "D3", "wavelength_um": round(d3_st["cwave_um"], 4), "flux_uJy": tr["flux_uJy"], "err_uJy": round(tr["flux_uJy"] / max(tr["snr"], 1.0), 2)}],
                "deciding_bands": [],
                "spectral_sampling": "Single-band D3 track only (102 channels unmeasured)",
                "motion_mas_yr": {"rate_arcsec_hr": tr["rate_arcsec_hr"], "linked_visits": tr["linked_visits"]},
                "epochs": {"SPHEREx_2025_2026": [v.get("epoch_iso") for v in visits]},
                "data_origin": "tier_b_real_spherex_field_analysis",
                "model_version": model_version,
            }
        )

    # Scan persistent unmodeled leftover peaks on D3 residual median stack
    res3 = d3_st["res_stack"]
    med3, sig3 = _grid_stats(res3)
    snr_grid = np.where(np.isfinite(res3), (res3 - med3) / sig3, -999.0)
    peaks = np.argwhere(snr_grid > 5.0)
    ny, nx = res3.shape
    seen_grid = np.zeros((ny, nx), dtype=bool)
    l_idx = 0
    for cy, cx in peaks[np.argsort(snr_grid[peaks[:, 0], peaks[:, 1]])[::-1]]:
        if seen_grid[cy, cx] or not (3 <= cy < ny - 3 and 3 <= cx < nx - 3):
            continue
        seen_grid[max(0, cy - 3) : min(ny, cy + 4), max(0, cx - 3) : min(nx, cx + 4)] = True
        info = _evaluate_psf_stamp_corr_and_conc(res3, d3_st["mask_or"], float(cx), float(cy), med3)
        if not info or info["flux_mjy_sr_sum"] <= 0.0:
            continue
        cg = evaluate_crosstalk_ghost_risk(float(cx), float(cy), float(res3[cy, cx] - med3), d3_st["mask_or"], bright_anchors_d3)
        near_cat = any(math.hypot(float(cx) - sx, float(cy) - sy) <= 1.35 for sx, sy in catalog_xy)
        if near_cat and cg["saturated_halo_clear"] and cg["crosstalk_ghost_clear"]:
            continue

        # Measure persistence across D1..D6 residual stacks
        n_dets_hit = 0
        fl_102 = np.full(len(wl_grid), np.nan, dtype=np.float64)
        fe_102 = np.full(len(wl_grid), np.nan, dtype=np.float64)
        meas_6, dec_bands = [], []
        for d_id in VALID_DETECTORS:
            ds = det_stacks[d_id]
            md, sg = _grid_stats(ds["res_stack"])
            d_info = _evaluate_psf_stamp_corr_and_conc(ds["res_stack"], ds["mask_or"], float(cx), float(cy), md)
            d_snr = (float(ds["res_stack"][cy, cx]) - md) / sg if (np.isfinite(ds["res_stack"][cy, cx]) and (ds["mask_or"][cy, cx] & 7) == 0) else 0.0
            f_ujy = d_info["flux_mjy_sr_sum"] * _MJY_SR_TO_UJY_PX if d_info else None
            if d_snr >= 3.5 and f_ujy is not None and f_ujy > 0:
                n_dets_hit += 1
                e_ujy = max(f_ujy / max(d_snr, 1.0), 1.0)
                idx = int(np.argmin(np.abs(wl_grid - ds["cwave_um"])))
                fl_102[idx] = f_ujy
                fe_102[idx] = e_ujy
                meas_6.append({"band": d_id, "wavelength_um": round(ds["cwave_um"], 4), "flux_uJy": round(f_ujy, 2), "err_uJy": round(e_ujy, 2)})
                dec_bands.append({"detector": d_id, "cwave_um": round(ds["cwave_um"], 4), "status": "MEASURED", "flux_uJy": round(f_ujy, 2), "flux_err_uJy": round(e_ujy, 2)})
            else:
                dec_bands.append({"detector": d_id, "cwave_um": round(ds["cwave_um"], 4), "status": "NOT_MEASURED", "flux_uJy": None, "flux_err_uJy": None})

        # Measure visit repeatability at (cy, cx) in D3 residuals
        n_v_hit = 0
        for rv in d3_st["res_visits"]:
            mv, sv = _grid_stats(rv)
            if np.isfinite(rv[cy, cx]) and (float(rv[cy, cx]) - mv) / sv >= 3.2:
                n_v_hit += 1

        ra_l, dec_l = wcs.all_pix2world([[float(cx), float(cy)]], 0)[0]
        checks = {
            "psflike_shape": bool(info["psf_corr"] >= 0.45 and info["frac_1px"] <= 0.85 and info["elongation"] <= 2.4),
            "multi_exposure_repeat": bool(n_v_hit >= 2 or n_dets_hit >= 2),
            "saturated_halo_clear": cg["saturated_halo_clear"],
            "crosstalk_ghost_clear": cg["crosstalk_ghost_clear"],
            "mask_bit_clean": bool(info["frac_masked_3x3"] < 0.35),
            "catalogue_skybot_status": "Near bright star halo" if not cg["saturated_halo_clear"] else "Unmatched residual signal",
        }
        fvec = _build_m1_feature_vector(
            snr=float(snr_grid[cy, cx]),
            psf_corr=info["psf_corr"],
            frac_1px=info["frac_1px"],
            conc_3x3_5x5=info["conc_3x3_5x5"],
            elongation=info["elongation"],
            frac_masked_3x3=info["frac_masked_3x3"],
            n_visits_det=n_v_hit,
            n_dets_det=max(n_dets_hit, 1),
            min_sat_or_bright_px=cg["min_sat_or_bright_px"],
            spike_axis_score=cg["spike_axis_score"],
            ghost_xtalk_score=cg["ghost_xtalk_score"],
            edge_px_dist=info["edge_px_dist"],
        )
        p_real, m1_pass = score_m1_candidate(m1_bundle, fvec, checks)
        pred = pipe.predict_one(fl_102, blend_share=0.0, is_variable=False, has_masked_pixels=not checks["mask_bit_clean"], parallax_snr=0.0, flux_err=fe_102)
        mols = compute_molecule_readings(wl_grid, bw_grid, fl_102, flux_err=fe_102, blend_share=0.0, is_variable=False)
        weird = pred["novelty"].get("weirdness_score") or 0.85
        unexp = max(weird, 0.85)
        l_idx += 1
        out.append(
            {
                "source_id": f"{field_id.upper()}-RES-{l_idx}",
                "field_id": field_id,
                "field_name": spec["field_name"],
                "kind": "Leftover residual" if cg["saturated_halo_clear"] and cg["crosstalk_ghost_clear"] else "Flagged artefact",
                "detector_hit": "leftover" if (m1_pass and cg["saturated_halo_clear"] and cg["crosstalk_ghost_clear"]) else "artefact",
                "ra_deg": round(float(ra_l), 6),
                "dec_deg": round(float(dec_l), 6),
                "x_px": float(cx),
                "y_px": float(cy),
                "snr": round(float(snr_grid[cy, cx]), 2),
                "blend_share": 0.0,
                "is_variable": False,
                "chi2_red": None,
                "p_real": p_real,
                "m1_passed_1pct_fpr": m1_pass,
                "priority": round(min(float(snr_grid[cy, cx]), 120.0) * p_real * unexp, 3),
                "unexplained_score": round(unexp, 3),
                "machine_checks": checks,
                "crosstalk_ghost_reasons": cg["reasons"],
                "edge_check": {"status": "NOT_MEASURED", "flagged": False},
                "estimate_spectrum_alone": pred["spectrum_alone"],
                "estimate_all_data": pred["all_data"],
                "top_3_classes": _compute_top3_classes(pipe, fl_102, fe_102),
                "novelty": pred["novelty"],
                "molecules": mols,
                "measured_6band": meas_6,
                "deciding_bands": dec_bands,
                "spectral_sampling": f"{len(meas_6)}/6 broadband detectors ({len(meas_6)}/102 channels; LVF narrow bands unmeasured)",
                "motion_mas_yr": {},
                "epochs": {"SPHEREx_2025_2026": [v.get("epoch_iso") for v in visits]},
                "data_origin": "tier_b_real_spherex_field_analysis",
                "model_version": model_version,
            }
        )
        if l_idx >= 18:
            break
    return out


def _matches_category(rec, cat_id):
    est_all = rec.get("estimate_all_data") or {}
    est_spec = rec.get("estimate_spectrum_alone") or {}
    top_names = {
        str(est_all.get("top_class") or ""),
        str(est_spec.get("top_class") or ""),
        str(est_spec.get("template_class") or ""),
        str(est_spec.get("tree_class") or ""),
    }
    conformal = set(est_all.get("conformal_set") or []) | set(est_spec.get("conformal_set") or [])
    candidates = top_names | conformal
    mols = rec.get("molecules") or {}

    if cat_id == "ultracool_dwarf":
        return "Ultracool dwarf" in candidates
    if cat_id == "yso":
        return "Young star with ice or dust" in candidates
    if cat_id == "star":
        return "Star" in candidates
    if cat_id == "evolved_giant":
        return "Evolved giant star" in candidates
    if cat_id == "galaxy":
        return "Galaxy" in candidates
    if cat_id == "agn_quasar":
        return "Active galaxy or quasar" in candidates
    if cat_id == "moving_source":
        return rec.get("detector_hit") == "mover" or rec.get("kind") == "Moving candidate"
    if cat_id == "variable_source":
        return bool(rec.get("is_variable"))
    if cat_id == "methane_dip":
        feats = (mols.get("features") if isinstance(mols, dict) else None) or {}
        ch4 = feats.get("CH4_3_3") or {}
        tau = ch4.get("integrated_tau")
        if ch4.get("status") != "MEASURED" or tau is None or float(tau) < 30.0:
            return False
        p16, p84 = ch4.get("p16"), ch4.get("p84")
        if p16 is not None and p84 is not None:
            err = max(abs(float(p84) - float(p16)) * 0.5, 1e-6)
            return float(tau) / err >= 3.0
        return True
    if cat_id in ("water_ice", "co2_ice", "co_ice"):
        feats = (mols.get("features") if isinstance(mols, dict) else None) or {}
        key_map = {"water_ice": "H2O_ice_3_05", "co2_ice": "CO2_4_26", "co_ice": "CO_4_67"}
        mol = feats.get(key_map[cat_id]) or {}
        tau = mol.get("integrated_tau")
        return bool(mol.get("status") == "MEASURED" and tau is not None and float(tau) >= 0.1)
    return True


def search_field_sources(
    field_id="all",
    categories=(),
    min_snr=5.0,
    max_blend=1.0,
    only_unexplained=False,
    sort_by="priority",
    limit=80,
    contracts_dir=DEFAULT_CONTRACTS_DIR,
):
    """Execute T51 Search-by-Light query across processed Tier-B sky fields."""
    avail_fields = [f["field_id"] for f in list_processed_fields(contracts_dir=contracts_dir)]
    target_fids = avail_fields if field_id in (None, "", "all") else [fid for fid in avail_fields if fid == field_id]
    combined = []
    coverage_notes = []
    for fid in target_fids:
        ana = analyze_field_candidates(fid, contracts_dir=contracts_dir)
        combined.extend(ana["records"])
        coverage_notes.append(f"{ana['field_name']} (3.3' radius)")

    cats = [str(c).strip() for c in (categories or []) if str(c).strip()]
    filtered = []
    for r in combined:
        if float(r.get("snr") or 0.0) < float(min_snr):
            continue
        if float(r.get("blend_share") or 0.0) > float(max_blend):
            continue
        if only_unexplained and float(r.get("unexplained_score") or 0.0) < 0.45:
            continue
        if cats and not any(_matches_category(r, c) for c in cats):
            continue
        filtered.append(r)

    if sort_by == "snr":
        filtered.sort(key=lambda r: float(r.get("snr") or 0.0), reverse=True)
    elif sort_by == "weirdness":
        filtered.sort(key=lambda r: float((r.get("novelty") or {}).get("weirdness_score") or 0.0), reverse=True)
    else:
        filtered.sort(key=lambda r: float(r.get("priority") or 0.0), reverse=True)

    return {
        "field_scope": field_id or "all",
        "coverage_statement": (
            f"Covers {', '.join(coverage_notes) or 'no fields'}; full-sky catalog search not active."
        ),
        "categories_available": SEARCH_CATEGORY_FILTERS,
        "total_matched": len(filtered),
        "results": filtered[: max(1, min(int(limit), 200))],
    }


def get_source_identity_v2(field_id, source_id, contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Fetch complete T52 Identity v2 packet (with spectral strips & model-card gate stats) for one source."""
    ana = analyze_field_candidates(field_id, contracts_dir=contracts_dir)
    ml_bundle = get_cached_ml_pipeline()
    rec = next((r for r in ana["records"] if r["source_id"] == source_id), None)
    if rec is None:
        raise KeyError(f"Source {source_id!r} not found in field {field_id!r}")
    return {
        **rec,
        "model_card": {
            "model_version": ml_bundle["model_version"],
            "release_status": ((ml_bundle["evaluation_report"].get("release_gates") or {}).get("release_status")) or "UNPUBLISHED",
            "gold_high_snr": ((ml_bundle["evaluation_report"].get("release_gates") or {}).get("high_snr_gold")) or {},
            "m1_calibration": ana["m1_calibration"],
        },
    }


def evaluate_slice2_benchmarks(contracts_dir=DEFAULT_CONTRACTS_DIR):
    """Measure B3 (planted mover recovery >= 80%), B6 (M1 recall at 1% FPR), and B10 (steady-star edge flag <= 1%)."""
    m1_bundle = train_and_calibrate_m1_classifier(contracts_dir=contracts_dir)

    # B3: measure mover recovery by planting synthetic moving PSF sources on real rwaur D3 background across visits
    spec, scene, manifest, flux_cube, mask_cube = load_field_scene_and_pack("rwaur", contracts_dir=contracts_dir)
    wcs = build_target_canvas_wcs(float(manifest["center_ra_deg"]), float(manifest["center_dec_deg"]), size_px=64)
    d_idx = DETECTOR_INDEX["D3"]
    epsf = (scene.get("epsf_calibration") or {}).get("D3")
    stamp = np.asarray(epsf["stamp_33x33"], dtype=np.float64) if (epsf and epsf.get("stamp_33x33")) else None
    prep = _convolve_reprojection_kernel(stamp, oversample=5) if stamp is not None else None
    visits = list(manifest.get("visits") or [])

    base_models = [
        solve_joint_psf_frame(flux_cube[v, d_idx], mask_cube[v, d_idx], wcs, scene["sources"], 2025.8, "D3", epsf_info=epsf)["model"]
        for v in range(flux_cube.shape[0])
    ]
    base_res = flux_cube[0, d_idx] - base_models[0]
    med_b, sig_b = _grid_stats(base_res)

    rng = np.random.default_rng(7)
    n_trials = 10
    n_recovered = 0
    for k in range(n_trials):
        fc = flux_cube.copy()
        # Plant a ~10-sigma clean moving PSF stepping cleanly across free sky pixels between V1 and V2
        x0 = float(rng.uniform(14.0, 26.0))
        y0 = float(rng.uniform(10.0, 18.0))
        x1 = x0 + 6.0
        y1 = y0 + 2.0
        for v_step, (xp, yp) in [(0, (x0, y0)), (1, (x1, y1))]:
            iy0, iy1, ix0, ix1, patch = evaluate_psf_patch(
                64, 64, xp, yp, half_box=3, stamp_33x33=stamp, sigma_px=DEFAULT_DETECTOR_SIGMA_PX["D3"], prepared_stamp=prep
            )
            flux_tot = (12.0 * sig_b) / max(float(np.max(patch)), 1e-6)
            fc[v_step, d_idx, iy0:iy1, ix0:ix1] += flux_tot * patch
        tracks = detect_moving_candidates(fc, mask_cube, base_models, wcs, visits, "D3", ())
        hit = any(
            math.hypot(t["x_px"] - x1, t["y_px"] - y1) <= 1.8
            for t in tracks
        )
        if hit:
            n_recovered += 1
    b3_rec = round(n_recovered / n_trials, 4)

    # B10 combined across rwaur and w1925
    b10_w = analyze_field_candidates("w1925", contracts_dir=contracts_dir)["b10_steady_edge_stats"]
    b10_r = analyze_field_candidates("rwaur", contracts_dir=contracts_dir)["b10_steady_edge_stats"]
    tot_steady = int(b10_w["steady_count"]) + int(b10_r["steady_count"])
    tot_flagged = int(b10_w.get("flagged_count", 0)) + int(b10_r.get("flagged_count", 0))
    b10_rate = round(tot_flagged / max(tot_steady, 1), 4)

    return {
        "B3": {
            "test_id": "B3",
            "status": "MEASURED",
            "planted_trials": n_trials,
            "recovered_count": n_recovered,
            "recovery_rate": b3_rec,
            "passed": bool(b3_rec >= 0.80),
        },
        "B6": {
            "test_id": "B6",
            "status": "MEASURED",
            "p_threshold_1pct_fpr": m1_bundle["p_threshold_1pct_fpr"],
            "val_false_pass_rate": m1_bundle["val_false_pass_rate"],
            "recall_at_1pct_fpr": m1_bundle["b6_recall_at_1pct_fpr"],
            "n_val_pos": m1_bundle["n_val_pos"],
            "n_val_neg": m1_bundle["n_val_neg"],
        },
        "B10": {
            "test_id": "B10",
            "status": "MEASURED",
            "steady_count": tot_steady,
            "flagged_count": tot_flagged,
            "false_flag_rate": b10_rate,
            "passed": bool(b10_rate <= 0.01),
        },
    }
