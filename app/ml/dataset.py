"""Synthetic training & template library generator.

Produces a deterministic, physically-shaped 102-band corpus for the six Level-1
classes (plus artefact spectra for M1), with:

* realistic continuum + molecular feature templates per class,
* ultracool-dwarf subtypes L0..Y1 (47-subtype ladder collapsed from the SPIFF
  convention; every subtype maps to a distinct template),
* a 60/20/20 train/calibrate/test split grouped by sky tile (section 5H.1),
* ``Gold`` vs ``Silver`` label grades (Silver == 0.5 training weight,
  Gold-only evaluation, section 4 label rules).

This corpus exists so the E1..E7 pipeline can be exercised end-to-end offline;
the same interfaces accept the SPIFF Zenodo / SPLICES tables later (see the
``append_external`` hooks at the bottom).
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Optional

import numpy as np

from app.ml import constants as C


# ---------------------------------------------------------------------------
# Physical spectrum builders
# ---------------------------------------------------------------------------

# Planck shape in arbitrary flux units, lambda in microns.
_HC_OVER_KB_UM_K = 14388.0  # h c / k_b, micron.Kelvin


def _blackbody(wl: np.ndarray, t_kelvin: float) -> np.ndarray:
    x = _HC_OVER_KB_UM_K / (wl * t_kelvin)
    x = np.clip(x, 1e-3, 50.0)  # avoid overflow
    body = (wl ** -5.0) / (np.expm1(x))
    return body / body.max()


def _powerlaw(wl: np.ndarray, alpha: float) -> np.ndarray:
    """F_lambda ~ lambda^-alpha, normalised to max 1."""
    base = wl ** (-alpha)
    return base / base.max()


def _gaussian(wl: np.ndarray, centre: float, width: float, strength: float) -> np.ndarray:
    """A gaussian feature: negative=absorption, positive=emission."""
    return strength * np.exp(-0.5 * ((wl - centre) / width) ** 2)


# Central wavelengths of the molecular / emission features (section 3).
_H2O_C = 3.05
_CH4_C = 3.30
_CO2_C = 4.27
_CO_C = 4.67
_XCN_C = 4.62
_PAH_C = 3.28
_H_PAA_C = 1.875
_H_BRA_C = 4.05


def _molecule_dips(wl: np.ndarray, h2o: float, ch4: float, co2: float, co: float, xcn: float) -> np.ndarray:
    """Total absorption from the ice/cool-star molecular features."""
    dip = np.zeros_like(wl)
    dip += _gaussian(wl, _H2O_C, 0.25, h2o)
    dip += _gaussian(wl, _CH4_C, 0.30, ch4)
    dip += _gaussian(wl, _CO2_C, 0.15, co2)
    dip += _gaussian(wl, _CO_C, 0.15, co)
    dip += _gaussian(wl, _XCN_C, 0.10, xcn)
    return dip


def _emission_lines(wl: np.ndarray, pah: float, p_alpha: float, br_alpha: float) -> np.ndarray:
    """Emission features for galaxies / AGN (PAH 3.28, H lines)."""
    em = np.zeros_like(wl)
    em += _gaussian(wl, _PAH_C, 0.10, pah)
    em += _gaussian(wl, _H_PAA_C, 0.05, p_alpha)
    em += _gaussian(wl, _H_BRA_C, 0.05, br_alpha)
    return em


# Subtype lattice: index -> (effective temp, CH4 depth, H2O depth, CO depth,
#                           D1-D4 covered?, D1-D4 flux level)
def _subtype_params(subtype: str) -> dict[str, float]:
    """Continuity along the L0..Y1 ladder (from literature relations)."""
    idx = C.subtype_index(subtype)
    n = len(C.ULTRA_COOL_SUBTYPES) - 1  # 21
    frac = idx / n  # 0 = L0, 1 = Y1

    temp = 2400.0 - frac * 2000.0       # ~2400K (L0) -> ~400K (Y1)
    # Molecular absorption depths grow strongly toward the cool subtypes; the
    # depth values are set so the 3.70-4.14 um reference window *exceeds* the
    # CH4 feature window -> a positive "dip" index (cf. Epsilon Indi B, +0.6 mag).
    ch4 = 0.30 + frac * 0.55            # grows with coolness
    h2o = 0.10 + frac * 0.30
    co = 0.05 + frac * 0.25
    # D1-D4 darken dramatically toward the Y dwarfs.
    d1d4_level = max(0.05, 1.0 - frac * 1.35)
    d1d4_covered = frac < 0.85          # Y0/Y1 mostly lose optical detection
    return {
        "temp": temp,
        "ch4": ch4,
        "h2o": h2o,
        "co": co,
        "d1d4_level": d1d4_level,
        "d1d4_covered": d1d4_covered,
    }


def make_spectrum(
    label: str,
    rng: np.random.Generator,
    subtype: Optional[str] = None,
    relative_error: float = 0.05,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Return (flux, err, covered, flags) for one 102-band synthetic source.

    ``flux`` is in arbitrary units (the templates and E1 solve scale, so the
    absolute level does not matter); ``err`` uses the 3-8% SPHEREx floors
    (fact 3); ``covered`` is all-True except for optically-invisible Y dwarfs;
    ``flags`` report spacecraft glow when only D5/D6 survive.
    """
    wl = np.array(C.WAVELENGTHS_UM, dtype=float)
    n = len(wl)
    covered = np.ones(n, dtype=bool)
    flags = np.zeros(n, dtype=np.int8)  # 0 clean, 1 glow, 2 spike, 3 ghost

    if label == "Ultracool dwarf":
        subtype = subtype or "T4"
        p = _subtype_params(subtype)
        # A cool ultra-cool dwarf shows a fairly *flat* near-IR continuum (the
        # Rayleigh-Jeans tail flattens in F_lambda) carved by strong molecular
        # absorption.  This flat base is what makes the molecule index come out
        # POSITIVE — the feature sits below the 3.70-4.14 um reference — exactly
        # like the frozen Epsilon Indi B spectrum (+0.60 mag CH4).  A steep
        # blackbody would instead give a false *negative* index.
        continuum = np.ones_like(wl)
        dips = _molecule_dips(wl, p["h2o"], p["ch4"], 0.0, p["co"], 0.0)
        flux = continuum * (1.0 - dips)
        # Optical (D1-D4) faintness scale.
        d1d4 = wl < 3.8
        flux[d1d4] *= p["d1d4_level"]
        if not p["d1d4_covered"]:
            covered[d1d4] = False
            flags[d1d4] = 3  # "ghost" sentinel => flagged out; see below
        # D5/D6 glow marker for the coldest subtypes.
        if "Y" in subtype:
            flags[wl >= 4.0] = 1

    elif label == "Star":
        # Main-sequence stars: hot stars peak blueward of the SPHEREx band, so
        # their F_lambda in 0.75-5 um is a smooth red power law (the
        # Rayleigh-Jeans tail), matching the frozen Barnard's Star spectrum
        # (lambda^-1.8).  The slope varies with temperature: hotter -> shallower,
        # cooler M dwarfs -> steeper.  No methane.
        alpha = rng.uniform(1.3, 2.8)
        continuum = _powerlaw(wl, alpha)
        # Weak water + weak CO; no methane.
        dips = _molecule_dips(wl, 0.10, 0.0, 0.0, 0.03, 0.0)
        flux = continuum * (1.0 - dips)

    elif label == "Young star":
        # Photosphere + warm dust, and an ice/dust absorption complex.  The
        # continuum is flat-ish (reddened photosphere), so the ice features
        # (H2O, CO2, CO) read as positive absorption.
        continuum = np.ones_like(wl) + 0.4 * np.exp(-((wl - 1.2) / 0.9) ** 2)
        dips = _molecule_dips(wl, 0.45, 0.05, 0.35, 0.30, 0.25)
        flux = continuum * (1.0 - dips)

    elif label == "Evolved giant star":
        # A cool evolved giant (Mira / RGB) in the near-IR has a fairly flat,
        # red continuum dominated by strong H2O and CO absorption (the CO bands
        # are the classic giant signature).  Like the UCD, the flat base makes
        # the CO index come out positive and large.
        continuum = np.ones_like(wl)
        dips = _molecule_dips(wl, 0.30, 0.0, 0.05, 0.55, 0.0)
        flux = continuum * (1.0 - dips)

    elif label == "Galaxy":
        # Composite stellar population + PAH and hydrogen emission, plus the
        # 4000 A break and a redder near-IR continuum.  Without a distinct
        # shape the galaxy template is a near-copy of a blackbody star
        # (cosine ~0.995) and E1 cannot separate them; the emission complex and
        # the flux tilt are what a real spectrum provides.
        t1 = rng.uniform(4000.0, 7000.0)
        t2 = rng.uniform(7000.0, 15000.0)
        continuum = 0.7 * _blackbody(wl, t1) + 0.3 * _blackbody(wl, t2)
        # Red continuum tilt (dust reddening) across the SPHEREx range.
        continuum = continuum * (wl / 1.5) ** rng.uniform(0.4, 1.2)
        em = _emission_lines(wl, pah=rng.uniform(0.25, 0.70),
                             p_alpha=rng.uniform(0.05, 0.20),
                             br_alpha=rng.uniform(0.05, 0.20))
        # Blueward 4000 A break: a step in the D1/D2 region.
        brk = np.where(wl < 1.11, rng.uniform(0.35, 0.65), 1.0)
        flux = continuum * (1.0 + em) * brk

    elif label == "Active galaxy or quasar":
        # Power-law continuum +/- reddening, broad emission lines, and a
        # strong blue tilt (inverted relative to the red galaxy population).
        alpha = rng.uniform(0.3, 1.5)
        continuum = _powerlaw(wl, alpha) * (wl / 1.5) ** rng.uniform(-1.4, -0.6)
        em = _emission_lines(wl, pah=0.0,
                             p_alpha=rng.uniform(0.35, 1.10),
                             br_alpha=rng.uniform(0.15, 0.45))
        redden = rng.uniform(0.0, 0.4)
        flux = continuum * (1.0 + em) * (1.0 + redden * (wl / 5.0) ** -1.0)

    else:  # pragma: no cover - defensive
        flux = _blackbody(wl, 5000.0)

    # Flux floor + photon noise around the 3-8% systematic floors.
    flux = np.clip(flux, 1e-6, None)
    err = flux * relative_error + 1e-6 * flux.max()
    noise = rng.normal(0.0, err)
    flux = flux + noise

    # Map sentinel flags back to named strings.
    flag_names = np.array(["", "spacecraft_glow_suspected", "overflow_suspected", "non_detection_upper_limit"], dtype=object)
    return flux, err, covered, flag_names[flags]


# ---------------------------------------------------------------------------
# Dataset container
# ---------------------------------------------------------------------------


@dataclass
class SyntheticDataset:
    """A labelled corpus plus its train/calibrate/test split."""

    spectra: np.ndarray                 # (N, 102) unnormalised flux
    errors: np.ndarray                  # (N, 102)
    covered: np.ndarray                 # (N, 102) bool
    y: np.ndarray                       # (N,) int -> CLASS_TO_INT
    grade: np.ndarray                   # (N,) 1=Gold, 0=Silver
    weight: np.ndarray                  # (N,) training weight (1.0 / 0.5)
    sky_tile: np.ndarray                # (N,) int
    subtype: np.ndarray                 # (N,) object: subtype str or None
    levels: list[str] = field(default_factory=lambda: list(C.LEVEL1_CLASSES))

    # artefact corpus for M1: spectra labelled real(1) vs artefact(0).
    artefact_spectra: np.ndarray = field(default_factory=lambda: np.empty((0, 102)))
    artefact_errors: np.ndarray = field(default_factory=lambda: np.empty((0, 102)))
    artefact_y: np.ndarray = field(default_factory=lambda: np.empty((0,), dtype=int))
    artefact_kind: list[str] = field(default_factory=list)

    @property
    def n(self) -> int:
        return int(self.spectra.shape[0])

    @property
    def class_names(self) -> list[str]:
        return self.levels

    def as_real_artefact(self) -> tuple[np.ndarray, np.ndarray]:
        """Concatenate real (label 1) + artefact (label 0) spectra for M1."""
        X_real = self.spectra
        y_real = np.ones(len(X_real), dtype=int)
        X = np.concatenate([X_real, self.artefact_spectra], axis=0)
        y = np.concatenate([y_real, self.artefact_y], axis=0)
        return X, y

    # -- splits --------------------------------------------------------------

    def split_indices(self) -> dict[str, np.ndarray]:
        """Grouped train/60 calibrate/20 test/20 by sky tile (section 5H.1)."""
        tiles = np.unique(self.sky_tile)
        rng = np.random.default_rng(C.SEED)
        perm = rng.permutation(tiles)
        n_train = max(1, int(round(len(tiles) * 0.6)))
        n_cal = max(1, int(round(len(tiles) * 0.2)))
        train_tiles = set(perm[:n_train].tolist())
        cal_tiles = set(perm[n_train:n_train + n_cal].tolist())
        test_tiles = set(perm[n_train + n_cal:].tolist())
        train = np.where(np.isin(self.sky_tile, list(train_tiles)))[0]
        cal = np.where(np.isin(self.sky_tile, list(cal_tiles)))[0]
        test = np.where(np.isin(self.sky_tile, list(test_tiles)))[0]
        return {"train": train, "calibrate": cal, "test": test}

    def gold_test_indices(self) -> np.ndarray:
        idx = self.split_indices()["test"]
        return idx[self.grade[idx] == 1]

    # -- templates -----------------------------------------------------------

    def class_templates(self, indices: np.ndarray) -> dict[str, np.ndarray]:
        """Mean spectrum per class over the given subset (mean-normalised)."""
        out: dict[str, np.ndarray] = {}
        for c in self.levels:
            ci = C.CLASS_TO_INT[c]
            m = self.y[indices] == ci
            if not m.any():
                continue
            tmpl = self._normalise(np.nanmean(self.spectra[indices][m], axis=0))
            out[c] = tmpl
        return out

    def subtype_templates(self, indices: np.ndarray) -> dict[str, np.ndarray]:
        """One template per ultracool subtype L0..Y1."""
        uc = C.CLASS_TO_INT["Ultracool dwarf"]
        m = (self.y[indices] == uc)
        out: dict[str, np.ndarray] = {}
        for sub in C.ULTRA_COOL_SUBTYPES:
            sm = m & (self.subtype[indices] == sub)
            if not sm.any():
                continue
            out[sub] = self._normalise(np.nanmean(self.spectra[indices][sm], axis=0))
        return out

    @staticmethod
    def _normalise(vec: np.ndarray) -> np.ndarray:
        m = vec.mean()
        return vec / m if m > 0 else vec


# ---------------------------------------------------------------------------
# Artefact builders (M1 training labels)
# ---------------------------------------------------------------------------


def _artifact_spectra(rng: np.random.Generator, n: int) -> tuple[np.ndarray, np.ndarray, list[str]]:
    wl = np.array(C.WAVELENGTHS_UM)
    specs = []
    errs = []
    kinds = []
    for _ in range(n):
        kind = rng.choice(["cosmic_ray", "ghost", "glow"], p=[0.4, 0.3, 0.3])
        base = _blackbody(wl, rng.uniform(3500.0, 6000.0))
        err = base * 0.05 + 1e-6
        if kind == "cosmic_ray":
            # A few wildly bright contiguous bins.
            idx = int(rng.integers(10, 90))
            width = int(rng.integers(1, 4))
            spec = base.copy()
            for j in range(idx, min(idx + width, 102)):
                spec[j] *= rng.uniform(30.0, 500.0)
        elif kind == "ghost":
            # Faint offset copy (a low-amplitude shifted continuum + spike).
            shift = int(rng.integers(-30, 30))
            spec = base + 0.05 * np.roll(base, shift)
            spec[int(rng.integers(0, 100))] *= 20.0
        else:  # glow
            # Elevated, noisy D5/D6.
            spec = base.copy()
            spec[wl >= 4.0] += base[wl >= 4.0] * rng.uniform(1.5, 4.0)
            spec = spec + rng.normal(0.0, err * 3.0)
        spec = spec + rng.normal(0.0, err)
        specs.append(spec)
        errs.append(err)
        kinds.append(kind)
    return np.array(specs), np.array(errs), kinds


# ---------------------------------------------------------------------------
# Generator entrypoint
# ---------------------------------------------------------------------------


def generate_dataset(
    seed: int = C.SEED,
    per_class: Optional[dict[str, int]] = None,
    n_artefacts: int = 300,
    n_tiles: int = 20,
) -> SyntheticDataset:
    """Build the deterministic synthetic corpus (600+ real spectra)."""
    rng = np.random.default_rng(seed)
    per_class = per_class or {
        "Star": 130,
        "Ultracool dwarf": 160,
        "Young star": 110,
        "Evolved giant star": 110,
        "Galaxy": 110,
        "Active galaxy or quasar": 110,
    }

    spectra: list[np.ndarray] = []
    errors: list[np.ndarray] = []
    covered: list[np.ndarray] = []
    y: list[int] = []
    grade: list[int] = []
    subtype: list[Optional[str]] = []
    tiles: list[int] = []

    for cls in C.LEVEL1_CLASSES:
        ci = C.CLASS_TO_INT[cls]
        n_cls = per_class[cls]
        for k in range(n_cls):
            # Subtypes for ultracool dwarfs; None elsewhere.
            sub: Optional[str] = None
            if cls == "Ultracool dwarf":
                sub = C.ULTRA_COOL_SUBTYPES[k % len(C.ULTRA_COOL_SUBTYPES)]
            flux, err, cov, _ = make_spectrum(cls, rng, subtype=sub)
            spectra.append(flux)
            errors.append(err)
            covered.append(cov)
            y.append(ci)
            subtype.append(sub)

            # Grade: ultracool dwarfs are SPIFF Gold; other types get a Silver
            # minority that trains at half weight and never counts in eval.
            g = 1
            if cls != "Ultracool dwarf" and k % 5 == 4:
                g = 0
            grade.append(g)
            tiles.append(int(rng.integers(0, n_tiles)))

    spec_arr = np.array(spectra)
    err_arr = np.array(errors)
    cov_arr = np.array(covered, dtype=bool)
    y_arr = np.array(y, dtype=int)
    grade_arr = np.array(grade, dtype=int)
    weight_arr = np.where(grade_arr == 1, 1.0, 0.5)
    sub_arr = np.array(subtype, dtype=object)
    tile_arr = np.array(tiles, dtype=int)

    art_spec, art_err, art_kind = _artifact_spectra(rng, n_artefacts)
    art_y = np.zeros(len(art_spec), dtype=int)

    return SyntheticDataset(
        spectra=spec_arr,
        errors=err_arr,
        covered=cov_arr,
        y=y_arr,
        grade=grade_arr,
        weight=weight_arr,
        sky_tile=tile_arr,
        subtype=sub_arr,
        artefact_spectra=art_spec,
        artefact_errors=art_err,
        artefact_y=art_y,
        artefact_kind=art_kind,
    )


# ---------------------------------------------------------------------------
# External ingestion hooks (SPIFF Zenodo / SPLICES) — placeholders
# ---------------------------------------------------------------------------


def append_external(
    dataset: SyntheticDataset,
    spectra: np.ndarray,
    errors: np.ndarray,
    labels: list[str],
    grades: list[int],
    subtypes: Optional[list[Optional[str]]] = None,
) -> SyntheticDataset:
    """Attach externally-supplied (real) spectra + labels to a corpus.

    ``spectra`` should be (N, 102) on the canonical grid; the caller is
    responsible for resampling/coverage.  This is the seam the SPIFF Zenodo
    ``10.5281/zenodo.19051216`` and the SPLICES tables plug into.
    """
    if len(spectra) == 0:
        return dataset
    y_ints = np.array([C.CLASS_TO_INT[c] for c in labels], dtype=int)
    sub = np.array(subtypes if subtypes else [None] * len(labels), dtype=object)
    cov = np.ones_like(spectra, dtype=bool)
    cov[np.isnan(spectra)] = False
    spectra = np.nan_to_num(spectra)
    errors = np.nan_to_num(errors, nan=np.nanmean(np.abs(errors)) or 0.01)

    rng = np.random.default_rng(C.SEED)
    dataset.spectra = np.concatenate([dataset.spectra, spectra], axis=0)
    dataset.errors = np.concatenate([dataset.errors, errors], axis=0)
    dataset.covered = np.concatenate([dataset.covered, cov], axis=0)
    dataset.y = np.concatenate([dataset.y, y_ints], axis=0)
    dataset.grade = np.concatenate([dataset.grade, np.array(grades, dtype=int)], axis=0)
    dataset.weight = np.concatenate([dataset.weight, np.where(np.array(grades) == 1, 1.0, 0.5)], axis=0)
    dataset.subtype = np.concatenate([dataset.subtype, sub], axis=0)
    dataset.sky_tile = np.concatenate([dataset.sky_tile, rng.integers(0, 20, size=len(labels))], axis=0)
    return dataset