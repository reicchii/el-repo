#!/usr/bin/env python3
"""
Phantom Worlds - Real SPHEREx (IRSA/AWS S3) & Gaia DR3 Data Downloader
Run locally with:
    pip install pyvo requests pandas
    python download_real_spherex_gaia.py
    python download_real_spherex_gaia.py --targets-csv targets.csv --resume --delay 0.2
    python download_real_spherex_gaia.py --ra 133.795129 --dec -7.245147 --name WISE_0855
"""
import argparse
import csv
import json
import math
import os
import re
import sys
import time
import pandas as pd
import requests
import pyvo

_REPO_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
if _REPO_ROOT not in sys.path:
    sys.path.insert(0, _REPO_ROOT)

from phantom_worlds.contracts import (
    ALLOWED_DOWNLOADER_HOSTS,
    ALLOWED_REMOTE_HOSTS,
    HardenedHTTPSession,
    is_safe_s3_key,
    propagate_position,
    resolve_s3_cloud_access_url,
    safe_s3_cloud_access_url,
    validate_remote_url,
)

if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)
if hasattr(sys.stderr, "reconfigure"):
    sys.stderr.reconfigure(line_buffering=True)

DEFAULT_OUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data_real")
IRSA_TAP_URL = "https://irsa.ipac.caltech.edu/TAP"
IRSA_SIA_URL = "https://irsa.ipac.caltech.edu/SIA"

SPHEREX_COLLECTIONS = (
    "spherex_dr1",
    "spherex_qr3",
    "spherex_dr1_deep",
    "spherex_qr3_deep",
    "spherex_dr1_cube",
)

SPHEREX_CANONICAL_COLUMNS = (
    "obs_collection",
    "obs_id",
    "s_ra",
    "s_dec",
    "energy_bandpassname",
    "em_min",
    "em_max",
    "em_res_power",
    "t_min",
    "t_max",
    "t_exptime",
    "s_pixel_scale",
    "s_xel1",
    "s_xel2",
    "s_region",
    "access_url",
    "access_format",
    "access_estsize",
    "obs_publisher_did",
    "cloud_access",
)

import concurrent.futures
import threading

_IRSA_IBE_SPHEREX_PREFIX = "https://irsa.ipac.caltech.edu/ibe/data/spherex/"

# Ordered mirrors for Gaia DR3: ESA often hits HTTP 429 or hangs in async UWS queue
# when anonymous slots saturate, so IRSA and ARI act as automatic fallbacks.
GAIA_MIRRORS = [
    ("ESA Gaia TAP", "https://gea.esac.esa.int/tap-server/tap", "gaiadr3.gaia_source", 20),
    ("IRSA Gaia DR3", IRSA_TAP_URL, "gaia_dr3_source", 90),
    ("ARI Heidelberg", "https://gaia.ari.uni-heidelberg.de/tap", "gaiadr3.gaia_source", 60),
]

_GAIA_MIRROR_COOLDOWN_UNTIL = {}
_COOLDOWN_LOCK = threading.Lock()
_LOG_LOCK = threading.Lock()
_RATE_LIMIT_COOLDOWN_SEC = 300.0
_TRANSIENT_COOLDOWN_SEC = 60.0


def reset_gaia_mirror_state():
    """Clear per-mirror cooldown timers so fresh runs or tests probe mirrors cleanly."""
    with _COOLDOWN_LOCK:
        _GAIA_MIRROR_COOLDOWN_UNTIL.clear()


def _cooldown_seconds_for_error(exc):
    msg = str(exc).lower()
    if any(tok in msg for tok in ("429", "too many requests", "rate limit")):
        return _RATE_LIMIT_COOLDOWN_SEC
    if any(tok in msg for tok in ("timed out", "timeout", "503", "temporarily unavailable")):
        return _TRANSIENT_COOLDOWN_SEC
    return 0.0

TARGETS = {
    "Barnards_Star": {"ra_deg": 269.452075, "dec_deg": 4.693364, "pmra_mas_yr": -801.55, "pmdec_mas_yr": 10362.39},
    "WISE_0855": {"ra_deg": 133.795129, "dec_deg": -7.245147, "pmra_mas_yr": -8118.0, "pmdec_mas_yr": 680.0},
    "Epsilon_Indi_B": {"ra_deg": 331.043833, "dec_deg": -56.782694, "pmra_mas_yr": 3976.0, "pmdec_mas_yr": -2499.0},
    "RW_Aurigae": {"ra_deg": 76.956500, "dec_deg": 30.401417, "pmra_mas_yr": 2.9, "pmdec_mas_yr": -24.1},
    "R_Draconis": {"ra_deg": 248.167625, "dec_deg": 66.754972, "pmra_mas_yr": -14.2, "pmdec_mas_yr": -33.1},
}


class _TimeoutSession(HardenedHTTPSession):
    """Hardened HTTPS session enforcing allowlisted hosts, timeouts, zero redirects, and no env proxies/.netrc."""

    def __init__(self, timeout=60, allowed_hosts=ALLOWED_DOWNLOADER_HOSTS):
        super().__init__(timeout=timeout, allowed_hosts=allowed_hosts)


def _log(msg):
    ts = time.strftime("%H:%M:%S")
    with _LOG_LOCK:
        print(f"[{ts}] {msg}", flush=True)


_TARGET_RE = re.compile(r"^[A-Za-z0-9_.-]{1,64}$")
_TABLE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
_COLLECTION_RE = re.compile(r"^[a-z0-9_]{3,64}$")
_ALLOWED_FITS_HOSTS = ALLOWED_REMOTE_HOSTS
_MAX_RANGE_BYTES = 64 * 1024 * 1024


def _validate_target_name(target_name):
    if not isinstance(target_name, str) or ".." in target_name or target_name.startswith("."):
        raise ValueError(f"Invalid target_name: {target_name!r}")
    if not _TARGET_RE.fullmatch(target_name):
        raise ValueError(f"Unsafe target_name characters: {target_name!r}")
    return target_name


def _normalize_realpath(path):
    resolved = os.path.realpath(path)
    if os.name == "nt" and resolved.startswith("\\\\?\\") and not resolved.startswith("\\\\?\\UNC\\"):
        return resolved[4:]
    return resolved


def _safe_output_path(out_dir, filename):
    real_dir = _normalize_realpath(out_dir)
    real_file = _normalize_realpath(os.path.join(real_dir, filename))
    if os.path.commonpath([real_dir, real_file]) != real_dir:
        raise ValueError(f"Resolved output path escapes out_dir: {filename!r}")
    return real_file


def _validate_coords(ra_deg, dec_deg, radius_deg):
    if any(isinstance(v, bool) for v in (ra_deg, dec_deg, radius_deg)):
        raise ValueError("Coordinates and radius must be numeric, not bool")
    ra = float(ra_deg)
    dec = float(dec_deg)
    rad = float(radius_deg)
    if not (math.isfinite(ra) and 0.0 <= ra <= 360.0):
        raise ValueError(f"ra_deg out of range [0, 360]: {ra_deg!r}")
    if not (math.isfinite(dec) and -90.0 <= dec <= 90.0):
        raise ValueError(f"dec_deg out of range [-90, 90]: {dec_deg!r}")
    if not (math.isfinite(rad) and 0.0 < rad <= 10.0):
        raise ValueError(f"radius_deg out of range (0, 10]: {radius_deg!r}")
    return ra, dec, rad


def _validate_and_propagate_coords(
    ra_deg,
    dec_deg,
    radius_deg,
    pmra_mas_yr=0.0,
    pmdec_mas_yr=0.0,
    epoch_yr=2026.0,
    ref_epoch_yr=2000.0,
):
    ra, dec, rad = _validate_coords(ra_deg, dec_deg, radius_deg)
    if any(isinstance(v, bool) for v in (pmra_mas_yr, pmdec_mas_yr, epoch_yr, ref_epoch_yr)):
        raise ValueError("Proper motion and epoch parameters must be numeric, not bool")
    pmra = float(pmra_mas_yr)
    pmdec = float(pmdec_mas_yr)
    epoch = float(epoch_yr)
    ref_epoch = float(ref_epoch_yr)
    if not (math.isfinite(pmra) and abs(pmra) <= 20000.0):
        raise ValueError(f"pmra_mas_yr out of range [-20000, 20000]: {pmra_mas_yr!r}")
    if not (math.isfinite(pmdec) and abs(pmdec) <= 20000.0):
        raise ValueError(f"pmdec_mas_yr out of range [-20000, 20000]: {pmdec_mas_yr!r}")
    if not (math.isfinite(epoch) and 1900.0 <= epoch <= 2100.0):
        raise ValueError(f"epoch_yr out of range [1900, 2100]: {epoch_yr!r}")
    if not (math.isfinite(ref_epoch) and 1900.0 <= ref_epoch <= 2100.0):
        raise ValueError(f"ref_epoch_yr out of range [1900, 2100]: {ref_epoch_yr!r}")
    ra_prop, dec_prop = propagate_position(ra, dec, pmra, pmdec, epoch - ref_epoch)
    return ra_prop, dec_prop, rad


def _validate_limit(limit):
    if limit is None:
        return None
    if isinstance(limit, bool) or not isinstance(limit, int) or limit < 1 or limit > 50000:
        raise ValueError(f"limit must be int in [1, 50000] or None, got {limit!r}")
    return limit


def _validate_collections(collections):
    cols = tuple(collections) if collections is not None else ()
    if not cols:
        raise ValueError("collections must be a non-empty sequence")
    for coll in cols:
        if not isinstance(coll, str) or not _COLLECTION_RE.fullmatch(coll):
            raise ValueError(f"Invalid SPHEREx collection name: {coll!r}")
    return cols


_is_safe_s3_key = is_safe_s3_key
_validate_fits_url = validate_remote_url


def _validate_byte_range(byte_start, byte_end):
    if isinstance(byte_start, bool) or isinstance(byte_end, bool):
        raise ValueError("Byte range bounds must be integers, not bool")
    if not isinstance(byte_start, int) or not isinstance(byte_end, int):
        raise ValueError("Byte range bounds must be integers")
    if byte_start < 0 or byte_end < byte_start:
        raise ValueError(f"Invalid byte range [{byte_start}, {byte_end}]")
    if (byte_end - byte_start + 1) > _MAX_RANGE_BYTES:
        raise ValueError(f"Requested byte range exceeds {_MAX_RANGE_BYTES} byte limit")


def _build_gaia_adql(table_name, ra_deg, dec_deg, radius_deg, limit=None):
    if not isinstance(table_name, str) or not _TABLE_RE.fullmatch(table_name):
        raise ValueError(f"Invalid Gaia table_name: {table_name!r}")
    ra, dec, rad = _validate_coords(ra_deg, dec_deg, radius_deg)
    valid_limit = _validate_limit(limit)
    top_clause = f"TOP {valid_limit} " if valid_limit is not None else ""
    return f"""
    SELECT {top_clause}
        source_id, ra, dec, pmra, pmdec, parallax,
        phot_g_mean_mag, phot_bp_mean_mag, phot_rp_mean_mag, ruwe
    FROM {table_name}
    WHERE 1=CONTAINS(
        POINT('ICRS', ra, dec),
        CIRCLE('ICRS', {ra}, {dec}, {rad})
    )
    ORDER BY phot_g_mean_mag ASC
    """


def _is_completed_csv(path):
    if not os.path.isfile(path) or os.path.getsize(path) <= 0:
        return False
    with open(path, encoding="utf-8", errors="ignore") as f:
        first_line = f.readline().strip()
    return bool(first_line and "," in first_line)


def _resolve_csv_col(fieldnames, aliases):
    by_lower = {col.strip().lower(): col for col in (fieldnames or []) if isinstance(col, str)}
    for alias in aliases:
        if alias in by_lower:
            return by_lower[alias]
    return None


def _parse_csv_float(row, col, default, field_label, row_num, allow_na=False):
    if col is None:
        return default
    raw = (row.get(col) or "").strip()
    if not raw or (allow_na and raw.lower() in ("na", "nan", "null", "none")):
        return default
    try:
        val = float(raw)
    except ValueError as exc:
        raise ValueError(f"Row {row_num}: invalid {field_label}: {raw!r}") from exc
    if not math.isfinite(val):
        raise ValueError(f"Row {row_num}: non-finite {field_label}: {raw!r}")
    return val


def load_targets_csv(csv_path):
    """Load and validate an external target catalog CSV (name, ra, dec, optional pm/ref_epoch)."""
    if not os.path.isfile(csv_path):
        raise ValueError(f"Targets CSV not found: {csv_path!r}")

    targets = {}
    with open(csv_path, encoding="utf-8-sig", newline="") as f:
        reader = csv.DictReader(f)
        if not reader.fieldnames:
            raise ValueError(f"Targets CSV has no header row: {csv_path!r}")

        name_col = _resolve_csv_col(reader.fieldnames, ("target_name", "name", "main_id", "source_name", "source_id", "id"))
        ra_col = _resolve_csv_col(reader.fieldnames, ("ra_deg", "ra_deg_j2000", "ra_j2000", "ra"))
        dec_col = _resolve_csv_col(reader.fieldnames, ("dec_deg", "dec_deg_j2000", "dec_j2000", "dec"))
        pmra_col = _resolve_csv_col(reader.fieldnames, ("pmra_mas_yr", "pm_ra_mas_yr", "pmra", "pm_ra"))
        pmdec_col = _resolve_csv_col(reader.fieldnames, ("pmdec_mas_yr", "pm_dec_mas_yr", "pmdec", "pm_dec"))
        ref_ep_col = _resolve_csv_col(reader.fieldnames, ("ref_epoch_yr", "ref_epoch"))
        if not (name_col and ra_col and dec_col):
            raise ValueError("Targets CSV must include name/target_name, ra/ra_deg, and dec/dec_deg columns")

        for row_num, row in enumerate(reader, start=2):
            safe_name = _validate_target_name((row.get(name_col) or "").strip())
            if safe_name in targets:
                raise ValueError(f"Row {row_num}: duplicate target_name {safe_name!r}")
            ra = _parse_csv_float(row, ra_col, None, "ra", row_num)
            dec = _parse_csv_float(row, dec_col, None, "dec", row_num)
            if ra is None or dec is None:
                raise ValueError(f"Row {row_num}: missing ra/dec for {safe_name!r}")
            pmra = _parse_csv_float(row, pmra_col, 0.0, "pmra", row_num, allow_na=True)
            pmdec = _parse_csv_float(row, pmdec_col, 0.0, "pmdec", row_num, allow_na=True)
            ref_epoch = _parse_csv_float(row, ref_ep_col, 2000.0, "ref_epoch", row_num, allow_na=True)
            _validate_and_propagate_coords(ra, dec, 0.05, pmra_mas_yr=pmra, pmdec_mas_yr=pmdec, epoch_yr=2026.0, ref_epoch_yr=ref_epoch)
            targets[safe_name] = {
                "ra_deg": ra,
                "dec_deg": dec,
                "pmra_mas_yr": pmra,
                "pmdec_mas_yr": pmdec,
                "ref_epoch_yr": ref_epoch,
            }

    if not targets:
        raise ValueError(f"Targets CSV contains zero rows: {csv_path!r}")
    return targets


def _atomic_write_csv(df, out_path):
    parent = os.path.dirname(os.path.abspath(out_path))
    os.makedirs(parent, exist_ok=True)
    tmp_path = f"{out_path}.tmp.{os.getpid()}.{threading.get_ident()}"
    try:
        df.to_csv(tmp_path, index=False)
        os.replace(tmp_path, out_path)
    finally:
        if os.path.exists(tmp_path):
            try:
                os.remove(tmp_path)
            except OSError:
                pass


def fetch_gaia_dr3_patch(
    target_name,
    ra_deg,
    dec_deg,
    radius_arcmin=5.0,
    limit=None,
    out_dir=DEFAULT_OUT_DIR,
    pmra_mas_yr=0.0,
    pmdec_mas_yr=0.0,
    epoch_yr=2026.0,
    ref_epoch_yr=2000.0,
    resume=False,
):
    """Fetch Gaia DR3 stars within radius_arcmin of target position propagated to epoch_yr."""
    safe_name = _validate_target_name(target_name)
    valid_limit = _validate_limit(limit)
    if isinstance(radius_arcmin, bool):
        raise ValueError("radius_arcmin must be numeric, not bool")
    ra, dec, radius_deg = _validate_and_propagate_coords(
        ra_deg,
        dec_deg,
        float(radius_arcmin) / 60.0,
        pmra_mas_yr=pmra_mas_yr,
        pmdec_mas_yr=pmdec_mas_yr,
        epoch_yr=epoch_yr,
        ref_epoch_yr=ref_epoch_yr,
    )
    out_path = _safe_output_path(out_dir, f"{safe_name}_gaia_dr3.csv")
    if resume and _is_completed_csv(out_path):
        _log(f"[Gaia DR3] Skipping {safe_name}: existing {out_path}")
        return pd.read_csv(out_path)
    os.makedirs(out_dir, exist_ok=True)
    _log(f"[Gaia DR3] Querying {safe_name} at epoch {float(epoch_yr):.1f} ({ra:.6f}, {dec:.6f})...")

    now = time.monotonic()
    with _COOLDOWN_LOCK:
        active_mirrors = [m for m in GAIA_MIRRORS if _GAIA_MIRROR_COOLDOWN_UNTIL.get(m[1], 0.0) <= now]
        ordered_mirrors = active_mirrors or sorted(
            GAIA_MIRRORS, key=lambda m: _GAIA_MIRROR_COOLDOWN_UNTIL.get(m[1], 0.0)
        )

    errors = []
    esa_fallback = None
    for label, tap_url, table_name, timeout in ordered_mirrors:
        t0 = time.time()
        try:
            service = pyvo.dal.TAPService(tap_url, session=_TimeoutSession(timeout))
            query = _build_gaia_adql(table_name, ra, dec, radius_deg, limit=valid_limit)
            search_kwargs = {"maxrec": max(50000, valid_limit or 50000)} if "esa.int" not in tap_url else {}
            # Sync TAP avoids ESA's anonymous async UWS queue limit (HTTP 429 / stalls).
            tbl = service.search(query, **search_kwargs).to_table().to_pandas()
            if (valid_limit is None or valid_limit > 2000) and "esa.int" in tap_url and len(tbl) >= 2000:
                esa_fallback = (label, tbl, t0)
                raise RuntimeError("ESA sync row limit (2000) reached; trying larger mirror")
            _atomic_write_csv(tbl, out_path)
            _log(f"  -> [{label}] Saved {len(tbl)} Gaia DR3 stars to {out_path} ({time.time() - t0:.1f}s)")
            return tbl
        except Exception as exc:
            err_msg = str(exc).splitlines()[0]
            cooldown = _cooldown_seconds_for_error(exc)
            if cooldown > 0:
                with _COOLDOWN_LOCK:
                    _GAIA_MIRROR_COOLDOWN_UNTIL[tap_url] = time.monotonic() + cooldown
                _log(f"  -> [{label}] Unavailable ({time.time() - t0:.1f}s, cooldown {cooldown:.0f}s): {err_msg}")
            else:
                _log(f"  -> [{label}] Unavailable ({time.time() - t0:.1f}s): {err_msg}")
            errors.append(f"{label}: {err_msg}")

    if esa_fallback is not None:
        fb_label, fb_tbl, fb_t0 = esa_fallback
        _atomic_write_csv(fb_tbl, out_path)
        _log(f"  -> [{fb_label}] Preserved {len(fb_tbl)} Gaia DR3 stars after fallback mirrors failed ({time.time() - fb_t0:.1f}s)")
        return fb_tbl

    raise RuntimeError(f"All Gaia DR3 mirrors failed for {safe_name}: {'; '.join(errors)}")


def _synthesize_cloud_access(access_url):
    if (
        not isinstance(access_url, str)
        or not access_url.startswith(_IRSA_IBE_SPHEREX_PREFIX)
        or "?" in access_url
        or "#" in access_url
        or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in access_url)
    ):
        return ""
    key = access_url[len(_IRSA_IBE_SPHEREX_PREFIX):]
    if not _is_safe_s3_key(key):
        return ""
    return json.dumps({"aws": {"bucket_name": "nasa-irsa-spherex", "key": key, "region": "us-east-1"}})


def normalize_spherex_frames_df(df, collections=SPHEREX_COLLECTIONS):
    """Project SIAv2 and TAP frame tables onto one canonical column schema and collection filter."""
    valid_cols = set(_validate_collections(collections))
    if df is None or len(df) == 0:
        return pd.DataFrame(columns=SPHEREX_CANONICAL_COLUMNS)

    out = df.copy()
    if "obs_collection" not in out.columns and "collection" in out.columns:
        out["obs_collection"] = out["collection"]
    if "obs_collection" in out.columns:
        out = out[out["obs_collection"].astype(str).isin(valid_cols)].copy()

    if "cloud_access" not in out.columns:
        out["cloud_access"] = ""
    urls = out["access_url"] if "access_url" in out.columns else pd.Series([""] * len(out), index=out.index)
    out["cloud_access"] = [
        val if safe_s3_cloud_access_url(val) else _synthesize_cloud_access(url)
        for val, url in zip(out["cloud_access"], urls)
    ]
    return out.reindex(columns=SPHEREX_CANONICAL_COLUMNS).reset_index(drop=True)


def query_irsa_spherex_sia(
    target_name,
    ra_deg,
    dec_deg,
    radius_deg=0.05,
    collections=SPHEREX_COLLECTIONS,
    out_dir=DEFAULT_OUT_DIR,
    pmra_mas_yr=0.0,
    pmdec_mas_yr=0.0,
    epoch_yr=2026.0,
    ref_epoch_yr=2000.0,
    resume=False,
):
    """Query NASA/IPAC IRSA SIAv2 across SPHEREx collections at epoch-propagated coordinates."""
    safe_name = _validate_target_name(target_name)
    valid_cols = _validate_collections(collections)
    ra, dec, rad = _validate_and_propagate_coords(
        ra_deg,
        dec_deg,
        radius_deg,
        pmra_mas_yr=pmra_mas_yr,
        pmdec_mas_yr=pmdec_mas_yr,
        epoch_yr=epoch_yr,
        ref_epoch_yr=ref_epoch_yr,
    )
    out_path = _safe_output_path(out_dir, f"{safe_name}_spherex_frames.csv")
    if resume and _is_completed_csv(out_path):
        _log(f"[IRSA SPHEREx] Skipping {safe_name}: existing {out_path}")
        return pd.read_csv(out_path)
    os.makedirs(out_dir, exist_ok=True)
    _log(f"[IRSA SPHEREx] Querying image frames covering {safe_name} at epoch {float(epoch_yr):.1f} ({ra:.6f}, {dec:.6f})...")

    t0 = time.time()
    frames = []
    counts = {}
    failed_cols = []
    try:
        sia = pyvo.dal.SIA2Service(IRSA_SIA_URL, session=_TimeoutSession(45))
        for coll in valid_cols:
            try:
                res = sia.search(pos=(ra, dec, rad), collection=coll, maxrec=10000)
                part = res.to_table().to_pandas()
                counts[coll] = len(part)
                if len(part) > 0:
                    if "obs_collection" not in part.columns:
                        part["obs_collection"] = coll
                    frames.append(part)
            except Exception as exc:
                failed_cols.append(coll)
                _log(f"  -> [IRSA SIAv2] Collection {coll} failed ({time.time() - t0:.1f}s): {exc}")
    except Exception as exc:
        failed_cols = list(valid_cols)
        _log(f"  -> [IRSA SIAv2] Failed ({time.time() - t0:.1f}s): {exc}; falling back to IRSA TAP s_region...")

    if frames and not failed_cols:
        df = normalize_spherex_frames_df(pd.concat(frames, ignore_index=True), collections=valid_cols)
        _atomic_write_csv(df, out_path)
        _log(f"  -> [IRSA SIAv2] Saved {len(df)} SPHEREx frame records {counts} to {out_path} ({time.time() - t0:.1f}s)")
        return df

    # Query TAP only for failed collections when partial SIAv2 survived, keeping SIAv2 rows even if TAP fails.
    tap_cols = tuple(failed_cols) if frames else valid_cols
    if not frames and not failed_cols:
        _log(f"  -> [IRSA SIAv2] Returned 0 rows ({time.time() - t0:.1f}s); falling back to IRSA TAP s_region...")
    elif frames:
        _log(f"  -> [IRSA SIAv2] Partial survival {counts}; querying IRSA TAP for failed {tap_cols}...")

    t1 = time.time()
    try:
        service = pyvo.dal.TAPService(IRSA_TAP_URL, session=_TimeoutSession(90))
        collections_sql = ", ".join(f"'{c}'" for c in tap_cols)
        select_cols = ", ".join(c for c in SPHEREX_CANONICAL_COLUMNS if c != "cloud_access")
        adql = f"""
        SELECT {select_cols}
        FROM spherex.obscore
        WHERE obs_collection IN ({collections_sql})
          AND (1=CONTAINS(POINT('ICRS', {ra}, {dec}), s_region) OR 1=INTERSECTS(CIRCLE('ICRS', {ra}, {dec}, {rad}), s_region))
        """
        raw_df = service.search(adql, maxrec=10000).to_table().to_pandas()
        if len(raw_df) > 0 or not frames:
            frames.append(raw_df)
    except Exception as exc:
        if not frames:
            raise
        _log(f"  -> [IRSA TAP] Recovery failed ({time.time() - t1:.1f}s): {exc}; keeping surviving SIAv2 frames {counts}")

    df = normalize_spherex_frames_df(pd.concat(frames, ignore_index=True), collections=valid_cols)
    _atomic_write_csv(df, out_path)
    _log(f"  -> [IRSA TAP] Saved {len(df)} normalized SPHEREx frame records to {out_path} ({time.time() - t1:.1f}s)")
    return df


resolve_s3_url_from_cloud_access = resolve_s3_cloud_access_url


def http_range_read_fits_tile(fits_url, byte_start, byte_end):
    """Fetch a validated HTTPS byte range (HTTP 206, or bounded HTTP 200 from byte 0) from an IRSA or SPHEREx S3 FITS object."""
    safe_url = _validate_fits_url(fits_url)
    _validate_byte_range(byte_start, byte_end)
    max_bytes = min(_MAX_RANGE_BYTES, byte_end - byte_start + 1)
    headers = {"Range": f"bytes={byte_start}-{byte_end}"}
    with _TimeoutSession(timeout=10, allowed_hosts=ALLOWED_REMOTE_HOSTS) as sess:
        with sess.get(safe_url, headers=headers, timeout=10, allow_redirects=False, stream=True) as resp:
            if resp.status_code == 200 and byte_start > 0:
                raise RuntimeError("Server ignored Range header with HTTP 200 for nonzero byte_start")
            if resp.status_code not in (200, 206):
                raise RuntimeError(f"Range request failed with HTTP {resp.status_code}")
            resp_headers = getattr(resp, "headers", None) or {}
            content_len = (
                resp_headers.get("Content-Length")
                if "Content-Length" in resp_headers
                else resp_headers.get("content-length")
            )
            if content_len is not None:
                try:
                    if int(content_len) > max_bytes:
                        raise RuntimeError(f"Range response exceeded {max_bytes} byte limit")
                except ValueError:
                    pass
            chunks = []
            total = 0
            for chunk in resp.iter_content(chunk_size=65536):
                if not chunk:
                    continue
                total += len(chunk)
                if total > max_bytes:
                    raise RuntimeError(f"Range response exceeded {max_bytes} byte limit")
                chunks.append(chunk)
            return b"".join(chunks)


def _validate_workers(workers):
    if isinstance(workers, bool) or not isinstance(workers, int) or workers < 1 or workers > 8:
        raise ValueError(f"workers must be int in [1, 8], got {workers!r}")
    return workers


def _download_one_target(
    idx,
    total,
    name,
    spec,
    *,
    epoch_yr,
    out_dir,
    radius_arcmin,
    radius_deg,
    limit,
    collections,
    resume,
):
    _log(f"=== Target {idx}/{total}: {name} ===")
    ran_network = False
    target_skipped = 0
    try:
        safe_name = _validate_target_name(name)
        gaia_path = _safe_output_path(out_dir, f"{safe_name}_gaia_dr3.csv")
        sia_path = _safe_output_path(out_dir, f"{safe_name}_spherex_frames.csv")
        pmra = spec.get("pmra_mas_yr", 0.0)
        pmdec = spec.get("pmdec_mas_yr", 0.0)
        ref_epoch = spec.get("ref_epoch_yr", 2000.0)

        if resume and _is_completed_csv(gaia_path):
            _log(f"  [Skip] Gaia DR3 already exists: {gaia_path}")
            target_skipped += 1
        else:
            ran_network = True
            fetch_gaia_dr3_patch(
                safe_name,
                spec["ra_deg"],
                spec["dec_deg"],
                radius_arcmin=radius_arcmin,
                limit=limit,
                pmra_mas_yr=pmra,
                pmdec_mas_yr=pmdec,
                epoch_yr=epoch_yr,
                ref_epoch_yr=ref_epoch,
                out_dir=out_dir,
            )

        if resume and _is_completed_csv(sia_path):
            _log(f"  [Skip] SPHEREx frames already exists: {sia_path}")
            target_skipped += 1
        else:
            ran_network = True
            query_irsa_spherex_sia(
                safe_name,
                spec["ra_deg"],
                spec["dec_deg"],
                radius_deg=radius_deg,
                collections=collections,
                pmra_mas_yr=pmra,
                pmdec_mas_yr=pmdec,
                epoch_yr=epoch_yr,
                ref_epoch_yr=ref_epoch,
                out_dir=out_dir,
            )
    except Exception as exc:
        _log(f"  [ERROR] {name} failed: {exc}")
        return name, str(exc), target_skipped, ran_network
    return name, None, target_skipped, ran_network


def download_all_targets(
    epoch_yr=2026.0,
    out_dir=DEFAULT_OUT_DIR,
    targets=None,
    radius_arcmin=5.0,
    radius_deg=0.05,
    limit=None,
    collections=SPHEREX_COLLECTIONS,
    resume=False,
    delay_sec=0.0,
    workers=1,
    max_targets=None,
):
    """Download Gaia DR3 and IRSA SPHEREx datasets for target mapping using epoch-propagated coordinates."""
    if isinstance(delay_sec, bool) or not math.isfinite(float(delay_sec)) or float(delay_sec) < 0.0:
        raise ValueError(f"delay_sec must be a finite number >= 0, got {delay_sec!r}")
    delay = float(delay_sec)
    n_workers = _validate_workers(workers)
    cap = _validate_limit(max_targets)
    valid_cols = _validate_collections(collections)
    target_map = TARGETS if targets is None else targets
    if not target_map:
        raise ValueError("No targets supplied to download")

    selected_items = list(target_map.items())[:cap] if cap is not None else list(target_map.items())
    os.makedirs(out_dir, exist_ok=True)
    failures = []
    skipped = 0
    total = len(selected_items)
    _log(f"Starting download for {total} target(s) (epoch {float(epoch_yr):.1f}, workers={n_workers}) into {out_dir}")

    common_kwargs = {
        "epoch_yr": epoch_yr,
        "out_dir": out_dir,
        "radius_arcmin": radius_arcmin,
        "radius_deg": radius_deg,
        "limit": limit,
        "collections": valid_cols,
        "resume": resume,
    }
    if n_workers == 1:
        for idx, (name, spec) in enumerate(selected_items, start=1):
            t_name, err, t_skip, ran_network = _download_one_target(idx, total, name, spec, **common_kwargs)
            skipped += t_skip
            if err is not None:
                failures.append((t_name, err))
            if idx < total and ran_network and delay > 0.0:
                time.sleep(delay)
    else:
        def _worker_call(idx_item):
            idx, (name, spec) = idx_item
            res = _download_one_target(idx, total, name, spec, **common_kwargs)
            if res[3] and delay > 0.0:
                time.sleep(delay)
            return res

        with concurrent.futures.ThreadPoolExecutor(max_workers=n_workers) as executor:
            for t_name, err, t_skip, _ in executor.map(_worker_call, enumerate(selected_items, start=1)):
                skipped += t_skip
                if err is not None:
                    failures.append((t_name, err))

    if skipped:
        _log(f"Skipped {skipped} already-completed file(s) via resume mode.")
    return failures


def _auto_target_name(ra_deg, dec_deg):
    ra, dec, _ = _validate_coords(ra_deg, dec_deg, 0.05)
    return f"target_{ra:.4f}_{dec:.4f}".replace(".", "p").replace("+", "")


def build_arg_parser():
    """Build CLI argument parser supporting --targets-csv, --ra/--dec/--name, and --resume."""
    parser = argparse.ArgumentParser(
        description="Download real Gaia DR3 astrometry and IRSA SPHEREx frame metadata into CSV files."
    )
    parser.add_argument("--targets-csv", help="CSV file of targets (name, ra, dec, optional pmra, pmdec, ref_epoch).")
    parser.add_argument("--ra", type=float, help="Single target Right Ascension (ICRS degrees, [0, 360]).")
    parser.add_argument("--dec", type=float, help="Single target Declination (ICRS degrees, [-90, 90]).")
    parser.add_argument("--name", help="Safe target identifier/filename prefix when using --ra/--dec.")
    parser.add_argument("--pmra", type=float, default=0.0, help="Proper motion RA*cos(Dec) in mas/yr (default: 0).")
    parser.add_argument("--pmdec", type=float, default=0.0, help="Proper motion Dec in mas/yr (default: 0).")
    parser.add_argument("--ref-epoch", type=float, default=2000.0, help="Reference epoch in Julian years (default: 2000.0).")
    parser.add_argument("--epoch", type=float, default=2026.0, help="Target observation epoch in Julian years (default: 2026.0).")
    parser.add_argument("--radius-arcmin", type=float, default=5.0, help="Gaia DR3 search radius in arcmin (default: 5.0).")
    parser.add_argument("--radius-deg", type=float, default=0.05, help="IRSA SPHEREx search radius in degrees (default: 0.05).")
    parser.add_argument("--limit", type=int, default=None, help="Optional Gaia DR3 max rows per target.")
    parser.add_argument("--collections", nargs="+", default=list(SPHEREX_COLLECTIONS), help="SPHEREx collections to query.")
    parser.add_argument("--out-dir", default=DEFAULT_OUT_DIR, help="Output directory for CSV files.")
    parser.add_argument("--resume", "--skip-existing", dest="resume", action="store_true", help="Skip non-empty CSVs already downloaded.")
    parser.add_argument("--delay", type=float, default=0.0, help="Seconds to pause between network targets in batch runs (default: 0.0).")
    parser.add_argument("--workers", type=int, default=1, help="Concurrent worker threads in [1, 8] (default: 1).")
    parser.add_argument("--max-targets", type=int, default=None, help="Optional max target count slice from input list.")
    return parser


def main(argv=None):
    """CLI entrypoint for downloading built-in test targets, --targets-csv batches, or single --ra/--dec targets."""
    parser = build_arg_parser()
    args = parser.parse_args(argv)

    has_ra_dec = args.ra is not None or args.dec is not None
    if args.targets_csv and (has_ra_dec or args.name is not None):
        parser.error("--targets-csv cannot be combined with --ra/--dec/--name")
    if (args.ra is None) != (args.dec is None):
        parser.error("Provide both --ra and --dec together")
    if args.name is not None and not has_ra_dec:
        parser.error("--name requires --ra and --dec")

    try:
        collections = _validate_collections(args.collections)
        if args.targets_csv:
            targets = load_targets_csv(args.targets_csv)
        elif has_ra_dec:
            _validate_and_propagate_coords(
                args.ra,
                args.dec,
                args.radius_deg,
                pmra_mas_yr=args.pmra,
                pmdec_mas_yr=args.pmdec,
                epoch_yr=args.epoch,
                ref_epoch_yr=args.ref_epoch,
            )
            safe_name = _validate_target_name(args.name) if args.name is not None else _auto_target_name(args.ra, args.dec)
            targets = {
                safe_name: {
                    "ra_deg": float(args.ra),
                    "dec_deg": float(args.dec),
                    "pmra_mas_yr": float(args.pmra),
                    "pmdec_mas_yr": float(args.pmdec),
                    "ref_epoch_yr": float(args.ref_epoch),
                }
            }
        else:
            targets = None

        failures = download_all_targets(
            epoch_yr=args.epoch,
            out_dir=args.out_dir,
            targets=targets,
            radius_arcmin=args.radius_arcmin,
            radius_deg=args.radius_deg,
            limit=args.limit,
            collections=collections,
            resume=args.resume,
            delay_sec=args.delay,
            workers=args.workers,
            max_targets=args.max_targets,
        )
    except ValueError as exc:
        parser.error(str(exc))

    if failures:
        _log(f"Completed with {len(failures)} failure(s): {failures}")
        return 1
    _log("All targets downloaded successfully.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
