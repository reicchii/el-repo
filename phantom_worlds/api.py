from collections import OrderedDict
import csv
import json
import math
import os
import re
import threading
import time
from typing import List, Literal, Optional

import astropy.units as u
from astropy.coordinates import SkyCoord
import numpy as np
import pyvo
from fastapi import FastAPI, HTTPException, Query
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field, field_validator

from phantom_worlds.contracts import (
    ALLOWED_REMOTE_HOSTS,
    DEFAULT_CONTRACTS_DIR,
    DEFAULT_CSV_DIR,
    DETECTOR_INDEX,
    HardenedHTTPSession,
    PACKAGE_ROOT,
    TARGET_SPECS,
    build_export_packet,
    build_target_spectrum_102,
    detector_visit_stacks,
    is_safe_s3_key,
    load_cases,
    load_manifest,
    load_patch_arrays,
    load_sources,
    load_spectra_table,
    load_targets,
    propagate_position,
    safe_remote_url,
    safe_s3_cloud_access_url,
)
from phantom_worlds.ml_pipeline import SpectralDiscoveryPipeline, compute_molecule_readings, train_from_real_dataset
from phantom_worlds.real_ml_data import (
    DEFAULT_ML_DIR,
    build_balanced_e1_templates,
    load_real_training_dataset,
    resample_spectrum_to_grid,
)

CASE_ID_RE = re.compile(r"^[A-Za-z0-9_-]{3,64}$")
DEFAULT_DATA_REAL_DIR = os.path.join(PACKAGE_ROOT, "phantom_worlds_dataset_kit", "scripts", "data_real")
DEFAULT_REAL_DATASET_NPZ = os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz")
_UNSET_DATASET = object()
STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")
_STATIC_ASSETS = {
    "viewer.js": "application/javascript; charset=utf-8",
    "fallback_data.js": "application/javascript; charset=utf-8",
    "styles.css": "text/css; charset=utf-8",
}
_UI_BASE_CSP = (
    "default-src 'self'; script-src 'self'; style-src 'self'; "
    "img-src 'self' data:; object-src 'none'; base-uri 'self'; form-action 'self'; "
)
_UI_BASE_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "Referrer-Policy": "strict-origin-when-cross-origin",
}
_DEFAULT_EMBED_FRAME_ANCESTORS = (
    "'self'",
    "https://*.nasa.gov",
    "https://*.spaceappschallenge.org",
    "https://localhost:*",
    "https://127.0.0.1:*",
    "http://localhost:*",
    "http://127.0.0.1:*",
)
_EMBED_ANCESTOR_RE = re.compile(
    r"^(?:'self'|https://(?:\*\.)?[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+(?::(?:\*|\d{1,5}))?|https?://(?:localhost|127\.0\.0\.1)(?::(?:\*|\d{1,5}))?)$"
)


def _build_embed_csp_headers(embed_frame_ancestors=None):
    if embed_frame_ancestors is None:
        env_raw = os.environ.get("PHANTOM_EMBED_FRAME_ANCESTORS", "").strip()
        ancestors = [tok for tok in re.split(r"[\s,]+", env_raw) if tok] if env_raw else list(_DEFAULT_EMBED_FRAME_ANCESTORS)
    else:
        ancestors = [str(tok).strip() for tok in embed_frame_ancestors if str(tok).strip()]
    if not ancestors:
        ancestors = ["'self'"]
    for tok in ancestors:
        if not _EMBED_ANCESTOR_RE.fullmatch(tok):
            raise ValueError(f"Unsafe CSP frame-ancestors origin: {tok!r}")
    return {
        **_UI_BASE_SECURITY_HEADERS,
        "Content-Security-Policy": _UI_BASE_CSP + "frame-ancestors " + " ".join(ancestors),
    }


_UI_SECURITY_HEADERS = {
    **_UI_BASE_SECURITY_HEADERS,
    "Content-Security-Policy": _UI_BASE_CSP + "frame-ancestors 'self'",
}
# Embed mode allows explicit NASA/dev iframe ancestors (never bare https: wildcard) while retaining strict script CSP.
_UI_EMBED_SECURITY_HEADERS = _build_embed_csp_headers()
_TARGET_ASSETS = TARGET_SPECS
_ALLOWED_REMOTE_HOSTS = ALLOWED_REMOTE_HOSTS
_COORD_PAIR_RE = re.compile(r"^\s*([+-]?\d+(?:\.\d+)?)\s*[, ]\s*([+-]?\d+(?:\.\d+)?)\s*$")
_LIVE_IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"
_SPHEREX_COLLECTIONS = (
    "spherex_dr1",
    "spherex_qr3",
    "spherex_dr1_deep",
    "spherex_qr3_deep",
    "spherex_dr1_cube",
)
_LIVE_IRSA_TIMEOUT = (5, 15)
_LIVE_IRSA_MAXREC = 100
_LIVE_IRSA_CACHE_TTL_SEC = 60.0
_LIVE_IRSA_CACHE_MAX_ENTRIES = 64
_LIVE_IRSA_TOTAL_BUDGET_SEC = 25.0
_LIVE_IRSA_BUSY_MSG = "Live IRSA archive query busy; showing local results only."
_LIVE_IRSA_SEMAPHORE = threading.BoundedSemaphore(4)


class _LiveIrsaSession(HardenedHTTPSession):
    """Hardened HTTPS session restricted to IRSA with bounded timeouts, zero redirects, and no env proxies/.netrc."""

    def __init__(self, timeout=_LIVE_IRSA_TIMEOUT):
        super().__init__(timeout=timeout, allowed_hosts={"irsa.ipac.caltech.edu"})


class SpectrumAnalyzeRequest(BaseModel):
    flux_uJy: List[Optional[float]] = Field(..., min_length=102, max_length=102)
    flux_err_uJy: Optional[List[Optional[float]]] = Field(default=None, min_length=102, max_length=102)
    blend_share: float = Field(default=0.0, ge=0.0, le=1.0)
    is_variable: bool = False
    parallax_snr: Optional[float] = Field(default=None)

    @field_validator("flux_uJy")
    @classmethod
    def check_finite_flux(cls, values):
        out = []
        finite_count = 0
        for v in values:
            if v is None:
                out.append(float("nan"))
            else:
                fv = float(v)
                if not math.isfinite(fv) or abs(fv) > 1e30:
                    raise ValueError("flux_uJy values must be finite and within [-1e30, 1e30]")
                out.append(fv)
                finite_count += 1
        if finite_count < 3:
            raise ValueError("flux_uJy must contain at least 3 non-null finite bands")
        return out

    @field_validator("flux_err_uJy")
    @classmethod
    def check_finite_err(cls, values):
        if values is None:
            return None
        out = []
        for v in values:
            if v is None:
                out.append(float("nan"))
            else:
                fv = float(v)
                if not math.isfinite(fv) or fv < 0.0 or fv > 1e30:
                    raise ValueError("flux_err_uJy values must be non-negative finite floats <= 1e30")
                out.append(fv)
        return out

    @field_validator("parallax_snr")
    @classmethod
    def check_finite_parallax_snr(cls, value):
        if value is None:
            return None
        fv = float(value)
        if not math.isfinite(fv) or abs(fv) > 1e12:
            raise ValueError("parallax_snr must be finite")
        return fv


def _build_default_discovery_pipeline(spectra_ref, dataset_npz_path=None):
    if dataset_npz_path and os.path.exists(dataset_npz_path):
        dataset = load_real_training_dataset(dataset_npz_path)
        fit_res = train_from_real_dataset(dataset, build_balanced_e1_templates, max_per_class=6, random_state=42)
        return fit_res["pipeline"], "real_spherex_dr1_spiff_trained"

    wl = np.asarray(spectra_ref["wavelength_um"], dtype=np.float64)
    bw = np.asarray(spectra_ref["bandwidth_um"], dtype=np.float64)
    rows = spectra_ref["rows"]
    col = lambda name: np.array([float(r[name]) for r in rows], dtype=np.float64)
    galaxy_tmpl = 40.0 + 30.0 * ((wl - wl.min()) / max(wl.max() - wl.min(), 1e-6)) ** 2
    templates = {
        "Star": col("Barnards_Star_uJy"),
        "Ultracool dwarf": [col("Eps_Indi_B_uJy"), col("WISE_0855_uJy")],
        "Young star with ice or dust": col("RW_Aurigae_uJy"),
        "Evolved giant star": col("R_Draconis_uJy"),
        "Galaxy": galaxy_tmpl,
    }
    rng = np.random.default_rng(42)
    X_ref, y_ref = [], []
    for label, base_entry in templates.items():
        variants = base_entry if isinstance(base_entry, list) else [base_entry]
        for idx in range(20):
            base = variants[idx % len(variants)]
            scale = rng.uniform(0.75, 1.25)
            noise = rng.normal(0.0, 0.025 * np.maximum(base, 0.2))
            X_ref.append(np.maximum(base * scale + noise, 0.01))
            y_ref.append(label)
    pipe = SpectralDiscoveryPipeline(wl, bw, template_library=templates, random_state=42)
    pipe.fit(np.asarray(X_ref, dtype=np.float64), np.asarray(y_ref), blend_shares=np.full(len(y_ref), 0.05))
    return pipe, "hour0_reference_template_bootstrap"


def _align_spectrum_to_model_grid(src_wl, fl_arr, err_arr, dst_wl):
    if len(dst_wl) == len(src_wl) and np.allclose(dst_wl, src_wl, atol=1e-4):
        return fl_arr, err_arr
    if err_arr is not None:
        fl_out, err_out = resample_spectrum_to_grid(src_wl, fl_arr, dst_wl, src_err=err_arr)
    else:
        fl_out = resample_spectrum_to_grid(src_wl, fl_arr, dst_wl)
        err_out = None
    # Preserve endpoint continuity across ~0.007 um SPHEREx filter-edge offsets only when boundary inputs are finite.
    i_lo = int(np.argmin(src_wl))
    i_hi = int(np.argmax(src_wl))
    if np.isfinite(fl_arr[i_lo]) and fl_arr[i_lo] > 0:
        mask_lo = (dst_wl < src_wl[i_lo]) & (dst_wl >= src_wl[i_lo] - 0.025)
        fl_out[mask_lo] = fl_arr[i_lo]
        if err_out is not None and err_arr is not None and np.isfinite(err_arr[i_lo]):
            err_out[mask_lo] = err_arr[i_lo]
    if np.isfinite(fl_arr[i_hi]) and fl_arr[i_hi] > 0:
        mask_hi = (dst_wl > src_wl[i_hi]) & (dst_wl <= src_wl[i_hi] + 0.025)
        fl_out[mask_hi] = fl_arr[i_hi]
        if err_out is not None and err_arr is not None and np.isfinite(err_arr[i_hi]):
            err_out[mask_hi] = err_arr[i_hi]
    return fl_out, err_out


def _angular_sep_arcmin(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    ra1, dec1, ra2, dec2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    a = (
        math.sin((dec2 - dec1) / 2.0) ** 2
        + math.cos(dec1) * math.cos(dec2) * (math.sin((ra2 - ra1) / 2.0) ** 2)
    )
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))) * 60.0


def _grid_to_json(arr2d):
    finite = np.isfinite(arr2d)
    rounded = np.zeros_like(arr2d, dtype=np.float64)
    rounded[finite] = np.round(arr2d[finite], 4)
    return np.where(finite, rounded.astype(object), None).tolist()


def _safe_float(val):
    if val is None or val == "" or np.ma.is_masked(val):
        return None
    try:
        out = float(val)
    except (TypeError, ValueError):
        return None
    return out if math.isfinite(out) else None


_is_safe_s3_key = is_safe_s3_key
_safe_remote_url = safe_remote_url
_safe_s3_url = safe_s3_cloud_access_url


def _parse_sky_input(coord, ra_deg, dec_deg, targets_list):
    if ra_deg is not None or dec_deg is not None:
        if ra_deg is None or dec_deg is None:
            raise HTTPException(status_code=422, detail="Provide both ra_deg and dec_deg")
        if not (math.isfinite(ra_deg) and 0.0 <= ra_deg <= 360.0 and math.isfinite(dec_deg) and -90.0 <= dec_deg <= 90.0):
            raise HTTPException(status_code=422, detail="ra_deg must be in [0, 360] and dec_deg in [-90, 90]")
        return float(ra_deg) % 360.0, float(dec_deg), None

    if not coord or not coord.strip() or len(coord.strip()) > 100:
        raise HTTPException(status_code=422, detail="Provide valid coord or numeric ra_deg/dec_deg")

    clean = coord.strip()
    norm = clean.lower()
    for row in targets_list:
        meta = _TARGET_ASSETS.get(row["target_id"], {})
        if norm == row["name"].lower() or norm in meta.get("aliases", ()):
            return float(row["ra_deg_j2000"]), float(row["dec_deg_j2000"]), row["target_id"]

    m = _COORD_PAIR_RE.match(clean)
    if m:
        ra_v, dec_v = float(m.group(1)), float(m.group(2))
        if not (0.0 <= ra_v <= 360.0 and -90.0 <= dec_v <= 90.0):
            raise HTTPException(status_code=422, detail="Numeric coordinates out of bounds")
        return ra_v % 360.0, dec_v, None

    try:
        if ":" in clean and "h" not in norm:
            sc = SkyCoord(clean, unit=(u.hourangle, u.deg), frame="icrs")
        elif "h" in norm or "d" in norm:
            sc = SkyCoord(clean, frame="icrs")
        else:
            raise ValueError("Unsupported coordinate syntax")
        return float(sc.ra.deg) % 360.0, float(sc.dec.deg), None
    except Exception as exc:
        raise HTTPException(status_code=422, detail="Invalid sky coordinate or unknown target name") from exc


def _serialize_detector_timeseries(manifest, flux_cube, mask_cube, detector_id, spectra_ref, stack_grid=None):
    det_idx = DETECTOR_INDEX[detector_id]
    visits_cube = flux_cube[:, det_idx, :, :]
    if stack_grid is None:
        stack_grid = detector_visit_stacks(flux_cube, detector_id=detector_id)
    diff_grid = visits_cube[-1] - visits_cube[0]
    mask_det = mask_cube[:, det_idx, :, :]
    flags = manifest["quality_mask_layout"]["flag_bits"]
    wls = [float(r["wavelength_um"]) for r in spectra_ref["rows"] if r["detector"] == detector_id]
    return {
        "target_id": manifest["target_id"],
        "detector": detector_id,
        "shape": [int(visits_cube.shape[1]), int(visits_cube.shape[2])],
        "wavelength_range_um": [round(min(wls), 4), round(max(wls), 4)],
        "visits": manifest["visits"],
        "frames_by_visit": [_grid_to_json(visits_cube[v]) for v in range(visits_cube.shape[0])],
        "stack": _grid_to_json(stack_grid),
        "difference": _grid_to_json(diff_grid),
        "mask_overlay": np.bitwise_or.reduce(mask_det, axis=0).tolist(),
        "mask_summary": {
            "irsa_rejected_px": int(np.count_nonzero((mask_det & int(flags["IRSA_REJECTED"])) != 0)),
            "overflow_saturated_px": int(np.count_nonzero((mask_det & int(flags["OVERFLOW_SATURATED"])) != 0)),
            "edge_masked_px": int(np.count_nonzero((mask_det & int(flags.get("EDGE_MASKED", 4))) != 0)),
        },
        "center_ra_deg": float(manifest["center_ra_deg"]),
        "center_dec_deg": float(manifest["center_dec_deg"]),
        "fov_arcmin": float(manifest["fov_arcmin"]),
        "pixel_scale_arcsec": float(manifest["pixel_scale_arcsec"]),
        "target_j2000_ra_deg": float(manifest["target_j2000_ra_deg"]),
        "target_j2000_dec_deg": float(manifest["target_j2000_dec_deg"]),
    }


def _load_local_target_frames(data_real_dir, slug, limit: Optional[int] = None):
    frames_path = os.path.join(data_real_dir, f"{slug}_spherex_frames.csv")
    if not os.path.exists(frames_path):
        return []
    rows = []
    with open(frames_path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            access_url = raw.get("access_url", "")
            safe_access = _safe_remote_url(access_url)
            rows.append(
                {
                    "obs_collection": raw.get("obs_collection", ""),
                    "obs_id": raw.get("obs_id", ""),
                    "s_ra": _safe_float(raw.get("s_ra")),
                    "s_dec": _safe_float(raw.get("s_dec")),
                    "energy_bandpassname": raw.get("energy_bandpassname") or "",
                    "em_min": _safe_float(raw.get("em_min")),
                    "em_max": _safe_float(raw.get("em_max")),
                    "t_min": _safe_float(raw.get("t_min")),
                    "t_max": _safe_float(raw.get("t_max")),
                    "access_url": safe_access,
                    "s3_fits_url": _safe_s3_url(raw.get("cloud_access", "")),
                }
            )
    # Newest epochs first so recent QR3/QR3_deep releases lead and no archive rows are silently truncated.
    rows.sort(key=lambda r: (r["t_min"] is None, -(r["t_min"] or 0.0), r["obs_id"]))
    return rows[:limit] if limit is not None else rows


def _read_local_gaia_rows(data_real_dir, slug, csv_dir=DEFAULT_CSV_DIR):
    gaia_path = os.path.join(data_real_dir, f"{slug}_gaia_dr3.csv")
    if not os.path.exists(gaia_path):
        return []
    catwise_map = {}
    if slug == "WISE_0855":
        patch_csv = os.path.join(csv_dir, "gaia_dr3_wise0855_patch.csv")
        if os.path.exists(patch_csv):
            with open(patch_csv, encoding="utf-8", newline="") as pf:
                for prow in csv.DictReader(pf):
                    sid = str(prow.get("gaia_source_id", ""))
                    if sid:
                        catwise_map[sid] = (
                            _safe_float(prow.get("catwise_w1_mag")),
                            _safe_float(prow.get("catwise_w2_mag")),
                        )
    rows = []
    with open(gaia_path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            ra16 = _safe_float(raw.get("ra"))
            dec16 = _safe_float(raw.get("dec"))
            if ra16 is None or dec16 is None:
                continue
            sid = str(raw.get("source_id", ""))
            w1_mag, w2_mag = catwise_map.get(sid, (None, None))
            rows.append(
                (
                    sid,
                    ra16,
                    dec16,
                    _safe_float(raw.get("pmra")) or 0.0,
                    _safe_float(raw.get("pmdec")) or 0.0,
                    _safe_float(raw.get("phot_g_mean_mag")),
                    w1_mag,
                    w2_mag,
                )
            )
    return rows


def _load_local_gaia_sources(
    data_real_dir,
    slug,
    center_ra_deg,
    center_dec_deg,
    radius_arcmin,
    epoch_yr,
    limit=50,
    raw_rows=None,
):
    rows = _read_local_gaia_rows(data_real_dir, slug) if raw_rows is None else raw_rows
    dt_yr = epoch_yr - 2016.0
    matched = []
    for item in rows:
        source_id, ra16, dec16, pmra, pmdec, g_mag = item[:6]
        w1_mag, w2_mag = item[6:8] if len(item) >= 8 else (None, None)
        ra_ep, dec_ep = propagate_position(ra16, dec16, pmra, pmdec, dt_yr)
        if _angular_sep_arcmin(center_ra_deg, center_dec_deg, ra_ep, dec_ep) <= radius_arcmin:
            entry = {
                "source_id": source_id,
                "ra_deg": round(ra_ep, 6),
                "dec_deg": round(dec_ep, 6),
                "phot_g_mean_mag": g_mag,
                "pmra_mas_yr": round(pmra, 3),
                "pmdec_mas_yr": round(pmdec, 3),
            }
            if w1_mag is not None:
                entry["catwise_w1_mag"] = w1_mag
            if w2_mag is not None:
                entry["catwise_w2_mag"] = w2_mag
            matched.append(entry)
    matched.sort(
        key=lambda s: (
            s["phot_g_mean_mag"] is None,
            s["phot_g_mean_mag"] if s["phot_g_mean_mag"] is not None else 99.0,
        )
    )
    return matched[:limit]


def _frame_dedup_key(frame):
    band = frame.get("energy_bandpassname") or ""
    if band:
        return (frame.get("obs_collection"), frame.get("obs_id"), band)
    em_min = frame.get("em_min")
    return (
        frame.get("obs_collection"),
        frame.get("obs_id"),
        round(float(em_min), 9) if em_min is not None else "",
    )


def _fetch_live_sky_data(ra_deg, dec_deg, radius_deg):
    """Query NASA/IPAC IRSA SIAv2 on demand for arbitrary sky coordinates."""
    frames = []
    warnings_list = []
    if not _LIVE_IRSA_SEMAPHORE.acquire(blocking=False):
        return [], [], [_LIVE_IRSA_BUSY_MSG]
    try:
        failed_collections = []
        deadline = time.monotonic() + _LIVE_IRSA_TOTAL_BUDGET_SEC
        with _LiveIrsaSession() as sess:
            sia = pyvo.dal.SIA2Service(_LIVE_IRSA_SIA_URL, session=sess)
            for idx, coll in enumerate(_SPHEREX_COLLECTIONS):
                if idx > 0 and time.monotonic() >= deadline:
                    failed_collections.extend(_SPHEREX_COLLECTIONS[idx:])
                    break
                try:
                    tbl = sia.search(
                        pos=(ra_deg, dec_deg, radius_deg),
                        collection=coll,
                        maxrec=_LIVE_IRSA_MAXREC,
                    ).to_table()
                    for row in tbl[:_LIVE_IRSA_MAXREC]:
                        access_url = str(row["access_url"]) if "access_url" in tbl.colnames else ""
                        cloud = str(row["cloud_access"]) if "cloud_access" in tbl.colnames else ""
                        frames.append(
                            {
                                "obs_collection": coll,
                                "obs_id": str(row["obs_id"]) if "obs_id" in tbl.colnames else "",
                                "s_ra": _safe_float(row["s_ra"]) if "s_ra" in tbl.colnames else None,
                                "s_dec": _safe_float(row["s_dec"]) if "s_dec" in tbl.colnames else None,
                                "energy_bandpassname": str(row["energy_bandpassname"]) if "energy_bandpassname" in tbl.colnames else "",
                                "em_min": _safe_float(row["em_min"]) if "em_min" in tbl.colnames else None,
                                "em_max": _safe_float(row["em_max"]) if "em_max" in tbl.colnames else None,
                                "t_min": _safe_float(row["t_min"]) if "t_min" in tbl.colnames else None,
                                "t_max": _safe_float(row["t_max"]) if "t_max" in tbl.colnames else None,
                                "access_url": _safe_remote_url(access_url),
                                "s3_fits_url": _safe_s3_url(cloud),
                            }
                        )
                except Exception:
                    failed_collections.append(coll)
        if failed_collections:
            warnings_list.append(
                f"Live IRSA archive query failed for {len(failed_collections)}/{len(_SPHEREX_COLLECTIONS)} collections; showing available results."
            )
    except Exception:
        warnings_list.append("Live IRSA archive query failed; showing local results only.")
    finally:
        _LIVE_IRSA_SEMAPHORE.release()
    return frames, [], warnings_list


def create_app(
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    data_real_dir=DEFAULT_DATA_REAL_DIR,
    embed_frame_ancestors=None,
    dataset_npz_path=_UNSET_DATASET,
):
    """Build FastAPI application wired to Hour-0 contracts, ML Layer-1, Sky Time-Series API, and Web UI."""
    resolved_dataset_npz = (
        (DEFAULT_REAL_DATASET_NPZ if csv_dir == DEFAULT_CSV_DIR else None)
        if dataset_npz_path is _UNSET_DATASET
        else dataset_npz_path
    )
    app = FastAPI(title="Phantom Worlds API", version="1.0.0-hour0")
    embed_security_headers = (
        _build_embed_csp_headers(embed_frame_ancestors)
        if embed_frame_ancestors is not None or os.environ.get("PHANTOM_EMBED_FRAME_ANCESTORS", "").strip()
        else _UI_EMBED_SECURITY_HEADERS
    )
    spectra_ref = load_spectra_table(csv_dir)
    targets_list = load_targets(csv_dir)
    default_manifest = load_manifest(contracts_dir)
    default_target_id = default_manifest.get("target_id", "TGT-02")
    cache_lock = threading.Lock()
    live_lock = threading.Lock()
    manifest_cache = {default_target_id: default_manifest}
    patch_cache = {}
    stack_cache = {}
    frames_cache = {}
    gaia_rows_cache = {}
    json_cache = {}
    live_cache = OrderedDict()
    live_inflight = {}

    def _cached(store, key, loader):
        with cache_lock:
            val = store.get(key)
            if val is None:
                val = loader()
                store[key] = val
            return val

    def _query_live_cached(live_ra, live_dec, radius_deg):
        cache_key = (round(live_ra, 4), round(live_dec, 4), round(radius_deg, 4))
        now = time.monotonic()
        with live_lock:
            entry = live_cache.get(cache_key)
            if entry is not None:
                if (now - entry[0]) < _LIVE_IRSA_CACHE_TTL_SEC:
                    live_cache.move_to_end(cache_key)
                    cached = entry[1]
                    return list(cached[0]), list(cached[1]), list(cached[2])
                live_cache.pop(cache_key, None)
            inflight = live_inflight.get(cache_key)
            if inflight is None:
                inflight = {"event": threading.Event(), "result": None}
                live_inflight[cache_key] = inflight
                is_leader = True
            else:
                is_leader = False
        if is_leader:
            try:
                res = _fetch_live_sky_data(live_ra, live_dec, radius_deg)
                inflight["result"] = res
                if not res[2]:
                    with live_lock:
                        now_store = time.monotonic()
                        expired = [k for k, (ts, _) in live_cache.items() if (now_store - ts) >= _LIVE_IRSA_CACHE_TTL_SEC]
                        for k in expired:
                            live_cache.pop(k, None)
                        while len(live_cache) >= _LIVE_IRSA_CACHE_MAX_ENTRIES and cache_key not in live_cache:
                            live_cache.popitem(last=False)
                        live_cache[cache_key] = (now_store, (list(res[0]), list(res[1]), list(res[2])))
                        live_cache.move_to_end(cache_key)
                return list(res[0]), list(res[1]), list(res[2])
            finally:
                with live_lock:
                    live_inflight.pop(cache_key, None)
                    inflight["event"].set()
        if inflight["event"].wait(timeout=0.5) and inflight["result"] is not None:
            res = inflight["result"]
            return list(res[0]), list(res[1]), list(res[2])
        return [], [], [_LIVE_IRSA_BUSY_MSG]

    def _get_manifest(target_id=None):
        tid = target_id or default_target_id
        return _cached(
            manifest_cache,
            tid,
            lambda: load_manifest(contracts_dir, root_manifest=default_manifest)
            if tid == default_target_id
            else load_manifest(contracts_dir, target_id=tid, root_manifest=default_manifest),
        )

    def _get_patch_arrays(target_id=None):
        tid = target_id or default_target_id
        manifest = _get_manifest(tid)
        return _cached(
            patch_cache,
            tid,
            lambda: load_patch_arrays(
                contracts_dir,
                target_id=None if tid == default_target_id else tid,
                manifest=manifest,
                root_manifest=default_manifest,
            ),
        )

    def _get_detector_stack(detector_id, target_id=None):
        manifest, flux_cube, _ = _get_patch_arrays(target_id=target_id)
        key = (manifest["target_id"], detector_id)
        det_img = _cached(stack_cache, key, lambda: detector_visit_stacks(flux_cube, detector_id=detector_id))
        return manifest, det_img

    def _read_index_html():
        index_path = os.path.join(STATIC_DIR, "index.html")
        if not os.path.exists(index_path):
            raise HTTPException(status_code=404, detail="Viewer UI not found")
        with open(index_path, encoding="utf-8") as f:
            return f.read()

    @app.get("/", response_class=HTMLResponse)
    def web_ui(embed: Optional[str] = Query(default=None)):
        headers = embed_security_headers if embed == "1" else _UI_SECURITY_HEADERS
        return HTMLResponse(content=_cached(json_cache, "index_html", _read_index_html), headers=headers)

    @app.get("/static/{asset_name}")
    def static_asset(asset_name: str):
        media_type = _STATIC_ASSETS.get(asset_name)
        if media_type is None:
            raise HTTPException(status_code=404, detail="Asset not found")
        return FileResponse(
            os.path.join(STATIC_DIR, asset_name),
            media_type=media_type,
            headers={"X-Content-Type-Options": "nosniff"},
        )

    @app.get("/health")
    def health():
        return {"status": "ok", "schema_version": default_manifest["schema_version"], "mode": "static_fallback_ready"}

    @app.get("/api/targets")
    def list_targets(epoch_yr: float = Query(default=2026.0, ge=1900.0, le=2100.0)):
        dt_yr = epoch_yr - 2000.0
        out = []
        for row in targets_list:
            ra_ep, dec_ep = propagate_position(
                float(row["ra_deg_j2000"]),
                float(row["dec_deg_j2000"]),
                float(row["pm_ra_mas_yr"]),
                float(row["pm_dec_mas_yr"]),
                dt_yr,
            )
            out.append(
                {
                    "target_id": row["target_id"],
                    "name": row["name"],
                    "object_type": row["object_type"],
                    "ra_deg_j2000": float(row["ra_deg_j2000"]),
                    "dec_deg_j2000": float(row["dec_deg_j2000"]),
                    "epoch_yr": epoch_yr,
                    "ra_deg_at_epoch": round(ra_ep, 6),
                    "dec_deg_at_epoch": round(dec_ep, 6),
                }
            )
        return {"epoch_yr": epoch_yr, "targets": out}

    @app.get("/api/patch/manifest")
    def get_patch_manifest(target_id: Optional[Literal["TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"]] = None):
        return _get_manifest(target_id=target_id)

    @app.get("/api/patch/stack/{detector_id}")
    def get_detector_stack(
        detector_id: Literal["D1", "D2", "D3", "D4", "D5", "D6"],
        target_id: Optional[Literal["TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"]] = None,
    ):
        manifest, det_img = _get_detector_stack(detector_id, target_id=target_id)
        valid_mask = np.isfinite(det_img)
        return {
            "target_id": manifest["target_id"],
            "detector": detector_id,
            "shape": list(det_img.shape),
            "valid_pixels": int(np.count_nonzero(valid_mask)),
            "masked_pixels": int(det_img.size - np.count_nonzero(valid_mask)),
            "min_flux": float(np.nanmin(det_img)) if np.any(valid_mask) else None,
            "max_flux": float(np.nanmax(det_img)) if np.any(valid_mask) else None,
            "mean_flux": float(np.nanmean(det_img)) if np.any(valid_mask) else None,
        }

    @app.get("/api/patch/timeseries")
    def get_patch_timeseries(
        detector: Literal["D1", "D2", "D3", "D4", "D5", "D6"] = "D6",
        target_id: Optional[Literal["TGT-01", "TGT-02", "TGT-03", "TGT-04", "TGT-05"]] = None,
    ):
        manifest, flux_cube, mask_cube = _get_patch_arrays(target_id=target_id)
        _, det_img = _get_detector_stack(detector, target_id=target_id)
        return _serialize_detector_timeseries(manifest, flux_cube, mask_cube, detector, spectra_ref, stack_grid=det_img)

    @app.get("/api/sky/timeseries")
    def query_sky_timeseries(
        coord: Optional[str] = Query(default=None, max_length=100),
        ra_deg: Optional[float] = Query(default=None),
        dec_deg: Optional[float] = Query(default=None),
        fov_arcmin: float = Query(default=6.5, ge=0.5, le=30.0),
        epoch_yr: float = Query(default=2026.0, ge=1900.0, le=2100.0),
        detector: Literal["D1", "D2", "D3", "D4", "D5", "D6"] = "D6",
        live: bool = False,
        frame_limit: Optional[int] = Query(default=None, ge=1, le=5000),
        frame_offset: int = Query(default=0, ge=0),
    ):
        q_ra, q_dec, explicit_id = _parse_sky_input(coord, ra_deg, dec_deg, targets_list)
        dt_yr = epoch_yr - 2000.0

        matched_row = None
        match_ra_ep, match_dec_ep = q_ra, q_dec
        best_sep = float("inf")
        match_radius_arcmin = min(fov_arcmin / 2.0, float(default_manifest["fov_arcmin"]) / 2.0)
        for row in targets_list:
            ra_ep, dec_ep = propagate_position(
                float(row["ra_deg_j2000"]),
                float(row["dec_deg_j2000"]),
                float(row["pm_ra_mas_yr"]),
                float(row["pm_dec_mas_yr"]),
                dt_yr,
            )
            if explicit_id == row["target_id"]:
                matched_row, match_ra_ep, match_dec_ep, best_sep = row, ra_ep, dec_ep, 0.0
                break
            sep = min(
                _angular_sep_arcmin(q_ra, q_dec, float(row["ra_deg_j2000"]), float(row["dec_deg_j2000"])),
                _angular_sep_arcmin(q_ra, q_dec, ra_ep, dec_ep),
            )
            if sep <= match_radius_arcmin and sep < best_sep:
                matched_row, match_ra_ep, match_dec_ep, best_sep = row, ra_ep, dec_ep, sep

        frames = []
        gaia_sources = []
        warnings_list = []
        spectrum_102 = None
        patch_ts = None
        source_mode = "local_no_coverage"

        if matched_row is not None:
            meta = _TARGET_ASSETS[matched_row["target_id"]]
            slug = meta["slug"]
            frames = _cached(frames_cache, slug, lambda s=slug: _load_local_target_frames(data_real_dir, s))
            raw_gaia = _cached(gaia_rows_cache, slug, lambda s=slug: _read_local_gaia_rows(data_real_dir, s, csv_dir=csv_dir))
            gaia_sources = _load_local_gaia_sources(
                data_real_dir, slug, match_ra_ep, match_dec_ep, fov_arcmin / 2.0 + 0.5, epoch_yr, raw_rows=raw_gaia
            )
            spectrum_102 = build_target_spectrum_102(matched_row["name"], meta, spectra_ref)
            source_mode = "local_archive"

        patch_tid = None
        if matched_row is not None:
            patch_tid = matched_row["target_id"]
        else:
            sep_patch = min(
                _angular_sep_arcmin(q_ra, q_dec, float(default_manifest["center_ra_deg"]), float(default_manifest["center_dec_deg"])),
                _angular_sep_arcmin(
                    q_ra, q_dec, float(default_manifest["target_j2000_ra_deg"]), float(default_manifest["target_j2000_dec_deg"])
                ),
            )
            if sep_patch <= match_radius_arcmin:
                patch_tid = default_target_id

        if patch_tid is not None:
            try:
                manifest, flux_cube, mask_cube = _get_patch_arrays(patch_tid)
                _, det_img = _get_detector_stack(detector, target_id=patch_tid)
                patch_ts = _serialize_detector_timeseries(
                    manifest, flux_cube, mask_cube, detector, spectra_ref, stack_grid=det_img
                )
                source_mode = "hour0_calibrated_pack"
            except FileNotFoundError:
                pass

        if live:
            live_frames, live_gaia, live_warnings = _query_live_cached(match_ra_ep, match_dec_ep, fov_arcmin / 120.0)
            if live_frames:
                seen_keys = {_frame_dedup_key(f) for f in live_frames}
                frames = list(live_frames) + [
                    f for f in frames if _frame_dedup_key(f) not in seen_keys
                ]
                source_mode = (
                    "live_irsa_siav2" if source_mode == "local_no_coverage" else f"{source_mode}+live_irsa_siav2"
                )
            elif source_mode == "local_no_coverage":
                source_mode = "live_irsa_empty"
            if live_gaia and not gaia_sources:
                gaia_sources = list(live_gaia)
            warnings_list.extend(live_warnings)

        total_matching_frames = len(frames)
        if frame_limit is not None:
            frames = frames[frame_offset : frame_offset + frame_limit]

        return {
            "query": {
                "coord_input": coord,
                "ra_deg": round(q_ra, 6),
                "dec_deg": round(q_dec, 6),
                "ra_deg_at_epoch": round(match_ra_ep, 6),
                "dec_deg_at_epoch": round(match_dec_ep, 6),
                "fov_arcmin": fov_arcmin,
                "epoch_yr": epoch_yr,
                "detector": detector,
            },
            "source_mode": source_mode,
            "matched_target": (
                {
                    "target_id": matched_row["target_id"],
                    "name": matched_row["name"],
                    "object_type": matched_row["object_type"],
                    "ra_deg_at_epoch": round(match_ra_ep, 6),
                    "dec_deg_at_epoch": round(match_dec_ep, 6),
                }
                if matched_row
                else None
            ),
            "patch_timeseries": patch_ts,
            "total_matching_frames": total_matching_frames,
            "frames": frames,
            "gaia_sources": gaia_sources,
            "spectrum_102": spectrum_102,
            "warnings": warnings_list,
        }

    @app.get("/api/sources")
    def get_sources():
        return _cached(json_cache, "sources", lambda: load_sources(contracts_dir))

    @app.get("/api/cases")
    def get_cases():
        return _cached(json_cache, "cases", lambda: load_cases(contracts_dir))

    @app.get("/api/cases/{case_id}/export")
    def export_case(case_id: str):
        if not CASE_ID_RE.match(case_id):
            raise HTTPException(status_code=404, detail="Case not found")
        cases_doc = _cached(json_cache, "cases", lambda: load_cases(contracts_dir))
        case = next((c for c in cases_doc["cases"] if c["case_id"] == case_id), None)
        if case is None:
            raise HTTPException(status_code=404, detail="Case not found")
        return build_export_packet(case, data_origin=cases_doc.get("data_origin", "synthetic_mock_fixture"))

    @app.post("/api/analyze/spectrum")
    def analyze_spectrum(payload: SpectrumAnalyzeRequest):
        try:
            readings = compute_molecule_readings(
                spectra_ref["wavelength_um"],
                spectra_ref["bandwidth_um"],
                payload.flux_uJy,
                flux_err=payload.flux_err_uJy,
                blend_share=payload.blend_share,
                is_variable=payload.is_variable,
            )
            ml_pipe, model_origin = _cached(
                json_cache,
                "ml_pipeline",
                lambda: _build_default_discovery_pipeline(spectra_ref, dataset_npz_path=resolved_dataset_npz),
            )
            src_wl = np.asarray(spectra_ref["wavelength_um"], dtype=np.float64)
            fl_arr = np.asarray(payload.flux_uJy, dtype=np.float64)
            err_arr = np.asarray(payload.flux_err_uJy, dtype=np.float64) if payload.flux_err_uJy is not None else None
            fl_model, err_model = _align_spectrum_to_model_grid(src_wl, fl_arr, err_arr, ml_pipe.wavelengths)
            has_masked = bool(not np.all(np.isfinite(fl_arr)) or not np.all(np.isfinite(fl_model)))
            classification = ml_pipe.predict_one(
                fl_model,
                blend_share=payload.blend_share,
                parallax_snr=payload.parallax_snr,
                has_masked_pixels=has_masked,
                flux_err=err_model,
            )
            classification["model_origin"] = model_origin
        except (ValueError, np.linalg.LinAlgError) as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        return {"molecule_readings": readings, "classification": classification}

    return app
