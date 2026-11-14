"""Real SPHEREx 102-band spectral dataset builder (S3 All-Sky Cubes + Zenodo SPIFF + Gaia DR3)."""

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import io
import json
import math
import os
import threading
import time
import zipfile

from astropy.io import fits
from astropy.wcs import WCS
import numpy as np
import pandas as pd
import requests

from phantom_worlds.contracts import (
    ALLOWED_REMOTE_HOSTS,
    HardenedHTTPSession,
    propagate_position,
    validate_remote_url,
)
from phantom_worlds.fits_cutout import (
    HttpRangeFitsReader,
    IRSA_REJECTED_MASK,
    OVERFLOW_MASK,
    _fits_hdu_data_bytes,
    _record_data_manifest,
)

PACKAGE_ROOT = os.path.dirname(os.path.abspath(__file__))
REPO_ROOT = os.path.dirname(PACKAGE_ROOT)
DEFAULT_ML_DIR = os.path.join(REPO_ROOT, "ml")
DEFAULT_DATA_DIR = os.path.join(REPO_ROOT, "data")
DEFAULT_SPIFF_DIR = os.path.join(DEFAULT_DATA_DIR, "spiff")
DEFAULT_CUBE_CACHE_DIR = os.path.join(DEFAULT_DATA_DIR, "cube_cache")
DEFAULT_DATA_MANIFEST = os.path.join(DEFAULT_DATA_DIR, "manifest.csv")
DEFAULT_CURATED_CSV = os.path.join(REPO_ROOT, "phantom_worlds_dataset_kit", "csv_tables", "curated_ml_targets.csv")
DEFAULT_CURATED_META_DIR = os.path.join(REPO_ROOT, "phantom_worlds_dataset_kit", "scripts", "data_ml_curated")

ALLOWED_ML_DATA_HOSTS = ALLOWED_REMOTE_HOSTS | frozenset({"zenodo.org"})
ZENODO_SPIFF_RECORD = "19051216"
ZENODO_SPIFF_FILES = (
    "spiff_templates_hybrid_csv.zip",
    "spiff_tables.zip",
    "spiff_known_bds_binned_csv.zip",
)

# Physical constants for flux density conversion and WISE W2 zero-point (Jarrett et al. 2011).
_C_UM_S = 2.99792458e14
_UJY_PER_W_M2_HZ = 1e32
_FLAMBDA_UM_TO_UJY = _UJY_PER_W_M2_HZ / _C_UM_S  # 3.3356409519815204e17
_WISE_W2_ZERO_POINT_JY = 171.787

S3_CUBE_PREFIX = "https://nasa-irsa-spherex.s3.us-east-1.amazonaws.com/dr1/hips5_cube/hips_20261026"
_HALF_BOX = 3
_AP_R2_MAX = 1.5 ** 2
_ANN_R2_MIN = 2.0 ** 2
_ANN_R2_MAX = 3.3 ** 2

_AXIS3_KEYS = (
    "CTYPE3",
    "CNAME3",
    "CUNIT3",
    "CRPIX3",
    "CDELT3",
    "CRVAL3",
    "PS3_0",
    "PS3_1",
    "PS3_2",
    "PV3_3",
    "PC3_3",
    "PC1_3",
    "PC2_3",
    "PC3_1",
    "PC3_2",
    "NAXIS3",
    "WCSAXES",
)

_SPECTRAL_CHANNELS_DTYPE = np.dtype(
    [
        ("DETECTOR", ">i2"),
        ("SUBCHAN", ">i2"),
        ("WAVELENGTH", ">f4"),
        ("WL_MIN", ">f4"),
        ("WL_MAX", ">f4"),
        ("R", ">f4"),
        ("R_STD", ">f4"),
        ("BANDWIDTH", ">f4"),
    ]
)

BENCHMARK_TARGETS = (
    {"slug": "Barnards_Star", "target_name": "Barnards_Star", "ra_deg": 269.452075, "dec_deg": 4.693365, "pmra": -798.58, "pmdec": 10328.12, "ref_epoch": 2016.0, "ml_class": "Star", "label_grade": "silver"},
    {"slug": "WISE_0855", "target_name": "WISE_0855", "ra_deg": 133.786245, "dec_deg": -7.244372, "pmra": -8118.0, "pmdec": 680.0, "ref_epoch": 2015.5, "ml_class": "Ultracool dwarf", "label_grade": "gold"},
    {"slug": "Eps_Indi_B", "target_name": "Epsilon_Indi_B", "ra_deg": 331.077167, "dec_deg": -56.790500, "pmra": 3960.93, "pmdec": -2539.23, "ref_epoch": 2000.0, "ml_class": "Ultracool dwarf", "label_grade": "gold"},
    {"slug": "RW_Aurigae", "target_name": "RW_Aurigae", "ra_deg": 76.956529, "dec_deg": 30.401440, "pmra": 3.55, "pmdec": -23.09, "ref_epoch": 2016.0, "ml_class": "Young star with ice or dust", "label_grade": "gold"},
    {"slug": "R_Draconis", "target_name": "R_Draconis", "ra_deg": 248.155875, "dec_deg": 66.703167, "pmra": -7.12, "pmdec": -34.21, "ref_epoch": 2016.0, "ml_class": "Evolved giant star", "label_grade": "silver"},
)


def ang2pix_nest(nside, ra_deg, dec_deg):
    """Compute nested HEALPix pixel index for J2000 (ra_deg, dec_deg) without GPL healpy."""
    if nside < 1 or (nside & (nside - 1)) != 0:
        raise ValueError(f"nside must be a positive power of 2, got {nside}")
    phi = math.radians(float(ra_deg) % 360.0)
    z = max(-1.0, min(1.0, math.sin(math.radians(float(dec_deg)))))
    za = abs(z)
    tt = (phi / (math.pi / 2.0)) % 4.0
    if za <= 2.0 / 3.0:
        t1 = nside * (0.5 + tt)
        t2 = nside * z * 0.75
        jp = int(t1 - t2)
        jm = int(t1 + t2)
        ifp = jp // nside
        ifm = jm // nside
        face = (ifp | 4) if ifp == ifm else (ifp if ifp < ifm else ifm + 8)
        ix = jm & (nside - 1)
        iy = nside - (jp & (nside - 1)) - 1
    else:
        ntt = min(3, int(tt))
        tp = tt - ntt
        tmp = nside * math.sqrt(max(0.0, 3.0 * (1.0 - za)))
        jp = min(nside - 1, int(tp * tmp))
        jm = min(nside - 1, int((1.0 - tp) * tmp))
        if z > 0.0:
            face, ix, iy = ntt, nside - jm - 1, nside - jp - 1
        else:
            face, ix, iy = ntt + 8, jp, jm

    bits = nside.bit_length() - 1
    pix_in_face = 0
    for b in range(bits):
        pix_in_face |= ((ix >> b) & 1) << (2 * b)
        pix_in_face |= ((iy >> b) & 1) << (2 * b + 1)
    return (face << (2 * bits)) + pix_in_face


def ang2pix_nest32(ra_deg, dec_deg):
    """Order-5 (Nside=32) nested HEALPix pixel index matching SPHEREx HiPS5 cubes."""
    return ang2pix_nest(32, ra_deg, dec_deg)


def s3_cube_url_for_ipix(ipix5):
    """Build validated HTTPS S3 URL for an Norder5 SPHEREx All-Sky Cube."""
    ipix = int(ipix5)
    if ipix < 0 or ipix >= 12288:
        raise ValueError(f"Norder5 ipix out of range [0, 12287]: {ipix}")
    dir_num = (ipix // 10000) * 10000
    url = f"{S3_CUBE_PREFIX}/Norder5/Dir{dir_num}/Npix{ipix}_cube.fits"
    return validate_remote_url(url)


def _parse_sexagesimal_hms_deg(ra_str):
    parts = [float(p) for p in str(ra_str).strip().split(":")]
    if len(parts) != 3:
        raise ValueError(f"Invalid sexagesimal RA: {ra_str!r}")
    return (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0) * 15.0


def _parse_sexagesimal_dms_deg(dec_str):
    txt = str(dec_str).strip()
    sign = -1.0 if txt.startswith("-") else 1.0
    parts = [abs(float(p)) for p in txt.lstrip("+-").split(":")]
    if len(parts) != 3:
        raise ValueError(f"Invalid sexagesimal Dec: {dec_str!r}")
    return sign * (parts[0] + parts[1] / 60.0 + parts[2] / 3600.0)


def _flambda_to_ujy(wl_um, flux_flambda):
    return np.asarray(flux_flambda, dtype=np.float64) * (np.asarray(wl_um, dtype=np.float64) ** 2) * _FLAMBDA_UM_TO_UJY


def _estimate_w2_mag_from_spectrum(wl_um, flux_ujy):
    wl = np.asarray(wl_um, dtype=np.float64)
    fl = np.asarray(flux_ujy, dtype=np.float64)
    mask = (wl >= 4.4) & (wl <= 4.8) & np.isfinite(fl) & (fl > 0.0)
    if not np.any(mask):
        return float("nan")
    f_jy = float(np.median(fl[mask])) * 1e-6
    return round(-2.5 * math.log10(f_jy / _WISE_W2_ZERO_POINT_JY), 4)


def resample_spectrum_to_grid(src_wl, src_flux, dst_wl, src_err=None):
    """Interpolate a spectrum linearly onto dst_wl, masking gaps larger than 2.5x native spacing."""
    swl = np.asarray(src_wl, dtype=np.float64)
    sfl = np.asarray(src_flux, dtype=np.float64)
    dwl = np.asarray(dst_wl, dtype=np.float64)
    serr = np.asarray(src_err, dtype=np.float64) if src_err is not None else None

    order = np.argsort(swl)
    swl = swl[order]
    sfl = sfl[order]
    if serr is not None:
        serr = serr[order]

    native_step = float(np.median(np.diff(swl))) if len(swl) > 1 else 0.05
    valid = np.isfinite(swl) & np.isfinite(sfl)
    if np.count_nonzero(valid) < 2:
        nan_out = np.full(len(dwl), np.nan, dtype=np.float64)
        return (nan_out, nan_out.copy()) if serr is not None else nan_out

    vwl = swl[valid]
    vfl = sfl[valid]
    out_fl = np.interp(dwl, vwl, vfl, left=np.nan, right=np.nan)
    idx_hi = np.searchsorted(vwl, dwl, side="left")
    in_bounds = (idx_hi > 0) & (idx_hi < len(vwl))
    gap = np.zeros(len(dwl), dtype=np.float64)
    gap[in_bounds] = vwl[idx_hi[in_bounds]] - vwl[idx_hi[in_bounds] - 1]
    out_fl[in_bounds & (gap > 2.5 * max(native_step, 1e-4))] = np.nan
    out_fl[(dwl < vwl[0]) | (dwl > vwl[-1])] = np.nan

    if serr is None:
        return out_fl

    verr = np.where(np.isfinite(serr[valid]) & (serr[valid] > 0), serr[valid], np.nan)
    out_err = np.full(len(dwl), np.nan, dtype=np.float64)
    if np.count_nonzero(np.isfinite(verr)) >= 2:
        ve_pos = np.isfinite(verr)
        out_err = np.interp(dwl, vwl[ve_pos], verr[ve_pos], left=np.nan, right=np.nan)
        out_err[~np.isfinite(out_fl)] = np.nan
    return out_fl, out_err


def _zenodo_spiff_url(filename):
    url = f"https://zenodo.org/api/records/{ZENODO_SPIFF_RECORD}/files/{filename}/content"
    return validate_remote_url(url, allowed_hosts=ALLOWED_ML_DATA_HOSTS)


def ensure_spiff_archives(spiff_dir=DEFAULT_SPIFF_DIR, session=None, manifest_path=DEFAULT_DATA_MANIFEST):
    """Ensure SPIFF Zenodo archives exist locally with verified zip structure and manifest SHA256."""
    os.makedirs(spiff_dir, exist_ok=True)
    own_sess = session is None
    sess = session or HardenedHTTPSession(allowed_hosts=ALLOWED_ML_DATA_HOSTS)
    paths = {}
    manifest_rows = []
    try:
        for fname in ZENODO_SPIFF_FILES:
            url = _zenodo_spiff_url(fname)
            dest = os.path.join(spiff_dir, fname)
            if os.path.commonpath([os.path.abspath(spiff_dir), os.path.abspath(dest)]) != os.path.abspath(spiff_dir):
                raise ValueError(f"Unsafe SPIFF output path: {dest!r}")
            if not (os.path.exists(dest) and zipfile.is_zipfile(dest)):
                resp = sess.get(url, stream=True, timeout=60, allow_redirects=False)
                resp.raise_for_status()
                tmp = dest + ".part"
                with open(tmp, "wb") as f:
                    for chunk in resp.iter_content(chunk_size=131072):
                        if chunk:
                            f.write(chunk)
                os.replace(tmp, dest)
                if not zipfile.is_zipfile(dest):
                    raise ValueError(f"Downloaded SPIFF file is not a valid zip: {dest}")
            h = hashlib.sha256()
            size = 0
            with open(dest, "rb") as f:
                while True:
                    blk = f.read(131072)
                    if not blk:
                        break
                    h.update(blk)
                    size += len(blk)
            paths[fname] = dest
            manifest_rows.append({"name": f"spiff/{fname}", "bytes": size, "sha256": h.hexdigest(), "source_url": url})
    finally:
        if own_sess:
            sess.close()
    if manifest_path:
        _record_data_manifest(manifest_path, manifest_rows)
    return paths


def load_spiff_hybrid_templates(spiff_paths, target_wl_um):
    """Load real L/T/Y/sd hybrid SPHEREx standard templates converted to uJy on target_wl_um."""
    tmpl_zip = spiff_paths["spiff_templates_hybrid_csv.zip"]
    out = []
    with zipfile.ZipFile(tmpl_zip) as zf:
        for name in sorted(zf.namelist()):
            if not name.endswith(".csv"):
                continue
            df = pd.read_csv(io.BytesIO(zf.read(name)))
            df.columns = [c.strip() for c in df.columns]
            wl = df["WAVELENGTH_MICRONS"].to_numpy(dtype=np.float64)
            fl = _flambda_to_ujy(wl, df["FLUX_FLAMBDA"].to_numpy(dtype=np.float64))
            fl = np.where(np.isfinite(fl) & (fl > 0.0), fl, np.nan)
            res = resample_spectrum_to_grid(wl, fl, target_wl_um)
            if int(np.count_nonzero(np.isfinite(res) & (res > 0.0))) >= 20:
                out.append(res)
    return out


def _select_balanced_spiff_bds(records, max_per_letter=80, max_total=240):
    buckets = {"M": [], "L": [], "T": [], "Y": [], "OTHER": []}
    for rec in records:
        spt = str(rec.get("subclass", "")).strip()
        key = spt[0].upper() if spt and spt[0].upper() in ("M", "L", "T", "Y") else "OTHER"
        buckets[key].append(rec)
    selected = []
    # Include rare M/Y/OTHER spectra first, then evenly spaced L/T spectra for broad coverage.
    for key in ("Y", "M", "OTHER", "T", "L"):
        grp = sorted(buckets[key], key=lambda r: str(r["target_name"]))
        if len(grp) <= max_per_letter:
            selected.extend(grp)
        else:
            step = np.linspace(0, len(grp) - 1, max_per_letter, dtype=int)
            selected.extend(grp[i] for i in step)
    if len(selected) > max_total:
        step = np.linspace(0, len(selected) - 1, max_total, dtype=int)
        selected = [selected[i] for i in step]
    return selected


def load_spiff_known_bd_spectra(spiff_paths, target_wl_um, curated_df=None, max_bds=240):
    """Load real SPHEREx 102-band brown dwarf spectra with published J2000 coordinates."""
    tables_zip = spiff_paths["spiff_tables.zip"]
    bds_zip = spiff_paths["spiff_known_bds_binned_csv.zip"]

    coord_map = {}
    with zipfile.ZipFile(tables_zip) as zf:
        auto_df = pd.read_csv(io.BytesIO(zf.read("spiff_tables/spherex_autotype_datasets_fulltable.csv")))
    for row in auto_df.itertuples(index=False):
        desig = str(row.designation).strip().replace(" ", "_")
        if desig and desig not in coord_map and pd.notna(row.ra_j2000) and pd.notna(row.dec_j2000):
            try:
                coord_map[desig] = (_parse_sexagesimal_hms_deg(row.ra_j2000), _parse_sexagesimal_dms_deg(row.dec_j2000))
            except ValueError:
                continue

    if curated_df is not None:
        ucd_rows = curated_df[curated_df["ml_class"] == "Ultracool dwarf"]
        for row in ucd_rows.itertuples(index=False):
            sid = str(row.source_id).strip().replace(" ", "_")
            if sid and sid not in coord_map:
                coord_map[sid] = (float(row.ra_deg), float(row.dec_deg))

    records = []
    with zipfile.ZipFile(bds_zip) as zf:
        for member in sorted(zf.namelist()):
            if not member.endswith(".csv"):
                continue
            base = os.path.basename(member)
            if "_moca_oid_" not in base or "_spt_" not in base:
                continue
            desig = base.split("_moca_oid_")[0]
            if desig not in coord_map:
                continue
            spt = base.split("_spt_")[-1].split("_spherex_spectrum")[0]
            ra_deg, dec_deg = coord_map[desig]
            df = pd.read_csv(io.BytesIO(zf.read(member)))
            wl = df["wavelength_um"].to_numpy(dtype=np.float64)
            fl = _flambda_to_ujy(wl, df["flux_flambda_w_m2_um"].to_numpy(dtype=np.float64))
            err = _flambda_to_ujy(wl, df["flux_error"].to_numpy(dtype=np.float64))
            valid_pos = np.isfinite(fl) & (fl > 0.0)
            if int(np.count_nonzero(valid_pos)) < 20:
                continue
            fl = np.where(np.isfinite(fl) & (fl > -1e4), fl, np.nan)
            err = np.where(np.isfinite(err) & (err > 0.0), err, np.nan)
            res_fl, res_err = resample_spectrum_to_grid(wl, fl, target_wl_um, src_err=err)
            if int(np.count_nonzero(np.isfinite(res_fl) & (res_fl > 0.0))) < 20:
                continue
            w2_est = _estimate_w2_mag_from_spectrum(target_wl_um, res_fl)
            records.append(
                {
                    "target_name": f"SPIFF_{desig}",
                    "ml_class": "Ultracool dwarf",
                    "subclass": spt,
                    "label_grade": "gold",
                    "label_source": f"SPIFF_Zenodo_{ZENODO_SPIFF_RECORD}",
                    "data_source": "spiff_known_bds_binned_csv",
                    "ra_deg": ra_deg,
                    "dec_deg": dec_deg,
                    "ipix5": ang2pix_nest32(ra_deg, dec_deg),
                    "sky_tile": f"h8_{ang2pix_nest(256, ra_deg, dec_deg)}",
                    "flux_ujy": res_fl,
                    "flux_err_ujy": res_err,
                    "w2_mag_est": w2_est,
                    "blend_share": 0.02,
                    "gaia_parallax_mas": float("nan"),
                    "gaia_g_mag": float("nan"),
                }
            )
    return _select_balanced_spiff_bds(records, max_per_letter=80, max_total=max_bds)


def _strip_axis3_wcs(img_header):
    h2 = img_header.copy()
    for key in _AXIS3_KEYS:
        if key in h2:
            del h2[key]
    h2["NAXIS"] = 2
    return WCS(h2)


def _read_range_retry(reader, start, length, max_attempts=3):
    for attempt in range(max_attempts):
        try:
            return reader.read_range(start, length)
        except (requests.exceptions.ConnectionError, requests.exceptions.Timeout):
            if attempt + 1 >= max_attempts:
                raise
            time.sleep(0.5 * (2 ** attempt))


def _read_header_at_offset(reader, offset, chunk_bytes=11520):
    hdr_bytes = bytearray()
    cur = offset
    while True:
        chunk = _read_range_retry(reader, cur, chunk_bytes)
        if not chunk:
            raise EOFError(f"Unexpected EOF reading FITS header at offset {cur}")
        for blk_off in range(0, len(chunk), 2880):
            blk = chunk[blk_off : blk_off + 2880]
            if len(blk) < 2880:
                raise EOFError(f"Truncated FITS header block at offset {cur}")
            hdr_bytes.extend(blk)
            cur += 2880
            if any(blk[i : i + 80].startswith(b"END     ") for i in range(0, 2880, 80)):
                return fits.Header.fromstring(hdr_bytes.decode("ascii", errors="ignore")), cur


def _scan_cube_hdus(reader):
    """Locate PRIMARY/IMAGE/NHITS/FLAGS/SPECTRAL_CHANNELS with minimal HTTP Range roundtrips."""
    prim_hdr, pos = _read_header_at_offset(reader, 0, chunk_bytes=11520)
    pos += ((_fits_hdu_data_bytes(prim_hdr) + 2879) // 2880) * 2880
    img_hdr, img_off = _read_header_at_offset(reader, pos, chunk_bytes=11520)
    if str(img_hdr.get("EXTNAME", "")).strip() == "IMAGE" and not img_hdr.get("ZIMAGE", False):
        img_bytes = _fits_hdu_data_bytes(img_hdr)
        nh_hdr_off = img_off + ((img_bytes + 2879) // 2880) * 2880
        nh_hdr, nh_off = _read_header_at_offset(reader, nh_hdr_off, chunk_bytes=2880)
        nh_bytes = _fits_hdu_data_bytes(nh_hdr)
        fl_hdr_off = nh_off + ((nh_bytes + 2879) // 2880) * 2880
        fl_hdr, fl_off = _read_header_at_offset(reader, fl_hdr_off, chunk_bytes=2880)
        fl_bytes = _fits_hdu_data_bytes(fl_hdr)
        sc_hdr_off = fl_off + ((fl_bytes + 2879) // 2880) * 2880
        sc_hdr, sc_off = _read_header_at_offset(reader, sc_hdr_off, chunk_bytes=2880)
        sc_bytes = _fits_hdu_data_bytes(sc_hdr)
        names = [str(h.get("EXTNAME", "")).strip() for h in (img_hdr, nh_hdr, fl_hdr, sc_hdr)]
        if names == ["IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS"]:
            return {
                "IMAGE": {"header": img_hdr, "data_offset": img_off, "data_bytes": img_bytes},
                "NHITS": {"header": nh_hdr, "data_offset": nh_off, "data_bytes": nh_bytes},
                "FLAGS": {"header": fl_hdr, "data_offset": fl_off, "data_bytes": fl_bytes},
                "SPECTRAL_CHANNELS": {"header": sc_hdr, "data_offset": sc_off, "data_bytes": sc_bytes},
            }
    return reader.scan_hdus(required_extnames=("IMAGE", "NHITS", "FLAGS", "SPECTRAL_CHANNELS"), max_hdus=8)


def _merge_row_intervals(y_centers, naxis2, half_box=_HALF_BOX):
    intervals = sorted((max(0, int(round(y)) - half_box), min(naxis2, int(round(y)) + half_box + 1)) for y in y_centers)
    merged = []
    for lo, hi in intervals:
        if not merged or lo > merged[-1][1]:
            merged.append([lo, hi])
        else:
            merged[-1][1] = max(merged[-1][1], hi)
    return [(lo, hi) for lo, hi in merged]


def _extract_point_spectrum_from_slabs(px, py, slab_img, slab_nh, slab_flg, y_offset, nchan, mjy_sr_to_ujy):
    """Extract background-subtracted 102-band point-source spectrum (uJy) and empirical RMS error."""
    nx = slab_img.shape[2]
    ny_slab = slab_img.shape[1]
    x_c = int(round(px))
    y_c = int(round(py)) - y_offset
    if x_c < 0 or x_c >= nx or y_c < 0 or y_c >= ny_slab:
        nan_arr = np.full(nchan, np.nan, dtype=np.float64)
        return nan_arr, nan_arr.copy()

    x0, x1 = max(0, x_c - _HALF_BOX), min(nx, x_c + _HALF_BOX + 1)
    y0, y1 = max(0, y_c - _HALF_BOX), min(ny_slab, y_c + _HALF_BOX + 1)

    yy, xx = np.mgrid[y0:y1, x0:x1]
    dx = xx - px
    dy = (yy + y_offset) - py
    r2 = dx * dx + dy * dy
    ap_mask = r2 <= _AP_R2_MAX
    ann_mask = (r2 >= _ANN_R2_MIN) & (r2 <= _ANN_R2_MAX)
    cy_local = y_c - y0
    cx_local = x_c - x0

    sub_img = slab_img[:, y0:y1, x0:x1].astype(np.float64)
    sub_nh = slab_nh[:, y0:y1, x0:x1]
    sub_flg = slab_flg[:, y0:y1, x0:x1]

    # Bit 21 (SOURCE) and bit 12 (FULLSAMPLE) are absent from IRSA_REJECTED_MASK so sources stay unmasked.
    valid_px = np.isfinite(sub_img) & (sub_nh > 0) & ((sub_flg & IRSA_REJECTED_MASK) == 0)
    n_ap_full = max(int(np.count_nonzero(ap_mask)), 1)

    flux_out = np.full(nchan, np.nan, dtype=np.float64)
    err_out = np.full(nchan, np.nan, dtype=np.float64)

    for k in range(nchan):
        v_k = valid_px[k]
        # Require at least the closest center pixel and >=3 valid aperture pixels to avoid flux bias.
        if not v_k[cy_local, cx_local]:
            continue
        ap_v = ap_mask & v_k
        n_ap_v = int(np.count_nonzero(ap_v))
        if n_ap_v < min(3, n_ap_full):
            continue

        ann_v = ann_mask & v_k & ((sub_flg[k] & OVERFLOW_MASK) == 0)
        ann_vals = sub_img[k][ann_v]
        if len(ann_vals) >= 4:
            med = float(np.median(ann_vals))
            mad = float(np.median(np.abs(ann_vals - med)))
            sigma_bg = max(1.4826 * mad, 1e-6)
            clipped = ann_vals[np.abs(ann_vals - med) <= 2.5 * sigma_bg]
            if len(clipped) >= 3:
                ann_vals = clipped
            bg = float(np.median(ann_vals))
            sigma_bg = max(1.4826 * float(np.median(np.abs(ann_vals - bg))), 1e-6)
        else:
            bg = 0.0
            sigma_bg = 0.01

        raw_ap_sum = float(np.sum(sub_img[k][ap_v] - bg))
        if n_ap_v < n_ap_full:
            raw_ap_sum *= n_ap_full / n_ap_v
        flux_out[k] = raw_ap_sum * mjy_sr_to_ujy
        err_out[k] = sigma_bg * math.sqrt(n_ap_full * (1.0 + n_ap_full / max(len(ann_vals), 1))) * mjy_sr_to_ujy

    return flux_out, err_out


def extract_cube_tile_spectra(
    ipix5,
    targets,
    session=None,
    url=None,
    cache_dir=DEFAULT_CUBE_CACHE_DIR,
    max_workers=12,
    use_cache=True,
):
    """Extract 102-band SPHEREx spectra for targets inside Norder5 cube ipix5 using HTTP Range slabs."""
    cube_url = validate_remote_url(url) if url is not None else s3_cube_url_for_ipix(ipix5)
    cache_path = os.path.join(cache_dir, f"Npix{int(ipix5)}_spectra.npz") if (cache_dir and use_cache) else None
    if cache_path and os.path.exists(cache_path):
        with np.load(cache_path, allow_pickle=False) as cached:
            cached_names = set(str(x) for x in cached["target_names"].tolist())
            req_names = {str(t["target_name"]) for t in targets}
            if req_names.issubset(cached_names):
                wl = cached["wavelength_um"].astype(np.float64)
                bw = cached["bandwidth_um"].astype(np.float64)
                by_name = {str(n): i for i, n in enumerate(cached["target_names"].tolist())}
                out = {}
                for t in targets:
                    idx = by_name[str(t["target_name"])]
                    out[str(t["target_name"])] = {
                        "flux_ujy": cached["flux_ujy"][idx].astype(np.float64),
                        "flux_err_ujy": cached["flux_err_ujy"][idx].astype(np.float64),
                        "px": float(cached["px"][idx]),
                        "py": float(cached["py"][idx]),
                    }
                return wl, bw, out, cube_url, 0

    own_sess = session is None
    sess = session or HardenedHTTPSession()
    tls = threading.local()
    sess_lock = threading.Lock()
    thread_sessions = []

    def _get_thread_session():
        # Reuse injected session during offline unit tests or open one pooled HTTPS session per worker thread.
        if session is not None or max_workers <= 1:
            return sess
        if not hasattr(tls, "s"):
            tls.s = HardenedHTTPSession()
            with sess_lock:
                thread_sessions.append(tls.s)
        return tls.s

    bytes_read = 0
    try:
        reader = HttpRangeFitsReader(cube_url, session=sess)
        hdus = _scan_cube_hdus(reader)
        img_info = hdus["IMAGE"]
        nh_info = hdus["NHITS"]
        fl_info = hdus["FLAGS"]
        sc_info = hdus["SPECTRAL_CHANNELS"]

        sc_raw = _read_range_retry(reader, sc_info["data_offset"], sc_info["data_bytes"])
        bytes_read += len(sc_raw)
        sc_arr = np.frombuffer(sc_raw, dtype=_SPECTRAL_CHANNELS_DTYPE)
        wl_um = sc_arr["WAVELENGTH"].astype(np.float64)
        bw_um = sc_arr["BANDWIDTH"].astype(np.float64)

        img_hdr = img_info["header"]
        nx = int(img_hdr["NAXIS1"])
        ny = int(img_hdr["NAXIS2"])
        nchan = int(img_hdr["NAXIS3"])
        if nchan != len(wl_um):
            raise ValueError(f"SPECTRAL_CHANNELS rows {len(wl_um)} != NAXIS3 {nchan}")

        w2 = _strip_axis3_wcs(img_hdr)
        mjy_sr_to_ujy = float(w2.proj_plane_pixel_area().to_value("sr")) * 1e12

        prop_coords = [
            propagate_position(
                float(t["ra_deg"]),
                float(t["dec_deg"]),
                float(t.get("pmra", 0.0)),
                float(t.get("pmdec", 0.0)),
                2026.0 - float(t.get("ref_epoch", 2016.0)),
            )
            for t in targets
        ]
        ras = np.array([c[0] for c in prop_coords], dtype=np.float64)
        decs = np.array([c[1] for c in prop_coords], dtype=np.float64)
        px_arr, py_arr = w2.world_to_pixel_values(ras, decs)

        inside_mask = np.isfinite(px_arr) & np.isfinite(py_arr) & (px_arr >= 0.5) & (px_arr <= nx - 1.5) & (py_arr >= 0.5) & (py_arr <= ny - 1.5)
        if not np.any(inside_mask):
            return wl_um, bw_um, {}, cube_url, bytes_read

        merged_slabs = _merge_row_intervals(py_arr[inside_mask], ny, half_box=_HALF_BOX)
        row_bytes = nx * 4
        plane_bytes = nx * ny * 4

        slab_arrays = {}
        for s_idx, (y0, y1) in enumerate(merged_slabs):
            rows_cnt = y1 - y0
            slab_arrays[s_idx] = {
                "IMAGE": np.empty((nchan, rows_cnt, nx), dtype=">f4"),
                "NHITS": np.empty((nchan, rows_cnt, nx), dtype=">i4"),
                "FLAGS": np.empty((nchan, rows_cnt, nx), dtype=">i4"),
            }

        jobs = []
        hdu_Specs = (
            ("IMAGE", img_info["data_offset"], ">f4"),
            ("NHITS", nh_info["data_offset"], ">i4"),
            ("FLAGS", fl_info["data_offset"], ">i4"),
        )
        for s_idx, (y0, y1) in enumerate(merged_slabs):
            slice_len = (y1 - y0) * row_bytes
            row_byte_off = y0 * row_bytes
            for hdu_name, base_off, dt_str in hdu_Specs:
                for k in range(nchan):
                    start = base_off + k * plane_bytes + row_byte_off
                    jobs.append((s_idx, hdu_name, k, y1 - y0, start, slice_len, dt_str))

        def _fetch_job(job):
            s_idx, hdu_name, k, rows_cnt, start, slice_len, dt_str = job
            s = _get_thread_session()
            data = _read_range_retry(HttpRangeFitsReader(cube_url, session=s), start, slice_len)
            arr = np.frombuffer(data, dtype=dt_str).reshape((rows_cnt, nx))
            return s_idx, hdu_name, k, arr, len(data)

        eff_workers = 1 if session is not None else max(1, min(int(max_workers), len(jobs)))
        if eff_workers == 1:
            for job in jobs:
                s_idx, hdu_name, k, arr, nbytes = _fetch_job(job)
                slab_arrays[s_idx][hdu_name][k] = arr
                bytes_read += nbytes
        else:
            with ThreadPoolExecutor(max_workers=eff_workers) as pool:
                for fut in as_completed([pool.submit(_fetch_job, job) for job in jobs]):
                    s_idx, hdu_name, k, arr, nbytes = fut.result()
                    slab_arrays[s_idx][hdu_name][k] = arr
                    bytes_read += nbytes

        extracted = {}
        for idx, t in enumerate(targets):
            if not inside_mask[idx]:
                continue
            px_val = float(px_arr[idx])
            py_val = float(py_arr[idx])
            y_round = int(round(py_val))
            slab_idx = next(si for si, (y0, y1) in enumerate(merged_slabs) if y0 <= y_round < y1)
            y0_slab = merged_slabs[slab_idx][0]
            sdata = slab_arrays[slab_idx]
            fl_ujy, err_ujy = _extract_point_spectrum_from_slabs(
                px_val, py_val, sdata["IMAGE"], sdata["NHITS"], sdata["FLAGS"], y0_slab, nchan, mjy_sr_to_ujy
            )
            extracted[str(t["target_name"])] = {
                "flux_ujy": fl_ujy,
                "flux_err_ujy": err_ujy,
                "px": px_val,
                "py": py_val,
            }

        if cache_path and extracted:
            os.makedirs(os.path.dirname(cache_path), exist_ok=True)
            names = sorted(extracted.keys())
            np.savez_compressed(
                cache_path,
                target_names=np.array(names, dtype="U96"),
                wavelength_um=wl_um,
                bandwidth_um=bw_um,
                flux_ujy=np.vstack([extracted[n]["flux_ujy"] for n in names]),
                flux_err_ujy=np.vstack([extracted[n]["flux_err_ujy"] for n in names]),
                px=np.array([extracted[n]["px"] for n in names], dtype=np.float64),
                py=np.array([extracted[n]["py"] for n in names], dtype=np.float64),
            )
        return wl_um, bw_um, extracted, cube_url, bytes_read
    finally:
        for ts in thread_sessions:
            ts.close()
        if own_sess:
            sess.close()


def _lookup_gaia_metadata(target_name, ra_deg, dec_deg, meta_dir=DEFAULT_CURATED_META_DIR):
    path = os.path.join(meta_dir, f"{target_name}_gaia_dr3.csv")
    if not os.path.exists(path):
        return float("nan"), float("nan")
    try:
        df = pd.read_csv(path)
    except Exception:
        return float("nan"), float("nan")
    if df.empty or "ra" not in df.columns or "dec" not in df.columns:
        return float("nan"), float("nan")
    cosd = max(math.cos(math.radians(dec_deg)), 1e-4)
    sep_arcsec = np.hypot((df["ra"].to_numpy(dtype=np.float64) - ra_deg) * cosd, df["dec"].to_numpy(dtype=np.float64) - dec_deg) * 3600.0
    best = int(np.argmin(sep_arcsec))
    if sep_arcsec[best] > 2.5:
        return float("nan"), float("nan")
    row = df.iloc[best]
    plx = float(row["parallax"]) if ("parallax" in df.columns and pd.notna(row["parallax"])) else float("nan")
    gmag = float(row["phot_g_mean_mag"]) if ("phot_g_mean_mag" in df.columns and pd.notna(row["phot_g_mean_mag"])) else float("nan")
    return plx, gmag


def _global_hpx_wcs():
    hdr = fits.Header()
    hdr["NAXIS"] = 2
    hdr["NAXIS1"] = 512
    hdr["NAXIS2"] = 512
    hdr["CTYPE1"] = "RA---HPX"
    hdr["CTYPE2"] = "DEC--HPX"
    hdr["CRVAL1"] = 0.0
    hdr["CRVAL2"] = 0.0
    hdr["CRPIX1"] = 0.5
    hdr["CRPIX2"] = 0.5
    hdr["PC1_1"] = -45.0 / 16384.0
    hdr["PC1_2"] = -45.0 / 16384.0
    hdr["PC2_1"] = 45.0 / 16384.0
    hdr["PC2_2"] = -45.0 / 16384.0
    hdr["CDELT1"] = 1.0
    hdr["CDELT2"] = 1.0
    hdr["LONPOLE"] = 0.0
    hdr["LATPOLE"] = 90.0
    hdr["PV2_1"] = 4.0
    hdr["PV2_2"] = 3.0
    hdr["RADESYS"] = "ICRS"
    return WCS(hdr)


def select_curated_cube_targets(curated_df, tiles_per_class=None):
    """Select compact, multi-Norder8-tile clusters per class so extraction stays fast on S3 cubes."""
    default_plan = {
        "Evolved giant star": {"max_targets": 24, "candidate_tiles": [7370, 7467, 7198, 7199, 8001, 7348, 7631, 7419]},
        "Galaxy": {"max_targets": 45, "candidate_tiles": [7370, 7467, 3622, 7198, 7199]},
        "Active galaxy or quasar": {"max_targets": 24, "candidate_tiles": [3428, 4802, 4804, 4805, 4801, 7489]},
        "Young star with ice or dust": {"max_targets": 55, "candidate_tiles": [5701, 5359]},
        "Star": {"max_targets": 38, "candidate_tiles": [2559, 2557, 2901]},
    }
    plan = tiles_per_class or default_plan
    work = curated_df.copy()
    work["ipix5"] = [ang2pix_nest32(r.ra_deg, r.dec_deg) for r in work.itertuples(index=False)]
    work["h8"] = [ang2pix_nest(256, r.ra_deg, r.dec_deg) for r in work.itertuples(index=False)]
    gx, gy = _global_hpx_wcs().world_to_pixel_values(work["ra_deg"].to_numpy(dtype=np.float64), work["dec_deg"].to_numpy(dtype=np.float64))
    work["px"] = gx - 512.0 * np.floor(gx / 512.0)
    work["py"] = gy - 512.0 * np.floor(gy / 512.0)
    work = work[(work["px"] >= 3.0) & (work["px"] <= 508.0) & (work["py"] >= 3.0) & (work["py"] <= 508.0)].copy()

    covered_rows = {}
    selected_indices = set()
    for ml_cls, cfg in plan.items():
        sub = work[(work["ml_class"] == ml_cls) & (work["ipix5"].isin(cfg["candidate_tiles"]))].copy()
        cap = int(cfg["max_targets"])
        remaining = {
            int(idx): (
                int(row.ipix5),
                int(row.h8),
                set(range(max(0, int(round(row.py)) - _HALF_BOX), min(512, int(round(row.py)) + _HALF_BOX + 1))),
            )
            for idx, row in sub.iterrows()
        }
        h8_counts = {}
        picked = 0
        while remaining and picked < cap:
            best_idx = min(
                remaining,
                key=lambda i: (
                    len(remaining[i][2] - covered_rows.get(remaining[i][0], set())) + 0.35 * h8_counts.get(remaining[i][1], 0),
                    i,
                ),
            )
            ipix, h8, rows_set = remaining.pop(best_idx)
            covered_rows.setdefault(ipix, set()).update(rows_set)
            h8_counts[h8] = h8_counts.get(h8, 0) + 1
            selected_indices.add(best_idx)
            picked += 1

    selected = work.loc[sorted(selected_indices)].copy()
    # Include any bonus targets sitting inside rows already scheduled for download.
    active_tiles = set(selected["ipix5"].unique().tolist())
    bonus_rows = []
    for idx, row in work[work["ipix5"].isin(active_tiles)].iterrows():
        if idx in selected_indices:
            continue
        rset = set(range(max(0, int(round(row.py)) - _HALF_BOX), min(512, int(round(row.py)) + _HALF_BOX + 1)))
        if rset.issubset(covered_rows.get(int(row.ipix5), set())):
            bonus_rows.append(idx)
    if bonus_rows:
        selected = pd.concat([selected, work.loc[bonus_rows]]).drop_duplicates(subset=["target_name"])
    return selected


def build_real_training_dataset(
    output_npz=os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz"),
    output_manifest=os.path.join(DEFAULT_ML_DIR, "dataset_manifest.json"),
    curated_csv=DEFAULT_CURATED_CSV,
    spiff_dir=DEFAULT_SPIFF_DIR,
    cube_cache_dir=DEFAULT_CUBE_CACHE_DIR,
    data_manifest_path=DEFAULT_DATA_MANIFEST,
    meta_dir=DEFAULT_CURATED_META_DIR,
    max_bds=240,
    max_workers=12,
    use_cache=True,
):
    """Build real SPHEREx 102-band spectral dataset across all 6 classes + 5 benchmark targets."""
    os.makedirs(os.path.dirname(os.path.abspath(output_npz)), exist_ok=True)
    spiff_paths = ensure_spiff_archives(spiff_dir=spiff_dir, manifest_path=data_manifest_path)

    curated_df = pd.read_csv(curated_csv)
    chosen_df = select_curated_cube_targets(curated_df)

    # Group curated targets and the 5 benchmark targets by Norder5 cube tile.
    tile_groups = {}
    for row in chosen_df.itertuples(index=False):
        ipix = int(row.ipix5)
        tile_groups.setdefault(ipix, []).append(
            {
                "target_name": str(row.target_name),
                "ra_deg": float(row.ra_deg),
                "dec_deg": float(row.dec_deg),
                "pmra": float(row.pmra) if pd.notna(row.pmra) else 0.0,
                "pmdec": float(row.pmdec) if pd.notna(row.pmdec) else 0.0,
                "ref_epoch": float(row.ref_epoch) if pd.notna(row.ref_epoch) else 2016.0,
                "ml_class": str(row.ml_class),
                "subclass": str(row.subclass) if pd.notna(row.subclass) else "",
                "label_grade": str(row.label_grade).strip().lower(),
                "label_source": str(row.label_source),
            }
        )

    for b in BENCHMARK_TARGETS:
        bipix = ang2pix_nest32(b["ra_deg"], b["dec_deg"])
        tile_groups.setdefault(bipix, []).append(dict(b))

    canonical_wl = None
    canonical_bw = None
    all_records = []
    bench_extracted = {}
    bench_name_to_slug = {b["target_name"]: b["slug"] for b in BENCHMARK_TARGETS}
    cube_manifest_rows = []
    seen_targets = set()

    sorted_tiles = sorted(tile_groups.keys())
    for idx_t, ipix in enumerate(sorted_tiles, start=1):
        tlist = tile_groups[ipix]
        wl_um, bw_um, extracted, cube_url, bytes_read = extract_cube_tile_spectra(
            ipix, tlist, cache_dir=cube_cache_dir, max_workers=max_workers, use_cache=use_cache
        )
        print(
            f"[cube {idx_t}/{len(sorted_tiles)}] Npix{ipix}: extracted={len(extracted)}/{len(tlist)} ({bytes_read / (1024 * 1024):.1f} MiB)",
            flush=True,
        )
        if canonical_wl is None:
            canonical_wl = wl_um
            canonical_bw = bw_um
        needs_resample = len(wl_um) != len(canonical_wl) or not np.allclose(wl_um, canonical_wl, atol=1e-4)
        cube_manifest_rows.append(
            {"name": f"cubes/Npix{ipix}_cube.fits_slabs", "bytes": bytes_read, "sha256": "range_extracted", "source_url": cube_url}
        )

        for t in tlist:
            tname = str(t["target_name"])
            if tname not in extracted:
                continue
            sp = extracted[tname]
            fl = sp["flux_ujy"]
            ferr = sp["flux_err_ujy"]
            if needs_resample:
                fl, ferr = resample_spectrum_to_grid(wl_um, fl, canonical_wl, src_err=ferr)
            n_valid = int(np.count_nonzero(np.isfinite(fl) & (fl > 0.0)))
            if n_valid < 20:
                continue

            if tname in bench_name_to_slug:
                bench_extracted[bench_name_to_slug[tname]] = {
                    "flux_ujy": fl,
                    "flux_err_ujy": ferr,
                    "ra_deg": float(t["ra_deg"]),
                    "dec_deg": float(t["dec_deg"]),
                    "ml_class": t["ml_class"],
                    "label_grade": t["label_grade"],
                    "ipix5": ipix,
                }
                continue

            if tname in seen_targets:
                continue
            seen_targets.add(tname)

            gaia_plx, gaia_g = _lookup_gaia_metadata(tname, t["ra_deg"], t["dec_deg"], meta_dir=meta_dir)
            all_records.append(
                {
                    "target_name": tname,
                    "ml_class": t["ml_class"],
                    "subclass": t.get("subclass", ""),
                    "label_grade": t["label_grade"],
                    "label_source": t.get("label_source", "curated_ml_targets"),
                    "data_source": f"s3_hips5_cube_Npix{ipix}",
                    "ra_deg": float(t["ra_deg"]),
                    "dec_deg": float(t["dec_deg"]),
                    "ipix5": ipix,
                    "sky_tile": f"h8_{ang2pix_nest(256, t['ra_deg'], t['dec_deg'])}",
                    "flux_ujy": fl,
                    "flux_err_ujy": ferr,
                    "w2_mag_est": _estimate_w2_mag_from_spectrum(canonical_wl, fl),
                    "blend_share": 0.05,
                    "gaia_parallax_mas": gaia_plx,
                    "gaia_g_mag": gaia_g,
                }
            )

    if data_manifest_path and cube_manifest_rows:
        _record_data_manifest(data_manifest_path, cube_manifest_rows)

    if canonical_wl is None:
        raise RuntimeError("No real S3 cube spectra could be extracted")

    spiff_records = load_spiff_known_bd_spectra(spiff_paths, canonical_wl, curated_df=curated_df, max_bds=max_bds)
    for r in spiff_records:
        if r["target_name"] not in seen_targets:
            seen_targets.add(r["target_name"])
            all_records.append(r)

    hybrid_templates = load_spiff_hybrid_templates(spiff_paths, canonical_wl)
    if not hybrid_templates:
        raise RuntimeError("No valid SPIFF hybrid templates loaded")

    names = [r["target_name"] for r in all_records]
    payload = {
        "wavelength_um": canonical_wl,
        "bandwidth_um": canonical_bw,
        "X_flux_uJy": np.vstack([r["flux_ujy"] for r in all_records]),
        "X_err_uJy": np.vstack([r["flux_err_ujy"] for r in all_records]),
        "y_class": np.array([r["ml_class"] for r in all_records], dtype="U64"),
        "subclass": np.array([r["subclass"] for r in all_records], dtype="U32"),
        "label_grades": np.array([r["label_grade"] for r in all_records], dtype="U16"),
        "sky_tiles": np.array([r["sky_tile"] for r in all_records], dtype="U24"),
        "ipix5": np.array([r["ipix5"] for r in all_records], dtype=np.int32),
        "ra_deg": np.array([r["ra_deg"] for r in all_records], dtype=np.float64),
        "dec_deg": np.array([r["dec_deg"] for r in all_records], dtype=np.float64),
        "w2_mag_est": np.array([r["w2_mag_est"] for r in all_records], dtype=np.float64),
        "blend_shares": np.array([r["blend_share"] for r in all_records], dtype=np.float64),
        "gaia_parallax_mas": np.array([r["gaia_parallax_mas"] for r in all_records], dtype=np.float64),
        "gaia_g_mag": np.array([r["gaia_g_mag"] for r in all_records], dtype=np.float64),
        "target_names": np.array(names, dtype="U96"),
        "data_sources": np.array([r["data_source"] for r in all_records], dtype="U64"),
        "spiff_hybrid_templates_uJy": np.vstack(hybrid_templates),
        "benchmark_slugs": np.array(sorted(bench_extracted.keys()), dtype="U32"),
        "benchmark_flux_uJy": np.vstack([bench_extracted[s]["flux_ujy"] for s in sorted(bench_extracted.keys())]),
        "benchmark_err_uJy": np.vstack([bench_extracted[s]["flux_err_ujy"] for s in sorted(bench_extracted.keys())]),
    }
    np.savez_compressed(output_npz, **payload)

    class_counts = {}
    for cls, grade in zip(payload["y_class"].tolist(), payload["label_grades"].tolist()):
        entry = class_counts.setdefault(cls, {"total": 0, "gold": 0, "silver": 0, "unique_h8_tiles": 0})
        entry["total"] += 1
        entry[grade if grade in ("gold", "silver") else "silver"] += 1
    for cls in class_counts:
        mask = payload["y_class"] == cls
        class_counts[cls]["unique_h8_tiles"] = int(len(set(payload["sky_tiles"][mask].tolist())))

    manifest = {
        "dataset_origin": "real_spherex_dr1_hips5_cube_and_spiff_zenodo",
        "spectral_grid_source": "SPECTRAL_CHANNELS BINTABLE (Norder5 All-Sky Cube)",
        "w2_mag_method": "Empirical -2.5*log10(median F_nu[4.4..4.8 um] / 171.787 Jy); NaN if non-positive",
        "sky_tile_definition": "HEALPix NESTED Norder8 (nside=256, ~0.23 deg); S3 extraction grouped by Norder5 (nside=32)",
        "total_spectra": len(all_records),
        "spiff_hybrid_templates_count": len(hybrid_templates),
        "benchmark_targets_extracted": sorted(bench_extracted.keys()),
        "class_summary": class_counts,
        "output_npz": os.path.relpath(output_npz, REPO_ROOT).replace("\\", "/"),
    }
    with open(output_manifest, "w", encoding="utf-8") as f:
        json.dump(manifest, f, indent=2)
    return manifest


def main(argv=None):
    parser = argparse.ArgumentParser(description="Build real SPHEREx 102-band training dataset from S3 cubes and SPIFF.")
    parser.add_argument("--output-npz", default=os.path.join(DEFAULT_ML_DIR, "real_training_dataset.npz"))
    parser.add_argument("--output-manifest", default=os.path.join(DEFAULT_ML_DIR, "dataset_manifest.json"))
    parser.add_argument("--max-bds", type=int, default=240)
    parser.add_argument("--workers", type=int, default=12)
    parser.add_argument("--no-cache", action="store_true")
    args = parser.parse_args(argv)
    summary = build_real_training_dataset(
        output_npz=args.output_npz,
        output_manifest=args.output_manifest,
        max_bds=args.max_bds,
        max_workers=args.workers,
        use_cache=not args.no_cache,
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
