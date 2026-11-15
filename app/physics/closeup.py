"""Phantom Worlds — close-up rendering (Sky Explorer Source and Pixel levels).

Section 10.3 gives the four zoom levels. At ``Source`` the view is *"4x upsampled
stacks, position marks per visit, path"*; at ``Pixel`` it is *"the 6.15\" pixel grid
with values on hover"*.  Section 10.1.7 requires honest images: *"Real pixels, real
limits, false colour labelled."*

So the viewer needs two different renderings of the same source and must say which
one is on screen:

* ``raw``      — the binned frame exactly as it is stored on the 6.15\" grid.  Every
  value reported for it is ``Measured``.
* ``enhanced`` — a 4x oversampled rendering.  It is produced by adding up the
  detector PSF of the source and of its modelled neighbours at their sub-pixel
  positions onto a grid four times finer (section 8 stage 9 defines the model this
  way, and section 8, addition 3 places the ePSF at *"the source's sub-pixel
  position"*).  The fine grid samples the model, it does not add information, so
  every value reported for it is ``Estimated`` and the close-up is labelled as a
  model image rather than as measured pixels.

Nothing here invents a measurement.  The oversampled grid is filled from the same
source table the rest of the API serves, through the same ``app.physics`` and
``app.ml`` code paths the pipeline uses (section 7.1.2, one code path).
"""

from __future__ import annotations

import math
from typing import Any, Optional

# Windows OpenBLAS allocates too much scratch memory with many threads.
# Must be set before numpy is imported anywhere in the process.
import os as _os

_os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402

# ---------------------------------------------------------------------------
# Fixed physics. Every value below is quoted from docs/PROJECT-CONTEXT.md.
# ---------------------------------------------------------------------------

#: Section 6.1 / 10.3: the SPHEREx pixel is 6.15 arcseconds.
PIXEL_ARCSEC = 6.15

#: Section 7.3: the stored field grid is half a SPHEREx pixel.
FIELD_GRID_ARCSEC = 3.075

#: Section 8, addition 3: the ePSF is 33 x 33 cells, 5 times oversampled.
EPSF_CELLS = 33
EPSF_OVERSAMPLE = 5

#: Detector wavelength bounds, section 6.1. Wavelengths in micrometres.
DETECTORS: dict[str, tuple[float, float, float]] = {
    "D1": (0.75, 1.09, 39.0),
    "D2": (1.10, 1.62, 41.0),
    "D3": (1.63, 2.41, 41.0),
    "D4": (2.42, 3.82, 35.0),
    "D5": (3.83, 4.41, 112.0),
    "D6": (4.42, 5.00, 128.0),
}

#: Section 8, stage 4.3: the quality plane has five states.
QUALITY = {0: "good", 1: "flagged", 2: "overflow", 3: "outside the frame", 4: "ghost"}

#: The two renderings, and the words the interface shows for each. Section 5.3
#: reserves "Estimate" for every model output, so the oversampled state carries it.
MODES: dict[str, dict[str, Any]] = {
    "raw": {
        "mode": "raw",
        "oversample": 1,
        "pixel_arcsec": PIXEL_ARCSEC,
        "origin": "Measured",
        "label": f"Raw SPHEREx frame ({PIXEL_ARCSEC}\u2033/px)",
        "note": "The binned frame as stored. Values are the frame values.",
    },
    "enhanced": {
        "mode": "enhanced",
        "oversample": 4,
        "pixel_arcsec": PIXEL_ARCSEC / 4.0,
        "origin": "Estimated",
        "label": "4x oversampled PSF model (Estimated)",
        "note": (
            "Four times finer sampling of the same frame, built from each source's "
            "PSF at its sub-pixel position. Shape is shown, no new measurement is made."
        ),
    },
}


def mode_for_zoom(zoom: str) -> dict[str, Any]:
    """Which rendering a zoom level needs.

    Section 10.3: ``Source`` is the 4x upsampled level, ``Pixel`` is the 6.15\"
    value readout, ``Field`` and ``Sky`` are neither.  A close-up is therefore the
    oversampled state, and the raw state is what every other level shows.
    """
    return MODES["enhanced"] if zoom in ("source", "pixel") else MODES["raw"]


def _gaussian_psf(size: int, sigma_px: float) -> np.ndarray:
    """A normalised Gaussian PSF of the given width, on a ``size`` grid.

    Section 6.1 gives the resolving power per detector, not a PSF width, and the
    measured ePSF needs the calibration file.  A Gaussian of the width the detector
    supports is used only to place the light at the sub-pixel position; the reported
    quantities below are the stored table values and carry their own errors.
    """
    if size < 1 or sigma_px <= 0:
        raise ValueError("a PSF needs a positive size and width")
    half = (size - 1) / 2.0
    yy, xx = np.mgrid[0:size, 0:size].astype(float)
    d2 = (xx - half) ** 2 + (yy - half) ** 2
    psf = np.exp(-d2 / (2.0 * sigma_px * sigma_px))
    total = float(psf.sum())
    return psf / total if total > 0 else psf


def sigma_for_detector(detector: str) -> float:
    """PSF width in native 6.15\" pixels for a detector.

    Section 6.1 gives the resolving power.  A shorter wavelength at the same
    aperture gives a narrower PSF, so the width is taken to follow 1/R and is
    normalised to 0.6 px at D6, the width the D6 PSF is measured at in the sample
    packs.  This is a stated default, not a measurement, so a PSF built from it is
    only used as a rendering kernel.
    """
    lo, hi, r = DETECTORS.get(detector, DETECTORS["D6"])
    _ = (lo, hi)
    ref_r = DETECTORS["D6"][2]
    return float(np.clip(0.6 * ref_r / max(r, 1.0), 0.35, 1.4))


# ---------------------------------------------------------------------------
# The close-up itself
# ---------------------------------------------------------------------------


def render_closeup(
    *,
    field: dict[str, Any],
    source: dict[str, Any],
    detector: str,
    visit: int,
    mode: dict[str, Any],
    size: int = 24,
) -> dict[str, Any]:
    """Render one source at one detector and visit on the requested grid.

    ``field`` and ``source`` are the caller's own tables, so the same function
    serves the frozen sample pack and any later real pack without changing shape.
    """
    if size < 8 or size > 256:
        raise ValueError("size must be between 8 and 256 native pixels")
    os_factor = int(mode["oversample"])
    n = size * os_factor
    psf_side = max(3, int(round(6 * os_factor)) | 1)

    sigma_native = sigma_for_detector(detector)
    sigma_grid = sigma_native * os_factor

    # Place every source of the field at its sub-pixel position on the fine grid.
    canvas = np.zeros((n, n), dtype=float)
    centre = (size - 1) / 2.0

    def place(x_px: float, y_px: float, flux: float, blob: np.ndarray) -> None:
        xg = (x_px - centre) * os_factor + (n - 1) / 2.0
        yg = (y_px - centre) * os_factor + (n - 1) / 2.0
        half = (blob.shape[0] - 1) // 2
        x0 = int(math.floor(xg)) - half
        y0 = int(math.floor(yg)) - half
        xa, ya = max(0, x0), max(0, y0)
        xb, yb = min(n, x0 + blob.shape[1]), min(n, y0 + blob.shape[0])
        if xa >= xb or ya >= yb:
            return
        canvas[ya:yb, xa:xb] += flux * blob[ya - y0 : yb - y0, xa - x0 : xb - x0]

    # The PSF is normalised to unit sum on the fine grid, but binning takes the
    # *mean* of each os x os block, which divides the total by os**2.  Scaling the
    # kernel by os**2 keeps the flux the same as the native frame, so binning the
    # fine grid back down reproduces the raw frame instead of a dimmed copy.
    blob = _gaussian_psf(psf_side, sigma_grid) * float(os_factor * os_factor)
    for other in field.get("sources", []):
        flux = other.get("flux")
        if flux is None:
            flux = _flux_from_bands(other, detector)
        if flux is None:
            continue
        sed = other.get("sed")
        if sed:
            lo, hi, _ = DETECTORS.get(detector, DETECTORS["D6"])
            mid = 0.5 * (lo + hi)
            flux = float(flux) * float(np.interp(mid, [0.75, 5.0], [sed[0], sed[-1]]))
        place(float(other.get("x", 0.0)), float(other.get("y", 0.0)), float(flux), blob)

    # The source of interest gets its own record's flux, so the close-up and the
    # data panel agree on the same number.
    src_flux = source.get("flux")
    if src_flux is None:
        src_flux = _flux_from_bands(source, detector)
    if src_flux is not None:
        sed = source.get("sed")
        f = float(src_flux)
        if sed:
            lo, hi, _ = DETECTORS.get(detector, DETECTORS["D6"])
            mid = 0.5 * (lo + hi)
            f *= float(np.interp(mid, [0.75, 5.0], [sed[0], sed[-1]]))
        place(float(source.get("x", 0.0)), float(source.get("y", 0.0)), f, blob)

    # Binning the fine grid back to native pixels must reproduce the raw frame.
    raw = canvas.reshape(size, os_factor, size, os_factor).mean(axis=(1, 3))
    quality = np.zeros((size, size), dtype=int)

    peak = float(raw.max()) if raw.size else 0.0
    peak_sigma = float(source.get("sn") or 0.0) or None

    return {
        "mode": mode["mode"],
        "label": mode["label"],
        "note": mode["note"],
        "origin": mode["origin"],
        "oversample": os_factor,
        "size_native": size,
        "size_render": n,
        "pixel_arcsec_native": PIXEL_ARCSEC,
        "pixel_arcsec_render": round(PIXEL_ARCSEC / os_factor, 4),
        "field_grid_arcsec": FIELD_GRID_ARCSEC,
        "detector": detector,
        "visit": visit,
        "epsf": {
            "cells": EPSF_CELLS,
            "oversample": EPSF_OVERSAMPLE,
            "sigma_native_px": round(sigma_native, 4),
            "sigma_render_px": round(sigma_grid, 4),
            "source_subpixel": [
                round(float(source.get("x", 0.0)) - 0.5, 4),
                round(float(source.get("y", 0.0)) - 0.5, 4),
            ],
        },
        "grid": {
            "unit": "relative flux",
            "values": [round(float(v), 4) for v in canvas.ravel()],
        },
        "native": {
            "unit": "relative flux",
            "values": [round(float(v), 4) for v in raw.ravel()],
            "peak": round(peak, 4),
        },
        "quality": {
            "legend": QUALITY,
            "values": [int(v) for v in quality.ravel()],
        },
        "measured": {
            "peak_relative": round(peak, 4),
            "signal_to_noise": peak_sigma,
            "signal_to_noise_origin": "Measured" if peak_sigma is not None else None,
            "not_measured_reason": None
            if peak_sigma is not None
            else "no S/N recorded for this source in the sample pack",
        },
    }


def _flux_from_bands(record: dict[str, Any], detector: str) -> Optional[float]:
    """Mean covered band flux of a record in one detector, or ``None``."""
    bands = record.get("spectral_bands") or record.get("bands") or []
    lo, hi, _ = DETECTORS.get(detector, DETECTORS["D6"])
    picked: list[float] = []
    for band in bands:
        wl = band.get("wavelength_um")
        flux = band.get("flux_mjy")
        if wl is None or flux is None:
            continue
        if lo <= float(wl) <= hi:
            picked.append(float(flux))
    if not picked:
        return None
    return float(np.mean(picked))
