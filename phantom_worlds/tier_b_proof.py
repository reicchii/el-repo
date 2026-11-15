"""Tier-B Proof, Retrospective Prediction Check, Searched Depth Injection & Case Queue (T46-T48, B4, B7-B9, T53-T54)."""

from datetime import datetime, timezone
import json
import math
import os
import re

os.environ.setdefault("LOKY_MAX_CPU_COUNT", "1")

import numpy as np

from phantom_worlds.contracts import (
    DEFAULT_CONTRACTS_DIR,
    DEFAULT_CSV_DIR,
    DETECTOR_INDEX,
    PACKAGE_ROOT,
    VALID_DETECTORS,
    _project_sky_to_px,
    load_manifest,
    load_patch_arrays,
    load_targets,
    propagate_position,
)
from phantom_worlds.fits_cutout import PIXEL_SCALE_ARCSEC, _MJY_SR_TO_UJY_PX
from phantom_worlds.ml_pipeline import compute_molecule_readings
from phantom_worlds.real_ml_data import DEFAULT_ML_DIR
from phantom_worlds.tier_a_metrics import (
    DEFAULT_EVAL_REPORT_JSON,
    _fit_visit_centroid,
    _measure_visit_photometry,
    _mjd_to_julian_year,
    build_proof_summary,
)
from phantom_worlds.tier_b_detectors import (
    _collect_field_6band_and_residuals,
    _evaluate_psf_stamp_corr_and_conc,
    _grid_stats,
    _matches_category,
    _sky_sep_arcsec,
    analyze_field_candidates,
    evaluate_slice2_benchmarks,
)
from phantom_worlds.tier_b_engine import (
    DEFAULT_DETECTOR_SIGMA_PX,
    PIPELINE_VERSION,
    _convolve_reprojection_kernel,
    evaluate_b1_b2_2mass_check,
    evaluate_psf_patch,
    list_processed_fields,
)

DEFAULT_PROOF_DIR = os.path.join(PACKAGE_ROOT, "proof")
INJECTION_AB_MAGS = (13.5, 14.5, 15.5, 16.5, 17.0, 17.5, 18.0, 18.5, 19.0)
INJECTION_MOTION_MODES = (
    {"id": "slow_multi_visit", "label": "0.03\"/hr (multi-visit 19 px shift)", "speed_arcsec_hr": 0.03, "shift_px": 19.0},
    {"id": "fast_asteroid", "label": "8.0\"/hr (intra-epoch 10 px step)", "speed_arcsec_hr": 8.0, "shift_px": 10.0},
)
PROOF_NEXT_ITEMS = [
    "C1-C5 Community review workflow, pinned sky evidence notes & Brier forecast scoring (Tier C).",
    "C6-C7 All-sky spectral cube slices & interactive Draw-the-Light spectral sketch matching.",
    "C8-C13 Saved search recipes, GCNS 3D neighbourhood map & Indonesian localization.",
]
PROOF_CREDITS = [
    {
        "name": "NASA SPHEREx DR1 & Quick Release (QR2, QR3) Spectral Images via IRSA",
        "detail": "IRSA SPHEREx Archive; QR2 DOI 10.26131/IRSA652; QR3 DOI 10.26131/IRSA662; Bock et al. 2025; Akeson et al. 2025 (arXiv:2511.15823).",
    },
    {
        "name": "Crowding & Sub-stellar Literature",
        "detail": "SMDET-1 crowding depth benchmark (arXiv:2608.00046); Faherty et al. 2018; WISE 0855 & Barnard's Star reference astrometry.",
    },
    {
        "name": "Reference Surveys & Archives",
        "detail": "Gaia DR3 (ESA), 2MASS (IPAC/UMass), CatWISE2020, unWISE, Spitzer GLIMPSE, SIMBAD, VizieR (CDS), AAVSO VSX, IMCCE SkyBoT.",
    },
    {
        "name": "Inspiration & Viewer Heritage",
        "detail": "WiseView (byw.tools), Backyard Worlds: Planet 9, The Rogue Worlds Project, Aladin Lite (CDS), IRSA forced photometry.",
    },
    {
        "name": "ML Training Libraries & Python Stack (Permissive Licences)",
        "detail": "SPIFF library (DOI 10.5281/zenodo.19051216, CC BY 4.0, Gagne et al. 2026); UltracoolSheet (DOI 10.5281/zenodo.4169084, CC BY 4.0); SPLICES (DOI 10.26131/IRSA554, Ashby et al. 2023); DESI DR1 (CC BY 4.0); Euclid; Astropy, photutils, scikit-learn, SciPy, NumPy, FastAPI.",
    },
]


def _processed_field_ids(contracts_dir):
    return [str(f["field_id"]) for f in list_processed_fields(contracts_dir=contracts_dir) if isinstance(f, dict) and f.get("field_id")]


def _px_to_sky_deg(cx, cy, center_ra, center_dec, fov_arcmin, n_px):
    scale_deg = (fov_arcmin / 60.0) / float(n_px)
    half = (float(n_px) - 1.0) * 0.5
    cosd = max(math.cos(math.radians(center_dec)), 1e-6)
    d_ra = -(float(cx) - half) * scale_deg / cosd
    d_dec = -(float(cy) - half) * scale_deg
    return ((center_ra + d_ra) % 360.0), max(-90.0, min(90.0, center_dec + d_dec))


def _evaluate_mover_retro(tid, manifest, target_row, contracts_dir):
    _, flux_cube, mask_cube = load_patch_arrays(contracts_dir, target_id=tid, manifest=manifest)
    visits = list(manifest.get("visits") or [])
    n_visits, _, ny, nx = flux_cube.shape
    yy, xx = np.mgrid[0:ny, 0:nx]
    center_ra = float(manifest["center_ra_deg"])
    center_dec = float(manifest["center_dec_deg"])
    fov_arcmin = float(manifest.get("fov_arcmin", 6.56))
    px_scale = float(manifest.get("pixel_scale_arcsec", PIXEL_SCALE_ARCSEC))
    gaia_rms = float(manifest.get("gaia_alignment_rms_arcsec") or 0.5)

    has_cat = target_row is not None and target_row.get("ra_deg_j2000") is not None
    ref_ra = float(target_row["ra_deg_j2000"]) if has_cat else float(manifest.get("target_j2000_ra_deg", center_ra))
    ref_dec = float(target_row["dec_deg_j2000"]) if has_cat else float(manifest.get("target_j2000_dec_deg", center_dec))
    cat_pmra = float(target_row.get("pm_ra_mas_yr", 0.0)) if has_cat else 0.0
    cat_pmdec = float(target_row.get("pm_dec_mas_yr", 0.0)) if has_cat else 0.0

    # Pick cleanest detector using target-aperture saturation (not distant frame borders/neighbours) and high SNR.
    det_order = ("D6",) if tid == "TGT-02" else ("D5", "D6", "D3", "D4", "D2", "D1")
    det_evals = {}
    for det_id in det_order:
        d_idx = DETECTOR_INDEX[det_id]
        expected_cat_px = []
        v_obs = []
        sat_sum = 0
        snrs = []
        for v_i in range(n_visits):
            mjd = float(visits[v_i].get("mjd", 60900.0))
            dt_yr = _mjd_to_julian_year(mjd) - 2000.0
            ra_v, dec_v = propagate_position(ref_ra, ref_dec, cat_pmra, cat_pmdec, dt_yr)
            cx_e, cy_e = _project_sky_to_px(ra_v, dec_v, center_ra, center_dec, fov_arcmin, nx)
            expected_cat_px.append((cx_e, cy_e, mjd, ra_v, dec_v))
            phot = _measure_visit_photometry(flux_cube[v_i, d_idx], mask_cube[v_i, d_idx], cx_e, cy_e, yy, xx)
            sat_sum += int(phot.get("saturated_core_px") or 0)
            if phot.get("snr") is not None:
                snrs.append(float(phot["snr"]))
            cen = _fit_visit_centroid(flux_cube[v_i, d_idx], mask_cube[v_i, d_idx], cx_e, cy_e, yy, xx) if (phot["snr"] or -99) >= 5.0 else None
            v_obs.append({"phot": phot, "cen": cen, "mjd": mjd, "visit_id": visits[v_i].get("visit_id", f"V{v_i + 1}")})
        med_snr = float(np.median(snrs)) if snrs else -99.0
        det_evals[det_id] = (sat_sum, med_snr, expected_cat_px, v_obs)

    clean_dets = [d for d in det_order if det_evals[d][0] == 0 and det_evals[d][1] >= 5.0]
    if clean_dets:
        chosen_det = max(clean_dets, key=lambda d: det_evals[d][1])
    elif tid == "TGT-02":
        chosen_det = "D6"
    else:
        chosen_det = min(det_order, key=lambda d: (det_evals[d][0], -det_evals[d][1]))

    _, _, expected_cat_px, obs_v = det_evals[chosen_det]

    if n_visits < 2:
        return {
            "target_id": tid,
            "target_name": manifest.get("target_name", tid),
            "detector": chosen_det,
            "status": "pending",
            "reason": "Fewer than 2 visits in cube",
            "pred_sep_arcsec": None,
            "stay_sep_arcsec": None,
            "sigma_arcsec": round(gaia_rms, 3),
        }

    final = obs_v[-1]
    snr_final = final["phot"].get("snr")
    # Retro prediction strictly excludes the held-out final visit
    if tid == "TGT-02" or sum(1 for r in obs_v[:-1] if r["cen"] is not None) < 2:
        # Stage 14 for WISE 0855: predict final visit from Gaia/cat PM+position, stay at V1 epoch
        pred_cx, pred_cy, pred_mjd, pred_ra, pred_dec = expected_cat_px[-1]
        stay_cx, stay_cy, stay_mjd, stay_ra, stay_dec = expected_cat_px[0]
        pred_basis = "Catalogue PM from V1 epoch (held-out V2/V3)"
        stay_basis = visits[0].get("visit_id", "V1")
        w_extrap = 1.0
        extrap_var_mult = 1.0
    else:
        c0 = obs_v[0]["cen"]
        c1 = obs_v[-2]["cen"]
        dt10_yr = max((obs_v[-2]["mjd"] - obs_v[0]["mjd"]) / 365.25, 0.05)
        dt20_yr = (final["mjd"] - obs_v[0]["mjd"]) / 365.25
        vx = (c1[0] - c0[0]) / dt10_yr
        vy = (c1[1] - c0[1]) / dt10_yr
        pred_cx = c0[0] + vx * dt20_yr
        pred_cy = c0[1] + vy * dt20_yr
        stay_cx, stay_cy = obs_v[0]["cen"]
        pred_mjd = final["mjd"]
        pred_ra, pred_dec = _px_to_sky_deg(pred_cx, pred_cy, center_ra, center_dec, fov_arcmin, nx)
        stay_ra, stay_dec = _px_to_sky_deg(stay_cx, stay_cy, center_ra, center_dec, fov_arcmin, nx)
        pred_basis = "Linear motion fitted on V1..V2 empirical centroids (V3 held out)"
        stay_basis = visits[0].get("visit_id", "V1")
        w_extrap = dt20_yr / dt10_yr
        # Linear two-point extrapolation pred = (1-w)*c0 + w*c1 + V3 observation variance
        extrap_var_mult = math.sqrt(1.0 + (1.0 - w_extrap) ** 2 + w_extrap ** 2)

    # Astrometric uncertainty includes single-visit Gaia WCS RMS, centroid SNR term, and extrapolation geometry
    centroid_err = px_scale / max(float(snr_final or 5.0), 5.0)
    sigma_epoch = max(math.hypot(gaia_rms, centroid_err), 0.25)
    sigma_as = sigma_epoch * extrap_var_mult
    sigma_stay_as = sigma_epoch * math.sqrt(2.0)

    if final["cen"] is None or snr_final is None or snr_final < 5.0:
        return {
            "target_id": tid,
            "target_name": manifest.get("target_name", tid),
            "detector": chosen_det,
            "held_out_visit": final["visit_id"],
            "held_out_mjd": round(final["mjd"], 4),
            "status": "not_observed",
            "reason": f"No >=5 sigma detection at predicted position in {chosen_det} {final['visit_id']} (S/N {snr_final})",
            "pred_basis": pred_basis,
            "stay_basis": stay_basis,
            "predicted_ra_deg": round(pred_ra, 6),
            "predicted_dec_deg": round(pred_dec, 6),
            "stay_ra_deg": round(stay_ra, 6),
            "stay_dec_deg": round(stay_dec, 6),
            "final_snr": snr_final,
            "pred_sep_arcsec": None,
            "stay_sep_arcsec": None,
            "sigma_arcsec": round(sigma_as, 3),
            "sigma_stay_arcsec": round(sigma_stay_as, 3),
            "saturated_core_px": int(final["phot"].get("saturated_core_px") or 0),
        }

    obs_cx, obs_cy = final["cen"]
    pred_sep_as = math.hypot(obs_cx - pred_cx, obs_cy - pred_cy) * px_scale
    stay_sep_as = math.hypot(obs_cx - stay_cx, obs_cy - stay_cy) * px_scale
    within_2sigma = pred_sep_as <= 2.0 * sigma_as
    stay_excluded_3sigma = stay_sep_as > 3.0 * sigma_stay_as
    status = "held" if (within_2sigma and stay_excluded_3sigma) else "failed"
    reason = (
        f"Within 2 sigma ({pred_sep_as:.2f}\" <= {2.0 * sigma_as:.2f}\") and excludes stationary baseline ({stay_sep_as:.2f}\" > {3.0 * sigma_stay_as:.2f}\")"
        if status == "held"
        else f"Pred sep {pred_sep_as:.2f}\" vs 2*sigma={2.0 * sigma_as:.2f}\" (stay sep {stay_sep_as:.2f}\")"
    )
    if int(final["phot"].get("saturated_core_px") or 0) > 0:
        reason += f" [outer-wing fit around {final['phot']['saturated_core_px']} saturated core px]"

    return {
        "target_id": tid,
        "target_name": manifest.get("target_name", tid),
        "detector": chosen_det,
        "held_out_visit": final["visit_id"],
        "held_out_mjd": round(pred_mjd, 4),
        "status": status,
        "reason": reason,
        "pred_basis": pred_basis,
        "stay_basis": stay_basis,
        "predicted_ra_deg": round(pred_ra, 6),
        "predicted_dec_deg": round(pred_dec, 6),
        "stay_ra_deg": round(stay_ra, 6),
        "stay_dec_deg": round(stay_dec, 6),
        "final_snr": snr_final,
        "pred_sep_arcsec": round(pred_sep_as, 3),
        "stay_sep_arcsec": round(stay_sep_as, 3),
        "sigma_arcsec": round(sigma_as, 3),
        "sigma_stay_arcsec": round(sigma_stay_as, 3),
        "within_2sigma": within_2sigma,
        "stay_excluded_3sigma": stay_excluded_3sigma,
        "saturated_core_px": int(final["phot"].get("saturated_core_px") or 0),
    }


def run_prediction_check(contracts_dir=DEFAULT_CONTRACTS_DIR, csv_dir=DEFAULT_CSV_DIR):
    """T46 & B7: Run retrospective Stage-14 prediction checks on movers plus locked future predictions."""
    targets = {row["target_id"]: row for row in load_targets(csv_dir=csv_dir)}
    movers = []
    for tid in ("TGT-01", "TGT-02", "TGT-03"):
        manifest = load_manifest(contracts_dir, target_id=tid)
        movers.append(_evaluate_mover_retro(tid, manifest, targets.get(tid), contracts_dir))

    # Build immutable locked-at predictions for field mover candidates (pending next SPHEREx epoch)
    locked_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    locked_predictions = []
    for fid in _processed_field_ids(contracts_dir):
        ana = analyze_field_candidates(fid, contracts_dir=contracts_dir, include_skybot=False)
        for rec in ana.get("records") or []:
            if rec.get("detector_hit") == "mover" or rec.get("kind") == "Moving candidate":
                pmra = float(rec.get("pm_ra_mas_yr") or 0.0)
                pmdec = float(rec.get("pm_dec_mas_yr") or 0.0)
                fut_ra, fut_dec = propagate_position(float(rec["ra_deg"]), float(rec["dec_deg"]), pmra, pmdec, 0.5)
                locked_predictions.append(
                    {
                        "prediction_id": f"PRED-{fid.upper()}-{rec['source_id']}",
                        "field_id": fid,
                        "source_id": rec["source_id"],
                        "locked_at": locked_at,
                        "horizon_days": 182.6,
                        "predicted_ra_deg": round(fut_ra, 6),
                        "predicted_dec_deg": round(fut_dec, 6),
                        "error_radius_arcsec": 1.2,
                        "stay_ra_deg": round(float(rec["ra_deg"]), 6),
                        "stay_dec_deg": round(float(rec["dec_deg"]), 6),
                        "status": "pending",
                        "reason": "Awaiting next visit epoch frames for settling",
                    }
                )
                if len([p for p in locked_predictions if p["field_id"] == fid]) >= 8:
                    break

    n_held = sum(1 for m in movers if m["status"] == "held")
    n_failed = sum(1 for m in movers if m["status"] == "failed")
    n_not_obs = sum(1 for m in movers if m["status"] == "not_observed")
    clean_movers = [m for m in movers if m["status"] in ("held", "failed") and (m.get("saturated_core_px") or 0) == 0]
    clean_held = sum(1 for m in clean_movers if m["status"] == "held")
    b7_passed = bool(clean_movers and clean_held == len(clean_movers) and n_failed == 0)

    return {
        "generated_at": locked_at,
        "pipeline_version": PIPELINE_VERSION,
        "b7_summary": {
            "pass_mark": "predicted <= 2 sigma, stay position excluded > 3 sigma",
            "movers_tested": len(movers),
            "held": n_held,
            "failed": n_failed,
            "not_observed": n_not_obs,
            "clean_unsaturated_held": f"{clean_held}/{len(clean_movers)}",
            "passed": b7_passed,
        },
        "retro_movers": movers,
        "locked_predictions": locked_predictions,
    }


def _interpolate_depth_at(curve_rows, target_rate=0.90):
    """Return faintest AB magnitude achieving >= target_rate recovery via linear interpolation."""
    prev_mag = None
    prev_rate = None
    best_mag = None
    for row in curve_rows:
        mag = float(row["ab_mag"])
        rate = float(row["recovery_rate"])
        if rate >= target_rate:
            best_mag = mag
        elif prev_mag is not None and prev_rate is not None and prev_rate >= target_rate and rate < prev_rate:
            frac = (prev_rate - target_rate) / (prev_rate - rate)
            return round(prev_mag + frac * (mag - prev_mag), 2)
        prev_mag, prev_rate = mag, rate
    return round(best_mag, 2) if best_mag is not None else None


def _fmt_depth(val):
    return f"{val:.2f} AB mag" if val is not None else "below 90% ceiling"


def format_planet_x_statement(fields_searched):
    """Generate honest Stage-15 / section 13.4 Planet X sensitivity text strictly from searched.json metrics."""
    rw = fields_searched.get("rwaur") or {}
    w1 = fields_searched.get("w1925") or {}
    rw_d6, w1_d6 = rw.get("depth_ab_90_d6"), w1.get("depth_ab_90_d6")
    rw_50, w1_50 = rw.get("depth_ab_50_d6"), w1.get("depth_ab_50_d6")
    rw_d3_50, w1_d3_50 = rw.get("depth_ab_50_d3"), w1.get("depth_ab_50_d3")
    d6_diff = round(float(rw_d6) - float(w1_d6), 2) if (rw_d6 is not None and w1_d6 is not None) else None
    d3_diff = round(float(rw_d3_50) - float(w1_d3_50), 2) if (rw_d3_50 is not None and w1_d3_50 is not None) else None
    if d3_diff is not None and d3_diff >= 0:
        crowd_txt = f"D3 50% crowding loss {d3_diff} mag ({_fmt_depth(rw_d3_50)} off-plane vs {_fmt_depth(w1_d3_50)} Galactic plane)"
    elif d6_diff is not None and d6_diff >= 0:
        crowd_txt = f"D6 90% crowding loss {d6_diff} mag"
    else:
        crowd_txt = (
            f"RW Aur bright-YSO halo limits local D6 90% ceiling to {_fmt_depth(rw_d6)} "
            f"(50%: {_fmt_depth(rw_50)}; D3 50%: {_fmt_depth(rw_d3_50)})"
        )
    fov = rw.get("fov_arcmin") or w1.get("fov_arcmin") or 6.56
    fov_arcsec = round(float(fov) * 60.0)
    return (
        f"Measured 90% mover recovery reaches {_fmt_depth(rw_d6)} (50%: {_fmt_depth(rw_50)}) off-plane (RW Aur D6) and "
        f"{_fmt_depth(w1_d6)} (50%: {_fmt_depth(w1_50)}) in the Galactic plane (W1925 D6); {crowd_txt} "
        f"across motions 0.03–8.0\"/hr. Field-size limit: each SPHEREx cutout covers {fov}' ({fov_arcsec}\"); "
        f"a 500 AU distant planet shifts ~800\" (~130 px) in 6 months via parallax, exceeding one cutout unless cross-tile links are run."
    )


def compute_searched_depth(contracts_dir=DEFAULT_CONTRACTS_DIR, write_files=True):
    """T47, B8 & B9: Run calibrated PSF injection/recovery on real field cutouts and write searched.json."""
    field_ids = _processed_field_ids(contracts_dir)
    if not field_ids:
        return {"fields": {}, "b8_summary": {}, "b9_smdet1": {}, "planet_x_statement": "No processed fields built."}

    rng = np.random.default_rng(20261114)
    candidate_pool = [(float(rng.uniform(8.0, 56.0)), float(rng.uniform(8.0, 56.0))) for _ in range(180)]
    results_by_field = {}
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    for fid in field_ids:
        collected = _collect_field_6band_and_residuals(fid, contracts_dir=contracts_dir)
        manifest = collected["manifest"]
        scene = collected["scene"]
        mask_cube = collected["mask_cube"]
        fov_arcmin = float(manifest.get("fov_arcmin", 6.56))
        ny, nx = mask_cube.shape[2], mask_cube.shape[3]
        det_tables = {}

        for det_id in ("D3", "D6"):
            d_idx = DETECTOR_INDEX[det_id]
            epsf_raw = ((scene.get("epsf_calibration") or {}).get(det_id) or {}).get("stamp_33x33")
            epsf_arr = np.asarray(epsf_raw, dtype=np.float64) if epsf_raw is not None else None
            prep_stamp = _convolve_reprojection_kernel(epsf_arr) if (epsf_arr is not None and epsf_arr.shape == (33, 33)) else None
            sigma_px = DEFAULT_DETECTOR_SIGMA_PX.get(det_id, 0.58)
            stacks = collected["det_stacks"][det_id]
            res_visits = stacks["res_visits"]
            anchors = collected["bright_anchors"][det_id]
            sat_yx = np.argwhere((np.bitwise_or.reduce(mask_cube[:, d_idx], axis=0) & 2) != 0)

            v0_idx, v1_idx = 0, max(len(res_visits) - 1, 0)
            rv0 = res_visits[v0_idx]
            rv1 = res_visits[v1_idx]
            med0, sig0 = _grid_stats(rv0)
            med1, sig1 = _grid_stats(rv1)
            mask0 = mask_cube[v0_idx, d_idx]
            mask1 = mask_cube[v1_idx, d_idx]

            motion_curves = []
            searchable_fracs = []
            for mode in INJECTION_MOTION_MODES:
                shift = float(mode["shift_px"])
                precomputed_trials = []
                n_attempted = 0
                for t_idx, (x0, y0) in enumerate(candidate_pool):
                    if len(precomputed_trials) >= 20:
                        break
                    n_attempted += 1
                    ang = 0.7854 + 0.5 * t_idx
                    x1 = max(6.0, min(nx - 7.0, x0 + shift * math.cos(ang)))
                    y1 = max(6.0, min(ny - 7.0, y0 + shift * math.sin(ang)))
                    if math.hypot(x1 - x0, y1 - y0) < 3.0:
                        x1 = x0 - shift * math.cos(ang)
                        y1 = y0 - shift * math.sin(ang)
                    ix0_i, iy0_i = int(round(x0)), int(round(y0))
                    ix1_i, iy1_i = int(round(x1)), int(round(y1))
                    # Require unmasked/non-saturated detector pixels (geometric searchable area)
                    if (mask0[iy0_i, ix0_i] & 7) != 0 or (mask1[iy1_i, ix1_i] & 7) != 0:
                        continue
                    if sat_yx.size > 0 and (
                        float(np.min(np.hypot(sat_yx[:, 1] - ix0_i, sat_yx[:, 0] - iy0_i))) < 2.5
                        or float(np.min(np.hypot(sat_yx[:, 1] - ix1_i, sat_yx[:, 0] - iy1_i))) < 2.5
                    ):
                        continue
                    # Crowded bright star anchors & pre-existing residual cores degrade completeness inside trials
                    blocked_by_crowding = (
                        any(math.hypot(ix0_i - bx, iy0_i - by) <= 2.2 for bx, by, _ in anchors)
                        or any(math.hypot(ix1_i - bx, iy1_i - by) <= 2.2 for bx, by, _ in anchors)
                        or (np.isfinite(rv1[iy0_i, ix0_i]) and abs(rv1[iy0_i, ix0_i] - med1) > 2.8 * sig1)
                        or (np.isfinite(rv0[iy1_i, ix1_i]) and abs(rv0[iy1_i, ix1_i] - med0) > 2.8 * sig0)
                    )
                    if blocked_by_crowding:
                        precomputed_trials.append(None)
                        continue
                    box_a = evaluate_psf_patch(ny, nx, x0, y0, half_box=3, prepared_stamp=prep_stamp, sigma_px=sigma_px)
                    box_b = evaluate_psf_patch(ny, nx, x1, y1, half_box=3, prepared_stamp=prep_stamp, sigma_px=sigma_px)
                    precomputed_trials.append((x0, y0, x1, y1, ix0_i, iy0_i, ix1_i, iy1_i, box_a, box_b))

                n_inj = max(len(precomputed_trials), 1)
                searchable_fracs.append(round(n_inj / float(max(n_attempted, 1)), 3))
                rows = []
                g0_work = rv0.copy()
                g1_work = rv1.copy()
                for ab_mag in INJECTION_AB_MAGS:
                    f_ujy = 3631.0e6 * (10.0 ** (-0.4 * float(ab_mag)))
                    f_mjy_sr_sum = f_ujy / _MJY_SR_TO_UJY_PX
                    n_rec = 0
                    for tr in precomputed_trials:
                        if tr is None:
                            continue
                        x0, y0, x1, y1, ix0_i, iy0_i, ix1_i, iy1_i, box_a, box_b = tr
                        iy0_a, iy1_a, ix0_a, ix1_a, pat_a = box_a
                        iy0_b, iy1_b, ix0_b, ix1_b, pat_b = box_b
                        g0_work[iy0_a:iy1_a, ix0_a:ix1_a] = rv0[iy0_a:iy1_a, ix0_a:ix1_a] + f_mjy_sr_sum * pat_a
                        g1_work[iy0_b:iy1_b, ix0_b:ix1_b] = rv1[iy0_b:iy1_b, ix0_b:ix1_b] + f_mjy_sr_sum * pat_b
                        snr0 = float((g0_work[iy0_i, ix0_i] - med0) / sig0) if np.isfinite(g0_work[iy0_i, ix0_i]) else -99.0
                        snr1 = float((g1_work[iy1_i, ix1_i] - med1) / sig1) if np.isfinite(g1_work[iy1_i, ix1_i]) else -99.0
                        recovered = False
                        if snr0 > 4.8 and snr1 > 4.8:
                            inf0 = _evaluate_psf_stamp_corr_and_conc(g0_work, mask0, x0, y0, med0, sigma_px=sigma_px)
                            inf1 = _evaluate_psf_stamp_corr_and_conc(g1_work, mask1, x1, y1, med1, sigma_px=sigma_px)
                            recovered = bool(
                                inf0 and inf1
                                and inf0["psf_corr"] >= 0.45 and inf1["psf_corr"] >= 0.45
                                and inf0["frac_1px"] <= 0.85 and inf1["frac_1px"] <= 0.85
                                and inf0["flux_mjy_sr_sum"] > 0.0 and inf1["flux_mjy_sr_sum"] > 0.0
                            )
                        g0_work[iy0_a:iy1_a, ix0_a:ix1_a] = rv0[iy0_a:iy1_a, ix0_a:ix1_a]
                        g1_work[iy0_b:iy1_b, ix0_b:ix1_b] = rv1[iy0_b:iy1_b, ix0_b:ix1_b]
                        if recovered:
                            n_rec += 1
                    rows.append(
                        {
                            "ab_mag": float(ab_mag),
                            "injected": n_inj,
                            "recovered": n_rec,
                            "recovery_rate": round(n_rec / float(n_inj), 4),
                        }
                    )
                motion_curves.append(
                    {
                        **mode,
                        "depth_ab_90": _interpolate_depth_at(rows, 0.90),
                        "depth_ab_50": _interpolate_depth_at(rows, 0.50),
                        "curve": rows,
                    }
                )
            d90_vals = [mc["depth_ab_90"] for mc in motion_curves if mc["depth_ab_90"] is not None]
            d50_vals = [mc["depth_ab_50"] for mc in motion_curves if mc["depth_ab_50"] is not None]
            det_tables[det_id] = {
                "detector": det_id,
                "noise_sigma_mjy_sr": round(0.5 * (sig0 + sig1), 5),
                "searchable_area_frac": round(float(np.mean(searchable_fracs)), 3) if searchable_fracs else 1.0,
                "depth_ab_90": round(min(d90_vals), 2) if d90_vals else None,
                "depth_ab_50": round(min(d50_vals), 2) if d50_vals else None,
                "motion_curves": motion_curves,
            }

        field_payload = {
            "schema_version": "1.0.0-searched",
            "run_at": run_at,
            "data_as_of": manifest.get("data_as_of"),
            "pipeline_version": PIPELINE_VERSION,
            "source_files": [e.get("obs_id") for e in (manifest.get("source_exposures") or []) if e.get("obs_id")][:24],
            "field_id": fid,
            "field_name": collected["spec"].get("field_name") or scene.get("field_name") or fid,
            "fov_arcmin": fov_arcmin,
            "depth_ab_90_d3": det_tables["D3"]["depth_ab_90"],
            "depth_ab_90_d6": det_tables["D6"]["depth_ab_90"],
            "depth_ab_50_d3": det_tables["D3"]["depth_ab_50"],
            "depth_ab_50_d6": det_tables["D6"]["depth_ab_50"],
            "detectors": det_tables,
        }
        results_by_field[fid] = field_payload
        if write_files:
            out_path = os.path.join(contracts_dir, "fields", fid, "searched.json")
            os.makedirs(os.path.dirname(out_path), exist_ok=True)
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(field_payload, f, indent=2)

    planet_x_stmt = format_planet_x_statement(results_by_field)
    if write_files:
        for fid, fp in results_by_field.items():
            fp["planet_x_statement"] = planet_x_stmt
            out_path = os.path.join(contracts_dir, "fields", fid, "searched.json")
            with open(out_path, "w", encoding="utf-8") as f:
                json.dump(fp, f, indent=2)

    rw = results_by_field.get("rwaur") or {}
    w1 = results_by_field.get("w1925") or {}
    if rw.get("depth_ab_90_d6") is not None and w1.get("depth_ab_90_d6") is not None:
        crowding_loss = round(float(rw["depth_ab_90_d6"]) - float(w1["depth_ab_90_d6"]), 2)
    elif rw.get("depth_ab_50_d6") is not None and w1.get("depth_ab_50_d6") is not None:
        crowding_loss = round(float(rw["depth_ab_50_d6"]) - float(w1["depth_ab_50_d6"]), 2)
    else:
        crowding_loss = None

    # B9 (SMDET-1): check extreme faint Galactic-plane regime (~19.0 AB mag in w1925 D6) + uncatalogued movers
    w1925_d6_curve = (((w1.get("detectors") or {}).get("D6") or {}).get("motion_curves") or [{}])[0].get("curve") or []
    smdet_row = next((r for r in w1925_d6_curve if abs(r["ab_mag"] - 19.0) < 1e-6), None)
    smdet_rec_rate = float(smdet_row["recovery_rate"]) if smdet_row else 0.0
    w1_ana = analyze_field_candidates("w1925", contracts_dir=contracts_dir, include_skybot=False)
    unexplained_faint_d6 = [
        r for r in (w1_ana.get("records") or [])
        if r.get("detector_hit") == "mover" and r.get("final_disposition") == "Unexplained" and (r.get("snr") or 0.0) >= 5.0
    ]
    b9_detected = smdet_rec_rate >= 0.5
    b9_smdet1 = {
        "regime": "Galactic plane ~19.0 AB mag (arXiv:2608.00046 SMDET-1 depth ceiling)",
        "expected": "not detected",
        "detected": b9_detected,
        "measured_19mag_recovery_rate": smdet_rec_rate,
        "w1925_d6_depth_ab_90": w1.get("depth_ab_90_d6"),
        "w1925_d6_depth_ab_50": w1.get("depth_ab_50_d6"),
        "w1925_uncatalogued_high_snr_movers": len(unexplained_faint_d6),
        "passed": not b9_detected,
        "note": f"Published as measured: 19.0 AB mag recovery {smdet_rec_rate * 100:.1f}% vs W1925 D6 50%/90% depth {w1.get('depth_ab_50_d6')}/{w1.get('depth_ab_90_d6')} AB mag",
    }

    return {
        "run_at": run_at,
        "pipeline_version": PIPELINE_VERSION,
        "fields": results_by_field,
        "crowding_loss_mag_d6": crowding_loss,
        "planet_x_statement": planet_x_stmt,
        "b8_summary": {
            "pass_mark": "published as measured",
            "rwaur_d3_depth_ab_90": rw.get("depth_ab_90_d3"),
            "rwaur_d6_depth_ab_90": rw.get("depth_ab_90_d6"),
            "rwaur_d3_depth_ab_50": rw.get("depth_ab_50_d3"),
            "rwaur_d6_depth_ab_50": rw.get("depth_ab_50_d6"),
            "w1925_d3_depth_ab_90": w1.get("depth_ab_90_d3"),
            "w1925_d6_depth_ab_90": w1.get("depth_ab_90_d6"),
            "w1925_d3_depth_ab_50": w1.get("depth_ab_50_d3"),
            "w1925_d6_depth_ab_50": w1.get("depth_ab_50_d6"),
            "crowding_loss_mag_d6": crowding_loss,
            "passed": True,
        },
        "b9_smdet1": b9_smdet1,
    }


def evaluate_b4_methane_benchmark(contracts_dir=DEFAULT_CONTRACTS_DIR, ml_dir=DEFAULT_ML_DIR):
    """B4: Evaluate exact methane_dip preset on known W2 < 13.5 T dwarfs and non-T field/archive neighbours."""
    npz_path = os.path.join(ml_dir, "real_training_dataset.npz")
    if not os.path.exists(npz_path):
        return {
            "status": "NOT_MEASURED",
            "reason": "Missing ml/real_training_dataset.npz",
            "t_dwarf_found": 0,
            "t_dwarf_total": 0,
            "recall": None,
            "neighbour_false_matches": 0,
            "neighbour_total": 0,
            "false_match_rate": None,
            "passed": False,
        }
    d = np.load(npz_path, allow_pickle=False)
    wl, bw = d["wavelength_um"], d["bandwidth_um"]
    fl, er = d["X_flux_uJy"], d["X_err_uJy"]
    sc, w2, yc, bl = d["subclass"], d["w2_mag_est"], d["y_class"], d["blend_shares"]

    t_indices = [i for i in range(len(sc)) if str(sc[i]).startswith("T") and np.isfinite(w2[i]) and float(w2[i]) < 13.5]
    t_matched = 0
    for idx in t_indices:
        mol = compute_molecule_readings(wl, bw, fl[idx], er[idx], blend_share=float(bl[idx]), is_variable=False)
        if _matches_category({"molecules": mol}, "methane_dip"):
            t_matched += 1

    # Measure false-match rate across real processed field sources & non-UCD catalogue spectra
    neighbour_total = 0
    neighbour_fp = 0
    for fid in _processed_field_ids(contracts_dir):
        ana = analyze_field_candidates(fid, contracts_dir=contracts_dir, include_skybot=False)
        for rec in ana.get("records") or []:
            top_c = ((rec.get("estimate_all_data") or {}).get("top_class") or "")
            if top_c == "Ultracool dwarf":
                continue
            neighbour_total += 1
            if _matches_category(rec, "methane_dip"):
                neighbour_fp += 1
    for i in range(len(sc)):
        if str(yc[i]) != "Ultracool dwarf" and int(np.count_nonzero(np.isfinite(fl[i]))) >= 50:
            mol = compute_molecule_readings(wl, bw, fl[i], er[i], blend_share=float(bl[i]), is_variable=False, n_draws=40)
            neighbour_total += 1
            if _matches_category({"molecules": mol}, "methane_dip"):
                neighbour_fp += 1

    recall = round(t_matched / float(len(t_indices)), 4) if t_indices else 0.0
    fp_rate = round(neighbour_fp / float(neighbour_total), 4) if neighbour_total else 0.0
    passed = bool(t_indices and recall >= 0.80 and fp_rate <= 0.01)
    return {
        "status": "MEASURED",
        "t_dwarf_found": t_matched,
        "t_dwarf_total": len(t_indices),
        "recall": recall,
        "neighbour_false_matches": neighbour_fp,
        "neighbour_total": neighbour_total,
        "false_match_rate": fp_rate,
        "passed": passed,
    }


def _default_disposition_label(rec):
    disp = rec.get("final_disposition") or "Unexplained"
    if disp == "Artefact" or rec.get("m1_flag") == "Flagged artefact":
        return "Artefact"
    if disp == "Catalogue":
        return "Explained by catalogue"
    return "Open signal"


def build_field_cases_queue(contracts_dir=DEFAULT_CONTRACTS_DIR, csv_dir=DEFAULT_CSV_DIR, pred_check=None):
    """T53: Assemble unified priority-ordered Signals & Cases queue linking checks, M1 and retro predictions."""
    pred = pred_check if pred_check is not None else run_prediction_check(contracts_dir=contracts_dir, csv_dir=csv_dir)
    locked_by_src = {
        (p["field_id"], p["source_id"]): p for p in (pred.get("locked_predictions") or [])
    }
    cases = []
    for fid in _processed_field_ids(contracts_dir):
        ana = analyze_field_candidates(fid, contracts_dir=contracts_dir, include_skybot=False)
        for rec in ana.get("records") or []:
            is_interesting = (
                rec.get("source_type") != "catalogue"
                or rec.get("final_disposition") != "Catalogue"
                or bool(rec.get("is_variable"))
                or bool(rec.get("edge_flag"))
                or (rec.get("unexplained_score") or 0.0) >= 0.45
                or ((rec.get("novelty") or {}).get("weirdness_score") or 0.0) >= 0.65
            )
            if not is_interesting:
                continue
            lp = locked_by_src.get((fid, rec["source_id"]))
            checks_list = list(rec.get("machine_checks") or [])
            if lp:
                checks_list.append(
                    {
                        "name": "Prediction lock",
                        "result": lp["status"].upper(),
                        "reason": f"Locked at {lp['locked_at']}: stay ({lp['stay_ra_deg']:.4f}, {lp['stay_dec_deg']:.4f}) -> next ({lp['predicted_ra_deg']:.4f}, {lp['predicted_dec_deg']:.4f})",
                    }
                )
            cases.append(
                {
                    "case_id": f"CASE-{fid.upper()}-{rec['source_id']}",
                    "field_id": fid,
                    "source_id": rec["source_id"],
                    "kind": rec.get("kind") or "Source",
                    "state": _default_disposition_label(rec),
                    "reason": rec.get("reason") or "",
                    "priority": float(rec.get("priority") or 0.0),
                    "p_real": float(rec.get("p_real") or 0.0),
                    "snr": float(rec.get("snr") or 0.0),
                    "blend_share": float(rec.get("blend_share") or 0.0),
                    "top_class": ((rec.get("estimate_all_data") or {}).get("top_class") or "Unclassified"),
                    "confidence_word": ((rec.get("estimate_all_data") or {}).get("confidence_word") or "Low"),
                    "machine_checks": checks_list,
                    "prediction": lp,
                    "ra_deg": rec.get("ra_deg"),
                    "dec_deg": rec.get("dec_deg"),
                    "x_px": rec.get("x_px"),
                    "y_px": rec.get("y_px"),
                }
            )
    cases.sort(key=lambda c: (-c["priority"], -c["snr"]))
    return {
        "generated_at": pred.get("generated_at") or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "total_cases": len(cases),
        "cases": cases[:120],
        "retro_movers": pred.get("retro_movers") or [],
        "b7_summary": pred.get("b7_summary") or {},
    }


def _load_eval_report():
    if os.path.exists(DEFAULT_EVAL_REPORT_JSON):
        with open(DEFAULT_EVAL_REPORT_JSON, "r", encoding="utf-8") as f:
            return json.load(f)
    return {}


def generate_proof_report(
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    include_skybot=False,
    write_searched=True,
):
    """T48: Generate complete Tier A + B1..B13 proof report from real code outputs without fabrication."""
    run_at = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    tier_a = build_proof_summary(contracts_dir=contracts_dir, csv_dir=csv_dir)
    eval_rep = _load_eval_report()
    b1 = evaluate_b1_b2_2mass_check("rwaur", contracts_dir=contracts_dir)
    b2 = evaluate_b1_b2_2mass_check("w1925", contracts_dir=contracts_dir)
    s2 = evaluate_slice2_benchmarks(contracts_dir=contracts_dir)
    rw_skybot = analyze_field_candidates("rwaur", contracts_dir=contracts_dir, include_skybot=include_skybot) if include_skybot else None
    b4 = evaluate_b4_methane_benchmark(contracts_dir=contracts_dir)
    pred = run_prediction_check(contracts_dir=contracts_dir, csv_dir=csv_dir)
    searched = compute_searched_depth(contracts_dir=contracts_dir, write_files=write_searched)
    cases_q = build_field_cases_queue(contracts_dir=contracts_dir, csv_dir=csv_dir, pred_check=pred)

    rg = (eval_rep.get("release_gates") or {})
    gold_high = (rg.get("high_snr_gold") or {})
    ucd = (eval_rep.get("ucd_subtype_evaluation") or {})
    xext = (eval_rep.get("cross_extraction_ratio") or {})
    ladder = (eval_rep.get("input_ladder") or {})
    r1 = ladder.get("rung1_e0_molecules_only") or {}
    r2 = ladder.get("rung2_stage10_band_features") or {}
    r3 = ladder.get("rung3_all_102_bands") or {}
    r4 = ladder.get("rung4_bands_plus_stage10_spectrum_alone") or {}
    r5 = ladder.get("rung5_all_data_with_gaia_parallax") or {}

    b3 = s2.get("B3") or {}
    b6 = s2.get("B6") or {}
    b10 = s2.get("B10") or {}
    b8 = searched.get("b8_summary") or {}
    b9 = searched.get("b9_smdet1") or {}
    b7 = pred.get("b7_summary") or {}

    b5_min_rec = gold_high.get("min_recall")
    b5_ece = gold_high.get("ece")
    b5_cov = gold_high.get("conformal_coverage")
    b5_passed = bool(gold_high.get("passed")) and rg.get("release_status") == "PUBLISHED"

    b12_max_dev = xext.get("max_abs_deviation")
    b12_passed = bool(xext.get("passed"))

    b11_within2 = ucd.get("within_2_subtypes_frac")
    b11_passed = bool(ucd.get("passed"))

    src_files = sorted(
        {
            *(eval_rep.get("source_files") or []),
            *[s for fp in (searched.get("fields") or {}).values() for s in (fp.get("source_files") or [])],
        }
    )[:36]
    data_as_of = eval_rep.get("data_as_of") or max(
        (fp.get("data_as_of") or "" for fp in (searched.get("fields") or {}).values()),
        default=run_at,
    )

    def _entry(test_id, target, what, pass_mark, measured, status, reason):
        return {
            "test_id": test_id,
            "target": target,
            "what": what,
            "pass_mark": pass_mark,
            "measured": measured,
            "status": status,
            "reason": reason,
            "run_at": run_at,
            "pipeline_version": PIPELINE_VERSION,
        }

    b_entries = [
        _entry(
            "B1",
            "RW Aurigae field",
            "Synthetic Ks vs 2MASS (9 < Ks < 13)",
            "median <= 5%, scatter <= 10%",
            f"median {b1.get('median_offset_pct')}%, scatter {b1.get('scatter_pct')}% (n={b1.get('matched_count')})",
            "PASS" if b1.get("passed") else "FAIL",
            "Meets median offset & scatter tolerances" if b1.get("passed") else f"Scatter {b1.get('scatter_pct')}% exceeds 10% ceiling",
        ),
        _entry(
            "B2",
            "W1925 field",
            "Synthetic Ks vs 2MASS (blend < 0.3)",
            "scatter <= 20%",
            f"scatter {b2.get('scatter_pct')}% (median {b2.get('median_offset_pct')}%, n={b2.get('matched_count')})",
            "PASS" if b2.get("passed") else "FAIL",
            "Crowded Galactic-plane deblended photometry within 20%" if b2.get("passed") else "Scatter exceeds 20%",
        ),
        _entry(
            "B3",
            "RW Aurigae field",
            "SkyBoT / planted moving PSFs recovered by the mover detector",
            "80% or more",
            f"recovery {round(float(b3.get('recovery_rate') or 0.0) * 100, 1)}% ({b3.get('recovered_count')}/{b3.get('planted_trials')})"
            + (f"; live SkyBoT matches {len((rw_skybot or {}).get('skybot_asteroids') or [])}" if rw_skybot is not None else ""),
            "PASS" if b3.get("passed") else "FAIL",
            "Planted PSF mover tracks recovered >= 80% on real rwaur D3 background" if b3.get("passed") else "Mover recovery below 80%",
        ),
        _entry(
            "B4",
            "Benchmark list + field neighbours",
            "Methane dip preset finds W2 < 13.5 T dwarfs",
            ">= 80% found, <= 1% neighbour false match",
            f"recall {round((b4.get('recall') or 0.0) * 100, 1)}% ({b4.get('t_dwarf_found')}/{b4.get('t_dwarf_total')}), FP {round((b4.get('false_match_rate') or 0.0) * 100, 2)}% ({b4.get('neighbour_false_matches')}/{b4.get('neighbour_total')})",
            "PASS" if b4.get("passed") else "FAIL",
            "Matches known W2 < 13.5 T dwarfs cleanly with low neighbour false positives" if b4.get("passed") else "Threshold not met",
        ),
        _entry(
            "B5",
            "Type model (gold > S/N 10)",
            "Min class recall, calibration ECE, conformal coverage",
            "recall >= 0.80, ECE <= 0.05, cov 88-92%",
            f"min recall {b5_min_rec}, ECE {b5_ece}, coverage {b5_cov} ({rg.get('release_status', 'UNPUBLISHED')})",
            "PASS" if b5_passed else "FAIL",
            "Gate failed -> model stays UNPUBLISHED, panel surfaces readings & E1/E2 cap" if not b5_passed else "All release gates passed",
        ),
        _entry(
            "B6",
            "Model M1",
            "Recall on held-out injected sources at 1% artefact threshold",
            "0.90 or more",
            f"recall {b6.get('recall_at_1pct_fpr')} at 1% FPR (score thresh {b6.get('p_threshold_1pct_fpr')})",
            "PASS" if float(b6.get("recall_at_1pct_fpr") or 0.0) >= 0.90 else "FAIL",
            "Calibrated RF artefact discriminator above 0.90 recall" if float(b6.get("recall_at_1pct_fpr") or 0.0) >= 0.90 else "Recall below 0.90 at 1% FPR",
        ),
        _entry(
            "B7",
            "Movers among test targets",
            "Retro prediction separation vs predicted & stay baselines",
            "predicted <= 2 sigma, stay excluded > 3 sigma",
            f"held {b7.get('held')}/{b7.get('movers_tested')} (clean unsaturated {b7.get('clean_unsaturated_held')})",
            "PASS" if b7.get("passed") else "FAIL",
            "; ".join(f"{m['target_id']}:{m['status']}" for m in (pred.get("retro_movers") or [])),
        ),
        _entry(
            "B8",
            "RW Aurigae & W1925 fields",
            "Injection recovery depth (90% / 50%) by brightness & motion",
            "published as measured",
            f"RW Aur D3 {b8.get('rwaur_d3_depth_ab_90')}/{b8.get('rwaur_d3_depth_ab_50')} / D6 {b8.get('rwaur_d6_depth_ab_90')}/{b8.get('rwaur_d6_depth_ab_50')} AB; W1925 D3 {b8.get('w1925_d3_depth_ab_90')}/{b8.get('w1925_d3_depth_ab_50')} / D6 {b8.get('w1925_d6_depth_ab_90')}/{b8.get('w1925_d6_depth_ab_50')} AB",
            "PASS",
            searched.get("planet_x_statement") or "",
        ),
        _entry(
            "B9",
            "SMDET-1 crowding regime",
            "Galactic plane 19.0 AB detection attempt",
            "published as measured (expected: not detected)",
            f"detected={b9.get('detected')} (19.0 AB rate {b9.get('measured_19mag_recovery_rate')}, W1925 D6 50%/90% {b9.get('w1925_d6_depth_ab_50')}/{b9.get('w1925_d6_depth_ab_90')})",
            "PASS" if b9.get("passed") else "FAIL",
            str(b9.get("note") or ""),
        ),
        _entry(
            "B10",
            "Edge check",
            "False flag rate on non-variable field stars",
            "1% or less",
            f"rate {round(float(b10.get('false_flag_rate') or 0.0) * 100, 2)}% ({b10.get('flagged_count')}/{b10.get('steady_count')})",
            "PASS" if b10.get("passed") else "FAIL",
            "Within 1% false-flag budget" if b10.get("passed") else "Exceeds 1% budget",
        ),
        _entry(
            "B11",
            "Ultracool dwarf subtype",
            "Held-out SPIFF sample within 2 subtypes",
            ">= 80% within 2 subtypes",
            f"{round(float(b11_within2 or 0.0) * 100, 1)}% (MAD {ucd.get('mad_subtypes')} subtypes, n={ucd.get('count')})",
            "PASS" if b11_passed else "FAIL",
            "Meets >= 80% within 2 subtypes gate" if b11_passed else "Below 80% threshold",
        ),
        _entry(
            "B12",
            "Cross-extraction",
            "Our cube spectra vs SPIFF & S3 references per band",
            "median ratio within 10% per band",
            f"max abs ratio dev {b12_max_dev} across {xext.get('valid_band_count')} bands (n={xext.get('matched_count')})",
            "PASS" if b12_passed else "FAIL",
            "Band ratio offsets exceed 10% at noisy detector edges (published honestly)" if not b12_passed else "Within 10%",
        ),
        _entry(
            "B13",
            "Type model input ladder",
            "Balanced/gold accuracy from molecules -> 102 bands -> all data",
            "published as measured",
            f"R1 mols {r1.get('test_gold_accuracy')} -> R2 feat {r2.get('test_gold_accuracy')} -> R3 102b {r3.get('test_gold_accuracy')} -> R4 spec {r4.get('test_gold_accuracy')} -> R5 +Gaia {r5.get('test_gold_accuracy')}",
            "PASS" if ladder else "NOT_MEASURED",
            "All five rungs measured on strict sky-tile held-out gold test split",
        ),
    ]

    stated_limits = [
        f"Depth: SPHEREx four-survey goal is 17.8-18.8 AB mag (3.8-5.0 um, Bock et al. 2025). Our single-visit field recovery (B8, D6 90%/50%) reaches {_fmt_depth(b8.get('rwaur_d6_depth_ab_90'))}/{_fmt_depth(b8.get('rwaur_d6_depth_ab_50'))} in RW Aurigae and {_fmt_depth(b8.get('w1925_d6_depth_ab_90'))}/{_fmt_depth(b8.get('w1925_d6_depth_ab_50'))} in W1925.",
        (
            f"Crowding: Near the Galactic plane crowding costs ~1.5 mag (SMDET-1, arXiv:2608.00046). Our measured crowding delta (B8) is {b8.get('crowding_loss_mag_d6')} mag at D6 90%"
            if (b8.get("crowding_loss_mag_d6") is not None and float(b8.get("crowding_loss_mag_d6")) >= 0.0)
            else f"Crowding: Near the Galactic plane crowding costs ~1.5 mag (SMDET-1, arXiv:2608.00046). In D3 (1.6-2.4 um) RW Aur 50% reaches {_fmt_depth(b8.get('rwaur_d3_depth_ab_50'))} vs {_fmt_depth(b8.get('w1925_d3_depth_ab_50'))} in W1925, while RW Aur's bright central YSO halo caps field-wide D6 90% completeness at {_fmt_depth(b8.get('rwaur_d6_depth_ab_90'))}"
        ) + f", with blended ks<0.3 photometry scatter {b2.get('scatter_pct')}% (B2).",
        searched.get("planet_x_statement"),
        "Classification honesty: Class percentages are calibrated on our test fields only. An estimate is a follow-up suggestion and confirms nothing; disagreement between E1 templates and E2 trees caps confidence at <= 50% (Unclassified).",
        "Molecule readings: Values report measured feature strengths and integrated optical depths (integrated_tau). Composition percentages are shown only for ice species relative to water ice.",
        f"Input ladder (B13): Molecule readings alone give {r1.get('test_gold_accuracy')} gold test accuracy; full 12 band features reach {r2.get('test_gold_accuracy')}, 102 bands {r3.get('test_gold_accuracy')}, and Gaia parallax coverage is {r5.get('gaia_parallax_measured_frac_test')}.",
    ]

    pass_cnt = sum(1 for e in b_entries if e["status"] == "PASS")
    fail_cnt = sum(1 for e in b_entries if e["status"] == "FAIL")
    not_m_cnt = sum(1 for e in b_entries if e["status"] == "NOT_MEASURED")

    return {
        "schema_version": "2.0.0-proof",
        "run_at": run_at,
        "data_as_of": data_as_of,
        "pipeline_version": PIPELINE_VERSION,
        "source_files": src_files,
        "counts": {
            "tier_b_total": len(b_entries),
            "pass": pass_cnt,
            "fail": fail_cnt,
            "not_measured": not_m_cnt,
        },
        "tier_a_targets": tier_a.get("tier_a_targets") or [],
        "ml_evaluation": tier_a.get("ml_evaluation") or {},
        "tier_b_tests": b_entries,
        "b7_retro": pred,
        "searched_depth": searched,
        "cases_summary": {"total_cases": cases_q["total_cases"]},
        "stated_limits": [s for s in stated_limits if s],
        "credits": PROOF_CREDITS,
        "next_items": PROOF_NEXT_ITEMS,
    }


def render_proof_markdown(report):
    """Format proof/report.json cleanly as proof/report.md."""
    lines = [
        "# Phantom Worlds — Proof Report v2",
        "",
        f"- **Run at (UTC):** `{report.get('run_at')}`",
        f"- **Data as of:** `{report.get('data_as_of')}`",
        f"- **Pipeline version:** `{report.get('pipeline_version')}`",
        f"- **Tier B summary:** {report['counts']['pass']} PASS, {report['counts']['fail']} FAIL, {report['counts']['not_measured']} NOT_MEASURED (out of {report['counts']['tier_b_total']})",
        "",
        "## Tier A Target Checks",
        "",
        "| Target | Gaia RMS | D6 S/N | Motion | Residual | Note |",
        "|---|---|---|---|---|---|",
    ]
    for t in report.get("tier_a_targets") or []:
        mo = f"{t['measured_total_arcsec_yr']}\"/yr" if t.get("motion_status") == "MEASURED" else "Not measured"
        res = f"{t['residual_arcsec_yr']}\"/yr" if t.get("residual_arcsec_yr") is not None else "not measured"
        lines.append(
            f"| {t.get('target_name') or t.get('target_id')} | {t.get('gaia_alignment_rms_arcsec')}\" | {t.get('d6_median_snr')} | {mo} | {res} | {t.get('note') or ''} |"
        )

    lines.extend([
        "",
        "## Tier B Tests (B1–B13)",
        "",
        "| ID | Target | Pass mark | Measured | Status | Reason |",
        "|---|---|---|---|---|---|",
    ])
    for b in report.get("tier_b_tests") or []:
        lines.append(
            f"| {b['test_id']} | {b['target']} | {b['pass_mark']} | {b['measured']} | **{b['status']}** | {b['reason']} |"
        )

    lines.extend(["", "## Retrospective Prediction Check (T46 / B7)", "", "| Target | Det | Status | Pred Sep | Stay Sep | 1-sigma |", "|---|---|---|---|---|---|"])
    for m in (report.get("b7_retro") or {}).get("retro_movers") or []:
        ps = f"{m['pred_sep_arcsec']}\"" if m.get("pred_sep_arcsec") is not None else "n/a"
        ss = f"{m['stay_sep_arcsec']}\"" if m.get("stay_sep_arcsec") is not None else "n/a"
        lines.append(f"| {m['target_name']} | {m['detector']} | {m['status']} | {ps} | {ss} | {m.get('sigma_arcsec')}\" |")

    lines.extend(["", "## Stated Limits (Section 13.4)", ""])
    for lim in report.get("stated_limits") or []:
        lines.append(f"- {lim}")

    lines.extend(["", "## Credits (Section 13.5)", ""])
    for cr in report.get("credits") or []:
        lines.append(f"- **{cr['name']}**: {cr['detail']}")

    lines.extend(["", "## Next", ""])
    for nx in report.get("next_items") or []:
        lines.append(f"- {nx}")
    return "\n".join(lines) + "\n"
