"""
Phantom Worlds — molecule reading engine (T43c / Layer 1).

Implements `phantom-worlds-ml-research.md` section 3 ("Molecules: what can be
measured") on top of the frozen Layer-1 spectrum.

Two sightline modes, chosen by the caller:

* ``brown_dwarf`` (default): the brown-dwarf / cool-star convention.  Each
  spectral index is measured *against the 3.70–4.14 µm reference window*
  (Rustamkulov 2026): ``index = -2.5 log10(mean(F_feature) / mean(F_ref))``.
  Positive = absorption (flux below the reference).  Unit: magnitudes.

* ``ice``: the ice-sightline convention.  A third-degree polynomial continuum
  (``numpy.polyfit``) is fitted through the clean windows 2.53–2.72, 3.80–4.02
  and 4.90–5.01 µm, then the optical depth per band ``tau = ln(continuum/flux)``
  is integrated over the feature window in wavenumber.  For non-H2O molecules we
  also report ``N(mol)/N(H2O) x 100`` using laboratory band strengths from Gibb
  et al. 2004 (values marked ``[TO CHECK]`` and ``origin=Estimated``).

Error (both modes): each covered band is redrawn within its Gaussian flux error
``n_resample`` times (default 200) and the measurement repeated.  We report the
median index, the 16th–84th percentile range, and a signed detection
significance ``sigma = value / std(samples)``.

Refusal rules (first match wins, per section 3.5; variability -> blending ->
contamination -> coverage):

a. source is flagged variable between visits,
b. ``blend_share > 0.3``,
c. a space-craft-glow / overflow / blend-flagged band sits inside the feature
   window (section 5G, section 8),
d. fewer than three covered bands cover the feature window.

Pure ``numpy`` + ``math`` (no scipy), matching the section-13 shortlist
("Polynomial continuum fit — ``numpy.polyfit``").
"""

from __future__ import annotations

import math
import os
from dataclasses import dataclass
from typing import Optional

# Windows OpenBLAS can fail to allocate memory with many threads (see tooling
# rules).  Must be set BEFORE ``import numpy``.
os.environ.setdefault("OPENBLAS_NUM_THREADS", "1")

import numpy as np  # noqa: E402

from app.schemas import MoleculeKey, MoleculeReading, SpectralBand  # noqa: E402

# Feature definition: (label, centre µm, window lo µm, window hi µm).
# Centres/feature windows follow section 3 and the Tier-A task brief.
FEATURES: dict[MoleculeKey, tuple[str, float, float, float]] = {
    "H2O": ("Water bands", 3.05, 2.95, 3.15),
    "CH4": ("Methane dip", 3.30, 3.20, 3.65),
    "CO2": ("Carbon dioxide", 4.27, 4.18, 4.35),
    "CO": ("Carbon monoxide", 4.67, 4.55, 4.80),
}

# Brown-dwarf / cool-star reference window (Rustamkulov 2026; section 3).
REFERENCE_WINDOW: tuple[float, float] = (3.70, 4.14)

# Clean windows for the ICE polynomial continuum (section 3.1).
CLEAN_WINDOWS: list[tuple[float, float]] = [
    (2.53, 2.72),
    (3.80, 4.02),
    (4.90, 5.01),
]

# Laboratory band strengths A (cm / molecule) for the ice N/A ratio.
# Gibb et al. 2004, cited by the SPHEREx ice team.  Values are [TO CHECK].
BAND_STRENGTH_CM: dict[MoleculeKey, float] = {
    "H2O": 2.0e-16,
    "CO2": 7.6e-17,
    "CO": 1.1e-17,
}

_CONTAMINATION_FLAGS = {
    "spacecraft_glow_suspected",
    "overflow",
    "overflow_suspected",
    "blend",
}

_DEFAULT_SEED = 20261114


@dataclass
class MoleculeEngine:
    """Stateful engine bound to one source's Layer-1 spectrum."""

    bands: list[SpectralBand]
    variable_flag: bool
    blend_share: float
    sightline: str = "brown_dwarf"  # "brown_dwarf" | "ice"
    n_resample: int = 200
    seed: int = _DEFAULT_SEED

    def __post_init__(self) -> None:
        self._wl = np.array([b.wavelength_um for b in self.bands], dtype=float)
        self._flux = np.array(
            [b.flux_mjy if b.covered and b.flux_mjy is not None else np.nan for b in self.bands],
            dtype=float,
        )
        self._err = np.array(
            [b.flux_error_mjy if b.covered and b.flux_error_mjy is not None else np.nan
             for b in self.bands],
            dtype=float,
        )
        self._covered = np.array([b.covered for b in self.bands])
        self._flagged = np.array([(b.flag or "") in _CONTAMINATION_FLAGS for b in self.bands])

    # -- indexing helpers ---------------------------------------------------

    def _in_window(self, lo: float, hi: float) -> np.ndarray:
        return (self._wl >= lo) & (self._wl <= hi)

    def _feature_indices(self, mol: MoleculeKey) -> np.ndarray:
        _, _, lo, hi = FEATURES[mol]
        return np.where(self._in_window(lo, hi) & self._covered & ~np.isnan(self._flux))[0]

    def _reference_indices(self) -> np.ndarray:
        lo, hi = REFERENCE_WINDOW
        return np.where(
            self._in_window(lo, hi) & self._covered & ~self._flagged & ~np.isnan(self._flux)
        )[0]

    def _clean_indices(self) -> np.ndarray:
        """Covered, unflagged bands inside any clean (ice) window."""
        inside = np.zeros_like(self._wl, dtype=bool)
        for lo, hi in CLEAN_WINDOWS:
            inside |= self._in_window(lo, hi)
        return np.where(inside & self._covered & ~self._flagged & ~np.isnan(self._flux))[0]

    # -- continuum (ICE mode only) ------------------------------------------

    def continuum_polynomial(self, flux_override: Optional[np.ndarray] = None) -> np.poly1d:
        """3rd-degree polynomial through the clean ice windows.

        ``flux_override`` optionally supplies perturbed fluxes (one resample).
        Wavelengths are normalised for numerical stability.
        """
        idx = self._clean_indices()
        if len(idx) < 4:
            return np.poly1d([np.nan, np.nan, np.nan, np.nan])
        flux = self._flux[idx].copy() if flux_override is None else flux_override[idx]
        wl = self._wl[idx]
        wmid = float(np.median(wl))
        wscale = float(np.ptp(wl)) or 1.0
        xn = (wl - wmid) / wscale
        coeffs = np.polyfit(xn, flux, 3)
        return np.poly1d(coeffs)

    def _continuum_at(self, poly: np.poly1d, wl_arr: np.ndarray) -> np.ndarray:
        idx = self._clean_indices()
        if len(idx) < 4:
            return np.full_like(wl_arr, np.nan)
        wmid = float(np.median(self._wl[idx]))
        wscale = float(np.ptp(self._wl[idx])) or 1.0
        return poly((wl_arr - wmid) / wscale)

    # -- brown-dwarf index ---------------------------------------------------

    def _index_draw(
        self,
        mol: MoleculeKey,
        rng: np.random.Generator,
        draw: bool,
    ) -> Optional[float]:
        feat_idx = self._feature_indices(mol)
        ref_idx = self._reference_indices()
        if len(feat_idx) < 3 or len(ref_idx) < 3:
            return None

        feat_flux = self._flux[feat_idx].astype(float)
        ref_flux = self._flux[ref_idx].astype(float)
        if draw:
            feat_flux = feat_flux + rng.normal(0.0, np.nan_to_num(self._err[feat_idx], nan=0.0))
            ref_flux = ref_flux + rng.normal(0.0, np.nan_to_num(self._err[ref_idx], nan=0.0))

        f_mean = float(np.mean(feat_flux))
        r_mean = float(np.mean(ref_flux))
        if f_mean <= 0 or r_mean <= 0:
            return None
        return -2.5 * math.log10(f_mean / r_mean)

    def read_index(self, mol: MoleculeKey) -> tuple[
        Optional[float], Optional[tuple[float, float]], Optional[float]
    ]:
        """Return (value, error_16_84, sigma) for the brown-dwarf index."""
        rng = np.random.default_rng(self.seed)
        samples: list[float] = []
        for _ in range(self.n_resample):
            v = self._index_draw(mol, rng, draw=True)
            if v is not None and math.isfinite(v):
                samples.append(v)
        if len(samples) < 3:
            return None, None, None
        value = float(np.median(samples))
        lo = float(np.percentile(samples, 16))
        hi = float(np.percentile(samples, 84))
        std = float(np.std(samples))
        sigma = (value / std) if std > 0 else None
        return value, (lo, hi), sigma

    # -- ICE mode ------------------------------------------------------------

    def read_ice(self, mol: MoleculeKey) -> tuple[
        Optional[float], Optional[tuple[float, float]], Optional[float], Optional[float]
    ]:
        """Return (tau_integrated, error_16_84, sigma, pct_of_water_ice)."""
        rng = np.random.default_rng(self.seed)
        feat_idx = self._feature_indices(mol)
        if len(feat_idx) < 3:
            return None, None, None, None

        tau_samples: list[float] = []
        for _ in range(self.n_resample):
            flux = self._flux.copy()
            pert = rng.normal(0.0, np.nan_to_num(self._err, nan=0.0))
            flux = np.where(self._covered, flux + pert, flux)
            poly = self.continuum_polynomial(flux_override=flux)
            cont = self._continuum_at(poly, self._wl[feat_idx])
            f = flux[feat_idx]
            tau = np.log(cont / f)
            # Integrate over wavenumber (1/micron) using trapezoid rule.
            nu = 1.0 / self._wl[feat_idx]
            tau_int = float(np.trapz(tau, nu))
            if math.isfinite(tau_int):
                tau_samples.append(tau_int)

        if len(tau_samples) < 3:
            return None, None, None, None

        value = float(np.median(tau_samples))
        lo = float(np.percentile(tau_samples, 16))
        hi = float(np.percentile(tau_samples, 84))
        std = float(np.std(tau_samples))
        sigma = (value / std) if std > 0 else None

        pct = None
        if mol != "H2O":
            h2o_idx = self._feature_indices("H2O")
            if len(h2o_idx) >= 3:
                poly = self.continuum_polynomial()
                cont = self._continuum_at(poly, self._wl[h2o_idx])
                tau_h2o = np.log(cont / self._flux[h2o_idx])
                nu_h2o = 1.0 / self._wl[h2o_idx]
                tau_h2o_int = float(np.trapz(tau_h2o, nu_h2o))
                a_mol = BAND_STRENGTH_CM[mol]
                a_h2o = BAND_STRENGTH_CM["H2O"]
                if tau_h2o_int > 0 and a_mol > 0 and a_h2o > 0:
                    pct = (value / a_mol) / (tau_h2o_int / a_h2o) * 100.0

        return value, (lo, hi), sigma, pct

    # -- refusal logic + dispatch -------------------------------------------

    def _refusal(self, mol: MoleculeKey) -> Optional[str]:
        _, _, lo, hi = FEATURES[mol]
        if self.variable_flag:
            return "Not measured: the source varies between visits"
        if self.blend_share > 0.3:
            return f"Not measured: blended source (blend share {self.blend_share:.2f})"
        if self._flagged[self._in_window(lo, hi) & self._covered].any():
            return "Not measured: flagged/contaminated band(s) inside the feature window"
        feat_idx = self._feature_indices(mol)
        if len(feat_idx) < 3:
            return "Not measured: fewer than three bands cover the feature"
        if self.sightline == "brown_dwarf" and len(self._reference_indices()) < 3:
            return "Not measured: fewer than three bands cover the reference window"
        return None

    def read_all(self) -> list[MoleculeReading]:
        out: list[MoleculeReading] = []
        for mol in FEATURES:
            label, centre, _, _ = FEATURES[mol]
            refusal = self._refusal(mol)
            value = None
            error_16_84 = None
            sigma = None
            pct = None
            origin: str = "Measured"

            if refusal is None:
                if self.sightline == "ice":
                    value, error_16_84, sigma, pct = self.read_ice(mol)
                    origin = "Estimated" if (mol != "H2O" and pct is not None) else "Measured"
                    if value is None:
                        refusal = "Not measured: fewer than three bands cover the feature"
                else:
                    value, error_16_84, sigma = self.read_index(mol)
                    if value is None:
                        refusal = "Not measured: fewer than three bands cover the feature"

                if value is not None:
                    value = round(value, 4)
                    error_16_84 = (round(error_16_84[0], 4), round(error_16_84[1], 4))
                    sigma = round(sigma, 4) if sigma is not None else None
                    pct = round(pct, 3) if pct is not None else None

            out.append(
                MoleculeReading(
                    molecule=mol,
                    feature_label=label,
                    wavelength_um=centre,
                    value=value,
                    unit="mag" if self.sightline == "brown_dwarf" else "dimensionless",
                    error_16_84=error_16_84,
                    sigma=sigma,
                    origin=origin,  # type: ignore[arg-type]
                    pct_of_water_ice=pct,
                    refusal_reason=refusal,
                )
            )
        return out