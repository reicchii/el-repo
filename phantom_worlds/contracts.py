import base64
import csv
from datetime import datetime, timedelta, timezone
import json
import math
import os
import re
from urllib.parse import urlparse

import numpy as np
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

PACKAGE_ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
DEFAULT_CONTRACTS_DIR = os.path.join(PACKAGE_ROOT, "phantom_worlds_dataset_kit", "hour0_contracts")
DEFAULT_CSV_DIR = os.path.join(PACKAGE_ROOT, "phantom_worlds_dataset_kit", "csv_tables")
DEFAULT_DATA_REAL_DIR = os.path.join(PACKAGE_ROOT, "phantom_worlds_dataset_kit", "scripts", "data_real")
DEFAULT_STATIC_DIR = os.path.join(os.path.dirname(__file__), "static")

VALID_DETECTORS = ("D1", "D2", "D3", "D4", "D5", "D6")
DETECTOR_INDEX = {name: idx for idx, name in enumerate(VALID_DETECTORS)}
TARGET_SPECS = {
    "TGT-01": {
        "slug": "Barnards_Star",
        "spec_col": "Barnards_Star_uJy",
        "blend_share": 0.01,
        "is_variable": False,
        "aliases": ("barnard", "barnards star", "barnard's star", "tgt-01"),
    },
    "TGT-02": {
        "slug": "WISE_0855",
        "spec_col": "WISE_0855_uJy",
        "blend_share": 0.08,
        "is_variable": False,
        "aliases": ("wise 0855", "wise0855", "w0855", "w0855-0714", "tgt-02"),
    },
    "TGT-03": {
        "slug": "Epsilon_Indi_B",
        "spec_col": "Eps_Indi_B_uJy",
        "blend_share": 0.22,
        "is_variable": False,
        "aliases": ("epsilon indi", "epsilon indi b", "eps indi b", "tgt-03"),
    },
    "TGT-04": {
        "slug": "RW_Aurigae",
        "spec_col": "RW_Aurigae_uJy",
        "blend_share": 0.15,
        "is_variable": True,
        "aliases": ("rw aurigae", "rw aur", "tgt-04"),
    },
    "TGT-05": {
        "slug": "R_Draconis",
        "spec_col": "R_Draconis_uJy",
        "blend_share": 0.02,
        "is_variable": True,
        "aliases": ("r draconis", "r dra", "tgt-05"),
    },
}
_SAFE_TARGET_ID_RE = re.compile(r"^[A-Za-z0-9_-]{1,32}$")
ALLOWED_REMOTE_HOSTS = frozenset({"irsa.ipac.caltech.edu", "nasa-irsa-spherex.s3.us-east-1.amazonaws.com"})
ALLOWED_DOWNLOADER_HOSTS = ALLOWED_REMOTE_HOSTS | frozenset({"gea.esac.esa.int", "gaia.ari.uni-heidelberg.de"})
ALLOWED_CATALOG_HOSTS = ALLOWED_REMOTE_HOSTS | frozenset(
    {"cds.unistra.fr", "vizier.idia.ac.za", "simbad.cds.unistra.fr", "tapvizier.cds.unistra.fr", "ssp.imcce.fr"}
)
S3_BUCKET_NAME = "nasa-irsa-spherex"
S3_REGION = "us-east-1"
_S3_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_./-]{0,511}$")


def is_safe_s3_key(key):
    """Validate an IRSA SPHEREx S3 object key without traversal or double slashes."""
    return isinstance(key, str) and bool(_S3_KEY_RE.fullmatch(key)) and ".." not in key and "//" not in key


def validate_remote_url(raw_url, allowed_hosts=ALLOWED_REMOTE_HOSTS, allow_query=False):
    """Validate an HTTPS IRSA/S3/Gaia URL against control chars, traversal, ports, credentials, and allowlisted hosts."""
    if not isinstance(raw_url, str) or not raw_url or any(ord(c) <= 0x20 or ord(c) == 0x7F for c in raw_url):
        raise ValueError(f"Unsafe FITS URL: {raw_url!r}")
    parsed = urlparse(raw_url)
    try:
        port = parsed.port
    except ValueError as exc:
        raise ValueError(f"Invalid port in FITS URL: {raw_url!r}") from exc
    host = (parsed.hostname or "").lower()
    lower_path = parsed.path.lower()
    if (
        parsed.scheme != "https"
        or parsed.username
        or parsed.password
        or port not in (None, 443)
        or not host
        or parsed.netloc.lower() != host
        or parsed.params
        or parsed.fragment
        or not parsed.path.startswith("/")
        or ".." in parsed.path
        or "//" in parsed.path
        or "\\" in raw_url
        or any(tok in lower_path for tok in ("%2e", "%2f", "%5c"))
    ):
        raise ValueError(f"Unsafe FITS URL scheme/authority/path: {raw_url!r}")
    if host not in allowed_hosts:
        raise ValueError(f"FITS URL host is not an allowlisted endpoint: {host!r}")
    rel_path = parsed.path[1:]
    if host == f"{S3_BUCKET_NAME}.s3.{S3_REGION}.amazonaws.com":
        if parsed.query or not is_safe_s3_key(rel_path):
            raise ValueError(f"Unsafe S3 object path in FITS URL: {raw_url!r}")
    elif not allow_query:
        if parsed.query or not is_safe_s3_key(rel_path):
            raise ValueError(f"Unsafe remote FITS URL path/query: {raw_url!r}")
        if host == "irsa.ipac.caltech.edu" and not (
            rel_path.startswith(("ibe/data/spherex/", "data/")) or rel_path.endswith((".fits", ".fits.fz", ".fz"))
        ):
            raise ValueError(f"IRSA URL outside allowed FITS namespaces: {raw_url!r}")
    return raw_url


class HardenedHTTPSession(requests.Session):
    """Requests session disabling .netrc/proxy env inheritance, redirects, retries, and non-allowlisted HTTPS hosts."""

    def __init__(self, timeout=60, allowed_hosts=ALLOWED_REMOTE_HOSTS):
        super().__init__()
        self._timeout = timeout
        self._allowed_hosts = frozenset(h.lower() for h in allowed_hosts)
        self.trust_env = False
        self.proxies = {}
        self.max_redirects = 0
        self.adapters.pop("http://", None)
        no_retry = HTTPAdapter(max_retries=Retry(total=0, connect=0, read=0, status=0, redirect=0))
        self.mount("https://", no_retry)

    def resolve_redirects(self, resp, req, *args, **kwargs):
        if self.get_redirect_target(resp):
            raise requests.TooManyRedirects(f"Redirects disabled for {req.url!r}", response=resp, request=req)
        return iter(())

    def request(self, method, url, **kwargs):
        validate_remote_url(str(url), allowed_hosts=self._allowed_hosts, allow_query=True)
        kwargs.setdefault("timeout", self._timeout)
        return super().request(method, url, **kwargs)

    def send(self, request, **kwargs):
        validate_remote_url(str(request.url), allowed_hosts=self._allowed_hosts, allow_query=True)
        kwargs["proxies"] = {}
        return super().send(request, **kwargs)


def safe_remote_url(raw_url):
    """Return validated remote URL or None when unsafe."""
    try:
        return validate_remote_url(raw_url)
    except ValueError:
        return None


def resolve_s3_cloud_access_url(cloud_access):
    """Resolve an IRSA SIAv2 `cloud_access` payload into a validated public HTTPS S3 URL."""
    payload = json.loads(cloud_access) if isinstance(cloud_access, str) else cloud_access
    if not isinstance(payload, dict) or not isinstance(payload.get("aws"), dict):
        raise ValueError("cloud_access payload must contain an 'aws' object")
    aws = payload["aws"]
    bucket = aws.get("bucket_name", "")
    region = aws.get("region", "")
    key = aws.get("key", "")
    if bucket != S3_BUCKET_NAME:
        raise ValueError(f"Unexpected SPHEREx S3 bucket: {bucket!r}")
    if region != S3_REGION:
        raise ValueError(f"Unexpected SPHEREx S3 region: {region!r}")
    if not is_safe_s3_key(key):
        raise ValueError(f"Invalid S3 object key: {key!r}")
    return validate_remote_url(f"https://{bucket}.s3.{region}.amazonaws.com/{key}")


def safe_s3_cloud_access_url(cloud_access):
    """Return validated S3 HTTPS URL from `cloud_access` or None when invalid/unsafe."""
    if not isinstance(cloud_access, str) or not cloud_access.strip().startswith("{"):
        return None
    try:
        return resolve_s3_cloud_access_url(cloud_access)
    except Exception:
        return None


def propagate_position(ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, dt_yr):
    """Propagate ICRS coordinates linearly over dt_yr using pmra = mu_alpha*cos(dec)."""
    params = (ra_deg, dec_deg, pmra_mas_yr, pmdec_mas_yr, dt_yr)
    if any(isinstance(v, bool) for v in params):
        raise ValueError("Position and proper-motion parameters must be numeric, not bool")
    ra_f, dec_f, pmra_f, pmdec_f, dt_f = (float(v) for v in params)
    if not all(math.isfinite(v) for v in (ra_f, dec_f, pmra_f, pmdec_f, dt_f)):
        raise ValueError("Position and proper-motion parameters must be finite")
    if not (-90.0 <= dec_f <= 90.0):
        raise ValueError(f"dec_deg out of range [-90, 90]: {dec_deg!r}")
    cosd = max(math.cos(math.radians(dec_f)), 1e-6)
    ra_out = (ra_f + (pmra_f * dt_f) / (3600000.0 * cosd)) % 360.0
    dec_out = max(-90.0, min(90.0, dec_f + (pmdec_f * dt_f) / 3600000.0))
    return ra_out, dec_out


def _safe_under_dir(base_dir, rel_path):
    real_base = os.path.realpath(base_dir)
    real_target = os.path.realpath(os.path.join(real_base, rel_path))
    if os.path.commonpath([real_base, real_target]) != real_base:
        raise ValueError(f"Resolved path escapes base directory: {rel_path!r}")
    return real_target


def _resolve_patch_dir(contracts_dir, target_id=None, root_manifest=None):
    if target_id is None:
        return contracts_dir
    if not isinstance(target_id, str) or ".." in target_id or not _SAFE_TARGET_ID_RE.fullmatch(target_id):
        raise ValueError(f"Invalid target_id: {target_id!r}")
    if root_manifest is None:
        with open(_safe_under_dir(contracts_dir, "manifest.json"), encoding="utf-8") as f:
            root_manifest = json.load(f)
    if root_manifest.get("target_id") == target_id:
        return contracts_dir
    return _safe_under_dir(contracts_dir, os.path.join("targets", target_id))


def load_manifest(contracts_dir=DEFAULT_CONTRACTS_DIR, target_id=None, root_manifest=None):
    patch_dir = _resolve_patch_dir(contracts_dir, target_id=target_id, root_manifest=root_manifest)
    with open(_safe_under_dir(patch_dir, "manifest.json"), encoding="utf-8") as f:
        return json.load(f)


def load_sources(contracts_dir=DEFAULT_CONTRACTS_DIR):
    with open(os.path.join(contracts_dir, "sources.json"), encoding="utf-8") as f:
        return json.load(f)


def load_cases(contracts_dir=DEFAULT_CONTRACTS_DIR):
    with open(os.path.join(contracts_dir, "cases.json"), encoding="utf-8") as f:
        return json.load(f)


def load_targets(csv_dir=DEFAULT_CSV_DIR):
    with open(os.path.join(csv_dir, "nasa_5_test_targets.csv"), encoding="utf-8", newline="") as f:
        return list(csv.DictReader(f))


def load_spectra_table(csv_dir=DEFAULT_CSV_DIR):
    with open(os.path.join(csv_dir, "spherex_102_band_spectra.csv"), encoding="utf-8", newline="") as f:
        rows = list(csv.DictReader(f))
    return {
        "wavelength_um": np.array([float(r["wavelength_um"]) for r in rows], dtype=np.float64),
        "bandwidth_um": np.array([float(r["bandwidth_um"]) for r in rows], dtype=np.float64),
        "detectors": [r["detector"] for r in rows],
        "band_ids": [r["band_id"] for r in rows],
        "rows": rows,
    }


def nominal_spectrum_flux_err(flux_uJy, noise_floor_uJy=0.15, rel_floor=0.03):
    """Conservative quadrature flux uncertainty (sky floor + relative calibration floor)."""
    fl = np.maximum(np.asarray(flux_uJy, dtype=np.float64), 0.0)
    return [round(float(v), 4) for v in np.hypot(noise_floor_uJy, rel_floor * fl).tolist()]


def build_target_spectrum_102(label, spec_meta, spectra_ref):
    """Build target 102-band spectrum payload with per-target blend_share, flux_err, and variability flags."""
    flux_102 = [float(r[spec_meta["spec_col"]]) for r in spectra_ref["rows"]]
    return {
        "label": label,
        "wavelength_um": [float(v) for v in spectra_ref["wavelength_um"].tolist()],
        "flux_uJy": flux_102,
        "flux_err_uJy": nominal_spectrum_flux_err(flux_102),
        "flux_err_origin": "nominal_spherex_3pct_0p15uJy_floor",
        "is_variable": bool(spec_meta["is_variable"]),
        "target_is_variable": bool(spec_meta["is_variable"]),
        "spectrum_epoch_mode": "single_visit",
        "blend_share": float(spec_meta["blend_share"]),
    }


def decode_calibrated_pack(pack_bytes, mask_bytes, manifest):
    """Decode uncompressed uint16 flux and uint8 quality mask arrays into calibrated float64 NaN-masked cubes."""
    pack_layout = manifest["pack_binary_layout"]
    mask_layout = manifest["quality_mask_layout"]

    if pack_layout.get("compression") != "none" or pack_layout.get("endianness") != "little":
        raise ValueError("Unsupported pack binary layout compression/endianness")
    if mask_layout.get("compression") != "none":
        raise ValueError("Unsupported quality mask compression")

    shape = tuple(int(v) for v in pack_layout["shape"])
    if tuple(int(v) for v in mask_layout["shape"]) != shape:
        raise ValueError("pack_binary_layout and quality_mask_layout shapes do not match")

    expected_elems = int(np.prod(shape))
    if len(pack_bytes) != expected_elems * 2:
        raise ValueError(f"pack.bin byte length {len(pack_bytes)} != expected {expected_elems * 2}")
    if len(mask_bytes) != expected_elems:
        raise ValueError(f"mask.bin byte length {len(mask_bytes)} != expected {expected_elems}")

    raw = np.frombuffer(pack_bytes, dtype="<u2").reshape(shape)
    mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(shape)

    flags = mask_layout["flag_bits"]
    bad_bits = (
        int(flags["IRSA_REJECTED"])
        | int(flags["OVERFLOW_SATURATED"])
        | int(flags.get("EDGE_MASKED", 4))
    )
    invalid_u16 = int(pack_layout["invalid_u16"])

    calibrated = raw.astype(np.float64) * float(pack_layout["flux_scale"]) + float(pack_layout["flux_zero"])
    bad = (raw == invalid_u16) | ((mask & bad_bits) != 0)
    calibrated[bad] = np.nan
    return calibrated


_MAX_PATCH_BINARY_BYTES = 64 * 1024 * 1024


def _expected_binary_bytes(layout, item_bytes, label, max_bytes=_MAX_PATCH_BINARY_BYTES):
    shape = layout.get("shape")
    if not isinstance(shape, (list, tuple)) or not shape:
        raise ValueError(f"{label} manifest shape missing or empty: {shape!r}")
    dims = [int(v) for v in shape]
    if any(isinstance(v, bool) for v in shape) or any(d <= 0 for d in dims):
        raise ValueError(f"{label} expected byte length out of bounds for shape {shape!r}")
    expected = math.prod(dims) * item_bytes
    if expected <= 0 or expected > max_bytes:
        raise ValueError(f"{label} expected byte length out of bounds: {expected}")
    declared = layout.get("byte_length")
    if declared is not None and int(declared) != expected:
        raise ValueError(f"{label} declared byte_length {declared} != expected {expected}")
    return expected


def _read_exact_bounded_bytes(path, expected_bytes, label):
    with open(path, "rb") as f:
        size = os.fstat(f.fileno()).st_size
        if size != expected_bytes:
            raise ValueError(f"{label} size mismatch: expected {expected_bytes} bytes, got {size}")
        data = f.read(expected_bytes + 1)
    if len(data) != expected_bytes:
        raise ValueError(f"{label} size changed during read: expected {expected_bytes} bytes, got {len(data)}")
    return data


def load_patch_arrays(contracts_dir=DEFAULT_CONTRACTS_DIR, target_id=None, manifest=None, root_manifest=None):
    patch_dir = _resolve_patch_dir(contracts_dir, target_id=target_id, root_manifest=root_manifest)
    if manifest is None:
        with open(_safe_under_dir(patch_dir, "manifest.json"), encoding="utf-8") as f:
            manifest = json.load(f)
    pack_layout = manifest["pack_binary_layout"]
    mask_layout = manifest["quality_mask_layout"]
    expected_pack = _expected_binary_bytes(pack_layout, 2, "pack")
    expected_mask = _expected_binary_bytes(mask_layout, 1, "mask")
    pack_path = _safe_under_dir(patch_dir, pack_layout["file"])
    mask_path = _safe_under_dir(patch_dir, mask_layout["file"])
    pack_bytes = _read_exact_bounded_bytes(pack_path, expected_pack, "pack")
    mask_bytes = _read_exact_bounded_bytes(mask_path, expected_mask, "mask")
    flux = decode_calibrated_pack(pack_bytes, mask_bytes, manifest)
    mask_shape = tuple(int(v) for v in mask_layout["shape"])
    mask = np.frombuffer(mask_bytes, dtype=np.uint8).reshape(mask_shape).copy()
    return manifest, flux, mask


def detector_visit_stacks(flux_cube, detector_id=None):
    """Mean calibrated flux across visits (all detectors or a single detector), ignoring NaN-masked samples."""
    if detector_id is not None:
        if detector_id not in DETECTOR_INDEX:
            raise ValueError(f"Unknown detector_id: {detector_id!r}")
        sub_cube = flux_cube[:, DETECTOR_INDEX[detector_id], :, :]
    else:
        sub_cube = flux_cube
    sub_arr = np.asarray(sub_cube, dtype=np.float64)
    valid = ~np.isnan(sub_arr)
    counts = np.count_nonzero(valid, axis=0)
    totals = np.where(valid, sub_arr, 0.0).sum(axis=0)
    out = np.full(counts.shape, np.nan, dtype=np.float64)
    return np.divide(totals, counts, out=out, where=counts > 0)


def build_export_packet(case_dict, data_origin="synthetic_mock_fixture"):
    """Build unified human-initiated JSON submission packet per truth rule 1."""
    return {
        "case_id": case_dict["case_id"],
        "field_name": case_dict["field_name"],
        "product_tier": case_dict.get("product_tier", "Unspecified"),
        "anomaly_class": case_dict["anomaly_class"],
        "data_origin": data_origin,
        "export_format": "phantom_worlds_json_packet_v1",
        "export_target": case_dict["export_target"],
        "requires_human_submission": True,
        "submission_note": (
            "Prepared candidate packet for external verification; confirmation requires "
            "human submission and follow-up telescope verification."
        ),
        "astrometry": {
            "ra_deg": case_dict["ra_deg"],
            "dec_deg": case_dict["dec_deg"],
            "predicted_ra_next_visit": case_dict["predicted_ra_next_visit"],
            "predicted_dec_next_visit": case_dict["predicted_dec_next_visit"],
            "prediction_epoch": case_dict["prediction_epoch"],
        },
        "ml_summary": {
            "m1_p_real": case_dict["m1_p_real"],
            "m2_top_class": case_dict["m2_top_class"],
            "m2_confidence_word": case_dict["m2_confidence_word"],
            "blend_share": case_dict.get("blend_share"),
            "deciding_bands": case_dict["deciding_bands"],
            "m3_novelty_status": case_dict.get("m3_novelty_status"),
            "m3_weirdness_score": case_dict.get("m3_weirdness_score"),
        },
    }


def build_sources_from_csv(csv_dir=DEFAULT_CSV_DIR, catalog_limit=None):
    """Build Hour-0 sources.json payload directly from canonical CSV tables to prevent manual duplication."""
    spectra = load_spectra_table(csv_dir)
    targets = {row["target_id"]: row for row in load_targets(csv_dir)}

    patch_path = os.path.join(csv_dir, "gaia_dr3_wise0855_patch.csv")
    with open(patch_path, encoding="utf-8", newline="") as f:
        all_patch_rows = list(csv.DictReader(f))
        patch_rows = all_patch_rows[:catalog_limit] if catalog_limit is not None else all_patch_rows

    known_catalog = [
        {
            "field": "WISE 0855",
            "gaia_source_id": str(row["gaia_source_id"]),
            "ra_ep2016_deg": float(row["ra_ep2016_deg"]),
            "dec_ep2016_deg": float(row["dec_ep2016_deg"]),
            "pmra_mas_yr": float(row["pmra_mas_yr"]),
            "pmdec_mas_yr": float(row["pmdec_mas_yr"]),
            "parallax_mas": float(row["parallax_mas"]),
            "ra_ep2026_deg": float(row["ra_ep2026_deg"]),
            "dec_ep2026_deg": float(row["dec_ep2026_deg"]),
            "phot_g_mean_mag": float(row["phot_g_mean_mag"]),
            "catwise_w1_mag": float(row["catwise_w1_mag"]),
            "catwise_w2_mag": float(row["catwise_w2_mag"]),
            "psf_subtracted": str(row["psf_subtracted"]),
        }
        for row in patch_rows
    ]

    target_spectra = {}
    for tgt_id, spec in TARGET_SPECS.items():
        spec_key = spec["slug"]
        csv_col = spec["spec_col"]
        tgt = targets[tgt_id]
        ra26, dec26 = propagate_position(
            float(tgt["ra_deg_j2000"]),
            float(tgt["dec_deg_j2000"]),
            float(tgt["pm_ra_mas_yr"]),
            float(tgt["pm_dec_mas_yr"]),
            26.0,
        )
        flux_102 = [float(row[csv_col]) for row in spectra["rows"]]
        d6_fluxes = [float(row[csv_col]) for row in spectra["rows"] if row["detector"] == "D6"]
        target_spectra[spec_key] = {
            "target_id": tgt_id,
            "field": str(tgt["name"]),
            "object_type": str(tgt["object_type"]),
            "ra_ep2026_deg": round(ra26, 6),
            "dec_ep2026_deg": round(dec26, 6),
            "flux_uJy_102": flux_102,
            "d6_mean_flux_uJy": round(float(np.mean(d6_fluxes)), 4),
            "data_origin": "csv_tables/spherex_102_band_spectra.csv",
        }

    return {
        "schema_version": "1.0.0-hour0",
        "field": "multi_target_hour0",
        "primary_cutout_field": "WISE 0855",
        "catalog_patch_field": "WISE 0855",
        "fields_covered": [entry["field"] for entry in target_spectra.values()],
        "wavelength_grid_um": [float(v) for v in spectra["wavelength_um"].tolist()],
        "known_catalog_sources": known_catalog,
        "target_spectra": target_spectra,
    }


def _mjd_to_iso(mjd):
    dt = datetime(1858, 11, 17, tzinfo=timezone.utc) + timedelta(days=float(mjd))
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ")


def _mjd_to_julian_year(mjd):
    return 2000.0 + (float(mjd) - 51544.5) / 365.25


def _sky_sep_arcmin(ra1_deg, dec1_deg, ra2_deg, dec2_deg):
    r1, d1, r2, d2 = map(math.radians, (ra1_deg, dec1_deg, ra2_deg, dec2_deg))
    a = math.sin((d2 - d1) / 2.0) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a))))) * 60.0


def _project_sky_to_px(ra_deg, dec_deg, center_ra_deg, center_dec_deg, fov_arcmin, size_px):
    cosd = max(math.cos(math.radians(center_dec_deg)), 1e-6)
    d_ra = ((ra_deg - center_ra_deg + 540.0) % 360.0) - 180.0
    dx_arcmin = d_ra * cosd * 60.0
    dy_arcmin = (dec_deg - center_dec_deg) * 60.0
    scale = size_px / fov_arcmin
    center_px = (size_px - 1) / 2.0
    return center_px - dx_arcmin * scale, center_px - dy_arcmin * scale


def _add_psf(grid, cx, cy, amplitude, sigma_px=1.15):
    ny, nx = grid.shape
    y0 = max(0, int(math.floor(cy - 6)))
    y1 = min(ny, int(math.ceil(cy + 7)))
    x0 = max(0, int(math.floor(cx - 6)))
    x1 = min(nx, int(math.ceil(cx + 7)))
    if y1 <= y0 or x1 <= x0:
        return
    yy, xx = np.mgrid[y0:y1, x0:x1]
    r2 = (xx - cx) ** 2 + (yy - cy) ** 2
    grid[y0:y1, x0:x1] += amplitude * np.exp(-0.5 * r2 / (sigma_px ** 2))


def _load_real_visit_mjds(data_real_dir, slug):
    frames_path = os.path.join(data_real_dir, f"{slug}_spherex_frames.csv")
    mjds = []
    if os.path.exists(frames_path):
        with open(frames_path, encoding="utf-8", newline="") as f:
            for row in csv.DictReader(f):
                try:
                    t = float(row.get("t_min", ""))
                except ValueError:
                    continue
                if math.isfinite(t):
                    mjds.append(t)
    if len(mjds) >= 3:
        mjds.sort()
        return [round(mjds[0], 4), round(mjds[len(mjds) // 2], 4), round(mjds[-1], 4)]
    return [60983.3433, 61168.8209, 61346.4624]


def build_target_hour0_cutouts(
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    data_real_dir=DEFAULT_DATA_REAL_DIR,
):
    """Build Hour-0 pack.bin, mask.bin, and manifest.json cutouts for all 5 targets."""
    root_manifest = load_manifest(contracts_dir)
    root_tid = root_manifest.get("target_id")
    spectra = load_spectra_table(csv_dir)
    targets = {row["target_id"]: row for row in load_targets(csv_dir)}

    size_px = 64
    pixel_scale = 6.15
    fov_arcmin = round(size_px * pixel_scale / 60.0, 4)
    flux_scale = 0.04
    flux_zero = -10.0
    invalid_u16 = 65535
    # Variability & core-saturation profiles match nasa_5_test_targets.csv test criteria.
    visit_scales = {
        "TGT-01": (1.0, 1.0, 1.0),
        "TGT-02": (1.0, 1.0, 1.0),
        "TGT-03": (1.0, 1.0, 1.0),
        "TGT-04": (0.72, 1.38, 0.94),
        "TGT-05": (1.35, 0.36, 0.88),
    }

    built = []
    for tid, spec in TARGET_SPECS.items():
        if tid not in targets:
            continue
        is_root = tid == root_tid
        row = targets[tid]
        slug = spec["slug"]
        ra_j2000 = float(row["ra_deg_j2000"])
        dec_j2000 = float(row["dec_deg_j2000"])
        pmra = float(row["pm_ra_mas_yr"])
        pmdec = float(row["pm_dec_mas_yr"])
        center_ra, center_dec = propagate_position(ra_j2000, dec_j2000, pmra, pmdec, 26.0)

        spec_col = spec["spec_col"]
        det_flux = [
            float(np.mean([float(r[spec_col]) for r in spectra["rows"] if r["detector"] == det]))
            for det in VALID_DETECTORS
        ]

        gaia_rows = []
        gaia_path = os.path.join(data_real_dir, f"{slug}_gaia_dr3.csv")
        if os.path.exists(gaia_path):
            with open(gaia_path, encoding="utf-8", newline="") as f:
                for g in csv.DictReader(f):
                    try:
                        gra = float(g["ra"])
                        gdec = float(g["dec"])
                        gmag = float(g.get("phot_g_mean_mag") or 18.0)
                        gpmra = float(g.get("pmra") or 0.0)
                        gpmdec = float(g.get("pmdec") or 0.0)
                    except ValueError:
                        continue
                    gaia_rows.append((gra, gdec, gpmra, gpmdec, gmag))
        gaia_rows.sort(key=lambda item: item[4])

        visit_mjds = (
            [float(v["mjd"]) for v in root_manifest["visits"]]
            if (is_root and len(root_manifest.get("visits", [])) == 3)
            else _load_real_visit_mjds(data_real_dir, slug)
        )
        seed = sum(ord(ch) for ch in tid)
        rng = np.random.default_rng(seed)
        flux_cube = rng.normal(0.02, 0.28, size=(3, 6, size_px, size_px))
        mask_cube = np.zeros((3, 6, size_px, size_px), dtype=np.uint8)
        sat_limit = 900.0 if tid in ("TGT-01", "TGT-05") else 1800.0
        tgt_flux_scale = float(root_manifest["pack_binary_layout"]["flux_scale"]) if is_root else flux_scale

        for v_idx, mjd in enumerate(visit_mjds):
            ep_yr = _mjd_to_julian_year(mjd)
            t_ra, t_dec = propagate_position(ra_j2000, dec_j2000, pmra, pmdec, ep_yr - 2000.0)
            tx, ty = _project_sky_to_px(t_ra, t_dec, center_ra, center_dec, fov_arcmin, size_px)
            v_mult = visit_scales.get(tid, (1.0, 1.0, 1.0))[v_idx]

            for d_idx in range(6):
                plane = flux_cube[v_idx, d_idx]
                for g_ra, g_dec, g_pmra, g_pmdec, g_mag in gaia_rows[:30]:
                    s_ra, s_dec = propagate_position(g_ra, g_dec, g_pmra, g_pmdec, ep_yr - 2016.0)
                    if _sky_sep_arcmin(s_ra, s_dec, t_ra, t_dec) < 0.08:
                        continue
                    sx, sy = _project_sky_to_px(s_ra, s_dec, center_ra, center_dec, fov_arcmin, size_px)
                    if -3 <= sx < size_px + 3 and -3 <= sy < size_px + 3:
                        wing_amp = max(2.5, 45.0 * (10.0 ** (-0.32 * (g_mag - 11.0))))
                        _add_psf(plane, sx, sy, wing_amp, sigma_px=1.05)
                        _add_psf(plane, sx + 0.35, sy - 0.25, -0.45 * wing_amp, sigma_px=0.95)

                amp = det_flux[d_idx] * v_mult if is_root else max(1.0, det_flux[d_idx] * v_mult)
                _add_psf(plane, tx, ty, amp, sigma_px=1.25)

                # Flag saturated cores (Barnard's Star D1-D3 / R Draconis bright max) and sample edge mask.
                sat_mask = plane > sat_limit
                if tid == "TGT-01" and d_idx >= 3:
                    sat_mask[:] = False
                mask_cube[v_idx, d_idx, sat_mask] |= 2
                if v_idx == 0 and not is_root:
                    mask_cube[v_idx, d_idx, 0, 0] |= 4

        raw_cube = np.rint((flux_cube - flux_zero) / tgt_flux_scale)
        raw_cube = np.clip(raw_cube, 0, invalid_u16 - 1).astype("<u2")
        target_dir = contracts_dir if is_root else _safe_under_dir(contracts_dir, os.path.join("targets", tid))
        os.makedirs(target_dir, exist_ok=True)
        with open(os.path.join(target_dir, "pack.bin"), "wb") as fp:
            fp.write(raw_cube.tobytes())
        with open(os.path.join(target_dir, "mask.bin"), "wb") as fm:
            fm.write(mask_cube.tobytes())

        manifest = {
            "schema_version": "1.0.0-hour0",
            "target_id": tid,
            "target_name": row["name"],
            "cutout_origin": "synthetic_hour0_mock_cutout",
            "center_ra_deg": round(center_ra, 6),
            "center_dec_deg": round(center_dec, 6),
            "center_epoch": "2026.0",
            "target_j2000_ra_deg": ra_j2000,
            "target_j2000_dec_deg": dec_j2000,
            "fov_arcmin": fov_arcmin,
            "cutout_size_px": [size_px, size_px],
            "pixel_scale_arcsec": pixel_scale,
            "gaia_alignment_rms_arcsec": float(root_manifest.get("gaia_alignment_rms_arcsec", 0.41)),
            "searched_depth_mag_d6": float(root_manifest.get("searched_depth_mag_d6", 19.8)),
            "visits": [
                {
                    "visit_id": f"V{i + 1}",
                    "epoch_iso": root_manifest["visits"][i]["epoch_iso"] if is_root else _mjd_to_iso(mjd),
                    "mjd": float(mjd),
                    "detectors_present": list(VALID_DETECTORS),
                }
                for i, mjd in enumerate(visit_mjds)
            ],
            "pack_binary_layout": {
                "file": "pack.bin",
                "dtype": "uint16",
                "endianness": "little",
                "compression": "none",
                "shape": [3, 6, size_px, size_px],
                "axes_order": ["visit", "detector", "y", "x"],
                "byte_length": 3 * 6 * size_px * size_px * 2,
                "flux_unit": "relative_flux",
                "flux_scale": tgt_flux_scale,
                "flux_zero": flux_zero,
                "invalid_u16": invalid_u16,
            },
            "quality_mask_layout": {
                "file": "mask.bin",
                "dtype": "uint8",
                "compression": "none",
                "shape": [3, 6, size_px, size_px],
                "axes_order": ["visit", "detector", "y", "x"],
                "byte_length": 3 * 6 * size_px * size_px,
                "flag_bits": {"OK": 0, "IRSA_REJECTED": 1, "OVERFLOW_SATURATED": 2, "EDGE_MASKED": 4},
            },
        }
        with open(os.path.join(target_dir, "manifest.json"), "w", encoding="utf-8") as mf:
            json.dump(manifest, mf, indent=2)
        built.append(tid)
    return built


def _compact_fallback_frames(data_real_dir, slug, max_rows=320):
    frames_path = os.path.join(data_real_dir, f"{slug}_spherex_frames.csv")
    if not os.path.exists(frames_path):
        return []
    rows = []
    with open(frames_path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            s3_url = safe_s3_cloud_access_url(raw.get("cloud_access", ""))
            s3_key = s3_url.split(".amazonaws.com/", 1)[1] if s3_url else ""
            try:
                em_min = float(raw["em_min"]) if raw.get("em_min") else None
                em_max = float(raw["em_max"]) if raw.get("em_max") else None
                t_min = float(raw["t_min"]) if raw.get("t_min") else None
                s_ra = float(raw["s_ra"]) if raw.get("s_ra") else None
                s_dec = float(raw["s_dec"]) if raw.get("s_dec") else None
            except ValueError:
                continue
            rows.append(
                [
                    raw.get("obs_collection", ""),
                    raw.get("obs_id", ""),
                    round(s_ra, 5) if s_ra is not None else None,
                    round(s_dec, 5) if s_dec is not None else None,
                    raw.get("energy_bandpassname") or "",
                    em_min,
                    em_max,
                    round(t_min, 4) if t_min is not None else None,
                    s3_key,
                ]
            )
    rows.sort(key=lambda r: (r[7] is None, -(r[7] or 0.0), r[1]))
    if len(rows) <= max_rows:
        return rows
    # Preserve collection diversity and newest epochs while capping bundle size for <3s offline load.
    idx = np.linspace(0, len(rows) - 1, max_rows, dtype=int)
    return [rows[i] for i in idx]


def build_static_fallback_js(
    out_path=os.path.join(DEFAULT_STATIC_DIR, "fallback_data.js"),
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    data_real_dir=DEFAULT_DATA_REAL_DIR,
):
    """Compile zero-downtime ADR-003 static fallback bundle for all 5 mandatory targets."""
    from phantom_worlds.ml_pipeline import compute_molecule_readings
    from phantom_worlds.tier_a_metrics import build_proof_summary, compute_target_tier_a_metrics

    spectra = load_spectra_table(csv_dir)
    targets = {row["target_id"]: row for row in load_targets(csv_dir)}
    det_wl_ranges = {
        det: [
            round(min(float(r["wavelength_um"]) for r in spectra["rows"] if r["detector"] == det), 4),
            round(max(float(r["wavelength_um"]) for r in spectra["rows"] if r["detector"] == det), 4),
        ]
        for det in VALID_DETECTORS
    }

    target_payloads = {}
    for tid, spec in TARGET_SPECS.items():
        tgt = targets[tid]
        patch_dir = _resolve_patch_dir(contracts_dir, target_id=tid)
        with open(os.path.join(patch_dir, "manifest.json"), encoding="utf-8") as mf:
            manifest = json.load(mf)
        with open(_safe_under_dir(patch_dir, manifest["pack_binary_layout"]["file"]), "rb") as fp:
            pack_b64 = base64.b64encode(fp.read()).decode("ascii")
        with open(_safe_under_dir(patch_dir, manifest["quality_mask_layout"]["file"]), "rb") as fm:
            mask_b64 = base64.b64encode(fm.read()).decode("ascii")
        _, flux_cube, mask_cube = load_patch_arrays(contracts_dir, target_id=tid, manifest=manifest)
        tier_a_metrics = compute_target_tier_a_metrics(manifest, flux_cube, mask_cube, target_row=tgt)

        spec_102 = build_target_spectrum_102(tgt["name"], spec, spectra)
        mol_readings = compute_molecule_readings(
            spectra["wavelength_um"],
            spectra["bandwidth_um"],
            spec_102["flux_uJy"],
            flux_err=spec_102["flux_err_uJy"],
            blend_share=spec_102["blend_share"],
            is_variable=spec_102["is_variable"],
        )

        center_ra = float(manifest["center_ra_deg"])
        center_dec = float(manifest["center_dec_deg"])
        gaia_compact = []
        gaia_path = os.path.join(data_real_dir, f"{spec['slug']}_gaia_dr3.csv")
        if os.path.exists(gaia_path):
            with open(gaia_path, encoding="utf-8", newline="") as f:
                candidates = []
                for g in csv.DictReader(f):
                    try:
                        gra = float(g["ra"])
                        gdec = float(g["dec"])
                        pmra = float(g.get("pmra") or 0.0)
                        pmdec = float(g.get("pmdec") or 0.0)
                        gmag = float(g.get("phot_g_mean_mag") or 99.0)
                    except ValueError:
                        continue
                    r26, d26 = propagate_position(gra, gdec, pmra, pmdec, 10.0)
                    if _sky_sep_arcmin(center_ra, center_dec, r26, d26) <= 13.0:
                        candidates.append(
                            [str(g.get("source_id", "")), round(gra, 6), round(gdec, 6), round(pmra, 3), round(pmdec, 3), round(gmag, 3)]
                        )
                candidates.sort(key=lambda item: item[5])
                gaia_compact = candidates[:120]

        target_payloads[tid] = {
            "target_id": tid,
            "slug": spec["slug"],
            "name": tgt["name"],
            "object_type": tgt["object_type"],
            "aliases": list(spec["aliases"]),
            "ra_deg_j2000": float(tgt["ra_deg_j2000"]),
            "dec_deg_j2000": float(tgt["dec_deg_j2000"]),
            "pm_ra_mas_yr": float(tgt["pm_ra_mas_yr"]),
            "pm_dec_mas_yr": float(tgt["pm_dec_mas_yr"]),
            "manifest": manifest,
            "pack_b64": pack_b64,
            "mask_b64": mask_b64,
            "spectrum_102": spec_102,
            "molecule_readings": mol_readings,
            "tier_a_metrics": tier_a_metrics,
            "gaia_sources": gaia_compact,
            "frames": _compact_fallback_frames(data_real_dir, spec["slug"]),
        }

    from phantom_worlds.tier_b_engine import (
        compute_field_remove_known,
        evaluate_b1_b2_2mass_check,
        list_processed_fields,
    )
    from phantom_worlds.tier_b_detectors import (
        SEARCH_CATEGORY_FILTERS,
        analyze_field_candidates,
        evaluate_slice2_benchmarks,
        get_cached_ml_pipeline,
    )

    fields_payload = {}
    search_records = []
    coverage_notes = []
    from phantom_worlds.tier_b_proof import (
        DEFAULT_PROOF_DIR,
        build_field_cases_queue,
        generate_proof_report,
    )

    slice2_bench = evaluate_slice2_benchmarks(contracts_dir=contracts_dir)
    pre_report_path = os.path.join(DEFAULT_PROOF_DIR, "report.json")
    if os.path.abspath(contracts_dir) == os.path.abspath(DEFAULT_CONTRACTS_DIR) and os.path.exists(pre_report_path):
        with open(pre_report_path, "r", encoding="utf-8") as pf:
            proof_report = json.load(pf)
    else:
        proof_report = generate_proof_report(
            contracts_dir=contracts_dir,
            csv_dir=csv_dir,
            include_skybot=False,
            write_searched=False,
        )
    field_cases = build_field_cases_queue(
        contracts_dir=contracts_dir,
        csv_dir=csv_dir,
        pred_check=proof_report.get("b7_retro"),
    )
    ml_bundle = get_cached_ml_pipeline()
    eval_rpt = ml_bundle.get("evaluation_report") or {}
    model_card_meta = {
        "model_version": ml_bundle.get("model_version", "spherex-dr1-e1e2-v2"),
        "release_status": ((eval_rpt.get("release_gates") or {}).get("release_status")) or "UNPUBLISHED",
        "gold_high_snr": ((eval_rpt.get("release_gates") or {}).get("high_snr_gold")) or {},
    }

    for fmeta in list_processed_fields(contracts_dir=contracts_dir):
        fid = fmeta["field_id"]
        b_check = evaluate_b1_b2_2mass_check(fid, contracts_dir=contracts_dir)
        by_det = {}
        for det_id in VALID_DETECTORS:
            rk = compute_field_remove_known(fid, detector_id=det_id, contracts_dir=contracts_dir)
            rk["image_stack"] = [
                [round(float(v), 3) if v is not None else None for v in row] for row in rk["image_stack"]
            ]
            rk["model_stack"] = [
                [round(float(v), 3) if v is not None else None for v in row] for row in rk["model_stack"]
            ]
            rk["residual_stack"] = [
                [round(float(v), 3) if v is not None else None for v in row] for row in rk["residual_stack"]
            ]
            rk["fitted_sources"] = rk["fitted_sources"][:120]
            by_det[det_id] = rk
        ana = analyze_field_candidates(fid, contracts_dir=contracts_dir, include_skybot=False)
        coverage_notes.append(f"{ana['field_name']} (3.3' radius)")
        # Ensure every represented category has offline parity while keeping bundle compact
        picked_ids = set()
        per_field_picks = []
        for rec in ana["records"][:35]:
            picked_ids.add(rec["source_id"])
            per_field_picks.append(rec)
        from phantom_worlds.tier_b_detectors import _matches_category

        for cat_meta in SEARCH_CATEGORY_FILTERS:
            c_id = cat_meta["id"]
            added = 0
            for rec in ana["records"]:
                if _matches_category(rec, c_id):
                    if rec["source_id"] not in picked_ids:
                        picked_ids.add(rec["source_id"])
                        per_field_picks.append(rec)
                    added += 1
                    if added >= 4:
                        break
        for rec in per_field_picks:
            compact_top3 = [
                {
                    "class_name": t["class_name"],
                    "score": t["score"],
                    "chi2_red": t["chi2_red"],
                    "strip_wavelength_um": t["strip_wavelength_um"],
                    "strip_norm_flux": [round(float(x), 3) if x is not None else None for x in t["strip_norm_flux"]],
                }
                for t in (rec.get("top_3_classes") or [])
            ]
            search_records.append({**rec, "top_3_classes": compact_top3})
        fields_payload[fid] = {
            **fmeta,
            "b_check": b_check,
            "m1_calibration": ana["m1_calibration"],
            "b10_steady_edge_stats": ana["b10_steady_edge_stats"],
            "remove_known": by_det,
        }

    search_records.sort(key=lambda r: float(r.get("priority") or 0.0), reverse=True)
    bundle = {
        "schema_version": "1.0.0-hour0",
        "mode": "hour0_static_fallback",
        "detector_wavelength_ranges_um": det_wl_ranges,
        "targets": target_payloads,
        "fields": fields_payload,
        "field_search": {
            "field_scope": "all",
            "coverage_statement": f"Covers {', '.join(coverage_notes) or 'no fields'}; full-sky catalog search not active.",
            "categories_available": SEARCH_CATEGORY_FILTERS,
            "total_matched": len(search_records),
            "results": search_records,
            "model_card": {**model_card_meta, "m1_calibration": (slice2_bench.get("B6") or {})},
            "slice2_benchmarks": slice2_bench,
        },
        "proof_summary": build_proof_summary(contracts_dir=contracts_dir, csv_dir=csv_dir),
        "prediction_check": proof_report.get("b7_retro"),
        "searched_depth": proof_report.get("searched_depth"),
        "field_cases": field_cases,
        "proof_report": proof_report,
    }
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as out_f:
        out_f.write("globalThis.__PHANTOM_STATIC_FALLBACK__ = ")
        json.dump(bundle, out_f, separators=(",", ":"))
        out_f.write(";\n")
    return out_path


def sync_hour0_contracts(contracts_dir=DEFAULT_CONTRACTS_DIR, csv_dir=DEFAULT_CSV_DIR):
    """Regenerate sources.json from csv_tables and ml_cases_output.csv from cases.json."""
    sources_payload = build_sources_from_csv(csv_dir=csv_dir)
    with open(os.path.join(contracts_dir, "sources.json"), "w", encoding="utf-8") as f:
        json.dump(sources_payload, f, indent=2)

    cases_doc = load_cases(contracts_dir)
    cases = cases_doc.get("cases", [])
    if cases:
        fieldnames = list(cases[0].keys())
        csv_path = os.path.join(csv_dir, "ml_cases_output.csv")
        with open(csv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(cases)


def _has_real_cutouts(contracts_dir=DEFAULT_CONTRACTS_DIR):
    for tid in TARGET_SPECS:
        try:
            manifest = load_manifest(contracts_dir, target_id=tid)
        except OSError:
            return False
        if manifest.get("cutout_origin") != "real_spherex_s3_wcs_cutout":
            return False
    return True


if __name__ == "__main__":
    if not _has_real_cutouts():
        build_target_hour0_cutouts()
    sync_hour0_contracts()
    build_static_fallback_js()
