"""Feature extraction shared by E2 (trees), M1 (artefact gate) and M3 (isolation).

Feature engineering follows `phantom-worlds-ml-research.md` section 5B/E and
13.2.  Three input sets are materialised from each source's Layer-1 spectrum:

* ``spectrum`` — the 102 bands, mean-normalised, with a coverage summary.  NaN
  marks uncovered/flagged bands, which XGBoost handles natively.
* ``indices`` — layer-1 molecule indices (H2O, CH4, CO2, CO) plus a few
  broadband slopes / colours, with NaNs where a reading is refused.
* ``survey`` — Gaia/WISE astrometry: parallax, distance, absolute magnitude,
  tangential speed, reduced proper motion, and non-detection flags.

The optional ``RealSource`` payload carries the frozen survey flags from the
benchmark pack so ``all_data`` (E1..E7) can be trained and evaluated.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Optional

import numpy as np

from app.ml import constants as C
from app.schemas import MoleculeReading, Readings, SpectralBand


@dataclass
class RealSurvey:
    """Frozen survey-derived inputs attached to a benchmark target."""

    gaia_match: bool = False
    neowise_match: bool = False
    catwise_match: bool = False
    two_mass_match: bool = False
    solar_system_object: bool = False
    simbad_type: Optional[str] = None
    splices_class: Optional[str] = None


@dataclass
class SourceFeatures:
    """One source, flattened into model-ready feature vectors."""

    spectrum: np.ndarray          # (102,) mean-normalised bands, NaN where uncovered
    coverage: np.ndarray          # (102,) bool
    indices: dict[str, float]     # molecule indices (mag), NaN where refused
    survey: dict[str, float]      # astrometry + non-detection flags
    errors: Optional[np.ndarray] = None   # (102,) 1-sigma flux errors, mean-normalised

    # Feature matrices, materialised on demand.
    _spectrum_vec: Optional[np.ndarray] = None
    _all_vec: Optional[np.ndarray] = None

    # -- spectra -------------------------------------------------------------

    @staticmethod
    def spectrum_vector(bands: list[SpectralBand]) -> np.ndarray:
        """Mean-normalised 102-band flux with NaN for uncovered/flagged bins.

        Equal to section 5B "102 bands divided by their mean, with errors and
        a coverage mask" (the baseline that matched learned embeddings within a
        point in the published star/galaxy study).
        """
        flux = np.array(
            [b.flux_mjy if (b.covered and b.flux_mjy is not None) else np.nan for b in bands],
            dtype=float,
        )
        flagged = np.array([(b.flag or "") in C.CONTAMINATION_FLAGS for b in bands])
        flux[flagged] = np.nan
        mean = np.nanmean(flux) if np.isfinite(flux).any() else 0.0
        norm = flux / mean if mean > 0 else flux
        return norm

    @staticmethod
    def coverage_vector(bands: list[SpectralBand]) -> np.ndarray:
        return np.array([b.covered for b in bands], dtype=bool)

    # -- indices -------------------------------------------------------------

    @staticmethod
    def molecule_indices(molecules: list[MoleculeReading]) -> dict[str, float]:
        out: dict[str, float] = {}
        for m in molecules:
            v = np.nan if m.value is None else float(m.value)
            out[m.molecule] = v
        return out

    @staticmethod
    def broadband_indices(bands: list[SpectralBand]) -> dict[str, float]:
        """A few synthetic broadband colours for the trees (NaN-safe)."""
        flux = np.array(
            [b.flux_mjy if (b.covered and b.flux_mjy is not None) else np.nan for b in bands],
            dtype=float,
        )
        wl = np.array(C.WAVELENGTHS_UM, dtype=float)
        out: dict[str, float] = {}

        def band_mean(lo: float, hi: float) -> float:
            m = (wl >= lo) & (wl <= hi) & np.isfinite(flux)
            return float(np.nan) if not m.any() else float(np.mean(flux[m]))

        j = band_mean(1.11, 1.35)
        h = band_mean(1.50, 1.80)
        k = band_mean(2.00, 2.40)
        d5 = band_mean(3.85, 4.40)
        d6 = band_mean(4.40, 5.00)
        out["j_h"] = _colour(j, h)
        out["h_k"] = _colour(h, k)
        out["k_d5"] = _colour(k, d5)
        out["d5_d6"] = _colour(d5, d6)
        return out

    # -- construction --------------------------------------------------------

    @classmethod
    def from_readings(cls, readings: Readings, survey: Optional[RealSurvey] = None) -> "SourceFeatures":
        spectrum = cls.spectrum_vector(readings.spectral_bands)
        coverage = cls.coverage_vector(readings.spectral_bands)

        # Molecule indices come from the *authoritative* Step-2 engine, not the
        # frozen ``readings.molecules`` snapshot (which still carries Step-1
        # placeholder "refused" values).  The engine recomputes CH4/CO2/CO/H2O
        # on the fly from the 102-band spectrum.
        from app.physics.molecules import MoleculeEngine

        engine = MoleculeEngine(
            bands=readings.spectral_bands,
            variable_flag=readings.variable_flag,
            blend_share=readings.blend_share,
            sightline="brown_dwarf",
            n_resample=50,
        )
        indices = cls.molecule_indices(engine.read_all())
        indices.update(cls.broadband_indices(readings.spectral_bands))

        # Mean-normalised 1-sigma errors, aligned to ``spectrum``.
        errors = np.array(
            [b.flux_error_mjy if (b.covered and b.flux_error_mjy is not None) else np.nan
             for b in readings.spectral_bands],
            dtype=float,
        )
        with np.errstate(invalid="ignore"):
            errors = errors / np.abs(spectrum)

        srv = cls.survey_from_readings(readings, survey)
        return cls(spectrum=spectrum, coverage=coverage, indices=indices, survey=srv, errors=errors)

    @classmethod
    def from_raw_spectrum(
        cls,
        flux: np.ndarray,
        err: Optional[np.ndarray] = None,
        covered: Optional[np.ndarray] = None,
        survey: Optional[RealSurvey] = None,
        variable_flag: bool = False,
        blend_share: float = 0.0,
    ) -> "SourceFeatures":
        """Build features from a raw 102-band synthetic spectrum.

        Runs the same ``MoleculeEngine`` used for the benchmark targets so the
        training features carry *real* molecular indices, not NaNs.  This is
        what lets E2 learn that a methane dip separates an ultracool dwarf from
        a star.
        """
        from app.physics.molecules import MoleculeEngine
        import app.schemas as S

        flux = np.asarray(flux, dtype=float)
        if err is None:
            err = np.abs(flux) * 0.05 + 1e-6
        err = np.asarray(err, dtype=float)
        if covered is None:
            covered = np.ones(len(flux), dtype=bool) & np.isfinite(flux)
        covered = np.asarray(covered, dtype=bool)

        bands: list[SpectralBand] = []
        for i, wl in enumerate(C.WAVELENGTHS_UM):
            ok = bool(covered[i]) and np.isfinite(flux[i]) and np.isfinite(err[i])
            bands.append(
                S.SpectralBand(
                    index=i, wavelength_um=wl,
                    flux_mjy=float(flux[i]) if ok else None,
                    flux_error_mjy=float(err[i]) if ok else None,
                    covered=ok, band_name=C.DETECTORS[i], flag=None,
                )
            )

        # Molecule indices via the real engine (brown-dwarf convention).
        engine = MoleculeEngine(
            bands=bands, variable_flag=variable_flag, blend_share=blend_share,
            sightline="brown_dwarf", n_resample=50,
        )
        mols = engine.read_all()
        indices = cls.molecule_indices(mols)
        indices.update(cls.broadband_indices(bands))

        # Mean-normalised band/error vectors.
        spec = cls.spectrum_vector(bands)
        with np.errstate(invalid="ignore"):
            err_norm = err / np.abs(np.where(np.isfinite(flux), flux, np.nan))

        srv = survey_dict(survey) if survey is not None else cls._empty_survey()
        return cls(spectrum=spec, coverage=covered, indices=indices, survey=srv, errors=err_norm)

    @staticmethod
    def _empty_survey() -> dict[str, float]:
        return {k: np.nan for k in (
            "parallax_mas", "distance_pc", "absolute_magnitude_g",
            "tangential_velocity_km_s", "pm_total_mas_yr", "ruwe",
            "parallax_significance", "reduced_proper_motion", "blend_share",
            "variable_flag", "gaia_match", "neowise_match", "catwise_match",
            "two_mass_match", "solar_system_object", "simbad_has_type",
            "splices_has_class",
        )}

    @staticmethod
    def survey_from_readings(readings: Readings, survey: Optional[RealSurvey] = None) -> dict[str, float]:
        g = readings.gaia
        out: dict[str, float] = {
            "parallax_mas": float(g.parallax_mas) if g and g.parallax_mas is not None else np.nan,
            "distance_pc": float(g.distance_pc) if g and g.distance_pc is not None else np.nan,
            "absolute_magnitude_g": float(g.absolute_magnitude_g) if g and g.absolute_magnitude_g is not None else np.nan,
            "tangential_velocity_km_s": float(g.tangential_velocity_km_s) if g and g.tangential_velocity_km_s is not None else np.nan,
            "pm_total_mas_yr": float(g.pm_total_mas_yr) if g and g.pm_total_mas_yr is not None else np.nan,
            "ruwe": float(g.ruwe) if g and g.ruwe is not None else np.nan,
            "parallax_significance": float(g.parallax_significance) if g and g.parallax_significance is not None else np.nan,
            "reduced_proper_motion": _reduced_pm(readings),
            "blend_share": float(readings.blend_share),
            "variable_flag": float(bool(readings.variable_flag)),
        }
        if survey is not None:
            out.update(
                {
                    "gaia_match": float(survey.gaia_match),
                    "neowise_match": float(survey.neowise_match),
                    "catwise_match": float(survey.catwise_match),
                    "two_mass_match": float(survey.two_mass_match),
                    "solar_system_object": float(survey.solar_system_object),
                    "simbad_has_type": float(survey.simbad_type is not None),
                    "splices_has_class": float(survey.splices_class is not None),
                }
            )
        else:
            for k in (
                "gaia_match", "neowise_match", "catwise_match", "two_mass_match",
                "solar_system_object", "simbad_has_type", "splices_has_class",
            ):
                out[k] = np.nan
        return out

    # -- vectors -------------------------------------------------------------

    def spectrum_vector_full(self) -> np.ndarray:
        """spectrum_alone features: 102 bands + coverage fraction + indices."""
        coverage_frac = np.array([float(self.coverage.mean())])
        idx = np.array([self.indices.get(k, np.nan) for k in ("H2O", "CH4", "CO2", "CO", "j_h", "h_k", "k_d5", "d5_d6")])
        return np.concatenate([self.spectrum, coverage_frac, idx])

    def all_vector_full(self) -> np.ndarray:
        """all_data features: spectrum_alone + survey block."""
        srv_keys = [
            "parallax_mas", "distance_pc", "absolute_magnitude_g",
            "tangential_velocity_km_s", "pm_total_mas_yr", "ruwe",
            "parallax_significance", "reduced_proper_motion", "blend_share",
            "variable_flag", "gaia_match", "neowise_match", "catwise_match",
            "two_mass_match", "solar_system_object", "simbad_has_type",
            "splices_has_class",
        ]
        srv = np.array([self.survey.get(k, np.nan) for k in srv_keys])
        return np.concatenate([self.spectrum_vector_full(), srv])


def _colour(m1: float, m2: float) -> float:
    if not math.isfinite(m1) or not math.isfinite(m2) or m1 <= 0 or m2 <= 0:
        return float(np.nan)
    return -2.5 * math.log10(m1 / m2)


def survey_dict(survey: "RealSurvey") -> dict[str, float]:
    """Flatten a RealSurvey into the survey-feature block."""
    return {
        "gaia_match": float(survey.gaia_match),
        "neowise_match": float(survey.neowise_match),
        "catwise_match": float(survey.catwise_match),
        "two_mass_match": float(survey.two_mass_match),
        "solar_system_object": float(survey.solar_system_object),
        "simbad_has_type": float(survey.simbad_type is not None),
        "splices_has_class": float(survey.splices_class is not None),
    }


def _reduced_pm(readings: Readings) -> float:
    g = readings.gaia
    if g is None or g.pm_total_mas_yr is None or g.phot_g_mean_mag is None:
        return float(np.nan)
    pm_arcsec_yr = g.pm_total_mas_yr / 1000.0
    if pm_arcsec_yr <= 0:
        return float(np.nan)
    return g.phot_g_mean_mag + 5.0 + 5.0 * math.log10(pm_arcsec_yr)