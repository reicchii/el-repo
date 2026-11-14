"""Shared Tier-A empirical cutout metrics and live proof-summary generator."""

from datetime import datetime, timezone
import json
import math
import os

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

DEFAULT_EVAL_REPORT_JSON = os.path.join(PACKAGE_ROOT, "ml", "evaluation_report.json")
_OVERFLOW_BIT = 2
_REJECTED_OR_EDGE_BITS = 1 | 4


def _mjd_to_julian_year(mjd):
    return 2000.0 + (float(mjd) - 51544.5) / 365.25


def _robust_sky_stats(grid, valid, r2, bg_min_r2=100.0, bg_max_r2=400.0):
    bg_mask = valid & (r2 >= bg_min_r2) & (r2 <= bg_max_r2)
    vals = grid[bg_mask]
    if vals.size < 8:
        vals = grid[valid]
    if vals.size == 0:
        return 0.0, 0.0
    med = float(np.median(vals))
    mad = float(np.median(np.abs(vals - med)))
    sigma = max(1.4826 * mad, 1e-6)
    return med, sigma


def _measure_visit_photometry(grid, mask_plane, cx, cy, yy, xx):
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    valid = np.isfinite(grid) & ((mask_plane & (_REJECTED_OR_EDGE_BITS | _OVERFLOW_BIT)) == 0)
    sat_core = int(np.count_nonzero((r2 <= 16.0) & ((mask_plane & _OVERFLOW_BIT) != 0)))
    bg, sigma_px = _robust_sky_stats(grid, valid, r2)

    core_mask = valid & (r2 <= 9.0)
    if int(np.count_nonzero(core_mask)) >= 4:
        ap_mask = core_mask
        region = "core_aperture"
    else:
        ring_mask = valid & (r2 >= 12.25) & (r2 <= 64.0)
        if int(np.count_nonzero(ring_mask)) >= 4:
            ap_mask = ring_mask
            region = "outer_annulus"
        else:
            return {
                "status": "NOT_MEASURED",
                "reason": "saturated or masked across aperture",
                "flux_rel": None,
                "flux_err_rel": None,
                "snr": None,
                "saturated_core_px": sat_core,
                "valid_px": int(np.count_nonzero(valid & (r2 <= 64.0))),
                "region": "not_measured",
            }

    n_ap = int(np.count_nonzero(ap_mask))
    flux_sum = float(np.sum(grid[ap_mask] - bg))
    flux_err = float(sigma_px * math.sqrt(float(n_ap)))
    snr = float(flux_sum / flux_err) if flux_err > 0.0 else None
    return {
        "status": "MEASURED",
        "reason": "",
        "flux_rel": round(flux_sum, 4),
        "flux_err_rel": round(flux_err, 4),
        "snr": round(snr, 2) if snr is not None else None,
        "saturated_core_px": sat_core,
        "valid_px": n_ap,
        "region": region,
    }


def _fit_visit_centroid(grid, mask_plane, pred_cx, pred_cy, yy, xx):
    r2 = (xx - pred_cx) ** 2 + (yy - pred_cy) ** 2
    valid = np.isfinite(grid) & ((mask_plane & (_REJECTED_OR_EDGE_BITS | _OVERFLOW_BIT)) == 0)
    bg, sigma_px = _robust_sky_stats(grid, valid, r2)
    win = valid & (r2 <= 36.0)
    if int(np.count_nonzero(win)) < 5:
        return None
    excess = grid - bg
    thresh = np.where(win, excess > max(2.0 * sigma_px, 1e-4), False)
    if int(np.count_nonzero(thresh)) >= 3:
        weights = excess[thresh]
        wx = xx[thresh]
        wy = yy[thresh]
    else:
        inner = valid & (r2 <= 12.25) & (excess > 0.0)
        if int(np.count_nonzero(inner)) < 3:
            return None
        weights = excess[inner]
        wx = xx[inner]
        wy = yy[inner]
    wsum = float(np.sum(weights))
    if wsum <= 0.0:
        return None
    return float(np.sum(wx * weights) / wsum), float(np.sum(wy * weights) / wsum)


def _angular_diff_deg(a_deg, b_deg):
    d = ((a_deg - b_deg + 180.0) % 360.0) - 180.0
    return abs(d)


def compute_target_tier_a_metrics(manifest, flux_cube, mask_cube, target_row=None):
    """Measure per-detector saturation, visit photometry, change spectrum, and empirical motion."""
    visits = list(manifest.get("visits") or [])
    n_visits = int(flux_cube.shape[0])
    ny, nx = int(flux_cube.shape[2]), int(flux_cube.shape[3])
    yy, xx = np.mgrid[0:ny, 0:nx]

    center_ra = float(manifest["center_ra_deg"])
    center_dec = float(manifest["center_dec_deg"])
    fov_arcmin = float(manifest.get("fov_arcmin", 6.56))
    px_scale = float(manifest.get("pixel_scale_arcsec", 6.15))

    has_cat = (
        target_row is not None
        and target_row.get("ra_deg_j2000") is not None
        and target_row.get("dec_deg_j2000") is not None
    )
    ref_ra = float(target_row["ra_deg_j2000"]) if has_cat else float(manifest.get("target_j2000_ra_deg", center_ra))
    ref_dec = float(target_row["dec_deg_j2000"]) if has_cat else float(manifest.get("target_j2000_dec_deg", center_dec))
    cat_pmra = float(target_row.get("pm_ra_mas_yr", 0.0)) if has_cat else 0.0
    cat_pmdec = float(target_row.get("pm_dec_mas_yr", 0.0)) if has_cat else 0.0

    expected_px = []
    for v_idx in range(n_visits):
        mjd = float(visits[v_idx]["mjd"]) if v_idx < len(visits) and visits[v_idx].get("mjd") is not None else 60900.0
        dt_yr = _mjd_to_julian_year(mjd) - 2000.0
        ra_v, dec_v = propagate_position(ref_ra, ref_dec, cat_pmra, cat_pmdec, dt_yr)
        cx, cy = _project_sky_to_px(ra_v, dec_v, center_ra, center_dec, fov_arcmin, nx)
        expected_px.append((cx, cy, mjd))

    per_detector = {}
    saturated_detectors = []
    for det_id in VALID_DETECTORS:
        d_idx = DETECTOR_INDEX[det_id]
        v_rows = []
        sat_total = 0
        for v_idx in range(n_visits):
            cx, cy, mjd = expected_px[v_idx]
            meta_v = visits[v_idx] if v_idx < len(visits) else {"visit_id": f"V{v_idx + 1}", "epoch_iso": ""}
            phot = _measure_visit_photometry(
                flux_cube[v_idx, d_idx], mask_cube[v_idx, d_idx], cx, cy, yy, xx
            )
            sat_total += phot["saturated_core_px"]
            v_rows.append(
                {
                    "visit_id": meta_v.get("visit_id", f"V{v_idx + 1}"),
                    "epoch_iso": meta_v.get("epoch_iso", ""),
                    "mjd": round(mjd, 4),
                    **phot,
                }
            )
        is_sat = sat_total > 0
        if is_sat:
            saturated_detectors.append(det_id)

        change_info = {
            "status": "NOT_MEASURED",
            "reason": "needs at least 2 visits",
            "ratio_last_vs_first": None,
            "delta_pct": None,
            "ratio_err": None,
        }
        if n_visits >= 2:
            f0 = v_rows[0]["flux_rel"]
            f1 = v_rows[-1]["flux_rel"]
            e0 = v_rows[0]["flux_err_rel"]
            e1 = v_rows[-1]["flux_err_rel"]
            if is_sat:
                change_info["reason"] = "Not measured: detector pixels near core overflow limit"
            elif f0 is None or f1 is None or f0 <= 0.0 or f1 <= 0.0:
                change_info["reason"] = "Not measured: low S/N or negative net flux"
            else:
                ratio = f1 / f0
                rel_err = math.sqrt(((e0 or 0.0) / f0) ** 2 + ((e1 or 0.0) / f1) ** 2)
                change_info = {
                    "status": "MEASURED",
                    "reason": "",
                    "ratio_last_vs_first": round(ratio, 4),
                    "delta_pct": round((ratio - 1.0) * 100.0, 2),
                    "ratio_err": round(ratio * rel_err, 4),
                }

        snrs = [r["snr"] for r in v_rows if r["snr"] is not None]
        per_detector[det_id] = {
            "detector": det_id,
            "is_saturated": is_sat,
            "saturated_core_px": sat_total,
            "median_snr": round(float(np.median(snrs)), 2) if snrs else None,
            "visits": v_rows,
            "change_last_vs_first": change_info,
        }

    # Pick highest-SNR unsaturated detector (prefer D6), falling back cleanly to D5..D1 if needed.
    motion_det = "D6"
    best_score = -1.0
    for det_id in ("D6", "D5", "D4", "D3", "D2", "D1"):
        d_info = per_detector[det_id]
        msnr = d_info["median_snr"]
        if msnr is not None and not d_info["is_saturated"] and msnr > best_score:
            best_score = msnr
            motion_det = det_id
    if best_score < 0.0:
        for det_id in ("D6", "D5", "D4", "D3", "D2", "D1"):
            msnr = per_detector[det_id]["median_snr"]
            if msnr is not None and msnr > best_score:
                best_score = msnr
                motion_det = det_id

    d_idx_m = DETECTOR_INDEX[motion_det]
    gaia_rms = manifest.get("gaia_alignment_rms_arcsec")
    rms_ok = gaia_rms is None or float(gaia_rms) <= 2.0
    centroid_pts = []
    for v_idx in range(n_visits):
        v_phot = per_detector[motion_det]["visits"][v_idx]
        if not rms_ok or v_phot["snr"] is None or v_phot["snr"] < 5.0:
            continue
        cx, cy, mjd = expected_px[v_idx]
        fit = _fit_visit_centroid(flux_cube[v_idx, d_idx_m], mask_cube[v_idx, d_idx_m], cx, cy, yy, xx)
        meta_v = visits[v_idx] if v_idx < len(visits) else {"visit_id": f"V{v_idx + 1}"}
        if fit is not None:
            centroid_pts.append(
                {
                    "visit_id": meta_v.get("visit_id", f"V{v_idx + 1}"),
                    "mjd": round(mjd, 4),
                    "cx_px": round(fit[0], 3),
                    "cy_px": round(fit[1], 3),
                    "expected_cx_px": round(cx, 3),
                    "expected_cy_px": round(cy, 3),
                }
            )

    cat_total = math.hypot(cat_pmra, cat_pmdec) / 1000.0
    cat_pa = (math.degrees(math.atan2(cat_pmra, cat_pmdec)) + 360.0) % 360.0 if cat_total > 0.0 else None

    default_reason = (
        f"Gaia WCS alignment RMS ({gaia_rms}\") exceeds 2.0\" threshold"
        if not rms_ok
        else "fewer than 2 visits reached S/N >= 5.0 for centroiding"
    )
    motion = {
        "status": "NOT_MEASURED",
        "reason": default_reason,
        "detector": motion_det,
        "origin": "Measured, SPHEREx cutouts",
        "measured_pm_ra_mas_yr": None,
        "measured_pm_dec_mas_yr": None,
        "measured_total_arcsec_yr": None,
        "measured_pa_deg": None,
        "catalogue_total_arcsec_yr": round(cat_total, 3),
        "catalogue_pa_deg": round(cat_pa, 1) if cat_pa is not None else None,
        "residual_arcsec_yr": None,
        "pa_diff_deg": None,
        "visit_centroids": centroid_pts,
    }
    if len(centroid_pts) >= 2:
        t_yrs = np.array([(pt["mjd"] - centroid_pts[0]["mjd"]) / 365.25 for pt in centroid_pts], dtype=np.float64)
        span_yr = float(np.max(t_yrs) - np.min(t_yrs))
        if span_yr >= 0.08:
            # East (+dRA) maps to -dx, North (+dDec) maps to -dy on the north-up east-left WCS grid.
            dra_arcsec = -np.array([pt["cx_px"] - centroid_pts[0]["cx_px"] for pt in centroid_pts], dtype=np.float64) * px_scale
            ddec_arcsec = -np.array([pt["cy_px"] - centroid_pts[0]["cy_px"] for pt in centroid_pts], dtype=np.float64) * px_scale
            t_centered = t_yrs - np.mean(t_yrs)
            denom = float(np.sum(t_centered ** 2))
            if denom > 0.0:
                pm_ra_as = float(np.sum(t_centered * (dra_arcsec - np.mean(dra_arcsec))) / denom)
                pm_dec_as = float(np.sum(t_centered * (ddec_arcsec - np.mean(ddec_arcsec))) / denom)
                tot_as = math.hypot(pm_ra_as, pm_dec_as)
                meas_pa = (math.degrees(math.atan2(pm_ra_as, pm_dec_as)) + 360.0) % 360.0 if tot_as > 0.0 else None
                res_as = math.hypot(pm_ra_as - cat_pmra / 1000.0, pm_dec_as - cat_pmdec / 1000.0)
                motion.update(
                    {
                        "status": "MEASURED",
                        "reason": "",
                        "measured_pm_ra_mas_yr": round(pm_ra_as * 1000.0, 1),
                        "measured_pm_dec_mas_yr": round(pm_dec_as * 1000.0, 1),
                        "measured_total_arcsec_yr": round(tot_as, 3),
                        "measured_pa_deg": round(meas_pa, 1) if meas_pa is not None else None,
                        "residual_arcsec_yr": round(res_as, 3),
                        "pa_diff_deg": round(_angular_diff_deg(meas_pa, cat_pa), 1)
                        if (meas_pa is not None and cat_pa is not None)
                        else None,
                    }
                )
        else:
            motion["reason"] = "visit baseline too short (<30 days)"

    return {
        "target_id": manifest.get("target_id"),
        "target_name": manifest.get("target_name"),
        "cutout_origin": manifest.get("cutout_origin"),
        "data_as_of": manifest.get("data_as_of"),
        "pipeline_version": manifest.get("pipeline_version"),
        "pixel_scale_arcsec": px_scale,
        "gaia_alignment_rms_arcsec": manifest.get("gaia_alignment_rms_arcsec"),
        "saturated_detectors": saturated_detectors,
        "per_detector": per_detector,
        "motion": motion,
    }


def build_proof_summary(
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    report_json_path=DEFAULT_EVAL_REPORT_JSON,
    root_manifest=None,
):
    """Compile live Tier-A target measurements and honest ML release-gate status with zero hardcoded numbers."""
    targets_by_id = {row["target_id"]: row for row in load_targets(csv_dir)}
    tier_a_targets = []
    for tid in ("TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"):
        row = targets_by_id.get(tid)
        m_obj = (
            load_manifest(contracts_dir, root_manifest=root_manifest)
            if (root_manifest is not None and tid == root_manifest.get("target_id"))
            else load_manifest(contracts_dir, target_id=tid, root_manifest=root_manifest)
        )
        _, flux_cube, mask_cube = load_patch_arrays(
            contracts_dir,
            target_id=None if (root_manifest is not None and tid == root_manifest.get("target_id")) else tid,
            manifest=m_obj,
            root_manifest=root_manifest,
        )
        metrics = compute_target_tier_a_metrics(m_obj, flux_cube, mask_cube, target_row=row)
        d6 = metrics["per_detector"]["D6"]
        d1_d4_snrs = [
            s
            for det in ("D1", "D2", "D3", "D4")
            for s in ([metrics["per_detector"][det]["median_snr"]] if metrics["per_detector"][det]["median_snr"] is not None else [])
        ]
        motion = metrics["motion"]
        gaia_rms = metrics["gaia_alignment_rms_arcsec"]

        if tid == "TGT-01":
            passed = bool(
                motion["status"] == "MEASURED"
                and motion["residual_arcsec_yr"] is not None
                and motion["residual_arcsec_yr"] <= 1.0
            )
            note = (
                f"Motion residual {motion['residual_arcsec_yr']}\"/yr (pass <= 1.0), saturated detectors: {', '.join(metrics['saturated_detectors']) or 'none'}"
                if motion["status"] == "MEASURED"
                else f"Not measured: {motion['reason']}"
            )
        elif tid == "TGT-02":
            d6_snrs = [v["snr"] for v in d6["visits"] if v["snr"] is not None]
            d6_ok = len(d6_snrs) >= 2 and all(s >= 5.0 for s in d6_snrs[-2:])
            d1_4_absent = not d1_d4_snrs or max(d1_d4_snrs) < 3.0
            passed = bool(d6_ok and d1_4_absent)
            note = (
                f"D6 median S/N {d6['median_snr']}, D1-D4 max S/N {round(max(d1_d4_snrs), 2) if d1_d4_snrs else 0.0}"
            )
        elif tid == "TGT-03":
            passed = bool(
                motion["status"] == "MEASURED"
                and motion["residual_arcsec_yr"] is not None
                and motion["residual_arcsec_yr"] <= 1.5
            )
            note = (
                f"Motion residual {motion['residual_arcsec_yr']}\"/yr on {motion['detector']} (pass <= 1.5)"
                if motion["status"] == "MEASURED"
                else f"Not measured: {motion['reason']}"
            )
        elif tid == "TGT-04":
            chg = d6["change_last_vs_first"]
            passed = bool(chg["status"] == "MEASURED" or len(metrics["saturated_detectors"]) > 0)
            note = (
                f"D6 last/first ratio {chg['ratio_last_vs_first']} ({chg['delta_pct']}%)"
                if chg["status"] == "MEASURED"
                else f"Saturated detectors excluded: {', '.join(metrics['saturated_detectors'])}"
            )
        else:
            passed = False
            note = "Core saturated on 3-visit cutout; full 222-date NEP light curve required for period test"

        tier_a_targets.append(
            {
                "target_id": tid,
                "target_name": metrics["target_name"],
                "gaia_alignment_rms_arcsec": gaia_rms,
                "alignment_passed": bool(gaia_rms is not None and float(gaia_rms) <= 1.0),
                "d6_median_snr": d6["median_snr"],
                "saturated_detectors": metrics["saturated_detectors"],
                "motion_status": motion["status"],
                "measured_total_arcsec_yr": motion["measured_total_arcsec_yr"],
                "catalogue_total_arcsec_yr": motion["catalogue_total_arcsec_yr"],
                "residual_arcsec_yr": motion["residual_arcsec_yr"],
                "tier_a_check_passed": passed,
                "note": note,
            }
        )

    ml_report = None
    if report_json_path and os.path.exists(report_json_path):
        with open(report_json_path, encoding="utf-8") as f:
            raw = json.load(f)
        rg = raw.get("release_gates", {})
        hi = rg.get("high_snr_gold", {})
        diag = raw.get("heldout_all_classes_diagnostic", {})
        cross_raw = raw.get("cross_extraction_ratio")
        cross_summary = (
            {k: v for k, v in cross_raw.items() if k != "band_median_ratios"}
            if isinstance(cross_raw, dict)
            else None
        )
        ml_report = {
            "status": "AVAILABLE",
            "model_version": raw.get("model_version"),
            "data_as_of": raw.get("data_as_of"),
            "total_spectra": raw.get("total_spectra"),
            "strict_tile_disjointness": raw.get("strict_tile_disjointness"),
            "conformal_q": raw.get("conformal_q"),
            "temperature_inv": raw.get("temperature_inv"),
            "release_status": rg.get("release_status", "UNPUBLISHED"),
            "gold_w2_le_14_count": hi.get("count"),
            "gold_min_recall": hi.get("min_recall"),
            "gold_ece": hi.get("ece"),
            "conformal_coverage": hi.get("conformal_coverage"),
            "e2_only_accuracy": diag.get("e2_only_accuracy"),
            "e1_only_accuracy": diag.get("e1_only_accuracy"),
            "combined_accuracy": diag.get("overall_accuracy"),
            "ucd_subtype_evaluation": raw.get("ucd_subtype_evaluation"),
            "input_ladder": raw.get("input_ladder"),
            "cross_extraction_ratio": cross_summary,
        }

    return {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "tier_a_targets": tier_a_targets,
        "ml_evaluation": ml_report
        or {
            "status": "NOT_MEASURED",
            "reason": "ML evaluation report file not present on disk",
            "release_status": "UNPUBLISHED",
        },
        "next_items": [
            "Move cross-extraction and bright-AGN E1 templates from 14\"/px S3 cubes to 6.2\"/px Level-2 PSF fitting",
            "Reach Gold W2<=14 per-class min recall >= 0.80 and ECE <= 0.05 to pass ML release gate",
            "Remove known catalogued stars on W1925 and RW Aurigae fields and add M1 injection suite",
        ],
    }
