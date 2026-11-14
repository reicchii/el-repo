from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
from datetime import datetime, timezone
import hashlib
import json
import math
import os
import threading

import astropy.io.fits.hdu.compressed._codecs as fits_codecs
from astropy.io import fits
from astropy.wcs import WCS
import numpy as np
import requests

from phantom_worlds.contracts import (
    DEFAULT_CONTRACTS_DIR,
    DEFAULT_CSV_DIR,
    DEFAULT_DATA_REAL_DIR,
    DEFAULT_STATIC_DIR,
    DETECTOR_INDEX,
    HardenedHTTPSession,
    PACKAGE_ROOT,
    TARGET_SPECS,
    VALID_DETECTORS,
    _mjd_to_iso,
    build_static_fallback_js,
    detector_visit_stacks,
    load_targets,
    propagate_position,
    resolve_s3_cloud_access_url,
    validate_remote_url,
)

PIPELINE_VERSION = "0.2.0-real-wcs"
PIXEL_SCALE_ARCSEC = 6.15
CUTOUT_GRID_SIZE = 64
CUTOUT_FOV_ARCMIN = round(CUTOUT_GRID_SIZE * PIXEL_SCALE_ARCSEC / 60.0, 2)
INVALID_U16 = 65535

# SPHEREx DR1 Level-2 FLAGS bit assignments verified from live FITS MSKM/MSKN cards
# Bit 21 (SOURCE) and bit 12 (FULLSAMPLE) are informational and MUST never be masked.
IRSA_REJECTED_BITS = (0, 2, 6, 7, 9, 10, 11, 14, 15, 17, 20, 25, 26, 27, 28, 29)
IRSA_REJECTED_MASK = sum(1 << b for b in IRSA_REJECTED_BITS)
OVERFLOW_BIT = 1
OVERFLOW_MASK = 1 << OVERFLOW_BIT

MASK_OK = 0
MASK_IRSA_REJECTED = 1
MASK_OVERFLOW_SATURATED = 2
MASK_EDGE = 4

# 6.15"/px solid angle in steradians, used to estimate AB point-source depth from MJy/sr RMS
_PIXEL_SR = (PIXEL_SCALE_ARCSEC / 206264.80624709636) ** 2
_MJY_SR_TO_UJY_PX = 1e12 * _PIXEL_SR


class CutoutCoverageError(RuntimeError):
    """Raised when a candidate exposure does not adequately overlap the target cutout."""


def _fetch_byte_range(session, url, start, length):
    if length <= 0:
        return b""
    headers = {"Range": f"bytes={start}-{start + length - 1}"}
    resp = session.get(url, headers=headers, timeout=45)
    if resp.status_code not in (200, 206):
        resp.raise_for_status()
    raw = resp.content
    if resp.status_code == 200 and len(raw) >= start + length:
        return raw[start : start + length]
    if len(raw) > length:
        return raw[:length]
    return raw


def _fits_hdu_data_bytes(hdr):
    naxis = int(hdr.get("NAXIS", 0))
    if naxis <= 0:
        return 0
    elem_bytes = abs(int(hdr["BITPIX"])) // 8
    size = elem_bytes
    for axis in range(1, naxis + 1):
        size *= int(hdr[f"NAXIS{axis}"])
    size += int(hdr.get("PCOUNT", 0))
    size *= int(hdr.get("GCOUNT", 1))
    return int(size)


class HttpRangeFitsReader:
    """Minimal FITS Multi-Extension HTTP Range reader avoiding full-file downloads or IRSA cutout calls."""

    def __init__(self, url, session=None, header_chunk_bytes=11520):
        validate_remote_url(url)
        self.url = url
        self._owns_session = session is None
        self.session = session if session is not None else HardenedHTTPSession()
        self.header_chunk_bytes = max(2880, int(header_chunk_bytes) - (int(header_chunk_bytes) % 2880))

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        self.close()

    def close(self):
        if self._owns_session and hasattr(self.session, "close"):
            self.session.close()

    def read_range(self, start, length):
        return _fetch_byte_range(self.session, self.url, start, length)

    def scan_hdus(self, required_extnames=("IMAGE", "FLAGS", "ZODI"), max_hdus=12):
        required = set(required_extnames)
        found = {}
        pos = 0
        for hdu_idx in range(max_hdus):
            hdr_bytes = bytearray()
            cur = pos
            at_end = False
            while not at_end:
                chunk = self.read_range(cur, self.header_chunk_bytes)
                if not chunk:
                    raise EOFError(f"Unexpected EOF scanning FITS header #{hdu_idx} at byte {cur}")
                for blk_off in range(0, len(chunk), 2880):
                    blk = chunk[blk_off : blk_off + 2880]
                    if len(blk) < 2880:
                        raise EOFError(f"Truncated FITS header block at byte {cur}")
                    hdr_bytes.extend(blk)
                    cur += 2880
                    if any(blk[i : i + 80].startswith(b"END     ") for i in range(0, 2880, 80)):
                        at_end = True
                        break
            hdr = fits.Header.fromstring(hdr_bytes.decode("ascii", errors="ignore"))
            nbytes = _fits_hdu_data_bytes(hdr)
            data_off = cur
            padded = ((nbytes + 2879) // 2880) * 2880 if nbytes > 0 else 0
            pos = cur + padded
            extname = str(hdr.get("EXTNAME", "PRIMARY" if hdu_idx == 0 else f"EXT{hdu_idx}")).strip()
            found[extname] = {"header": hdr, "data_offset": data_off, "data_bytes": nbytes}
            if required.issubset(found.keys()):
                return found
        missing = sorted(required - set(found.keys()))
        raise KeyError(f"FITS archive {self.url} missing extensions {missing}")

    def read_image_slice(self, hdu_info, y0, y1, x0, x1):
        hdr = hdu_info["header"]
        nx = int(hdr["NAXIS1"])
        ny = int(hdr["NAXIS2"])
        if not (0 <= y0 < y1 <= ny and 0 <= x0 < x1 <= nx):
            raise ValueError(f"Slice [{y0}:{y1}, {x0}:{x1}] out of FITS image shape ({ny}, {nx})")
        bitpix = int(hdr["BITPIX"])
        dtype_map = {-32: ">f4", -64: ">f8", 32: ">i4", 16: ">i2", 8: "u1"}
        if bitpix not in dtype_map:
            raise ValueError(f"Unsupported FITS BITPIX={bitpix}")
        dt = np.dtype(dtype_map[bitpix])
        row_bytes = nx * dt.itemsize
        raw_bytes = self.read_range(hdu_info["data_offset"] + y0 * row_bytes, (y1 - y0) * row_bytes)
        arr = np.frombuffer(raw_bytes, dtype=dt).reshape(y1 - y0, nx)[:, x0:x1].astype(np.float64)
        bscale = float(hdr.get("BSCALE", 1.0))
        bzero = float(hdr.get("BZERO", 0.0))
        if bscale != 1.0 or bzero != 0.0:
            arr = arr * bscale + bzero
        return arr

    def read_flags_slice(self, hdu_info, y0, y1, x0, x1):
        hdr = hdu_info["header"]
        if not bool(hdr.get("ZIMAGE", False)):
            arr = self.read_image_slice(hdu_info, y0, y1, x0, x1)
            return np.asarray(arr, dtype=np.int64).astype(np.uint32)

        cmptype = str(hdr.get("ZCMPTYPE", "")).strip()
        if cmptype != "RICE_1":
            raise ValueError(f"Unsupported compressed FLAGS ZCMPTYPE={cmptype!r}")
        znx = int(hdr["ZNAXIS1"])
        zny = int(hdr["ZNAXIS2"])
        nrows = int(hdr["NAXIS2"])
        row_width = int(hdr["NAXIS1"])
        if int(hdr.get("ZTILE1", znx)) != znx or int(hdr.get("ZTILE2", 1)) != 1:
            raise ValueError("Only row-tiled RICE_1 FLAGS (ZTILE2=1) is supported")

        table_bytes = nrows * row_width
        desc_raw = self.read_range(hdu_info["data_offset"], table_bytes)
        if row_width == 8:
            desc = np.frombuffer(desc_raw, dtype=">u4").reshape(nrows, 2)
        elif row_width == 16:
            desc = np.frombuffer(desc_raw, dtype=">u8").reshape(nrows, 2)
        else:
            raise ValueError(f"Unexpected compressed FLAGS BINTABLE row width={row_width}")

        sub_desc = desc[y0:y1]
        nonzero = sub_desc[:, 0] > 0
        flags = np.zeros((y1 - y0, znx), dtype=np.uint32)
        if np.any(nonzero):
            valid_desc = sub_desc[nonzero]
            rel_start = int(np.min(valid_desc[:, 1]))
            rel_end = int(np.max(valid_desc[:, 1] + valid_desc[:, 0]))
            theap = int(hdr.get("THEAP", table_bytes))
            heap_abs_start = hdu_info["data_offset"] + theap
            heap_buf = self.read_range(heap_abs_start + rel_start, rel_end - rel_start)

            zparams = {}
            for idx in (1, 2):
                k_name = str(hdr.get(f"ZNAME{idx}", "")).strip().lower()
                if k_name:
                    zparams[k_name] = int(hdr[f"ZVAL{idx}"])
            blocksize = int(zparams.get("blocksize", 32))
            bytepix = int(zparams.get("bytepix", abs(int(hdr.get("ZBITPIX", 32))) // 8))
            codec = fits_codecs.Rice1(blocksize=blocksize, bytepix=bytepix, tilesize=znx)
            raw_dt = np.int16 if bytepix == 2 else np.int32
            uint_dt = np.uint16 if bytepix == 2 else np.uint32
            for row_i, (cnt, off) in enumerate(sub_desc):
                if int(cnt) == 0:
                    continue
                rel = int(off) - rel_start
                cbytes = np.frombuffer(heap_buf[rel : rel + int(cnt)], dtype=np.uint8)
                decoded = np.asarray(codec.decode(cbytes), dtype=raw_dt).ravel()[:znx]
                flags[row_i] = decoded.view(uint_dt).astype(np.uint32)

        return flags[:, x0:x1]


def build_target_canvas_wcs(center_ra_deg, center_dec_deg, size_px=CUTOUT_GRID_SIZE, pixel_scale_arcsec=PIXEL_SCALE_ARCSEC):
    """Build tangent WCS aligned with HTML5 viewer (North at top, East at left, 6.15\"/px)."""
    w = WCS(naxis=2)
    step_deg = float(pixel_scale_arcsec) / 3600.0
    crpix = (float(size_px) + 1.0) / 2.0
    w.wcs.ctype = ["RA---TAN", "DEC--TAN"]
    w.wcs.crval = [float(center_ra_deg), float(center_dec_deg)]
    w.wcs.crpix = [crpix, crpix]
    w.wcs.cdelt = [-step_deg, -step_deg]
    return w


def reproject_patch_to_canvas(src_net, src_mask, src_wcs, center_ra_deg, center_dec_deg, size_px=CUTOUT_GRID_SIZE, pixel_scale_arcsec=PIXEL_SCALE_ARCSEC, src_x0=0, src_y0=0):
    """Bilinearly reproject net flux + propagate quality masks onto standard North-up TAN canvas."""
    target_wcs = build_target_canvas_wcs(center_ra_deg, center_dec_deg, size_px=size_px, pixel_scale_arcsec=pixel_scale_arcsec)
    gy, gx = np.mgrid[0:size_px, 0:size_px]
    sky = target_wcs.all_pix2world(np.column_stack([gx.ravel(), gy.ravel()]), 0)
    src_xy = src_wcs.all_world2pix(sky, 0)
    sx = (src_xy[:, 0] - float(src_x0)).reshape(size_px, size_px)
    sy = (src_xy[:, 1] - float(src_y0)).reshape(size_px, size_px)

    ny, nx = src_net.shape
    in_bounds = np.isfinite(sx) & np.isfinite(sy) & (sx >= 0.0) & (sx <= nx - 1.0) & (sy >= 0.0) & (sy <= ny - 1.0)
    out_flux = np.full((size_px, size_px), np.nan, dtype=np.float64)
    out_mask = np.full((size_px, size_px), MASK_EDGE, dtype=np.uint8)
    if not np.any(in_bounds):
        return out_flux, out_mask

    sx_c = np.clip(sx, 0.0, nx - 1.0)
    sy_c = np.clip(sy, 0.0, ny - 1.0)
    x_lo = np.floor(sx_c).astype(np.int64)
    y_lo = np.floor(sy_c).astype(np.int64)
    x_hi = np.minimum(x_lo + 1, nx - 1)
    y_hi = np.minimum(y_lo + 1, ny - 1)
    fx = sx_c - x_lo
    fy = sy_c - y_lo

    corners = (
        (y_lo, x_lo, (1.0 - fy) * (1.0 - fx)),
        (y_lo, x_hi, (1.0 - fy) * fx),
        (y_hi, x_lo, fy * (1.0 - fx)),
        (y_hi, x_hi, fy * fx),
    )
    weighted_sum = np.zeros((size_px, size_px), dtype=np.float64)
    weight_sum = np.zeros((size_px, size_px), dtype=np.float64)
    for cy, cx, w in corners:
        val = src_net[cy, cx]
        m = src_mask[cy, cx]
        good = in_bounds & (m == MASK_OK) & np.isfinite(val) & (w > 0.0)
        weighted_sum = np.where(good, weighted_sum + w * val, weighted_sum)
        weight_sum = np.where(good, weight_sum + w, weight_sum)

    nx_nn = np.clip(np.rint(sx_c).astype(np.int64), 0, nx - 1)
    ny_nn = np.clip(np.rint(sy_c).astype(np.int64), 0, ny - 1)
    nn_mask = np.full((size_px, size_px), MASK_EDGE, dtype=np.uint8)
    nn_mask[in_bounds] = src_mask[ny_nn[in_bounds], nx_nn[in_bounds]]

    good_out = in_bounds & (nn_mask == MASK_OK) & (weight_sum > 0.0)
    out_flux[good_out] = weighted_sum[good_out] / weight_sum[good_out]
    out_mask[good_out] = MASK_OK
    bad_in_bounds = in_bounds & (~good_out)
    out_mask[bad_in_bounds] = np.where(
        nn_mask[bad_in_bounds] != MASK_OK, nn_mask[bad_in_bounds], MASK_IRSA_REJECTED
    )
    out_flux[~good_out] = np.nan
    return out_flux, out_mask


def extract_real_level2_cutout(
    fits_url,
    center_ra_deg,
    center_dec_deg,
    session=None,
    size_px=CUTOUT_GRID_SIZE,
    pixel_scale_arcsec=PIXEL_SCALE_ARCSEC,
    min_coverage_frac=0.25,
):
    """Fetch minimal HTTP Byte Ranges from a SPHEREx Level-2 FITS and project onto fixed TAN canvas."""
    with HttpRangeFitsReader(fits_url, session=session) as reader:
        hdus = reader.scan_hdus(required_extnames=("IMAGE", "FLAGS", "ZODI"))
        img_info = hdus["IMAGE"]
        flg_info = hdus["FLAGS"]
        zodi_info = hdus["ZODI"]

        img_hdr = img_info["header"]
        src_wcs = WCS(img_hdr, naxis=2)
        src_nx = int(img_hdr["NAXIS1"])
        src_ny = int(img_hdr["NAXIS2"])

        target_wcs = build_target_canvas_wcs(
            center_ra_deg, center_dec_deg, size_px=size_px, pixel_scale_arcsec=pixel_scale_arcsec
        )
        # Sample canvas boundary & interior points to handle arbitrary position angles safely
        edge_pts = np.linspace(0, size_px - 1, 9)
        grid_pts = np.array([(x, y) for y in edge_pts for x in edge_pts], dtype=np.float64)
        sky_pts = target_wcs.all_pix2world(grid_pts, 0)
        det_pts = src_wcs.all_world2pix(sky_pts, 0)
        finite_pts = np.isfinite(det_pts[:, 0]) & np.isfinite(det_pts[:, 1])
        inside_pts = (
            finite_pts
            & (det_pts[:, 0] >= 0.0)
            & (det_pts[:, 0] <= src_nx - 1.0)
            & (det_pts[:, 1] >= 0.0)
            & (det_pts[:, 1] <= src_ny - 1.0)
        )
        cov_frac = float(np.mean(inside_pts))
        if cov_frac < float(min_coverage_frac):
            raise CutoutCoverageError(
                f"Exposure {fits_url} covers only {cov_frac:.2%} of target cutout"
            )

        in_pts = det_pts[finite_pts]
        x0 = max(0, int(math.floor(float(np.min(in_pts[:, 0])))) - 2)
        x1 = min(src_nx, int(math.ceil(float(np.max(in_pts[:, 0])))) + 3)
        y0 = max(0, int(math.floor(float(np.min(in_pts[:, 1])))) - 2)
        y1 = min(src_ny, int(math.ceil(float(np.max(in_pts[:, 1])))) + 3)
        if x0 >= x1 or y0 >= y1:
            raise CutoutCoverageError(f"Empty clamped bounding box for {fits_url}")

        raw_img = reader.read_image_slice(img_info, y0, y1, x0, x1)
        raw_zodi = reader.read_image_slice(zodi_info, y0, y1, x0, x1)
        raw_flags = reader.read_flags_slice(flg_info, y0, y1, x0, x1)

    net = raw_img - raw_zodi
    src_mask = np.zeros(raw_flags.shape, dtype=np.uint8)
    src_mask[(raw_flags & np.uint32(IRSA_REJECTED_MASK)) != 0] |= MASK_IRSA_REJECTED
    src_mask[(raw_flags & np.uint32(OVERFLOW_MASK)) != 0] |= MASK_OVERFLOW_SATURATED
    src_mask[~np.isfinite(net) & ((src_mask & MASK_OVERFLOW_SATURATED) == 0)] |= MASK_IRSA_REJECTED

    out_flux, out_mask = reproject_patch_to_canvas(
        net,
        src_mask,
        src_wcs,
        center_ra_deg,
        center_dec_deg,
        size_px=size_px,
        pixel_scale_arcsec=pixel_scale_arcsec,
        src_x0=x0,
        src_y0=y0,
    )
    valid_px = np.isfinite(out_flux) & (out_mask == MASK_OK)
    if float(np.mean(valid_px)) < 0.05:
        raise CutoutCoverageError(f"All pixels masked/out-of-bounds in {fits_url}")
    return {
        "flux": out_flux,
        "mask": out_mask,
        "coverage_frac": cov_frac,
        "valid_frac": float(np.mean(valid_px)),
        "bunit": str(img_hdr.get("BUNIT", "MJy / sr")).strip(),
    }


def _select_visit_clusters(frames_by_det, n_visits=3):
    """Group epochs within the 6-detector overlap span into chronologically separated visit clusters."""
    non_empty = [det_rows for det_rows in frames_by_det.values() if det_rows]
    if not non_empty:
        return []
    common_lo = max(min(float(r["t_min"]) for r in rows) for rows in non_empty)
    common_hi = min(max(float(r["t_min"]) for r in rows) for rows in non_empty)
    if common_lo <= common_hi:
        all_mjds = sorted(
            float(r["t_min"])
            for rows in non_empty
            for r in rows
            if common_lo - 1e-6 <= float(r["t_min"]) <= common_hi + 1e-6
        )
    else:
        all_mjds = sorted(float(r["t_min"]) for rows in non_empty for r in rows)
    if not all_mjds:
        return []
    if len(all_mjds) < n_visits:
        return [(f"V{i + 1}", m, m) for i, m in enumerate(all_mjds)]

    arr = np.asarray(all_mjds, dtype=np.float64)
    diffs = np.diff(arr)
    # Prefer large survey cadence gaps (> 15 days between SPHEREx sky passes); else time quantiles
    big_gaps = [int(i) for i in np.argsort(diffs)[::-1] if diffs[i] > 15.0]
    if len(big_gaps) >= n_visits - 1:
        split_idx = sorted(big_gaps[: n_visits - 1])
        bounds = []
        prev = 0
        for s_idx in split_idx:
            bounds.append((prev, s_idx + 1))
            prev = s_idx + 1
        bounds.append((prev, len(arr)))
        clusters = [(f"V{i + 1}", float(arr[a]), float(arr[b - 1])) for i, (a, b) in enumerate(bounds)]
    else:
        edges = np.linspace(float(arr[0]), float(arr[-1]) + 1e-6, n_visits + 1)
        clusters = [(f"V{i + 1}", float(edges[i]), float(edges[i + 1])) for i in range(n_visits)]

    # Verify every cluster has >= 1 candidate per non-empty detector; fall back to equal-time bins if needed
    all_covered = all(
        any(lo - 1e-6 <= float(r["t_min"]) <= hi + 1e-6 for r in rows)
        for _, lo, hi in clusters
        for rows in non_empty
    )
    if not all_covered:
        edges = np.linspace(float(arr[0]), float(arr[-1]) + 1e-6, n_visits + 1)
        clusters = [(f"V{i + 1}", float(edges[i]), float(edges[i + 1])) for i in range(n_visits)]
    return clusters


def _ang_sep_deg(ra1, dec1, ra2, dec2):
    r1, d1, r2, d2 = map(math.radians, (ra1, dec1, ra2, dec2))
    a = math.sin((d2 - d1) / 2.0) ** 2 + math.cos(d1) * math.cos(d2) * math.sin((r2 - r1) / 2.0) ** 2
    return math.degrees(2.0 * math.asin(min(1.0, math.sqrt(max(0.0, a)))))


def _load_target_level2_candidates(data_real_dir, slug):
    path = os.path.join(data_real_dir, f"{slug}_spherex_frames.csv")
    if not os.path.exists(path):
        raise FileNotFoundError(f"Missing frame index CSV: {path}")
    by_det = {det: [] for det in VALID_DETECTORS}
    with open(path, encoding="utf-8", newline="") as f:
        for raw in csv.DictReader(f):
            bp = str(raw.get("energy_bandpassname", "")).strip()
            det = bp.replace("SPHEREx-", "") if bp.startswith("SPHEREx-") else bp
            if det not in DETECTOR_INDEX:
                continue
            if not raw.get("cloud_access") or not raw.get("t_min") or not raw.get("s_ra") or not raw.get("s_dec"):
                continue
            by_det[det].append(raw)
    return by_det


def _quantize_flux_and_masks(flux_cube, mask_cube):
    valid = (mask_cube == MASK_OK) & np.isfinite(flux_cube)
    if not np.any(valid):
        raise ValueError("No valid unmasked pixels extracted across target cube")
    valid_vals = flux_cube[valid]
    vmin = float(np.min(valid_vals))
    vmax = float(np.max(valid_vals))
    # Guard uint16 linear scale against isolated unflagged negative detector spikes (e.g. -2000 MJy/sr)
    q_lo = max(vmin, float(np.percentile(valid_vals, 0.02)) - 5.0)
    if q_lo >= vmax:
        q_lo = vmin
    flux_scale = float(f"{max((vmax - q_lo) / float(INVALID_U16 - 1), 1e-6):.10g}")
    flux_zero = float(f"{q_lo:.10g}")

    scaled = np.round((flux_cube - flux_zero) / flux_scale)
    scaled = np.clip(np.where(valid, scaled, INVALID_U16), 0, INVALID_U16 - 1)
    pack_u16 = np.where(valid, scaled, INVALID_U16).astype("<u2")
    mask_u8 = np.asarray(mask_cube, dtype=np.uint8)
    mask_u8[~valid & (mask_u8 == MASK_OK)] = MASK_IRSA_REJECTED
    return pack_u16, mask_u8, flux_zero, flux_scale


def _measure_d6_depth_and_rms(flux_cube, gaia_sources, center_ra_deg, center_dec_deg):
    """Estimate D6 5-sigma point-source AB depth and Gaia astrometric residual directly from cutout pixels."""
    d6_stack = detector_visit_stacks(flux_cube, detector_id="D6")
    finite_d6 = d6_stack[np.isfinite(d6_stack)]
    searched_depth = None
    if finite_d6.size >= 64:
        med = float(np.median(finite_d6))
        # Robust background noise from lower half + MAD avoids bias from bright sources
        mad = float(np.median(np.abs(finite_d6 - med)))
        sigma_mjy_sr = max(1.4826 * mad, 1e-4)
        # 5-sigma point-source sensitivity across ~4-pixel effective PSF area
        f5_uJy = 5.0 * math.sqrt(4.0) * sigma_mjy_sr * _MJY_SR_TO_UJY_PX
        searched_depth = round(23.9 - 2.5 * math.log10(max(f5_uJy, 1e-6)), 2)

    gaia_rms = None
    if gaia_sources:
        d1_stack = detector_visit_stacks(flux_cube, detector_id="D1")
        wcs = build_target_canvas_wcs(center_ra_deg, center_dec_deg)
        res_arcsec = []
        ny, nx = d1_stack.shape
        for star in gaia_sources[:20]:
            px, py = wcs.all_world2pix([[star["ra_deg"], star["dec_deg"]]], 0)[0]
            ix, iy = int(round(px)), int(round(py))
            if not (2 <= ix < nx - 2 and 2 <= iy < ny - 2):
                continue
            box = d1_stack[iy - 2 : iy + 3, ix - 2 : ix + 3]
            if not np.all(np.isfinite(box)):
                continue
            bg = float(np.median(box))
            peak = float(np.max(box)) - bg
            noise = max(float(np.median(np.abs(box - bg))) * 1.4826, 1e-4)
            if peak <= 5.0 * noise:
                continue
            sub = np.maximum(box - bg, 0.0)
            yy, xx = np.mgrid[iy - 2 : iy + 3, ix - 2 : ix + 3]
            tot = float(np.sum(sub))
            if tot <= 0.0:
                continue
            cx = float(np.sum(sub * xx) / tot)
            cy = float(np.sum(sub * yy) / tot)
            res_arcsec.append(math.hypot(cx - px, cy - py) * PIXEL_SCALE_ARCSEC)
        if res_arcsec:
            gaia_rms = round(float(math.sqrt(np.mean(np.square(res_arcsec)))), 3)

    return searched_depth, gaia_rms


def _record_data_manifest(data_manifest_path, rows):
    os.makedirs(os.path.dirname(data_manifest_path), exist_ok=True)
    existing = []
    if os.path.exists(data_manifest_path):
        with open(data_manifest_path, encoding="utf-8", newline="") as f:
            existing = [r for r in csv.DictReader(f) if r.get("name")]
    merged = {r["name"]: r for r in existing}
    for row in rows:
        merged[row["name"]] = row
    fieldnames = ["name", "bytes", "sha256", "source_url"]
    with open(data_manifest_path, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        for key in sorted(merged):
            writer.writerow({k: merged[key].get(k, "") for k in fieldnames})


def build_real_target_cutouts(
    contracts_dir=DEFAULT_CONTRACTS_DIR,
    csv_dir=DEFAULT_CSV_DIR,
    data_real_dir=DEFAULT_DATA_REAL_DIR,
    static_dir=DEFAULT_STATIC_DIR,
    data_manifest_path=os.path.join(PACKAGE_ROOT, "data", "manifest.csv"),
    session_factory=None,
    max_workers=6,
):
    """Build real 3-visit x 6-detector WCS cutouts for all 5 targets via S3 HTTP Range GETs."""
    os.makedirs(contracts_dir, exist_ok=True)
    targets = {row["target_id"]: row for row in load_targets(csv_dir)}
    now_iso = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    make_session = session_factory if session_factory is not None else HardenedHTTPSession
    manifest_records = []
    summaries = {}
    thread_local = threading.local()
    created_sessions = []
    sess_lock = threading.Lock()

    def _get_session():
        sess = getattr(thread_local, "session", None)
        if sess is None:
            sess = make_session()
            thread_local.session = sess
            with sess_lock:
                created_sessions.append(sess)
        return sess

    try:
        for tgt_id, spec in TARGET_SPECS.items():
            tgt = targets[tgt_id]
            slug = spec["slug"]
            ra_ep26, dec_ep26 = propagate_position(
                float(tgt["ra_deg_j2000"]),
                float(tgt["dec_deg_j2000"]),
                float(tgt["pm_ra_mas_yr"]),
                float(tgt["pm_dec_mas_yr"]),
                26.0,
            )
            by_det = _load_target_level2_candidates(data_real_dir, slug)
            clusters = _select_visit_clusters(by_det, n_visits=3)
            if len(clusters) != 3:
                raise RuntimeError(f"Expected 3 visit clusters for {tgt_id}, got {len(clusters)}")

            gaia_path = os.path.join(data_real_dir, f"{slug}_gaia_dr3.csv")
            gaia_sources = []
            if os.path.exists(gaia_path):
                with open(gaia_path, encoding="utf-8", newline="") as gf:
                    for gr in csv.DictReader(gf):
                        try:
                            ra16, dec16 = float(gr["ra"]), float(gr["dec"])
                        except (KeyError, ValueError, TypeError):
                            continue
                        pmr = float(gr.get("pmra") or 0.0)
                        pmd = float(gr.get("pmdec") or 0.0)
                        rag, decg = propagate_position(ra16, dec16, pmr, pmd, 10.0)
                        gaia_sources.append({"ra_deg": rag, "dec_deg": decg})

            flux_cube = np.full((3, len(VALID_DETECTORS), CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE), np.nan, dtype=np.float64)
            mask_cube = np.full((3, len(VALID_DETECTORS), CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE), MASK_EDGE, dtype=np.uint8)
            selected_mjds = [[], [], []]
            selected_exposures = []
            tasks = []

            for v_idx, (visit_id, lo_mjd, hi_mjd) in enumerate(clusters):
                mid_mjd = 0.5 * (lo_mjd + hi_mjd)
                for det_id in VALID_DETECTORS:
                    cands = [
                        r
                        for r in by_det[det_id]
                        if (lo_mjd - 1e-6 <= float(r["t_min"]) <= hi_mjd + 1e-6)
                    ]
                    if not cands:
                        # Fall back to exposures nearest cluster midpoint so uneven detector cadences still resolve
                        cands = sorted(
                            by_det[det_id],
                            key=lambda r: (
                                abs(float(r["t_min"]) - mid_mjd),
                                _ang_sep_deg(float(r["s_ra"]), float(r["s_dec"]), ra_ep26, dec_ep26),
                            ),
                        )
                    else:
                        cands.sort(
                            key=lambda r: _ang_sep_deg(float(r["s_ra"]), float(r["s_dec"]), ra_ep26, dec_ep26)
                        )
                    tasks.append((v_idx, visit_id, det_id, cands))

            def _run_cell(item):
                v_idx, visit_id, det_id, cands = item
                sess = _get_session()
                last_err = None
                for cand in cands[:8]:
                    url = resolve_s3_cloud_access_url(cand["cloud_access"])
                    try:
                        res = extract_real_level2_cutout(url, ra_ep26, dec_ep26, session=sess)
                        return v_idx, visit_id, det_id, cand, url, res
                    except (CutoutCoverageError, requests.RequestException, EOFError) as exc:
                        last_err = exc
                        continue
                raise RuntimeError(f"{tgt_id} {visit_id} {det_id} failed across candidates: {last_err}")

            with ThreadPoolExecutor(max_workers=max_workers) as pool:
                futs = [pool.submit(_run_cell, task) for task in tasks]
                for fut in as_completed(futs):
                    v_idx, visit_id, det_id, cand, url, res = fut.result()
                    d_idx = DETECTOR_INDEX[det_id]
                    flux_cube[v_idx, d_idx] = res["flux"]
                    mask_cube[v_idx, d_idx] = res["mask"]
                    selected_mjds[v_idx].append(float(cand["t_min"]))
                    selected_exposures.append(
                        {
                            "visit_id": visit_id,
                            "detector": det_id,
                            "obs_id": cand["obs_id"],
                            "obs_collection": cand.get("obs_collection", "spherex_dr1"),
                            "t_min": round(float(cand["t_min"]), 6),
                            "coverage_frac": round(res["coverage_frac"], 4),
                            "s3_url": url,
                        }
                    )

            selected_exposures.sort(key=lambda e: (e["visit_id"], DETECTOR_INDEX[e["detector"]]))
            visits_meta = []
            for v_idx in range(3):
                mjd_med = float(np.median(selected_mjds[v_idx]))
                visits_meta.append(
                    {
                        "visit_id": f"V{v_idx + 1}",
                        "epoch_iso": _mjd_to_iso(mjd_med),
                        "mjd": round(mjd_med, 4),
                        "detectors_present": list(VALID_DETECTORS),
                    }
                )

            pack_u16, mask_u8, flux_zero, flux_scale = _quantize_flux_and_masks(flux_cube, mask_cube)
            searched_depth, gaia_rms = _measure_d6_depth_and_rms(flux_cube, gaia_sources, ra_ep26, dec_ep26)

            patch_dir = contracts_dir if tgt_id == "TGT-02" else os.path.join(contracts_dir, "targets", tgt_id)
            os.makedirs(patch_dir, exist_ok=True)
            pack_bytes = pack_u16.tobytes(order="C")
            mask_bytes = mask_u8.tobytes(order="C")
            with open(os.path.join(patch_dir, "pack.bin"), "wb") as pf:
                pf.write(pack_bytes)
            with open(os.path.join(patch_dir, "mask.bin"), "wb") as mf:
                mf.write(mask_bytes)

            manifest = {
                "schema_version": "1.0.0-hour0",
                "data_as_of": now_iso,
                "pipeline_version": PIPELINE_VERSION,
                "target_id": tgt_id,
                "target_name": str(tgt["name"]),
                "cutout_origin": "real_spherex_s3_wcs_cutout",
                "center_ra_deg": round(ra_ep26, 6),
                "center_dec_deg": round(dec_ep26, 6),
                "center_epoch": "2026.0",
                "target_j2000_ra_deg": float(tgt["ra_deg_j2000"]),
                "target_j2000_dec_deg": float(tgt["dec_deg_j2000"]),
                "fov_arcmin": CUTOUT_FOV_ARCMIN,
                "cutout_size_px": [CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE],
                "pixel_scale_arcsec": PIXEL_SCALE_ARCSEC,
                "gaia_alignment_rms_arcsec": gaia_rms,
                "searched_depth_mag_d6": searched_depth,
                "visits": visits_meta,
                "source_exposures": selected_exposures,
                "pack_binary_layout": {
                    "file": "pack.bin",
                    "dtype": "uint16",
                    "endianness": "little",
                    "compression": "none",
                    "shape": [3, 6, CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE],
                    "axes_order": ["visit", "detector", "y", "x"],
                    "byte_length": len(pack_bytes),
                    "flux_unit": "MJy/sr",
                    "flux_scale": flux_scale,
                    "flux_zero": flux_zero,
                    "invalid_u16": INVALID_U16,
                },
                "quality_mask_layout": {
                    "file": "mask.bin",
                    "dtype": "uint8",
                    "compression": "none",
                    "shape": [3, 6, CUTOUT_GRID_SIZE, CUTOUT_GRID_SIZE],
                    "axes_order": ["visit", "detector", "y", "x"],
                    "byte_length": len(mask_bytes),
                    "flag_bits": {
                        "OK": MASK_OK,
                        "IRSA_REJECTED": MASK_IRSA_REJECTED,
                        "OVERFLOW_SATURATED": MASK_OVERFLOW_SATURATED,
                        "EDGE_MASKED": MASK_EDGE,
                    },
                },
            }
            manifest_bytes = (json.dumps(manifest, indent=2) + "\n").encode("utf-8")
            with open(os.path.join(patch_dir, "manifest.json"), "wb") as jf:
                jf.write(manifest_bytes)

            manifest_records.append(
                {
                    "name": f"cutouts/{tgt_id}/pack.bin",
                    "bytes": len(pack_bytes),
                    "sha256": hashlib.sha256(pack_bytes).hexdigest(),
                    "source_url": selected_exposures[0]["s3_url"],
                }
            )
            summaries[tgt_id] = {
                "target_name": manifest["target_name"],
                "valid_frac": round(float(np.mean(mask_u8 == MASK_OK)), 4),
                "rejected_px": int(np.count_nonzero((mask_u8 & MASK_IRSA_REJECTED) != 0)),
                "overflow_px": int(np.count_nonzero((mask_u8 & MASK_OVERFLOW_SATURATED) != 0)),
                "edge_px": int(np.count_nonzero((mask_u8 & MASK_EDGE) != 0)),
                "searched_depth_mag_d6": searched_depth,
                "gaia_alignment_rms_arcsec": gaia_rms,
                "visits": [v["mjd"] for v in visits_meta],
            }
    finally:
        for sess in created_sessions:
            if hasattr(sess, "close"):
                sess.close()

    if data_manifest_path:
        _record_data_manifest(data_manifest_path, manifest_records)
    if static_dir:
        build_static_fallback_js(
            out_path=os.path.join(static_dir, "fallback_data.js"),
            contracts_dir=contracts_dir,
            csv_dir=csv_dir,
            data_real_dir=data_real_dir,
        )
    return summaries


if __name__ == "__main__":
    summary = build_real_target_cutouts()
    print(json.dumps(summary, indent=2))
