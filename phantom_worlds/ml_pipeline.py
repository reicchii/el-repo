import math
import re

import numpy as np
from sklearn.ensemble import HistGradientBoostingClassifier, HistGradientBoostingRegressor, IsolationForest
from sklearn.linear_model import LogisticRegression
from sklearn.model_selection import StratifiedKFold, StratifiedShuffleSplit

CONTINUUM_WINDOWS = ((2.50, 2.72), (3.80, 4.02), (4.90, 5.01))
MOLECULE_WINDOWS = {
    "H2O_ice_3_05": (2.90, 3.20),
    "CH4_3_3": (3.20, 3.65),
    "CO2_4_26": (4.18, 4.35),
    "CO_4_67": (4.55, 4.80),
}
TRACE_ICE_WINDOWS = {
    "13CO2_4_38": (4.36, 4.41),
    "XCN_4_62": (4.59, 4.65),
    "OCS_4_91": (4.88, 4.94),
}
# Laboratory integrated band strengths A (cm/molecule, Gibb et al. 2004 / Boogert et al. 2015)
MOLECULE_BAND_STRENGTHS_CM = {
    "H2O_ice_3_05": 2.0e-16,
    "CH4_3_3": 1.0e-17,
    "CO2_4_26": 7.6e-17,
    "CO_4_67": 1.1e-17,
    "13CO2_4_38": 7.8e-17,
    "XCN_4_62": 1.3e-16,
    "OCS_4_91": 1.5e-16,
}
CO_SHOULDER_WINDOWS = ((4.38, 4.545), (4.805, 4.92))


def _in_windows(wavelengths, windows):
    mask = np.zeros(len(wavelengths), dtype=bool)
    for lo, hi in windows:
        mask |= (wavelengths >= lo) & (wavelengths <= hi)
    return mask


def _fit_log_poly(wavelengths, flux, mask, deg, fallback):
    w = wavelengths[mask]
    n_pts = len(w)
    if n_pts < 3 or float(np.ptp(w)) < 1e-4:
        return fallback
    deg = min(deg, max(1, len(np.unique(w)) - 1))
    w_mid = 0.5 * (float(wavelengths.min()) + float(wavelengths.max()))
    w_half = max(0.5 * (float(wavelengths.max()) - float(wavelengths.min())), 1e-6)
    xs = (w - w_mid) / w_half
    xg = (wavelengths - w_mid) / w_half
    y = np.log(flux[mask])
    try:
        coeffs = np.polyfit(xs, y, deg=deg)
        log_cont = np.polyval(coeffs, xg)
    except (np.linalg.LinAlgError, FloatingPointError):
        return fallback
    if not np.all(np.isfinite(log_cont)):
        return fallback
    # Bound extrapolation smoothly relative to observed anchor log-flux (scale-invariant).
    log_cont = np.clip(log_cont, float(np.min(y)) - 3.0, float(np.max(y)) + 3.0)
    return np.exp(log_cont)


def _fit_continuum(wavelengths, flux, valid):
    cont_mask = valid & _in_windows(wavelengths, CONTINUUM_WINDOWS) & (flux > 0)
    n_win = sum(1 for lo, hi in CONTINUUM_WINDOWS if np.any(cont_mask & (wavelengths >= lo) & (wavelengths <= hi)))
    used_fallback = False
    if np.count_nonzero(cont_mask) < 4 or n_win < 2:
        broad = valid & (wavelengths >= 2.4) & (flux > 0)
        if np.count_nonzero(broad) >= 3:
            cont_mask = broad
            used_fallback = True
    n_pts = int(np.count_nonzero(cont_mask))
    fallback = float(np.nanmedian(flux[valid & (flux > 0)])) if np.any(valid & (flux > 0)) else 1.0
    fallback_grid = np.full_like(wavelengths, max(fallback, np.finfo(np.float64).tiny), dtype=np.float64)

    # Fit degree <= 2 in log-flux space across the 3 anchor clusters to avoid cubic Runge swings and extinction hijacks.
    if not used_fallback and n_win >= 3 and n_pts >= 6:
        deg = 2
    elif used_fallback and n_pts >= 6 and float(np.ptp(wavelengths[cont_mask])) >= 0.8:
        deg = 2
    else:
        deg = 1
    return _fit_log_poly(wavelengths, flux, cont_mask, deg=deg, fallback=fallback_grid)


def _fit_co_continuum(wavelengths, flux, valid, global_cont):
    # Cold brown dwarfs peak thermally across 4.4-4.9 um; fit disjoint shoulders outside CO_4_67.
    co_mask = valid & _in_windows(wavelengths, CO_SHOULDER_WINDOWS) & (flux > 0)
    co_lo, co_hi = MOLECULE_WINDOWS["CO_4_67"]
    if (
        np.count_nonzero(co_mask) >= 6
        and len(np.unique(wavelengths[co_mask])) >= 3
        and np.any(co_mask & (wavelengths < co_lo))
        and np.any(co_mask & (wavelengths > co_hi))
    ):
        return _fit_log_poly(wavelengths, flux, co_mask, deg=2, fallback=global_cont)
    return global_cont


def _integrate_windows(wavelengths, bandwidths, flux, feature_masks, active_features, continuum, co_continuum):
    d_nu = 10000.0 * bandwidths / np.maximum(wavelengths ** 2, 1e-6)
    tiny = np.finfo(np.float64).tiny
    results = {}
    for name in active_features:
        fmask = feature_masks[name]
        ref_cont = co_continuum if name == "CO_4_67" else continuum
        tau = np.log(np.maximum(ref_cont[fmask], tiny) / np.maximum(flux[fmask], tiny))
        results[name] = float(np.sum(tau * d_nu[fmask]))
    return results


def _refused_feature_entry(window):
    lo, hi = window
    return {
        "status": "REFUSED",
        "refusal_reason": f"Not measured: fewer than 3 valid positive bands in {lo:.2f}-{hi:.2f} um",
        "integrated_tau": None,
        "column_density_cm2": None,
        "rel_to_h2o_ice_pct": None,
        "median": None,
        "p16": None,
        "p84": None,
        "uncertainty_available": False,
        "uncertainty_reason": "Feature refused",
        "origin": "Refused",
    }


def compute_molecule_readings(
    wavelengths,
    bandwidths,
    flux,
    flux_err=None,
    blend_share=0.0,
    is_variable=False,
    rng_seed=0,
    n_draws=200,
    include_trace_ices=False,
):
    """Compute integrated optical depths with 200-redraw uncertainties and per-feature safety refusals."""
    wl = np.asarray(wavelengths, dtype=np.float64)
    bw = np.asarray(bandwidths, dtype=np.float64)
    fl = np.asarray(flux, dtype=np.float64)
    if wl.ndim != 1 or wl.shape != bw.shape or wl.shape != fl.shape:
        raise ValueError("wavelengths, bandwidths, and flux must be 1D arrays with matching shapes")

    bshare = float(blend_share)
    if not math.isfinite(bshare) or not (0.0 <= bshare <= 1.0):
        raise ValueError("blend_share must be finite and in [0.0, 1.0]")
    if int(n_draws) < 1:
        raise ValueError("n_draws must be >= 1")

    valid = np.isfinite(wl) & np.isfinite(bw) & np.isfinite(fl) & (wl > 0) & (bw > 0) & (fl > 0)
    if np.any(valid) and np.max(np.abs(fl[valid])) > 1e100:
        raise ValueError("flux values exceed finite numerical range (<= 1e100)")
    err = None
    if flux_err is not None:
        err = np.asarray(flux_err, dtype=np.float64)
        if err.shape != wl.shape:
            raise ValueError("flux_err must match wavelengths shape")
        if np.any(valid) and (np.any(~np.isfinite(err[valid]) | (err[valid] < 0.0)) or np.max(err[valid]) > 1e100):
            raise ValueError("flux_err on valid spectral bands must be finite, non-negative, and <= 1e100")

    reasons = []
    if is_variable:
        reasons.append("Not measured: source flagged variable between visits")
    if bshare > 0.3:
        reasons.append(f"Not measured: blend_share {bshare:.2f} exceeds 0.30 threshold")
    if np.count_nonzero(valid) < 3:
        reasons.append("Not measured: fewer than 3 valid positive spectral bands")
    if reasons:
        return {"status": "REFUSED", "refusal_reason": "; ".join(reasons), "features": {}}

    windows = {**MOLECULE_WINDOWS, **TRACE_ICE_WINDOWS} if include_trace_ices else MOLECULE_WINDOWS
    feature_masks = {
        name: valid & (wl >= lo) & (wl <= hi)
        for name, (lo, hi) in windows.items()
    }
    active_features = [name for name, fmask in feature_masks.items() if np.count_nonzero(fmask) >= 3]
    refused_features = {
        name: _refused_feature_entry(windows[name])
        for name in windows
        if name not in active_features
    }
    if not active_features:
        return {
            "status": "REFUSED",
            "refusal_reason": "Not measured: fewer than 3 valid positive bands in any molecular feature window",
            "features": refused_features,
        }

    global_cont = _fit_continuum(wl, fl, valid)
    co_cont = _fit_co_continuum(wl, fl, valid, global_cont)
    point_est = _integrate_windows(wl, bw, fl, feature_masks, active_features, global_cont, co_cont)

    draws = {k: [] for k in active_features}
    if err is not None:
        safe_err = np.where(valid, err, 0.0)
        rng = np.random.default_rng(rng_seed)
        floor = np.where(valid, np.maximum(0.25 * np.abs(fl), 1e-12), 1.0)
        for _ in range(int(n_draws)):
            raw = fl + rng.normal(0.0, safe_err)
            soft = fl * (0.25 + 0.25 * np.exp(np.clip((raw - 0.5 * fl) / floor, -50.0, 0.0)))
            sampled = np.where(valid, np.where(raw >= 0.5 * fl, raw, soft), fl)
            s_global = _fit_continuum(wl, sampled, valid)
            s_co = _fit_co_continuum(wl, sampled, valid, s_global)
            s_res = _integrate_windows(wl, bw, sampled, feature_masks, active_features, s_global, s_co)
            for k, val in s_res.items():
                draws[k].append(val)

    col_dens_map = {}
    for name in active_features:
        band_a = MOLECULE_BAND_STRENGTHS_CM.get(name)
        tau_val = float(point_est[name])
        col_dens_map[name] = max(0.0, tau_val / band_a) if (band_a and tau_val > 0.0) else 0.0
    h2o_col = col_dens_map.get("H2O_ice_3_05", 0.0)

    features = {}
    for name in windows:
        if name in refused_features:
            features[name] = refused_features[name]
        else:
            col_d = col_dens_map.get(name, 0.0)
            rel_h2o = round(100.0 * col_d / h2o_col, 4) if (h2o_col > 0.0 and col_d > 0.0) else None
            if err is not None:
                features[name] = {
                    "status": "MEASURED",
                    "refusal_reason": None,
                    "integrated_tau": point_est[name],
                    "column_density_cm2": col_d,
                    "rel_to_h2o_ice_pct": rel_h2o,
                    "median": float(np.median(draws[name])),
                    "p16": float(np.percentile(draws[name], 16)),
                    "p84": float(np.percentile(draws[name], 84)),
                    "uncertainty_available": True,
                    "uncertainty_reason": None,
                    "origin": "Measured",
                }
            else:
                features[name] = {
                    "status": "MEASURED",
                    "refusal_reason": None,
                    "integrated_tau": point_est[name],
                    "column_density_cm2": col_d,
                    "rel_to_h2o_ice_pct": rel_h2o,
                    "median": None,
                    "p16": None,
                    "p84": None,
                    "uncertainty_available": False,
                    "uncertainty_reason": "Uncertainties unavailable: flux_err not provided",
                    "origin": "Measured",
                }

    partial_notes = [f"{k} ({refused_features[k]['refusal_reason']})" for k in refused_features]
    return {
        "status": "MEASURED",
        "refusal_reason": "; ".join(partial_notes) if partial_notes else None,
        "features": features,
    }


_EXTRAGALACTIC_CLASSES = frozenset({"Galaxy", "Active galaxy or quasar"})


_UCD_LETTER_BASES = {"M": 60.0, "L": 70.0, "T": 80.0, "Y": 90.0}
_UCD_SPT_RE = re.compile(r"([MLTY])\s*(\d(?:\.\d+)?)", re.IGNORECASE)


def parse_ucd_spectral_index(subclass_str):
    """Convert optical/IR spectral type string (e.g., L3.5, esdT0, Y1e) to numeric index (M0=60..Y9=99)."""
    txt = str(subclass_str or "").strip()
    m = _UCD_SPT_RE.search(txt)
    if not m:
        return float("nan")
    letter = m.group(1).upper()
    num = float(m.group(2))
    if not (0.0 <= num < 10.0):
        return float("nan")
    return _UCD_LETTER_BASES[letter] + num


def format_ucd_spectral_index(idx_val):
    val = max(60.0, min(99.9, float(idx_val)))
    for letter, base in (("Y", 90.0), ("T", 80.0), ("L", 70.0), ("M", 60.0)):
        if val >= base:
            sub = min(9.9, val - base)
            return f"{letter}{sub:.1f}"
    return "M0.0"


class _PowerCalibrator:
    """Rank-preserving multiclass temperature calibrator compatible with calibrators_.predict."""

    def __init__(self, inv_temp: float):
        self.inv_temp = float(inv_temp)

    def predict(self, probs_1d):
        arr = np.clip(np.asarray(probs_1d, dtype=np.float64), 1e-6, 1.0)
        return np.power(arr, self.inv_temp)


def _fit_temperature_inv(raw_probs, y_true, classes):
    probs = np.clip(np.asarray(raw_probs, dtype=np.float64), 1e-6, 1.0)
    class_to_col = {c: idx for idx, c in enumerate(classes)}
    cols = [class_to_col.get(val, -1) for val in y_true]
    valid_rows = [i for i, col in enumerate(cols) if col >= 0]
    if not valid_rows:
        return 1.0
    sub_p = probs[valid_rows]
    sub_cols = np.array([cols[i] for i in valid_rows], dtype=int)
    log_p = np.log(sub_p)

    def _nll(inv_t):
        scaled = log_p * inv_t
        scaled = scaled - np.max(scaled, axis=1, keepdims=True)
        exp_s = np.exp(scaled)
        norm_p = exp_s / np.sum(exp_s, axis=1, keepdims=True)
        picked = np.clip(norm_p[np.arange(len(sub_cols)), sub_cols], 1e-12, 1.0)
        return float(-np.mean(np.log(picked)))

    best_t = 1.0
    best_loss = _nll(1.0)
    for grid in (np.geomspace(0.35, 3.0, 55), np.linspace(max(0.25, best_t * 0.8), min(4.0, best_t * 1.25), 31)):
        for cand in grid:
            loss = _nll(float(cand))
            if loss < best_loss:
                best_loss = loss
                best_t = float(cand)
        grid_hi = min(4.0, best_t * 1.25)
        grid_lo = max(0.25, best_t * 0.8)
    for cand in np.linspace(grid_lo, grid_hi, 31):
        loss = _nll(float(cand))
        if loss < best_loss:
            best_loss = loss
            best_t = float(cand)
    return float(best_t)


class SpectralDiscoveryPipeline:
    """Layer 1-3 ensemble combining template chi2 matching, independent trees, temperature calibration, and conformal sets."""

    def __init__(self, wavelengths, bandwidths, template_library, random_state=42):
        self.wavelengths = np.asarray(wavelengths, dtype=np.float64)
        self.bandwidths = np.asarray(bandwidths, dtype=np.float64)
        self._wl_order = np.argsort(self.wavelengths, kind="mergesort")
        self._sorted_wl = self.wavelengths[self._wl_order]
        self.template_library = {}
        self.template_variants_ = {}
        for k, v in template_library.items():
            if isinstance(v, (list, tuple)) and len(v) > 0 and isinstance(v[0], (list, tuple, np.ndarray)):
                variants = [self._normalize(np.asarray(sub, dtype=np.float64)) for sub in v]
            else:
                arr = np.asarray(v, dtype=np.float64)
                if arr.ndim == 2:
                    variants = [self._normalize(row) for row in arr]
                else:
                    variants = [self._normalize(arr)]
            self.template_variants_[k] = variants
            self.template_library[k] = variants[0]
        self.random_state = random_state
        self.classes_ = sorted(self.template_library.keys())
        self.tree_model = self._build_tree()
        self.meta_combiner = LogisticRegression(max_iter=500, C=0.5, class_weight="balanced", random_state=random_state)
        self.novelty_forest = IsolationForest(contamination=0.05, random_state=random_state)
        self.subtype_regressor = HistGradientBoostingRegressor(
            max_iter=60,
            max_depth=4,
            min_samples_leaf=3,
            l2_regularization=0.3,
            random_state=random_state,
        )
        self.subtype_fitted_ = False
        self.calibrators_ = {}
        self.temperature_inv_ = 1.0
        self.calibration_size_ = 0
        self.isotonic_size_ = 0
        self.conformal_q_ = 0.85
        self.silver_weight_applied_ = 1.0
        self.fitted_ = False

    @staticmethod
    def _normalize(flux):
        arr = np.asarray(flux, dtype=np.float64)
        finite = np.isfinite(arr)
        denom = float(np.mean(np.abs(arr[finite]))) if np.any(finite) else 1.0
        return arr / max(denom, 1e-6)

    def _bridge_narrow_log_gaps(self, log_fl, swl):
        n = len(log_fl)
        if n < 3 or len(swl) != n:
            return log_fl
        out = log_fl.copy()
        finite = np.isfinite(out)
        if np.count_nonzero(finite) < 2 or np.all(finite):
            return out
        i = 0
        while i < n:
            if finite[i]:
                i += 1
                continue
            j = i
            while j < n and not finite[j]:
                j += 1
            gap_len = j - i
            if i > 0 and j < n and gap_len <= 3:
                x0, x1 = float(swl[i - 1]), float(swl[j])
                y0, y1 = float(out[i - 1]), float(out[j])
                dx = x1 - x0
                for p in range(i, j):
                    t = (float(swl[p]) - x0) / dx if abs(dx) > 1e-9 else 0.5
                    out[p] = y0 + t * (y1 - y0)
            elif gap_len == 1 and n >= 10:
                if i == 0 and finite[1] and finite[2]:
                    dx = float(swl[2] - swl[1])
                    slope = (float(out[2] - out[1]) / dx) if abs(dx) > 1e-9 else 0.0
                    step = max(-0.5, min(0.5, slope * float(swl[0] - swl[1])))
                    out[0] = float(out[1]) + step
                elif j == n and finite[n - 2] and finite[n - 3]:
                    dx = float(swl[n - 2] - swl[n - 3])
                    slope = (float(out[n - 2] - out[n - 3]) / dx) if abs(dx) > 1e-9 else 0.0
                    step = max(-0.5, min(0.5, slope * float(swl[n - 1] - swl[n - 2])))
                    out[n - 1] = float(out[n - 2]) + step
            i = j
        return out

    def _sorted_log_flux(self, flux):
        raw_arr = np.asarray(flux, dtype=np.float64)
        n = len(raw_arr)
        arr = raw_arr[self._wl_order] if len(self._wl_order) == n else raw_arr
        swl = self._sorted_wl if len(self._sorted_wl) == n else self.wavelengths
        log_fl = np.full(n, np.nan, dtype=np.float64)
        pos = np.isfinite(arr) & (arr > 0)
        if np.any(pos):
            log_fl[pos] = np.log(arr[pos])
        return self._bridge_narrow_log_gaps(log_fl, swl), swl

    def _spectral_colors(self, flux):
        log_fl, swl = self._sorted_log_flux(flux)
        n = len(log_fl)
        k = max(1, min(12, n // 4))
        broad = log_fl[k:] - log_fl[: n - k]
        if n > 1:
            local_idx = np.linspace(0, n - 2, k, dtype=int)
            local = log_fl[local_idx + 1] - log_fl[local_idx]
            finite = np.isfinite(log_fl)
            if k >= 4 and len(swl) == n:
                ref = float(np.median(log_fl[finite])) if np.any(finite) else np.nan
                bands = ((0.75, 1.11), (1.11, 1.64), (1.64, 2.42), (2.42, 3.82), (3.82, 4.42), (4.42, 5.05))
                bvals = np.full(len(bands), np.nan, dtype=np.float64)
                for idx, (lo, hi) in enumerate(bands):
                    hi_mask = (swl <= hi) if idx == len(bands) - 1 else (swl < hi)
                    bm = (swl >= lo) & hi_mask & finite
                    if np.any(bm):
                        bvals[idx] = float(np.median(log_fl[bm]))
                # Pack physical band levels + long-baseline slopes into local[:k-4] while keeping len == len(wl).
                shape_feats = np.concatenate([
                    bvals - ref if np.isfinite(ref) else np.full(len(bands), np.nan, dtype=np.float64),
                    np.array([bvals[2] - bvals[0], bvals[5] - bvals[2]], dtype=np.float64),
                ])
                n_pack = min(k - 4, len(shape_feats))
                if n_pack > 0 and np.any(np.isfinite(shape_feats[:n_pack])):
                    local[:n_pack] = shape_feats[:n_pack]
                cont_m = _in_windows(swl, CONTINUUM_WINDOWS) & finite
                cont_ref = float(np.mean(log_fl[cont_m])) if np.any(cont_m) else (
                    float(np.mean(log_fl[finite])) if np.any(finite) else np.nan
                )
                for idx_offset, (lo, hi) in enumerate(MOLECULE_WINDOWS.values()):
                    wm = (swl >= lo) & (swl <= hi) & finite
                    if np.any(wm) and np.isfinite(cont_ref):
                        local[k - 4 + idx_offset] = cont_ref - float(np.mean(log_fl[wm]))
        else:
            local = np.full(k, np.nan, dtype=np.float64)
        return np.concatenate([broad, local])

    def _extract_features(self, X):
        # E2 trees train on scale- and gap-invariant spectral colors + physical band slopes (zero E1 leakage).
        return np.vstack([self._spectral_colors(row) for row in X])

    @staticmethod
    def _reduced_chi2(norm_flux, tmpl, norm_err=None):
        nf_finite = int(np.count_nonzero(np.isfinite(norm_flux)))
        valid = np.isfinite(norm_flux) & np.isfinite(tmpl)
        n_valid = int(np.count_nonzero(valid))
        if n_valid < 3:
            return float("inf")
        if nf_finite >= 20 and n_valid < int(0.65 * nf_finite):
            return float("inf")
        coverage_penalty = (
            float(nf_finite) / float(n_valid)
            if (nf_finite >= 20 and n_valid < nf_finite)
            else 1.0
        )
        nf = norm_flux[valid]
        tp = tmpl[valid]
        fallback_err = np.maximum(0.05 * np.abs(nf), 0.02)
        if norm_err is not None:
            ne = np.asarray(norm_err, dtype=np.float64)
            if ne.shape == norm_flux.shape:
                ne_valid = ne[valid]
                good_e = np.isfinite(ne_valid) & (ne_valid > 0)
                if np.any(good_e):
                    err = np.where(good_e, np.maximum(ne_valid, 0.01), fallback_err)
                    w = 1.0 / (err ** 2)
                    scale = float(np.dot(w * nf, tp) / max(float(np.dot(w * tp, tp)), 1e-9))
                else:
                    err = fallback_err
                    denom = float(np.dot(tp, tp))
                    scale = float(np.dot(nf, tp) / max(denom, 1e-9))
            else:
                err = fallback_err
                denom = float(np.dot(tp, tp))
                scale = float(np.dot(nf, tp) / max(denom, 1e-9))
        else:
            err = fallback_err
            denom = float(np.dot(tp, tp))
            scale = float(np.dot(nf, tp) / max(denom, 1e-9))
        chi2_terms = ((nf - scale * tp) / err) ** 2
        outlier_drop = min(3, len(chi2_terms) // 15)
        if outlier_drop > 0:
            chi2_terms = np.sort(chi2_terms)[:-outlier_drop]
        return float(np.mean(chi2_terms)) * coverage_penalty

    def _predict_template_class(self, norm_flux, norm_err=None):
        scores = {
            label: min(self._reduced_chi2(norm_flux, tmpl, norm_err=norm_err) for tmpl in variants)
            for label, variants in self.template_variants_.items()
        }
        best = min(scores, key=scores.get)
        return best, scores

    def _template_probs(self, tmpl_class, chi2_map):
        finite_vals = (
            [float(chi2_map[c]) for c in self.classes_ if c in chi2_map and math.isfinite(float(chi2_map[c]))]
            if chi2_map
            else []
        )
        if chi2_map and finite_vals:
            best_val = min(finite_vals)
            raw = np.array(
                [
                    math.exp(-0.5 * min(max(0.0, float(chi2_map[c]) - best_val), 100.0))
                    if c in chi2_map and math.isfinite(float(chi2_map[c]))
                    else 0.0
                    for c in self.classes_
                ],
                dtype=np.float64,
            )
        else:
            raw = np.array([1.0 if c == tmpl_class else 0.0 for c in self.classes_], dtype=np.float64)
        total = float(np.sum(raw))
        return raw / total if total > 0 else np.full(len(self.classes_), 1.0 / max(len(self.classes_), 1), dtype=np.float64)

    def _predict_tree_probs(self, feat_row):
        probs = self.tree_model.predict_proba(feat_row.reshape(1, -1))[0]
        return {str(label): float(p) for label, p in zip(self.tree_model.classes_, probs)}

    def _combined_meta_features(self, norm_rows, e2_probs_matrix, norm_errs=None):
        e1_rows = []
        for idx, row in enumerate(norm_rows):
            nerr = norm_errs[idx] if norm_errs is not None else None
            e1_rows.append(self._template_probs(*self._predict_template_class(row, norm_err=nerr)))
        e1_matrix = np.vstack(e1_rows)
        return np.hstack([e1_matrix, e2_probs_matrix])

    def _apply_isotonic(self, raw_probs):
        if not self.calibrators_:
            return raw_probs
        cal = np.empty_like(raw_probs, dtype=np.float64)
        for col, cls in enumerate(self.meta_combiner.classes_):
            iso = self.calibrators_.get(str(cls))
            cal[:, col] = iso.predict(raw_probs[:, col]) if iso is not None else raw_probs[:, col]
        totals = cal.sum(axis=1, keepdims=True)
        out = raw_probs.copy()
        pos = totals[:, 0] > 0
        if np.any(pos):
            out[pos] = cal[pos] / totals[pos]
        return out

    def _split_fit_indices(self, y, sky_tiles=None, label_grades=None):
        classes, counts = np.unique(y, return_counts=True)
        min_count = int(np.min(counts)) if len(counts) else 0
        if min_count < 4 or len(y) < 3 * len(classes):
            raise ValueError("Need at least 4 samples per class for disjoint train/isotonic/conformal splits")
        if sky_tiles is not None:
            tiles = np.asarray(sky_tiles)
            uniq_tiles = sorted(set(tiles.tolist()), key=str)
            if len(uniq_tiles) >= 3:
                tile_buckets = _allocate_stratified_tiles(
                    tiles, y, fracs=(0.70, 0.15, 0.15), random_state=self.random_state
                )
                tr_idx = np.where(np.isin(tiles, list(tile_buckets[0])))[0]
                iso_idx = np.where(np.isin(tiles, list(tile_buckets[1])))[0]
                conf_idx = np.where(np.isin(tiles, list(tile_buckets[2])))[0]
                if label_grades is not None:
                    grades = np.array([str(g).strip().lower() for g in label_grades])
                    iso_gold = iso_idx[grades[iso_idx] == "gold"]
                    conf_gold = conf_idx[grades[conf_idx] == "gold"]
                    if len(set(y[iso_gold].tolist())) == len(classes):
                        iso_idx = iso_gold
                    if len(set(y[conf_gold].tolist())) == len(classes):
                        conf_idx = conf_gold
                if (
                    len(set(y[tr_idx].tolist())) == len(classes)
                    and len(set(y[iso_idx].tolist())) == len(classes)
                    and len(set(y[conf_idx].tolist())) == len(classes)
                ):
                    return tr_idx, iso_idx, conf_idx
        s1 = StratifiedShuffleSplit(n_splits=1, test_size=0.45, random_state=self.random_state)
        train_idx, holdout_idx = next(s1.split(np.zeros(len(y)), y))
        s2 = StratifiedShuffleSplit(n_splits=1, test_size=0.5, random_state=self.random_state)
        iso_rel, conf_rel = next(s2.split(np.zeros(len(holdout_idx)), y[holdout_idx]))
        return train_idx, holdout_idx[iso_rel], holdout_idx[conf_rel]

    def _build_tree(self):
        return HistGradientBoostingClassifier(
            max_iter=80,
            max_depth=4,
            min_samples_leaf=3,
            l2_regularization=0.4,
            max_features=0.35,
            learning_rate=0.08,
            class_weight="balanced",
            random_state=self.random_state,
        )

    def _augment_masked_training(self, X_subset, y_subset, weights_subset=None):
        # Simulate missing SPHEREx detector blocks and sensor gaps during E2 training without affecting calibration splits.
        n_bands = X_subset.shape[1]
        segs = min(5, max(1, n_bands // 2))
        block = max(1, n_bands // segs)
        feat_parts = [self._extract_features(X_subset)]
        y_parts = [y_subset]
        w_parts = [weights_subset] if weights_subset is not None else []
        if n_bands >= 6:
            for seg in range(segs):
                masked_rows = X_subset.copy()
                lo = seg * block
                hi = n_bands if seg == segs - 1 else (seg + 1) * block
                masked_rows[:, lo:hi] = np.nan
                feat_parts.append(self._extract_features(masked_rows))
                y_parts.append(y_subset)
                if weights_subset is not None:
                    w_parts.append(weights_subset)
        if n_bands >= 16:
            edge_mid_rows = X_subset.copy()
            edge_mid_rows[:, :2] = np.nan
            edge_mid_rows[:, -2:] = np.nan
            mid = n_bands // 2
            edge_mid_rows[:, max(0, mid - 2) : min(n_bands, mid + 2)] = np.nan
            feat_parts.append(self._extract_features(edge_mid_rows))
            y_parts.append(y_subset)
            if weights_subset is not None:
                w_parts.append(weights_subset)
        aug_w = np.concatenate(w_parts) if w_parts else None
        return np.vstack(feat_parts), np.concatenate(y_parts), aug_w

    def fit(self, X_flux, y_labels, blend_shares=None, sky_tiles=None, label_grades=None, X_err=None, subtypes=None):
        X = np.asarray(X_flux, dtype=np.float64)
        y = np.asarray(y_labels)
        denoms = np.array(
            [
                max(float(np.mean(np.abs(row[np.isfinite(row)]))) if np.any(np.isfinite(row)) else 1.0, 1e-6)
                for row in X
            ],
            dtype=np.float64,
        )
        normed = X / denoms[:, None]
        norm_errs = (np.asarray(X_err, dtype=np.float64) / denoms[:, None]) if X_err is not None else None
        feats = self._extract_features(X)
        train_idx, iso_idx, conf_idx = self._split_fit_indices(y, sky_tiles=sky_tiles, label_grades=label_grades)

        sample_weights = np.ones(len(y), dtype=np.float64)
        self.silver_weight_applied_ = 1.0
        if label_grades is not None:
            is_silver = np.array([str(g).strip().lower() == "silver" for g in label_grades], dtype=bool)
            if np.any(is_silver):
                sample_weights[is_silver] = 0.5
                self.silver_weight_applied_ = 0.5

        _, tr_counts = np.unique(y[train_idx], return_counts=True)
        n_cv = max(2, min(3, int(np.min(tr_counts))))
        tree_classes = np.array(sorted(set(y[train_idx].tolist())))
        skf = StratifiedKFold(n_splits=n_cv, shuffle=True, random_state=self.random_state)
        oof_e2 = np.zeros((len(train_idx), len(tree_classes)), dtype=np.float64)
        tr_weights = sample_weights[train_idx]
        for sub_tr, sub_va in skf.split(feats[train_idx], y[train_idx]):
            aug_f, aug_y, aug_w = self._augment_masked_training(
                X[train_idx][sub_tr], y[train_idx][sub_tr], tr_weights[sub_tr]
            )
            fold_tree = self._build_tree()
            fold_tree.fit(aug_f, aug_y, sample_weight=aug_w)
            oof_e2[sub_va] = fold_tree.predict_proba(feats[train_idx][sub_va])

        full_aug_f, full_aug_y, full_aug_w = self._augment_masked_training(
            X[train_idx], y[train_idx], tr_weights
        )
        self.tree_model.fit(full_aug_f, full_aug_y, sample_weight=full_aug_w)
        tr_nerr = norm_errs[train_idx] if norm_errs is not None else None
        meta_train = self._combined_meta_features(normed[train_idx], oof_e2, norm_errs=tr_nerr)
        self.meta_combiner.fit(meta_train, y[train_idx], sample_weight=tr_weights)

        # Stage 2: fit rank-preserving temperature scaling strictly on held-out iso_idx
        iso_nerr = norm_errs[iso_idx] if norm_errs is not None else None
        iso_meta = self._combined_meta_features(normed[iso_idx], self.tree_model.predict_proba(feats[iso_idx]), norm_errs=iso_nerr)
        raw_iso_probs = self.meta_combiner.predict_proba(iso_meta)
        self.temperature_inv_ = _fit_temperature_inv(raw_iso_probs, y[iso_idx], self.meta_combiner.classes_)
        self.calibrators_ = {
            str(cls): _PowerCalibrator(self.temperature_inv_) for cls in self.meta_combiner.classes_
        }
        self.isotonic_size_ = len(iso_idx)

        # Stage 3: calibrate conformal quantile strictly on unseen held-out conf_idx
        conf_nerr = norm_errs[conf_idx] if norm_errs is not None else None
        conf_meta = self._combined_meta_features(normed[conf_idx], self.tree_model.predict_proba(feats[conf_idx]), norm_errs=conf_nerr)
        cal_conf_probs = self._apply_isotonic(self.meta_combiner.predict_proba(conf_meta))
        class_to_col = {c: idx for idx, c in enumerate(self.meta_combiner.classes_)}
        nonconformity = [1.0 - float(cal_conf_probs[i, class_to_col[y[conf_idx][i]]]) for i in range(len(conf_idx))]
        n = len(nonconformity)
        q_level = min(math.ceil((n + 1) * 0.90) / n, 1.0)
        self.conformal_q_ = float(np.quantile(nonconformity, q_level, method="higher"))
        self.calibration_size_ = n

        clean_mask = np.ones(len(train_idx), dtype=bool)
        if blend_shares is not None:
            clean_mask &= np.asarray(blend_shares, dtype=np.float64)[train_idx] <= 0.3
        train_feats = feats[train_idx]
        self.novelty_forest.fit(train_feats[clean_mask] if np.any(clean_mask) else train_feats)

        self.subtype_fitted_ = False
        if subtypes is not None:
            sub_arr = np.asarray(subtypes)
            ucd_tr = [
                i for i in train_idx
                if str(y[i]) == "Ultracool dwarf" and math.isfinite(parse_ucd_spectral_index(sub_arr[i]))
            ]
            if len(ucd_tr) >= 12:
                ucd_idx = np.asarray(ucd_tr, dtype=int)
                ucd_y = np.array([parse_ucd_spectral_index(sub_arr[i]) for i in ucd_idx], dtype=np.float64)
                aug_sub_x, aug_sub_y, _ = self._augment_masked_training(X[ucd_idx], ucd_y)
                self.subtype_regressor.fit(aug_sub_x, aug_sub_y)
                self.subtype_fitted_ = True

        self.fitted_ = True
        return self

    def predict_ucd_subtype(self, flux):
        if not self.fitted_ or not self.subtype_fitted_:
            return None
        feat = self._extract_features(np.asarray(flux, dtype=np.float64).reshape(1, -1))
        idx_val = float(self.subtype_regressor.predict(feat)[0])
        return {"spectral_index": round(idx_val, 2), "subtype_label": format_ucd_spectral_index(idx_val)}

    def evaluate_ucd_subtype_accuracy(self, X_sub, y_sub, subclasses):
        if not self.fitted_ or not self.subtype_fitted_:
            return {"count": 0, "mad_subtypes": None, "mae_subtypes": None, "within_2_subtypes_frac": 0.0, "passed": False}
        errs = []
        for row, cls_val, spt_str in zip(X_sub, y_sub, subclasses):
            if str(cls_val) != "Ultracool dwarf":
                continue
            true_idx = parse_ucd_spectral_index(spt_str)
            if not math.isfinite(true_idx):
                continue
            pred = self.predict_ucd_subtype(row)
            if pred is not None:
                errs.append(abs(float(pred["spectral_index"]) - true_idx))
        if not errs:
            return {"count": 0, "mad_subtypes": None, "mae_subtypes": None, "within_2_subtypes_frac": 0.0, "passed": False}
        arr = np.asarray(errs, dtype=np.float64)
        within_2 = float(np.mean(arr <= 2.0))
        return {
            "count": int(len(arr)),
            "mad_subtypes": round(float(np.median(arr)), 4),
            "mae_subtypes": round(float(np.mean(arr)), 4),
            "within_2_subtypes_frac": round(within_2, 4),
            "passed": bool(within_2 >= 0.80),
        }

    def _summarize_branch(self, probs, tmpl_class, tree_top_class, conformal_probs=None, excluded=()):
        raw_top = str(max(probs, key=probs.get))
        confidence = float(probs[raw_top])
        experts_disagree = (tmpl_class != tree_top_class) or (raw_top != tmpl_class)
        if experts_disagree:
            confidence = min(confidence, 0.50)
        top_class = "Unclassified" if (confidence < 0.50 or experts_disagree) else raw_top
        cprobs = probs if conformal_probs is None else conformal_probs
        conformal_set = [
            str(c) for c, p in cprobs.items() if c not in excluded and (1.0 - p) <= self.conformal_q_ + 1e-6
        ]
        return top_class, round(confidence, 4), conformal_set

    def predict_one(self, flux, blend_share=0.0, is_variable=False, has_masked_pixels=False, parallax_snr=0.0, flux_err=None):
        if not self.fitted_:
            raise RuntimeError("Pipeline must be fitted before calling predict_one")

        psnr = 0.0 if (parallax_snr is None or isinstance(parallax_snr, bool)) else float(parallax_snr)
        parallax_gated = math.isfinite(psnr) and psnr > 5.0
        fl = np.asarray(flux, dtype=np.float64)
        if int(np.count_nonzero(np.isfinite(fl) & (fl > 0))) < 3:
            return {
                "spectrum_alone": {
                    "top_class": "Unclassified",
                    "confidence": 0.0,
                    "template_class": "Unclassified",
                    "tree_class": "Unclassified",
                    "conformal_set": [],
                },
                "all_data": {
                    "top_class": "Unclassified",
                    "confidence": 0.0,
                    "parallax_gate_applied": parallax_gated,
                    "conformal_set": [],
                },
                "novelty": {"status": "CONTAMINATION_SCREENED", "weirdness_score": None},
            }

        finite = np.isfinite(fl)
        denom = max(float(np.mean(np.abs(fl[finite]))) if np.any(finite) else 1.0, 1e-6)
        norm_fl = fl / denom
        norm_err = (np.asarray(flux_err, dtype=np.float64) / denom) if flux_err is not None else None
        feat = self._extract_features(fl.reshape(1, -1))[0]

        tmpl_class, chi2_map = self._predict_template_class(norm_fl, norm_err=norm_err)
        tree_probs = self._predict_tree_probs(feat)
        tree_top_class = str(max(tree_probs, key=tree_probs.get))

        e1_vec = self._template_probs(tmpl_class, chi2_map).reshape(1, -1)
        e2_vec = np.array([tree_probs.get(c, 0.0) for c in self.tree_model.classes_]).reshape(1, -1)
        raw_meta = self.meta_combiner.predict_proba(np.hstack([e1_vec, e2_vec]))
        cal_probs_arr = self._apply_isotonic(raw_meta)[0]
        spec_probs = {str(c): float(p) for c, p in zip(self.meta_combiner.classes_, cal_probs_arr)}

        spec_top_class, spec_conf, spec_conformal_set = self._summarize_branch(spec_probs, tmpl_class, tree_top_class)

        all_probs = dict(spec_probs)
        excluded = _EXTRAGALACTIC_CLASSES if parallax_gated else ()
        all_tmpl_class = tmpl_class
        all_tree_class = tree_top_class
        if parallax_gated:
            for extra in _EXTRAGALACTIC_CLASSES:
                if extra in all_probs:
                    all_probs[extra] = 0.0
            surviving = sum(all_probs.values())
            denom = surviving + (1.0 - surviving) ** 2
            if denom > 0.0:
                all_probs = {k: v / denom for k, v in all_probs.items()}
            gal_chi2 = {k: v for k, v in chi2_map.items() if k not in excluded}
            if gal_chi2:
                all_tmpl_class = min(gal_chi2, key=gal_chi2.get)
            gal_tree = {k: v for k, v in tree_probs.items() if k not in excluded}
            if gal_tree:
                all_tree_class = max(gal_tree, key=gal_tree.get)

        all_top_class, all_conf, all_conformal_set = self._summarize_branch(
            all_probs,
            all_tmpl_class,
            all_tree_class,
            conformal_probs=spec_probs,
            excluded=excluded,
        )

        has_unmasked_defect = not bool(np.all(np.isfinite(fl))) or not bool(np.all(np.isfinite(feat)))
        if blend_share > 0.3 or is_variable or has_masked_pixels or has_unmasked_defect:
            novelty = {"status": "CONTAMINATION_SCREENED", "weirdness_score": None}
        else:
            raw_iso = float(-self.novelty_forest.score_samples(feat.reshape(1, -1))[0])
            iso_outlier = int(self.novelty_forest.predict(feat.reshape(1, -1))[0]) == -1
            novelty = {
                "status": "NOVEL"
                if (not spec_conformal_set or chi2_map.get(tmpl_class, 0.0) > 3.0 or iso_outlier)
                else "OK",
                "weirdness_score": round(max(0.0, min(1.0, raw_iso)), 4),
            }

        return {
            "spectrum_alone": {
                "top_class": spec_top_class,
                "confidence": spec_conf,
                "template_class": tmpl_class,
                "tree_class": tree_top_class,
                "conformal_set": spec_conformal_set,
            },
            "all_data": {
                "top_class": all_top_class,
                "confidence": all_conf,
                "parallax_gate_applied": parallax_gated,
                "conformal_set": all_conformal_set,
            },
            "novelty": novelty,
        }

    def evaluate_release_gates(self, X_test, y_test, w2_mags=None, label_grades=None, blend_shares=None, X_err=None):
        """Evaluate Gold-only test split and per-W2 brightness bins against ml-research.md §9 pass marks."""
        if not self.fitted_:
            raise RuntimeError("Pipeline must be fitted before calling evaluate_release_gates")
        X = np.asarray(X_test, dtype=np.float64)
        X_err_arr = np.asarray(X_err, dtype=np.float64) if X_err is not None else None
        y = np.asarray(y_test)
        n_total = len(y)
        if label_grades is not None:
            gold_mask = np.array([str(g).strip().lower() == "gold" for g in label_grades], dtype=bool)
        else:
            gold_mask = np.ones(n_total, dtype=bool)
        excluded_silver = int(np.count_nonzero(~gold_mask))

        X_gold = X[gold_mask]
        err_gold = X_err_arr[gold_mask] if X_err_arr is not None else None
        y_gold = y[gold_mask]
        w2_gold = np.asarray(w2_mags, dtype=np.float64)[gold_mask] if w2_mags is not None else np.full(len(y_gold), 12.0)
        bshares = np.asarray(blend_shares, dtype=np.float64)[gold_mask] if blend_shares is not None else np.full(len(y_gold), 0.05)

        preds = [
            self.predict_one(
                X_gold[i],
                blend_share=float(bshares[i]),
                flux_err=(err_gold[i] if err_gold is not None else None),
            )["spectrum_alone"]
            for i in range(len(y_gold))
        ]

        def _score_subset(mask_arr):
            idxs = np.where(mask_arr)[0]
            if len(idxs) == 0:
                return {
                    "count": 0,
                    "per_class_recall": {},
                    "min_recall": 0.0,
                    "ece": 0.0,
                    "conformal_coverage": 0.0,
                    "passed": False,
                }
            sub_y = y_gold[idxs]
            sub_preds = [preds[i] for i in idxs]
            present_classes = sorted(set(sub_y.tolist()), key=str)
            recalls = {}
            for cls in present_classes:
                cls_pos = [j for j, yy in enumerate(sub_y) if yy == cls]
                recalls[str(cls)] = round(sum(sub_preds[j]["top_class"] == cls for j in cls_pos) / len(cls_pos), 4)
            min_rec = float(min(recalls.values())) if recalls else 0.0
            coverage = round(sum(sub_y[j] in sub_preds[j]["conformal_set"] for j in range(len(idxs))) / len(idxs), 4)
            confs = np.array([p["confidence"] for p in sub_preds], dtype=np.float64)
            correct = np.array([sub_preds[j]["top_class"] == sub_y[j] for j in range(len(idxs))], dtype=np.float64)
            ece = 0.0
            for lo, hi in zip(np.linspace(0.0, 0.9, 10), np.linspace(0.1, 1.0, 10)):
                bmask = (confs >= lo) & ((confs <= hi) if hi == 1.0 else (confs < hi))
                if np.any(bmask):
                    ece += (float(np.sum(bmask)) / len(confs)) * abs(float(np.mean(correct[bmask])) - float(np.mean(confs[bmask])))
            ece = round(float(ece), 4)
            passed = bool(min_rec >= 0.80 and ece <= 0.05 and coverage >= 0.88)
            return {
                "count": int(len(idxs)),
                "per_class_recall": recalls,
                "min_recall": min_rec,
                "ece": ece,
                "conformal_coverage": coverage,
                "passed": passed,
            }

        bin_defs = (
            ("W2<=12", w2_gold <= 12.0),
            ("12<W2<=13", (w2_gold > 12.0) & (w2_gold <= 13.0)),
            ("13<W2<=14", (w2_gold > 13.0) & (w2_gold <= 14.0)),
            ("W2>14", w2_gold > 14.0),
        )
        bins_out = {name: _score_subset(bmask) for name, bmask in bin_defs}
        high_snr = _score_subset(w2_gold <= 14.0)
        high_snr_bins_ok = all(
            bins_out[bname]["passed"]
            for bname in ("W2<=12", "12<W2<=13", "13<W2<=14")
            if bins_out[bname]["count"] > 0
        )
        return {
            "excluded_silver_count": excluded_silver,
            "high_snr_gold": high_snr,
            "brightness_bins": bins_out,
            "release_status": "PUBLISHED" if (high_snr["passed"] and high_snr_bins_ok) else "UNPUBLISHED",
        }


def _allocate_stratified_tiles(tiles, y=None, fracs=(0.60, 0.20, 0.20), random_state=42):
    """Partition unique sky tiles into disjoint buckets while stratifying rare classes first."""
    uniq_tiles = sorted(set(tiles.tolist()), key=str)
    n_tiles = len(uniq_tiles)
    k = len(fracs)
    if n_tiles < k:
        raise ValueError(f"Need at least {k} distinct sky tiles, got {n_tiles}")
    rng = np.random.default_rng(random_state)
    if y is None:
        perm = [uniq_tiles[i] for i in rng.permutation(n_tiles)]
        n2 = max(1, int(round(fracs[2] * n_tiles)))
        n1 = max(1, int(round(fracs[1] * n_tiles)))
        n0 = max(1, n_tiles - n1 - n2)
        return [set(perm[:n0]), set(perm[n0 : n0 + n1]), set(perm[n0 + n1 :])]

    y_arr = np.asarray(y)
    cls_tiles = {}
    tile_classes = {t: set() for t in uniq_tiles}
    for tile_val, cls_val in zip(tiles.tolist(), y_arr.tolist()):
        cls_str = str(cls_val)
        tile_classes[tile_val].add(cls_str)
        cls_tiles.setdefault(cls_str, set()).add(tile_val)

    rarity = {c: len(ts) for c, ts in cls_tiles.items()}
    strata = {}
    for t in uniq_tiles:
        rarest_cls = min(tile_classes[t], key=lambda c: (rarity[c], c))
        strata.setdefault(rarest_cls, []).append(t)

    buckets = [set() for _ in range(k)]
    # Allocate rarest-class tile strata first so small classes get disjoint coverage across all splits.
    for cls_key in sorted(strata.keys(), key=lambda c: (len(strata[c]), rarity[c], c)):
        group = sorted(strata[cls_key], key=str)
        shuffled = [group[i] for i in rng.permutation(len(group))]
        m = len(shuffled)
        if m >= k:
            counts = [1] * k
            for _ in range(m - k):
                b_pick = max(range(k), key=lambda b: (m * fracs[b] - counts[b], -b))
                counts[b_pick] += 1
        else:
            counts = [0] * k
            for _ in range(m):
                b_pick = max(range(k), key=lambda b: (fracs[b] * max(n_tiles, 1) - len(buckets[b]) - counts[b], -b))
                counts[b_pick] += 1
        offset = 0
        for b, cnt in enumerate(counts):
            if cnt > 0:
                buckets[b].update(shuffled[offset : offset + cnt])
                offset += cnt
    return buckets


def split_by_sky_tile(sky_tiles, y=None, label_grades=None, train_frac=0.60, cal_frac=0.20, test_frac=0.20, random_state=42):
    """Split dataset indices by disjoint sky tiles (60% train, 20% calibrate, 20% test) with Gold-only test set."""
    tiles = np.asarray(sky_tiles)
    uniq_tiles = sorted(set(tiles.tolist()), key=str)
    if len(uniq_tiles) < 3:
        raise ValueError("split_by_sky_tile requires at least 3 distinct sky tiles")
    train_tiles, cal_tiles, test_tiles = _allocate_stratified_tiles(
        tiles, y=y, fracs=(train_frac, cal_frac, test_frac), random_state=random_state
    )

    train_idx = np.where(np.isin(tiles, list(train_tiles)))[0]
    cal_idx = np.where(np.isin(tiles, list(cal_tiles)))[0]
    test_idx = np.where(np.isin(tiles, list(test_tiles)))[0]
    if label_grades is not None:
        grades = np.array([str(g).strip().lower() for g in label_grades])
        test_idx = test_idx[grades[test_idx] == "gold"]
    return {
        "train_idx": train_idx,
        "cal_idx": cal_idx,
        "test_idx": test_idx,
        "train_tiles": sorted(train_tiles, key=str),
        "cal_tiles": sorted(cal_tiles, key=str),
        "test_tiles": sorted(test_tiles, key=str),
    }


def train_from_real_dataset(dataset, build_templates_fn, max_per_class=6, random_state=42):
    """Single shared zero-leakage training entrypoint used by both ml/train.py and phantom_worlds/api.py."""
    wl = np.asarray(dataset["wavelength_um"], dtype=np.float64)
    bw = np.asarray(dataset["bandwidth_um"], dtype=np.float64)
    X = np.asarray(dataset["X_flux_uJy"], dtype=np.float64)
    X_err = np.asarray(dataset["X_err_uJy"], dtype=np.float64) if "X_err_uJy" in dataset else None
    y = np.asarray(dataset["y_class"])
    subtypes = np.asarray(dataset["subclass"]) if "subclass" in dataset else None
    tiles = np.asarray(dataset["sky_tiles"])
    grades = np.asarray(dataset["label_grades"]) if "label_grades" in dataset else np.full(len(y), "gold")
    blends = np.asarray(dataset["blend_shares"], dtype=np.float64) if "blend_shares" in dataset else np.full(len(y), 0.05)
    hybrids = np.asarray(dataset["spiff_hybrid_templates_uJy"], dtype=np.float64) if "spiff_hybrid_templates_uJy" in dataset else None

    split = split_by_sky_tile(tiles, y=y, label_grades=grades, random_state=random_state)
    fit_mask = np.concatenate([split["train_idx"], split["cal_idx"]])
    outer_test_tiles = set(split["test_tiles"])
    test_all_idx = np.where(np.isin(tiles, list(outer_test_tiles)))[0]

    # Determine internal train/isotonic/conformal tile split before building E1 templates so E1 sees train-only rows.
    dummy_lib = {str(c): np.ones(len(wl), dtype=np.float64) for c in sorted(set(str(v) for v in y.tolist()))}
    probe = SpectralDiscoveryPipeline(wl, bw, template_library=dummy_lib, random_state=random_state)
    tr_rel, iso_rel, conf_rel = probe._split_fit_indices(y[fit_mask], sky_tiles=tiles[fit_mask], label_grades=grades[fit_mask])

    e1_templates = build_templates_fn(
        X[fit_mask][tr_rel],
        y[fit_mask][tr_rel],
        hybrid_templates=hybrids,
        max_per_class=max_per_class,
    )
    tr_tiles_in = set(tiles[fit_mask][tr_rel].tolist())
    iso_tiles_in = set(tiles[fit_mask][iso_rel].tolist())
    conf_tiles_in = set(tiles[fit_mask][conf_rel].tolist())
    strict_disjoint = bool(
        not (tr_tiles_in & iso_tiles_in)
        and not (tr_tiles_in & conf_tiles_in)
        and not (iso_tiles_in & conf_tiles_in)
        and not (tr_tiles_in & outer_test_tiles)
        and not (iso_tiles_in & outer_test_tiles)
        and not (conf_tiles_in & outer_test_tiles)
    )

    pipe = SpectralDiscoveryPipeline(wl, bw, template_library=e1_templates, random_state=random_state)
    pipe.fit(
        X[fit_mask],
        y[fit_mask],
        blend_shares=blends[fit_mask],
        sky_tiles=tiles[fit_mask],
        label_grades=grades[fit_mask],
        X_err=(X_err[fit_mask] if X_err is not None else None),
        subtypes=(subtypes[fit_mask] if subtypes is not None else None),
    )
    return {
        "pipeline": pipe,
        "e1_templates": e1_templates,
        "split": split,
        "fit_mask": fit_mask,
        "tr_rel": tr_rel,
        "iso_rel": iso_rel,
        "conf_rel": conf_rel,
        "test_all_idx": test_all_idx,
        "test_gold_idx": split["test_idx"],
        "strict_tile_disjointness": strict_disjoint,
    }


def evaluate_cross_extraction_ratio(our_spectra, reference_spectra, max_band_tol=0.10):
    """Compare extracted spectra against reference library band by band (ml-research.md §5.H.5 & §9: median ratio within 10%)."""
    ours = np.asarray(our_spectra, dtype=np.float64)
    refs = np.asarray(reference_spectra, dtype=np.float64)
    if ours.shape != refs.shape or ours.ndim != 2:
        raise ValueError("our_spectra and reference_spectra must be 2D arrays with matching shape")
    valid = np.isfinite(ours) & np.isfinite(refs) & (ours > 0) & (refs > 0)
    band_medians = []
    for col in range(ours.shape[1]):
        m = valid[:, col]
        band_medians.append(round(float(np.median(ours[m, col] / refs[m, col])), 4) if np.any(m) else None)
    finite_meds = [v for v in band_medians if v is not None]
    max_dev = max((abs(v - 1.0) for v in finite_meds), default=float("inf"))
    return {
        "band_median_ratios": band_medians,
        "valid_band_count": int(len(finite_meds)),
        "max_abs_deviation": round(max_dev, 4) if math.isfinite(max_dev) else None,
        "passed": bool(math.isfinite(max_dev) and max_dev <= float(max_band_tol)),
    }


def evaluate_input_ladder(dataset, fit_res, random_state=42):
    """Evaluate Rungs 1-5 (E0 molecules -> band slopes -> 102 bands -> spectrum_alone -> +Gaia) on identical sky-tile test splits."""
    pipe = fit_res["pipeline"]
    wl = np.asarray(dataset["wavelength_um"], dtype=np.float64)
    bw = np.asarray(dataset["bandwidth_um"], dtype=np.float64)
    X = np.asarray(dataset["X_flux_uJy"], dtype=np.float64)
    X_err = np.asarray(dataset["X_err_uJy"], dtype=np.float64) if "X_err_uJy" in dataset else None
    y = np.asarray(dataset["y_class"])
    grades = np.asarray(dataset["label_grades"]) if "label_grades" in dataset else np.full(len(y), "gold")
    blends = np.asarray(dataset["blend_shares"], dtype=np.float64) if "blend_shares" in dataset else np.full(len(y), 0.05)
    plx = np.asarray(dataset["gaia_parallax_mas"], dtype=np.float64) if "gaia_parallax_mas" in dataset else np.full(len(y), np.nan)
    tr_idx = fit_res["fit_mask"][fit_res["tr_rel"]]
    te_all = fit_res["test_all_idx"]
    te_gold = fit_res["test_gold_idx"]
    tr_w = np.where(np.array([str(g).strip().lower() == "silver" for g in grades[tr_idx]]), 0.5, 1.0)

    def _mol_vec(idx_arr):
        rows = []
        for idx in idx_arr:
            res = compute_molecule_readings(wl, bw, X[idx], blend_share=0.0, is_variable=False, rng_seed=0)
            feats = res.get("features", {})
            rows.append([
                float((feats.get(m) or {}).get("integrated_tau"))
                if (feats.get(m) or {}).get("integrated_tau") is not None
                else np.nan
                for m in ("H2O_ice_3_05", "CH4_3_3", "CO2_4_26", "CO_4_67")
            ])
        return np.asarray(rows, dtype=np.float64)

    all_colors = pipe._extract_features(X)
    rungs = {}
    clf_kwargs = dict(max_iter=80, max_depth=4, min_samples_leaf=3, l2_regularization=0.4, class_weight="balanced", random_state=random_state)
    feature_sets = {
        "rung1_e0_molecules_only": _mol_vec(np.arange(len(y))),
        "rung2_stage10_band_features": all_colors[:, -min(12, all_colors.shape[1]):],
        "rung3_all_102_bands": all_colors[:, : max(1, all_colors.shape[1] - 12)],
    }
    for name, fmat in feature_sets.items():
        clf = HistGradientBoostingClassifier(**clf_kwargs)
        clf.fit(fmat[tr_idx], y[tr_idx], sample_weight=tr_w)
        all_acc = float(np.mean(clf.predict(fmat[te_all]) == y[te_all])) if len(te_all) else 0.0
        gold_acc = float(np.mean(clf.predict(fmat[te_gold]) == y[te_gold])) if len(te_gold) else 0.0
        rungs[name] = {
            "n_features": int(fmat.shape[1]),
            "test_all_accuracy": round(all_acc, 4),
            "test_gold_accuracy": round(gold_acc, 4),
        }

    # Rung 4 (spectrum_alone) & Rung 5 (+Gaia parallax gate on conservative parallax > 1.0 mas proxy)
    p4_all = [
        pipe.predict_one(X[i], blend_share=float(blends[i]), flux_err=(X_err[i] if X_err is not None else None))["spectrum_alone"]["top_class"]
        for i in te_all
    ]
    p4_gold = [
        pipe.predict_one(X[i], blend_share=float(blends[i]), flux_err=(X_err[i] if X_err is not None else None))["spectrum_alone"]["top_class"]
        for i in te_gold
    ]
    rungs["rung4_bands_plus_stage10_spectrum_alone"] = {
        "n_features": int(all_colors.shape[1]),
        "test_all_accuracy": round(float(np.mean([p4_all[j] == str(y[te_all[j]]) for j in range(len(te_all))])) if len(te_all) else 0.0, 4),
        "test_gold_accuracy": round(float(np.mean([p4_gold[j] == str(y[te_gold[j]]) for j in range(len(te_gold))])) if len(te_gold) else 0.0, 4),
    }

    p5_all = [
        pipe.predict_one(
            X[i],
            blend_share=float(blends[i]),
            flux_err=(X_err[i] if X_err is not None else None),
            parallax_snr=(10.0 if (math.isfinite(float(plx[i])) and float(plx[i]) > 1.0) else 0.0),
        )["all_data"]["top_class"]
        for i in te_all
    ]
    p5_gold = [
        pipe.predict_one(
            X[i],
            blend_share=float(blends[i]),
            flux_err=(X_err[i] if X_err is not None else None),
            parallax_snr=(10.0 if (math.isfinite(float(plx[i])) and float(plx[i]) > 1.0) else 0.0),
        )["all_data"]["top_class"]
        for i in te_gold
    ]
    rungs["rung5_all_data_with_gaia_parallax"] = {
        "n_features": int(all_colors.shape[1]),
        "gaia_parallax_measured_frac_test": round(float(np.mean(np.isfinite(plx[te_all]))) if len(te_all) else 0.0, 4),
        "test_all_accuracy": round(float(np.mean([p5_all[j] == str(y[te_all[j]]) for j in range(len(te_all))])) if len(te_all) else 0.0, 4),
        "test_gold_accuracy": round(float(np.mean([p5_gold[j] == str(y[te_gold[j]]) for j in range(len(te_gold))])) if len(te_gold) else 0.0, 4),
    }
    return rungs


def evaluate_fixed_targets(wavelengths, bandwidths, spectra_by_slug, pipeline, errs_by_slug=None):
    """Verify the 5 fixed NASA benchmark targets against ml-research.md §8 expected readings."""
    target_configs = (
        ("Barnards_Star", False, 0.02, ("Star",)),
        ("Eps_Indi_B", False, 0.14, ("Ultracool dwarf",)),
        ("WISE_0855", False, 0.08, ("Ultracool dwarf", "Unclassified")),
        ("RW_Aurigae", True, 0.18, ("Young star with ice or dust", "Unclassified")),
        ("R_Draconis", True, 0.05, ("Evolved giant star", "Unclassified")),
    )
    results = {}
    all_passed = True
    for slug, is_var, blend, allowed_classes in target_configs:
        fl = np.asarray(spectra_by_slug[slug], dtype=np.float64)
        ferr = np.asarray(errs_by_slug[slug], dtype=np.float64) if (errs_by_slug is not None and slug in errs_by_slug) else None
        mol = compute_molecule_readings(wavelengths, bandwidths, fl, flux_err=ferr, blend_share=blend, is_variable=is_var, rng_seed=0)
        pred = pipeline.predict_one(fl, blend_share=blend, is_variable=is_var, flux_err=ferr)
        top_cls = pred["spectrum_alone"]["top_class"]
        mol_status = mol["status"]
        ch4_tau = (mol.get("features", {}).get("CH4_3_3", {}) or {}).get("integrated_tau")
        co_tau = (mol.get("features", {}).get("CO_4_67", {}) or {}).get("integrated_tau")
        if is_var:
            ok = (mol_status == "REFUSED") and (pred["novelty"]["status"] == "CONTAMINATION_SCREENED") and (top_cls in allowed_classes)
        elif slug == "Barnards_Star":
            ok = (top_cls in allowed_classes) and (mol_status == "MEASURED") and (ch4_tau is not None and ch4_tau < 10.0)
        elif slug == "Eps_Indi_B":
            ok = (top_cls in allowed_classes) and (mol_status == "MEASURED") and (ch4_tau is not None and ch4_tau > 20.0)
        else:
            ok = (top_cls in allowed_classes) and (mol_status == "MEASURED") and (ch4_tau is not None and ch4_tau > 0.0) and (co_tau is not None and co_tau > 0.0)
        all_passed = all_passed and bool(ok)
        results[slug] = {
            "top_class": top_cls,
            "molecule_status": mol_status,
            "novelty_status": pred["novelty"]["status"],
            "ch4_tau": ch4_tau,
            "co_tau": co_tau,
            "passed": bool(ok),
        }
    return {"all_passed": all_passed, "targets": results}
